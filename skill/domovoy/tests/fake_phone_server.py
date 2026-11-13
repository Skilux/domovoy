"""FAKE of the DOMOVOY phone server, for local tests only.

This is not the real Vercel phone server. It imitates its HTTP API so client
scripts can be tested without the network. Everything is held in memory and is
lost when the process stops. The signed URL it returns is not usable.

Usage: DOMOVOY_SECRET=... python3 fake_phone_server.py [port]
"""

import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
RESULT_PREFIX = "/api/result/"

SECRET = os.environ.get("DOMOVOY_SECRET", "")
LOCK = threading.Lock()
STATE = {"pending": None, "results": {}, "seen_conversations": set()}


class Handler(BaseHTTPRequestHandler):
    server_version = "FakePhoneServer"
    sys_version = ""

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("x-domovoy-fake", "1")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        sys.stderr.write("%s %s %d\n" % (self.command, self.route(), status))
        sys.stderr.flush()

    def route(self):
        return urlsplit(self.path).path

    def has_secret(self):
        given = self.headers.get("x-domovoy-secret") or ""
        return hmac.compare_digest(given.encode("utf-8"), SECRET.encode("utf-8"))

    def read_object(self):
        try:
            length = int(self.headers.get("content-length") or 0)
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_GET(self):
        path = self.route()
        if path == "/api/pending":
            with LOCK:
                pending = STATE["pending"]
                STATE["pending"] = None
            if pending is None:
                return self.send_json(404, {"error": "no pending call"})
            return self.send_json(200, pending)
        if path == "/api/signed-url":
            return self.send_json(
                200, {"signed_url": "wss://fake.invalid/domovoy", "fake": True}
            )
        if path.startswith(RESULT_PREFIX) and len(path) > len(RESULT_PREFIX):
            if not self.has_secret():
                return self.send_json(401, {"error": "unauthorized"})
            property_id = unquote(path[len(RESULT_PREFIX):])
            with LOCK:
                result = STATE["results"].get(property_id)
            if result is None:
                return self.send_json(404, {"error": "no result yet"})
            return self.send_json(200, result)
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.route()
        if path == "/api/call":
            if not self.has_secret():
                return self.send_json(401, {"error": "unauthorized"})
            body = self.read_object()
            if body is None:
                return self.send_json(400, {"error": "body must be a JSON object"})
            property_id = body.get("property_id")
            if not isinstance(property_id, str) or not property_id:
                return self.send_json(
                    400, {"error": "property_id must be a non-empty string"}
                )
            with LOCK:
                STATE["pending"] = body
            return self.send_json(200, {"ok": True})
        if path == "/api/result":
            body = self.read_object()
            if body is None:
                return self.send_json(400, {"error": "body must be a JSON object"})
            property_id = body.get("property_id")
            conversation_id = body.get("conversation_id")
            if not isinstance(property_id, str):
                return self.send_json(400, {"error": "property_id must be a string"})
            if not isinstance(conversation_id, str):
                return self.send_json(
                    400, {"error": "conversation_id must be a string"}
                )
            with LOCK:
                duplicate = conversation_id in STATE["seen_conversations"]
                if not duplicate:
                    STATE["seen_conversations"].add(conversation_id)
                    STATE["results"][property_id] = body
            if duplicate:
                return self.send_json(200, {"ok": True, "duplicate": True})
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "not found"})

    def not_found(self):
        return self.send_json(404, {"error": "not found"})

    do_HEAD = not_found
    do_PUT = not_found
    do_PATCH = not_found
    do_DELETE = not_found
    do_OPTIONS = not_found


def main():
    if not SECRET:
        sys.exit("error: DOMOVOY_SECRET is not set")
    raw_port = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FAKE_PHONE_PORT")
    try:
        port = int(raw_port) if raw_port else DEFAULT_PORT
    except ValueError:
        sys.exit("error: port must be an integer")
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(
        "FAKE phone server (test only) on http://%s:%d" % (HOST, server.server_address[1]),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
