import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_qrparse as qp
import lb_oath as lo

CPY = sys.implementation.name == "cpython"
GOOD = b"otpauth://totp/Example:alice@google.com?secret=JBSWY3DPEHPK3PXP&issuer=Example"


def ok(s):
    return qp.parse(s if isinstance(s, bytes) else s.encode()).fields


def bad(testcase, s):
    with testcase.assertRaises(qp.ParseError, msg=repr(s)):
        qp.parse(s if isinstance(s, (bytes, bytearray)) else s.encode())


class Basics(unittest.TestCase):
    def test_google_example(self):
        f = ok(GOOD)
        self.assertEqual((f["type"], f["issuer"], f["account"], f["secret"]),
                         ("TOTP", "Example", "alice@google.com", "JBSWY3DPEHPK3PXP"))
        self.assertEqual((f["alg"], f["digits"], f["period"], f["counter"]), ("SHA1", 6, 30, 0))

    def test_all_params(self):
        f = ok("otpauth://totp/ACME:bob?secret=JBSWY3DPEHPK3PXP&issuer=ACME"
               "&algorithm=sha512&digits=8&period=60")
        self.assertEqual((f["alg"], f["digits"], f["period"]), ("SHA512", 8, 60))

    def test_hotp(self):
        f = ok("otpauth://hotp/bob?secret=JBSWY3DPEHPK3PXP&counter=42")
        self.assertEqual((f["type"], f["counter"], f["issuer"]), ("HOTP", 42, ""))

    def test_case_and_bytearray(self):
        self.assertEqual(ok("OTPAUTH://TOTP/a?secret=jbswy3dpehpk3pxp")["type"], "TOTP")
        self.assertEqual(qp.parse(bytearray(GOOD)).type, qp.OTPAUTH)

    def test_label_forms(self):
        self.assertEqual(ok("otpauth://totp/Big%20Co%3Aalice?secret=JBSWY3DPEHPK3PXP")["issuer"], "Big Co")
        self.assertEqual(ok("otpauth://totp/Co:%20alice?secret=JBSWY3DPEHPK3PXP")["account"], "alice")
        self.assertEqual(ok("otpauth://totp/Big Co:alice?secret=JBSWY3DPEHPK3PXP")["issuer"], "Big Co")
        self.assertEqual(ok("otpauth://totp/a+b?secret=JBSWY3DPEHPK3PXP")["account"], "a+b")  # literal in label
        self.assertEqual(ok("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&issuer=Big+Co")["issuer"], "Big Co")

    def test_issuer_param_wins_when_label_has_none(self):
        self.assertEqual(ok("otpauth://totp/alice?secret=JBSWY3DPEHPK3PXP&issuer=X")["issuer"], "X")

    def test_utf8_account(self):
        self.assertEqual(ok("otpauth://totp/J%C3%BCrgen?secret=JBSWY3DPEHPK3PXP")["account"], "Jürgen")

    def test_secret_padding_allowed(self):
        self.assertEqual(ok("otpauth://totp/a?secret=MZXW6YTBOI======")["secret"], "MZXW6YTBOI======")

    def test_msg_repr_hides_secret(self):
        self.assertNotIn("JBSWY3DPEHPK3PXP", repr(qp.parse(GOOD)))

    def test_limits(self):
        self.assertEqual(qp.limits()["max_payload"], 512)


