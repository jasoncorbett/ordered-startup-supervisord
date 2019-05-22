from __future__ import print_function

import logging
import os
import unittest

import supervisor.events
from supervisor.options import (EventListenerConfig, EventListenerPoolConfig, ProcessConfig,
                                ProcessGroupConfig)
from supervisor.process import ProcessStates
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
from supervisor.states import getProcessStateDescription
from supervisor.supervisord import Supervisor
from supervisor.tests.base import DummyOptions, DummyProcess
from supervisor.xmlrpc import RPCError

try:
    from xmlrpclib import Fault as XmlrpcFault
except ImportError:
    from xmlrpc.client import Fault as XmlrpcFault

try:
    from unittest import mock
except ImportError:
    import mock

# isort:imports-localfolder
from . import DependentStartup, StringIO, cleanup_tmp_dir, helpers, test_tmp_dir, utils
from .utils import colored, cprint


logger = logging.getLogger(utils.plugin_tests_logger_name)


class UnitTestException(Exception):
    pass


dependent_startup_service_name = 'dependentstartup'


supervisord_conf_template = """[unix_http_server]
file={{ tmp_dir }}/supervisor.sock

[supervisord]
logfile={{ dependent_startup_log_dir }}/supervisord.log
loglevel=info
pidfile=//{{ tmp_dir }}/supervisord.pid
nodaemon=false
minfds=1024
minprocs=200

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{{ tmp_dir }}/supervisor.sock ; use a unix:// URL  for a unix socket

[eventlistener:%(plugin_name)s]
command={{ supervisord_dependent_startup }} -c /tmp/tmp_home/etc/supervisord.conf
stderr_logfile={{ dependent_startup_log_dir }}/%%(program_name)s-err.log
autostart=true
events=PROCESS_STATE

[include]
files = {{ etc_dir }}/supervisord.d/*.ini

""" % {'plugin_name': dependent_startup_service_name}  # noqa: E501

service_conf_template = """[program:{{ name }}]
command={{ command }}
redirect_stderr=true
{%- if stdout_logfile %}
stdout_logfile={{ dependent_startup_log_dir }}/%(program_name)s.log
{%- endif %}
{%- if priority %}
priority={{ priority }}
{%- endif %}
{%- if autostart is defined %}
autostart={{ autostart }}
{%- endif %}
{%- if autorestart is defined %}
autorestart={{ autorestart }}
{%- endif %}
{%- if startsecs is defined %}
startsecs={{ startsecs }}
{%- endif %}
{%- if dependent_startup is defined %}
dependent_startup={{ dependent_startup }}
{%- endif %}
{%- if dependent_startup_wait_for is defined %}
dependent_startup_wait_for={{ dependent_startup_wait_for }}
{%- endif %}
{%- if dependent_startup_inherit_priority is defined %}
dependent_startup_inherit_priority={{ dependent_startup_inherit_priority }}
{%- endif %}

"""


class DependentStartupTester(DependentStartup):

    process_state_events = ['PROCESS_STATE']

    def __init__(self, args, config_file, **kwargs):
        super(DependentStartupTester, self).__init__(args, config_file, **kwargs)
        self.batchmsgs = []

    def get_process_state_change_msg(self, headers, payload):
        return repr(payload)

    def handle_event(self, headers, payload):
        msg = self.get_process_state_change_msg(headers, payload)
        self.batchmsgs.append(msg)
        super(DependentStartupTester, self).handle_event(headers, payload)

    def monitor_print_batchmsgs(self):
        for i, msg in enumerate(self.monitor.batchmsgs):
            print("Batch msg[%2s]: %s" % (i, msg))


