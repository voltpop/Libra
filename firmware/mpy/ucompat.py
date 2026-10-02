# ucompat.py - fills in unittest assertions that MicroPython's unittest lacks
#
# Import after `import unittest`. Only adds a method when it is missing, so on CPython this
# does nothing. Tests-only; not part of the firmware.

import unittest

_T = unittest.TestCase


def _add(name, fn):
    if not hasattr(_T, name):
        setattr(_T, name, fn)


def _not_in(self, a, b, msg=None):
    if a in b:
        raise AssertionError(msg or "%r unexpectedly found in %r" % (a, b))


def _greater(self, a, b, msg=None):
    if not a > b:
        raise AssertionError(msg or "%r not greater than %r" % (a, b))


def _less(self, a, b, msg=None):
    if not a < b:
        raise AssertionError(msg or "%r not less than %r" % (a, b))


_add("assertNotIn", _not_in)
_add("assertGreater", _greater)
_add("assertLess", _less)
