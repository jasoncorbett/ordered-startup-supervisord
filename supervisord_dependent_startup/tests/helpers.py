from __future__ import print_function

import logging
import os
import shutil
import tempfile

from testfixtures import LogCapture, StringComparison

from . import log_utils, utils

logger = logging.getLogger(log_utils.plugin_tests_logger_name)


log_capture_fmt = "[%(index_str)s] %(name)s %(filename)s:%(lineno)-4s [%(levelname)-7s]  %(message)s"


class LogCapturePrintable(LogCapture):

    def __init__(self, formatter=None, **args):
        # Set names to capture only the plugin logger
        args['names'] = (log_utils.plugin_logger_name, )
        super(LogCapturePrintable, self).__init__(**args)
        self.formatter = formatter

    def emit(self, record):
        record.index = len(self.records)
        super(LogCapturePrintable, self).emit(record)

    def _row_attrs(self, record, attributes):
        for a in attributes:
            value = getattr(record, a, None)
            if callable(value):
                value = value()
            yield a, value

    def __len__(self):
        return len(self.records)

    def __str__(self):
        if not self.records:
            return 'No log statements captured for logs: %s' % (self.names)
        ret = ""
        for r in self.format_records():
            ret += "%s\n" % r
        return ret

    def format_records(self):
        if not self.formatter:
            self.formatter = logging.Formatter(fmt=log_capture_fmt)
        ret = []
        for i, e in enumerate(self.actual()):
            record = self.records[i]
            record.index_str = "%-{}d".format(len(str(len(self.records)))) % (record.index)
            ret.append(self.formatter.format(record))
        return ret

    def match_regex(self, regex_pattern, name=None, level=None):
        matches = []
        for r in self.records:
            if name and r.name != name:
                continue
            if level and r.levelname != level:
                continue
            if r.getMessage() != StringComparison(regex_pattern):
                continue
            matches.append(r)
        return matches


def get_log_capture_printable(formatter=None, fmt=None, colors=True, capture_fmt=True):
    """
    Args:
        capture_fmt (bool): Use the default capture format. If False, get the format from the consol logger

    """
    if fmt is None and capture_fmt:
        fmt = log_capture_fmt

    if fmt is None and formatter is None:
        root = logging.getLogger()
        if not fmt:
            for h in root.handlers:
                if h.get_name() == log_utils.logging_console_handler_name:
                    formatter = h.formatter
                    break
    if colors:
        formatter = log_utils.ColorFormatter(formatter=formatter, fmt=fmt, colors=colors, update_fmt_for_colors=True)

    return LogCapturePrintable(formatter=formatter)


class TempDir(object):
    """
    class for temporary directories
    creates a (named) directory which is deleted after use.
    All files created within the directory are destroyed

    """
    def __init__(self, suffix="", prefix=None, basedir=None, name=None, clear=True, cleanup=True, id=None):
        """
        Args:
            suffix(str): Suffix to add to directory name
            prefix(str): Prefix to add to directory name
            basedir(str): The base path there to create the dir. Defaults to /tmp
            clear(bool): Clear directory if already exists
            cleanup(bool): Clear directory on exit

        If name is given, no random name value will be generated.
        """
        self.cleanup = cleanup
        self.id = id
        if prefix is None:
            prefix = tempfile.gettempprefix()
        if basedir is None:
            basedir = tempfile.gettempdir()

        # Use the given name as directory name
        if name:
            path = os.path.join(basedir, name)

            if clear:
                logger.debug("Clearing temporary directory: %s", path)
                shutil.rmtree(path, ignore_errors=True)

            utils.mkdir(path, ignore_errors=False)
            self.name = path
        else:
            self.name = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=basedir)

    def __del__(self):
        try:
            if self.name:
                self.dissolve()
        except AttributeError:
            pass

    def __enter__(self):
        return self.name

    def __exit__(self, *errstuff):
        self.dissolve()

    def dissolve(self):
        """remove all files and directories created within the tempdir"""
        if self.name and self.cleanup:
            try:
                shutil.rmtree(self.name)
            except OSError as err:
                logger.warn("Error when cleaning up directory %s%s: %s", self.name, " (id: %s)" % self.id, err)
                raise

        self.name = ""

    def __str__(self):
        if self.name:
            return "temporary directory at: %s%s" % (self.name, " (id: %s)" % self.id)
        else:
            return "dissolved temporary directory"
