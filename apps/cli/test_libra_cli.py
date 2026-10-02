import io
import json
import sys
import unittest

import libra
import libra_policy as policy
import libra_transport as tr

tr.QUIET_S = 0.0  # the fake answers at once


class Board:
    """Pretends to be the rig's console: the same commands and replies, scriptable outcomes."""

    def __init__(self, decision="APPROVED", polls=2, trust="masked", unlock="pin", build="dev", rig=True,
                 reject=None, silent=False, lose_link_after=None):
        self.mode = {"trust": trust, "build": build, "unlock": unlock, "console": "ro", "level": "L1",
                     "usb": "False", "ble": "False", "stay_unlocked": "False"}
        self.settings = {"push_to_show": "True", "utc_offset_min": "0"}
        self.clock_trusted = False
        self.pending = None
        self.decision = decision
        self.polls = polls
        self.polls_left = 0
        self.last = None
        self.n = 0
        self.rig = rig
        self.reject = reject  # a refusal sentence for any proposal
        self.silent = silent
        self.lose_link_after = lose_link_after
        self.stopped = False  # `stop` was approved: the rig no longer answers
        self.ignore_zone = False  # an old device: takes the time, ignores the zone
        self.out = b""
        self.sent = []
        self.in_waiting = 0

    def reset_input_buffer(self):
        self.out = b""

    def close(self):
        pass

    def _say(self, text):
        self.out += (text + "\r\n").encode()

    def read(self, n):
        d, self.out = self.out[:n], self.out[n:]
        self.in_waiting = len(self.out)
        return d

    def _propose(self, kind, effect, msg="change proposed: hold PTT on the device to approve"):
        if self.reject:
            return self._say("error: refused (%s)" % self.reject)
        self.pending = (kind, effect)
        self.polls_left = self.polls
        self._say(msg)

    def write(self, data):
        self.sent.append(data)
        if self.lose_link_after is not None:
            self.lose_link_after -= 1
            if self.lose_link_after < 0:
                raise OSError("device reports readiness to read but returned no data")
        line = data.decode().strip()
        if not line or self.silent:
            return
        if line.startswith("import pico_main"):
            self.rig = True
            return
        if self.stopped and self.rig:
            self.rig = False
        if not self.rig:
            return self._say("Traceback (most recent call last):\nNameError: name '%s' isn't defined" % line.split()[0])
        cmd, *args = line.split()
        if cmd == "mode":
            self._say(" ".join("%s=%s" % kv for kv in self.mode.items()))
        elif cmd == "status":
            if self.pending and self.polls_left <= 0:
                self._resolve()
            elif self.pending:
                self.polls_left -= 1
            self._say("screen Idle | session UNLOCKED | attempts 0 | accounts 4")
            self._say("pending %s | fp match | clock %s 12:00" % (
                "none" if not self.pending else "%s: x" % self.pending[0],
                "trusted" if self.clock_trusted else "NOT trusted"))
        elif cmd == "settings":
            self._say(" ".join("%s=%s" % kv for kv in self.settings.items()))
            self._say("stay_unlocked=False console=ro")
        elif cmd == "result":
            self._say("result none" if not self.last else "result %d %s" % self.last)
        elif cmd == "cancel":
            if self.pending:
                self.pending = None
                self.n += 1
                self.last = (self.n, "CANCELLED")
                self._say("withdrawn")
            else:
                self._say("nothing is waiting")
        elif cmd == "settime":
            zone = args[1] if len(args) > 1 else None

            def effect():
                self.clock_trusted = True
                if zone is not None and not self.ignore_zone:
                    self.settings["utc_offset_min"] = zone
            self._propose("SET_TIME", effect, "time proposed: hold PTT on the device to approve")
        elif cmd == "set":
            key, val = args
            self._propose("SETTING", lambda: self.settings.__setitem__(
                key, ("True" if val == "on" else "False") if key == "push_to_show" else val))
        elif cmd in ("restart", "factoryreset"):
            self._propose(cmd.upper(), lambda: None)
        elif cmd == "stop":
            self._propose("STOP", lambda: setattr(self, "stopped", True),
                          "stop proposed: hold PTT on the device to approve, Back to refuse")
        elif cmd == "stayunlocked":
            self._propose("MODE", lambda: self.mode.__setitem__("stay_unlocked", "True" if args[0] == "on" else "False"))
        elif cmd == "rw":
            self._propose("CONSOLE_RW", lambda: self.mode.__setitem__("console", "rw"),
                          "read-write requested: only a fingerprint on the device approves it")
        elif cmd == "ro":
            self.mode["console"] = "ro"
            self._say("console is read-only")
        else:
            self._say("error: unknown command")

    def _resolve(self):
        kind, effect = self.pending
        self.pending = None
        self.n += 1
        self.last = (self.n, self.decision)
        if self.decision == "APPROVED":
            effect()


