"""Offline tests for doctor.py. One fake server on 127.0.0.1 stands in for Notion, Apify, Featherless, ElevenLabs
and the phone server, reached through the *_API_BASE variables and PHONE_URL. Nothing else is contacted.
All keys here are synthetic.
"""
import contextlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import doctor  # noqa: E402

NOTION = "notion-test-secret-9c1e"
APIFY = "apify-test-token-7f3a"
FEATHERLESS = "featherless-test-key-2b6d"
ELEVEN = "eleven-test-key-5a8f"
SECRET = "phone-test-secret-4d2c"
AGENT = "agent_test_0001"
DATA_SOURCE = "11111111-2222-3333-4444-555555555555"
ACTOR = "vladb~domovoy"


def live_properties():
    live = {}
    for name, spec in doctor.CONTRACT["properties"].items():
        kind = spec["type"]
        value = {"type": kind, kind: {}}
        if kind in ("select", "multi_select"):
            value[kind] = {"options": [{"id": str(i), "name": o} for i, o in enumerate(spec.get("options", []))]}
        live[name] = value
    return live


class Fake:
    def __init__(self):
        self.properties = live_properties()
        self.store_ok = True
        self.actor_visible = True
        self.requests = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.fake = self
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        fake = self.server.fake
        path = self.path
        fake.requests.append((self.command, path))
        bearer = self.headers.get("Authorization")
        if path == "/v1/users/me":
            if bearer != "Bearer " + NOTION:
                return self.reply(401, {"code": "unauthorized"})
            return self.reply(200, {"object": "user", "name": "DOMOVOY"})
        if path == "/v1/data_sources/" + DATA_SOURCE:
            return self.reply(200, {"properties": fake.properties})
        if path.startswith("/v1/data_sources/"):
            return self.reply(404, {"code": "object_not_found"})
        if path == "/v2/users/me":
            if bearer != "Bearer " + APIFY:
                return self.reply(401, {"error": {"type": "token-not-valid"}})
            return self.reply(200, {"data": {"username": "tester"}})
        if path == "/v2/acts/" + ACTOR:
            if fake.actor_visible:
                return self.reply(200, {"data": {"id": "act1"}})
            return self.reply(404, {"error": {"type": "record-not-found"}})
        if path == "/v1/models":
            if bearer != "Bearer " + FEATHERLESS:
                return self.reply(401, {"error": "unauthorized"})
            return self.reply(200, {"data": []})
        if path.startswith("/v1/convai/agents"):
            if self.headers.get("xi-api-key") != ELEVEN:
                return self.reply(401, {"detail": "invalid"})
            if path == "/v1/convai/agents?page_size=1":
                return self.reply(200, {"agents": []})
            if path == "/v1/convai/agents/" + AGENT:
                return self.reply(200, {"agent_id": AGENT, "name": "Domovoy"})
            return self.reply(404, {"detail": "not found"})
        if path == "/api/result/" + doctor.PROBE_ID:
            if self.headers.get("x-domovoy-secret") != SECRET:
                return self.reply(401, {"error": "unauthorized"})
            if not fake.store_ok:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self.reply(404, {"error": "not_found"})
        self.reply(418, {"unexpected": path})


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.addCleanup(self.fake.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {
            "backend": {"module": "scripts/notion.py"},
            "notion": {"data_source_id": DATA_SOURCE},
            "phone": {"env_file": os.path.join(self.tmp.name, ".env"), "url_env": "PHONE_URL",
                      "secret_env": "DOMOVOY_SECRET"},
            "active_profile": "p1", "profiles": [{"id": "p1"}],
        }
        self.env = {
            "NOTION_TOKEN": NOTION, "APIFY_TOKEN": APIFY, "FEATHERLESS_API_KEY": FEATHERLESS,
            "ELEVENLABS_API_KEY": ELEVEN, "ELEVENLABS_AGENT_ID": AGENT,
            "PHONE_URL": self.fake.url, "DOMOVOY_SECRET": SECRET,
        }
        doctor.SECRETS.clear()

    def run_doctor(self, *args, write_config=True):
        config_path = os.path.join(self.tmp.name, "config.json")
        if write_config:
            with open(config_path, "w") as f:
                json.dump(self.config, f)
        env_path = self.config["phone"]["env_file"]
        with open(env_path, "w") as f:
            f.write("# synthetic test keys\n")
            for key, value in self.env.items():
                f.write("%s=%s\n" % (key, value))
        os.chmod(env_path, 0o600)
        environ = {"DOMOVOY_CONFIG": config_path, "HOME": self.tmp.name, "PATH": os.environ.get("PATH", "")}
        for name in ("NOTION_API_BASE", "APIFY_API_BASE", "FEATHERLESS_API_BASE", "ELEVENLABS_API_BASE"):
            environ[name] = self.fake.url
        out = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stdout(out):
            code = doctor.main(["check"] + list(args))
        return code, out.getvalue()

    def check(self, *args, **kwargs):
        code, text = self.run_doctor("--json", *args, **kwargs)
        result = json.loads(text)
        return code, result, {item["id"]: item for item in result["checks"]}

    def test_all_set_has_no_fail(self):
        code, result, rows = self.check()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["next"])
        for check_id in ("notion.token", "notion.schema", "apify.token", "apify.actor", "featherless.key",
                         "phone.url", "phone.secret", "phone.store", "elevenlabs.key", "elevenlabs.agent"):
            self.assertEqual(rows[check_id]["status"], "PASS", check_id)
        self.assertEqual(rows["calendar.access"]["status"], "SKIP")
        self.assertEqual(rows["posthog.keys"]["status"], "SKIP")
        self.assertEqual(rows["local.skill"]["status"], "WARN")

    def test_only_get_requests_are_sent(self):
        self.check()
        self.assertTrue(self.fake.requests)
        self.assertEqual({method for method, _ in self.fake.requests}, {"GET"})

    def test_no_key_is_printed(self):
        self.env["NOTION_TOKEN"] = "wrong-" + NOTION
        self.env["DOMOVOY_SECRET"] = "wrong-" + SECRET
        for args in ((), ("--json",)):
            _, text = self.run_doctor(*args)
            for value in (NOTION, APIFY, FEATHERLESS, ELEVEN, SECRET):
                self.assertNotIn(value, text)

    def test_empty_setup_lists_every_fix(self):
        self.env = {}
        code, result, rows = self.check(write_config=False)
        self.assertEqual(code, 1)
        self.assertEqual(rows["local.config"]["status"], "FAIL")
        self.assertEqual(rows["notion.token"]["status"], "FAIL")
        self.assertEqual(rows["notion.schema"]["detail"], "blocked by notion.token")
        self.assertEqual(rows["apify.token"]["status"], "FAIL")
        self.assertEqual(rows["phone.url"]["status"], "FAIL")
        self.assertEqual(rows["featherless.key"]["status"], "SKIP")
        self.assertEqual(rows["elevenlabs.key"]["status"], "SKIP")
        self.assertEqual(result["next"], rows["local.config"]["fix"])
        self.assertEqual(self.fake.requests, [])

    def test_rejected_notion_token_blocks_the_schema_check(self):
        self.env["NOTION_TOKEN"] = "bad"
        code, _, rows = self.check("--only", "notion")
        self.assertEqual(code, 1)
        self.assertEqual(rows["notion.token"]["status"], "FAIL")
        self.assertEqual(rows["notion.schema"]["status"], "SKIP")

    def test_schema_drift_is_named(self):
        del self.fake.properties["Reason"]
        self.fake.properties["Status"]["select"]["options"].pop()
        code, _, rows = self.check("--only", "notion")
        self.assertEqual(code, 1)
        self.assertIn("Reason is missing", rows["notion.schema"]["detail"])
        self.assertIn("Status lacks the options Not booked", rows["notion.schema"]["detail"])
        self.assertIn("notion.py setup", rows["notion.schema"]["fix"])

    def test_missing_and_unseen_data_source(self):
        self.config["notion"]["data_source_id"] = ""
        _, _, rows = self.check("--only", "notion")
        self.assertIn("not set", rows["notion.schema"]["detail"])
        self.config["notion"]["data_source_id"] = "99999999-2222-3333-4444-555555555555"
        _, _, rows = self.check("--only", "notion")
        self.assertIn("Connections", rows["notion.schema"]["fix"])

    def test_other_backend_skips_notion(self):
        self.config["backend"]["module"] = "tests/fake_notion_backend.py"
        self.env.pop("NOTION_TOKEN")
        code, _, rows = self.check("--only", "notion")
        self.assertEqual(code, 0)
        self.assertEqual(rows["notion.token"]["status"], "SKIP")

    def test_actor_not_visible(self):
        self.fake.actor_visible = False
        code, _, rows = self.check("--only", "apify")
        self.assertEqual(code, 1)
        self.assertEqual(rows["apify.token"]["status"], "PASS")
        self.assertIn("apify push", rows["apify.actor"]["fix"])

    def test_phone_wrong_secret_and_broken_store(self):
        self.env["DOMOVOY_SECRET"] = "other"
        _, _, rows = self.check("--only", "phone")
        self.assertEqual(rows["phone.url"]["status"], "PASS")
        self.assertEqual(rows["phone.secret"]["status"], "FAIL")
        self.assertEqual(rows["phone.store"]["status"], "SKIP")
        self.env["DOMOVOY_SECRET"] = SECRET
        self.fake.store_ok = False
        code, _, rows = self.check("--only", "phone")
        self.assertEqual(code, 1)
        self.assertEqual(rows["phone.secret"]["status"], "PASS")
        self.assertIn("Upstash", rows["phone.store"]["fix"])

    def test_phone_unreachable(self):
        self.env["PHONE_URL"] = "http://127.0.0.1:9"
        code, _, rows = self.check("--only", "phone")
        self.assertEqual(code, 1)
        self.assertEqual(rows["phone.url"]["status"], "FAIL")
        self.assertEqual(rows["phone.secret"]["status"], "SKIP")

    def test_elevenlabs_agent_missing_or_unknown(self):
        self.env["ELEVENLABS_AGENT_ID"] = ""
        _, _, rows = self.check("--only", "elevenlabs")
        self.assertIn("sync-agent.mjs", rows["elevenlabs.agent"]["fix"])
        self.env["ELEVENLABS_AGENT_ID"] = "agent_gone"
        code, _, rows = self.check("--only", "elevenlabs")
        self.assertEqual(code, 1)
        self.assertIn("was not found", rows["elevenlabs.agent"]["detail"])

    def test_posthog_is_never_a_fail(self):
        self.env["POSTHOG_PROJECT_TOKEN"] = "phc_test"
        code, _, rows = self.check("--only", "posthog")
        self.assertEqual(code, 0)
        self.assertEqual(rows["posthog.keys"]["status"], "WARN")

    def test_env_file_open_to_others_warns(self):
        self.run_doctor("--json")
        os.chmod(self.config["phone"]["env_file"], 0o644)
        cfg, problem = {"phone": self.config["phone"]}, None
        rows = {item["id"]: item for item in doctor.check_local(doctor.Settings(cfg), problem)}
        self.assertEqual(rows["local.env_file"]["status"], "WARN")
        self.assertIn("chmod 600", rows["local.env_file"]["fix"])

    def test_text_output_and_unknown_group(self):
        code, text = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("PASS  notion.token", text)
        self.assertIn("0 fail", text)
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            doctor.main(["check", "--only", "nope"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
