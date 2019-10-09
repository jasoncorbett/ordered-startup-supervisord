from __future__ import print_function

import os
import pprint

try:
    from termcolor import colored, cprint
    termcolor = True
except ImportError:
    termcolor = False

    def cprint(*arg, **kwargs):
        print(*arg)

    def colored(text, color):
        return text


pp = pprint.PrettyPrinter(indent=4)


def format_object(obj):
    return pp.pformat(obj)


def write_file(name, content):
    with open(name, 'w') as f:
        f.write(content)


def mkdir(path, ignore_errors=True):
    try:
        os.mkdir(path)
    except OSError:
        if not ignore_errors:
            raise
