import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_hold as lh
import lb_ticks

STEP = 50


class Rng:  # xorshift32 so the randomized test runs on MicroPython too
    def __init__(self, seed):
        self.s = seed or 1

    def below(self, n):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s % n


def run(eng, t0, ms, pressed=True, request="Sign: commit abc", kind="sign", step=STEP):
    """Sample from t0 for ms milliseconds; return (list of statuses, next time)."""
    out = []
    t = t0
    end = t0 + ms
    while t <= end:
        out.append(eng.update(t, pressed, request, kind))
        t += step
    return out, t


def commits(statuses):
    return sum(1 for s in statuses if s.committed)


class Duration(unittest.TestCase):
    def test_login_commits_at_500_not_before(self):
        eng = lh.HoldEngine()
        for t in range(0, 500, STEP):
            s = eng.update(t, True, "Login", "login")
            self.assertFalse(s.committed, t)
        s = eng.update(500, True, "Login", "login")
        self.assertTrue(s.committed)
        self.assertEqual((s.state, s.permille), (lh.COMMITTED, 1000))

    def test_sign_and_delete_need_1500(self):
        for kind in ("sign", "delete"):
            eng = lh.HoldEngine()
            sts, _ = run(eng, 0, 1450, kind=kind)
            self.assertEqual(commits(sts), 0)
            self.assertTrue(eng.update(1500, True, "Sign: commit abc", kind).committed)

    def test_unknown_kind_gets_longest(self):
        eng = lh.HoldEngine()
        self.assertEqual(eng.required_ms("login"), 500)
        self.assertEqual(eng.required_ms("mystery"), 1500)
        self.assertEqual(eng.required_ms(None), 1500)
        sts, _ = run(eng, 0, 1450, kind="mystery")
        self.assertEqual(commits(sts), 0)

    def test_progress_monotonic_and_capped(self):
        eng = lh.HoldEngine()
        sts, _ = run(eng, 0, 1500)
        p = [s.permille for s in sts]
        self.assertEqual(p, sorted(p))
        self.assertEqual(p[0], 0)
        self.assertTrue(all(x < 1000 for x in p[:-1]))
        self.assertEqual(p[-1], 1000)

    def test_commits_exactly_once_while_held(self):
        eng = lh.HoldEngine()
        sts, t = run(eng, 0, 5000)
        self.assertEqual(commits(sts), 1)

    def test_new_hold_after_release(self):
        eng = lh.HoldEngine()
        sts, t = run(eng, 0, 1500)
        self.assertEqual(commits(sts), 1)
        eng.update(t, False, "Sign: commit abc", "sign")
        sts, _ = run(eng, t + STEP, 1500)
        self.assertEqual(commits(sts), 1)

    def test_custom_durations_and_floor(self):
        eng = lh.HoldEngine({"login": 800, "backup": 2000})
        self.assertEqual((eng.required_ms("login"), eng.required_ms("backup")), (800, 2000))
        for bad in (299, 5001, 0, -1, True, 500.0, "500", None):
            with self.assertRaises(lh.HoldError, msg=repr(bad)):
                lh.HoldEngine({"login": bad})
        with self.assertRaises(lh.HoldError):
            lh.HoldEngine({5: 500})
        for g in (5, 1001, True, "250"):
            with self.assertRaises(lh.HoldError, msg=repr(g)):
                lh.HoldEngine(max_gap_ms=g)


class Aborts(unittest.TestCase):
    def test_early_release_is_free_abort(self):
        eng = lh.HoldEngine()
        sts, t = run(eng, 0, 1000)
        s = eng.update(t, False, "Sign: commit abc", "sign")
        self.assertEqual((s.state, s.reason, s.committed), (lh.IDLE, "RELEASED", False))
        self.assertEqual(commits(sts), 0)

    def test_request_change_resets_and_needs_new_press(self):
        eng = lh.HoldEngine()
        sts, t = run(eng, 0, 1000, request="Sign: A")
        s = eng.update(t, True, "Sign: B", "sign")
        self.assertEqual((s.state, s.reason), (lh.RELEASE, "REQUEST_CHANGED"))
        # holding on through B for a very long time must never approve B
        sts, t = run(eng, t + STEP, 10000, request="Sign: B")
        self.assertEqual(commits(sts), 0)
        eng.update(t, False, "Sign: B", "sign")
        sts, _ = run(eng, t + STEP, 1500, request="Sign: B")
        self.assertEqual(commits(sts), 1)

    def test_kind_change_with_same_text_resets(self):
        eng = lh.HoldEngine()
        run(eng, 0, 400, kind="login")
        s = eng.update(450, True, "Sign: commit abc", "sign")
        self.assertEqual(s.reason, "REQUEST_CHANGED")

    def test_request_withdrawn_mid_hold(self):
        eng = lh.HoldEngine()
        run(eng, 0, 400)
        s = eng.update(450, True, None, None)
        self.assertEqual(s.reason, "REQUEST_CHANGED")
        sts, _ = run(eng, 500, 5000, request="Sign: commit abc")
        self.assertEqual(commits(sts), 0)

    def test_stall_cancels_hold(self):
        eng = lh.HoldEngine()
        run(eng, 0, 300)
        s = eng.update(1600, True, "Sign: commit abc", "sign")  # loop stalled 1.3 s
        self.assertEqual((s.reason, s.committed, s.state), ("GAP", False, lh.RELEASE))

    def test_gap_at_limit_is_tolerated(self):
        eng = lh.HoldEngine(max_gap_ms=250)
        eng.update(0, True, "L", "login")
        self.assertIsNone(eng.update(250, True, "L", "login").reason)
        self.assertEqual(eng.update(501, True, "L", "login").reason, "GAP")

    def test_clock_going_backwards_cancels(self):
        eng = lh.HoldEngine()
        run(eng, 1000, 300)
        s = eng.update(1100, True, "Sign: commit abc", "sign")
        self.assertEqual((s.reason, s.committed), ("CLOCK", False))

    def test_external_cancel(self):
        eng = lh.HoldEngine()
        run(eng, 0, 300)
        eng.cancel()
        sts, _ = run(eng, 400, 5000)
        self.assertEqual(commits(sts), 0)  # button still down after Back: no hold

    def test_reset_while_held(self):
        eng = lh.HoldEngine()
        run(eng, 0, 300)
        eng.reset()
        sts, _ = run(eng, 400, 5000)
        self.assertEqual(commits(sts), 0)


