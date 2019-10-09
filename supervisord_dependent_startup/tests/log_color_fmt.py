from __future__ import print_function

import copy
import logging
import re

RED = 31
GREEN = 32
YELLOW = 33
BLUE = 34
MAGENTA = 35
CYAN = 36
WHITE = 37

WHITE_ON_RED_BG = 41
WHITE_ON_BLUE_BG = 44


LEVEL_TO_COLORS_MAPPING = {
    'TRACE': WHITE,
    'DEBUG': CYAN,
    'INFO': GREEN,
    'WARNING': YELLOW,
    'ERROR': RED,
    'CRITICAL': WHITE_ON_RED_BG,
}

PREFIX = '\033['
SUFFIX = '\033[0m'


def get_new_key_fmt(m_dict):
    """
    m_dict: {'width': '5', 'fmt': '%(levelname)-5s', 'align': '-', 'key': 'levelname'}
    """
    if 'width' not in m_dict:
        return m_dict['fmt']

    mid_width = int(m_dict['width'])
    mid_width += 9  # Increase width with the number is invisible characters added for coloring
    new_fmt = "%({}){}s".format(m_dict['key'], "%s%s" % (m_dict['align'], mid_width))
    return new_fmt


class ColorFormatter(logging.Formatter):

    colored_fields = ['levelname']

    def __init__(self, formatter=None, colors=True, update_fmt_for_colors=True, **kwargs):
        if formatter:
            kwargs['fmt'] = formatter._fmt
            kwargs['datefmt'] = formatter.datefmt
        logging.Formatter.__init__(self, **kwargs)
        self.fmt_orig = self._fmt
        self.colors = colors
        if not isinstance(formatter, ColorFormatter) and colors and update_fmt_for_colors:
            self.update_log_fmt()

    def update_log_fmt(self):
        """Update the log format string to correct for color characters.

        If any format keys have a minium width for the field, this value
        will not be sufficient when the invisible color characters are
        added for the value. Therefore we must update the key format
        with an adjusted width for the value we colorize
        """
        # Matches format keys on the format on the form "%(levelname)-5s"
        matches = re.finditer(r'(?P<fmt>%\((?P<key>[^\s%]+)\)(?:(?P<align>(?:-)?)(?P<width>[\d]+))?s)', self._fmt)
        for fmt_match in matches:
            m_dict = fmt_match.groupdict()
            if m_dict['key'] in self.colored_fields:
                new_fmt = get_new_key_fmt(m_dict)
                if m_dict['fmt'] != new_fmt:
                    self._fmt = self._fmt.replace(m_dict['fmt'], new_fmt)

    def format(self, record):
        colored_record = copy.copy(record)
        # Only color the levelname for now
        levelname = colored_record.levelname
        color_code = WHITE
        if self.colors:
            color_code = LEVEL_TO_COLORS_MAPPING.get(levelname, WHITE)
        colored_levelname = ('{0}{1}m{2}{3}').format(PREFIX, color_code, levelname, SUFFIX)
        colored_record.levelname = colored_levelname
        return logging.Formatter.format(self, colored_record)
