import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_session as ls
import lb_ticks
import lb_hold

COMBO = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1]
WRONG = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3]


class Clock:
    def __init__(self, t=1000):
        self.t = t

    def __call__(self):
        return self.t % lb_ticks.PERIOD

    def advance(self, ms):
        self.t += ms


class KS:
    def __init__(self, attempts=0, combo=COMBO):
        self.n = attempts
        self.combo = list(combo)
        self.log = []
        self.wiped = 0
        self.zeroized = 0
        self.fail_write = False
        self.fail_verify = False
        self.fail_wipe = False
        self.fail_read = False

    def attempts(self):
        if self.fail_read:
            raise OSError("read")
        return self.n

    def set_attempts(self, n):
        if self.fail_write:
            raise OSError("write")
        self.log.append(("set", n))
        self.n = n

    def verify(self, combo):
        self.log.append(("verify", self.n))
        if self.fail_verify:
            raise ValueError("kdf")
        return list(combo) == self.combo

    def wipe(self):
        if self.fail_wipe:
            raise OSError("wipe")
        self.wiped += 1

    def zeroize(self):
        self.zeroized += 1


class FP:
    def __init__(self, result=True):
        self.result = result
        self.calls = 0

    def matched(self):
        self.calls += 1
        if self.result == "boom":
            raise OSError("sensor")
        return self.result


def mk(attempts=0, fp=None, **kw):
    clock = Clock()
    ks = KS(attempts)
    return ls.Session(ks, clock, fp=fp, **kw), ks, clock


def unlocked(**kw):
    s, ks, clock = mk(**kw)
    assert s.unlock(COMBO).outcome == ls.OK
    ks.log.clear()
    return s, ks, clock


class Unlock(unittest.TestCase):
    def test_starts_locked_and_unlocks(self):
        s, ks, _ = mk()
        self.assertEqual(s.state(), ls.LOCKED)
        r = s.unlock(COMBO)
        self.assertEqual((r.outcome, s.state()), (ls.OK, ls.UNLOCKED))
        self.assertEqual(ks.n, 0)

    def test_counter_written_before_check(self):
        s, ks, _ = mk()
        s.unlock(WRONG)
        self.assertEqual(ks.log, [("set", 1), ("verify", 1)])

    def test_write_failure_means_no_check(self):
        s, ks, _ = mk()
        ks.fail_write = True
        with self.assertRaises(ls.StorageError):
            s.unlock(COMBO)  # even the right combo is not checked
        self.assertEqual(ks.log, [])
        self.assertEqual(s.state(), ls.LOCKED)

    def test_delay_schedule(self):
        s, ks, clock = mk()
        want = [0, 0, 0, 5000, 30000, 300000, 900000, 1800000, 3600000]
        for i, d in enumerate(want, 1):
            r = s.unlock(WRONG)
            self.assertEqual((r.outcome, r.delay_ms, r.attempts_left), (ls.BAD, d, 10 - i), i)
            clock.advance(d)

    def test_delayed_attempt_is_free_and_unchecked(self):
        s, ks, clock = mk()
        for _ in range(4):
            s.unlock(WRONG)
        ks.log.clear()
        clock.advance(4999)
        r = s.unlock(COMBO)
        self.assertEqual((r.outcome, r.delay_ms), (ls.DELAYED, 1))
        self.assertEqual(ks.log, [])  # no attempt used, nothing verified
        clock.advance(1)
        self.assertEqual(s.unlock(COMBO).outcome, ls.OK)

    def test_tenth_failure_wipes(self):
        s, ks, clock = mk()
        for i in range(9):
            self.assertEqual(s.unlock(WRONG).outcome, ls.BAD)
            clock.advance(10 ** 7)
        r = s.unlock(WRONG)
        self.assertEqual(r.outcome, ls.WIPED)
        self.assertEqual((ks.wiped, s.wiped(), s.state()), (1, True, ls.LOCKED))
        clock.advance(10 ** 7)
        self.assertEqual(s.unlock(COMBO).outcome, ls.WIPED)  # right combo is too late
        self.assertEqual(ks.wiped, 1)

    def test_correct_combo_on_last_attempt_works(self):
        s, ks, clock = mk(attempts=9)
        clock.advance(3600000)  # the boot delay after 9 failures
        r = s.unlock(COMBO)
        self.assertEqual(r.outcome, ls.OK)
        self.assertEqual(ks.n, 0)

    def test_success_resets_counter(self):
        s, ks, clock = mk()
        s.unlock(WRONG)
        s.unlock(WRONG)
        self.assertEqual(ks.n, 2)
        s.unlock(COMBO)
        self.assertEqual(ks.n, 0)

    def test_counter_reset_failure_after_success_is_only_stricter(self):
        s, ks, clock = mk()
        s.unlock(WRONG)
        orig = ks.set_attempts  # only the reset to 0 after a good combo fails

        def flaky(n):
            if n == 0:
                raise OSError("reset failed")
            orig(n)
        ks.set_attempts = flaky
        clock.advance(10 ** 6)
        self.assertEqual(s.unlock(COMBO).outcome, ls.OK)  # unlocked despite the failed reset
        self.assertEqual(ks.n, 2)  # stale counter left behind
        s2 = ls.Session(ks, clock)  # next boot is stricter, never looser
        self.assertEqual(s2.state(), ls.LOCKED)

    def test_verifier_exception_counts_as_failure(self):
        s, ks, _ = mk()
        ks.fail_verify = True
        r = s.unlock(COMBO)
        self.assertEqual((r.outcome, ks.n), (ls.BAD, 1))

    def test_unlock_when_unlocked_is_noop(self):
        s, ks, _ = unlocked()
        self.assertEqual(s.unlock(WRONG).outcome, ls.OK)
        self.assertEqual(ks.log, [])

    def test_wipe_failure_still_marks_wiped(self):
        s, ks, clock = mk(attempts=9)
        clock.advance(3600000)
        ks.fail_wipe = True
        self.assertEqual(s.unlock(WRONG).outcome, ls.WIPED)
        self.assertTrue(s.wiped())