def run(argv, board, answers=(), **kw):
    """Run the CLI against the fake board; returns (exit code, stdout lines, stderr lines)."""
    out, err = [], []
    it = iter(answers)

    class Ctx:
        def __enter__(self_):
            return tr.Console(board)

        def __exit__(self_, *a):
            pass
    code = libra.main(argv, input_fn=lambda p: next(it), out=out.append, err=err.append,
                      transport_factory=lambda args, e: Ctx(), **kw)
    return code, out, err


class Policy(unittest.TestCase):
    def mode(self, **kw):
        m = {"trust": "masked", "unlock": "pin", "build": "dev"}
        m.update(kw)
        return m

    def test_the_device_scope_is_allowed_from_a_masked_computer(self):
        for path in [p for p, r in policy.RULES.items() if r[0] == "device"]:
            self.assertTrue(policy.check(path, self.mode(unlock="none"))[0], path)

    def test_accounts_hosts_data_need_a_session_and_pin_plus_fingerprint(self):
        for scope in ("accounts", "hosts", "data"):
            rules = [(p, r) for p, r in policy.RULES.items() if r[0] == scope]
            self.assertTrue(rules)
            for path, (_, trust, unlock, _) in rules:
                self.assertEqual((trust, unlock), ("session", "pin+fp"), path)

    def test_planned_commands_say_so(self):
        ok, why = policy.check(("accounts", "list"), self.mode(trust="session", unlock="pin+fp"))
        self.assertFalse(ok)
        self.assertIn("planned", why)

    def test_dev_commands_need_a_dev_build(self):
        self.assertTrue(policy.check(("dev", "console"), self.mode())[0])
        ok, why = policy.check(("dev", "console"), self.mode(build="release"))
        self.assertFalse(ok)
        self.assertIn("dev builds only", why)

    def test_trust_and_unlock_are_ordered_and_separate(self):
        self.assertLess(policy.rank(policy.TRUST, "masked"), policy.rank(policy.TRUST, "session"))
        self.assertLess(policy.rank(policy.TRUST, "session"), policy.rank(policy.TRUST, "paired"))
        self.assertLess(policy.rank(policy.UNLOCK, "pin"), policy.rank(policy.UNLOCK, "pin+fp"))
        self.assertEqual(set(policy.TRUST) & set(policy.UNLOCK), set())
        self.assertEqual({r[0] for r in policy.RULES.values()}, set(policy.SCOPES))

    def test_unknown_values_never_pass(self):
        self.assertFalse(policy.check(("device", "status"), {})[0])
        self.assertFalse(policy.check(("nope",), self.mode())[0])


class Zone(unittest.TestCase):
    def test_good_and_bad(self):
        self.assertEqual(libra.parse_zone("UTC-08:00"), -480)
        self.assertEqual(libra.parse_zone("utc+05:30"), 330)
        for text, mins in (("+05:30", 330), ("-08:00", -480), ("0", 0), ("60", 60), ("-90", -90), ("+14:00", 840)):
            self.assertEqual(libra.parse_zone(text), mins, text)
        for text in ("+15:00", "-13:00", "7", "+05:61", "abc", "+5:x"):
            with self.assertRaises(ValueError, msg=text):
                libra.parse_zone(text)


