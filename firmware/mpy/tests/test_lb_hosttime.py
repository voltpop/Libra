import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
sys.path.insert(0, "pico")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_console
import lb_dt
from lb_rig import Rig

T0 = lb_dt.to_unix(2026, 10, 2) + 12 * 3600  # 2026-10-02 12:00:00 UTC


def rig():
    r = Rig(push_to_show=False)
    r.clock.trusted_flag = False  # a freshly powered Pico does not know the time
    r.unlock()
    return r


def screen(r):
    return r.ui.screen()


class HostTime(unittest.TestCase):
    def test_a_proposal_changes_nothing_until_PTT_is_held(self):
        r = rig()
        before = r.clock.now()
        self.assertIsNotNone(r.ui.host_set_time(T0 * 1000))
        r.run(3000)
        self.assertEqual(screen(r)["id"], "HostRequest")
        self.assertIn("2026-10-02 12:00:00 UTC", screen(r)["lines"])
        self.assertFalse(r.clock.trusted())
        self.assertLess(abs(r.clock.now() - before), 10)  # untouched

    def test_holding_ptt_sets_the_clock_and_makes_it_trusted(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)
        self.assertTrue(r.clock.trusted())
        self.assertEqual(screen(r)["id"], "Notice")
        self.assertTrue(screen(r)["lines"][0].startswith("Clock set: 12:00:0"))
        self.assertTrue(T0 <= r.clock.now() <= T0 + 6)

    def test_time_spent_waiting_is_added(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.run(20000)  # twenty seconds looking at the screen first
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)
        self.assertTrue(T0 + 20 <= r.clock.now() <= T0 + 26, r.clock.now() - T0)

    def test_milliseconds_are_kept_until_the_final_second(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000 + 990)  # .99 s into the second: waiting rolls it over
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)
        self.assertGreaterEqual(r.clock.now(), T0 + 3)

    def test_backing_out_or_an_early_release_does_not_set_it(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.down("PTT")
        r.run(300)
        r.up("PTT")
        r.run(100)
        self.assertFalse(r.clock.trusted())
        r.press("BACK")
        r.run(100)
        self.assertFalse(r.clock.trusted())
        self.assertNotEqual(screen(r)["id"], "HostRequest")

    def test_a_replacing_request_cannot_set_the_time(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.session.request("SIGN", "USB", "Sign something")
        r.run(100)
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)
        self.assertFalse(r.clock.trusted())

    def test_a_new_proposal_replaces_the_old_one(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.ui.host_set_time((T0 + 3600) * 1000)
        r.run(100)
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)
        self.assertTrue(T0 + 3600 <= r.clock.now() <= T0 + 3606)

    def test_out_of_range_times_are_refused(self):
        r = rig()
        for bad in (0, 1000, lb_dt.to_unix(2023, 12, 31) * 1000, lb_dt.to_unix(2100, 1, 1) * 1000):
            self.assertIsNone(r.ui.host_set_time(bad), bad)
        self.assertNotEqual(screen(r)["id"], "HostRequest")

    def test_the_request_expires_if_nobody_holds(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000)
        r.run(40000)  # a host request lapses after 30 s
        self.assertNotEqual(screen(r)["id"], "HostRequest")
        self.assertFalse(r.clock.trusted())

    def test_while_locked_it_waits_for_the_unlock(self):
        r = Rig(push_to_show=False)  # locked
        r.clock.trusted_flag = False
        r.ui.host_set_time(T0 * 1000)
        r.run(2000)
        self.assertEqual(screen(r)["id"], "Locked")
        self.assertFalse(r.clock.trusted())


class Console(unittest.TestCase):
    def setUp(self):
        self.r = rig()
        self.out = []
        self.c = lb_console.Console(self.r, out=self.out.append)

    def test_settime_proposes(self):
        self.c.handle("settime %d.250" % T0)
        self.assertIn("hold PTT", self.out[-1])
        self.r.run(100)
        self.assertEqual(screen(self.r)["id"], "HostRequest")

    def test_settime_is_not_instant(self):
        self.c.handle("settime %d" % T0)
        self.assertFalse(self.r.clock.trusted())

    def test_bad_input_is_rejected_without_changing_anything(self):
        for line in ("settime", "settime abc", "settime 5", "settime %d.x" % T0, "settime 99999999999"):
            self.out.clear()
            self.c.handle(line)
            self.assertTrue(self.out, line)
            self.assertNotEqual(screen(self.r)["id"], "HostRequest", line)


def device_default_rig():
    r = rig()
    r.settings.set("push_to_show", True)  # the device default; the test rig turns it off
    r.oath.set_reveal_all(True)
    return r


class HostSettings(unittest.TestCase):
    def hold(self, r):
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(100)

    def test_nothing_changes_until_PTT_is_held(self):
        r = device_default_rig()
        self.assertIsNotNone(r.ui.host_set_setting("push_to_show", False))
        r.run(3000)
        self.assertEqual(screen(r)["id"], "HostRequest")
        self.assertIn("Set push_to_show: off", screen(r)["lines"])
        self.assertTrue(r.settings.get("push_to_show"))

    def test_the_hold_applies_it_and_the_oath_store_follows(self):
        r = device_default_rig()
        r.ui.host_set_setting("push_to_show", False)
        self.hold(r)
        self.assertFalse(r.settings.get("push_to_show"))
        self.assertEqual(screen(r)["id"], "Notice")

    def test_even_a_strengthening_change_needs_the_hold(self):
        r = device_default_rig()
        r.settings.set("push_to_show", False, approved=True)
        self.assertIsNotNone(r.ui.host_set_setting("push_to_show", True))
        r.run(100)
        self.assertFalse(r.settings.get("push_to_show"))
        self.hold(r)
        self.assertTrue(r.settings.get("push_to_show"))

    def test_zone_is_shown_readably_and_applied(self):
        r = device_default_rig()
        r.ui.host_set_setting("utc_offset_min", 330)
        self.assertIn("Set utc_offset_min: UTC+05:30", screen(r)["lines"])
        self.hold(r)
        self.assertEqual(r.settings.get("utc_offset_min"), 330)

    def test_refused_without_ever_asking_the_user(self):
        r = device_default_rig()
        for name, value in (("nope", 1), ("push_to_show", 1), ("utc_offset_min", 7),
                            ("utc_offset_min", 9999), ("utc_offset_min", 0), ("push_to_show", True)):
            self.assertIsNone(r.ui.host_set_setting(name, value), (name, value))
        self.assertNotEqual(screen(r)["id"], "HostRequest")

    def test_back_denies_and_nothing_changes(self):
        r = device_default_rig()
        r.ui.host_set_setting("push_to_show", False)
        r.run(100)
        r.press("BACK")
        r.run(100)
        self.hold(r)
        self.assertTrue(r.settings.get("push_to_show"))

    def test_a_setting_and_a_time_proposal_do_not_mix(self):
        r = device_default_rig()
        r.ui.host_set_time(T0 * 1000)
        r.ui.host_set_setting("push_to_show", False)  # replaces the time request
        self.hold(r)
        self.assertFalse(r.settings.get("push_to_show"))
        self.assertFalse(r.clock.trusted())


class SettingsConsole(unittest.TestCase):
    def setUp(self):
        self.r = device_default_rig()
        self.out = []
        self.c = lb_console.Console(self.r, out=self.out.append)

    def test_set_proposes_and_settings_lists(self):
        self.c.handle("set push_to_show off")
        self.assertIn("hold PTT", self.out[-1])
        self.assertTrue(self.r.settings.get("push_to_show"))
        self.c.handle("settings")
        self.assertEqual(self.out[-2], "push_to_show=True utc_offset_min=0")
        self.assertEqual(self.out[-1], "stay_unlocked=False console=rw")  # the simulator console starts read-write

    def test_bad_set_commands_are_rejected(self):
        for line in ("set", "set push_to_show", "set push_to_show maybe", "set utc_offset_min x",
                     "set utc_offset_min 7", "set bogus 1"):
            self.out.clear()
            self.c.handle(line)
            self.assertTrue(self.out, line)
            self.assertNotEqual(screen(self.r)["id"], "HostRequest", line)


class ResetAndMode(unittest.TestCase):
    def hold(self, r):
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(200)

    def test_reset_needs_the_hold_and_then_starts_over_locked(self):
        r = rig()
        r.oath.add(__import__("lb_oath").Entry(issuer="X", account="me", secret=b"12345678901234567890",
                                              type="TOTP"), approved=True)
        n = len(r.oath.list())
        self.assertIsNotNone(r.ui.host_factory_reset())
        r.run(3000)
        self.assertEqual(screen(r)["id"], "HostRequest")
        self.assertIn("ERASE ALL accounts and settings", screen(r)["lines"])
        self.assertEqual(len(r.oath.list()), n)  # nothing erased yet
        self.hold(r)
        self.assertEqual(screen(r)["id"], "Locked")
        self.assertNotEqual(len(r.oath.list()), n)  # back to the demo accounts only

    def test_reset_denied_with_back(self):
        r = rig()
        n = len(r.oath.list())
        r.ui.host_factory_reset()
        r.run(100)
        r.press("BACK")
        r.run(100)
        self.hold(r)
        self.assertEqual(len(r.oath.list()), n)
        self.assertEqual(r.session.state(), "UNLOCKED")

    def test_stay_unlocked_blocks_the_idle_lock_until_it_is_turned_off(self):
        r = rig()
        self.assertIsNotNone(r.ui.host_keep_unlocked(True))
        self.assertFalse(r.session.keep_unlocked())  # not until the hold
        self.hold(r)
        self.assertTrue(r.session.keep_unlocked())
        r.run(r.session.policy().idle_ms * 3)
        self.assertEqual(r.session.state(), "UNLOCKED")
        r.ui.host_keep_unlocked(False)
        r.run(100)
        self.hold(r)
        self.assertFalse(r.session.keep_unlocked())
        r.run(r.session.policy().idle_ms + 2000)
        self.assertEqual(r.session.state(), "LOCKED")

    def test_idle_lock_still_works_without_the_mode(self):
        r = rig()
        r.run(r.session.policy().idle_ms + 2000)
        self.assertEqual(r.session.state(), "LOCKED")

    def test_any_lock_ends_the_mode(self):
        r = rig()
        r.ui.host_keep_unlocked(True)
        r.run(100)
        self.hold(r)
        r.session.lock("MANUAL")
        self.assertFalse(r.session.keep_unlocked())
        r.unlock()
        r.run(r.session.policy().idle_ms + 2000)
        self.assertEqual(r.session.state(), "LOCKED")  # it did not come back

    def test_the_mode_cannot_be_proposed_while_locked_or_when_already_so(self):
        r = Rig(push_to_show=False)  # locked
        self.assertIsNone(r.ui.host_keep_unlocked(True))
        r.unlock()
        self.assertIsNone(r.ui.host_keep_unlocked(False))  # already off

    def test_console_commands(self):
        r = rig()
        out = []
        c = lb_console.Console(r, out=out.append)
        c.handle("stayunlocked on")
        self.assertIn("hold PTT", out[-1])
        c.handle("factoryreset")
        self.assertIn("ERASE", out[-1])
        c.handle("stayunlocked maybe")
        self.assertNotIn("proposed", out[-1])
        c.handle("settings")
        self.assertIn("stay_unlocked=False", out[-1])


class Restart(unittest.TestCase):
    def hold(self, r):
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(200)

    def test_restart_needs_the_hold_keeps_data_and_comes_back_locked(self):
        r = rig()
        n = len(r.oath.list())
        r.ui.host_keep_unlocked(True)
        r.run(100)
        self.hold(r)
        self.assertTrue(r.session.keep_unlocked())
        self.assertIsNotNone(r.ui.host_restart())
        r.run(3000)
        self.assertEqual(r.ui.screen()["id"], "HostRequest")
        self.assertEqual(r.session.state(), "UNLOCKED")  # nothing yet
        self.hold(r)
        self.assertEqual(r.ui.screen()["id"], "Locked")
        self.assertEqual(len(r.oath.list()), n)
        self.assertFalse(r.session.keep_unlocked())

    def test_back_refuses_a_restart(self):
        r = rig()
        r.ui.host_restart()
        r.run(100)
        r.press("BACK")
        r.run(100)
        self.hold(r)
        self.assertEqual(r.session.state(), "UNLOCKED")


class LockedDownConsole(unittest.TestCase):
    """On the device the computer may only propose; it cannot press buttons or skip a hold."""

    def setUp(self):
        self.r = rig()
        self.out = []
        self.c = lb_console.Console(self.r, out=self.out.append, direct=False)

    def test_every_bypass_command_is_refused(self):
        for line in ("usb on", "ble on", "press p 2000", "down p", "up p", "unlock", "host SIGN", "swap", "scan 0", "fp match",
                     "clock trusted", "time 1790944123", "time demo", "warp 5000", "reboot", "reset"):
            self.out.clear()
            self.c.handle(line)
            self.assertIn("off on the device", self.out[-1], line)

    def test_a_proposal_cannot_be_approved_through_the_console(self):
        self.c.handle("settime 1790944123")
        self.r.run(100)
        self.c.handle("down p")
        self.r.run(3000)
        self.c.handle("up p")
        self.assertFalse(self.r.clock.trusted())

    def test_proposals_and_read_only_commands_still_work(self):
        for line in ("settime 1790944123", "set push_to_show off", "restart", "factoryreset",
                     "stayunlocked on", "settings", "status", "help"):
            self.out.clear()
            self.c.handle(line)
            self.assertNotIn("off on the device", " ".join(self.out), line)

    def test_direct_mode_is_the_default_for_the_simulator(self):
        out = []
        lb_console.Console(self.r, out=out.append).handle("press d 60")
        self.assertNotIn("off on the device", " ".join(out))


class ConsoleRW(unittest.TestCase):
    """The console is read-only on the device; only a fingerprint can make it read-write."""

    def setUp(self):
        self.r = rig()
        self.out = []
        self.c = lb_console.Console(self.r, out=self.out.append, direct=False)

    def hold(self):
        self.r.down("PTT")
        self.r.run(2500)
        self.r.up("PTT")
        self.r.run(200)

    def test_a_matching_fingerprint_and_a_hold_make_it_read_write(self):
        self.assertFalse(self.c.direct)
        self.c.handle("rw")
        self.r.run(100)
        self.assertFalse(self.c.direct)  # not until approved
        self.hold()
        self.assertTrue(self.c.direct)
        self.c.handle("press d 60")
        self.assertNotIn("off on the device", self.out[-1])

    def test_a_fingerprint_that_does_not_match_is_final_with_no_combo_fallback(self):
        for mode in ("nomatch", "error"):
            self.r.fp.mode = mode
            self.c.handle("rw")
            self.r.run(100)
            self.hold()
            self.assertFalse(self.c.direct, mode)
            self.assertNotEqual(self.r.ui.screen()["id"], "ComboApprove", mode)
            self.assertEqual(self.r.session.pending(), None, mode)
            self.assertIn("Fingerprint did not match", self.r.ui.screen()["lines"], mode)

    def test_the_combo_cannot_stand_in_for_the_fingerprint(self):
        self.r.fp.mode = "nomatch"
        rid = self.r.ui.host_console_rw()
        self.r.run(100)
        self.hold()
        import lb_fakes
        import lb_session
        with self.assertRaises(lb_session.NoSuchRequest):
            self.r.session.approve_with_combo(rid, lb_fakes.DEMO_COMBO)
        self.assertFalse(self.c.direct)

    def test_it_needs_an_unlocked_device(self):
        locked = Rig(push_to_show=False)
        c = lb_console.Console(locked, out=self.out.append, direct=False)
        c.handle("rw")
        self.assertIn("refused", self.out[-1])
        self.assertFalse(c.direct)

    def test_a_lock_or_restart_puts_it_back_to_read_only(self):
        self.c.handle("rw")
        self.r.run(100)
        self.hold()
        self.assertTrue(self.c.direct)
        self.r.session.lock("MANUAL")
        self.assertFalse(self.c.direct)
        self.r.run(100)
        self.r.unlock()
        self.c.handle("rw")
        self.r.run(100)
        self.hold()
        self.assertTrue(self.c.direct)
        self.r.boot()
        self.assertFalse(self.c.direct)

    def test_ro_turns_it_off_at_once(self):
        self.c.handle("rw")
        self.r.run(100)
        self.hold()
        self.c.handle("ro")
        self.assertFalse(self.c.direct)
        self.c.handle("down p")
        self.assertIn("off on the device", self.out[-1])

    def test_back_refuses_and_no_other_command_turns_it_on(self):
        self.c.handle("rw")
        self.r.run(100)
        self.r.press("BACK")
        self.r.run(100)
        self.hold()
        self.assertFalse(self.c.direct)
        for line in ("set direct on", "stayunlocked on", "settings", "status", "restart"):
            self.c.handle(line)
        self.assertFalse(self.c.direct)

    def test_settings_shows_the_console_mode(self):
        self.c.handle("settings")
        self.assertIn("console=ro", self.out[-1])

    def test_the_device_config_has_no_switch_for_it(self):
        import pico_config
        self.assertFalse(hasattr(pico_config, "CONSOLE_DIRECT"))


class Outcomes(unittest.TestCase):
    """How a proposal ended, withdrawing one, and what the device says about the computer."""

    def setUp(self):
        self.r = rig()
        self.out = []
        self.c = lb_console.Console(self.r, out=self.out.append, direct=False)

    def propose(self):
        self.c.handle("settime %d" % T0)
        self.r.run(100)

    def hold(self):
        self.r.down("PTT")
        self.r.run(2500)
        self.r.up("PTT")
        self.r.run(100)

    def result(self):
        self.c.handle("result")
        return self.out[-1]

    def test_no_result_yet(self):
        self.assertEqual(self.result(), "result none")

    def test_approved(self):
        self.propose()
        self.hold()
        self.assertTrue(self.result().endswith("APPROVED"))

    def test_refused_with_back(self):
        self.propose()
        self.r.press("BACK")
        self.r.run(100)
        self.assertTrue(self.result().endswith("CANCELLED"))

    def test_expired(self):
        self.propose()
        self.r.run(40000)
        self.assertTrue(self.result().endswith("EXPIRED"))

    def test_the_computer_can_withdraw_its_own_proposal(self):
        self.propose()
        self.c.handle("cancel")
        self.assertEqual(self.out[-1], "withdrawn")
        self.r.run(100)
        self.assertTrue(self.result().endswith("CANCELLED"))
        self.assertEqual(self.r.session.pending(), None)
        self.assertFalse(self.r.clock.trusted())
        self.c.handle("cancel")
        self.assertEqual(self.out[-1], "nothing is waiting")

    def test_a_withdrawn_proposal_cannot_be_approved_later(self):
        self.propose()
        self.c.handle("cancel")
        self.r.run(100)
        self.hold()
        self.assertFalse(self.r.clock.trusted())

    def test_the_device_reports_masked_until_pairing_exists(self):
        self.c.handle("mode")
        self.assertIn("trust=masked", self.out[-1])
        self.assertIn("console=ro", self.out[-1])
        self.assertIn("level=L1", self.out[-1])
        self.assertIn("unlock=pin", self.out[-1])
        self.assertIn("build=dev", self.out[-1])
        self.r.session.lock("MANUAL")
        self.c.handle("mode")
        self.assertIn("unlock=none", self.out[-1])


class TimeWithZone(unittest.TestCase):
    """One proposal, one hold: the clock and the zone together."""

    def hold(self, r):
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(200)

    def test_the_screen_shows_both_and_nothing_changes_until_the_hold(self):
        r = rig()
        self.assertIsNotNone(r.ui.host_set_time(T0 * 1000, 330))
        r.run(100)
        self.assertIn("2026-10-02 12:00:00 UTC, zone UTC+05:30", r.ui.screen()["lines"])
        self.assertEqual(r.settings.get("utc_offset_min"), 0)
        self.assertFalse(r.clock.trusted())

    def test_one_hold_sets_the_clock_and_the_zone(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000, -240)
        r.run(100)
        self.hold(r)
        self.assertTrue(r.clock.trusted())
        self.assertEqual(r.settings.get("utc_offset_min"), -240)
        self.assertIn("zone UTC-04:00", r.ui.screen()["lines"][0])

    def test_without_a_zone_the_existing_one_is_left_alone(self):
        r = rig()
        r.settings.set("utc_offset_min", 120)
        r.ui.host_set_time(T0 * 1000)
        r.run(100)
        self.hold(r)
        self.assertEqual(r.settings.get("utc_offset_min"), 120)
        self.assertNotIn("zone", r.ui.screen()["lines"][0])

    def test_a_bad_zone_is_refused_before_the_user_is_asked(self):
        r = rig()
        for bad in (7, 9999, -9999, 1):
            self.assertIsNone(r.ui.host_set_time(T0 * 1000, bad), bad)
        self.assertNotEqual(r.ui.screen()["id"], "HostRequest")

    def test_back_refuses_both(self):
        r = rig()
        r.ui.host_set_time(T0 * 1000, 60)
        r.run(100)
        r.press("BACK")
        r.run(100)
        self.hold(r)
        self.assertFalse(r.clock.trusted())
        self.assertEqual(r.settings.get("utc_offset_min"), 0)

    def test_the_console_takes_an_optional_zone(self):
        r = rig()
        out = []
        c = lb_console.Console(r, out=out.append, direct=False)
        c.handle("settime %d 60" % T0)
        self.assertIn("hold PTT", out[-1])
        r.run(100)
        self.hold(r)
        self.assertEqual(r.settings.get("utc_offset_min"), 60)
        for bad in ("settime %d 7" % T0, "settime %d 9999" % T0, "settime %d x" % T0):
            out.clear()
            c.handle(bad)
            self.assertNotIn("proposed", " ".join(out), bad)


class DevStop(unittest.TestCase):
    """Developer only: ending the rig program takes a PTT hold like everything else."""

    def hold(self, r):
        r.down("PTT")
        r.run(2500)
        r.up("PTT")
        r.run(200)

    def test_nothing_stops_until_the_hold(self):
        r = rig()
        self.assertIsNotNone(r.ui.host_stop())
        r.run(3000)
        self.assertEqual(r.ui.screen()["id"], "HostRequest")
        self.assertIn("Stop the rig program (dev)", r.ui.screen()["lines"])
        self.assertFalse(r.stop_requested)
        self.hold(r)
        self.assertTrue(r.stop_requested)

    def test_back_refuses_and_a_withdrawn_stop_cannot_be_approved_later(self):
        r = rig()
        r.ui.host_stop()
        r.run(100)
        r.press("BACK")
        r.run(100)
        self.hold(r)
        self.assertFalse(r.stop_requested)
        r.ui.host_stop()
        r.session.cancel(r.session.pending()["id"])
        r.run(100)
        self.hold(r)
        self.assertFalse(r.stop_requested)

    def test_it_still_works_after_a_restart_and_through_the_read_only_console(self):
        r = rig()
        r.boot()
        r.unlock()
        out = []
        c = lb_console.Console(r, out=out.append, direct=False)
        c.handle("stop")
        self.assertIn("hold PTT", out[-1])
        r.run(100)
        self.hold(r)
        self.assertTrue(r.stop_requested)

    def test_a_wiped_device_refuses(self):
        r = rig()
        r.session._wipe_now()
        self.assertIsNone(r.ui.host_stop())


if __name__ == "__main__":
    unittest.main()
