#!/usr/bin/env python
#
# An event listener for supervisord that handles ordered startup of services
#
from __future__ import print_function

import argparse
import glob
import logging
import os
import socket
import sys
import traceback
from collections import OrderedDict

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO  # noqa: F401

try:
    from xmlrpc.client import Fault
except ImportError:
    from xmlrpclib import Fault

# isort:imports-thirdparty
import toposort
from supervisor import childutils, states
from supervisor.datatypes import boolean, integer
from supervisor.options import UnhosedConfigParser
from supervisor.states import RUNNING_STATES


log_str_to_levels = {'critial': logging.CRITICAL,
                     'error': logging.ERROR,
                     'warning': logging.WARNING,
                     'info': logging.INFO,
                     'debug': logging.DEBUG,
                     'notset': logging.NOTSET}


def get_level_from_string(str_level, default='info'):
    default_level = log_str_to_levels.get(default, logging.INFO)
    return log_str_to_levels.get(str_level.lower(), default_level)


def get_str_from_level(level):
    if level == logging.NOTSET:
        return "unset"
    for k, v in log_str_to_levels.items():
        if level == v:
            return k
    raise Exception("No level with value %s" % level)


plugin_logger_name = 'supervisord_dependent_startup'

log = logging.getLogger(plugin_logger_name)


class SupervisorProcessStates(states.ProcessStates):

    def __init__(self):
        self._states = None

    def __contains__(self, state):
        if self._states is None:
            self._set_process_states()
        return state in self._states

    def is_running(self, state):
        if self._states is None:
            self._set_process_states()
        # RUNNING_STATES contains RUNNING, STARTING, BACKOFF
        return self._states[state] in RUNNING_STATES

    def _set_process_states(self):
        states = {}
        for state in dir(self.__class__):
            if state.startswith("_") or callable(getattr(self.__class__, state)):
                continue
            val = getattr(self.__class__, state)
            if type(val) != int:
                log.warning("Process state value for '%s' is not an int but '%s': %s" % (state, type(val), val))
            states[state] = val
        self._states = states

    def process_state_event_to_string(self, event_name):
        return event_name.replace('PROCESS_STATE_', '')


process_states = SupervisorProcessStates()


def get_all_configs(root_path):
    """Get all the configuration files to be parsed.  This is kinda weird because in
    order to do it we must parse the configs.
    """
    retval = [root_path]
    parser = UnhosedConfigParser()
    parser.read(root_path)
    if 'include' in parser.sections() and parser.has_option('include', 'files'):
        files = parser.get('include', 'files').split()
        base_dir = os.path.dirname(os.path.abspath(root_path))
        for pattern in files:
            if pattern.startswith('/'):
                for config in glob.glob(pattern):
                    retval.extend(get_all_configs(config))
            else:
                for config in glob.glob(os.path.join(base_dir, pattern)):
                    retval.extend(get_all_configs(config))
    return retval


def get_config_search_paths():
    script_path = os.path.abspath(os.path.dirname(os.path.dirname(sys.argv[0])))
    cwd = os.getcwd()
    search_paths = [script_path + "/",
                    os.path.join(script_path, 'etc/'),
                    cwd + "/",
                    os.path.join(cwd, 'etc/'),
                    '/etc/',
                    '/etc/supervisor/']
    return search_paths


def search_for_config_file(paths, config_filename):
    for path in paths:
        conf_file = os.path.join(path, config_filename)
        if os.path.exists(conf_file):
            return conf_file
    return None


class DependentStartupError(Exception):
    pass


class ConfigParser(UnhosedConfigParser):

    def safeget(self, section, option, default=None, type_func=None, **kwargs):
        """
        Safely get a config value without raising ValueError

        Args:
            section(str): The section to get the value from
            option(str): The option name
            default(any): The value to return if getting the option value fails
            type_func(func): Function call on the value to convert to proper type
        """
        try:
            value = self.saneget(section, option, default=default, **kwargs)
            if type_func is not None:
                value = type_func(value)
            return value
        except ValueError as err:
            log.warning("Error when parsing section '%s' field: %s: %s", section, option, err)
            return default


