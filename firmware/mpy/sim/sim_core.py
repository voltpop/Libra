# sim_core.py - the simulator's state, QA hooks and note capture (host only, CPython)
#
# Wraps lb_rig.Rig (the real session/oath/hold/UI modules over simulated drivers) with a lock,
# a background tick, panel actions for testers, and a "this needs work" note that saves the
# current screen and the last inputs so feedback is concrete.

import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import lb_fakes  # noqa: E402
import lb_session  # noqa: E402
import lb_ticks  # noqa: E402
from lb_rig import Rig  # noqa: E402
from lb_samples import HOST_REQUESTS, REPLACEMENT, SAMPLES  # noqa: E402

COMBO_HINT = "U D L R U D L R U D (QA hint: the device never shows this)"
MAX_NOTE = 2000


class Sim:
    def __init__(self, notes_path=None):
        self.lock = threading.RLock()
        self.notes_path = notes_path or os.path.join(HERE, "qa_notes.jsonl")
        self.rig = Rig(real_clock=True)
        self.panel_log = []
        self.led_rgb = [0, 0, 0]

    # ---- device input (all under the lock)

    def tick(self):
        with self.lock:
            self.rig.ui.tick()
            self.led_rgb = list(self.rig.led_color())  # sampled every tick so short blinks are seen

    def button(self, name, down):
        with self.lock:
            self.rig.ui.button(name, down)

    def scan(self, index):
        with self.lock:
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(SAMPLES):
                raise ValueError("no such sample")
            return self.rig.ui.scan(SAMPLES[index][1])

    def panel(self, action, **kw):
        with self.lock:
            r = self.rig
            self._plog(action, kw)
            if action == "host_request":
                kind = kw.get("kind")
                if kind not in HOST_REQUESTS:
                    raise ValueError("unknown request kind")
                r.session.request(kind, "USB", HOST_REQUESTS[kind])
            elif action == "host_replace":
                p = r.session.pending()
                kind = kw.get("kind") or (p["kind"] if p else "SIGN")
                if kind not in REPLACEMENT:
                    raise ValueError("unknown request kind")
                r.session.request(kind, "USB", REPLACEMENT[kind])
            elif action == "fp":
                if kw.get("mode") not in ("match", "nomatch", "error"):
                    raise ValueError("bad fingerprint mode")
                r.fp.mode = kw["mode"]
            elif action == "clock_trusted":
                r.clock.trusted_flag = bool(kw.get("value"))
            elif action == "warp":
                ms = kw.get("ms")
                if not isinstance(ms, int) or isinstance(ms, bool) or not 0 < ms <= 3600000:
                    raise ValueError("bad warp")
                r.clock.advance(ms)
            elif action == "power_cycle":
                r.boot()
            elif action == "reset":
                self.rig = Rig(real_clock=True)
            else:
                raise ValueError("unknown action")

    def _plog(self, action, kw):
        self.panel_log.append((time.time(), action, dict(kw)))
        del self.panel_log[:-100]

    # ---- output

    def _trail(self, n):
        now = self.rig.clock.ticks()
        return [[lb_ticks.diff(now, t), k, x] for (t, k, x) in self.rig.ui.trail[-n:]]

    def state(self):
        with self.lock:
            r = self.rig
            s = r.session
            return {
                "screen": r.ui.screen(),
                "led": list(self.led_rgb),
                "samples": [n for n, _ in SAMPLES],
                "hostKinds": list(HOST_REQUESTS),
                "debug": {
                    "session": s.state(), "wiped": s.wiped(), "attempts_used": r.ks.attempts(),
                    "pending": s.pending(), "fingerprint": r.fp.mode,
                    "clock_trusted": r.clock.trusted_flag, "accounts": len(r.oath.list()),
                    "combo": COMBO_HINT,
                },
                "trail": self._trail(40),
            }

    def note(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty note")
        with self.lock:
            st = self.state()
            rec = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note": text.strip()[:MAX_NOTE],
                "screen": st["screen"]["id"], "title": st["screen"]["title"],
                "lines": st["screen"]["lines"], "toast": st["screen"]["toast"],
                "debug": st["debug"], "trail": st["trail"],
                "panel": [[round(t), a, k] for (t, a, k) in self.panel_log[-10:]],
            }
            with open(self.notes_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            return rec["screen"]
