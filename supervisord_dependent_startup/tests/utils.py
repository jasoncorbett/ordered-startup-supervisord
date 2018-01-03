from __future__ import print_function

import logging
import os
import pprint
import sys

try:
    from termcolor import colored, cprint
    termcolor = True
except ImportError:
    termcolor = False

    def cprint(*arg, **kwargs):
        print(*arg)

    def colored(text, color):
        return text

# isort:imports-localfolder
from . import get_level_from_string, plugin_logger_name

# Name of logger used by unit tests
plugin_tests_logger_name = 'dependent_startup_unit_tests'

pp = pprint.PrettyPrinter(indent=4)


def format_object(obj):
    return pp.pformat(obj)


DEFAULT_CONSOL_LOG_LEVEL = logging.CRITICAL


def setup_tests_logging(plugin_str_level, tests_str_level, log_format):

    plugin_log_level = DEFAULT_CONSOL_LOG_LEVEL
    tests_log_level = DEFAULT_CONSOL_LOG_LEVEL

    def get_level(str_level):
        log_level = get_level_from_string(str_level, 'notset')
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
    formatter = logging.Formatter(log_format)
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


def write_file(name, content):
    with open(name, 'w') as f:
        f.write(content)


def mkdir(path, ignore_errors=True):
    try:
        os.mkdir(path)
    except OSError:
        if not ignore_errors:
            raise
