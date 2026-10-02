# lb_led.py - what the RGB status LED should show (pure logic: screen in, colour out)
#
# color(now, screen) -> (r, g, b), each 0..255 and already scaled by BRIGHTNESS. Feed it the
# UI's screen() dict about every 20 ms.
#
# Palette: BLUE = powered, RED = error, GREEN = success. Priority, highest first:
#   1. a short cue, started by a haptic event:
#        commit (green flash), success (green double blink), error (red triple blink),
#        tap (white blink), abort (orange blip: a hold released too early), notify (cyan pulses)
#   2. a PTT hold in progress: the blue turns to green as the hold fills, ending in the commit flash
#   3. waiting for a PTT hold (an approval is pending on screen): the colour sweeps continuously
#      green <-> blue through teal (never red: red is only ever an error), so it is plainly
#      "doing something, waiting for you" without looking like any of the one-shot cues
#   4. a code on screen: steady purple (a secret is visible)
#   5. Wiped: solid red. Locked: the blue breathing slowly. Unlocked: a dim steady blue.

import lb_ticks

BRIGHTNESS = 0.5  # global cap, 0..1: a status light, not a torch

OFF = (0, 0, 0)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
ORANGE = (255, 70, 0)
CYAN = (0, 200, 255)
WHITE = (255, 255, 255)
PURPLE = (150, 0, 255)
BLUE = (0, 60, 255)
POWERED = 0.3  # the steady "powered" blue is kept dim

# cue name -> list of (duration_ms, colour) segments, played in order
CUES = {
    "commit": [(450, GREEN)],
    "success": [(130, GREEN), (100, OFF), (130, GREEN), (100, OFF)],
    "error": [(100, RED), (90, OFF), (100, RED), (90, OFF), (100, RED), (90, OFF)],
    "notify": [(250, CYAN), (150, OFF), (250, CYAN), (150, OFF)],
    "tap": [(90, WHITE)],
    "abort": [(160, ORANGE)],
}
BREATH_PERIOD_MS = 3200
WAIT_PERIOD_MS = 2400  # one full green-blue-green sweep while waiting for PTT
# screens that are waiting for a PTT hold (the approval screens; ComboApprove waits for a combo)
WAIT_SCREENS = ("ConfirmOTP", "RevealPrompt", "HostRequest", "SetTime", "ConfirmSetting")


def _sweep(phase, period):
    """Green to blue and back through teal, integers only. Never any red: red means error."""
    half = period // 2
    f = (phase if phase < half else period - phase) * 255 // half  # 0..255..0
    return (0, min(255, 2 * (255 - f)), min(255, 2 * f))  # bright all the way: teal never dips dark


def _scale(c, k=1.0):
    return (int(c[0] * BRIGHTNESS * k), int(c[1] * BRIGHTNESS * k), int(c[2] * BRIGHTNESS * k))


def cue_length(name):
    return sum(d for d, _ in CUES[name])


class LedEngine:
    def __init__(self):
        self._seq = None
        self._cue = None
        self._t0 = 0

    def reset(self):
        self._seq = None
        self._cue = None

    def _start_cue(self, name, now):
        if name in CUES:
            self._cue = name
            self._t0 = now

    def _cue_colour(self, now):
        if self._cue is None:
            return None
        e = lb_ticks.diff(now, self._t0)
        if e < 0:
            self._cue = None
            return None
        for dur, col in CUES[self._cue]:
            if e < dur:
                return col
            e -= dur
        self._cue = None
        return None

    def color(self, now, sc):
        hap = sc.get("haptic") or {}
        seq = hap.get("seq")
        if self._seq is None:
            self._seq = seq  # the first frame only records where the event counter is
        elif seq != self._seq:
            self._seq = seq
            self._start_cue(hap.get("kind"), now)
        c = self._cue_colour(now)
        if c is not None:
            return _scale(c)
        hold = sc.get("hold")
        if hold:  # progress 1..1000: from the powered blue to the success green
            p = max(0, min(1000, hold))
            base = _scale(BLUE, POWERED)
            end = _scale(GREEN)
            return tuple(base[i] + int((end[i] - base[i]) * p / 1000) for i in range(3))  # toward zero
        sid = sc.get("id")
        if sid in WAIT_SCREENS:  # waiting for PTT: keep changing colour until it is held or dismissed
            return _scale(_sweep(lb_ticks.diff(now, 0) % WAIT_PERIOD_MS, WAIT_PERIOD_MS))
        if sid == "TOTPCode" and (sc.get("body") or {}).get("code"):
            return _scale(PURPLE)
        if sid == "Wiped":
            return _scale(RED)
        if (sc.get("status") or {}).get("locked") or sid == "Locked":
            phase = lb_ticks.diff(now, 0) % BREATH_PERIOD_MS
            half = BREATH_PERIOD_MS // 2
            tri = phase if phase < half else BREATH_PERIOD_MS - phase  # 0..half..0
            return _scale(BLUE, 0.08 + 0.52 * tri / half)  # breathes between very dim and half
        return _scale(BLUE, POWERED)  # powered and unlocked