class ServiceOptions(object):

    valid_wait_on_states = ['STARTING', 'RUNNING', 'BACKOFF', 'STOPPING', 'EXITED', 'FATAL']
    wait_for_opts_string = 'dependent_startup_wait_for'
    inherit_priority_opts_string = 'dependent_startup_inherit_priority'
    option_field_type_funcs = {
        'priority': integer,
        'autostart': boolean,
        'dependent_startup': boolean,
    }

    def __init__(self):
        self.opts = {}
        self.wait_for_services = OrderedDict()
        ServiceOptions.option_field_type_funcs[self.inherit_priority_opts_string] = boolean

    def parse(self, parser, section_name):
        """
        Args:
            parser(UnhosedConfigParser): the config parser object
            section_name(str): The name of the section to get the options from

        """
        def set_option(option, **kwargs):
            if 'type_func' not in kwargs:
                kwargs['type_func'] = self.option_field_type_funcs.get(option)
            option_value = parser.safeget(section_name, option, **kwargs)
            if option_value is not None:
                self.opts[option] = option_value

        if parser.has_option(section_name, 'priority'):
            set_option('priority')
        if parser.has_option(section_name, 'autostart'):
            set_option('autostart')
        if parser.has_option(section_name, 'dependent_startup'):
            set_option('dependent_startup')
        if parser.has_option(section_name, self.inherit_priority_opts_string):
            set_option(self.inherit_priority_opts_string)
        if parser.has_option(section_name, self.wait_for_opts_string):
            wait_for = parser.safeget(section_name, self.wait_for_opts_string)
            if wait_for is not None:
                self._parse_wait_for(section_name, wait_for)

    def _parse_wait_for(self, section_name, wait_for):
        for dep in wait_for.split(' '):
            # By default, depend on the process being in RUNNING state
            dep_states = ["RUNNING"]
            depsplit = dep.split(':')
            dep_service = depsplit[0]
            if len(depsplit) == 2:
                dep_states = [state.upper() for state in depsplit[1].split(',')]
                for state in list(dep_states):
                    if state not in self.valid_wait_on_states:
                        log.warning("Ignoring invalid state '%s' in '%s' for '%s'" %
                                    (state, self.wait_for_opts_string, section_name))
                        dep_states.remove(state)
            self.wait_for_services[dep_service] = dep_states

    @property
    def autostart(self):
        return self.opts.get('autostart', True)

    @property
    def priority(self):
        return self.opts.get('priority', None)

    @property
    def dependent_startup(self):
        return self.opts.get('dependent_startup', False)

    @property
    def inherit_priority(self):
        return self.opts.get(self.inherit_priority_opts_string, False)

    @property
    def wait_for(self):
        if self.wait_for_services:
            return " ".join(["%s:%s" % (dep, ",".join(state for state in self.wait_for_services[dep]))
                             for dep in self.wait_for_services])
        else:
            None

    def wait_for_state(self, dep):
        return ",".join(state for state in self.wait_for_services[dep])

    def __str__(self):
        attrs = []
        for attr in ['dependent_startup', 'autostart', self.inherit_priority_opts_string]:
            if attr in self.opts:
                attrs.append("%s: %s" % (attr, self.opts[attr]))

        if self.wait_for_services:
            attrs.append("%s: %s" % (self.wait_for_opts_string, str(self.wait_for_services)))

        ret = ", ".join(attrs)
        return ret


class Service(object):

    # The default priority used by supervisor when no priority is set
    default_priority_sort = 999

    def __init__(self, services_handler):
        self.name = None
        self.services_handler = services_handler
        self.options = None
        self.states_reached = []

    def parse_section(self, parser, section_name):
        """
        Args:
            parser(UnhosedConfigParser): the config parser object
            section_name(str): The name of the section to get the options from

        """
        self.name = section_name[8:]
        self.options = ServiceOptions()
        self.options.parse(parser, section_name)

        if self.options.dependent_startup:
            error_msg = None

            if self.options.autostart:
                error_msg = ("Service '%s' config has dependent_startup set to %s, "
                             "which requires autostart to be set explicitly to false. "
                             "autostart is currently %s" %
                             (self.name, self.options.dependent_startup,
                              self.options.opts.get('autostart', 'not set')))
                log.warning("Error when reading config '%s': %s" %
                            (parser.section_to_file[section_name], error_msg))

            if error_msg:
                if self.services_handler.args.error_action == 'exit':
                    raise DependentStartupError(error_msg)
                elif self.services_handler.args.error_action in ['skip', 'ignore']:
                    log.warning("Disable handling service '%s'" % (self.name))
                    self.options.opts['dependent_startup'] = False

    def has_reached_states(self, states):
        """
        Args:
            states (list): List of states

        Returns: True of one of the states have been reached, else False

        """
        for state in states:
            if state in self.states_reached:
                return True
        return False

    @property
    def dependent_startup(self):
        return self.options.dependent_startup

    @property
    def priority_sort(self):
        priority = self.default_priority_sort
        if self.priority:
            priority = self.priority

        if self.options.inherit_priority:
            for dep in self.options.wait_for_services:
                priority = min(priority, self.services_handler._services[dep].priority_sort)
        return priority

    @property
    def priority_effective(self):
        priority = self.priority_sort
        if priority == self.default_priority_sort:
            return None
        return priority

    @property
    def priority(self):
        return self.options.priority

    def depends_on_diff(self, other):
        """
        Return set of dependencies in self that other does not have
        """
        return set(self.options.wait_for_services.keys()).difference(
            set(other.options.wait_for_services.keys()))

    def __str__(self):
        return "Service(name=%s, %s)" % (self.name, str(self.options))

    def __repr__(self):
        return self.__str__()


