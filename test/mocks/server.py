"""Deterministic, read-only sensor/PLC/verifier doubles for the Compose test profile."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROLE = os.environ.get("MOCK_ROLE", "sensor")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "UP", "role": ROLE})
        elif ROLE == "sensor" and self.path == "/sample":
            self.reply(200, {"lineId": "mock-line", "equipmentId": "mock-press", "values": {"temperature": 45.0}})
        elif ROLE == "plc" and self.path == "/status":
            self.reply(200, {"state": "simulated_idle", "controlSupported": False})
        else:
            self.reply(404, {"error": "not_found"})

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if ROLE == "verifier" and self.path == "/verify":
            valid = body.get("evaluated") == len(body.get("verdicts", [])) and body.get("evaluated", 0) > 0
            self.reply(200, {"valid": valid, "verifier": "deterministic-v1"})
        else:
            self.reply(404, {"error": "not_found"})

    def reply(self, status, body):
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