class TimeZone(unittest.TestCase):
    def setUp(self):
        self._orig = libra.computer_offset_minutes
        libra.computer_offset_minutes = lambda now=None: 60

    def tearDown(self):
        libra.computer_offset_minutes = self._orig

    def test_the_computers_zone_is_sent_with_the_time_in_one_proposal(self):
        b = Board()
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 0)
        proposals = [x for x in b.sent if x.startswith(b"settime")]
        self.assertEqual(len(proposals), 1)  # one request, so one hold
        self.assertTrue(proposals[0].decode().strip().endswith(" 60"))
        self.assertEqual(b.settings["utc_offset_min"], "60")
        self.assertIn("zone set to UTC+01:00", out[-1])
        self.assertIn("daylight-saving", out[-1])

    def test_no_zone_sends_only_the_time(self):
        b = Board()
        code, out, _ = run(["device", "time", "set", "--no-zone"], b)
        self.assertEqual(code, 0)
        self.assertEqual(len(b.sent[-0:] and [x for x in b.sent if x.startswith(b"settime")][0].split()), 2)
        self.assertEqual(b.settings["utc_offset_min"], "0")
        self.assertIn("zone was left alone", out[-1])

    def test_negative_zones_work_in_every_spelling(self):
        for argv in (["device", "time", "set", "--zone", "-08:00"], ["device", "time", "set", "--zone=-08:00"],
                     ["device", "time", "set", "--zone", "UTC-08:00"], ["device", "time", "set", "--zone", "-480"],
                     ["device", "setting", "set", "zone", "-08:00"], ["--yes", "device", "setting", "set", "zone", "-08:00"]):
            b = Board()
            code, out, _ = run(argv, b)
            self.assertEqual(code, 0, argv)
            self.assertEqual(b.settings["utc_offset_min"], "-480", argv)

    def test_zone_overrides_the_computers(self):
        b = Board()
        code, out, _ = run(["device", "time", "set", "--zone", "-08:00"], b)
        self.assertEqual(code, 0)
        self.assertEqual(b.settings["utc_offset_min"], "-480")

    def test_zone_and_no_zone_cannot_be_combined_and_a_bad_zone_is_a_usage_error(self):
        b = Board()
        for argv in (["device", "time", "set", "--zone", "+1:00", "--no-zone"],
                     ["device", "time", "set", "--zone", "+20:00"]):
            old = sys.stderr
            sys.stderr = io.StringIO()
            try:
                try:
                    code = run(argv, b)[0]
                except SystemExit as e:
                    code = e.code
            finally:
                sys.stderr = old
            self.assertEqual(code, 3, argv)
        self.assertFalse(any(x.startswith(b"settime") for x in b.sent))

    def test_a_device_that_ignores_the_zone_is_reported_not_trusted_blindly(self):
        b = Board()
        b.ignore_zone = True
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 1)
        self.assertIn("reports zone 0, not 60", out[-1])

    def test_refusing_changes_neither(self):
        b = Board(decision="CANCELLED")
        code, _, _ = run(["device", "time", "set"], b)
        self.assertEqual((code, b.settings["utc_offset_min"], b.clock_trusted), (1, "0", False))

    def test_a_zone_the_device_cannot_hold_sends_only_the_time(self):
        libra.computer_offset_minutes = lambda now=None: None
        b = Board()
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 0)
        self.assertIn("only the clock is sent", " ".join(out))

    def test_json_carries_the_zone(self):
        code, out, _ = run(["device", "time", "set", "--json"], Board())
        self.assertEqual(json.loads(out[0])["data"]["zone_min"], 60)