class ProcessHandler(object):

    states_done = ['RUNNING']

    def __init__(self, rpc):
        self.rpc = rpc
        self.proc_info = OrderedDict()

    def update_proc_info_all(self):
        info = self.rpc.supervisor.getAllProcessInfo()
        for p_info in info:
            self.proc_info[p_info['name']] = p_info

    def update_proc_info_service(self, name):
        info = self.rpc.supervisor.getProcessInfo(name)
        self.proc_info[name] = info

    def get_service_state(self, name, update=False):
        if update:
            self.update_proc_info_service(name)
        return self.proc_info[name].get('statename')

    def is_startable(self, name):
        state = self.get_service_state(name)
        return not (process_states.is_running(state) or state in ['FATAL'])

    def is_done(self, name):
        self.update_proc_info_service(name)
        return self.get_service_state(name) in self.states_done

    def start_service(self, name, wait=True):
        state = self.get_service_state(name)
        log.info("Starting service: {} (State: {})".format(name, state))

        if not self.is_startable(name):
            log.info("Service: %s has state %s. Will not attempt to start service" % (name, state))
            return False

        try:
            self.rpc.supervisor.startProcess(name, wait)
        except Fault as err:
            log.warning("Error when starting service '%s': %s" % (name, err))
            return False

        return True


class ServicesHandler(ProcessHandler):
    """ServicesHandler keep track of all the services managed by supervisor
    """

    def __init__(self, rpc, args):
        super(ServicesHandler, self).__init__(rpc)
        self.max_name_len = 0
        self.indent = 0
        self.args = args
        self._services = OrderedDict()

    def parse_config(self, parser):
        environ_expansions = {}
        for k, v in os.environ.items():
            environ_expansions['ENV_%s' % k] = v
        parser.expansions = environ_expansions
        log.debug("Parsing config with the following expansions: %s", environ_expansions)

        for section_name in parser.sections():
            if section_name.startswith('program:'):
                service = Service(self)
                service.parse_section(parser, section_name)
                self._services[service.name] = service

        self.verify_dependencies()
        ordered = self.get_sorted_services_list()
        ordered_services = OrderedDict([(s_name, self._services[s_name]) for s_name in ordered])
        self._services = ordered_services

    def verify_dependencies(self):
        for sname, v in self._services.items():
            deps = set(v.options.wait_for_services.keys())
            for dep in deps:
                if dep not in self._services:
                    msg = "Service '%s' depends on unknown service '%s'" % (sname, dep)
                    log.warning(msg)
                    if self.args.error_action == 'exit':
                        raise DependentStartupError(msg)
                    else:
                        # Must remove the dependency
                        log.warning("Removing dependency '%s' from service %s", dep, sname)
                        del v.options.wait_for_services[dep]

    def get_sorted_services_list(self):
        deps_dict = {}
        for k, v in self._services.items():
            deps_dict[k] = set(v.options.wait_for_services.keys())

        try:
            result = []
            # Iterator returns a set with services on the same level
            for d in toposort.toposort(deps_dict):
                # First sort by priority, then name
                ordered = sorted(d, key=lambda service:
                                 (self._services[service].priority_sort, service), reverse=False)
                result.extend(ordered)
            return result
        except toposort.CircularDependencyError as err:
            log.error("Cirular dependencies detected: %s" % (err))
            raise DependentStartupError(err)

    def service_wait_for_satisifed(self, service):
        for dep_service in service.options.wait_for_services:
            satisifed = False
            for required_state in service.options.wait_for_services[dep_service]:
                if self._services[dep_service].has_reached_states([required_state]):
                    satisifed = True

            if not satisifed:
                dep_state = self.get_service_state(dep_service)
                log.debug("Service '%s' depends on '%s' to reach state %s. '%s' is currently %s" %
                          (service.name, dep_service, service.options.wait_for_state(dep_service),
                              dep_service, dep_state))
                return False
        return True

    @property
    def services(self):
        return self._services.values()

    def is_service_done(self, name):
        return self._services[name].has_reached_states(['RUNNING', 'FATAL'])

    def update_proc_info_all(self, print_services_list=False):
        super(ServicesHandler, self).update_proc_info_all()
        self.max_name_len = 0
        for k, p_info in self.proc_info.items():
            self.max_name_len = max(self.max_name_len, len(p_info['name']))
        if print_services_list:
            self.log_services_list()

    def update_state_event(self, service_name, state):
        if service_name in self._services:
            self._services[service_name].states_reached.append(state)

    def get_service_str(self, name):
        service = self._services[name]
        state = self.get_service_state(name)
        ret = ("%-{}s  state: %-8s   dependent_startup: %-5s".format(self.max_name_len) %
               (service.name, state, service.options.dependent_startup))
        if service.options.wait_for_services:
            ret += "  wait_for: '%s'" % service.options.wait_for

        effective = service.priority_effective
        if effective is not None:
            ret += "  priority: %4s" % effective
            if service.priority is None:
                ret += " (inherited)"

        return ret

    def log_services_list(self):
        for service in self.services:
            log.info(" - %s" % self.get_service_str(service.name))


