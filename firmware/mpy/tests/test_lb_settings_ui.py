import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_dt
import lb_fakes
import lb_lcd
import lb_oath
import lb_session as ls
from lb_rig import Rig

try:
    import json
except ImportError:
    json = None


def shot(r):
    s = r.ui.screen()
    if json:
        json.dumps(s)
    return s


def ready(**kw):
    r = Rig(**kw)
    r.unlock()
    assert r.id == "Idle", r.id
    return r


def open_settings(r, row=0):
    r.press("SELECT")
    assert r.id == "Settings", r.id
    for _ in range(row):
        r.press("DOWN")


def lcd(r):
    return lb_lcd.LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks())


class SettingsMenu(unittest.TestCase):
    def test_select_on_idle_opens_it(self):
        r = ready()
        open_settings(r)
        s = shot(r)
        self.assertEqual(s["id"], "Settings")
        rows = s["body"]["rows"]
        self.assertEqual([x["text"] for x in rows], ["Set time", "Time zone", "Reorder accounts", "Push to show"])
        self.assertEqual(rows[3]["value"], "ON")
        self.assertEqual(s["body"]["cursor"], 0)
        self.assertEqual(s["hints"]["select"], "Open")

    def test_navigation_clamps_and_back_goes_home(self):
        r = ready()
        open_settings(r)
        r.press("UP")
        self.assertEqual(shot(r)["body"]["cursor"], 0)
        for _ in range(5):
            r.press("DOWN")
        s = shot(r)
        self.assertEqual(s["body"]["cursor"], 3)
        self.assertEqual(s["hints"]["select"], "Toggle")
        r.press("BACK")
        self.assertEqual(r.id, "Idle")

    def test_the_chord_locks_from_settings_and_a_long_back_does_not(self):
        r = ready()
        open_settings(r)
        r.hold("BACK", 1100)
        self.assertNotEqual(r.id, "Locked")  # holding Back is just Back now
        open_settings(r)
        r.down("PTT")
        r.down("BACK")
        r.run(50)
        self.assertEqual(r.id, "Locked")

    def test_time_row_shows_the_time_or_not_set(self):
        r = ready()
        open_settings(r)
        v = shot(r)["body"]["rows"][0]["value"]
        self.assertEqual((len(v), v[2]), (5, ":"))
        r.press("BACK")
        r.clock.trusted_flag = False
        open_settings(r)
        self.assertEqual(shot(r)["body"]["rows"][0]["value"], "not set")

    def test_lcd_lines(self):
        r = ready()
        open_settings(r)
        l1, l2 = lcd(r)
        self.assertTrue(l1.startswith("Settings") and l1.rstrip().endswith("1/4"))
        self.assertTrue(l2.startswith(">Set time"))
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")
        self.assertEqual(lcd(r)[1].strip(), ">Push to show ON")
        r.press("UP")
        r.press("UP")
        self.assertEqual(lcd(r)[1].strip(), ">Zone UTC+00:00")  # "Time zone" is shortened to fit 16


