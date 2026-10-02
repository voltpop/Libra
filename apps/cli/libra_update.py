#!/usr/bin/env python3
"""libra_update.py - copy the firmware files from this repository onto the board and verify them.

    libra dev update [--with-tests] [--dry-run] [--yes]

It compares SHA-256 hashes, copies only what differs, then reads the board back to check every
file. Files the board has that the repository does not are reported, never deleted.

Prototype only: this goes through the board's Python prompt (mpremote), so it stops the running
rig and cannot ask for a PTT hold. A real firmware update will be signed and approved on the
device; do not rely on this path for that.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
MPY = os.path.join(REPO, "firmware", "mpy")

# What the board needs, relative to firmware/mpy: the model and driver modules, the Pico drivers
# and entry points. (tests/ are optional.)
def repo_files(root=MPY, with_tests=False):
    """{path on the board: local path} for everything the board needs."""
    files = {}
    for name in sorted(os.listdir(root)):
        if (name.startswith("lb_") or name == "ucompat.py") and name.endswith(".py"):
            files[name] = os.path.join(root, name)
    pico = os.path.join(root, "pico")
    for name in sorted(os.listdir(pico)):
        if name.endswith(".py"):
            files[name] = os.path.join(pico, name)
    if with_tests:
        tests = os.path.join(root, "tests")
        for name in sorted(os.listdir(tests)):
            if name.endswith(".py"):
                files["tests/" + name] = os.path.join(tests, name)
    return files


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_compiles(files):
    """Syntax-check every file here first, so a typo never lands on the board."""
    bad = []
    for dev, path in files.items():
        try:
            with open(path, "rb") as f:
                compile(f.read(), path, "exec")
        except SyntaxError as e:
            bad.append("%s: %s (line %s)" % (dev, e.msg, e.lineno))
    return bad


DEVICE_HASHES = """
import os, hashlib, binascii
def hs(d, prefix):
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return
    for f in names:
        if f.endswith('.py'):
            h = hashlib.sha256()
            with open((d + '/' if d != '.' else '') + f, 'rb') as fh:
                while True:
                    b = fh.read(512)
                    if not b:
                        break
                    h.update(b)
            print(binascii.hexlify(h.digest()).decode(), prefix + f)
hs('.', '')
hs('tests', 'tests/')
"""


def mpremote_cmd(port):
    exe = shutil.which("mpremote")
    base = [exe] if exe else [sys.executable, "-m", "mpremote"]
    return base + (["connect", port] if port else [])


def run_mpremote(args, port=None, timeout=120):
    """Run mpremote; returns (exit code, stdout). Replaceable in tests."""
    try:
        p = subprocess.run(mpremote_cmd(port) + list(args), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:  # a hung copy: report it like any failure so it gets its one retry
        return 1, "mpremote timed out after %d s" % timeout
    except OSError as e:  # mpremote itself missing or not runnable
        return 1, "could not run mpremote: %s" % (e,)
    return p.returncode, p.stdout.replace("\r", "") + ("\n" + p.stderr if p.returncode else "")


def device_hashes(runner, port=None):
    code, out = runner(["exec", DEVICE_HASHES], port)
    if code:
        raise RuntimeError("could not read the board: " + out.strip().splitlines()[-1] if out.strip() else "no output")
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            result[parts[1]] = parts[0]
    return result


def plan(local, device):
    """(to copy, unchanged, only on the board)."""
    todo = sorted(p for p, path in local.items() if device.get(p) != sha256(path))
    same = sorted(p for p, path in local.items() if device.get(p) == sha256(path))
    have_tests = any(k.startswith("tests/") for k in local)
    extra = sorted(p for p in device if p not in local and (have_tests or not p.startswith("tests/")))
    return todo, same, extra


def update(runner=run_mpremote, port=None, with_tests=False, dry_run=False, confirm=None, out=print,
           root=MPY, sleep=time.sleep):
    """Returns 0 on success (including nothing to do), 1 on failure or if cancelled."""
    local = repo_files(root, with_tests)
    bad = check_compiles(local)
    if bad:
        out("refusing to copy: these files do not compile:\n  " + "\n  ".join(bad))
        return 1
    try:
        dev = device_hashes(runner, port)
    except RuntimeError as e:
        out(str(e) + "\n(is the board plugged in, and is nothing else holding the port?)")
        return 1
    todo, same, extra = plan(local, dev)
    out("%d file(s) up to date, %d to copy%s" % (len(same), len(todo), ":" if todo else "."))
    for p in todo:
        out("  %s %s" % ("new   " if p not in dev else "update", p))
    if extra:
        out("on the board but not in the repository (left alone): " + " ".join(extra))
    if not todo:
        return 0
    if dry_run:
        out("(dry run: nothing copied)")
        return 0
    if confirm is not None and not confirm("This overwrites %d file(s) on the board and stops the running rig." % len(todo)):
        out("Cancelled.")
        return 1
    for dest_dir, group in (("", [p for p in todo if "/" not in p]), ("tests/", [p for p in todo if p.startswith("tests/")])):
        if not group:
            continue
        if dest_dir:
            runner(["exec", "import os\ntry:\n    os.mkdir('tests')\nexcept OSError:\n    pass"], port)
        code, text = runner(["fs", "cp"] + [local[p] for p in group] + [":" + dest_dir], port)
        if code:  # the board's flash sometimes answers with a one-off I/O error: once more, then give up
            out("copy hit an error (%s): retrying once" % text.strip().splitlines()[-1])
            sleep(2)
            code, text = runner(["fs", "cp"] + [local[p] for p in group] + [":" + dest_dir], port)
        if code:
            out("copy failed: " + text.strip().splitlines()[-1])
            return 1
    try:
        after = device_hashes(runner, port)
    except RuntimeError as e:
        out("copied, but could not verify: " + str(e))
        return 1
    wrong = [p for p in todo if after.get(p) != sha256(local[p])]
    if wrong:
        out("VERIFY FAILED for: " + " ".join(wrong))
        return 1
    out("Updated %d file(s); all %d verified by SHA-256. The next libra_* command restarts the rig." % (len(todo), len(local)))
    return 0
