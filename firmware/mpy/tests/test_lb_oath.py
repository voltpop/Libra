import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import hashlib
import lb_oath as lo
from lb_oath import Entry, Oath

try:
    import hmac as _cpy_hmac
    import random
except ImportError:  # MicroPython: skip the cross-checks
    _cpy_hmac = None

HAVE_SHA512 = hasattr(hashlib, "sha512")  # many MicroPython ports ship without it
need_sha512 = unittest.skipUnless(HAVE_SHA512, "this port's hashlib has no sha512")


class Clock:
    def __init__(self, t=59, trusted=True):
        self.t = t
        self._trusted = trusted

    def trusted(self):
        return self._trusted

    def now(self):
        return self.t


class Store:
    def __init__(self, records=()):
        self.rec = {r["id"]: dict(r) for r in records}
        self.log = []
        self.fail = set()

    def _op(self, name):
        if name in self.fail:
            raise OSError("injected " + name)
        self.log.append(name)

    def load_all(self):
        self._op("load")
        return [dict(r) for r in self.rec.values()]

    def put(self, id, record):
        self._op("put")
        self.rec[id] = dict(record)

    def delete(self, id):
        self._op("delete")
        del self.rec[id]

    def set_counter(self, id, n):
        self._op("set_counter")
        self.rec[id]["counter"] = n

    def load_order(self):
        self._op("load_order")
        return getattr(self, "order", None)

    def save_order(self, ids):
        self._op("save_order")
        self.order = list(ids)


S1 = b"12345678901234567890"
S256 = b"12345678901234567890123456789012"
S512 = b"1234567890123456789012345678901234567890123456789012345678901234"


def make(clock=None, store=None, **kw):
    store = store or Store()
    svc = Oath(store, clock or Clock(), **kw)
    return svc, store


def add(svc, secret=S1, account="alice", **kw):
    return svc.add(Entry(account, secret, **kw), approved=True)


class Vectors(unittest.TestCase):
    def test_rfc4226_hotp(self):
        want = ["755224", "287082", "359152", "969429", "338314",
                "254676", "287922", "162583", "399871", "520489"]
        svc, _ = make()
        i = add(svc, type=lo.HOTP)
        self.assertEqual([svc.code(i).digits for _ in want], want)

    def test_rfc6238_totp(self):
        times = [59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000]
        cases = [
            (lo.SHA1, S1, ["94287082", "07081804", "14050471", "89005924", "69279037", "65353130"]),
            (lo.SHA256, S256, ["46119246", "68084774", "67062674", "91819424", "90698825", "77737706"]),
        ]
        if HAVE_SHA512:
            cases.append((lo.SHA512, S512, ["90693936", "25091201", "99943326", "93441116",
                                            "38618901", "47863826"]))
        for alg, secret, want in cases:
            clock = Clock()
            svc, _ = make(clock)
            i = add(svc, secret, alg=alg, digits=8)
            for t, w in zip(times, want):
                clock.t = t
                self.assertEqual(svc.code(i).digits, w, (alg, t))

    def test_leading_zero_kept(self):
        svc, _ = make(Clock(1111111109))
        i = add(svc, digits=8)
        self.assertEqual(svc.code(i).digits, "07081804")

    @unittest.skipIf(_cpy_hmac is None, "needs CPython hmac")
    def test_hmac_matches_stdlib(self):
        be = lo.default_backends()
        rnd = random.Random(1)
        for alg, (ctor, block) in be.items():
            for n in (1, 20, block - 1, block, block + 1, 200):
                key = bytes(rnd.randrange(256) for _ in range(n))
                msg = bytes(rnd.randrange(256) for _ in range(37))
                want = _cpy_hmac.new(key, msg, getattr(hashlib, lo._ALGS[alg][0])).digest()
                self.assertEqual(lo._hmac(be, alg, key, msg), want)


class Base32(unittest.TestCase):
    def test_rfc4648(self):
        for plain, enc in [(b"f", "MY======"), (b"fo", "MZXQ===="), (b"foo", "MZXW6==="),
                           (b"foob", "MZXW6YQ="), (b"fooba", "MZXW6YTB"), (b"foobar", "MZXW6YTBOI======")]:
            self.assertEqual(bytes(lo.b32decode(enc)), plain)
            self.assertEqual(bytes(lo.b32decode(enc.rstrip("="))), plain)

    def test_formatting_tolerated(self):
        self.assertEqual(bytes(lo.b32decode("mzxw 6ytb-oi")), b"foobar")

    def test_rejects(self):
        for bad in ["", "====", "MZXW1", "MZX!", "A", "ABC", "ABCDEF" , "é", 5, None, "A" * 161]:
            with self.assertRaises(lo.InvalidEntry, msg=repr(bad)):
                lo.b32decode(bad)


