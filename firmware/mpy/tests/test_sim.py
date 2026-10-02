# Host-only tests for the simulator (CPython): the QA hooks and the HTTP layer's guards.
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sim"))
sys.path.insert(0, os.path.join(HERE, ".."))

import lb_session as ls  # noqa: E402
import sim_core  # noqa: E402
import sim_server  # noqa: E402


def new_sim():
    d = tempfile.mkdtemp()
    return sim_core.Sim(os.path.join(d, "notes.jsonl"))


def unlock(sim):
    for c in (0, 1, 2, 3, 0, 1, 2, 3, 0, 1):
        sim.button(("UP", "DOWN", "LEFT", "RIGHT")[c], True)
        sim.button(("UP", "DOWN", "LEFT", "RIGHT")[c], False)
    sim.button("SELECT", True)
    sim.button("SELECT", False)


class Core(unittest.TestCase):
    def test_starts_locked_and_unlocks(self):
        s = new_sim()
        self.assertEqual(s.state()["screen"]["id"], "Locked")
        unlock(s)
        self.assertEqual(s.state()["screen"]["id"], "Idle")

    def test_state_is_json(self):
        s = new_sim()
        json.dumps(s.state())

    def test_note_saves_context(self):
        s = new_sim()
        unlock(s)
        s.button("UP", True)
        s.button("UP", False)
        self.assertEqual(s.note("  the list is hard to read  "), "Accounts")
        with open(s.notes_path) as f:
            rec = json.loads(f.read().splitlines()[-1])
        self.assertEqual(rec["note"], "the list is hard to read")
        self.assertEqual(rec["screen"], "Accounts")
        self.assertTrue(any(t[1] == "btn" for t in rec["trail"]))
        self.assertIn("debug", rec)

    def test_note_rules(self):
        s = new_sim()
        for bad in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                s.note(bad)
        s.note("x" * 5000)
        with open(s.notes_path) as f:
            rec = json.loads(f.read())
        self.assertEqual(len(rec["note"]), sim_core.MAX_NOTE)

    def test_panel_validation(self):
        s = new_sim()
        for action, kw in [("nope", {}), ("host_request", {"kind": "X"}), ("fp", {"mode": "x"}),
                           ("warp", {"ms": 0}), ("warp", {"ms": 10 ** 9}), ("warp", {"ms": True}),
                           ("warp", {"ms": "5"}), ("host_replace", {"kind": "X"})]:
            with self.assertRaises(ValueError, msg=repr((action, kw))):
                s.panel(action, **kw)

    def test_scan_validation(self):
        s = new_sim()
        for bad in (-1, 99, "1", None, True):
            with self.assertRaises(ValueError):
                s.scan(bad)

    def test_host_request_and_swap(self):
        s = new_sim()
        unlock(s)
        s.panel("host_request", kind="SIGN")
        a = s.state()["debug"]["pending"]
        self.assertEqual(a["summary"], sim_core.HOST_REQUESTS["SIGN"])
        s.panel("host_replace")
        b = s.state()["debug"]["pending"]
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(b["summary"], sim_core.REPLACEMENT["SIGN"])

    def test_warp_triggers_idle_lock_and_fingerprint_mode(self):
        s = new_sim()
        unlock(s)
        s.panel("warp", ms=61000)
        s.tick()
        self.assertEqual(s.state()["screen"]["id"], "Locked")
        s.panel("fp", mode="nomatch")
        self.assertEqual(s.state()["debug"]["fingerprint"], "nomatch")

    def test_power_cycle_keeps_accounts_and_lockout(self):
        s = new_sim()
        for _ in range(5):
            for _ in range(10):
                s.button("DOWN", True)
                s.button("DOWN", False)
            s.button("SELECT", True)
            s.button("SELECT", False)
            s.panel("warp", ms=60000)
        self.assertEqual(s.state()["debug"]["attempts_used"], 5)
        s.panel("power_cycle")
        st = s.state()
        self.assertEqual((st["screen"]["id"], st["debug"]["attempts_used"]), ("Locked", 5))
        s.panel("reset")
        self.assertEqual(s.state()["debug"]["attempts_used"], 0)

    def test_state_carries_the_led_colour(self):
        import time
        s = new_sim()
        s.tick()
        led = s.state()["led"]
        self.assertEqual(len(led), 3)
        self.assertTrue(all(isinstance(x, int) and 0 <= x <= 255 for x in led))
        self.assertEqual("RGB"[led.index(max(led))], "B")  # locked and powered: blue

    def test_a_wrong_combo_shows_red_on_the_led(self):
        import time
        s = new_sim()
        s.tick()
        for _ in range(10):
            s.button("DOWN", True)
            s.button("DOWN", False)
        s.button("SELECT", True)
        s.button("SELECT", False)
        seen = []
        for _ in range(40):
            time.sleep(0.02)
            s.tick()
            seen.append(s.state()["led"])
        self.assertTrue(any(c[0] > 0 and c[1] == 0 and c[2] == 0 for c in seen), "no red frame seen")

    def test_all_samples_scan_without_error(self):
        for i in range(len(sim_core.SAMPLES)):
            s = new_sim()
            unlock(s)
            s.scan(i)
            json.dumps(s.state())


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = new_sim()
        probe = ThreadingHTTPServer(("127.0.0.1", 0), sim_server.BaseHTTPRequestHandler)
        cls.port = probe.server_address[1]
        probe.server_close()
        allowed = {"127.0.0.1:%d" % cls.port, "localhost:%d" % cls.port}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), sim_server.make_handler(cls.sim, allowed))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, r.read(), dict(r.getheaders()))
        c.close()
        return out

    OK = {"X-Libra-Sim": "1"}

    def test_page_and_state(self):
        st, body, hdr = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"Libra simulator", body)
        self.assertIn("default-src 'none'", hdr["Content-Security-Policy"])
        self.assertEqual(hdr["X-Content-Type-Options"], "nosniff")
        st, body, _ = self.req("GET", "/api/state")
        self.assertEqual((st, json.loads(body)["screen"]["id"]), (200, "Locked"))
        self.assertEqual(self.req("GET", "/nope")[0], 404)

    def test_wrong_host_header_refused(self):
        for p in ("/", "/api/state"):
            self.assertEqual(self.req("GET", p, host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.req("POST", "/api/button", {"name": "UP", "down": True}, self.OK,
                                  host="evil.example")[0], 403)

    def test_post_needs_the_custom_header(self):
        self.assertEqual(self.req("POST", "/api/button", {"name": "UP", "down": True})[0], 403)
        self.assertEqual(self.req("POST", "/api/button", {"name": "UP", "down": True},
                                  {"X-Libra-Sim": "0"})[0], 403)

    def test_bad_bodies(self):
        for body in (b"not json", b"[1,2]", b'"x"', b'{"name":"POWER","down":true}',
                     b'{"name":"UP","down":"yes"}', b'{"name":"UP"}'):
            st = self.req("POST", "/api/button", body, self.OK)[0]
            self.assertEqual(st, 400, body)
        self.assertEqual(self.req("POST", "/api/nope", {}, self.OK)[0], 400)
        self.assertEqual(self.req("POST", "/api/scan", {"index": 99}, self.OK)[0], 400)
        self.assertEqual(self.req("POST", "/api/panel", {"action": "x"}, self.OK)[0], 400)
        self.assertEqual(self.req("POST", "/api/note", {"text": ""}, self.OK)[0], 400)

    def test_oversize_body_refused(self):
        big = b'{"text":"' + b"a" * (sim_server.MAX_BODY + 10) + b'"}'
        self.assertEqual(self.req("POST", "/api/note", big, self.OK)[0], 400)

    def test_press_over_http(self):
        st, body, _ = self.req("POST", "/api/button", {"name": "UP", "down": True}, self.OK)
        self.assertEqual((st, json.loads(body)["ok"]), (200, True))
        self.req("POST", "/api/button", {"name": "UP", "down": False}, self.OK)
        trail = json.loads(self.req("GET", "/api/state")[1])["trail"]
        self.assertTrue(any(t[2] == "UP down" for t in trail))


if __name__ == "__main__":
    unittest.main()
