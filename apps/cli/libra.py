#!/usr/bin/env python3
"""libra - talk to a Libra from this computer.

    libra device status                     what the device says about itself and about this computer
    libra device time set                   propose this computer's clock and zone (one approval)
                                            --zone +05:30 to send another zone, --no-zone to skip it
    libra device setting list
    libra device setting set push-to-show on|off
    libra device setting set zone +05:30    (or minutes: 330)
    libra device restart                    data kept, comes back locked
    libra device factory-reset              ERASES everything
    libra dev stay-unlocked on|off          bench tools, dev builds only
    libra dev console rw|ro
    libra dev stop                          end the rig program on the board (needs the PTT hold)
    libra dev start                         run the rig on the board again (comes up locked)
    libra dev update [--with-tests]         copy this repository's firmware to the board
    libra policy                            what each command needs

This tool is untrusted by design: it only PROPOSES. Every action waits for a PTT hold on the
device (Back refuses it, Ctrl-C withdraws it), and the device decides what a computer may ask.
Global options work before or after the command: --port, --json, --yes, --wait, --verbose, --dry-run.
Exit codes: 0 done, 1 not done (refused, expired, rejected...), 2 the link to the board failed,
3 bad usage.
"""
import argparse
import json
import re
import sys
import time

import libra_policy as policy
import libra_transport as tr

EXIT_OK, EXIT_NOT_DONE, EXIT_LINK, EXIT_USAGE = 0, 1, 2, 3


class Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit 3, so 2 stays free for "the link failed"
        self.print_usage(sys.stderr)
        sys.stderr.write("libra: error: %s\n" % message)
        raise SystemExit(EXIT_USAGE)


def parse_zone(text):
    """'+05:30' / '-08:00' / 'UTC-08:00' / '60' / '-90' -> minutes east of UTC."""
    t = text.strip()
    if t.upper().startswith("UTC"):
        t = t[3:]
    if ":" in t:
        sign = -1 if t.startswith("-") else 1
        h, _, m = t.lstrip("+-").partition(":")
        if not (h.isdigit() and m.isdigit() and 0 <= int(m) < 60):
            raise ValueError("zone must look like +05:30")
        minutes = sign * (int(h) * 60 + int(m))
    else:
        minutes = int(t)
    if not -720 <= minutes <= 840 or minutes % 15:
        raise ValueError("zone must be -12:00..+14:00 in 15-minute steps")
    return minutes