class Validation(unittest.TestCase):
    def bad(self, **kw):
        args = dict(account="a", secret=S1)
        args.update(kw)
        with self.assertRaises(lo.InvalidEntry, msg=repr(kw)):
            Entry(**args)

    def test_bad_fields(self):
        self.bad(digits=7)
        self.bad(digits=True)
        self.bad(digits="6")
        self.bad(period=45)
        self.bad(alg="MD5")
        self.bad(alg="sha1")
        self.bad(type="STEAM")
        self.bad(counter=-1)
        self.bad(counter=1 << 64)
        self.bad(counter=True)
        self.bad(counter=1.0)
        self.bad(reveal_requires_hold=1)
        self.bad(secret=b"x" * 9)
        self.bad(secret=b"x" * 65)
        self.bad(secret=12345)
        self.bad(secret="")
        self.bad(account="")
        self.bad(account="   ")
        self.bad(account=None)
        self.bad(issuer=5)
        self.bad(account="a" * 65)

    def test_boundaries_ok(self):
        Entry("a" * 64, b"x" * 10)
        Entry("a", b"x" * 64, counter=(1 << 64) - 1)

    def test_spoofing_characters_rejected(self):
        for ch in ["\n", "\x00", "\x1b", "\x7f", "\x85", "​", "‮", "⁦",
                   " ", "﻿"]:
            self.bad(account="bob" + ch + "evil")
            self.bad(issuer=ch + "Bank")

    def test_text_is_stripped(self):
        self.assertEqual(Entry("  bob ", S1, issuer=" X ").account, "bob")

    def test_secret_copied(self):
        raw = bytearray(S1)
        e = Entry("a", raw)
        raw[0] = 0
        self.assertEqual(e._secret[0], S1[0])


class Secrecy(unittest.TestCase):
    def test_no_secret_in_text_or_summary(self):
        svc, _ = make()
        i = add(svc, "JBSWY3DPEHPK3PXP")
        e = svc._entries[i]
        blobs = [repr(e), str(e), repr(svc.list()), repr(svc.code(i))]
        secret_hex = bytes(e._secret).hex()
        for b in blobs:
            self.assertNotIn("JBSWY3DPEHPK3PXP", b)
            self.assertNotIn(secret_hex, b)
        self.assertNotIn("secret", svc.list()[0])
        self.assertFalse(hasattr(e, "secret"))

    def test_code_repr_hides_digits(self):
        svc, _ = make()
        c = svc.code(add(svc))
        self.assertNotIn(c.digits, repr(c))

    def test_delete_wipes_secret(self):
        svc, _ = make()
        i = add(svc)
        e = svc._entries[i]
        svc.delete(i, approved=True)
        self.assertEqual(bytes(e._secret), bytes(len(S1)))


class Approval(unittest.TestCase):
    def test_add_and_delete_need_approval(self):
        svc, store = make()
        with self.assertRaises(lo.ApprovalRequired):
            svc.add(Entry("a", S1))
        self.assertEqual(store.rec, {})
        i = add(svc)
        with self.assertRaises(lo.ApprovalRequired):
            svc.delete(i)
        self.assertEqual(len(svc.list()), 1)

    def test_reveal_gate_does_not_burn_hotp_counter(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP, reveal_requires_hold=True)
        self.assertTrue(svc.reveal_required(i))
        with self.assertRaises(lo.ApprovalRequired):
            svc.code(i)
        self.assertEqual(store.rec[i]["counter"], 0)
        self.assertEqual(svc.code(i, approved=True).digits, "755224")

    def test_add_requires_fresh_entry(self):
        svc, _ = make()
        e = Entry("a", S1)
        svc.add(e, approved=True)
        with self.assertRaises(lo.InvalidEntry):
            svc.add(e, approved=True)
        with self.assertRaises(lo.InvalidEntry):
            svc.add({"account": "a"}, approved=True)


