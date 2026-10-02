import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_fakes
import lb_settings as st
from lb_settings import Settings


class Defaults(unittest.TestCase):
    def test_push_to_show_is_on_by_default(self):
        self.assertTrue(Settings().get("push_to_show"))
        self.assertEqual(Settings().all(), {"push_to_show": True, "utc_offset_min": 0})

    def test_unknown_names_are_refused(self):
        s = Settings()
        with self.assertRaises(st.UnknownSetting):
            s.get("nope")
        with self.assertRaises(st.UnknownSetting):
            s.set("nope", True)

    def test_wrong_types_are_refused(self):
        s = Settings()
        for bad in (0, 1, "yes", None, 1.0, [True]):
            with self.assertRaises(st.InvalidSetting, msg=repr(bad)):
                s.set("push_to_show", bad, approved=True)
        self.assertTrue(s.get("push_to_show"))


class UtcOffset(unittest.TestCase):
    def test_default_is_utc(self):
        self.assertEqual(Settings().get("utc_offset_min"), 0)

    def test_valid_offsets_in_quarter_hours(self):
        s = Settings()
        for m in (-720, -480, -210, -15, 0, 15, 60, 330, 345, 840):
            s.set("utc_offset_min", m)
            self.assertEqual(s.get("utc_offset_min"), m)

    def test_changing_it_needs_no_approval(self):
        s = Settings()
        s.set("utc_offset_min", 120)  # it only changes what is displayed, so it is not a weakening
        s.set("utc_offset_min", 0)

    def test_bad_offsets_are_refused_and_nothing_changes(self):
        s = Settings()
        s.set("utc_offset_min", 60)
        for bad in (-735, -721, 841, 900, 7, 61, -1, True, False, 1.5, 60.0, "60", None):
            with self.assertRaises(st.InvalidSetting, msg=repr(bad)):
                s.set("utc_offset_min", bad)
            self.assertEqual(s.get("utc_offset_min"), 60)

    def test_saved_and_reloaded(self):
        store = lb_fakes.MemSettingsStore()
        Settings(store).set("utc_offset_min", 330)
        self.assertEqual(Settings(store).get("utc_offset_min"), 330)
        self.assertEqual(store.data, {"push_to_show": True, "utc_offset_min": 330})

    def test_a_corrupt_stored_offset_falls_back_to_utc(self):
        for junk in (7, 9999, -9999, True, 1.5, "60", None):
            store = lb_fakes.MemSettingsStore()
            store.load = lambda j=junk: {"push_to_show": False, "utc_offset_min": j}
            s = Settings(store)
            self.assertEqual(s.get("utc_offset_min"), 0, repr(junk))
            self.assertFalse(s.get("push_to_show"))  # the good key is still honoured

    def test_failed_save_rolls_back(self):
        store = lb_fakes.MemSettingsStore()
        s = Settings(store)
        store.fail = True
        with self.assertRaises(st.StorageError):
            s.set("utc_offset_min", 120)
        self.assertEqual(s.get("utc_offset_min"), 0)


class Weakening(unittest.TestCase):
    def test_turning_it_off_needs_approval(self):
        s = Settings()
        with self.assertRaises(st.ApprovalRequired):
            s.set("push_to_show", False)
        self.assertTrue(s.get("push_to_show"))
        s.set("push_to_show", False, approved=True)
        self.assertFalse(s.get("push_to_show"))

    def test_turning_it_on_is_free(self):
        s = Settings()
        s.set("push_to_show", False, approved=True)
        s.set("push_to_show", True)
        self.assertTrue(s.get("push_to_show"))

    def test_setting_it_off_when_already_off_needs_no_approval(self):
        s = Settings()
        s.set("push_to_show", False, approved=True)
        s.set("push_to_show", False)  # nothing weakens
        self.assertFalse(s.get("push_to_show"))


class Persistence(unittest.TestCase):
    def test_saved_and_reloaded(self):
        store = lb_fakes.MemSettingsStore()
        s = Settings(store)
        s.set("push_to_show", False, approved=True)
        self.assertEqual(store.data, {"push_to_show": False, "utc_offset_min": 0})
        self.assertFalse(Settings(store).get("push_to_show"))

    def test_save_failure_rolls_back_and_says_so(self):
        store = lb_fakes.MemSettingsStore()
        s = Settings(store)
        store.fail = True
        with self.assertRaises(st.StorageError):
            s.set("push_to_show", False, approved=True)
        self.assertTrue(s.get("push_to_show"))  # still protected
        self.assertIsNone(store.data)

    def test_corrupt_or_missing_store_falls_back_to_the_strict_default(self):
        class Bad:
            def load(self):
                raise OSError("unreadable")
        self.assertTrue(Settings(Bad()).get("push_to_show"))
        for junk in (None, "x", 5, [1], {"push_to_show": "no"}, {"push_to_show": 0}, {"zzz": False}):
            store = lb_fakes.MemSettingsStore()
            store.load = lambda j=junk: j  # whatever the flash returned, even a non-dict
            self.assertTrue(Settings(store).get("push_to_show"), repr(junk))

    def test_unrelated_stored_keys_are_ignored(self):
        store = lb_fakes.MemSettingsStore()
        store.data = {"push_to_show": False, "backdoor": True}
        s = Settings(store)
        self.assertEqual(s.all(), {"push_to_show": False, "utc_offset_min": 0})


if __name__ == "__main__":
    unittest.main()
