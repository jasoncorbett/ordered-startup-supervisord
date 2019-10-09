from __future__ import print_function

import logging
import os
import sys

from supervisord_dependent_startup.supervisord_dependent_startup import (get_log_level_from_string,
                                                                         plugin_logger_name)

# isort:imports-localfolder
from .log_color_fmt import ColorFormatter

# Name of logger used by unit tests
plugin_tests_logger_name = 'dependent_startup_unit_tests'
logging_console_handler_name = 'console_handler'

DEFAULT_CONSOL_LOG_LEVEL = logging.CRITICAL

# Set the environment variable TESTS_LOG_LEVEL to a proper log level to output
# the log statements of the tests logger (plugin_tests_logger_name)
env_tests_log_level = os.environ.get('TESTS_LOG_LEVEL', "")

# Set the environment variable PLUGIN_LOG_LEVEL to a proper log level to output
# the log statements from the supervisord_dependent_startup eventhandler
env_plugin_log_level = os.environ.get('PLUGIN_LOG_LEVEL', "")

default_log_format = "%(asctime)s - %(name)-29s %(filename)35s:%(lineno)-3s - [%(levelname)-7s] %(message)s"
log_format = os.environ.get('TESTS_LOG_FORMAT', default_log_format)


def setup_tests_logging():
    setup_tests_loggers(env_plugin_log_level, env_tests_log_level, log_format)


def setup_tests_loggers(plugin_str_level, tests_str_level, log_format):
    plugin_log_level = DEFAULT_CONSOL_LOG_LEVEL
    tests_log_level = DEFAULT_CONSOL_LOG_LEVEL

    def get_level(str_level):
        log_level = get_log_level_from_string(str_level, 'notset')
        if log_level == logging.NOTSET:
            raise Exception("Bad log level given: '%s'" % (str_level))
        return log_level

    if plugin_str_level:
        plugin_log_level = get_level(plugin_str_level)
    if tests_str_level:
        tests_log_level = get_level(tests_str_level)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.set_name(logging_console_handler_name)
    formatter = ColorFormatter(fmt=log_format)
    console_handler.setFormatter(formatter)

    class ConsoleFiler(logging.Filter):

        def filter(self, rec):
            if rec.name == plugin_logger_name:
                return rec.levelno >= plugin_log_level
            elif rec.name == plugin_tests_logger_name:
                return rec.levelno >= tests_log_level
            else:
                return True

    console_handler.addFilter(ConsoleFiler())

    root.addHandler(console_handler)