class Rejections(unittest.TestCase):
    def test_not_otpauth(self):
        for s in ["", "hello", "https://example.com", "otpauth:/totp/a?secret=AAAAAAAAAAAAAAAA",
                  "otpauth-migration://offline?data=AAAA", "xotpauth://totp/a?secret=JBSWY3DPEHPK3PXP",
                  "PEER:abcd"]:
            bad(self, s)

    def test_unsupported_types(self):
        for t in ["steam", "ocra", "yubikey", "", "totp2"]:
            bad(self, "otpauth://%s/a?secret=JBSWY3DPEHPK3PXP" % t)

    def test_wrong_input_types(self):
        for v in [None, "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP", 5, ["x"]]:
            with self.assertRaises(qp.ParseError):
                qp.parse(v)

    def test_structure(self):
        base = "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP"
        for s in [base + "#frag", base + "?x=1", "otpauth://totp/a/b?secret=JBSWY3DPEHPK3PXP",
                  "otpauth://totp?secret=JBSWY3DPEHPK3PXP", "otpauth://totp/a",
                  "otpauth://totp/a?", "otpauth://totp/?secret=JBSWY3DPEHPK3PXP",
                  "otpauth://totp/:?secret=JBSWY3DPEHPK3PXP", "otpauth://totp/a:b:c?secret=JBSWY3DPEHPK3PXP",
                  "otpauth://totp/Co:%20?secret=JBSWY3DPEHPK3PXP"]:
            bad(self, s)

    def test_parameters(self):
        base = "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP"
        for extra in ["&secret=JBSWY3DPEHPK3PXP", "&image=http://x", "&foo=bar", "&digits=",
                      "&=1", "&digits", "&&digits=6", "&issuer=A&issuer=A", "&Digits=6",
                      "&digits=7", "&digits=-6", "&digits=+6", "&digits=6.0", "&digits=%DF%A6",
                      "&digits=%D9%A6", "&period=45", "&period=0", "&counter=1",
                      "&algorithm=MD5", "&algorithm=SHA3", "&algorithm=", "&issuer=A%2"]:
            bad(self, base + extra)
        bad(self, "otpauth://totp/a?issuer=A")
        bad(self, "otpauth://totp/Co:a?secret=JBSWY3DPEHPK3PXP&issuer=Evil")
        bad(self, "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&" + "&".join(["issuer=A"] * 3))
        many = "&".join("digits=6" for _ in range(9))
        bad(self, "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&" + many)

    def test_hotp_rules(self):
        base = "otpauth://hotp/a?secret=JBSWY3DPEHPK3PXP"
        bad(self, base)
        bad(self, base + "&counter=")
        bad(self, base + "&counter=-1")
        bad(self, base + "&counter=1&period=30")
        bad(self, base + "&counter=18446744073709551616")
        bad(self, base + "&counter=" + "9" * 21)
        self.assertEqual(ok(base + "&counter=18446744073709551615")["counter"], (1 << 64) - 1)

    def test_secret_rules(self):
        for sec in ["", "=", "====", "JBSW1DPE", "JBSW DPE", "JBSW-DPE", "%E2%82%AC", "A" * 161,
                    "JBSWY3DP%00"]:
            bad(self, "otpauth://totp/a?secret=" + sec)

    def test_bad_encoding_and_bytes(self):
        for s in [b"otpauth://totp/a%?secret=JBSWY3DPEHPK3PXP", b"otpauth://totp/a%2?secret=JBSWY3DPEHPK3PXP",
                  b"otpauth://totp/a%zz?secret=JBSWY3DPEHPK3PXP", b"otpauth://totp/\xc3\xbc?secret=JBSWY3DPEHPK3PXP",
                  b"otpauth://totp/a\n?secret=JBSWY3DPEHPK3PXP", b"otpauth://totp/a\x00?secret=JBSWY3DPEHPK3PXP",
                  b"otpauth://totp/a\x7f?secret=JBSWY3DPEHPK3PXP", b"otpauth://totp/a\t?secret=JBSWY3DPEHPK3PXP"]:
            bad(self, s)

    def test_encoded_control_chars_rejected(self):
        for enc in ["%00", "%0A", "%0D", "%1B", "%7F", "%09"]:
            bad(self, "otpauth://totp/a%s?secret=JBSWY3DPEHPK3PXP" % enc)
            bad(self, "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&issuer=A" + enc)

    def test_invalid_utf8_rejected(self):
        for enc in ["%C0%80", "%C1%BF", "%E0%80%80", "%ED%A0%80", "%F4%90%80%80", "%F5%80%80%80",
                    "%80", "%E2%82", "%FF", "%C3"]:
            bad(self, "otpauth://totp/a%s?secret=JBSWY3DPEHPK3PXP" % enc)

    def test_size_limits(self):
        bad(self, GOOD + b"&issuer=" + b"A" * 600)
        bad(self, "otpauth://totp/%s?secret=JBSWY3DPEHPK3PXP" % ("a" * 129))
        ok("otpauth://totp/%s?secret=JBSWY3DPEHPK3PXP" % ("a" * 128))
        bad(self, b"o" * 100000)

    def test_bidi_passes_parser_but_not_entry(self):
        msg = qp.parse(b"otpauth://totp/bob%E2%80%AEevil?secret=JBSWY3DPEHPK3PXP")
        with self.assertRaises(lo.InvalidEntry):
            lo.from_qr(msg)


