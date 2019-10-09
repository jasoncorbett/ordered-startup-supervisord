from __future__ import print_function

import os

from supervisord_dependent_startup.supervisord_dependent_startup import (DependentStartup,
                                                                         DependentStartupError,
                                                                         get_all_configs,
                                                                         process_states, Service,
                                                                         ServiceOptions,
                                                                         ServicesHandler, xmlrpclib)

from .log_utils import setup_tests_logging

__all__ = ['DependentStartup', 'ServiceOptions', 'DependentStartupError', 'Service',
           'ServicesHandler', 'get_all_configs', 'process_states', 'xmlrpclib']


setup_tests_logging()

valid_booleans = {'true': True, 'True': True, 'TRUE': True, 't': True, '1': True}
cleanup_tmp_dir = os.environ.get('CLEANUP_TESTS', "True") in valid_booleans

# Name of directory to store supervisor config files.  If unset, a random value is used
test_tmp_dir = os.environ.get('TEST_TMP_DIR', None)