class Clocking(unittest.TestCase):
    def test_totp_refused_when_untrusted(self):
        svc, _ = make(Clock(trusted=False))
        i = add(svc)
        with self.assertRaises(lo.ClockUntrusted):
            svc.code(i)

    def test_bad_time_refused(self):
        for t in (-1, "59", None, 59.0):
            svc, _ = make(Clock(t))
            i = add(svc)
            with self.assertRaises(lo.ClockUntrusted, msg=repr(t)):
                svc.code(i)

    def test_hotp_ignores_clock(self):
        svc, _ = make(Clock(trusted=False))
        i = add(svc, type=lo.HOTP)
        self.assertEqual(svc.code(i).digits, "755224")

    def test_remaining(self):
        for t, r30, r60 in [(0, 30, 60), (1, 29, 59), (29, 1, 31), (30, 30, 30), (59, 1, 1)]:
            clock = Clock(t)
            svc, _ = make(clock)
            a = add(svc, account="a")
            b = add(svc, account="b", period=60)
            self.assertEqual((svc.code(a).remaining_s, svc.code(b).remaining_s), (r30, r60), t)

    def test_hotp_remaining_is_none(self):
        svc, _ = make()
        self.assertIsNone(svc.code(add(svc, type=lo.HOTP)).remaining_s)


class CounterBeforeCode(unittest.TestCase):
    def test_counter_persisted_first(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP)
        store.log.clear()
        svc.code(i)
        self.assertEqual(store.log, ["set_counter"])
        self.assertEqual(store.rec[i]["counter"], 1)

    def test_store_failure_means_no_code_and_no_advance(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP)
        store.fail.add("set_counter")
        with self.assertRaises(lo.StorageError):
            svc.code(i)
        self.assertEqual(svc._entries[i].counter, 0)
        store.fail.clear()
        self.assertEqual(svc.code(i).digits, "755224")  # value 0 was never shown

    def test_no_reuse_after_restart(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP)
        first = svc.code(i).digits
        svc2, _ = make(store=store)  # "power cycle"
        self.assertNotEqual(svc2.code(i).digits, first)
        self.assertEqual(svc2.code(i).digits, "359152")

    def test_counter_exhaustion(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP, counter=lo.MAX_COUNTER)
        with self.assertRaises(lo.CounterExhausted):
            svc.code(i)
        self.assertNotIn("set_counter", store.log)

    def test_last_counter_value_usable(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP, counter=lo.MAX_COUNTER - 1)
        svc.code(i)
        with self.assertRaises(lo.CounterExhausted):
            svc.code(i)


class Management(unittest.TestCase):
    def test_duplicate_and_full(self):
        svc, _ = make(max_entries=2)
        add(svc, account="a", issuer="X")
        with self.assertRaises(lo.Duplicate):
            add(svc, account="a", issuer="X")
        add(svc, account="a", issuer="Y")
        with self.assertRaises(lo.Full):
            add(svc, account="b")

    def test_failed_add_leaves_nothing(self):
        svc, store = make()
        store.fail.add("put")
        e = Entry("a", S1)
        with self.assertRaises(lo.StorageError):
            svc.add(e, approved=True)
        self.assertIsNone(e.id)
        self.assertEqual(svc.list(), [])
        store.fail.clear()
        self.assertEqual(add(svc), 1)

    def test_rename(self):
        svc, store = make()
        a = add(svc, account="a")
        add(svc, account="b")
        svc.rename(a, " alice ")
        self.assertEqual(store.rec[a]["account"], "alice")
        with self.assertRaises(lo.Duplicate):
            svc.rename(a, "b")
        with self.assertRaises(lo.InvalidEntry):
            svc.rename(a, "x‮y")
        store.fail.add("put")
        with self.assertRaises(lo.StorageError):
            svc.rename(a, "zed")
        self.assertEqual(svc.list()[0]["account"], "alice")

    def test_delete(self):
        svc, store = make()
        i = add(svc)
        store.fail.add("delete")
        with self.assertRaises(lo.StorageError):
            svc.delete(i, approved=True)
        self.assertEqual(len(svc.list()), 1)
        self.assertNotEqual(bytes(svc._entries[i]._secret), bytes(len(S1)))
        store.fail.clear()
        svc.delete(i, approved=True)
        with self.assertRaises(lo.NotFound):
            svc.code(i)

    def test_unknown_ids(self):
        svc, _ = make()
        for bad in (99, None, "1", -1):
            with self.assertRaises(lo.NotFound):
                svc.code(bad)
            with self.assertRaises(lo.NotFound):
                svc.reveal_required(bad)

    def test_list_sorted_without_secret(self):
        svc, _ = make()
        for n in "cab":
            add(svc, account=n)
        self.assertEqual([e["id"] for e in svc.list()], [1, 2, 3])

    def test_capacity_default_is_64(self):
        svc, _ = make()
        for n in range(64):
            add(svc, account="a%d" % n)
        with self.assertRaises(lo.Full):
            add(svc, account="x")