class PushToShow(unittest.TestCase):
    def test_on_by_default_and_every_code_needs_a_hold(self):
        r = Rig()
        r.unlock()
        r.press("DOWN")
        r.press("SELECT")  # GitHub: no per-account flag
        self.assertEqual(r.id, "RevealPrompt")
        r.hold("PTT", 250)
        self.assertEqual(r.id, "RevealPrompt")
        self.assertIn("Keep holding", shot(r)["toast"])

    def test_visible_only_while_held_and_hides_on_release(self):
        r = Rig()
        r.unlock()
        r.press("DOWN")
        r.press("SELECT")
        r.down("PTT")
        r.run(600)
        s = shot(r)
        self.assertEqual(s["id"], "TOTPCode")
        digits = s["body"]["code"].replace(" ", "")
        self.assertEqual(s["hints"]["ptt"], "Release: hide")
        r.up("PTT")
        r.run(40)
        h = shot(r)
        self.assertEqual(h["id"], "RevealPrompt")
        self.assertNotIn(digits, repr(h))
        self.assertNotIn("code", r.ui._d)

    def test_every_account_is_gated_including_hotp(self):
        r = Rig()
        r.unlock()
        for index in range(4):
            r.press("DOWN")
            for _ in range(index):
                r.press("DOWN")
            r.press("SELECT")
            self.assertEqual(r.id, "RevealPrompt", index)
            r.press("BACK")
            r.press("BACK")

    def test_hotp_code_is_reshown_without_burning_another_counter(self):
        r = Rig()
        r.unlock()
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")  # VPN (HOTP, no per-account flag)
        r.press("SELECT")
        r.down("PTT")
        r.run(600)
        first = shot(r)["body"]["code"]
        r.up("PTT")
        r.run(40)
        r.down("PTT")
        r.run(600)
        self.assertEqual(shot(r)["body"]["code"], first)
        self.assertEqual(r.store.rec[3]["counter"], 1)

    def test_the_oath_module_refuses_a_code_without_approval(self):
        r = Rig()
        for i in (1, 2, 3, 4):
            with self.assertRaises(lb_oath.ApprovalRequired):
                r.oath.code(i)
        self.assertEqual(r.store.rec[3]["counter"], 0)  # a refused HOTP read burns nothing

    def test_turning_it_off_needs_a_hold_and_back_cancels(self):
        r = Rig()
        r.unlock()
        open_settings(r, 3)
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "ConfirmSetting")
        self.assertEqual(s["hints"]["ptt"], "Hold: turn off")
        r.press("BACK")
        self.assertEqual(r.id, "Settings")
        self.assertTrue(r.settings.get("push_to_show"))  # still on
        r.press("SELECT")
        r.hold("PTT", 250)  # too short
        self.assertEqual(r.id, "ConfirmSetting")
        self.assertTrue(r.settings.get("push_to_show"))
        r.down("PTT")
        r.run(600)
        r.up("PTT")
        r.run(40)
        s = shot(r)
        self.assertEqual(s["id"], "Settings")
        self.assertEqual(s["body"]["rows"][3]["value"], "OFF")
        self.assertIn("Push to show: OFF", s["toast"])
        self.assertFalse(r.settings.get("push_to_show"))

    def test_off_means_codes_show_without_a_hold(self):
        r = Rig()
        r.unlock()
        open_settings(r, 3)
        r.press("SELECT")
        r.down("PTT")
        r.run(600)
        r.up("PTT")
        r.run(40)
        r.press("BACK")
        r.press("DOWN")
        r.press("SELECT")
        self.assertEqual(r.id, "TOTPCode")  # plain: GitHub has no per-account flag
        self.assertEqual(shot(r)["hints"]["ptt"], "")
        r.run(10000)
        self.assertEqual(r.id, "TOTPCode")

    def test_turning_it_back_on_needs_no_hold(self):
        r = Rig(push_to_show=False)
        r.unlock()
        open_settings(r, 3)
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "Settings")
        self.assertEqual(s["body"]["rows"][3]["value"], "ON")
        self.assertTrue(r.settings.get("push_to_show"))
        with self.assertRaises(lb_oath.ApprovalRequired):
            r.oath.code(1)

    def test_fingerprint_failure_falls_back_to_the_combo(self):
        r = Rig()
        r.unlock()
        r.fp.mode = "nomatch"
        open_settings(r, 3)
        r.press("SELECT")
        r.down("PTT")
        r.run(600)
        r.up("PTT")
        r.run(40)
        self.assertEqual(r.id, "ComboApprove")
        self.assertTrue(r.settings.get("push_to_show"))
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(r.id, "Settings")
        self.assertFalse(r.settings.get("push_to_show"))

    def test_survives_a_power_cycle(self):
        r = Rig(push_to_show=False)
        r.boot()
        self.assertFalse(r.settings.get("push_to_show"))
        with_default = Rig()
        with_default.boot()
        self.assertTrue(with_default.settings.get("push_to_show"))
        with self.assertRaises(lb_oath.ApprovalRequired):
            with_default.oath.code(1)

    def test_a_failed_save_keeps_protection_on(self):
        r = Rig()
        r.unlock()
        r.settings_store.fail = True
        open_settings(r, 3)
        r.press("SELECT")
        r.down("PTT")
        r.run(600)
        r.up("PTT")
        r.run(40)
        self.assertTrue(r.settings.get("push_to_show"))
        with self.assertRaises(lb_oath.ApprovalRequired):
            r.oath.code(1)

    def test_a_device_with_no_saved_settings_starts_strict(self):
        r = Rig()
        r.settings_store.data = {"push_to_show": "garbage"}
        r.boot()
        self.assertTrue(r.settings.get("push_to_show"))


