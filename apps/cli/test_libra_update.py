import os
import shutil
import tempfile
import unittest

import libra_update


def make_tree(files):
    root = tempfile.mkdtemp()
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return root


class Board:
    """Pretends to be mpremote talking to a board: a dict of path -> bytes."""
    def __init__(self, files=None, fail_copy=False, corrupt=False):
        self.files = dict(files or {})
        self.calls = []
        self.fail_copy = fail_copy
        self.corrupt = corrupt

    def __call__(self, args, port=None):
        self.calls.append(list(args))
        if args[0] == "exec" and "hashlib" in args[1]:
            import hashlib
            return 0, "".join("%s %s\n" % (hashlib.sha256(b).hexdigest(), p) for p, b in sorted(self.files.items()))
        if args[0] == "exec":
            return 0, ""
        if args[:2] == ["fs", "cp"]:
            if self.fail_copy:
                return 1, "mpremote: cp failed"
            dest = args[-1][1:]
            for src in args[2:-1]:
                with open(src, "rb") as fh:
                    data = fh.read()
                self.files[dest + os.path.basename(src)] = data + (b"x" if self.corrupt else b"")
            return 0, ""
        return 1, "unknown"


class Update(unittest.TestCase):
    def setUp(self):
        self.root = make_tree({"lb_a.py": "x = 1\n", "ucompat.py": "y = 2\n", "pico/pico_main.py": "z = 3\n",
                               "pico/notes.txt": "no", "tests/test_a.py": "pass\n", "other.py": "ignored\n"})
        self.said = []

    def tearDown(self):
        shutil.rmtree(self.root)

    def go(self, board, **kw):
        kw.setdefault("confirm", lambda what: True)
        return libra_update.update(runner=board, out=self.said.append, root=self.root, **kw)

    def test_the_required_files_are_the_model_modules_and_pico_files(self):
        self.assertEqual(sorted(libra_update.repo_files(self.root)), ["lb_a.py", "pico_main.py", "ucompat.py"])
        self.assertIn("tests/test_a.py", libra_update.repo_files(self.root, with_tests=True))

    def test_copies_everything_to_an_empty_board_and_verifies(self):
        b = Board()
        self.assertEqual(self.go(b), 0)
        self.assertEqual(sorted(b.files), ["lb_a.py", "pico_main.py", "ucompat.py"])
        self.assertTrue(any("verified by SHA-256" in s for s in self.said))

    def test_only_changed_files_are_copied(self):
        b = Board({"lb_a.py": b"x = 1\n", "ucompat.py": b"old\n", "pico_main.py": b"z = 3\n"})
        self.assertEqual(self.go(b), 0)
        copied = [c for c in b.calls if c[:2] == ["fs", "cp"]]
        self.assertEqual(len(copied), 1)
        self.assertEqual([os.path.basename(x) for x in copied[0][2:-1]], ["ucompat.py"])

    def test_nothing_to_do_copies_nothing(self):
        b = Board({"lb_a.py": b"x = 1\n", "ucompat.py": b"y = 2\n", "pico_main.py": b"z = 3\n"})
        self.assertEqual(self.go(b), 0)
        self.assertFalse(any(c[:2] == ["fs", "cp"] for c in b.calls))

    def test_dry_run_and_cancel_change_nothing(self):
        b = Board()
        self.assertEqual(self.go(b, dry_run=True), 0)
        self.assertEqual(b.files, {})
        self.assertEqual(self.go(b, confirm=lambda what: False), 1)
        self.assertEqual(b.files, {})
        self.assertIn("Cancelled.", self.said)

    def test_extra_files_on_the_board_are_reported_and_kept(self):
        b = Board({"old_thing.py": b"keep me\n"})
        self.assertEqual(self.go(b), 0)
        self.assertIn(b"keep me\n", b.files.values())
        self.assertTrue(any("old_thing.py" in s and "left alone" in s for s in self.said))

    def test_tests_go_to_the_tests_folder_only_when_asked(self):
        b = Board()
        self.go(b, with_tests=True)
        self.assertIn("tests/test_a.py", b.files)
        b2 = Board()
        self.go(b2)
        self.assertNotIn("tests/test_a.py", b2.files)

    def test_a_syntax_error_stops_everything_before_touching_the_board(self):
        with open(os.path.join(self.root, "lb_a.py"), "w") as f:
            f.write("def broken(:\n")
        b = Board()
        self.assertEqual(self.go(b), 1)
        self.assertEqual(b.calls, [])
        self.assertTrue(any("do not compile" in s for s in self.said))

    def test_a_one_off_copy_error_is_retried_once(self):
        class Flaky(Board):
            def __init__(self):
                Board.__init__(self)
                self.copies = 0

            def __call__(self, args, port=None):
                if args[:2] == ["fs", "cp"]:
                    self.copies += 1
                    if self.copies == 1:
                        self.calls.append(list(args))
                        return 1, "OSError: [Errno 5] Input/output error"
                return Board.__call__(self, args, port)
        b = Flaky()
        self.assertEqual(self.go(b, sleep=lambda s: None), 0)
        self.assertEqual(b.copies, 2)
        self.assertTrue(any("retrying once" in s for s in self.said))
        self.assertIn("pico_main.py", b.files)

    def test_a_failed_copy_and_a_failed_verify_are_reported(self):
        self.assertEqual(self.go(Board(fail_copy=True), sleep=lambda s: None), 1)
        self.assertTrue(any("copy failed" in s for s in self.said))
        self.said.clear()
        self.assertEqual(self.go(Board(corrupt=True)), 1)
        self.assertTrue(any("VERIFY FAILED" in s for s in self.said))

    def test_an_unreachable_board_is_explained(self):
        def dead(args, port=None):
            return 1, "mpremote: no device found"
        self.assertEqual(libra_update.update(runner=dead, out=self.said.append, root=self.root), 1)
        self.assertTrue(any("no device found" in s for s in self.said))


if __name__ == "__main__":
    unittest.main()