class BootBehaviour(unittest.TestCase):
    def test_counter_at_limit_wipes_at_boot(self):
        s, ks, _ = mk(attempts=10)
        self.assertEqual((s.wiped(), ks.wiped), (True, 1))
        self.assertEqual(s.unlock(COMBO).outcome, ls.WIPED)

    def test_reboot_does_not_skip_the_delay(self):
        s, ks, clock = mk(attempts=5)  # 5 failures before the power cycle
        r = s.unlock(COMBO)
        self.assertEqual((r.outcome, r.delay_ms), (ls.DELAYED, 30000))
        clock.advance(30000)
        self.assertEqual(s.unlock(COMBO).outcome, ls.OK)

    def test_few_failures_before_reboot_have_no_delay(self):
        s, ks, _ = mk(attempts=2)
        self.assertEqual(s.unlock(COMBO).outcome, ls.OK)

    def test_unreadable_or_corrupt_counter_fails_closed(self):
        for bad in ("x", -1, None, True, 1.5):
            ks = KS()
            ks.n = bad
            with self.assertRaises(ls.StorageError, msg=repr(bad)):
                ls.Session(ks, Clock())
        ks = KS()
        ks.fail_read = True
        with self.assertRaises(ls.StorageError):
            ls.Session(ks, Clock())

    def test_policy_limit_applies_at_boot(self):
        ks = KS(attempts=4)
        s = ls.Session(ks, Clock(), policy=ls.Policy(bad_limit=4))
        self.assertTrue(s.wiped())


