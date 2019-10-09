from __future__ import print_function

import logging
import os

import supervisor
from supervisor.options import NotFound
from supervisor.process import ProcessStates, Subprocess
from supervisor.xmlrpc import Faults, RPCError

from supervisord_dependent_startup.supervisord_dependent_startup import main as eventplugin_main

from . import common, DependentStartupError, process_states, xmlrpclib
from .common import DefaultTestRPCInterface, dependent_startup_service_name, mock
from .helpers import get_log_capture_printable, LogCapturePrintable
from .log_utils import plugin_logger_name, plugin_tests_logger_name  # noqa: F401
from .utils import cprint  # noqa: F401

log = logging.getLogger(plugin_tests_logger_name)


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

        self.setup_eventlistener_process()
        self.setup_state_event_callback()

    def setup_state_event_callback(self):

        def process_state_event_cb(event):
            log.debug("EVENT CALLBACK: %s" % (event))
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
            log.debug("Writing event envelope to stdin: %s" % envelope)

            self.stdin_wrapper.write(envelope)
            eventlistener.event_buffer.pop(0)
            self.listener_process.event = event

        del supervisor.events.callbacks[:]
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

            supervisor.events.subscribe(getattr(supervisor.events.EventTypes, event), process_state_event_cb)

    def setup_eventlistener_process(self):
        eventlistener_pconfig = self.make_epconfig(
            dependent_startup_service_name, "/bin/sleep 100", self.options, uid='process1-new', autostart=True)
        eventlistener_events = self.make_econfig("PROCESS_STATE")
        eventlistener_group = self.make_egconfig(
            dependent_startup_service_name, self.options, [eventlistener_pconfig], eventlistener_events)
        self.process_group_configs[dependent_startup_service_name] = eventlistener_group
        self.listener_process = self.add_process(dependent_startup_service_name,
                                                 eventlistener_pconfig, eventlistener_group.name,
                                                 pid=105, state=ProcessStates.RUNNING)


