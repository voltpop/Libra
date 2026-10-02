# lb_ui.py - UI model: the screen state machine, with no rendering
#
# Spec: LIBRA.md "User interface" (screens, gestures, hold-to-confirm) and "Host-side
# development". Inputs are button events, scanned QR payloads and a tick; the output is
# screen(), a plain dict (an id plus fields) that any renderer can draw. It drives the real
# session, oath, qrparse and hold-engine modules; only the drivers are simulated.
#
# Screens in this slice: Locked, Idle, ShowQR (placeholder), Accounts, TOTPCode, ConfirmOTP,
# RevealPrompt, HostRequest, ComboApprove (fingerprint fallback), ShowText, Notice, Wiped.
#
# Gestures: D-pad moves, Select opens, Back goes up one level (a long Back locks the device),
# PTT tap = harmless (show my QR), PTT hold = commit. Every consequential action is a request
# registered with the session and approved by a hold on the request screen.

import lb_dt
import lb_hold
import lb_oath
import lb_qrparse
import lb_session
import lb_settings
import lb_ticks

BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "PTT")
_DIRS = {"UP": 0, "DOWN": 1, "LEFT": 2, "RIGHT": 3}

LOCKED = "Locked"
IDLE = "Idle"
SHOW_QR = "ShowQR"
ACCOUNTS = "Accounts"
TOTP_CODE = "TOTPCode"
CONFIRM_OTP = "ConfirmOTP"
REVEAL = "RevealPrompt"
HOST_REQUEST = "HostRequest"
COMBO_APPROVE = "ComboApprove"
SHOW_TEXT = "ShowText"
NOTICE = "Notice"
WIPED = "Wiped"
SETTINGS = "Settings"
SET_TIME = "SetTime"
TIME_ZONE = "TimeZone"
REORDER = "Reorder"
CONFIRM_SETTING = "ConfirmSetting"

_REQUEST_SCREENS = (CONFIRM_OTP, REVEAL, HOST_REQUEST, COMBO_APPROVE, SET_TIME, CONFIRM_SETTING)

# Hold duration class by request kind (see lb_hold: login about 0.5 s, sign/delete 1.5 s)
_HOLD_KIND = {"AUTH": "login", "OATH_REVEAL": "login", "OATH_ADD": "login", "VAULT": "login",
              "STICK": "login", "SETTING": "login", "SET_TIME": "sign", "SIGN": "sign", "DECRYPT": "sign", "XCH_SIGN": "sign",
              "BACKUP": "sign", "RESTORE": "sign", "RESET": "sign", "MODE": "login", "RESTART": "login", "CONSOLE_RW": "login", "STOP": "login"}

LONG_BACK_MS = 1000
TAP_MAX_MS = 400
NOTICE_MS = 3000
TOAST_MS = 2500
SHOW_QR_MS = 30000
REVEAL_AUTOHIDE_MS = 8000  # a code revealed by combo (no PTT held to release) hides itself
ROWS = 6
REPEAT_DELAY_MS = 500  # holding Up or Down on the Set time page repeats after this...
REPEAT_STEP_MS = 80    # ...then every this often
YEAR_MIN = 2024
YEAR_MAX = 2099
TIME_START = lb_dt.to_unix(2026, 1, 1)  # where the editor starts when the clock was never set
_TIME_LABELS = ("Year", "Month", "Day", "Hour", "Minute", "Second")
_TIME_RANGE = ((YEAR_MIN, YEAR_MAX), (1, 12), (1, 31), (0, 23), (0, 59), (0, 59))
MAX_TEXT_SHOWN = 160
TRAIL_MAX = 300


def _safe_ascii(b, limit):
    """Show unknown scanned bytes without interpreting them: printable ASCII, '?' otherwise."""
    out = []
    for c in b[:limit]:
        out.append(chr(c) if 32 <= c < 127 else "?")
    s = "".join(out)
    return s + "..." if len(b) > limit else s


def _group(code):
    h = len(code) // 2
    return code[:h] + " " + code[h:]