class ComboValidation(unittest.TestCase):
    def test_malformed_combos_use_no_attempt(self):
        s, ks, _ = mk()
        for bad in ([], [0] * 7, [0] * 17, [0] * 9 + [4], [0] * 9 + [-1], [0] * 9 + [True],
                    [0] * 9 + ["1"], [0] * 9 + [1.0], "0123012301", None, 5, {1: 2}):
            r = s.unlock(bad)
            self.assertEqual(r.outcome, ls.INVALID, repr(bad))
        self.assertEqual(ks.log, [])

    def test_accepts_tuple_bytes_bytearray_and_limits(self):
        for form in (tuple(COMBO), bytes(COMBO), bytearray(COMBO)):
            s, ks, _ = mk()
            self.assertEqual(s.unlock(form).outcome, ls.OK, repr(form))
        for n in (8, 16):
            s, ks, _ = mk()
            self.assertEqual(s.unlock([0] * n).outcome, ls.BAD)


class Idle(unittest.TestCase):
    def test_idle_lock(self):
        s, ks, clock = unlocked()
        clock.advance(59999)
        s.tick()
        self.assertEqual(s.state(), ls.UNLOCKED)
        clock.advance(1)
        s.tick()
        self.assertEqual((s.state(), ks.zeroized), (ls.LOCKED, 1))

    def test_activity_resets_timer(self):
        s, ks, clock = unlocked()
        clock.advance(50000)
        s.activity()
        clock.advance(50000)
        s.tick()
        self.assertEqual(s.state(), ls.UNLOCKED)
        clock.advance(10000)
        s.tick()
        self.assertEqual(s.state(), ls.LOCKED)

    def test_idle_across_tick_wraparound(self):
        clock = Clock(lb_ticks.PERIOD - 30000)
        ks = KS()
        s = ls.Session(ks, clock)
        s.unlock(COMBO)
        clock.advance(59999)
        s.tick()
        self.assertEqual(s.state(), ls.UNLOCKED)
        clock.advance(1)
        s.tick()
        self.assertEqual(s.state(), ls.LOCKED)

    def test_lock_zeroizes_even_if_it_fails(self):
        s, ks, _ = unlocked()
        ks.zeroize = lambda: (_ for _ in ()).throw(OSError("x"))
        s.lock("BACK")
        self.assertEqual(s.state(), ls.LOCKED)

    def test_locked_session_never_idle_unlocks(self):
        s, ks, clock = mk()
        clock.advance(10 ** 6)
        s.tick()
        self.assertEqual(s.state(), ls.LOCKED)


class PolicyTests(unittest.TestCase):
    def test_defaults(self):
        p = ls.Policy()
        self.assertEqual((p.combo_min, p.combo_max, p.bad_limit, p.idle_ms), (8, 16, 10, 60000))

    def test_ranges(self):
        for kw in ({"combo_min": 7}, {"combo_min": 17}, {"combo_max": 7}, {"combo_max": 17},
                   {"combo_min": 12, "combo_max": 10}, {"bad_limit": 2}, {"bad_limit": 11},
                   {"idle_ms": 14999}, {"idle_ms": 600001}, {"idle_ms": True}, {"bad_limit": 5.0},
                   {"combo_min": "8"}, {"idle_ms": None}):
            with self.assertRaises(ls.InvalidPolicy, msg=repr(kw)):
                ls.Policy(**kw)
        ls.Policy(8, 8, 3, 15000)
        ls.Policy(16, 16, 10, 600000)

    def test_set_policy_needs_unlock_and_applies(self):
        s, ks, clock = mk()
        with self.assertRaises(ls.SessionError):
            s.set_policy(ls.Policy(idle_ms=15000))
        s.unlock(COMBO)
        s.set_policy(ls.Policy(idle_ms=15000))
        clock.advance(15000)
        s.tick()
        self.assertEqual(s.state(), ls.LOCKED)
        s.unlock(COMBO)
        with self.assertRaises(ls.InvalidPolicy):
            s.set_policy({"idle_ms": 1})  # only a validated Policy object is accepted

    def test_policy_affects_combo_length_and_limit(self):
        s, ks, clock = mk(policy=ls.Policy(combo_min=12, combo_max=12, bad_limit=3))
        self.assertEqual(s.unlock(COMBO).outcome, ls.INVALID)  # 10 presses < 12
        w = [3] * 12
        s.unlock(w)
        s.unlock(w)
        self.assertEqual(s.unlock(w).outcome, ls.WIPED)