class DependentStartupSupervisorTestsBase(unittest.TestCase):
    """
    * Setup the directories to store supervisor config files
    * Utility functions to create new service files in supervisord.d/
    * Utility functions to create the configuration objects for supervisor

    """
    def tearDown(self):
        super(DependentStartupSupervisorTestsBase, self).tearDown()
        del self.tmpdir  # MUST delete this to trigger call to __exit__

    def setUp(self):
        super(DependentStartupSupervisorTestsBase, self).setUp()
        # Create a temporary dir to store the supervisor config files
        self.tmpdir = helpers.TempDir(name=test_tmp_dir, id=self.id(),
                                      cleanup=cleanup_tmp_dir,
                                      prefix='dependent_startup_unit_test_')

        self.supervisor_base = self.tmpdir.name
        self.etc = os.path.join(self.supervisor_base, 'etc')
        self.log_dir = os.path.join(self.supervisor_base, 'supervisord_logs')
        self.supervisord_d = os.path.join(self.etc, 'supervisord.d')
        self.tmp = os.path.join(self.supervisor_base, 'tmp')

        utils.mkdir(self.etc)
        utils.mkdir(self.tmp)
        utils.mkdir(self.supervisord_d)
        utils.mkdir(self.log_dir)

        self.supervisor_conf = os.path.join(self.etc, 'supervisord.conf')
        logger.info("Using supervisor base dir: %s", self.supervisor_base)

        self.base_args = {'etc_dir': self.etc,
                          'supervisord_dependent_startup': 'supervisord-dependent-startup',
                          'dependent_startup_log_dir': self.log_dir,
                          'tmp_dir': self.tmp,
                          'dependent_startup': 'true',
                          }
        self.processes = {}
        self.process_group_configs = []
        self.processes_started = []
        self.testProcessClass = DummyProcess
        self.supervisord = None
        self.mock_args = mock.Mock(error_action='skip')

    def get_dependent_startup_mock(self, **kwargs):
        if 'stdin' not in kwargs:
            kwargs['stdin'] = StringIO()
        if 'stdout' not in kwargs:
            kwargs['stdout'] = StringIO()
        if 'stderr' not in kwargs:
            kwargs['stderr'] = StringIO()

        args = kwargs.pop('args', self.mock_args)
        config_file = self.supervisor_conf
        obj = DependentStartupTester(args, config_file, **kwargs)
        return obj

    def write_config(self, output_file, template, args):
        from jinja2 import Template
        tmpl = Template(template)
        rendered = tmpl.render(args)
        utils.write_file(output_file, rendered)

    def write_supervisord_config(self):
        args = dict(self.base_args)
        self.write_config(self.supervisor_conf, supervisord_conf_template, args)

    def add_service_file(self, name, cmd="/bin/sleep 100", **extra_args):
        args = dict(self.base_args)
        args['name'] = name
        args['command'] = cmd

        if extra_args:
            args.update(extra_args)

        for a in args:
            if type(args[a]) is bool:
                args[a] = str(args[a]).lower()

        self.service_conf = os.path.join(self.supervisord_d, "%s.ini" % name)
        self.write_config(self.service_conf, service_conf_template, args)
        return self.service_conf

    def add_process(self, name, pconfig, **args):
        state = args.get('state', ProcessStates.STOPPED)
        process = self.testProcessClass(pconfig, state=state)
        process.laststart = 0
        process.laststop = 0

        if 'pid' in args:
            if args['pid'] is True:
                process.pid = 100 + len(self.processes)
            else:
                process.pid = args['pid']
        else:
            process.pid = None

        self.processes[name] = process
        return process

    def add_test_service(self, name, options, cmd="/bin/sleep 100", autostart=False, **args):
        self.add_service_file(name, cmd, autostart=autostart, **args)
        pconfig = self.make_pconfig(name, cmd, options, uid='new', autostart=autostart, **args)
        pgroup_config = self.make_gconfig(name, [pconfig], options)
        self.process_group_configs.append(pgroup_config)
        self.add_process(name, pconfig, **args)

    def make_econfig(self, *pool_event_names):
        """
        Make eventlistener config
        """
        result = []
        for pool_event_name in pool_event_names:
            result.append(getattr(supervisor.events.EventTypes, pool_event_name, None))
        return result

    def make_epconfig(self, name, command, options, **params):
        """"
        Make Eventlistener process config
        """
        result = {
            'name': name, 'command': command,
            'directory': None, 'umask': None, 'priority': 999, 'autostart': True,
            'autorestart': True, 'startsecs': 10, 'startretries': 999,
            'uid': None, 'stdout_logfile': None, 'stdout_capture_maxbytes': 0,
            'stdout_events_enabled': False,
            'stdout_logfile_backups': 0, 'stdout_logfile_maxbytes': 0,
            'stdout_syslog': False,
            'stderr_logfile': None, 'stderr_capture_maxbytes': 0,
            'stderr_events_enabled': False,
            'stderr_logfile_backups': 0, 'stderr_logfile_maxbytes': 0,
            'stderr_syslog': False,
            'redirect_stderr': False,
            'stopsignal': None, 'stopwaitsecs': 10,
            'stopasgroup': False,
            'killasgroup': False,
            'exitcodes': (0, 2), 'environment': None, 'serverurl': None,
        }
        result.update(params)
        return EventListenerConfig(options, **result)

    def make_egconfig(self, name, options, pconfigs, pool_events,
                      result_handler='supervisor.dispatchers:default_handler'):
        """
        Make eventlistener group config
        """
        return EventListenerPoolConfig(options, name, 25, pconfigs, 10, pool_events, result_handler)

    def make_pconfig(self, name, command, options, **params):
        """
        Make process config
        """
        result = {
            'name': name, 'command': command,
            'directory': None, 'umask': None, 'priority': 999, 'autostart': True,
            'autorestart': True, 'startsecs': 10, 'startretries': 999,
            'uid': None, 'stdout_logfile': None, 'stdout_capture_maxbytes': 0,
            'stdout_events_enabled': False,
            'stdout_logfile_backups': 0, 'stdout_logfile_maxbytes': 0,
            'stdout_syslog': False,
            'stderr_logfile': None, 'stderr_capture_maxbytes': 0,
            'stderr_events_enabled': False,
            'stderr_logfile_backups': 0, 'stderr_logfile_maxbytes': 0,
            'stderr_syslog': False,
            'redirect_stderr': False,
            'stopsignal': None, 'stopwaitsecs': 10,
            'stopasgroup': False,
            'killasgroup': False,
            'exitcodes': (0, 2), 'environment': None, 'serverurl': None,
        }
        result.update(params)
        return ProcessConfig(options, **result)

    def make_gconfig(self, name, pconfigs, options):
        """
        Make process group config
        """
        return ProcessGroupConfig(options, name, 25, pconfigs)

    def print_procs(self, names=None):
        if names is None:
            procs = self.rpc.getAllProcessInfo()
        else:
            procs = []
            for name in names():
                proc_info = self.rpc.getProcessInfo(name)
                procs.append(proc_info)

        exclude = ['name', 'statename', 'state', 'pid']
        for p in procs:
            rest = {k: p[k] for k in p if k not in exclude}
            print("Proc({name:15}): state({state:2}): {statename:10} pid: {pid:4} {rest}".format(rest=rest, **p))

    def getProcessStateDescription(self, process=None, state=None):  # noqa: N802 (lowercase)
        if process is not None:
            return getProcessStateDescription(self.processes[process].state)
        else:
            return getProcessStateDescription(state)

    def assertLogContains(self, capture, expected, count=None):  # noqa: N802 (lowercase)
        found = 0
        for e in capture.records:
            if e.name != expected[0]:
                continue
            if e.levelname != expected[1]:
                continue
            if e.getMessage() != expected[2]:
                continue
            found += 1

        if count is None or found == count:
            return

        logger.error("Captured log statements:\n%s", capture)
        if count and found != count:
            msg = "Log message '%s' occured %d times. Expected %d" % (str(expected), found, count)
        else:
            msg = "Log message '%s' not found" % (str(expected))
        self.fail(msg)

    def assertStateProc(self, name, state):  # noqa: N802 (lowercase)
        proc_info = self.rpc.getProcessInfo(name)
        self.assertEqual(proc_info['statename'], state,
                         "Proc %s expected state %s != %s" % (name, state, proc_info['statename']))

    def assertStateProcs(self, proc_states):  # noqa: N802 (lowercase)
        for name, state in proc_states:
            self.assertStateProc(name, state)

    def assertStateProcsRunning(self, names):  # noqa: N802 (lowercase)
        self.assertStateProcs([(name, 'RUNNING') for name in names])


