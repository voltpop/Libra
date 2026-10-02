"""libra_policy.py - what each command may do, in terms of trust level, unlock strength and scope.

Three separate ideas, never mixed:
  * TRUST LEVEL describes the computer (the connection): masked < session < paired.
      masked   the default for any computer
      session  device unlocked with fingerprint and PIN, and the computer connected (ends on lock/unplug)
      paired   permanent: the device was asked to remember this computer and recognises its key
  * UNLOCK STRENGTH describes how the device was unlocked: none < pin < pin+fp.
  * SCOPE describes what a command touches: device, accounts, hosts, data, dev.
A rule maps a command to its scope and the minimum trust level and unlock strength it needs. The
DEVICE enforces policy; this table lets the CLI say so early and explain. Every allowed action
still needs a PTT hold on the device.
"""

TRUST = ("masked", "session", "paired")
UNLOCK = ("none", "pin", "pin+fp")

SCOPES = {
    "device": "the Libra itself: info, settings, restart, reset (harmless from any computer)",
    "accounts": "OTP and key accounts: names, add, remove, reorder",
    "hosts": "pairing: remember, list and revoke computers",
    "data": "backup and restore",
    "dev": "bench tools for dev builds only",
}

READY, PLANNED = "ready", "planned"

# command path -> (scope, minimum trust, minimum unlock, status)
RULES = {
    ("device", "status"): ("device", "masked", "none", READY),
    ("device", "time", "set"): ("device", "masked", "none", READY),
    ("device", "setting", "list"): ("device", "masked", "none", READY),
    ("device", "setting", "set"): ("device", "masked", "none", READY),
    ("device", "restart"): ("device", "masked", "none", READY),
    ("device", "factory-reset"): ("device", "masked", "none", READY),
    ("accounts", "list"): ("accounts", "session", "pin+fp", PLANNED),
    ("accounts", "add"): ("accounts", "session", "pin+fp", PLANNED),
    ("accounts", "remove"): ("accounts", "session", "pin+fp", PLANNED),
    ("accounts", "reorder"): ("accounts", "session", "pin+fp", PLANNED),
    ("hosts", "pair"): ("hosts", "session", "pin+fp", PLANNED),
    ("hosts", "list"): ("hosts", "session", "pin+fp", PLANNED),
    ("hosts", "revoke"): ("hosts", "session", "pin+fp", PLANNED),
    ("data", "backup"): ("data", "session", "pin+fp", PLANNED),
    ("data", "restore"): ("data", "session", "pin+fp", PLANNED),
    ("dev", "stay-unlocked"): ("dev", "masked", "none", READY),
    ("dev", "console"): ("dev", "masked", "none", READY),
    ("dev", "update"): ("dev", "masked", "none", READY),
    ("dev", "stop"): ("dev", "masked", "none", READY),
    ("dev", "start"): ("dev", "masked", "none", READY),
}

# Commands that run on this computer and never need to ask the device first.
HOST_SIDE = (("dev", "update"),)


def rank(order, value):
    return order.index(value) if value in order else -1


def check(path, mode):
    """(allowed, reason). mode is what the device reports: trust, unlock and build."""
    rule = RULES.get(tuple(path))
    if rule is None:
        return False, "unknown command"
    scope, trust, unlock, status = rule
    name = " ".join(path)
    if status == PLANNED:
        return False, "'%s' is planned, not built yet" % name
    if scope == "dev" and mode.get("build") != "dev":
        return False, "'%s' is for dev builds only; this device is a %s build" % (name, mode.get("build", "?"))
    have_trust = rank(TRUST, mode.get("trust"))
    if have_trust < rank(TRUST, trust):
        return False, "'%s' needs a %s computer; the device sees this one as %s" % (
            name, trust, mode.get("trust", "unknown"))
    have_unlock = rank(UNLOCK, mode.get("unlock"))
    if have_unlock < rank(UNLOCK, unlock):
        return False, "'%s' needs the device unlocked with %s; it is %s" % (name, unlock, mode.get("unlock", "unknown"))
    return True, ""


def table():
    """Rows for display: (command, scope, trust, unlock, status)."""
    return [(" ".join(p),) + rule for p, rule in RULES.items()]
