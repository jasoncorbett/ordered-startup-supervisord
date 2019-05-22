from __future__ import print_function

import logging

from supervisor import events
from supervisor.process import ProcessStates, Subprocess

from supervisord_dependent_startup.supervisord_dependent_startup import main

from . import DependentStartupError, common, process_states
from .common import DefaultTestRPCInterface, dependent_startup_service_name, mock
from .helpers import LogCapturePrintable
from .utils import cprint, plugin_logger_name, plugin_tests_logger_name  # noqa: F401

logger = logging.getLogger(plugin_tests_logger_name)


class SubProcessDummy(Subprocess):

    def __init__(self, pconfig, state=None):
        Subprocess.__init__(self, pconfig)
        self.state = state


class DependentStartupEventTestsBase(common.WithEventListenerProcessTestsBase):

    def setUp(self):
        super(DependentStartupEventTestsBase, self).setUp()
        self.state_change_events = []

        self.write_supervisord_config()
        self.testProcessClass = SubProcessDummy

        self.setup_event_listener()
        self.setup_state_event_callback()

    def setup_state_event_callback(self):

        def process_state_event_cb(event):
            logger.debug("EVENT CALLBACK: %s" % (event))
            eventlistener = self.rpc.supervisord.process_groups[dependent_startup_service_name]

            eventlistener._acceptEvent(event, head=False)
            event_type = event.__class__
            serial = event.serial
            pool_serial = event.pool_serials[dependent_startup_service_name]

            try:
                payload = event.payload()
            except AttributeError:
                # supervisor version <= 3.4.0
                payload = str(event)

            envelope = eventlistener._eventEnvelope(event_type, serial, pool_serial, payload)
            logger.debug("Writing event envelope to stdin: %s" % envelope)
            self.stdin_wrapper.write(envelope)
            eventlistener.event_buffer.pop(0)
            self.listener_process.event = event

        del events.callbacks[:]
        for event in [
                # 'PROCESS_STATE',
                'PROCESS_STATE_STOPPED',
                'PROCESS_STATE_EXITED',
                'PROCESS_STATE_STARTING',
                'PROCESS_STATE_STOPPING',
                'PROCESS_STATE_BACKOFF',
                'PROCESS_STATE_FATAL',
                'PROCESS_STATE_RUNNING',
                'PROCESS_STATE_UNKNOWN']:

            events.subscribe(getattr(events.EventTypes, event), process_state_event_cb)

    def setup_event_listener(self):
        eventlistener_pconfig = self.make_epconfig(
            dependent_startup_service_name, "/bin/sleep 100", self.options, uid='process1-new', autostart=True)
        eventlistener_events = self.make_econfig("PROCESS_STATE")
        eventlistener_group = self.make_egconfig(
            dependent_startup_service_name, self.options, [eventlistener_pconfig], eventlistener_events)
        self.process_group_configs.append(eventlistener_group)
        self.listener_process = self.add_process(dependent_startup_service_name,
                                                 eventlistener_pconfig, pid=105, state=ProcessStates.RUNNING)


