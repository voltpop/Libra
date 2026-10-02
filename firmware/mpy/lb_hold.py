# lb_hold.py - hold-to-confirm engine (pure logic; the UI feeds it samples)
#
# Spec: LIBRA.md "Hold-to-confirm" and the approval gate. Duration scales with risk
# (about 0.5 s login, 1.5 s signing or deleting). The request is captured when the hold
# starts and any change resets it. Releasing early is a free abort.
#
# Hardening beyond the spec text (each has a test):
#   - A hold starts only on a fresh press (rising edge) while a request is on screen, so a
#     pocket press, or a button already down when the request appears, never counts.
#   - After any reset the button must be released before a new hold can start. Otherwise
#     holding through a swap from request A to request B would approve B.
#   - A stalled sampling loop (gap > max_gap_ms) or a clock that goes backwards cancels the
#     hold: a release and re-press could have been missed in the gap.
#   - A hold commits exactly once; it must be released before the next one.
#   - An unknown risk kind gets the longest duration, never the shortest.
#
# Call update() every 10 to 50 ms with the button level and the request now shown.

import lb_ticks

IDLE = "IDLE"
HOLDING = "HOLDING"
COMMITTED = "COMMITTED"  # held past the duration; waiting for release
RELEASE = "RELEASE"      # reset happened; waiting for the button to come up

DEFAULT_HOLD_MS = {"login": 500, "sign": 1500, "delete": 1500}
MIN_HOLD_MS = 300   # configuration can never weaken the gesture below this
MAX_HOLD_MS = 5000
DEFAULT_MAX_GAP_MS = 250


class HoldError(Exception):
    pass


class Status:
    __slots__ = ("state", "permille", "committed", "reason")

    def __init__(self, state, permille, committed, reason):
        self.state = state
        self.permille = permille    # progress 0..1000 for the ring or bar
        self.committed = committed  # True on exactly one update: fire the haptic tick
        self.reason = reason        # why a hold ended early, else None

    def __repr__(self):
        return "<Status %s %d %s %s>" % (self.state, self.permille, self.committed, self.reason)


class HoldEngine:
    def __init__(self, durations=None, max_gap_ms=DEFAULT_MAX_GAP_MS):
        d = dict(DEFAULT_HOLD_MS)
        if durations:
            d.update(durations)
        for kind, ms in d.items():
            if (not isinstance(kind, str) or isinstance(ms, bool) or not isinstance(ms, int)
                    or not MIN_HOLD_MS <= ms <= MAX_HOLD_MS):
                raise HoldError("bad hold duration for %r" % (kind,))
        if isinstance(max_gap_ms, bool) or not isinstance(max_gap_ms, int) \
                or not 10 <= max_gap_ms <= 1000:
            raise HoldError("bad max_gap_ms")
        self._dur = d
        self._longest = max(d.values())
        self._gap = max_gap_ms
        self.reset()
        self._state = IDLE  # a new engine has seen no button yet
        self._prev = False

    def reset(self):
        """Drop everything (call on lock). A button still down must be released first."""
        self._state = RELEASE
        self._prev = True
        self._last_t = None
        self._snap = None
        self._t0 = 0
        self._need = 0

    def cancel(self):
        """The user pressed Back or the request was withdrawn."""
        if self._state in (HOLDING, COMMITTED):
            self._state = RELEASE if self._prev else IDLE
        self._snap = None

    def required_ms(self, kind):
        return self._dur.get(kind, self._longest)

    def update(self, now, pressed, request=None, kind=None):
        pressed = bool(pressed)
        committed = False
        reason = None

        if self._last_t is not None and self._state == HOLDING:
            dt = lb_ticks.diff(now, self._last_t)
            if dt < 0 or dt > self._gap:
                reason = "CLOCK" if dt < 0 else "GAP"
                self._abort(pressed)
        self._last_t = now

        if self._state == IDLE:
            if pressed:
                if self._prev or request is None:
                    # already down when we looked, or nothing to approve: not a hold.
                    # A press with no request is just a tap; remember it so a request
                    # that appears under a held button still cannot start a hold.
                    self._state = RELEASE if self._prev else IDLE
                else:
                    self._snap = (request, kind)
                    self._t0 = now
                    self._need = self.required_ms(kind)
                    self._state = HOLDING
        elif self._state == RELEASE:
            if not pressed:
                self._state = IDLE
        elif self._state == HOLDING:
            if not pressed:
                reason = "RELEASED"
                self._state = IDLE
                self._snap = None
            elif request is None or (request, kind) != self._snap:
                reason = "REQUEST_CHANGED"
                self._abort(pressed)
            elif lb_ticks.diff(now, self._t0) >= self._need:
                self._state = COMMITTED
                committed = True
        elif self._state == COMMITTED:
            if not pressed:
                self._state = IDLE
                self._snap = None

        self._prev = pressed
        if self._state == COMMITTED:
            permille = 1000
        elif self._state == HOLDING:
            permille = min(999, lb_ticks.diff(now, self._t0) * 1000 // self._need)
        else:
            permille = 0
        return Status(self._state, permille, committed, reason)

    def _abort(self, pressed):
        self._snap = None
        self._state = RELEASE if pressed else IDLE
