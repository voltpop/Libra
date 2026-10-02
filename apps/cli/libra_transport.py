"""libra_transport.py - how the CLI talks to a Libra. Only this file knows about the wire.

Today the wire is the prototype rig's text console over USB serial. The commands in libra.py use
only the methods of Console (ask, mode, status, settings, propose, cancel), so a real USB protocol
can replace this class later without touching a single command.

The computer only PROPOSES. propose() sends the proposal, waits for the person at the device to
hold PTT (or refuse it with Back), and reports exactly how it ended.
"""
import time

BAUD = 115200
PICO_VID = 0x2E8A  # Raspberry Pi

APPROVED, REFUSED, EXPIRED, DENIED = "approved", "refused", "expired", "denied"
REJECTED, TIMEOUT, WITHDRAWN, NO_RIG = "rejected", "timeout", "withdrawn", "no_rig"
LOCKED = "locked"  # the device was still locked when a computer's request lapsed (about 30 s)
_DECISIONS = {"APPROVED": APPROVED, "CANCELLED": REFUSED, "EXPIRED": EXPIRED, "DENIED": DENIED,
              "LOCKED_TIMEOUT": LOCKED}


class Outcome:
    def __init__(self, kind, detail=""):
        self.kind = kind
        self.detail = detail

    def __repr__(self):
        return "Outcome(%s, %r)" % (self.kind, self.detail)


def settime_command(now=None, offset_min=None):
    """The proposal line for the current time, seconds with milliseconds, taken as late as possible,
    plus the zone (minutes east of UTC) if one is to be set in the same approval."""
    t = time.time() if now is None else now
    line = "settime %d.%03d" % (int(t), int((t % 1) * 1000))
    return line if offset_min is None else line + " %d" % offset_min


def find_port():
    from serial.tools import list_ports
    found = [p.device for p in list_ports.comports() if p.vid == PICO_VID]
    if len(found) != 1:
        raise SystemExit("found %d Pico serial ports (%s): pass --port" % (len(found), ", ".join(found) or "none"))
    return found[0]


def link_lost_message(e):
    return ("lost the connection to the board (%s). It may have been unplugged or reset, or another "
            "program opened the port. Nothing was changed unless the Libra already showed it done. "
            "Run the command again." % (e,))


QUIET_S = 0.15  # once lines have arrived, stop after this long with nothing more


def read_lines(ser, seconds):
    """Lines the device sends in the next `seconds`, returning early once it has gone quiet."""
    end = time.monotonic() + seconds
    buf = b""
    got = False
    last = time.monotonic()
    while time.monotonic() < end:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            last = time.monotonic()
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            got = True
            yield line.decode("utf-8", "replace").strip()
        if got and not buf and not chunk and time.monotonic() - last >= QUIET_S:
            return


def parse_kv(line):
    """'a=1 b=two' -> {'a': '1', 'b': 'two'}"""
    return dict(kv.split("=", 1) for kv in line.split() if "=" in kv)


