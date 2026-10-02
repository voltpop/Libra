# apps/cli: the `libra` command

The v0 host tool: set the time and settings, restart or reset the device, and bench tools for
testing. Command-line only. Python 3 with `pyserial` (`pip install pyserial`) and `mpremote`
(for `dev update`).

    python3 libra.py <scope> <command> [options]

## The model: three separate ideas

- **Trust level** describes the *computer* (the connection): `masked` < `session` < `paired`.
  `masked` is the default for any computer. `session` means the device is unlocked with
  fingerprint and PIN and the computer is connected. `paired` is permanent: after a strong
  unlock the device offers to remember the computer, and recognises it by its key later.
- **Unlock strength** describes how the *device* was unlocked: `none` < `pin` < `pin+fp`.
- **Scope** describes what a *command touches*: `device`, `accounts`, `hosts`, `data`, `dev`.

A policy maps each command to a scope plus the minimum trust level and unlock strength it
needs. `libra policy` prints the table. The **device** scope (info, settings, restart, factory
reset) works from a masked computer; accounts, hosts and data need `session` trust and `pin+fp`
(planned: they are not built yet); `dev` needs a dev build. The device enforces all of this; the
CLI only reads the device's answer and explains it early. Today the prototype reports every
computer as `masked` because pairing does not exist yet.

**This tool is untrusted by design.** It only *proposes*. Every action waits for a PTT hold on
the device (Back refuses it, Ctrl-C withdraws it), including ones that make the device stricter.
It never asks for or relays the unlock combo.

## Commands

    libra device status                      trust level, unlock, screen, clock, settings
    libra device time set                    propose this computer's time (UTC) AND its zone, one approval
                                             (--zone +05:30 sends another zone, --no-zone only the clock)
    libra device setting list
    libra device setting set push-to-show on|off
    libra device setting set zone +05:30     # or minutes: 330
    libra device restart                     data kept, comes back locked   (type RESTART)
    libra device factory-reset               ERASES everything              (type RESET)
    libra dev stay-unlocked on|off           test mode: no idle lock (unlock the device first)
    libra dev console rw|ro                  rw: only a FINGERPRINT on the device approves it
    libra dev stop                           end the rig program on the board (needs the PTT hold)
    libra dev start                          run the rig on the board again; it comes up locked
    libra dev update [--with-tests]          copy this repository's firmware to the board
    libra policy                             what each command needs

Options (before or after the command; a negative zone can be written -08:00 or UTC-08:00): `--port`, `--json` (one JSON object on stdout, progress
on stderr), `--yes` (skip the typed Are-you-sure; never the hold), `--wait SECONDS` (default 45),
`--verbose` (the raw exchange on stderr), `--dry-run`.

A request from a computer lasts about **30 seconds** on the device. If the device is locked, unlock
it first or the request lapses (the CLI says so). The zone is a fixed UTC offset in 15-minute steps
with no daylight-saving rules, so `time set` sends today's offset: run it again when your clocks change.

Exit codes: **0** done, **1** not done (refused on the device, expired, denied, rejected, timed
out, withdrawn, or blocked by policy), **2** the link to the board failed, **3** bad usage.

## How it talks to the board

`libra_transport.py` is the only file that knows the wire. Today that is the prototype rig's text
console over USB serial; the CLI starts the rig itself if the board is sitting at a Python
prompt (no Thonny needed, but Thonny must not be holding the port). A real USB protocol replaces
that one class later and no command changes. The device's console is **read-only** by default:
it takes proposals and read-only commands, and refuses anything that would skip a hold.

## `libra dev stop` and `libra dev start`

Developer-only, and not expected to exist in the finished device. `stop` is a proposal like any
other: a PTT hold on the device ends the rig program, leaving the board at its Python prompt (the
LCD shows "Stopped"). `start` runs the rig again; it cannot ask for a hold because nothing is
running to show one, and the device always comes up locked. The prototype keeps its data in RAM,
so a stop and start **forgets** the settings and the clock (unlike `restart`, which keeps them).

## `libra dev update`

Copies the firmware files (`lb_*.py`, `ucompat.py` and everything in `firmware/mpy/pico/`) to the
board's root: only files that differ by SHA-256, then it reads the board back and verifies every
file. It syntax-checks first, asks you to type `UPDATE` (skip with `--yes`) and never deletes.
Prototype only: it goes through the board's Python prompt (mpremote), so it stops the running rig
and cannot ask for a PTT hold. The real firmware update will be signed and approved on the device.

## Files and tests

| File | What it is |
|---|---|
| `libra.py` | the command line: parser, commands, output, exit codes |
| `libra_policy.py` | trust levels, unlock strengths, scopes and the rules (data) |
| `libra_transport.py` | the wire: `Console` (ask, mode, status, settings, propose, cancel) |
| `libra_update.py` | `dev update` |

Tests: `python3 test_libra_cli.py` and `python3 test_libra_update.py` (a fake board, no hardware).