class ZoneHelpers(unittest.TestCase):
    def test_the_computers_offset_is_rounded_to_the_devices_steps_and_range(self):
        import os
        import time as _t
        old = os.environ.get("TZ")
        try:
            for tz, want in (("UTC0", 0), ("CET-1", 60), ("EST5", -300), ("IST-5:30", 330), ("NPT-5:45", 345)):
                os.environ["TZ"] = tz
                _t.tzset()
                self.assertEqual(libra.computer_offset_minutes(1790944123), want, tz)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            _t.tzset()

    def test_zone_text(self):
        self.assertEqual(libra.zone_text(330), "UTC+05:30")
        self.assertEqual(libra.zone_text(-480), "UTC-08:00")
        self.assertEqual(libra.zone_text(0), "UTC+00:00")

    def test_the_proposal_line(self):
        self.assertEqual(tr.settime_command(1790944123.4567), "settime 1790944123.456")
        self.assertEqual(tr.settime_command(1790944123.4567, 330), "settime 1790944123.456 330")
        self.assertEqual(tr.settime_command(1790944123.0, -480), "settime 1790944123.000 -480")


class Commands(unittest.TestCase):
    def test_status_shows_the_trust_level_and_the_device(self):
        code, out, _ = run(["device", "status"], Board())
        self.assertEqual(code, 0)
        text = "\n".join(out)
        self.assertIn("seen as: masked", text)
        self.assertIn("unlocked with: pin", text)
        self.assertIn("push_to_show=True", text)

    def test_time_set_approved_and_verified(self):
        b = Board()
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 0)
        self.assertTrue(any(x.startswith("Clock set") for x in out))
        self.assertTrue(b.clock_trusted)
        self.assertTrue(any(s.startswith(b"settime ") for s in b.sent))

    def test_a_refusal_on_the_device_is_a_clear_nothing_changed(self):
        b = Board(decision="CANCELLED")
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 1)
        self.assertIn("Refused on the device", out[-1])
        self.assertFalse(b.clock_trusted)

    def test_a_request_that_lapses_while_the_device_is_locked_says_so(self):
        b = Board(decision="LOCKED_TIMEOUT", unlock="none")
        code, out, _ = run(["device", "time", "set"], b)
        self.assertEqual(code, 1)
        self.assertTrue(any("LOCKED" in x and "unlock it first" in x for x in out))
        self.assertIn("still locked when the request lapsed", out[-1])
        self.assertFalse(b.clock_trusted)

    def test_an_unknown_decision_is_shown_not_hidden(self):
        code, out, _ = run(["device", "time", "set"], Board(decision="SOMETHING_NEW"))
        self.assertEqual(code, 1)
        self.assertIn("SOMETHING_NEW", out[-1])

    def test_expired(self):
        code, out, _ = run(["device", "time", "set"], Board(decision="EXPIRED"))
        self.assertEqual(code, 1)
        self.assertIn("expired", out[-1])

    def test_the_device_rejecting_a_proposal(self):
        code, out, _ = run(["device", "time", "set"], Board(reject="wiped, or the time is out of range"))
        self.assertEqual(code, 1)
        self.assertIn("would not take it", out[-1])

    def test_no_approval_in_time_withdraws_it(self):
        b = Board(polls=10 ** 9)
        code, out, _ = run(["device", "time", "set", "--wait", "1"], b)
        self.assertEqual(code, 1)
        self.assertIn("withdrawn", out[-1])
        self.assertIsNone(b.pending)
        self.assertFalse(b.clock_trusted)

    def test_setting_zone_and_push_to_show_read_back(self):
        b = Board()
        code, out, _ = run(["device", "setting", "set", "zone", "+05:30"], b)
        self.assertEqual(code, 0)
        self.assertEqual(b.settings["utc_offset_min"], "330")
        self.assertIn("utc_offset_min=330", out[-1])
        code, out, _ = run(["device", "setting", "set", "push-to-show", "off"], b)
        self.assertEqual(code, 0)
        self.assertEqual(b.settings["push_to_show"], "False")

    def test_bad_values_are_usage_errors_before_anything_is_sent(self):
        b = Board()
        self.assertEqual(run(["device", "setting", "set", "zone", "+20:00"], b)[0], 3)
        self.assertEqual(run(["device", "setting", "set", "push-to-show", "maybe"], b)[0], 3)
        self.assertFalse(any(s.startswith(b"set ") for s in b.sent))

    def test_setting_list(self):
        code, out, _ = run(["device", "setting", "list"], Board())
        self.assertEqual(code, 0)
        self.assertIn("push_to_show=True", out[-1])

    def test_restart_and_factory_reset_need_the_typed_word(self):
        for argv, word in ((["device", "restart"], "RESTART"), (["device", "factory-reset"], "RESET")):
            b = Board()
            code, out, _ = run(argv, b, answers=["no"])
            self.assertEqual(code, 1, argv)
            self.assertIn("Cancelled.", out)
            self.assertFalse(any(s.startswith((b"restart", b"factoryreset")) for s in b.sent), argv)
            b = Board()
            code, out, _ = run(argv, b, answers=[word])
            self.assertEqual(code, 0, argv)

    def test_yes_skips_the_prompt_but_not_the_hold(self):
        b = Board(decision="CANCELLED")
        code, out, _ = run(["device", "factory-reset", "--yes"], b, answers=[])
        self.assertEqual(code, 1)
        self.assertTrue(any(s.startswith(b"factoryreset") for s in b.sent))

    def test_stay_unlocked(self):
        b = Board()
        self.assertEqual(run(["dev", "stay-unlocked", "on"], b)[0], 0)
        self.assertEqual(b.mode["stay_unlocked"], "True")

    def test_console_rw_is_verified_and_ro_is_immediate(self):
        b = Board()
        self.assertEqual(run(["dev", "console", "rw"], b)[0], 0)
        self.assertEqual(b.mode["console"], "rw")
        self.assertEqual(run(["dev", "console", "ro"], b)[0], 0)
        self.assertEqual(b.mode["console"], "ro")

    def test_a_fingerprint_that_does_not_match_is_reported(self):
        code, out, _ = run(["dev", "console", "rw"], Board(decision="DENIED"))
        self.assertEqual(code, 1)
        self.assertIn("fingerprint did not match", out[-1])