class CursorMemory(unittest.TestCase):
    def test_settings_reopens_on_the_row_you_were_on(self):
        r = ready()
        open_settings(r, 3)
        r.press("BACK")  # home
        r.press("SELECT")
        self.assertEqual(shot(r)["body"]["cursor"], 3)  # same row, not row 0

    def test_back_from_a_confirm_screen_lands_on_the_same_row(self):
        r = ready()
        open_settings(r, 3)
        r.press("SELECT")  # ConfirmSetting
        r.press("BACK")
        self.assertEqual((r.id, shot(r)["body"]["cursor"]), ("Settings", 3))

    def test_after_the_set_time_notice_the_cursor_is_on_set_time(self):
        r = ready()
        r.clock.trusted_flag = False
        open_settings(r, 0)
        r.press("SELECT")  # the editor
        r.down("PTT")
        r.run(1700)
        r.up("PTT")
        r.run(3200)
        self.assertEqual((r.id, shot(r)["body"]["cursor"]), ("Settings", 0))


class SetTime(unittest.TestCase):
    def open_editor(self, r):
        open_settings(r, 0)
        r.press("SELECT")
        self.assertEqual(r.id, "SetTime")

    def fields(self, r):
        return [f["text"] for f in shot(r)["body"]["fields"]]

    def test_starts_from_the_current_time_when_trusted(self):
        r = ready()
        r.clock.set_unix(lb_dt.to_unix(2026, 10, 2, 13, 7, 9))
        self.open_editor(r)
        self.assertEqual(self.fields(r), ["2026", "10", "02", "13", "07", "09"])

    def test_a_clock_before_2024_starts_from_the_default_instead(self):
        r = ready()
        self.assertEqual(lb_dt.to_fields(r.clock.now())[0], 2023)  # the simulated clock's own epoch
        self.open_editor(r)
        self.assertEqual(shot(r)["body"]["text"], "2026-01-01 00:00:00")

    def test_starts_from_a_sensible_default_when_never_set(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        self.assertEqual(shot(r)["body"]["text"], "2026-01-01 00:00:00")

    def test_left_right_pick_the_field_and_clamp(self):
        r = ready()
        self.open_editor(r)
        r.press("LEFT")
        self.assertEqual(shot(r)["body"]["index"], 0)
        for _ in range(8):
            r.press("RIGHT")
        self.assertEqual(shot(r)["body"]["index"], 5)
        self.assertEqual(shot(r)["body"]["fields"][5]["label"], "Second")

    def test_up_down_wrap_without_carry(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)  # 2026-01-01 00:00:00
        r.press("RIGHT")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["text"], "2026-02-01 00:00:00")
        r.press("DOWN")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["text"], "2026-12-01 00:00:00")  # month wraps, year untouched
        r.press("RIGHT")
        r.press("RIGHT")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["text"], "2026-12-01 23:00:00")  # hour wraps, day untouched
        r.press("RIGHT")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["text"], "2026-12-01 23:59:00")
        r.press("RIGHT")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["text"], "2026-12-01 23:59:01")

    def test_year_range_wraps(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.press("DOWN")
        r.press("DOWN")
        self.assertEqual(self.fields(r)[0], "2024")  # 2026 -> 2025 -> 2024, the lowest year offered
        r.press("DOWN")
        self.assertEqual(self.fields(r)[0], "2099")  # wraps to the highest
        r.press("UP")
        self.assertEqual(self.fields(r)[0], "2024")

    def test_day_follows_the_month_and_the_leap_year(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.press("RIGHT")
        r.press("RIGHT")  # Day
        r.press("DOWN")   # 01 wraps to 31
        self.assertEqual(shot(r)["body"]["text"], "2026-01-31 00:00:00")
        r.press("LEFT")
        r.press("UP")     # month 2: the day clamps to 28
        self.assertEqual(shot(r)["body"]["text"], "2026-02-28 00:00:00")
        r.press("LEFT")
        for _ in range(2):  # year 2026 -> 2028 (a leap year)
            r.press("UP")
        r.press("RIGHT")
        r.press("RIGHT")
        r.press("UP")     # 28 -> 29 exists in 2028
        self.assertEqual(shot(r)["body"]["text"], "2028-02-29 00:00:00")
        r.press("LEFT")
        r.press("LEFT")
        r.press("UP")     # 2029: Feb 29 no longer exists
        self.assertEqual(shot(r)["body"]["text"], "2029-02-28 00:00:00")

    def test_holding_up_repeats_and_release_stops_it(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        for _ in range(4):
            r.press("RIGHT")  # Minute
        r.down("UP")
        r.run(400)
        self.assertEqual(self.fields(r)[4], "01")  # before the repeat delay: just the first step
        r.run(1100)
        n = int(self.fields(r)[4])
        self.assertTrue(10 <= n <= 20, n)
        r.up("UP")
        r.run(500)
        self.assertEqual(int(self.fields(r)[4]), n)  # stopped

    def test_the_editor_itself_asks_for_the_hold(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        s = shot(r)
        self.assertEqual(s["hints"]["ptt"], "Hold: set clock")
        self.assertEqual(s["hints"]["select"], "Next field")
        self.assertEqual(s["toast"], "Hold PTT to set the clock")  # the LCD has no hint bar
        self.assertEqual(r.session.pending()["kind"], "SET_TIME")
        r.down("PTT")
        r.run(500)
        self.assertTrue(0 < shot(r)["hold"] < 1000)  # a progress bar, on the page you are editing
        r.up("PTT")

    def test_select_moves_to_the_next_field_and_wraps(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        seen = []
        for _ in range(7):
            seen.append(shot(r)["body"]["index"])
            r.press("SELECT")
        self.assertEqual(seen, [0, 1, 2, 3, 4, 5, 0])

    def test_back_cancels_and_leaves_nothing_pending(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.press("RIGHT")
        r.press("UP")
        r.press("BACK")
        self.assertEqual(r.id, "Settings")
        self.assertIsNone(r.session.pending())
        self.assertFalse(r.clock.trusted_flag)

    def test_editing_during_a_hold_resets_it(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.down("PTT")
        r.run(1000)
        r.press("UP")  # change a field with the hold in progress
        r.run(900)
        self.assertEqual(r.id, "SetTime")  # the old hold did not commit the changed value
        self.assertFalse(r.clock.trusted_flag)
        self.assertIn("release", shot(r)["toast"].lower())
        r.up("PTT")
        r.run(40)
        r.down("PTT")
        r.run(1700)  # a fresh, uninterrupted hold does
        self.assertEqual(r.id, "Notice")
        self.assertTrue(r.clock.trusted_flag)
        r.up("PTT")

    def test_the_request_is_renewed_quietly_if_you_dial_for_over_two_minutes(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        first = r.session.pending()["id"]
        for _ in range(13):  # about 130 s of dialling, with the idle lock held off
            r.session.activity()
            r.run(10000)
        self.assertEqual(r.id, "SetTime")
        self.assertIsNotNone(r.session.pending())
        self.assertNotEqual(r.session.pending()["id"], first)
        r.down("PTT")
        r.run(1700)
        r.up("PTT")
        self.assertTrue(r.clock.trusted_flag)  # and it still works afterwards
    def test_a_short_hold_does_not_set_the_clock(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.down("PTT")
        r.run(900)  # a login-length hold is not enough for the clock
        self.assertEqual(r.id, "SetTime")
        self.assertFalse(r.clock.trusted_flag)
        r.up("PTT")
        r.run(40)
        self.assertIn("Keep holding", shot(r)["toast"])
    def test_a_full_hold_sets_the_clock_and_trusts_it(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        for _ in range(3):
            r.press("RIGHT")  # Hour
        for _ in range(5):
            r.press("UP")
        r.down("PTT")
        r.run(1700)
        s = shot(r)
        self.assertEqual(s["id"], "Notice")
        self.assertEqual(s["lines"], ["Clock set: 05:00 (UTC+00:00)"])
        want = lb_dt.to_unix(2026, 1, 1, 5, 0, 0)
        self.assertTrue(r.clock.trusted_flag)
        self.assertTrue(0 <= r.clock.now() - want <= 1, r.clock.now() - want)
        r.up("PTT")
        r.run(3200)
        self.assertEqual(r.id, "Settings")
        self.assertEqual(shot(r)["body"]["rows"][0]["value"], "05:00")
    def test_codes_follow_the_new_clock(self):
        r = ready(push_to_show=False)
        self.open_editor(r)
        r.down("PTT")
        r.run(1700)
        r.up("PTT")
        r.run(3200)
        want = r.oath.code(1).digits
        r.press("BACK")
        r.press("DOWN")
        r.press("SELECT")
        self.assertEqual(shot(r)["body"]["code"].replace(" ", ""), want)
    def test_fingerprint_failure_falls_back_to_the_combo(self):
        r = ready()
        r.fp.mode = "nomatch"
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.down("PTT")
        r.run(1700)
        r.up("PTT")
        r.run(40)
        self.assertEqual(r.id, "ComboApprove")
        self.assertFalse(r.clock.trusted_flag)
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(r.id, "Notice")
        self.assertTrue(r.clock.trusted_flag)

    def test_back_from_the_combo_screen_returns_to_the_edit_with_the_edits(self):
        r = ready()
        r.fp.mode = "nomatch"
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.press("RIGHT")
        r.press("UP")  # month 02
        r.down("PTT")
        r.run(1700)
        r.up("PTT")
        r.run(40)
        self.assertEqual(r.id, "ComboApprove")
        r.press("BACK")
        self.assertEqual(r.id, "SetTime")
        self.assertEqual(shot(r)["body"]["text"], "2026-02-01 00:00:00")
        self.assertEqual(shot(r)["body"]["index"], 1)
        self.assertFalse(r.clock.trusted_flag)
    def test_a_host_request_interrupts_and_nothing_is_set(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        self.assertEqual(r.id, "HostRequest")
        self.assertFalse(r.clock.trusted_flag)
    def test_lcd_editor(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_editor(r)
        self.assertTrue(lcd(r)[1].startswith("Hold PTT to set"))  # the hint covers line 2 at first
        r.press("LEFT")  # any press dismisses it
        l1, l2 = lcd(r)
        self.assertEqual(l1, "2026-01-01 00:00")
        self.assertTrue(l2.startswith("Year <2026>") and l2.rstrip().endswith(":00"))
        for _ in range(5):
            r.press("RIGHT")
        r.press("UP")
        self.assertTrue(lcd(r)[1].startswith("Second <01>") and lcd(r)[1].rstrip().endswith(":01"))
        r.down("PTT")
        r.run(500)
        self.assertTrue(lcd(r)[0].startswith("Hold "))  # the bar replaces the date line while you hold
        self.assertTrue(lcd(r)[1].startswith("Second <01>"))
        r.up("PTT")

class TimeZone(unittest.TestCase):
    def open_zone(self, r):
        open_settings(r, 1)
        r.press("SELECT")
        self.assertEqual(r.id, "TimeZone")

    def hhmm(self, unix):
        f = lb_dt.to_fields(unix)
        return "%02d:%02d" % (f[3], f[4])

    def test_opens_on_the_current_offset_with_the_local_time(self):
        r = ready()
        self.open_zone(r)
        s = shot(r)
        self.assertEqual((s["body"]["text"], s["body"]["offset"]), ("UTC+00:00", 0))
        self.assertEqual(s["body"]["local"], self.hhmm(r.clock.now()))
        self.assertEqual((s["hints"]["select"], s["hints"]["back"]), ("Save", "Cancel"))
        self.assertIn("daylight", " ".join(s["lines"]))

    def test_up_down_move_a_quarter_hour_left_right_an_hour(self):
        r = ready()
        self.open_zone(r)
        r.press("UP")
        self.assertEqual(shot(r)["body"]["text"], "UTC+00:15")
        r.press("RIGHT")
        self.assertEqual(shot(r)["body"]["text"], "UTC+01:15")
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["text"], "UTC+00:30")
        r.press("LEFT")
        self.assertEqual(shot(r)["body"]["text"], "UTC-00:30")
        r.press("LEFT")
        self.assertEqual(shot(r)["body"]["text"], "UTC-01:30")

    def test_the_local_time_preview_follows_the_offset(self):
        r = ready()
        self.open_zone(r)
        for _ in range(5):
            r.press("RIGHT")
        self.assertEqual(shot(r)["body"]["local"], self.hhmm(r.clock.now() + 5 * 3600))

    def test_the_range_clamps_at_both_ends(self):
        r = ready()
        self.open_zone(r)
        for _ in range(20):
            r.press("LEFT")
        self.assertEqual(shot(r)["body"]["text"], "UTC-12:00")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["offset"], -720)
        for _ in range(30):
            r.press("RIGHT")
        self.assertEqual(shot(r)["body"]["text"], "UTC+14:00")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["offset"], 840)

    def test_quarter_hour_zones_show_correctly(self):
        r = ready()
        self.open_zone(r)
        for _ in range(5):
            r.press("RIGHT")
        for _ in range(2):
            r.press("UP")
        self.assertEqual(shot(r)["body"]["text"], "UTC+05:30")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["text"], "UTC+05:45")  # Nepal

    def test_select_saves_and_shows_it_in_settings(self):
        r = ready()
        self.open_zone(r)
        for _ in range(2):
            r.press("RIGHT")
        r.press("SELECT")
        s = shot(r)
        self.assertEqual((s["id"], s["body"]["cursor"]), ("Settings", 1))
        self.assertEqual(s["toast"], "Zone: UTC+02:00")
        self.assertEqual(s["body"]["rows"][1]["value"], "UTC+02:00")
        self.assertEqual(r.settings.get("utc_offset_min"), 120)
        self.assertFalse(r.settings_store.data is None)

    def test_back_cancels_without_saving(self):
        r = ready()
        self.open_zone(r)
        for _ in range(3):
            r.press("RIGHT")
        r.press("BACK")
        self.assertEqual(r.id, "Settings")
        self.assertEqual(r.settings.get("utc_offset_min"), 0)

    def test_it_survives_a_power_cycle(self):
        r = ready()
        self.open_zone(r)
        r.press("LEFT")
        r.press("LEFT")
        r.press("SELECT")
        r.boot()
        self.assertEqual(r.settings.get("utc_offset_min"), -120)

    def test_a_failed_save_says_so_and_stays_on_the_page(self):
        r = ready()
        self.open_zone(r)
        r.press("RIGHT")
        r.settings_store.fail = True
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "TimeZone")
        self.assertIn("Not saved", s["toast"])
        self.assertEqual(r.settings.get("utc_offset_min"), 0)

    def test_holding_up_repeats(self):
        r = ready()
        self.open_zone(r)
        r.down("UP")
        r.run(1600)
        r.up("UP")
        n = shot(r)["body"]["offset"] // 15
        self.assertTrue(10 <= n <= 20, n)

    def test_the_status_bar_and_settings_show_local_time(self):
        r = ready()
        r.clock.set_unix(lb_dt.to_unix(2026, 10, 2, 13, 0, 0))
        self.assertEqual(shot(r)["status"]["time"], "13:00")
        self.open_zone(r)
        for _ in range(2):
            r.press("RIGHT")
        r.press("SELECT")
        self.assertEqual(shot(r)["status"]["time"], "15:00")  # UTC+2
        self.assertEqual(shot(r)["body"]["rows"][0]["value"], "15:00")
        r.press("BACK")
        self.assertEqual(lcd(r)[0][-5:], "15:00")  # on the LCD's Idle line too

    def test_the_clock_stays_utc_underneath_so_codes_do_not_change(self):
        r = ready(push_to_show=False)
        before = r.oath.code(1).digits
        r.clock.set_unix(lb_dt.to_unix(2026, 10, 2, 13, 0, 0))
        base = r.oath.code(1).digits
        self.open_zone(r)
        for _ in range(3):
            r.press("RIGHT")
        r.press("SELECT")
        self.assertEqual(r.oath.code(1).digits, base)  # a zone is only a display setting
        self.assertTrue(0 <= r.clock.now() - lb_dt.to_unix(2026, 10, 2, 13, 0, 0) <= 3)  # still UTC
        self.assertNotEqual(before, "")

    def test_set_time_is_typed_in_local_time_and_stored_as_utc(self):
        r = ready()
        r.clock.trusted_flag = False
        open_settings(r, 1)
        r.press("SELECT")
        for _ in range(5):
            r.press("RIGHT")
        for _ in range(2):
            r.press("UP")  # +5:30
        r.press("SELECT")
        self.assertEqual(shot(r)["body"]["rows"][1]["value"], "UTC+05:30")
        r.press("UP")  # row 0: Set time
        r.press("SELECT")
        self.assertEqual(r.id, "SetTime")
        self.assertIn("UTC+05:30", shot(r)["title"])
        for _ in range(3):
            r.press("RIGHT")  # Hour
        for _ in range(12):
            r.press("UP")  # 12:00 local
        r.down("PTT")
        r.run(1700)
        s = shot(r)
        self.assertEqual(s["lines"], ["Clock set: 12:00 (UTC+05:30)"])
        want_utc = lb_dt.to_unix(2026, 1, 1, 12, 0, 0) - 5 * 3600 - 30 * 60
        self.assertTrue(0 <= r.clock.now() - want_utc <= 1, r.clock.now() - want_utc)
        self.assertEqual(self.hhmm(r.clock.now()), "06:30")  # UTC underneath
        r.up("PTT")

    def test_the_editor_starts_from_local_time_when_the_clock_is_set(self):
        r = ready()
        r.clock.set_unix(lb_dt.to_unix(2026, 10, 2, 13, 7, 9))
        self.open_zone(r)
        for _ in range(3):
            r.press("LEFT")  # UTC-03:00
        r.press("SELECT")
        r.press("UP")
        r.press("SELECT")
        t = shot(r)["body"]["text"]
        self.assertEqual(t[:16], "2026-10-02 10:07")  # local = UTC-3; the seconds drift while the buttons are pressed
        self.assertTrue(9 <= int(t[17:]) <= 15, t)

    def test_a_local_date_before_1970_cannot_happen_through_the_editor(self):
        r = ready()
        r.clock.trusted_flag = False
        self.open_zone(r)
        for _ in range(20):
            r.press("LEFT")
        r.press("SELECT")
        r.press("UP")
        r.press("SELECT")
        for _ in range(3):
            r.press("DOWN")  # year wraps within 2024..2099, never below
        self.assertGreaterEqual(int(shot(r)["body"]["fields"][0]["text"]), 2024)

    def test_lcd_zone_page_and_settings_row(self):
        r = ready()
        self.open_zone(r)
        for _ in range(5):
            r.press("RIGHT")
        for _ in range(2):
            r.press("UP")
        l1, l2 = lcd(r)
        self.assertEqual(l1.strip(), "Time zone")
        self.assertTrue(l2.startswith("UTC+05:30 ") and l2[-5:] == self.hhmm(r.clock.now() + 19800))
        r.press("SELECT")
        self.assertEqual(lcd(r)[1].strip(), "Zone: UTC+05:30")  # the saved-toast, which fits 16
        r.run(2600)
        self.assertEqual(lcd(r)[1].strip(), ">Zone UTC+05:30")


class Reorder(unittest.TestCase):
    def names(self, r):
        return [e["issuer"] for e in r.oath.list()]

    def open_reorder(self, r):
        open_settings(r, 2)
        r.press("SELECT")
        self.assertEqual(r.id, "Reorder")

    def test_needs_two_accounts(self):
        r = ready(seed=False)
        open_settings(r, 2)
        r.press("SELECT")
        self.assertEqual(shot(r)["lines"], ["Nothing to reorder"])
        r.oath.add(lb_oath.Entry("a", "JBSWY3DPEHPK3PXP"), approved=True)
        r.press("BACK")
        r.press("SELECT")
        self.assertEqual(shot(r)["lines"], ["Nothing to reorder"])

    def test_grab_move_drop(self):
        r = ready()
        self.open_reorder(r)
        s = shot(r)
        self.assertEqual((s["body"]["total"], s["body"]["index"], s["body"]["grabbed"]), (4, 0, False))
        self.assertEqual(s["hints"]["select"], "Grab")
        r.press("SELECT")
        self.assertTrue(shot(r)["body"]["grabbed"])
        self.assertEqual(shot(r)["hints"]["select"], "Drop")
        r.press("DOWN")
        r.press("DOWN")
        s = shot(r)
        self.assertEqual(s["body"]["index"], 2)
        self.assertEqual(s["body"]["rows"][2]["text"], "GitHub alice")  # the grabbed one travelled
        self.assertEqual(self.names(r)[0], "GitHub")  # nothing saved until the drop
        r.press("SELECT")
        self.assertEqual(self.names(r), ["Example Bank", "VPN", "GitHub", "Work Vault"])
        self.assertIn("position 3", shot(r)["toast"])
        self.assertFalse(shot(r)["body"]["grabbed"])

    def test_one_save_per_drop_not_per_step(self):
        r = ready()
        saves = []
        orig = r.store.save_order
        r.store.save_order = lambda ids: (saves.append(list(ids)), orig(ids))[1]
        self.open_reorder(r)
        r.press("SELECT")
        for _ in range(3):
            r.press("DOWN")
        r.press("UP")
        r.press("SELECT")
        self.assertEqual(len(saves), 1)

    def test_cancel_puts_it_back(self):
        r = ready()
        self.open_reorder(r)
        r.press("DOWN")
        r.press("SELECT")
        r.press("DOWN")
        r.press("DOWN")
        r.press("BACK")
        s = shot(r)
        self.assertEqual(r.id, "Reorder")
        self.assertFalse(s["body"]["grabbed"])
        self.assertEqual(s["body"]["index"], 1)  # the cursor is back on the account's own slot
        self.assertEqual(s["body"]["rows"][1]["text"], "Example Bank alice@example.com")
        self.assertIn("cancelled", s["toast"])
        self.assertEqual(self.names(r), ["GitHub", "Example Bank", "VPN", "Work Vault"])

    def test_dropping_where_it_started_saves_nothing(self):
        r = ready()
        saves = []
        orig = r.store.save_order
        r.store.save_order = lambda ids: (saves.append(1), orig(ids))[1]
        self.open_reorder(r)
        r.press("SELECT")
        r.press("DOWN")
        r.press("UP")
        r.press("SELECT")
        self.assertEqual(saves, [])

    def test_edges_clamp(self):
        r = ready()
        self.open_reorder(r)
        r.press("UP")
        self.assertEqual(shot(r)["body"]["index"], 0)
        r.press("SELECT")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["rows"][0]["text"], "GitHub alice")
        for _ in range(9):
            r.press("DOWN")
        self.assertEqual(shot(r)["body"]["index"], 3)
        self.assertEqual(shot(r)["body"]["rows"][3]["text"], "GitHub alice")

    def test_a_failed_save_reverts_and_says_so(self):
        r = ready()
        r.store.fail_order = True
        self.open_reorder(r)
        r.press("SELECT")
        r.press("DOWN")
        r.press("SELECT")
        s = shot(r)
        self.assertIn("not saved", s["toast"])
        self.assertEqual(s["body"]["rows"][0]["text"], "GitHub alice")
        self.assertEqual(self.names(r)[0], "GitHub")

    def test_back_returns_to_settings_on_the_reorder_row_and_the_order_shows_in_accounts(self):
        r = ready()
        self.open_reorder(r)
        r.press("SELECT")
        r.press("DOWN")
        r.press("SELECT")
        r.press("BACK")
        s = shot(r)
        self.assertEqual((s["id"], s["body"]["cursor"]), ("Settings", 2))
        r.press("BACK")
        r.press("DOWN")
        self.assertEqual(shot(r)["body"]["rows"][0]["text"], "Example Bank alice@example.com")

    def test_survives_a_power_cycle(self):
        r = ready()
        self.open_reorder(r)
        r.press("SELECT")
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")
        r.boot()
        self.assertEqual(self.names(r), ["Example Bank", "VPN", "GitHub", "Work Vault"])

    def test_opens_on_the_account_you_last_used_and_lcd_marks_the_grab(self):
        r = ready(push_to_show=False)
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")  # opens the second account's code
        r.press("BACK")
        r.press("BACK")
        self.open_reorder(r)
        self.assertEqual(shot(r)["body"]["index"], 1)
        self.assertTrue(lcd(r)[1].startswith(">"))
        r.press("SELECT")
        self.assertTrue(lcd(r)[1].startswith("*"))
        self.assertTrue(lcd(r)[0].startswith("Reorder"))


if __name__ == "__main__":
    unittest.main()
