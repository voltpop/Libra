# lb_sleep.py - when the LCD and the LED should go dark (pure logic: time and screen in, bool out)
#
# After `timeout_ms` with no button or console activity the display and LED sleep. They wake on
# any button press (that press is swallowed so nobody acts on a screen they cannot see), and by
# themselves when the device needs attention: an approval is waiting for PTT, a new haptic cue
# fired (a host request, an error...) or the device was wiped. 0 disables sleeping.

import lb_ticks
import lb_led

ALWAYS_AWAKE = ("Wiped",)


class IdleSleep:
    def __init__(self, timeout_ms):
        self._timeout = timeout_ms
        self._last = None      # ticks of the last activity
        self._asleep = False
        self._seq = None       # last haptic event counter seen
        self._swallow = set()  # buttons whose wake press is still down

    def asleep(self):
        return self._asleep

    def _wake(self, now):
        self._asleep = False
        self._last = now

    def activity(self, now):
        """Something happened (a button, a console line). True if it woke us up."""
        woke = self._asleep
        self._wake(now)
        return woke

    def button(self, name, down, now):
        """Gate a button event: True to pass it on to the UI, False to swallow it."""
        if down:
            if self.activity(now):
                self._swallow.add(name)
                return False
            return True
        self._last = now
        if name in self._swallow:
            self._swallow.discard(name)
            return False
        return True

    def update(self, now, sc):
        """Call every loop with the UI screen dict. Returns True while asleep."""
        if self._last is None:
            self._last = now
        hap = sc.get("haptic") or {}
        seq = hap.get("seq")
        fired = self._seq is not None and seq != self._seq
        self._seq = seq
        if self._timeout <= 0:
            return False
        needs_you = sc.get("id") in lb_led.WAIT_SCREENS or sc.get("id") in ALWAYS_AWAKE or fired
        if needs_you:
            self._wake(now)
        elif not self._asleep and lb_ticks.diff(now, self._last) >= self._timeout:
            self._asleep = True
        return self._asleep