class Options(unittest.TestCase):
    def test_global_options_work_before_or_after_the_command(self):
        for argv in (["--yes", "--wait", "5", "device", "restart"], ["device", "--yes", "restart", "--wait", "5"],
                     ["device", "restart", "--yes", "--wait=5"], ["--wait=5", "--yes", "device", "restart"]):
            code, out, _ = run(argv, Board(), answers=[])
            self.assertEqual(code, 0, argv)

    def test_hoisting_keeps_values_with_their_flags(self):
        self.assertEqual(libra.hoist_options(["--port", "/dev/x", "device", "status", "--json"]),
                         ["device", "status", "--port", "/dev/x", "--json"])
        self.assertEqual(libra.hoist_options(["device", "setting", "set", "zone", "UTC-08:00"]),
                         ["device", "setting", "set", "zone", "UTC-08:00"])


class DevStartStop(unittest.TestCase):
    def test_stop_needs_the_hold_and_is_verified_by_the_rig_going_quiet(self):
        b = Board()
        code, out, _ = run(["dev", "stop"], b)
        self.assertEqual(code, 0)
        self.assertIn("Stopped", out[-1])
        self.assertIn("libra dev start", out[-1])
        self.assertFalse(b.rig)

    def test_a_rig_that_vanishes_between_polls_still_counts_as_stopped(self):
        class Vanishing(Board):
            def _resolve(self):
                Board._resolve(self)
                self.rig = False  # gone before even the next status
        b = Vanishing()
        b.stopped = False
        code, out, _ = run(["dev", "stop"], b)
        self.assertEqual(code, 0)

    def test_only_stop_reads_a_silent_rig_as_approval(self):
        class Vanishing(Board):
            def _resolve(self):
                Board._resolve(self)
                self.rig = False
        code, out, _ = run(["device", "time", "set"], Vanishing())
        self.assertEqual(code, 1)  # a time request that ends in silence is NOT assumed approved

    def test_a_refused_stop_leaves_the_rig_running(self):
        b = Board(decision="CANCELLED")
        code, out, _ = run(["dev", "stop"], b)
        self.assertEqual(code, 1)
        self.assertTrue(b.rig)

    def test_stop_needs_a_dev_build(self):
        b = Board(build="release")
        code, out, _ = run(["dev", "stop"], b)
        self.assertEqual(code, 1)
        self.assertFalse(any(s.startswith(b"stop") for s in b.sent))

    def test_start_launches_the_rig_without_asking_for_a_hold(self):
        b = Board(rig=False)
        code, out, _ = run(["dev", "start"], b)
        self.assertEqual(code, 0)
        self.assertTrue(b.rig)
        self.assertTrue(any(s.startswith(b"import pico_main") for s in b.sent))
        self.assertIn("comes up locked", out[-1])
        self.assertFalse(any(s.startswith(b"stop") for s in b.sent))

    def test_start_when_it_is_already_running_does_nothing(self):
        b = Board()
        code, out, _ = run(["dev", "start"], b)
        self.assertEqual(code, 0)
        self.assertIn("already running", out[-1])
        self.assertFalse(any(s.startswith(b"import") for s in b.sent))

    def test_start_on_a_silent_board_does_not_interrupt_it(self):
        b = Board(silent=True)
        code, out, _ = run(["dev", "start"], b)
        self.assertEqual(code, 1)
        self.assertFalse(any(s.startswith(b"import") or b"\x03" in s for s in b.sent))

    def test_the_policy_lists_both_as_dev_scope(self):
        for verb in ("stop", "start"):
            self.assertEqual(policy.RULES[("dev", verb)][0], "dev")