class UI:
    def __init__(self, session, oath, hold, ticks, rtc, name="Libra", level="L1", haptic=None,
                 settings=None, set_time=None, factory_reset=None, restart=None, console_rw=None,
                 usb_present=None, ble_active=None, stop=None):
        self._s = session
        self._oath = oath
        self._hold = hold
        self._ticks = ticks    # callable: wrap-around ms
        self._rtc = rtc        # trusted() / now() -> unix seconds
        self._name = name
        self._level = level
        self._haptic = haptic
        self._settings = settings if settings is not None else lb_settings.Settings()
        self._set_time = set_time  # callable(unix): sets the clock and trusts it
        self._factory_reset = factory_reset  # callable(): erase everything and start over
        self._stop = stop  # callable(): end the prototype rig program (developer only)
        self._ble = ble_active  # callable() -> bool: is BLE on (None: never)
        self._usb = usb_present  # callable() -> bool: is USB plugged in (None: never)
        self._console_rw = console_rw  # callable(bool): lets the console act directly (fingerprint only)
        self._restart = restart  # callable(): power-cycle the model; data kept, comes back locked
        self._rep_name = None
        self._rep_next = 0
        self._proposal = None  # what the host proposed and is waiting on a hold for (a dict, see host_*)
        oath.set_reveal_all(self._settings.get("push_to_show"))
        self._ptt = False
        self._ptt_t = 0
        self._back_t = 0
        self._last_sec = ticks()
        self._toast = None
        self._toast_until = 0
        self._permille = None
        self._flow = None
        self._focus = None  # id of the account the list cursor returns to
        self._set_cursor = 0  # the Settings row you were last on
        self._stash = None  # (account id, HOTP code) kept so a re-reveal does not burn another counter
        self.trail = []
        self._beep = 0
        self._beep_kind = None
        self._scr = IDLE
        self._d = {}
        self._combo = []
        session.set_listener(self._on_session_event)
        self._enter(LOCKED)
        self._sync()

    # ------------------------------------------------------------ plumbing

    def _log(self, kind, text):
        self.trail.append((self._ticks(), kind, text))
        if len(self.trail) > TRAIL_MAX:
            del self.trail[:len(self.trail) - TRAIL_MAX]

    def _pulse(self, kind):
        self._beep += 1
        self._beep_kind = kind
        if self._haptic is not None:
            self._haptic.pulse(kind)
        self._log("haptic", kind)

    def _on_session_event(self, evt, data):
        if evt == lb_session.EVT_LOCK_CHANGED and data != lb_session.UNLOCKED and self._console_rw:
            self._console_rw(False)  # read-write ends with the unlock
        self._log("session", "%s %s" % (evt, data))

    def _enter(self, scr, **data):
        if scr != self._scr:
            self._log("screen", "%s -> %s" % (self._scr, scr))
        self._scr = scr
        self._d = data
        self._toast = None
        self._rep_name = None
        if scr in (LOCKED, COMBO_APPROVE):
            self._combo = []
        if scr not in _REQUEST_SCREENS:
            self._flow = None
        if scr == SHOW_QR:
            data["until"] = lb_ticks.add(self._ticks(), SHOW_QR_MS)

    def _goto(self, scr):
        if scr == ACCOUNTS:
            self._open_accounts()
        elif scr == SETTINGS:
            self._open_settings()
        else:
            self._enter(scr)

    def _say(self, text):
        self._toast = text
        self._toast_until = lb_ticks.add(self._ticks(), TOAST_MS)

    def _notice(self, text, ret=IDLE):
        self._enter(NOTICE, text=text, ret=ret, until=lb_ticks.add(self._ticks(), NOTICE_MS))

    # ------------------------------------------------------------ input

    def button(self, name, down):
        if name not in BUTTONS:
            raise ValueError("unknown button")
        down = bool(down)
        self._log("btn", "%s %s" % (name, "down" if down else "up"))
        if self._s.wiped():
            return
        self._s.activity()
        now = self._ticks()
        if name == "PTT":
            if down:
                self._ptt = True
                self._ptt_t = now
            else:
                held = lb_ticks.diff(now, self._ptt_t)
                self._ptt = False
                if self._scr == IDLE and held <= TAP_MAX_MS:
                    self._pulse("tap")
                    self._enter(SHOW_QR)
                elif self._scr == TOTP_CODE and self._d.get("gate"):
                    self._hide_code()
        elif name == "BACK":
            if down:
                self._back_t = now
            else:
                self._back(lb_ticks.diff(now, self._back_t) >= LONG_BACK_MS)
        elif down:
            self._press(name)
            if name in ("UP", "DOWN") and self._scr in (SET_TIME, TIME_ZONE):
                self._rep_name = name
                self._rep_next = lb_ticks.add(now, REPEAT_DELAY_MS)
        elif name == self._rep_name:
            self._rep_name = None
        self._sync()

    def scan(self, payload):
        """The simulated camera delivered a decoded QR payload (bytes)."""
        self._log("scan", "%d bytes" % len(payload))
        if self._s.wiped() or self._s.state() != lb_session.UNLOCKED:
            return False
        if self._scr not in (IDLE, ACCOUNTS):
            return False
        self._s.activity()
        try:
            msg = lb_qrparse.parse(payload)
        except lb_qrparse.ParseError as e:
            if bytes(payload[:10]).lower() == b"otpauth://":
                self._notice("Bad OTP code: " + str(e))
            else:  # never act on unknown payloads; show the source
                self._enter(SHOW_TEXT, text=_safe_ascii(bytes(payload), MAX_TEXT_SHOWN))
            self._pulse("error")
            return True
        try:
            entry = lb_oath.from_qr(msg)
        except lb_oath.OathError as e:
            self._notice("Rejected: " + str(e))
            self._pulse("error")
            return True
        for a in self._oath.list():
            if a["issuer"] == entry.issuer and a["account"] == entry.account:
                self._notice("Already added")
                return True
        summary = ("Add %s %s" % (entry.issuer, entry.account))[:90]
        self._start_flow(CONFIRM_OTP, "OATH_ADD", summary, entry=entry)
        self._sync()
        return True

    def _start_flow(self, scr, kind, summary, **data):
        try:
            rid = self._s.request(kind, "UI", summary)
        except lb_session.SessionError as e:
            self._notice("Cannot start: " + str(e))
            return
        self._enter(scr, **data)
        self._flow = rid

    # ------------------------------------------------------------ gestures

    def _press(self, name):
        scr = self._scr
        if scr == LOCKED or scr == COMBO_APPROVE:
            if name in _DIRS:
                if len(self._combo) < self._s.policy().combo_max:
                    self._combo.append(_DIRS[name])
            elif name == "SELECT":
                self._submit_combo()
        elif scr == IDLE:
            if name == "SELECT":
                self._open_settings()
            else:
                self._open_accounts()
        elif scr == SETTINGS:
            self._press_settings(name)
        elif scr == SET_TIME:
            self._time_edit(name)
        elif scr == TIME_ZONE:
            self._zone_edit(name)
        elif scr == REORDER:
            self._press_reorder(name)
        elif scr == ACCOUNTS:
            n = len(self._d["rows"])
            if name == "UP":
                self._d["cursor"] = max(0, self._d["cursor"] - 1)
            elif name == "DOWN":
                self._d["cursor"] = min(n - 1, self._d["cursor"] + 1) if n else 0
            elif name == "SELECT" and n:
                self._open_account(self._d["rows"][self._d["cursor"]])
        elif scr == NOTICE and name == "SELECT":
            self._goto(self._d["ret"])

    def _back(self, long_press):
        scr = self._scr
        if scr == LOCKED:
            self._combo = []
            return
        if long_press:
            self._s.lock("BACK")
            return
        if scr in (CONFIRM_OTP, REVEAL, HOST_REQUEST, COMBO_APPROVE, SET_TIME, CONFIRM_SETTING):
            if self._flow is not None:
                self._s.cancel(self._flow)
            origin = self._d.get("back") if scr == COMBO_APPROVE else scr
            if origin == REVEAL:
                self._open_accounts()
            elif scr == COMBO_APPROVE and origin == SET_TIME:
                self._open_set_time(self._d.get("v"), self._d.get("f", 0))  # back to the edit
            elif origin in (SET_TIME, CONFIRM_SETTING):
                self._open_settings()
            else:
                self._enter(IDLE)
        elif scr == SETTINGS:
            self._enter(IDLE)
        elif scr == TIME_ZONE:
            self._open_settings()
        elif scr == REORDER:
            self._back_reorder()
        elif scr in (ACCOUNTS, SHOW_QR, SHOW_TEXT):
            self._enter(IDLE)
        elif scr == TOTP_CODE:
            self._open_accounts()
        elif scr == NOTICE:
            self._goto(self._d["ret"])

    def _open_accounts(self):
        self._stash = None
        rows = self._oath.list()
        cursor = 0
        for i, r in enumerate(rows):
            if r["id"] == self._focus:
                cursor = i
        self._enter(ACCOUNTS, rows=rows, cursor=cursor)

    def _open_account(self, row):
        if self._stash and self._stash[0] != row["id"]:
            self._stash = None
        self._focus = row["id"]
        label = ("%s %s" % (row["issuer"], row["account"])).strip()
        if row["reveal_requires_hold"] or self._push():
            self._start_flow(REVEAL, "OATH_REVEAL", ("Reveal code: " + label)[:90], row=row)
            return
        self._show_code(row, False)

    def _show_code(self, row, revealed):
        gate = bool(revealed and (row["reveal_requires_hold"] or self._push()))  # only while PTT is held
        try:
            if gate and row["type"] == "HOTP" and self._stash and self._stash[0] == row["id"]:
                digits, rem = self._stash[1], None  # same code again: do not burn a counter
            else:
                c = self._oath.code(row["id"], approved=revealed)
                digits, rem = c.digits, c.remaining_s
                if gate and row["type"] == "HOTP":
                    self._stash = (row["id"], digits)
        except lb_oath.ClockUntrusted:
            self._notice("Set the clock first", ACCOUNTS)
            self._pulse("error")
            return
        except lb_oath.OathError as e:
            self._notice("Code unavailable: " + str(e), ACCOUNTS)
            self._pulse("error")
            return
        hide_at = None
        if gate and not self._ptt:  # approved by combo: there is no PTT release to wait for
            hide_at = lb_ticks.add(self._ticks(), REVEAL_AUTOHIDE_MS)
        self._enter(TOTP_CODE, row=row, revealed=revealed, gate=gate, hide_at=hide_at, code=digits,
                    remaining=rem, unix=self._rtc.now() if rem else None)

    def _hide_code(self):
        """Back to the reveal prompt for the same account; the code is dropped from the screen
        state. Showing it again needs a fresh hold (the approval)."""
        row = self._d["row"]
        label = ("%s %s" % (row["issuer"], row["account"])).strip()
        self._start_flow(REVEAL, "OATH_REVEAL", ("Reveal code: " + label)[:90], row=row)
        if self._scr == REVEAL:
            self._say("Code hidden: hold to show")

    def _submit_combo(self):
        combo = list(self._combo)
        self._combo = []
        try:
            if self._scr == LOCKED:
                res = self._s.unlock(combo)
            else:
                res = self._s.approve_with_combo(self._flow, combo)
        except lb_session.SessionError as e:
            self._say("Storage error: " + str(e))
            return
        if res.outcome == lb_session.OK:
            if self._scr == COMBO_APPROVE:
                self._approved()
            return
        self._pulse("error")
        if res.outcome == lb_session.BAD:
            t = "Wrong combo. %d left" % res.attempts_left
            if res.delay_ms:
                t += ". Wait %d s" % ((res.delay_ms + 999) // 1000)
            self._say(t)
        elif res.outcome == lb_session.DELAYED:
            self._say("Wait %d s" % ((res.delay_ms + 999) // 1000))
        elif res.outcome == lb_session.INVALID:
            pol = self._s.policy()
            self._say("Use %d to %d presses" % (pol.combo_min, pol.combo_max))
        # WIPED is handled by _sync

    # ------------------------------------------------------------ approval

    def _hold_target(self):
        scr = self._scr
        if scr == CONFIRM_OTP:
            return "%s|Add|%s|%s" % (self._flow, self._d["entry"].issuer,
                                     self._d["entry"].account), "login"
        if scr == REVEAL:
            r = self._d["row"]
            return "%s|Reveal|%s|%s" % (self._flow, r["issuer"], r["account"]), "login"
        if scr == SET_TIME:
            return "%s|SetTime|%d-%d-%d %d:%d:%d" % ((self._flow,) + tuple(self._d["v"])), "sign"
        if scr == CONFIRM_SETTING:
            return "%s|Setting|%s" % (self._flow, self._d["setting"]), "login"
        if scr == HOST_REQUEST:
            p = self._s.pending()
            if p is not None and p["id"] == self._flow:
                return "%s|%s|%s" % (p["id"], p["kind"], p["summary"]), \
                    _HOLD_KIND.get(p["kind"], "sign")
        return None, None

    def _on_commit(self):
        self._pulse("commit")
        res = self._s.hold_complete(self._flow)
        if res == lb_session.APPROVED:
            self._approved()
        elif res == lb_session.DENIED:
            self._proposal = None
            self._pulse("error")
            self._notice("Fingerprint did not match")
        elif res == lb_session.NEED_COMBO:
            d = self._d
            self._enter(COMBO_APPROVE, back=self._scr, entry=d.get("entry"), row=d.get("row"),
                        v=d.get("v"), f=d.get("f", 0), setting=d.get("setting"))
        else:
            self._notice("Request no longer valid")

    def _approved(self):
        scr = self._scr
        d = self._d
        if scr == COMBO_APPROVE:
            self._pulse("success")  # no hold happened, so no commit flash: say it worked
        if (scr == HOST_REQUEST or (scr == COMBO_APPROVE and d.get("back") == HOST_REQUEST)) \
                and self._proposal is not None and self._proposal["id"] == self._flow:
            self._apply_host_proposal()
            return
        if scr == SET_TIME or (scr == COMBO_APPROVE and d.get("back") == SET_TIME):
            if self._set_time is None:
                self._notice("No clock to set", SETTINGS)
                return
            v = d["v"]
            try:
                unix = lb_dt.to_unix(*v) - self._offset_s()  # typed in local time, stored as UTC
            except ValueError:
                self._notice("Not a valid date", SETTINGS)
                return
            self._set_time(unix)
            self._notice("Clock set: %02d:%02d (%s)" % (v[3], v[4], self._zone_text(
                self._settings.get("utc_offset_min"))), SETTINGS)
            return
        if scr == CONFIRM_SETTING or (scr == COMBO_APPROVE and d.get("back") == CONFIRM_SETTING):
            name, value = d["setting"]
            self._apply_setting(name, value, pulse=False)  # the hold's commit flash already said it
            return
        if scr == CONFIRM_OTP or (scr == COMBO_APPROVE and d.get("back") == CONFIRM_OTP):
            entry = d["entry"]
            try:
                self._focus = self._oath.add(entry, approved=True)
            except lb_oath.OathError as e:
                self._notice("Not added: " + str(e))
                return
            self._notice("Added " + entry.account, ACCOUNTS)
        elif scr == REVEAL or (scr == COMBO_APPROVE and d.get("back") == REVEAL):
            self._show_code(d["row"], True)
        else:
            self._notice("Approved")

    # ------------------------------------------------------------ settings

    def _push(self):
        return self._settings.get("push_to_show")

    def _offset_s(self):
        return self._settings.get("utc_offset_min") * 60

    @staticmethod
    def _zone_text(minutes):
        a = abs(minutes)
        return "UTC%s%02d:%02d" % ("+" if minutes >= 0 else "-", a // 60, a % 60)

    def _settings_rows(self):
        if self._rtc.trusted():
            t = self._rtc.now() + self._offset_s()
            clock = "%02d:%02d" % ((t // 3600) % 24, (t // 60) % 60)
        else:
            clock = "not set"
        return [("Set time", clock),
                ("Time zone", self._zone_text(self._settings.get("utc_offset_min"))),
                ("Reorder accounts", ""),
                ("Push to show", "ON" if self._push() else "OFF")]

    def _open_settings(self, cursor=None):
        """Settings always reopens on the row you were last on (Back from a confirm screen, a
        notice or a sub-page), so a second Select cannot open the wrong page."""
        if cursor is not None:
            self._set_cursor = cursor
        self._enter(SETTINGS, cursor=self._set_cursor)

    def _press_settings(self, name):
        d = self._d
        if name == "UP":
            d["cursor"] = max(0, d["cursor"] - 1)
        elif name == "DOWN":
            d["cursor"] = min(3, d["cursor"] + 1)
        self._set_cursor = d["cursor"]
        if name == "SELECT":
            c = d["cursor"]
            if c == 0:
                self._open_set_time()
            elif c == 1:
                self._open_zone()
            elif c == 2:
                self._open_reorder()
            else:
                self._toggle_push()

    def _toggle_push(self):
        if not self._push():
            self._apply_setting("push_to_show", True)  # turning protection on needs no approval
            return
        # turning it off weakens protection: ask for a hold, like any consequential action
        self._start_flow(CONFIRM_SETTING, "SETTING", "Turn off push to show",
                         setting=("push_to_show", False), cursor=3)

    def _apply_setting(self, name, value, pulse=True):
        try:
            self._settings.set(name, value, approved=True)
        except lb_settings.SettingsError as e:
            self._notice("Not changed: " + str(e), SETTINGS)
            self._pulse("error")
            return
        if name == "push_to_show":
            self._oath.set_reveal_all(value)
        if pulse:
            self._pulse("success")
        self._open_settings(3)
        self._say("Push to show: %s" % ("ON" if value else "OFF"))

    # ---- Set time from the host (the computer proposes, a PTT hold on the device decides)

    def host_set_time(self, unix_ms, offset_min=None):
        """The computer proposes the time (UTC, unix milliseconds) and optionally the zone (minutes
        east of UTC). Nothing changes until the user holds PTT on the approval screen, one hold for
        both; the clock is then set to the proposal plus the time that passed while waiting.
        Returns the request id, or None if refused."""
        if self._s.wiped() or self._set_time is None:
            return None
        if offset_min is not None:
            try:
                lb_settings.Settings().set("utc_offset_min", offset_min, approved=True)  # validates only
            except lb_settings.SettingsError:
                return None
        if not lb_dt.to_unix(YEAR_MIN, 1, 1) * 1000 <= unix_ms < lb_dt.to_unix(YEAR_MAX + 1, 1, 1) * 1000:
            return None
        f = lb_dt.to_fields(unix_ms // 1000)
        try:
            text = "%04d-%02d-%02d %02d:%02d:%02d UTC" % tuple(f)
            if offset_min is not None:
                text += ", zone " + self._zone_text(offset_min)
            rid = self._s.request("SET_TIME", "USB", text)
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "time", "ms": unix_ms, "t0": self._ticks(), "offset": offset_min}
        self._sync()
        return rid

    def host_set_setting(self, name, value):
        """The computer proposes a settings change. Like the time, it needs a PTT hold on the
        device, always: even a change that strengthens protection comes from the untrusted side.
        Returns the request id, or None if refused (wiped, unknown, invalid, or no change)."""
        if self._s.wiped():
            return None
        try:
            probe = lb_settings.Settings()
            probe.set(name, value, approved=True)  # validates name, type and range without touching ours
            if self._settings.get(name) == value:
                return None
        except lb_settings.SettingsError:
            return None
        shown = ("on" if value else "off") if isinstance(value, bool) else (
            self._zone_text(value) if name == "utc_offset_min" else str(value))
        try:
            rid = self._s.request("SETTING", "USB", ("Set %s: %s" % (name, shown)))
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "setting", "name": name, "value": value}
        self._sync()
        return rid

    def host_factory_reset(self):
        """The computer proposes erasing the device. The screen says so plainly and only a PTT
        hold does it. Returns the request id, or None if refused."""
        if self._s.wiped() or self._factory_reset is None:
            return None
        try:
            rid = self._s.request("RESET", "USB", "ERASE ALL accounts and settings")
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "reset"}
        self._sync()
        return rid

    def host_console_rw(self):
        """The computer asks to make the console read-write (it can then press buttons and skip
        holds). Only a fingerprint approves this: no combo fallback, and a failed match is final.
        Returns the request id, or None if refused."""
        if self._s.wiped() or self._console_rw is None or self._s.state() != lb_session.UNLOCKED:
            return None
        try:
            rid = self._s.request("CONSOLE_RW", "USB", "Console READ-WRITE (fingerprint)")
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "console_rw"}
        self._sync()
        return rid

    def host_stop(self):
        """Developer only: the computer proposes ending the rig program on the board. A PTT hold does
        it; the board is then left at its Python prompt (`libra dev start` runs the rig again).
        Returns the request id, or None if refused."""
        if self._s.wiped() or self._stop is None:
            return None
        try:
            rid = self._s.request("STOP", "USB", "Stop the rig program (dev)")
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "stop"}
        self._sync()
        return rid

    def host_restart(self):
        """The computer proposes a restart (data kept, comes back locked, test mode ends). Like
        everything the computer asks for, only a PTT hold does it. Returns the request id or None."""
        if self._s.wiped() or self._restart is None:
            return None
        try:
            rid = self._s.request("RESTART", "USB", "Restart the device")
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "restart"}
        self._sync()
        return rid

    def host_keep_unlocked(self, on):
        """The computer proposes test mode: no idle lock while it is in use. Needs the device to
        be unlocked already, and a PTT hold. Returns the request id, or None if refused."""
        if self._s.wiped() or self._s.state() != lb_session.UNLOCKED \
                or self._s.keep_unlocked() == bool(on):
            return None
        try:
            rid = self._s.request("MODE", "USB", "Stay unlocked: " + ("ON" if on else "off"))
        except lb_session.SessionError:
            return None
        self._proposal = {"id": rid, "kind": "mode", "on": bool(on)}
        self._sync()
        return rid

    def _apply_host_proposal(self):
        p = self._proposal
        self._proposal = None
        if p["kind"] == "reset":
            self._pulse("success")
            self._factory_reset()  # replaces this UI with a fresh one: nothing more to do here
            return
        if p["kind"] == "console_rw":
            self._console_rw(True)
            self._notice("Console is read-write")
            return
        if p["kind"] == "stop":
            self._pulse("success")
            self._stop()  # the loop ends after this frame
            return
        if p["kind"] == "restart":
            self._pulse("success")
            self._restart()  # replaces this UI and session: nothing more to do here
            return
        if p["kind"] == "mode":
            try:
                self._s.set_keep_unlocked(p["on"])
            except lb_session.SessionError:
                self._notice("Not changed: unlock first")
                return
            self._notice("Stay unlocked " + ("ON" if p["on"] else "off"))
            return
        if p["kind"] == "time":
            waited = lb_ticks.diff(self._ticks(), p["t0"])
            unix = (p["ms"] + max(0, waited)) // 1000
            self._set_time(unix)
            f = lb_dt.to_fields(unix)
            text = "Clock set: %02d:%02d:%02d UTC" % (f[3], f[4], f[5])
            if p.get("offset") is not None:
                try:
                    self._settings.set("utc_offset_min", p["offset"], approved=True)
                    text += ", zone " + self._zone_text(p["offset"])
                except lb_settings.SettingsError:
                    self._pulse("error")
                    text += " (zone not saved)"
            self._notice(text)
            return
        try:
            self._settings.set(p["name"], p["value"], approved=True)
        except lb_settings.SettingsError as e:
            self._notice("Not changed: " + str(e))
            self._pulse("error")
            return
        if p["name"] == "push_to_show":
            self._oath.set_reveal_all(p["value"])
        self._notice("Setting changed")

    # ---- Set time (typed in local time; the clock itself is UTC)

    def _open_set_time(self, v=None, f=0):
        if v is None:
            u = self._rtc.now() + self._offset_s() if self._rtc.trusted() else TIME_START
            v = lb_dt.to_fields(u)
            if v[0] < YEAR_MIN:
                v = lb_dt.to_fields(TIME_START)
        self._start_flow(SET_TIME, "SET_TIME", "Set the clock", v=list(v), f=f)
        if self._scr == SET_TIME:
            self._say("Hold PTT to set the clock")

    def _time_edit(self, name):
        d = self._d
        v = d["v"]
        f = d["f"]
        self._toast = None  # the hint has done its job once you start editing
        if name == "LEFT":
            d["f"] = max(0, f - 1)
        elif name == "RIGHT":
            d["f"] = min(5, f + 1)
        elif name == "SELECT":
            d["f"] = (f + 1) % 6  # next field, wrapping
        elif name in ("UP", "DOWN"):
            lo, hi = _TIME_RANGE[f]
            if f == 2:
                hi = lb_dt.days_in_month(v[0], v[1])
            step = 1 if name == "UP" else -1
            v[f] = lo + (v[f] - lo + step) % (hi - lo + 1)  # wraps; no carry into the next field
            v[2] = min(v[2], lb_dt.days_in_month(v[0], v[1]))  # month or year changed under the day

    # ---- Time zone

    def _open_zone(self):
        self._enter(TIME_ZONE, off=self._settings.get("utc_offset_min"))

    def _zone_edit(self, name):
        d = self._d
        if name == "SELECT":
            try:
                self._settings.set("utc_offset_min", d["off"])
            except lb_settings.SettingsError as e:
                self._say("Not saved: " + str(e))
                self._pulse("error")
                return
            self._pulse("success")
            self._open_settings(1)
            self._say("Zone: " + self._zone_text(d["off"]))  # short enough for the 16-character LCD
            return
        step = {"UP": 15, "DOWN": -15, "RIGHT": 60, "LEFT": -60}.get(name, 0)
        d["off"] = max(lb_settings.OFFSET_MIN, min(lb_settings.OFFSET_MAX, d["off"] + step))

    # ---- Reorder accounts

    def _open_reorder(self):
        rows = self._oath.list()
        if len(rows) < 2:
            self._notice("Nothing to reorder", SETTINGS)
            return
        cursor = 0
        for i, r in enumerate(rows):
            if r["id"] == self._focus:
                cursor = i
        self._enter(REORDER, rows=rows, cursor=cursor, grabbed=False, orig=None)

    def _press_reorder(self, name):
        d = self._d
        rows = d["rows"]
        c = d["cursor"]
        if name in ("UP", "DOWN"):
            n = c - 1 if name == "UP" else c + 1
            if not 0 <= n < len(rows):
                return
            if d["grabbed"]:
                rows[c], rows[n] = rows[n], rows[c]  # the grabbed account travels with the cursor
            d["cursor"] = n
        elif name == "SELECT":
            if not d["grabbed"]:
                d["grabbed"] = True
                d["orig"] = list(rows)
            else:
                moved = rows[c]
                d["grabbed"] = False
                if [r["id"] for r in rows] != [r["id"] for r in d["orig"]]:
                    try:
                        self._oath.move(moved["id"], c)
                    except lb_oath.OathError as e:
                        d["rows"] = list(d["orig"])
                        self._say("Order not saved")
                        self._pulse("error")
                        return
                    self._focus = moved["id"]
                    self._pulse("success")
                    self._say("Moved to position %d" % (c + 1))

    def _back_reorder(self):
        d = self._d
        if d["grabbed"]:  # put it back where it was, cursor and all
            moved_id = d["rows"][d["cursor"]]["id"]
            d["rows"] = list(d["orig"])
            d["cursor"] = [r["id"] for r in d["rows"]].index(moved_id)
            d["grabbed"] = False
            self._say("Move cancelled")
        else:
            self._open_settings(2)

    # ------------------------------------------------------------ tick and sync

    def _sync(self):
        s = self._s
        if s.wiped():
            if self._scr != WIPED:
                self._enter(WIPED)
            return
        if s.state() == lb_session.LOCKED:
            self._stash = None
            if self._scr != LOCKED:
                self._hold.reset()
                self._enter(LOCKED)
            return
        if self._scr == LOCKED:
            self._enter(IDLE)
        p = s.pending()
        if self._scr == SET_TIME and p is None:  # the request lapsed while you were dialling: renew it
            self._flow = s.request("SET_TIME", "UI", "Set the clock")
            p = s.pending()
        if self._scr in _REQUEST_SCREENS and (p is None or p["id"] != self._flow):
            if self._scr == COMBO_APPROVE or p is None or p["origin"] != "USB":
                self._notice("Request replaced" if p else "Request expired")
        p = s.pending()
        if p is not None and p["origin"] == "USB" and (self._scr != HOST_REQUEST
                                                       or self._flow != p["id"]):
            replaced = self._scr in _REQUEST_SCREENS
            self._enter(HOST_REQUEST)
            self._flow = p["id"]
            self._pulse("notify")
            if replaced:
                self._say("Request changed")

    def tick(self):
        now = self._ticks()
        if lb_ticks.diff(now, self._last_sec) >= 1000:
            self._last_sec = now
            self._s.tick()
            self._refresh_code()
        self._sync()
        text, kind = self._hold_target()
        st = self._hold.update(now, self._ptt, text, kind)
        self._permille = st.permille if text is not None else None
        if text is not None and st.reason:
            self._pulse("abort")
            if st.reason == "RELEASED":
                self._say("Keep holding to approve")
            elif st.reason == "REQUEST_CHANGED":
                self._say("Request changed: release, then hold again")
            else:
                self._say("Hold interrupted: try again")
        if st.committed and text is not None:
            self._on_commit()
            self._sync()
        if self._toast is not None and lb_ticks.diff(now, self._toast_until) >= 0:
            self._toast = None
        if self._rep_name and self._scr in (SET_TIME, TIME_ZONE) \
                and lb_ticks.diff(now, self._rep_next) >= 0:
            self._rep_next = lb_ticks.add(now, REPEAT_STEP_MS)
            if self._scr == SET_TIME:
                self._time_edit(self._rep_name)
            else:
                self._zone_edit(self._rep_name)
        if self._scr == TOTP_CODE and self._d.get("hide_at") is not None \
                and lb_ticks.diff(now, self._d["hide_at"]) >= 0:
            self._hide_code()
        if self._scr == NOTICE and lb_ticks.diff(now, self._d["until"]) >= 0:
            self._goto(self._d["ret"])
            self._sync()
        elif self._scr == SHOW_QR and lb_ticks.diff(now, self._d["until"]) >= 0:
            self._enter(IDLE)

    def _refresh_code(self):
        d = self._d
        if self._scr != TOTP_CODE or d.get("unix") is None:
            return
        unix = self._rtc.now()
        if unix == d["unix"]:
            return
        try:
            c = self._oath.code(d["row"]["id"], approved=d["revealed"])
        except lb_oath.OathError:
            self._notice("Code unavailable", ACCOUNTS)
            return
        d["code"] = c.digits
        d["remaining"] = c.remaining_s
        d["unix"] = unix

    # ------------------------------------------------------------ output

    def screen(self):
        scr = self._scr
        d = self._d
        hints = {"select": "", "ptt": "", "back": ""}
        body = {}
        title = scr
        lines = []
        if scr == LOCKED:
            title = "Locked"
            body["dots"] = len(self._combo)
            lines = ["Enter your combo"]
            p = self._s.pending()
            if p is not None:
                lines = ["Unlock to continue", p["summary"]]
            hints = {"select": "Unlock", "ptt": "", "back": "Clear"}
        elif scr == IDLE:
            title = self._name
            body["name"] = self._name
            hints = {"select": "Settings", "ptt": "Tap: my QR", "back": "Hold: lock"}
        elif scr == SETTINGS:
            title = "Settings"
            body["rows"] = [{"text": a, "value": b} for a, b in self._settings_rows()]
            body["cursor"] = d["cursor"]
            hints = {"select": "Toggle" if d["cursor"] == 3 else "Open", "ptt": "", "back": "Home"}
        elif scr == SET_TIME:
            v = d["v"]
            title = "Set time " + self._zone_text(self._settings.get("utc_offset_min"))
            body["fields"] = [{"label": _TIME_LABELS[i], "text": ("%04d" if i == 0 else "%02d") % v[i]}
                              for i in range(6)]
            body["index"] = d["f"]
            body["text"] = "%04d-%02d-%02d %02d:%02d:%02d" % tuple(v)
            hints = {"select": "Next field", "ptt": "Hold: set clock", "back": "Cancel"}
        elif scr == TIME_ZONE:
            title = "Time zone"
            t = self._rtc.now() + d["off"] * 60
            body["offset"] = d["off"]
            body["text"] = self._zone_text(d["off"])
            body["local"] = "%02d:%02d" % ((t // 3600) % 24, (t // 60) % 60)
            lines = ["No daylight saving:", "change it by hand"]
            hints = {"select": "Save", "ptt": "", "back": "Cancel"}
        elif scr == CONFIRM_SETTING:
            title = "Turn off?"
            lines = ["Push to show", "Codes will stay on", "screen once opened"]
            hints = {"select": "", "ptt": "Hold: turn off", "back": "Cancel"}
        elif scr == REORDER:
            title = "Reorder"
            rows = d["rows"]
            c = d["cursor"]
            top = max(0, min(c - ROWS + 1, len(rows) - ROWS)) if len(rows) > ROWS else 0
            top = max(top, c - ROWS + 1)
            body["rows"] = [{"text": ("%s %s" % (r["issuer"], r["account"])).strip(),
                             "tag": r["type"], "hold": r["reveal_requires_hold"]}
                            for r in rows[top:top + ROWS]]
            body["cursor"] = c - top
            body["index"] = c
            body["total"] = len(rows)
            body["grabbed"] = d["grabbed"]
            hints = ({"select": "Drop", "ptt": "", "back": "Cancel"} if d["grabbed"]
                     else {"select": "Grab", "ptt": "", "back": "Done"})
        elif scr == SHOW_QR:
            title = "My QR"
            lines = ["(placeholder)", "Fingerprint", "3F2A 91BC 77D0", "14E8 52A6 0B39"]
            hints = {"select": "", "ptt": "", "back": "Back"}
        elif scr == ACCOUNTS:
            title = "Accounts"
            rows = d["rows"]
            top = max(0, min(d["cursor"] - ROWS + 1, len(rows) - ROWS)) if len(rows) > ROWS else 0
            top = max(top, d["cursor"] - ROWS + 1)
            body["rows"] = [{"text": ("%s %s" % (r["issuer"], r["account"])).strip(),
                             "tag": r["type"], "hold": r["reveal_requires_hold"]}
                            for r in rows[top:top + ROWS]]
            body["cursor"] = d["cursor"] - top
            body["index"] = d["cursor"]
            body["total"] = len(rows)
            if not rows:
                lines = ["No accounts yet", "Scan an OTP QR to add one"]
            hints = {"select": "Show code", "ptt": "", "back": "Home"}
        elif scr == TOTP_CODE:
            r = d["row"]
            title = r["issuer"] or "Code"
            body.update({"issuer": r["issuer"], "account": r["account"], "type": r["type"],
                         "code": _group(d["code"]), "remaining": d["remaining"]})
            if d["remaining"] is not None:
                body["ring"] = max(0, min(1000, d["remaining"] * 1000 // r["period"]))
            hints = {"select": "", "ptt": "Release: hide" if d.get("gate") else "", "back": "Back"}
        elif scr == CONFIRM_OTP:
            e = d["entry"]
            title = "Add account?"
            lines = [e.issuer or "(no issuer)", e.account,
                     "%s %s %d digits" % (e.type, e.alg, e.digits),
                     ("every %d s" % e.period) if e.type == "TOTP" else ("counter %d" % e.counter)]
            hints = {"select": "", "ptt": "Hold: add", "back": "Cancel"}
        elif scr == REVEAL:
            r = d["row"]
            title = "Reveal code?"
            lines = [r["issuer"] or "(no issuer)", r["account"]]
            hints = {"select": "", "ptt": "Hold: reveal", "back": "Cancel"}
        elif scr == HOST_REQUEST:
            p = self._s.pending()
            title = "Approve?"
            if p is not None:
                lines = ["From: " + ("computer" if p["origin"] == "USB" else "device"),
                         p["kind"], p["summary"]]
            hints = {"select": "", "ptt": "Hold: approve", "back": "Deny"}
        elif scr == COMBO_APPROVE:
            title = "Use your combo"
            body["dots"] = len(self._combo)
            lines = ["Fingerprint did not match", "Enter your combo to approve"]
            hints = {"select": "Approve", "ptt": "", "back": "Cancel"}
        elif scr == SHOW_TEXT:
            title = "Unknown QR"
            lines = ["Not an OTP code. Raw text:", d["text"]]
            hints = {"select": "", "ptt": "", "back": "Back"}
        elif scr == NOTICE:
            title = "Notice"
            lines = [d["text"]]
            hints = {"select": "OK", "ptt": "", "back": "Back"}
        elif scr == WIPED:
            title = "Wiped"
            lines = ["Too many wrong combos.", "Keys erased.", "Restore from backup."]
        t = self._rtc.now() + self._offset_s() if self._rtc.trusted() else None
        return {
            "id": scr, "title": title, "lines": lines, "body": body, "hints": hints,
            "hold": self._permille if scr in _REQUEST_SCREENS else None,
            "toast": self._toast,
            "status": {"locked": self._s.state() == lb_session.LOCKED, "level": self._level,
                       "usb": bool(self._usb()) if self._usb is not None else False,
                       "ble": bool(self._ble()) if self._ble is not None else False,
                       "time": ("%02d:%02d" % ((t // 3600) % 24, (t // 60) % 60))
                       if t is not None else "--:--"},
            "haptic": {"seq": self._beep, "kind": self._beep_kind},
        }
