#!/usr/bin/env python3
"""Libra UI simulator: a local web page that drives the real UI model.

    python3 sim/sim_server.py            # then open http://127.0.0.1:8765/

Binds to localhost only unless --host is given. Everything here is simulated and holds no real
secrets; the device combo is a demo value. Notes go to sim/qa_notes.jsonl.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sim_core import HERE, Sim

MAX_BODY = 65536
BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "PTT")


def make_handler(sim, allowed_hosts):
    with open(os.path.join(HERE, "index.html"), "rb") as f:
        page = f.read()

    class H(BaseHTTPRequestHandler):
        server_version = "LibraSim"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; img-src data:")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            return allowed_hosts is None or self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b'{"error":"bad host"}')
            if self.path == "/":
                return self._send(200, page, "text/html; charset=utf-8")
            if self.path == "/api/state":
                return self._send(200, json.dumps(sim.state()).encode())
            self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Libra-Sim") != "1":
                return self._send(403, b'{"error":"forbidden"}')  # blocks cross-site posts
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 <= n <= MAX_BODY:
                    raise ValueError("body size")
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be an object")
                out = self._route(body)
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
            self._send(200, json.dumps({"ok": True, "result": out}).encode())

        def _route(self, b):
            if self.path == "/api/button":
                if b.get("name") not in BUTTONS or not isinstance(b.get("down"), bool):
                    raise ValueError("bad button")
                sim.button(b["name"], b["down"])
            elif self.path == "/api/scan":
                return sim.scan(b.get("index"))
            elif self.path == "/api/panel":
                action = b.pop("action", None)
                sim.panel(action, **b)
            elif self.path == "/api/note":
                return sim.note(b.get("text"))
            else:
                raise ValueError("unknown endpoint")

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    sim = Sim()
    loopback = a.host in ("127.0.0.1", "localhost")
    allowed = {"127.0.0.1:%d" % a.port, "localhost:%d" % a.port} if loopback else None
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(sim, allowed))

    def ticker():
        while True:
            try:
                sim.tick()
            except Exception as e:  # keep the simulator alive; the trail shows what happened
                print("tick error:", e)
            time.sleep(0.02)

    threading.Thread(target=ticker, daemon=True).start()
    print("Libra simulator on http://%s:%d/   (Ctrl+C to stop)" % (a.host, a.port))
    if not loopback:
        print("WARNING: reachable from your network; anyone there can drive it and read notes.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
