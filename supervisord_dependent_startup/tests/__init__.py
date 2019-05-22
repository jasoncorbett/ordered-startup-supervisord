from __future__ import print_function

import os

from supervisord_dependent_startup.supervisord_dependent_startup import (DependentStartup,
                                                                         DependentStartupError,
                                                                         Service, ServiceOptions,
                                                                         ServicesHandler, StringIO,
                                                                         default_log_format,
                                                                         get_all_configs,
                                                                         get_level_from_string,
                                                                         get_str_from_level,
                                                                         plugin_logger_name,
                                                                         process_states)

from .utils import setup_tests_logging

__all__ = ['DependentStartup', 'ServiceOptions', 'DependentStartupError', 'Service',
           'ServicesHandler', 'get_all_configs', 'process_states', 'StringIO',
           'plugin_logger_name', 'get_level_from_string', 'get_str_from_level']


env_tests_log_level = os.environ.get('TESTS_LOG_LEVEL', "")
env_plugin_log_level = os.environ.get('PLUGIN_LOG_LEVEL', "")
log_format = os.environ.get('TESTS_LOG_FORMAT', default_log_format)

setup_tests_logging(env_plugin_log_level, env_tests_log_level, log_format)

valid_booleans = {'true': True, 'True': True, 'TRUE': True, 't': True, '1': True}
cleanup_tmp_dir = os.environ.get('CLEANUP_TESTS', "True") in valid_booleans

# Name of directory to store supervisor config files.  If unset, a random value is used
test_tmp_dir = os.environ.get('TEST_TMP_DIR', None)
