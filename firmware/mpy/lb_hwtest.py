# lb_hwtest.py - state of the interactive button test (pure logic; no I/O)
#
# Feed it button events and the time; it says what to show on the 16x2 display. Progress is
# "n/total" on line 1; line 2 names the button being held (with a running timer for a single
# button, which also checks the PTT hold feel) or the last one released.

import lb_lcd
import lb_ticks

ORDER = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "PTT")
DONE_HOLD_MS = 4000  # how long the all-clear stays up after the last button is released


class HwTest:
    def __init__(self, names=ORDER, done_hold_ms=DONE_HOLD_MS):
        self._names = list(names)
        self._seen = []
        self._down = {}
        self._last = None
        self._complete_at = None  # when the last unseen button was first pressed
        self._released_at = None  # when everything was released after completion
        self._done_hold = done_hold_ms

    def button(self, name, down, now):
        if name not in self._names:
            return
        if down:
            self._down[name] = now
            self._last = name
            self._released_at = None
            if name not in self._seen:
                self._seen.append(name)
                if len(self._seen) == len(self._names):
                    self._complete_at = now
        else:
            self._down.pop(name, None)
            if self._complete_at is not None and not self._down:
                self._released_at = now

    def seen(self):
        return list(self._seen)

    def missing(self):
        return [n for n in self._names if n not in self._seen]

    def complete(self):
        return self._complete_at is not None

    def finished(self, now):
        """All buttons seen, all released, and the all-clear has been up long enough."""
        return (self._released_at is not None and not self._down
                and lb_ticks.diff(now, self._released_at) >= self._done_hold)

    def lines(self, now):
        total = len(self._names)
        done = self.complete()
        l1 = lb_lcd.two("ALL %d OK!" % total if done else "Button test",
                        "" if done else "%d/%d" % (len(self._seen), total))
        if self._down:
            held = [n for n in self._names if n in self._down]
            if len(held) == 1:
                tenths = max(0, lb_ticks.diff(now, self._down[held[0]]) // 100)
                l2 = "> %s %d.%ds" % (held[0], tenths // 10, tenths % 10)
            else:
                l2 = "> " + " ".join(held)
        elif done:
            l2 = "Test complete"
        elif self._last:
            l2 = "last: " + self._last
        else:
            l2 = "Press a button"
        return lb_lcd.fit(l1), lb_lcd.fit(l2)