class DependentStartupEventSuccessTests(DependentStartupEventTestsBase):

    def setUp(self):
        super(DependentStartupEventSuccessTests, self).setUp()
        test_instance = self

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                test_instance.processes_started.append(name)

                # Set the process to have started 10 seconds ago
                test_instance.processes[name].laststart -= 15

                # This changes the process state
                test_instance.processes[name].transition()

        self.rpcinterface_class = TestRPCInterface

    def test_run_with_two_services_started_simultaneously_with_priorities(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running", priority=10)
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running", priority=15)
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()

        procs = ['consul', 'consul2', 'slurmd', 'slurmd2']
        self.assertEqual(self.processes_started, procs)
        self.assertStateProcsRunning(procs)

    def test_run_with_two_services_started_simultaneously_without_priorities(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()
        # self.monitor_print_batchmsgs()

        procs = ['consul', 'consul2', 'slurmd', 'slurmd2']
        self.assertEqual(self.processes_started, procs)
        self.assertStateProcsRunning(procs)

    def test_start_service_with_no_file_failure_20(self):
        self.add_test_service('consul', self.options)
        # slurmd should fail to start. Command MUST be '/bad/filename',
        # as it's hardcoded tests/base.py:DummyOptions
        self.add_test_service('slurmd', self.options, pid=True,
                              dependent_startup_wait_for="consul:running", cmd='/bad/filename')

        self.setup_eventlistener()
        with LogCapturePrintable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            self.assertLogContains(log_capture,
                                   (plugin_logger_name, 'WARNING',
                                    "Error when starting service 'slurmd': <Fault 20: 'NO_FILE: bad filename'>"))
        procs = ['consul']
        self.assertEqual(self.processes_started, procs)
        self.assertStateProcs([('consul', 'RUNNING'),
                               ('slurmd', 'STOPPED')])

    def test_start_service_with_circular_dependency(self):
        self.add_test_service('consul', self.options, dependent_startup_wait_for="consul3:running")
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('consul3', self.options, dependent_startup_wait_for="consul2:running")

        with self.assertRaises(DependentStartupError) as context:
            self.setup_eventlistener()
            self.monitor_run_and_listen_until_no_more_events()

        expected = {'consul': set(['consul3']), 'consul2': set(['consul']), 'consul3': set(['consul2'])}
        expected_str = 'Circular dependencies exist among these items: {{{}}}'.format(
            ', '.join('{!r}:{!r}'.format(key, value) for key, value in sorted(expected.items())))

        self.assertEqual(expected_str, str(context.exception))

    def test_start_service_check_order(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")
        # slurmd3 should come before slurmd2 due to priority
        self.add_test_service('slurmd3', self.options,
                              dependent_startup_wait_for="consul:running slurmd:running", priority=100)

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()

        procs = ['consul', 'consul2', 'slurmd', 'slurmd3', 'slurmd2']
        self.assertEqual(procs, self.processes_started)
        self.assertStateProcsRunning(procs)

    def test_not_starting_service_not_satisfying_deps(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('unhandled', self.options, autostart=True)
        self.add_test_service('slurmd', self.options,
                              dependent_startup_wait_for="consul:running unhandled:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()

        # self.print_procs()
        self.assertEqual(self.processes_started, ['consul'])
        self.assertStateProcs([('consul', 'RUNNING'),
                               ('slurmd', 'STOPPED'),
                               ('unhandled', 'STOPPED')])

    def test_run_main(self):
        self.write_supervisord_config()

        self.add_test_service('consul', self.options)
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running", priority=10)
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")

        self.setup_supervisord()
        testargs = [self.supervisor_conf]

        with mock.patch.multiple('sys', argv=testargs, stdin=self.stdin_wrapper, stdout=self.stdout):
            with self.assertRaises(common.UnitTestException):
                main()


class DependentStartupEventErrorTests(DependentStartupEventTestsBase):

    def setUp(self):
        super(DependentStartupEventErrorTests, self).setUp()
        test_instance = self

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                test_instance.processes_started.append(name)

        self.rpcinterface_class = TestRPCInterface

    def test_start_service_on_already_running_service(self):
        self.add_test_service('consul', self.options, pid=None)
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running")

        self.state_change_events.append(('consul', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd', ProcessStates.RUNNING))

        self.setup_eventlistener()
        with LogCapturePrintable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            self.assertLogContains(log_capture,
                                   (plugin_logger_name, 'INFO',
                                    'No more processes to start for initial startup, ignoring all future events.'))

        procs = ['consul', 'slurmd']
        self.assertEqual(self.processes_started, procs)
        self.assertStateProcsRunning(procs)

    def test_start_service_on_already_running_service_force_error(self):
        """
        Test what happens if supervisord throws an Faults.ALREADY_STARTED error
        """
        print()
        self.state_change_events.append(('consul', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd', ProcessStates.STARTING))
        self.state_change_events.append(('slurmd', ProcessStates.RUNNING))

        self.add_test_service('consul', self.options, pid=None)
        self.add_test_service('slurmd', self.options, pid=True, dependent_startup_wait_for="consul:running")

        self.setup_eventlistener()

        # mock these two functions to circumvent the tests that should prevent starting an already running process
        def is_done(self, name):
            if name == 'slurmd':
                return False
            return self.get_service_state(name) in self.states_done

        def is_startable(self, name):
            if name == 'slurmd':
                return True
            state = self.get_service_state(name)
            return not process_states.is_running(state)

        with (
            mock.patch('supervisord_dependent_startup.supervisord_dependent_startup.ProcessHandler.is_done',
                       is_done)) as a, (  # noqa: F841
            mock.patch('supervisord_dependent_startup.supervisord_dependent_startup.ProcessHandler.is_startable',
                       is_startable)) as b, (  # noqa: F841
                LogCapturePrintable()) as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            self.assertLogContains(
                log_capture,
                (plugin_logger_name, "WARNING",
                 "Error when starting service 'slurmd': <Fault 60: 'ALREADY_STARTED: slurmd'>"))

        procs = ['consul', 'slurmd']
        self.assertEqual(self.processes_started, procs)
        self.assertStateProcsRunning(procs)

    def test_process_not_started_after_reaching_fatal_state(self):
        self.state_change_events.append(('consul', ProcessStates.BACKOFF))
        self.state_change_events.append(('consul', ProcessStates.FATAL))
        self.add_test_service('consul', self.options)

        self.setup_eventlistener()
        with LogCapturePrintable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()

        log_starting = log_capture.match_regex("Starting service:.+", level="INFO")
        self.assertEqual(1, len(log_starting))
        self.assertEqual("Starting service: consul (State: STOPPED)", log_starting[0].getMessage())