class DependentStartupEventSuccessTests(DependentStartupEventTestsBase):

    def setUp(self):
        super(DependentStartupEventSuccessTests, self).setUp()

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                ret = DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                self.test_instance.processes_started.append(name)

                # If it's a process group with multiple processes (numproc > 1), the name
                # if on the form service:service_<proc num>, e.g. slurmd:slurmd_00
                # The processes dict contains the process name without the group prefix
                # so remove that here
                if name not in self.test_instance.processes:
                    name = name.split(':')[1]

                # Set the process to have started 10 seconds ago
                self.test_instance.processes[name].laststart -= 15

                # This changes the process state
                self.test_instance.processes[name].transition()
                return ret

            def startProcessGroup(self, group, wait=True):  # noqa: N802 (lowercase)
                return DefaultTestRPCInterface.startProcessGroup(self, group, wait=wait)

        self.rpcinterface_class = TestRPCInterface

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_start_service_with_numproc_two_processes(self):
        """
        Test starting service with numproc specifying two processes.

        Supervisor will create a process group for the two processes

        """
        self.add_test_service('consul', self.options, pid=None)
        self.add_test_service('slurmd', self.options,
                              cmd='/valid/filename',
                              numprocs=2,
                              process_name="%(program_name)s_%(process_num)02d",
                              dependent_startup_wait_for="consul:running")

        self.setup_eventlistener()

        with get_log_capture_printable() as log_capture:  # noqa: F841
            self.monitor_run_and_listen_until_no_more_events()
            # print(log_capture)

        expected_procs = ['consul', 'slurmd:slurmd_00', 'slurmd:slurmd_01']
        self.assertEqual(expected_procs, sorted(self.processes_started))
        self.assertStateProcsRunning(expected_procs)

    def test_run_with_two_services_started_simultaneously_with_priorities(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running", priority=10)
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running", priority=15)
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()

        expected_procs = ['consul', 'consul2', 'slurmd', 'slurmd2']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

    def test_run_with_two_services_started_simultaneously_without_priorities(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('consul2', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd', self.options, dependent_startup_wait_for="consul:running")
        self.add_test_service('slurmd2', self.options, dependent_startup_wait_for="consul:running slurmd:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()
        # self.monitor_print_batchmsgs()

        expected_procs = ['consul', 'consul2', 'slurmd', 'slurmd2']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

    def test_start_service_with_no_file_failure_20(self):
        self.add_test_service('consul', self.options)
        # slurmd should fail to start. Command MUST be '/bad/filename',
        # as it's hardcoded tests/base.py:DummyOptions
        self.add_test_service('slurmd', self.options, pid=True,
                              dependent_startup_wait_for="consul:running", cmd='/bad/filename')

        self.setup_eventlistener()
        with LogCapturePrintable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            self.assertLogContains(
                log_capture,
                (plugin_logger_name, 'WARNING',
                 "Error when starting service 'slurmd' (group: slurmd): <Fault 20: 'NO_FILE: bad filename'>"))
        expected_procs = ['consul']
        self.assertEqual(expected_procs, self.processes_started)
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

        expected_procs = ['consul', 'consul2', 'slurmd', 'slurmd3', 'slurmd2']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

    def test_not_starting_service_not_satisfying_deps(self):
        self.add_test_service('consul', self.options)
        self.add_test_service('unhandled', self.options, autostart=True)
        self.add_test_service('slurmd', self.options,
                              dependent_startup_wait_for="consul:running unhandled:running")

        self.setup_eventlistener()
        self.monitor_run_and_listen_until_no_more_events()

        # self.print_procs()
        self.assertEqual(['consul'], self.processes_started)
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
            with self.assertRaises(common.UnitTestNoMoreEventsException):
                eventplugin_main()


class DependentStartupEventErrorTests(DependentStartupEventTestsBase):

    def setUp(self):
        super(DependentStartupEventErrorTests, self).setUp()

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                ret = DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                self.test_instance.processes_started.append(name)
                return ret

        self.rpcinterface_class = TestRPCInterface

    def test_start_services(self):
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

        expected_procs = ['consul', 'slurmd']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

    def test_process_not_started_after_reaching_fatal_state(self):
        self.state_change_events.append(('consul', ProcessStates.BACKOFF))
        self.state_change_events.append(('consul', ProcessStates.FATAL))
        self.add_test_service('consul', self.options)

        self.setup_eventlistener()
        with get_log_capture_printable(colors=True) as log_capture:  # noqa: F841
            self.monitor_run_and_listen_until_no_more_events()

        log_starting = log_capture.match_regex("Starting service:.+", level="INFO")
        self.assertEqual(1, len(log_starting))
        self.assertEqual("Starting service: consul (State: STOPPED)", log_starting[0].getMessage())


class DependentStartupEventForceErrorTests(DependentStartupEventErrorTests):
    """
    To produce the errors, these tests mock the plugin code to circumvent existing sanity checks

    """
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_start_service_on_already_running_service(self):
        """
        Test what happens if supervisord throws an Faults.ALREADY_STARTED error
        """
        self.state_change_events.append(('consul', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd', ProcessStates.STARTING))
        self.state_change_events.append(('slurmd', ProcessStates.RUNNING))

        self.add_test_service('consul', self.options, pid=None)
        self.add_test_service('slurmd', self.options, pid=True, dependent_startup_wait_for="consul:running")

        self.setup_eventlistener()

        # mock these functions to circumvent the tests that should prevent starting an already running process
        def is_service_done(self, service):
            if service.name == 'slurmd':
                return False
            states = self.get_service_states(service)
            procs_done = [state in self.states_done for sname, state in states]
            return False not in procs_done

        def is_startable(self, service):
            if service.name == 'slurmd':
                return True
            states = self.get_service_states(service)
            startable = [process_states.is_running(state) for sname, state in states]
            return True not in startable

        def is_not_running(process):
            from supervisor.states import RUNNING_STATES
            if process.config.name == 'slurmd':
                return True
            return not process.get_state() in RUNNING_STATES

        def check_execv_args(filename, argv, st):
            print("check_execv_args - filename: %s, argv: %s, st: %s" % (filename, argv, st))
            if st is None:
                raise NotFound("can't find command %r" % filename)

        with (
            mock.patch('supervisord_dependent_startup.supervisord_dependent_startup.ServicesHandler.is_service_done',
                       is_service_done)) as a, (  # noqa: F841
            mock.patch('supervisord_dependent_startup.supervisord_dependent_startup.ProcessHandler.is_startable',
                       is_startable)) as b, (  # noqa: F841
            mock.patch('supervisor.rpcinterface.isNotRunning',
                       is_not_running)) as b, (  # noqa: F841
                LogCapturePrintable()) as log_capture:

            self.monitor_run_and_listen_until_no_more_events()
            # print(log_capture)

            self.assertLogContains(
                log_capture,
                (plugin_logger_name, "WARNING",
                 "Error when starting service 'slurmd' (group: slurmd): <Fault 60: 'ALREADY_STARTED: slurmd'>"))

        expected_procs = ['consul', 'slurmd']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

    def setUp(self):
        super(DependentStartupEventErrorTests, self).setUp()

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                ret = None
                try:
                    ret = DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                    self.test_instance.processes_started.append(name)
                except RPCError as err:
                    self.test_instance.processes_failed.append((name, err))
                return ret

            def startProcessGroup(self, group, wait=True):  # noqa: N802 (lowercase)
                try:
                    return DefaultTestRPCInterface.startProcessGroup(self, group, wait=wait)
                except xmlrpclib.Fault as err:
                    self.test_instance.processes_failed.append((group, err))
                    raise

        self.rpcinterface_class = TestRPCInterface

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_start_bad_service_with_numproc_two_processes(self):
        """
        Test starting service with numproc specifying two processes.

        Supervisor will create a process group for the two processes

        """
        self.state_change_events.append(('consul', ProcessStates.RUNNING))

        self.add_test_service('consul', self.options, pid=None)
        self.add_test_service('slurmd', self.options, cmd='/bad/filename',
                              numprocs=2,
                              process_name="%(program_name)s_%(process_num)02d",
                              dependent_startup_wait_for="consul:running")

        self.setup_eventlistener()

        with get_log_capture_printable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            # print(log_capture)
            self.assertLogContains(
                log_capture,
                (plugin_logger_name, "WARNING",
                 "Error when starting service 'slurmd' (group: slurmd): <Fault 20: 'NO_FILE: bad filename'>"))

        expected_procs = ['consul']
        self.assertEqual(expected_procs, self.processes_started)
        self.assertStateProcsRunning(expected_procs)

        slurmd_err_expected = xmlrpclib.Fault(Faults.NO_FILE, 'NO_FILE: bad filename')
        slurmd_err = self.processes_failed[0][1]
        self.assertEqual(repr(slurmd_err), repr(slurmd_err_expected))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_start_services_in_same_process_group(self):
        """
        Test that services in the same process group are started
        """
        self.state_change_events.append(('consul', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd2', ProcessStates.RUNNING))

        conf_str = ""
        service_conf, rendered = self.add_test_service('consul', self.options, pid=None)
        service_conf2, rendered = self.add_test_service('slurmd', self.options,
                                                        cmd='/valid/filename',
                                                        group='foo',
                                                        write=False,
                                                        dependent_startup_wait_for="consul:running")
        conf_str += "%s\n" % rendered
        service_conf3, rendered = self.add_test_service('slurmd2', self.options,
                                                        cmd='/valid/filename',
                                                        group='foo',
                                                        write=False,
                                                        dependent_startup_wait_for="consul:running")
        conf_str += "%s\n" % rendered
        conf_str += """
[group:foo]
programs=slurmd,slurmd2
priority=999
"""

        self.write_config(service_conf2, conf_str)
        self.setup_eventlistener()

        with get_log_capture_printable() as log_capture:  # noqa: F841
            self.monitor_run_and_listen_until_no_more_events()
            # print(log_capture)

        procs = ['consul', 'foo:slurmd', 'foo:slurmd2']
        self.assertEqual(procs, self.processes_started)
        self.assertStateProcsRunning(procs)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_start_service_group_with_two_processes_force_error(self):
        """
        Test what happens if supervisord throws an Faults.NO_FILE: bad filename' error
        """
        self.state_change_events.append(('consul', ProcessStates.RUNNING))
        self.state_change_events.append(('slurmd', ProcessStates.RUNNING))

        conf_str = ""
        service_conf, rendered = self.add_test_service('consul', self.options, pid=None)
        service_conf2, rendered = self.add_test_service('slurmd', self.options,
                                                        cmd='/valid/filename',
                                                        group='foo',
                                                        write=False,
                                                        dependent_startup_wait_for="consul:running")
        conf_str += "%s\n" % rendered
        service_conf3, rendered = self.add_test_service('slurmd2', self.options,
                                                        cmd='/bad/filename',
                                                        group='foo',
                                                        write=False,
                                                        dependent_startup_wait_for="consul:running")

        conf_str += "%s\n" % rendered
        conf_str += """
[group:foo]
programs=slurmd,slurmd2
priority=999
"""

        self.write_config(service_conf2, conf_str)
        self.setup_eventlistener()

        with get_log_capture_printable() as log_capture:
            self.monitor_run_and_listen_until_no_more_events()
            # print(log_capture)
            self.assertLogContains(
                log_capture,
                (plugin_logger_name, "WARNING",
                 "Error when starting service 'slurmd2' (group: foo): <Fault 20: 'NO_FILE: bad filename'>"))

        procs = ['consul', 'foo:slurmd']
        self.assertEqual(procs, self.processes_started)
        self.assertStateProcsRunning(procs)