def zone_text(minutes):
    a = abs(minutes)
    return "UTC%s%02d:%02d" % ("+" if minutes >= 0 else "-", a // 60, a % 60)


def computer_offset_minutes(now=None):
    """This computer's current offset from UTC in minutes, rounded to the device's 15-minute steps,
    or None if the device cannot hold it. It is today's offset: the device has no daylight-saving
    rules, so run `time set` again when the clocks change."""
    t = time.time() if now is None else now
    try:
        off = time.localtime(t).tm_gmtoff // 60
    except (AttributeError, OverflowError, OSError, ValueError):
        return None
    off = int(round(off / 15.0)) * 15
    return off if -720 <= off <= 840 else None


_GLOBAL_FLAGS = ("--json", "--yes", "--verbose", "--dry-run")
_GLOBAL_VALUED = ("--port", "--wait")


def hoist_options(argv):
    """Move the global options to the end, so they work before or after the command. (argparse only
    sees an option where its own parser expects it.)"""
    rest, opts = [], []
    it = iter(argv)
    for x in it:
        if x in _GLOBAL_FLAGS or any(x.startswith(f + "=") for f in _GLOBAL_VALUED):
            opts.append(x)
        elif x in _GLOBAL_VALUED:
            opts.append(x)
            nxt = next(it, None)
            if nxt is not None:
                opts.append(nxt)
        else:
            rest.append(x)
    return rest + opts


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("options")
    g.add_argument("--port", help="serial port (default: find the one Pico)")
    g.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    g.add_argument("--yes", action="store_true", help="skip the typed Are-you-sure prompt (never the PTT hold)")
    g.add_argument("--wait", type=int, default=45, help="seconds to wait for the PTT hold (default 45)")
    g.add_argument("--verbose", action="store_true", help="show the raw exchange with the device on stderr")
    g.add_argument("--dry-run", action="store_true", help="show what would be sent and stop")

    top = Parser(prog="libra", description="Talk to a Libra. The computer only proposes; the device decides.",
                 epilog="Run 'libra policy' to see what each command needs.")
    top.add_argument("--version", action="version", version="libra cli 0.1 (prototype console link)")
    scopes = top.add_subparsers(dest="scope", metavar="scope", parser_class=Parser)

    def leaf(parent, name, path, help_, **kw):
        p = parent.add_parser(name, parents=[common], help=help_, description=help_)
        p.set_defaults(path=path)
        return p

    dev_ = scopes.add_parser("device", help="the Libra itself", parents=[common])
    dsub = dev_.add_subparsers(dest="verb", metavar="command", parser_class=Parser)
    leaf(dsub, "status", ("device", "status"), "what the device says about itself and about this computer")
    leaf(dsub, "restart", ("device", "restart"), "restart (data kept; comes back locked)")
    leaf(dsub, "factory-reset", ("device", "factory-reset"), "ERASE every account and setting")
    t = dsub.add_parser("time", help="the device clock", parents=[common])
    ts = leaf(t.add_subparsers(dest="sub", metavar="command", parser_class=Parser), "set", ("device", "time", "set"),
              "propose this computer's current time (UTC) and its time zone, in one approval")
    zg = ts.add_mutually_exclusive_group()
    zg.add_argument("--zone", metavar="ZONE", help="send this zone instead of the computer's (+05:30, -08:00 or minutes)")
    zg.add_argument("--no-zone", action="store_true", help="set only the clock; leave the device's zone alone")
    s = dsub.add_parser("setting", help="device settings", parents=[common])
    ssub = s.add_subparsers(dest="sub", metavar="command", parser_class=Parser)
    leaf(ssub, "list", ("device", "setting", "list"), "show the settings")
    ps = leaf(ssub, "set", ("device", "setting", "set"), "propose a settings change")
    ps.add_argument("name", choices=["push-to-show", "zone"])
    ps.add_argument("value")

    d2 = scopes.add_parser("dev", help="bench tools (dev builds only)", parents=[common])
    xsub = d2.add_subparsers(dest="verb", metavar="command", parser_class=Parser)
    su = leaf(xsub, "stay-unlocked", ("dev", "stay-unlocked"), "test mode: no idle lock (unlock the device first)")
    su.add_argument("value", choices=["on", "off"])
    co = leaf(xsub, "console", ("dev", "console"), "rw: console may press buttons (fingerprint only); ro: back at once")
    co.add_argument("value", choices=["rw", "ro"])
    leaf(xsub, "stop", ("dev", "stop"), "end the rig program on the board (the board is left at its Python prompt)")
    leaf(xsub, "start", ("dev", "start"), "run the rig program on the board (it comes up locked)")
    up = leaf(xsub, "update", ("dev", "update"), "copy this repository's firmware to the board and verify")
    up.add_argument("--with-tests", action="store_true", help="also copy the tests/ folder")

    # planned scopes: accepted so the policy can explain, never run
    for scope in ("accounts", "hosts", "data"):
        sp = scopes.add_parser(scope, help=policy.SCOPES[scope] + " (planned)", parents=[common])
        sub = sp.add_subparsers(dest="verb", metavar="command", parser_class=Parser)
        for path, rule in policy.RULES.items():
            if path[0] == scope:
                leaf(sub, path[1], path, "(planned) " + path[1])

    leaf(scopes, "policy", ("policy",), "what each command needs: trust level, unlock strength, scope")
    return top


class Result:
    def __init__(self, ok, outcome, message="", data=None):
        self.ok = ok
        self.outcome = outcome
        self.message = message
        self.data = data or {}


def confirm(what, word, input_fn=input, out=print):
    """Ask before sending anything. `word` is typed to confirm, so a stray Enter does nothing."""
    out(what)
    return input_fn("Type %s to continue, anything else cancels: " % word).strip() == word


def _outcome_result(o, ok_message):
    if o.kind == tr.APPROVED:
        return Result(True, o.kind, ok_message)
    texts = {tr.REFUSED: "Refused on the device (Back). Nothing was changed.",
             tr.EXPIRED: "The request expired before it was approved. Nothing was changed.",
             tr.DENIED: "The fingerprint did not match. Nothing was changed.",
             tr.LOCKED: "The device was still locked when the request lapsed (about 30 s). Unlock it, then run "
                        "the command again. Nothing was changed.",
             tr.REJECTED: "The device would not take it: %s" % o.detail,
             tr.TIMEOUT: "Nothing was changed: %s." % o.detail,
             tr.WITHDRAWN: "Nothing was changed: %s." % o.detail,
             tr.NO_RIG: o.detail}
    return Result(False, o.kind, texts.get(o.kind, o.detail))


class Cli:
    def __init__(self, args, tport, out, err, input_fn, mode=None):
        self.mode = mode or {}  # what the device reported at the start
        self.a = args
        self.t = tport
        self.out = out
        self.err = err
        self.input = input_fn

    def say(self, msg):
        (self.err if self.a.json else self.out)(msg)

    def tick(self, left):
        if self.err is not None and self.a.json is False and sys.stdout.isatty():
            sys.stdout.write("\r  waiting for the PTT hold... %2d s " % left)
            sys.stdout.flush()

    def propose(self, line, ok_message, intro="Hold PTT on the Libra to approve (Back to refuse, Ctrl-C to withdraw).",
                ends_rig=False):
        if self.mode.get("unlock") == "none":
            self.say("The device is LOCKED: unlock it first. A request from a computer lapses after about 30 s.")
        self.say("Proposed. " + intro)
        o = self.t.propose(line, self.a.wait, self.tick, ends_rig)
        if sys.stdout.isatty() and not self.a.json:
            sys.stdout.write("\r" + " " * 48 + "\r")
        return _outcome_result(o, ok_message)

    # ---- commands

    def device_status(self):
        mode = self.t.mode()
        st = self.t.status()
        data = {"mode": mode, "status": {k: v for k, v in st.items() if k != "raw"},
                "settings": self.t.settings()}
        lines = ["computer is seen as: %s  (device unlocked with: %s, %s build, console %s)" % (
                    mode.get("trust", "?"), mode.get("unlock", "?"), mode.get("build", "?"), mode.get("console", "?")),
                 "screen: %s   session: %s   pending: %s" % (st.get("screen", "?"), st.get("session", "?"),
                                                              st.get("pending") or "nothing"),
                 "clock: %s (%s)" % (st.get("clock", "?"), "set" if st.get("clock_trusted") else "NOT set"),
                 "settings: " + " ".join("%s=%s" % kv for kv in sorted(data["settings"].items())),
                 "usb: %s   ble: %s   stay-unlocked: %s" % (mode.get("usb", "?"), mode.get("ble", "?"),
                                                           mode.get("stay_unlocked", "?"))]
        return Result(True, "ok", "\n".join(lines), data)

    def time_set(self):
        a = self.a
        zone = None
        if not a.no_zone:
            zone = parse_zone(a.zone) if a.zone else computer_offset_minutes()
            if zone is None:
                self.say("(this computer's zone does not fit the device, so only the clock is sent)")
        what = "the clock" + (" and the zone %s" % zone_text(zone) if zone is not None else "")
        r = self.propose(tr.settime_command(offset_min=zone), "Clock set.",
                         "Hold PTT on the Libra to set %s (Back to refuse, Ctrl-C to withdraw)." % what)
        if not r.ok:
            return r
        if not self.t.status().get("clock_trusted"):
            return Result(False, "unverified", "Approved, but the device does not report a set clock.")
        data = {"zone_min": zone}
        if zone is None:
            return Result(True, r.outcome, "Clock set (UTC). The zone was left alone.", data)
        now = self.t.settings()
        if now.get("utc_offset_min") != str(zone):
            return Result(False, "unverified", "The clock is set, but the device reports zone %s, not %s." % (
                now.get("utc_offset_min"), zone), data)
        return Result(True, r.outcome, "Clock set (UTC) and zone set to %s. The device has no daylight-saving "
                      "rules: run this again when your clocks change." % zone_text(zone), data)

    def setting_list(self):
        s = self.t.settings()
        return Result(bool(s), "ok" if s else "no_answer", " ".join("%s=%s" % kv for kv in sorted(s.items())) or "no answer", s)

    def setting_set(self):
        a = self.a
        key = {"push-to-show": "push_to_show", "zone": "utc_offset_min"}[a.name]
        if key == "push_to_show":
            if a.value not in ("on", "off"):
                return Result(False, "usage", "push-to-show takes on or off")
            line, want = "set push_to_show " + a.value, str(a.value == "on")
        else:
            minutes = parse_zone(a.value)
            line, want = "set utc_offset_min %d" % minutes, str(minutes)
        r = self.propose(line, "Done.")
        if r.ok:
            now = self.t.settings()
            if now.get(key) != want:
                return Result(False, "unverified", "Approved, but the device reports %s=%s." % (key, now.get(key)), now)
            r.data = now
            r.message = "Done. Now: " + " ".join("%s=%s" % kv for kv in sorted(now.items()))
        return r

    def restart(self):
        if not self.a.yes and not confirm("This restarts the Libra. Data is kept, it comes back LOCKED, and "
                                          "stay-unlocked ends.", "RESTART", self.input, self.say):
            return Result(False, "cancelled", "Cancelled.")
        return self.propose("restart", "Restarted: the device is locked.")

    def factory_reset(self):
        if not self.a.yes and not confirm("This ERASES every account and setting on the Libra. It cannot be undone.",
                                          "RESET", self.input, self.say):
            return Result(False, "cancelled", "Cancelled.")
        return self.propose("factoryreset", "Factory reset done: the device is locked and empty.",
                            "Hold PTT on the Libra to ERASE EVERYTHING (Back to refuse, Ctrl-C to withdraw).")

    def stay_unlocked(self):
        r = self.propose("stayunlocked " + self.a.value, "Stay-unlocked %s." % self.a.value)
        return r

    def stop(self):
        r = self.propose("stop", "Stopped.", ends_rig=True)
        if r.ok and not self.t.wait_until_stopped():
            return Result(False, "unverified", "Approved, but the rig is still answering.")
        if r.ok:
            r.message = "Stopped: the board is at its Python prompt. `libra dev start` runs the rig again."
        return r

    def console(self):
        if self.a.value == "ro":
            self.t.ask("ro")
            mode = self.t.mode()
            return Result(mode.get("console") == "ro", "ok", "Console is read-only.", mode)
        r = self.propose("rw", "Console is read-write until the next lock or restart.",
                         "Only a FINGERPRINT on the device approves this (and a PTT hold).")
        if r.ok and self.t.mode().get("console") != "rw":
            return Result(False, "unverified", "Approved, but the console is still read-only.")
        return r


def show_policy(out, as_json):
    rows = policy.table()
    if as_json:
        out(json.dumps({"trust_levels": policy.TRUST, "unlock_strengths": policy.UNLOCK,
                        "scopes": policy.SCOPES,
                        "commands": [dict(zip(("command", "scope", "trust", "unlock", "status"), r)) for r in rows]}))
        return
    out("Trust levels (the computer):  " + " < ".join(policy.TRUST))
    out("Unlock strength (the device): " + " < ".join(policy.UNLOCK))
    out("Every allowed action still needs a PTT hold on the device.\n")
    out("%-26s %-9s %-8s %-8s %s" % ("command", "scope", "trust", "unlock", "status"))
    for cmd, scope, trust, unlock, status in rows:
        out("%-26s %-9s %-8s %-8s %s" % ("libra " + cmd, scope, trust, unlock, status))
    out("\nScopes:")
    for k, v in policy.SCOPES.items():
        out("  %-9s %s" % (k, v))


def default_transport(args, err):
    """Open the serial port. Returns a context manager yielding a tr.Console."""
    import serial

    class Ctx:
        def __enter__(self_):
            self_.ser = serial.Serial(args.port or tr.find_port(), tr.BAUD, timeout=0.1)
            return tr.Console(self_.ser, err if args.verbose else None)

        def __exit__(self_, *exc):
            self_.ser.close()
    return Ctx()


def main(argv=None, input_fn=input, out=print, err=None, transport_factory=None, updater=None):
    err = err or (lambda s: print(s, file=sys.stderr))
    parser = build_parser()
    # argparse reads "-08:00" as an option flag; spell such zones "UTC-08:00" before it sees them
    argv = [("UTC" + x if re.match(r"^-\d{1,2}:\d{2}$", x) else x) for x in (sys.argv[1:] if argv is None else argv)]
    argv = hoist_options(argv)
    args = parser.parse_args(argv)
    path = getattr(args, "path", None)
    if path is None:
        parser.print_help()
        return EXIT_USAGE
    if path == ("policy",):
        show_policy(out, args.json)
        return EXIT_OK
    name = "libra " + " ".join(path)

    def finish(r):
        if args.json:
            out(json.dumps({"ok": r.ok, "command": name, "outcome": r.outcome, "message": r.message,
                            "data": r.data}))
        else:
            out(r.message)
        return EXIT_OK if r.ok else EXIT_NOT_DONE

    if policy.RULES.get(path, (0, 0, 0, 0))[3] == policy.PLANNED:  # nothing to send: say so, even with no board
        return finish(Result(False, "planned", policy.check(path, {})[1] + ". Run 'libra policy' to see what is built."))

    if path == ("device", "time", "set") and getattr(args, "zone", None):
        try:
            parse_zone(args.zone)
        except ValueError as e:
            err("libra: error: %s" % e)
            return EXIT_USAGE
    if path == ("device", "setting", "set") and args.name == "zone":
        try:
            parse_zone(args.value)
        except ValueError as e:
            err("libra: error: %s" % e)
            return EXIT_USAGE
    if path == ("device", "setting", "set") and args.name == "push-to-show" and args.value not in ("on", "off"):
        err("libra: error: push-to-show takes on or off")
        return EXIT_USAGE

    if path in policy.HOST_SIDE:  # runs here: no serial session of ours may hold the port
        import libra_update
        run = updater or libra_update.update
        conf = None if args.yes else (lambda what: confirm(what, "UPDATE", input_fn, out))
        if args.dry_run:
            return EXIT_OK if run(port=args.port or None, with_tests=args.with_tests, dry_run=True,
                                  confirm=None, out=out) == 0 else EXIT_NOT_DONE
        code = run(port=args.port or None, with_tests=args.with_tests, dry_run=False, confirm=conf,
                   out=out if not args.json else err)
        return finish(Result(code == 0, "ok" if code == 0 else "failed",
                             "Updated." if code == 0 else "Update did not finish."))

    if args.dry_run:
        out("would run: %s (nothing sent)" % name)
        return EXIT_OK

    try:
        ctx = (transport_factory or default_transport)(args, err)
        with ctx as t:
            if path == ("dev", "start"):  # nothing is running to ask for a hold: this only launches it
                if t.rig_running():
                    return finish(Result(True, "already_running", "The rig is already running."))
                ok = t.ensure_rig(err if args.json else out)
                return finish(Result(ok, "started" if ok else "no_rig",
                                     "The rig is running; the device comes up locked." if ok
                                     else "Could not start the rig."))
            if not t.ensure_rig(err if args.json else out):
                return finish(Result(False, "no_rig", "The board is not answering as a Libra."))
            mode = t.mode()
            ok, why = policy.check(path, mode)
            if not ok:
                return finish(Result(False, "refused_by_policy", why + "."))
            cli = Cli(args, t, out, err, input_fn, mode)
            handler = {("device", "status"): cli.device_status, ("device", "time", "set"): cli.time_set,
                       ("device", "setting", "list"): cli.setting_list, ("device", "setting", "set"): cli.setting_set,
                       ("device", "restart"): cli.restart, ("device", "factory-reset"): cli.factory_reset,
                       ("dev", "stay-unlocked"): cli.stay_unlocked, ("dev", "console"): cli.console,
                       ("dev", "stop"): cli.stop}[path]
            return finish(handler())
    except Exception as e:  # noqa: BLE001 - a dropped serial link must not show a traceback
        if e.__class__.__name__ in ("SerialException", "OSError") or isinstance(e, OSError):
            err("libra: " + tr.link_lost_message(e))
            return EXIT_LINK
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