class Ordering(unittest.TestCase):
    def three(self):
        svc, store = make()
        ids = [add(svc, account=n) for n in "abc"]
        return svc, store, ids

    def names(self, svc):
        return [e["account"] for e in svc.list()]

    def test_new_accounts_go_last_and_the_order_is_saved(self):
        svc, store, ids = self.three()
        self.assertEqual(self.names(svc), ["a", "b", "c"])
        self.assertEqual(store.order, ids)

    def test_move(self):
        svc, store, ids = self.three()
        svc.move(ids[2], 0)
        self.assertEqual(self.names(svc), ["c", "a", "b"])
        svc.move(ids[2], 2)
        self.assertEqual(self.names(svc), ["a", "b", "c"])
        svc.move(ids[0], 1)
        self.assertEqual(self.names(svc), ["b", "a", "c"])
        self.assertEqual(store.order, [ids[1], ids[0], ids[2]])
        self.assertEqual(svc.order(), [ids[1], ids[0], ids[2]])

    def test_order_survives_a_restart(self):
        svc, store, ids = self.three()
        svc.move(ids[2], 0)
        svc2, _ = make(store=store)
        self.assertEqual(self.names(svc2), ["c", "a", "b"])

    def test_bad_moves_are_refused(self):
        svc, store, ids = self.three()
        for idx in (-1, 3, 99, True, "1", None, 1.0):
            with self.assertRaises(lo.InvalidEntry, msg=repr(idx)):
                svc.move(ids[0], idx)
        with self.assertRaises(lo.NotFound):
            svc.move(999, 0)
        self.assertEqual(self.names(svc), ["a", "b", "c"])

    def test_failed_save_changes_nothing(self):
        svc, store, ids = self.three()
        store.fail.add("save_order")
        with self.assertRaises(lo.StorageError):
            svc.move(ids[2], 0)
        self.assertEqual(self.names(svc), ["a", "b", "c"])

    def test_delete_removes_it_from_the_order(self):
        svc, store, ids = self.three()
        svc.move(ids[2], 0)
        svc.delete(ids[1], approved=True)
        self.assertEqual(self.names(svc), ["c", "a"])
        self.assertEqual(store.order, [ids[2], ids[0]])

    def test_a_failed_order_save_never_hides_an_account(self):
        svc, store = make()
        store.fail.add("save_order")
        add(svc, account="a")
        add(svc, account="b")  # saving the order failed both times
        self.assertEqual(self.names(svc), ["a", "b"])
        svc2, _ = make(store=store)  # restart with a missing or stale order
        self.assertEqual(self.names(svc2), ["a", "b"])

    def test_corrupt_saved_order_is_repaired_on_load(self):
        svc, store, ids = self.three()
        for junk in ([ids[2], 999, ids[2], "x", None, ids[0]], [], "nonsense", 5, [True]):
            store.order = junk
            svc2, _ = make(store=store)
            names = self.names(svc2)
            self.assertEqual(sorted(names), ["a", "b", "c"], repr(junk))  # every account is still there
        store.order = [ids[2], 999, ids[2], "x", None, ids[0]]
        self.assertEqual(self.names(make(store=store)[0]), ["c", "a", "b"])

    def test_unreadable_order_falls_back_to_id_order(self):
        svc, store, ids = self.three()
        store.order = [ids[2], ids[1], ids[0]]
        store.fail.add("load_order")
        self.assertEqual(self.names(make(store=store)[0]), ["a", "b", "c"])


class RevealAll(unittest.TestCase):
    def test_global_push_to_show_gates_every_code(self):
        svc, store = make()
        i = add(svc)
        self.assertFalse(svc.reveal_required(i))
        self.assertEqual(len(svc.code(i).digits), 6)
        svc.set_reveal_all(True)
        self.assertTrue(svc.reveal_required(i))
        with self.assertRaises(lo.ApprovalRequired):
            svc.code(i)
        self.assertEqual(len(svc.code(i, approved=True).digits), 6)

    def test_refusal_does_not_burn_a_hotp_counter(self):
        svc, store = make()
        i = add(svc, type=lo.HOTP)
        svc.set_reveal_all(True)
        with self.assertRaises(lo.ApprovalRequired):
            svc.code(i)
        self.assertEqual(store.rec[i]["counter"], 0)
        self.assertEqual(svc.code(i, approved=True).digits, "755224")

    def test_turning_it_off_restores_the_per_account_rule(self):
        svc, store = make()
        a = add(svc, account="a")
        b = add(svc, account="b", reveal_requires_hold=True)
        svc.set_reveal_all(True)
        svc.set_reveal_all(False)
        self.assertEqual(len(svc.code(a).digits), 6)
        with self.assertRaises(lo.ApprovalRequired):
            svc.code(b)

    def test_summary_keeps_the_per_account_flag_only(self):
        svc, store = make()
        add(svc, account="a")
        svc.set_reveal_all(True)
        self.assertFalse(svc.list()[0]["reveal_requires_hold"])