class Console:
    def __init__(self, ser, log=None):
        self._ser = ser
        self._log = log  # callable(str) for --verbose: the raw exchange

    # ---- plumbing

    def ask(self, line, seconds=1.0):
        """Send one console line and return the lines it answers with."""
        self._ser.reset_input_buffer()
        if self._log:
            self._log(">> " + line)
        self._ser.write((line + "\n").encode())
        lines = list(read_lines(self._ser, seconds))
        if self._log:
            for x in lines:
                self._log("<< " + x)
        return lines

    def rig_running(self):
        """True if the board answers as the rig right now."""
        return "trust=" in " ".join(self.ask("mode", 1.5))

    def wait_until_stopped(self, seconds=6):
        """True once the rig has stopped answering (after an approved `dev stop`)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not self.rig_running():
                return True
        return False

    def ensure_rig(self, out=print, start_wait_s=15):
        """True once the board answers as the rig. A board sitting at a Python prompt gets the rig
        started; one that is silent or running something else is never interrupted."""
        text = " ".join(self.ask("mode", 1.5))
        if "trust=" in text:
            return True
        if "Error" not in text:
            out("the board did not answer. Is something else running on it (Thonny? a test)? Not interrupting it.")
            return False
        out("the board is at a Python prompt: starting the rig...")
        self._ser.write(b"import pico_main; pico_main.run()\r\n")
        end = time.monotonic() + start_wait_s
        while time.monotonic() < end:
            if "trust=" in " ".join(self.ask("mode", 1.5)):
                out("rig started.")
                return True
        out("could not start the rig. Is pico_main.py on the board?")
        return False

    # ---- what the device says

    def mode(self):
        """{'trust': 'masked', 'unlock': 'pin', 'build': 'dev', 'console': 'ro', ...}"""
        for line in self.ask("mode"):
            if "trust=" in line:
                return parse_kv(line)
        return {}

    def status(self):
        lines = self.ask("status", 1.2)
        text = " | ".join(lines)
        d = {"raw": lines, "pending": None, "clock_trusted": "clock trusted" in text}
        for line in lines:
            if line.startswith("screen "):
                for part in line.split(" | "):
                    k, _, v = part.partition(" ")
                    d[k] = v
            elif line.startswith("pending "):
                first = line.split(" | ")[0]
                d["pending"] = None if first == "pending none" else first[len("pending "):]
                d["clock"] = line.split(" | ")[-1].replace("clock ", "")
        return d

    def settings(self):
        for line in self.ask("settings"):
            if line.startswith("push_to_show="):
                return parse_kv(line)
        return {}

    # ---- proposals

    def _result(self, ends_rig=False):
        lines = self.ask("result")
        if ends_rig and (not lines or any("Error" in x for x in lines)):
            return Outcome(APPROVED, "the rig stopped before it could answer")
        for line in lines:
            parts = line.split()
            if len(parts) == 3 and parts[0] == "result":
                if parts[2] in _DECISIONS:
                    return Outcome(_DECISIONS[parts[2]], parts[2])
                return Outcome(REJECTED, "the device ended it as %s" % parts[2])  # never hide what it said
        return Outcome(REJECTED, "the device did not say how it ended")

    def cancel(self):
        return "withdrawn" in " ".join(self.ask("cancel"))

    def propose(self, line, wait_s=45, tick=None, ends_rig=False):
        """Send a proposal and wait. Returns an Outcome: approved, refused (Back), expired, denied
        (fingerprint), rejected (the device would not take it), timeout or withdrawn (Ctrl-C);
        the last two withdraw it on the device so it does not linger. With ends_rig (a proposal that
        ends the rig program, `dev stop`) the rig going quiet right after the request clears IS the
        approval: it exits before it can answer "result"."""
        reply = " ".join(self.ask(line, 1.5))
        if "proposed" not in reply and "requested" not in reply:
            if "refused" in reply:
                return Outcome(REJECTED, reply.split("refused", 1)[1].strip(" ()"))
            if "off on the device" in reply:
                return Outcome(REJECTED, "this device build does not take that command")
            if "Error" in reply:
                return Outcome(NO_RIG, "the board is at a Python prompt, not running the rig")
            return Outcome(REJECTED, "unexpected reply: %r" % (reply,))
        end = time.monotonic() + wait_s
        try:
            while time.monotonic() < end:
                if tick:
                    tick(int(end - time.monotonic()))
                text = " ".join(self.ask("status", 1.0))
                if ends_rig and "Error" in text:  # the rig is gone: it stopped between two polls
                    return Outcome(APPROVED, "the rig stopped")
                if "pending none" in text:
                    return self._result(ends_rig)
        except KeyboardInterrupt:
            self.cancel()
            return Outcome(WITHDRAWN, "stopped from the keyboard; withdrawn on the device")
        self.cancel()
        return Outcome(TIMEOUT, "no approval within %d s; withdrawn on the device" % wait_s)