class Requests(unittest.TestCase):
    def test_validation(self):
        s, _, _ = unlocked()
        for args in [("NOPE", "USB", "x"), ("SIGN", "BLE", "x"), ("SIGN", "USB", ""),
                     ("SIGN", "USB", "   "), ("SIGN", "USB", None), ("SIGN", "USB", "a" * 97),
                     ("SIGN", "USB", "line\nbreak"), ("SIGN", "USB", "bob‮evil"),
                     (None, "USB", "x"), ("SIGN", None, "x")]:
            with self.assertRaises(ls.InvalidRequest, msg=repr(args)):
                s.request(*args)
        self.assertIsNone(s.pending())
        s.request("SIGN", "USB", "a" * 96)

    def test_new_request_cancels_old(self):
        s, _, _ = unlocked()
        a = s.request("SIGN", "USB", "A")
        b = s.request("AUTH", "USB", "B")
        self.assertEqual(s.decision(a), ls.CANCELLED)
        self.assertIsNone(s.decision(b))
        self.assertEqual(s.pending()["id"], b)

    def test_stale_id_cannot_approve(self):
        s, _, _ = unlocked(fp=FP(True))
        a = s.request("SIGN", "USB", "A")
        b = s.request("SIGN", "USB", "B")
        self.assertEqual(s.hold_complete(a), ls.STALE)
        self.assertIsNone(s.decision(b))
        self.assertEqual(s.hold_complete(b), ls.APPROVED)
        self.assertEqual(s.hold_complete(b), ls.STALE)  # cannot approve twice
        self.assertEqual(s.decision(a), ls.CANCELLED)

    def test_fingerprint_approves_only_when_unlocked(self):
        fp = FP(True)
        s, ks, clock = mk(fp=fp)
        r = s.request("AUTH", "USB", "Login to x")
        self.assertEqual(s.pending()["locked"], True)
        self.assertEqual(s.hold_complete(r), ls.NEEDS_UNLOCK)
        self.assertEqual(fp.calls, 0)  # the sensor is never consulted while locked
        self.assertIsNone(s.decision(r))
        s.unlock(COMBO)
        self.assertEqual(s.hold_complete(r), ls.APPROVED)
        self.assertEqual(s.decision(r), ls.APPROVED)

    def test_fingerprint_failure_falls_back_to_combo(self):
        for fp in (FP(False), FP("boom"), None):
            s, ks, clock = unlocked(fp=fp)
            r = s.request("SIGN", "UI", "Sign: abc")
            self.assertEqual(s.hold_complete(r), ls.NEED_COMBO)
            self.assertTrue(s.pending()["needs_combo"])
            res = s.approve_with_combo(r, COMBO)
            self.assertEqual(res.outcome, ls.OK)
            self.assertEqual(s.decision(r), ls.APPROVED)

    def test_combo_fallback_is_counted_delayed_and_wipes(self):
        s, ks, clock = unlocked(fp=FP(False))
        r = s.request("SIGN", "UI", "Sign")
        s.hold_complete(r)
        for i in range(1, 4):
            self.assertEqual(s.approve_with_combo(r, WRONG).outcome, ls.BAD)
        self.assertEqual(ks.n, 3)
        res = s.approve_with_combo(r, WRONG)
        self.assertEqual((res.outcome, res.delay_ms), (ls.BAD, 5000))
        self.assertEqual(s.approve_with_combo(r, COMBO).outcome, ls.DELAYED)  # delay applies here too
        self.assertIsNone(s.decision(r))
        clock.advance(5000)
        for d in (30000, 300000, 900000, 1800000):
            self.assertEqual(s.approve_with_combo(r, WRONG).outcome, ls.BAD)
            clock.advance(d)
        self.assertEqual(s.approve_with_combo(r, WRONG).outcome, ls.BAD)
        clock.advance(3600000)
        res = s.approve_with_combo(r, WRONG)
        self.assertEqual(res.outcome, ls.WIPED)
        self.assertEqual(s.decision(r), ls.CANCELLED)
        self.assertEqual((s.state(), ks.wiped), (ls.LOCKED, 1))

    def test_combo_fallback_needs_failed_fingerprint_and_unlock(self):
        s, ks, _ = unlocked(fp=FP(True))
        r = s.request("SIGN", "UI", "Sign")
        with self.assertRaises(ls.NoSuchRequest):
            s.approve_with_combo(r, COMBO)  # fingerprint not tried yet
        with self.assertRaises(ls.NoSuchRequest):
            s.approve_with_combo(999, COMBO)
        s2, ks2, _ = unlocked(fp=FP(False))
        r2 = s2.request("SIGN", "UI", "Sign")
        s2.hold_complete(r2)
        s2.lock()
        with self.assertRaises(ls.NoSuchRequest):
            s2.approve_with_combo(r2, COMBO)  # a locked device cannot approve

    def test_fallback_wrong_id_after_replacement(self):
        s, _, _ = unlocked(fp=FP(False))
        a = s.request("SIGN", "UI", "A")
        s.hold_complete(a)
        b = s.request("SIGN", "UI", "B")
        with self.assertRaises(ls.NoSuchRequest):
            s.approve_with_combo(a, COMBO)
        self.assertIsNone(s.decision(b))

    def test_cancel(self):
        s, _, _ = unlocked()
        r = s.request("SIGN", "UI", "x")
        s.cancel(999)
        self.assertIsNone(s.decision(r))
        s.cancel(r)
        self.assertEqual(s.decision(r), ls.CANCELLED)
        self.assertIsNone(s.pending())

    def test_expiry_unlocked_and_locked(self):
        s, ks, clock = unlocked()
        r = s.request("SIGN", "USB", "x")
        clock.advance(29999)
        s.tick()
        self.assertIsNone(s.decision(r))
        clock.advance(1)
        s.tick()
        self.assertEqual(s.decision(r), ls.EXPIRED)
        s2, ks2, clock2 = mk()
        r2 = s2.request("SIGN", "USB", "x")
        clock2.advance(30000)
        s2.tick()
        self.assertEqual(s2.decision(r2), ls.LOCKED_TIMEOUT)

    def test_device_started_requests_get_longer_timeout(self):
        s, ks, clock = unlocked()
        u = s.request("OATH_ADD", "UI", "Add x")
        clock.advance(ls.REQUEST_TIMEOUT_MS)
        s.tick()
        self.assertIsNone(s.decision(u))  # still waiting: nobody is on the wire
        for _ in range(3):  # the user keeps pressing buttons, so the idle lock stays off
            s.activity()
            clock.advance((ls.UI_REQUEST_TIMEOUT_MS - ls.REQUEST_TIMEOUT_MS) // 3)
            s.tick()
        self.assertEqual(s.decision(u), ls.EXPIRED)

    def test_hold_after_deadline_is_refused(self):
        fp = FP(True)
        s, ks, clock = unlocked(fp=fp)
        r = s.request("SIGN", "USB", "x")
        clock.advance(30000)
        self.assertEqual(s.hold_complete(r), ls.STALE)
        self.assertEqual((s.decision(r), fp.calls), (ls.EXPIRED, 0))

    def test_request_survives_lock_and_proceeds_after_unlock(self):
        s, ks, clock = unlocked(fp=FP(True))
        r = s.request("SIGN", "USB", "x")
        s.lock("IDLE")
        self.assertEqual(s.hold_complete(r), ls.NEEDS_UNLOCK)
        s.unlock(COMBO)
        self.assertIsNone(s.decision(r))  # not auto-approved by unlocking
        self.assertEqual(s.hold_complete(r), ls.APPROVED)

    def test_wipe_cancels_pending(self):
        s, ks, clock = mk(attempts=9)
        clock.advance(3600000)
        r = s.request("SIGN", "USB", "x")
        s.unlock(WRONG)
        self.assertEqual(s.decision(r), ls.CANCELLED)

    def test_decision_lookup_and_bounded_history(self):
        s, _, _ = unlocked()
        ids = [s.request("SIGN", "UI", "r%d" % i) for i in range(8)]
        s.cancel(ids[-1])
        with self.assertRaises(ls.NoSuchRequest):
            s.decision(ids[0])  # evicted
        self.assertEqual(s.decision(ids[-1]), ls.CANCELLED)
        for bad in (0, None, "1", 12345):
            with self.assertRaises(ls.NoSuchRequest):
                s.decision(bad)
        self.assertLessEqual(len(s._decisions), 4)

    def test_summary_is_trimmed_and_safe(self):
        s, _, _ = unlocked()
        s.request("SIGN", "USB", "  Sign commit abc  ")
        self.assertEqual(s.pending()["summary"], "Sign commit abc")


class Events(unittest.TestCase):
    def test_event_sequence(self):
        ev = []
        s, ks, clock = mk(fp=FP(True), listener=lambda e, d: ev.append((e, d)))
        r = s.request("AUTH", "USB", "x")
        s.unlock(COMBO)
        s.hold_complete(r)
        s.lock("BACK")
        self.assertEqual([e for e, _ in ev], [ls.EVT_UNLOCK_NEEDED, ls.EVT_LOCK_CHANGED,
                                              ls.EVT_REQUEST_PENDING, ls.EVT_REQUEST_DONE,
                                              ls.EVT_LOCK_CHANGED])
        self.assertEqual(ev[3][1], (r, ls.APPROVED))

    def test_pending_event_when_unlocked(self):
        ev = []
        s, _, _ = unlocked()
        s.set_listener(lambda e, d: ev.append(e))
        s.request("AUTH", "USB", "x")
        self.assertEqual(ev, [ls.EVT_REQUEST_PENDING])

    def test_broken_listener_does_not_break_gates(self):
        def boom(e, d):
            raise RuntimeError("ui bug")
        s, ks, _ = mk(listener=boom, fp=FP(True))
        r = s.request("SIGN", "USB", "x")
        self.assertEqual(s.unlock(COMBO).outcome, ls.OK)
        self.assertEqual(s.hold_complete(r), ls.APPROVED)

    def test_set_listener(self):
        ev = []
        s, _, _ = mk()
        s.set_listener(lambda e, d: ev.append(e))
        s.unlock(COMBO)
        self.assertEqual(ev, [ls.EVT_LOCK_CHANGED])


class WithHoldEngine(unittest.TestCase):
    """The UI loop: hold engine -> session.hold_complete."""

    def drive(self, s, eng, req_id, shown, kind, t0, press_ms, step=50):
        committed = False
        t = t0
        while t <= t0 + press_ms:
            st = eng.update(t, True, shown, kind)
            if st.committed:
                committed = True
                outcome = s.hold_complete(req_id)
                return outcome, t
            t += step
        return None, t

    def test_hold_then_approve(self):
        s, ks, clock = unlocked(fp=FP(True))
        eng = lb_hold.HoldEngine()
        r = s.request("SIGN", "USB", "Sign: abc")
        out, _ = self.drive(s, eng, r, "Sign: abc", "sign", 0, 2000)
        self.assertEqual(out, ls.APPROVED)

    def test_swapped_request_is_never_approved_by_the_old_hold(self):
        s, ks, clock = unlocked(fp=FP(True))
        eng = lb_hold.HoldEngine()
        a = s.request("SIGN", "USB", "Sign: A")
        for t in range(0, 1000, 50):
            eng.update(t, True, "Sign: A", "sign")
        b = s.request("SIGN", "USB", "Sign: B")  # host swaps the request mid-hold
        out, _ = self.drive(s, eng, b, "Sign: B", "sign", 1000, 5000)
        self.assertIsNone(out)  # the engine reset; B needs its own fresh hold
        self.assertIsNone(s.decision(b))
        self.assertEqual(s.hold_complete(a), ls.STALE)


if __name__ == "__main__":
    unittest.main()
