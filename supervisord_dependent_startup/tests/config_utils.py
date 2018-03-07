from __future__ import print_function

import os

from supervisor.datatypes import boolean
from supervisor.options import expand


def expand_string(name, value):
    expansions = {}
    for k, v in os.environ.items():
        expansions['ENV_%s' % k] = v
    return expand(value, expansions, name)


def donothing(value):
    return value


def safe_boolean(value):
    try:
        return boolean(value)
    except ValueError:
        return value