class PocketPresses(unittest.TestCase):
    def test_button_already_down_when_request_appears(self):
        eng = lh.HoldEngine()
        out = [eng.update(t, True, None, None) for t in range(0, 200, STEP)]
        out += [eng.update(t, True, "Sign: commit abc", "sign") for t in range(200, 4000, STEP)]
        self.assertEqual(commits(out), 0)
        eng.update(4000, False, "Sign: commit abc", "sign")
        out, _ = run(eng, 4050, 1500)
        self.assertEqual(commits(out), 1)

    def test_held_through_idle_screen_into_prompt(self):
        eng = lh.HoldEngine()
        eng.update(0, True, "Sign: commit abc", "sign")
        eng.update(50, False, "Sign: commit abc", "sign")  # tap
        eng.update(100, True, None, None)                  # pressed on Idle (no request)
        out = [eng.update(t, True, "Sign: commit abc", "sign") for t in range(150, 4000, STEP)]
        self.assertEqual(commits(out), 0)

    def test_tap_without_request_does_nothing(self):
        eng = lh.HoldEngine()
        out = [eng.update(0, True, None, None), eng.update(50, False, None, None)]
        self.assertEqual([s.state for s in out], [lh.IDLE, lh.IDLE])


class TickWrap(unittest.TestCase):
    def test_hold_across_wraparound(self):
        eng = lh.HoldEngine()
        start = lb_ticks.PERIOD - 300
        out = []
        for i in range(0, 1600, STEP):
            out.append(eng.update((start + i) % lb_ticks.PERIOD, True, "S", "sign"))
        self.assertEqual(commits(out), 1)
        self.assertEqual([i for i, s in enumerate(out) if s.committed], [30])  # 1500 ms

    def test_diff_and_add(self):
        P = lb_ticks.PERIOD
        self.assertEqual(lb_ticks.diff(5, P - 5), 10)
        self.assertEqual(lb_ticks.diff(P - 5, 5), -10)
        self.assertEqual(lb_ticks.diff(100, 100), 0)
        self.assertEqual(lb_ticks.add(P - 1, 3), 2)
        self.assertEqual(lb_ticks.diff(lb_ticks.add(P - 1, 3), P - 1), 3)


class Invariant(unittest.TestCase):
    def test_random_sampling_never_commits_without_a_real_hold(self):
        """Reference check on random input. A commit is only legal if, looking back over the
        samples: the button was down and showed the same request and kind continuously for
        at least the required time, with no sampling gap over max_gap_ms, and the run began
        on a fresh press (the sample before it was released), never on a button that was
        already down."""
        rng = Rng(2024)
        reqs = [None, "A", "B"]
        kinds = ["login", "sign"]
        total = 0
        for trial in range(300 if sys.implementation.name == "cpython" else 20):
            eng = lh.HoldEngine()
            hist = []
            t = 0
            for _ in range(400):
                t += rng.below(4) * 40 + 10
                pressed = rng.below(10) > 2
                if hist and rng.below(6):
                    pressed = hist[-1][1] or rng.below(3) == 0  # long presses are common
                req = hist[-1][2] if hist and rng.below(8) else reqs[rng.below(3)]
                kind = hist[-1][3] if hist and rng.below(8) else kinds[rng.below(2)]
                st = eng.update(t, pressed, req, kind)
                hist.append((t, pressed, req, kind))
                if not st.committed:
                    continue
                total += 1
                need = eng.required_ms(kind)
                start = None
                for j in range(len(hist) - 1, -1, -1):
                    h = hist[j]
                    if not (h[1] and h[2] is not None and h[2] == req and h[3] == kind):
                        break
                    if j < len(hist) - 1 and hist[j + 1][0] - h[0] > 250:
                        break
                    start = j
                self.assertIsNotNone(start, (trial, hist[-6:]))
                self.assertGreaterEqual(t - hist[start][0], need, (trial, hist[-6:]))
                self.assertTrue(start == 0 or not hist[start - 1][1], (trial, hist[-6:]))
        self.assertGreater(total, 0)  # the generator does reach commits


if __name__ == "__main__":
    unittest.main()
