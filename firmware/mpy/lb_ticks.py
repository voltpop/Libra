# lb_ticks.py - wrap-safe millisecond arithmetic (MicroPython time.ticks_ms wraps at 2**30)
#
# Same semantics as time.ticks_diff, written in pure Python so it also runs on CPython.
# Valid while the two values are less than half a period (about 149 hours) apart.

PERIOD = 1 << 30
_HALF = PERIOD >> 1


def diff(a, b):
    """Signed a - b in ms, correct across a wrap of the tick counter."""
    return ((a - b + _HALF) % PERIOD) - _HALF


def add(t, ms):
    return (t + ms) % PERIOD