class DependentStartup(object):

    process_state_events = ['PROCESS_STATE']

    def __init__(self, args, config_file, **kwargs):
        self.config_file = config_file
        self.interval = kwargs.get('interval', 1.0)
        self.stdin = kwargs.get('stdin', sys.stdin)
        self.stdout = kwargs.get('stdout', sys.stdout)
        self.stderr = kwargs.get('stderr', sys.stderr)
        self.rpc = kwargs.get('rpcinterface', None)
        if not self.rpc:
            self.rpc = childutils.getRPCInterface(os.environ)
            try:
                api_version = self.rpc.supervisor.getAPIVersion()
                log.info("Connected to supervisor with API version: %s", api_version)
            except socket.error:
                raise DependentStartupError("Failed to connect to supervisord:\n%s" % traceback.format_exc())

        self.startup_done = False
        self.start_first = None
        self.plugin_initialized = False
        self.services_handler = ServicesHandler(self.rpc, args)

        log.debug("Args: %s" % args)
        if kwargs.get('load_config', True) is True:
            self.load_config()

    def load_config(self):
        log.info("Reading supervisor config: %s" % self.config_file)
        parser = ConfigParser()
        parser.read(get_all_configs(self.config_file))
        self.services_handler.parse_config(parser)

    def write_stderr(self, msg):
        self.stderr.write(msg)
        self.stderr.flush()

    def get_event_str(self, headers, payload, short=True):
        pheaders = childutils.get_headers(payload)
        pheaders.update(headers)
        if short:
            new_state = process_states.process_state_event_to_string(pheaders['eventname'])
            return ("Service %s went from %s to %s" %
                    (pheaders['processname'], pheaders['from_state'], new_state))
        return "headers: %s, payload: %s" % (headers, payload)

    def handle_event(self, headers, payload):
        event_str = self.get_event_str(headers, payload)

        if self.startup_done:
            return

        log.info("")
        log.info("New event: %s" % event_str)

        if headers['eventname'].startswith('PROCESS_STATE') and not self.startup_done:
            pheaders = childutils.get_headers(payload)
            state = process_states.process_state_event_to_string(headers['eventname'])
            event_process = pheaders['processname']
            log.debug("Event from service '%s' (%s)" % (event_process, state))
            log.debug("headers = {}".format(repr(headers)))
            log.debug("payload = {}".format(repr(pheaders)))

            self.services_handler.update_state_event(event_process, state)
            self.services_handler.update_proc_info_all()

            if self.start_first:
                log.info("Starting immediately: %s" % self.start_first)
                self.services_handler.start_service(self.start_first, wait=False)
                log.info("Starting ordered services")
                self.services_handler.update_proc_info_service(self.start_first)
                self.start_first = None

            self.start_services()

    def start_services(self):
        log.info("Services:")
        self.services_handler.log_services_list()

        # All services we should be handling that aren't already done
        service_to_be_started = []
        for service in self.services_handler.services:
            if not service.dependent_startup:
                continue

            if self.services_handler.is_service_done(service.name):
                state = self.services_handler.get_service_state(service.name)
                log.debug("Ignoring service '%s' in state %s" % (service.name, state))
                continue

            service_to_be_started.append(service)

        # All services with dependent_startup enabled are done
        if not service_to_be_started:
            self.startup_done = True
            log.info("No more processes to start for initial startup, ignoring all future events.")
            return

        log.info("Services not yet running (%s): %s",
                 len(service_to_be_started), [s.name for s in service_to_be_started])

        to_start_priorites = {}
        for service in service_to_be_started:
            if not self.services_handler.service_wait_for_satisifed(service):
                continue

            if not self.services_handler.is_startable(service.name):
                continue

            priority = service.priority_effective
            procs = to_start_priorites.get(priority, list())
            procs.append(service)
            to_start_priorites[priority] = procs

        if to_start_priorites:
            priority_start = sorted(to_start_priorites.keys(), key=lambda x: float('inf') if x is None else x)
            for priority in priority_start:
                for service in to_start_priorites[priority]:
                    self.services_handler.start_service(service.name, wait=False)

    def _listen(self):
        while not self.startup_done:
            headers, payload = childutils.listener.wait(self.stdin, self.stdout)
            self.handle_event(headers, payload)
            childutils.listener.ok(self.stdout)
            yield

    def listen(self):
        for l in self._listen():
            pass

    def run_and_listen(self):
        log.info("")
        log.info("")
        self.run()
        self.listen()

    def run(self):
        self.services_handler.update_proc_info_all(print_services_list=True)

        for service in self.services_handler.services:

            if service.options.autostart or not service.dependent_startup:
                continue

            if not self.services_handler.is_startable(service.name):
                continue

            if not self.services_handler.service_wait_for_satisifed(service):
                continue

            self.start_first = service.name
            break

        if not self.start_first:
            self.startup_done = True
            log.info("Found no services to start")