class StdinManualEventsWrapper(object):
    """
    Wrapper around stdin that converts events from the event list
    into str formatted event read by from supervisor.childutils
    """
    def __init__(self):
        self.events = []
        self.index = 0
        self.base_event = {'ver': '3.0',
                           'server': 'supervisor',
                           'serial': '329',
                           'pool': dependent_startup_service_name,
                           'poolserial': '0',
                           'eventname': 'unset',
                           'len': 'unset',
                           'processname': 'unset',
                           'from_state': 'unset',
                           'groupname': 'unset'}

    def add_event(self, event):
        event_dict = dict(self.base_event, **event)
        self.events.append(event_dict)

    def get_process_event_line(self, index):
        return ("processname:%(processname)s groupname:%(groupname)s "
                "from_state:%(from_state)s pid:%(pid)s" % self.events[index])

    def readline(self):
        if self.index >= len(self.events):
            raise UnitTestException("No more events")
        process_line = self.get_process_event_line(self.index)
        attrs = dict(self.events[self.index])
        attrs['len'] = len(process_line)
        line = "ver:%(ver)s server:%(server)s serial:%(serial)s pool:%(pool)s "\
               "poolserial:%(poolserial)s eventname:%(eventname)s len:%(len)s" % attrs
        return line

    def read(self, n=-1):
        process_line = self.get_process_event_line(self.index)
        self.index += 1
        return process_line