class Utf8(unittest.TestCase):
    def test_vectors(self):
        good = [b"", b"a", b"\xc2\x80", b"\xdf\xbf", b"\xe0\xa0\x80", b"\xe2\x82\xac", b"\xed\x9f\xbf",
                b"\xee\x80\x80", b"\xef\xbf\xbf", b"\xf0\x90\x80\x80", b"\xf0\x9f\x98\x80", b"\xf4\x8f\xbf\xbf"]
        evil = [b"\x80", b"\xbf", b"\xc0\x80", b"\xc1\xbf", b"\xc2", b"\xe0\x80\x80", b"\xe0\x9f\xbf",
                b"\xed\xa0\x80", b"\xed\xbf\xbf", b"\xf0\x80\x80\x80", b"\xf0\x8f\xbf\xbf",
                b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80", b"\xf8\x88\x80\x80\x80", b"\xff", b"\xe2\x82",
                b"\xe2\x28\xa1", b"a\xc3"]
        for b in good:
            self.assertTrue(qp._utf8_valid(b), repr(b))
        for b in evil:
            self.assertFalse(qp._utf8_valid(b), repr(b))

    @unittest.skipUnless(CPY, "needs CPython's strict decoder")
    def test_matches_cpython(self):
        rng = Rng(7)
        for _ in range(30000):
            b = bytes(rng.pick(b"\x00\x41\x7f\x80\x8f\x90\x9f\xa0\xbf\xc0\xc1\xc2\xdf\xe0\xe1\xec\xed\xee\xef\xf0\xf1\xf3\xf4\xf5\xff")
                      for _ in range(rng.below(6)))
            try:
                b.decode("utf-8")
                want = True
            except UnicodeDecodeError:
                want = False
            self.assertEqual(qp._utf8_valid(b), want, repr(b))


class Rng:  # xorshift32, so the fuzz test runs on MicroPython too
    def __init__(self, seed):
        self.s = seed or 1

    def next(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s

    def below(self, n):
        return self.next() % n

    def pick(self, seq):
        return seq[self.below(len(seq))]


CORPUS = [GOOD,
          b"otpauth://hotp/ACME%20Co:john@example.com?secret=HXDMVJECJJWSRB3HWIZR4IFUGFTMXBOZ&counter=7&digits=8",
          b"otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&algorithm=SHA512&period=60&issuer=J%C3%BCrgen"]
ALPHABET = b"%&=?/:#+ \x00\x7f\x80\xff0123456789ABCDEFabcdef-_.~@otpauth"


class Fuzz(unittest.TestCase):
    def check(self, payload):
        try:
            msg = qp.parse(payload)
        except qp.ParseError:
            return 0
        try:
            lo.from_qr(msg)
        except lo.InvalidEntry:
            pass
        return 1

    def test_mutations_only_raise_parse_error(self):
        rng = Rng(12345)
        rounds = 20000 if CPY else 400
        accepted = 0
        for _ in range(rounds):
            b = bytearray(rng.pick(CORPUS))
            for _ in range(1 + rng.below(4)):
                op = rng.below(4)
                pos = rng.below(len(b) + 1)
                # slicing only: MicroPython's bytearray has no insert() or item deletion
                if op == 0 and b:
                    b[pos % len(b)] = rng.pick(ALPHABET)
                elif op == 1:
                    b = b[:pos] + bytes([rng.pick(ALPHABET)]) + b[pos:]
                elif op == 2 and b:
                    i = pos % len(b)
                    b = b[:i] + b[i + 1:]
                else:
                    b = b[:pos]
            accepted += self.check(bytes(b))
        self.assertGreater(accepted, 0)  # the fuzzer does reach the success path

    def test_random_bytes(self):
        rng = Rng(99)
        for _ in range(5000 if CPY else 200):
            self.check(bytes(rng.below(256) for _ in range(rng.below(40))))

    def test_prefix_then_noise(self):
        rng = Rng(5)
        for _ in range(5000 if CPY else 200):
            self.check(b"otpauth://" + bytes(rng.pick(ALPHABET) for _ in range(rng.below(60))))


class EndToEnd(unittest.TestCase):
    def test_scan_confirm_add_code(self):
        class Clock:
            def trusted(self):
                return True

            def now(self):
                return 59

        class Store:
            def __init__(self):
                self.r = {}

            def load_all(self):
                return []

            def put(self, i, r):
                self.r[i] = r

            def delete(self, i):
                del self.r[i]

            def set_counter(self, i, n):
                self.r[i]["counter"] = n

        svc = lo.Oath(Store(), Clock())
        entry = lo.from_qr(qp.parse(
            b"otpauth://totp/Lab:rfc?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8&issuer=Lab"))
        self.assertIsNone(entry.id)  # nothing stored before approval
        i = svc.add(entry, approved=True)
        self.assertEqual(svc.code(i).digits, "94287082")  # RFC 6238, T=59, SHA1

    def test_from_qr_rejects_other_messages(self):
        class Other:
            type = "PEER_FP"
            fields = {}
        for m in (Other(), None, object()):
            with self.assertRaises(lo.InvalidEntry):
                lo.from_qr(m)


if __name__ == "__main__":
    unittest.main()