default_log_format = "%(asctime)s - %(name)s - [%(levelname)-7s] %(message)s"


def main():
    search_paths = get_config_search_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument('--log-file', help="Log to file instead of stderr")
    parser.add_argument('--log-level', choices=log_str_to_levels.keys(), default="info",
                        help="Log level. Default: %(default)s")
    parser.add_argument('--log-format', default=default_log_format,
                        help="Logging format. Default: %(default)s")
    parser.add_argument('-c', '--config', help="Full path to the supervisor config file. "
                        "If not provided, the config will be searched for in the following "
                        "paths: '%s'" % "'\n'".join(search_paths))
    parser.add_argument('--config-filename', default="supervisord.conf",
                        help="The name of the config file to search for "
                        "if the config is not provided. Default: %(default)s")
    parser.add_argument('--fail-on-warning', default=False, action='store_true',
                        help=argparse.SUPPRESS)
    parser.add_argument('--error-action', default='skip', choices=['exit', 'skip', 'ignore'],
                        help="The action to perform when encountering service config errors")
    args = parser.parse_args()

    log_level = get_level_from_string(args.log_level, default='info')

    if args.log_file:
        logging.basicConfig(filename=args.log_file, level=log_level, format=args.log_format)
    else:
        logging.basicConfig(stream=sys.stderr, level=log_level, format=args.log_format)

    if args.fail_on_warning:
        args.error_action = "exit"

    log.info("")
    log.info("supervisord-dependent-startup event listener starting...")

    config_file = None
    if args.config:
        config_file = args.config
    else:
        config_file = search_for_config_file(search_paths, args.config_filename)

    if config_file is None:
        log.warning("Unable to find a config file")
        return 4
    if not os.path.exists(config_file):
        log.warning("Config path {} does not exist!".format(config_file))
        return 2

    event_listener = DependentStartup(args, config_file)
    event_listener.run_and_listen()


def run():
    exit_code = 0
    try:
        main()
    except:  # noqa: E722
        log.error("Error occured:", exc_info=sys.exc_info())
        exit_code = 3
    sys.exit(exit_code)


if __name__ == '__main__':
    run()