class StdinIOStringWrapper(object):

    def __init__(self):
        self.buffer = StringIO()

    def __len__(self):
        return self._buffer_len() - self.buffer.tell()

    def _buffer_len(self):
        cur_pos = self.buffer.tell()
        self.buffer.seek(0, os.SEEK_END)
        length = self.buffer.tell()
        self.buffer.seek(cur_pos)
        return length

    def readline(self):
        if self._buffer_len() == self.buffer.tell():
            raise UnitTestException("No more events")

        return self.buffer.readline()

    def read(self, n=-1):
        return self.buffer.read(n)

    def write(self, buf):
        logger.debug(colored("StdinIOStringWrapper.write() EVENT: '%s'" % buf, 'red'))
        pos = self.buffer.tell()
        self.buffer.write(buf)
        self.buffer.seek(pos)


class MockRPCInterfaceTestsBase(DependentStartupSupervisorTestsBase):

    def setUp(self):
        super(MockRPCInterfaceTestsBase, self).setUp()
        self.rpc_patcher = mock.patch('supervisor.childutils.getRPCInterface')
        self.mock_get_rpc_interface = self.rpc_patcher.start()

    def tearDown(self):
        super(MockRPCInterfaceTestsBase, self).tearDown()
        self.rpc_patcher.stop()


class DependentStartupTestsBase(MockRPCInterfaceTestsBase):

    def setUp(self):
        super(DependentStartupTestsBase, self).setUp()
        self.options = DummyOptions()

    def setup_supervisord(self, mock_get_rpc_interface=None):
        if mock_get_rpc_interface is None:
            mock_get_rpc_interface = self.mock_get_rpc_interface
        self.supervisord = Supervisor(self.options)
        self.supervisord.options.process_group_configs = self.process_group_configs
        self.rpc = self.rpcinterface_class(self.supervisord)

        for p in self.processes:
            self.rpc.addProcessGroup(p)
            self.rpc.supervisord.process_groups[p].processes = {p: self.processes[p]}

        # When calling supervisor.childutils.getRPCInterface, return itself
        mock_get_rpc_interface.return_value = mock_get_rpc_interface
        # When accessing supervisor attribute, return the rpc object
        type(mock_get_rpc_interface).supervisor = mock.PropertyMock(return_value=self.rpc)

    def monitor_run_and_listen_action(self, count):
        pass

    def monitor_run_and_listen_until_no_more_events(self):
        self.monitor.run()
        with self.assertRaises(UnitTestException):
            count = 0
            for l in self.monitor._listen():
                count += 1
                self.monitor_run_and_listen_action(count)