class Loading(unittest.TestCase):
    def rec(self, **kw):
        r = dict(id=1, issuer="", account="a", type=lo.TOTP, alg=lo.SHA1, digits=6,
                 period=30, counter=0, reveal=False, secret=S1)
        r.update(kw)
        return r

    def test_good_records_load_and_ids_continue(self):
        store = Store([self.rec(id=3), self.rec(id=7, account="b")])
        svc, _ = make(store=store)
        self.assertEqual(svc.rejected, 0)
        self.assertEqual(add(svc, account="c"), 8)

    def test_corrupt_records_skipped_not_fatal(self):
        bad = [self.rec(id=2, digits=7), self.rec(id=3, secret=b"x"), self.rec(id=4, alg="MD5"),
               self.rec(id=5, account="a‮"), self.rec(id=6, counter=-5),
               self.rec(id=0), self.rec(id=-1), self.rec(id="9")]
        missing = self.rec(id=10)
        del missing["secret"]
        store = Store([self.rec(id=1)] + bad + [missing])
        svc, _ = make(store=store)
        self.assertEqual([e["id"] for e in svc.list()], [1])
        self.assertEqual(svc.rejected, len(bad) + 1)

    def test_load_failure_is_storage_error(self):
        store = Store()
        store.fail.add("load")
        with self.assertRaises(lo.StorageError):
            Oath(store, Clock())

    def test_persisted_fields_roundtrip(self):
        svc, store = make()
        add(svc, "JBSWY3DPEHPK3PXP", issuer="GitHub", alg=lo.SHA256, digits=8, period=60,
            reveal_requires_hold=True)
        svc2, _ = make(store=store)
        self.assertEqual(svc2.list(), svc.list())
        self.assertEqual(svc2._entries[1].period, 60)


class Backends(unittest.TestCase):
    def test_missing_hash_is_clean_error(self):
        class Stub:  # a hashlib with no sha512
            sha1 = hashlib.sha1
            sha256 = hashlib.sha256
        real = lo.hashlib
        lo.hashlib = Stub
        try:
            svc, _ = make()
        finally:
            lo.hashlib = real
        self.assertEqual(svc.supported_algs(), [lo.SHA1, lo.SHA256])
        with self.assertRaises(lo.UnsupportedAlgorithm):
            add(svc, S512, alg=lo.SHA512)

    def test_sha512_without_a_backend_is_refused_cleanly(self):
        svc, _ = make(Clock(59))
        if HAVE_SHA512:
            self.assertIn(lo.SHA512, svc.supported_algs())
        else:
            self.assertNotIn(lo.SHA512, svc.supported_algs())
            with self.assertRaises(lo.UnsupportedAlgorithm):
                add(svc, S512, alg=lo.SHA512, digits=8)
            self.assertEqual(svc.list(), [])  # nothing half-added

    @need_sha512
    def test_plugin_backend_used_and_must_match_vectors(self):
        calls = []

        def ctor(data=b""):
            calls.append(1)
            return hashlib.sha512(data)
        svc, _ = make(Clock(59), backends={lo.SHA512: (ctor, 128)})
        i = add(svc, S512, alg=lo.SHA512, digits=8)
        self.assertEqual(svc.code(i).digits, "90693936")
        self.assertTrue(calls)

    def test_backend_cannot_add_algorithms_or_wrong_block(self):
        for bad in ({"MD5": (hashlib.sha1, 64)}, {lo.SHA512: (hashlib.sha1, 64)},
                    {lo.SHA1: (None, 64)}, {lo.SHA1: hashlib.sha1}, {lo.SHA1: (hashlib.sha1,)}):
            with self.assertRaises(lo.OathError, msg=repr(bad)):
                Oath(Store(), Clock(), backends=bad)


if __name__ == "__main__":
    unittest.main()