class Planned(unittest.TestCase):
    def test_planned_commands_explain_themselves_without_touching_the_board(self):
        for argv in (["accounts", "list"], ["hosts", "pair"], ["data", "backup"]):
            b = Board()
            code, out, _ = run(argv, b)
            self.assertEqual(code, 1, argv)
            self.assertIn("planned", out[-1])
            self.assertEqual(b.sent, [], argv)


class Gates(unittest.TestCase):
    def test_dev_commands_refused_on_a_release_build(self):
        b = Board(build="release")
        code, out, _ = run(["dev", "console", "rw"], b)
        self.assertEqual(code, 1)
        self.assertIn("dev builds only", out[-1])
        self.assertFalse(any(s.startswith(b"rw") for s in b.sent))

    def test_nothing_is_proposed_when_policy_says_no(self):
        b = Board(trust="masked")
        orig = dict(policy.RULES)
        policy.RULES[("device", "restart")] = ("device", "session", "pin+fp", "ready")
        try:
            code, out, _ = run(["device", "restart", "--yes"], b)
        finally:
            policy.RULES.clear()
            policy.RULES.update(orig)
        self.assertEqual(code, 1)
        self.assertIn("needs a session computer", out[-1])
        self.assertFalse(any(s.startswith(b"restart") for s in b.sent))

    def test_the_board_at_a_python_prompt_gets_the_rig_started(self):
        b = Board(rig=False)
        code, out, _ = run(["device", "status"], b)
        self.assertEqual(code, 0)
        self.assertIn("rig started.", out)
        self.assertTrue(any(s.startswith(b"import pico_main") for s in b.sent))

    def test_a_silent_board_is_never_interrupted(self):
        b = Board(silent=True)
        code, out, _ = run(["device", "status"], b)
        self.assertEqual(code, 1)
        self.assertTrue(any("Not interrupting" in s for s in out))
        self.assertFalse(any(s.startswith(b"import") or b"\x03" in s for s in b.sent))

    def test_a_dropped_link_has_its_own_exit_code_and_message(self):
        b = Board(lose_link_after=3)
        code, out, err = run(["device", "time", "set"], b)
        self.assertEqual(code, 2)
        self.assertTrue(any("Run the command again" in s for s in err))