class DefaultTestRPCInterface(SupervisorNamespaceRPCInterface):

    def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
        """
        SupervisorNamespaceRPCInterface raises, RPCError, but we need to catch
        type xmlrpclib.Fault in the plugin, so translate RPCError to xmlrpclib.Fault.
        """
        try:
            SupervisorNamespaceRPCInterface.startProcess(self, name, wait=wait)
        except RPCError as err:
            raise XmlrpcFault(err.code, err.text)


class DependentStartupWithoutEventListenerTestsBase(DependentStartupTestsBase):

    def setUp(self):
        super(DependentStartupWithoutEventListenerTestsBase, self).setUp()
        test_instance = self

        class TestRPCInterface(DefaultTestRPCInterface):

            def startProcess(self, name, wait=True):  # noqa: N802 (lowercase)
                # cprint("startProcess(%s)" % (name), 'yellow')
                test_instance.add_event(name, 'STOPPED', 'PROCESS_STATE_STARTING')
                test_instance.add_event(name, 'STARTING', 'PROCESS_STATE_RUNNING')
                DefaultTestRPCInterface.startProcess(self, name, wait=wait)
                test_instance.processes_started.append(name)

        self.rpcinterface_class = TestRPCInterface
        self.stdin_wrapper = StdinManualEventsWrapper()

    def add_event(self, name, from_state, eventname):
        pid = 9999
        if name in self.processes:
            pid = self.processes[name].pid

        event = {'from_state': from_state, 'eventname': eventname, 'processname': name,
                 'groupname': name, 'pid': pid}

        self.stdin_wrapper.add_event(event)

    def setup_eventlistener(self, mock_get_rpc_interface=None, **kwargs):
        super(DependentStartupWithoutEventListenerTestsBase, self).setup_supervisord(
            mock_get_rpc_interface=mock_get_rpc_interface)
        self.monitor = self.get_dependent_startup_mock(stdin=self.stdin_wrapper,
                                                       rpcinterface=mock_get_rpc_interface,
                                                       **kwargs)

    def monitor_run_and_listen_until_no_more_events(self):
        # We need to add an initial event to trigger the plugin to start handling the services
        self.add_event(dependent_startup_service_name, 'STOPPED', 'PROCESS_STATE_STARTING')
        self.add_event(dependent_startup_service_name, 'STARTING', 'PROCESS_STATE_RUNNING')
        super(DependentStartupWithoutEventListenerTestsBase, self).monitor_run_and_listen_until_no_more_events()


class WithEventListenerProcessTestsBase(DependentStartupTestsBase):

    def setUp(self):
        super(WithEventListenerProcessTestsBase, self).setUp()
        self.stdout = StringIO()
        self.stdin_wrapper = StdinIOStringWrapper()

    def setup_eventlistener(self, mock_get_rpc_interface=None, **kwargs):
        super(WithEventListenerProcessTestsBase, self).setup_supervisord(
            mock_get_rpc_interface=mock_get_rpc_interface)
        self.monitor = self.get_dependent_startup_mock(stdin=self.stdin_wrapper,
                                                       stdout=self.stdout,
                                                       rpcinterface=mock_get_rpc_interface, **kwargs)

    def monitor_run_and_listen_until_no_more_events(self):
        # We need to add an initial event to trigger the plugin to start handling the services
        self.processes[dependent_startup_service_name].change_state(ProcessStates.STARTING)
        self.processes[dependent_startup_service_name].transition()
        super(WithEventListenerProcessTestsBase, self).monitor_run_and_listen_until_no_more_events()

    def monitor_run_and_listen_action(self, count):
        if self.state_change_events:
            process, state = self.state_change_events.pop(0)
            if state == self.processes[process].state:
                cprint("STATE ERROR - Process '%s' already is in state %s" %
                       (process, self.getProcessStateDescription(state=state)), color='red')

            # print("LOOP %2d change State %s: %s -> %s" %
            #       (count, process, self.getProcessStateDescription(process=process),
            #            self.getProcessStateDescription(state=state)))
            self.processes[process].change_state(state)
