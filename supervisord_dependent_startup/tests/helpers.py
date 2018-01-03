from __future__ import print_function

import logging
import os
import shutil
import tempfile

from testfixtures import LogCapture

from . import utils

logger = logging.getLogger(utils.plugin_tests_logger_name)


class LogCapturePrintable(LogCapture):

    list_fmt = "{name}  {filename}:{lineno:<4} [{levelname:7}]  {msg}\n"

    def __str__(self):
        if not self.records:
            return 'No logging captured'
        ret = ""
        for i, e in enumerate(self.actual()):
            ret += self.list_fmt.format(index=i, **self.records[i].__dict__)
        return ret

    def __init__(self, **args):
        args['names'] = (utils.plugin_logger_name, )
        super(LogCapturePrintable, self).__init__(**args)


class TempDir(object):
    """
    class for temporary directories
    creates a (named) directory which is deleted after use.
    All files created within the directory are destroyed

    """
    def __init__(self, suffix="", prefix=None, basedir=None, name=None, clear=True, cleanup=True):
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
            shutil.rmtree(self.name)
        self.name = ""

    def __str__(self):
        if self.name:
            return "temporary directory at: %s" % (self.name,)
        else:
            return "dissolved temporary directory"