class Output(unittest.TestCase):
    def test_json_is_one_object_with_the_outcome(self):
        code, out, err = run(["device", "time", "set", "--json"], Board())
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1)
        obj = json.loads(out[0])
        self.assertEqual((obj["ok"], obj["outcome"], obj["command"]), (True, "approved", "libra device time set"))

    def test_json_failure(self):
        code, out, err = run(["device", "time", "set", "--json"], Board(decision="CANCELLED"))
        obj = json.loads(out[0])
        self.assertEqual((code, obj["ok"], obj["outcome"]), (1, False, "refused"))

    def test_json_status_carries_the_mode(self):
        code, out, _ = run(["device", "status", "--json"], Board())
        obj = json.loads(out[0])
        self.assertEqual(obj["data"]["mode"]["trust"], "masked")

    def test_verbose_shows_the_raw_exchange_on_the_error_stream(self):
        lines = []
        b = Board()

        class Ctx:
            def __enter__(self_):
                return tr.Console(b, lines.append)

            def __exit__(self_, *a):
                pass
        libra.main(["device", "status"], out=lambda s: None, err=lambda s: None,
                   transport_factory=lambda a, e: Ctx())
        self.assertTrue(any(x.startswith(">> mode") for x in lines))
        self.assertTrue(any(x.startswith("<< trust=masked") for x in lines))

    def test_policy_command_needs_no_board_and_has_json(self):
        out = []
        self.assertEqual(libra.main(["policy"], out=out.append), 0)
        self.assertIn("masked < session < paired", out[0])
        out.clear()
        libra.main(["policy", "--json"], out=out.append)
        obj = json.loads(out[0])
        self.assertEqual(obj["trust_levels"], list(policy.TRUST))

    def test_dry_run_sends_nothing(self):
        b = Board()
        code, out, _ = run(["device", "factory-reset", "--dry-run"], b)
        self.assertEqual(code, 0)
        self.assertEqual(b.sent, [])

    def test_usage_errors_exit_3(self):
        for argv in (["nonsense"], ["device"], ["device", "setting", "set"], []):
            old_err, old_out = sys.stderr, sys.stdout
            sys.stderr = io.StringIO()
            sys.stdout = io.StringIO()
            try:
                try:
                    code = libra.main(argv, out=lambda s: None)
                except SystemExit as e:
                    code = e.code
            finally:
                sys.stderr, sys.stdout = old_err, old_out
            self.assertEqual(code, 3, argv)


class Update(unittest.TestCase):
    def test_dev_update_runs_on_this_computer_without_opening_the_board(self):
        calls = []

        def updater(port=None, with_tests=False, dry_run=False, confirm=None, out=print):
            calls.append((with_tests, dry_run, confirm is None))
            return 0
        out = []

        def boom(args, e):
            raise AssertionError("must not open the serial port")
        code = libra.main(["dev", "update", "--with-tests", "--yes"], out=out.append, err=out.append,
                          transport_factory=boom, updater=updater)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [(True, False, True)])

    def test_without_yes_it_asks_for_the_word(self):
        seen = []

        def updater(port=None, with_tests=False, dry_run=False, confirm=None, out=print):
            seen.append(confirm("overwrite?"))
            return 0
        libra.main(["dev", "update"], input_fn=lambda p: "UPDATE", out=lambda s: None, err=lambda s: None,
                   updater=updater)
        libra.main(["dev", "update"], input_fn=lambda p: "nope", out=lambda s: None, err=lambda s: None,
                   updater=updater)
        self.assertEqual(seen, [True, False])


if __name__ == "__main__":
    unittest.main()
