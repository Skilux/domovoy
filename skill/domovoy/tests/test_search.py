"""Offline tests for search.py: start, poll, the OUTPUT summary, refusals and token hygiene.

A fake Apify API runs in-process on 127.0.0.1 and is reached through APIFY_API_BASE. Nothing else is contacted.
"""
import contextlib
import copy
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
import search  # noqa: E402

TOKEN = "apify-test-token-7f3a"            # synthetic
NOTION_SECRET = "notion-test-secret-9c1e"  # must never reach the run input or any output
ACTOR = "vladb~domovoy"
RUN_ID = "RUN_TEST_0001"
STORE_ID = "STORE_TEST_0001"
DATA_SOURCE = "ds-test-0001"
CONSOLE = "https://console.apify.com/view/runs/" + RUN_ID
RUN_PATH = "/v2/actor-runs/" + RUN_ID
OUTPUT_PATH = "/v2/key-value-stores/%s/records/OUTPUT" % STORE_ID

PROFILE = {
    "id": "test-2kk-30k",
    "version": 1,
    "filters": {"offer_type": "rent", "property_type": "flat",
                "locations": [{"city": "Praha", "citypart": "Vinohrady"}], "dispositions": ["2+kk"],
                "max_rent": 30000, "min_area_m2": 45, "sources": ["sreality"], "max_listings": 150},
    "household": {"occupants": 1},
    "requirements": {"max_total_monthly": 30000, "elevator": "required"},
}
# The Actor's own RunSummary, serialized by apify/domovoy/models.py (generated, not hand-written).
with open(os.path.join(HERE, "fixtures", "run_summary_example.json"), encoding="utf-8") as f:
    OUTPUT = json.load(f)


def run_object(status):
    return {"id": RUN_ID, "status": status, "defaultKeyValueStoreId": STORE_ID, "consoleUrl": CONSOLE}


class FakeApify:
    """Stands in for the Apify REST API. Records each request as (method, path, authorization, body)."""

    def __init__(self):
        self.statuses = ["SUCCEEDED"]  # one status per run GET; the last one repeats
        self.polls = 0
        self.get_failures = 0          # how many run GETs answer 503 first
        self.output = dict(OUTPUT)     # None means the OUTPUT record does not exist
        self.start_reply = None        # (http status, body) replacing the start reply
        self.requests = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.fake = self
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def next_status(self):
        self.polls += 1
        return self.statuses[min(self.polls, len(self.statuses)) - 1]

    def calls(self, method, suffix=""):
        return [r for r in self.requests if r[0] == method and r[1].endswith(suffix)]


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

    def handle_request(self, method):
        fake = self.server.fake
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode()) if length else None
        auth = self.headers.get("Authorization")
        fake.requests.append((method, self.path, auth, body))
        if auth != "Bearer " + TOKEN:
            return self.reply(401, {"error": {"type": "token-not-provided",
                                              "message": "Authentication token is missing or invalid."}})
        if method == "POST" and self.path == "/v2/actors/%s/runs" % ACTOR:
            if fake.start_reply:
                return self.reply(*fake.start_reply)
            return self.reply(201, {"data": run_object("READY")})
        if method == "GET" and self.path == RUN_PATH:
            if fake.get_failures:
                fake.get_failures -= 1
                return self.reply(503, {"error": {"type": "unavailable", "message": "try again"}})
            return self.reply(200, {"data": run_object(fake.next_status())})
        if method == "GET" and self.path == OUTPUT_PATH:
            if fake.output is None:
                return self.reply(404, {"error": {"type": "record-not-found", "message": "Record not found"}})
            return self.reply(200, fake.output)
        if method == "POST" and self.path == RUN_PATH + "/abort":
            return self.reply(200, {"data": run_object("ABORTING")})
        return self.reply(404, {"error": {"type": "not-found", "message": "no such route"}})

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeApify()
        self.addCleanup(self.fake.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg_path = os.path.join(tmp.name, "config.json")
        self.env_file = os.path.join(tmp.name, "no-such.env")  # never read the real ~/.config/domovoy/.env
        self.save(self.base_config())
        env = mock.patch.dict(os.environ, {
            "DOMOVOY_CONFIG": self.cfg_path, "APIFY_TOKEN": TOKEN, "APIFY_API_BASE": self.fake.url,
            "NOTION_TOKEN": NOTION_SECRET, "no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"})
        env.start()
        self.addCleanup(env.stop)
        for name in ("APIFY_ACTOR_ID", "NOTION_DATA_SOURCE_ID"):
            os.environ.pop(name, None)

    def base_config(self):
        return {
            "active_profile": PROFILE["id"],
            "profiles": [copy.deepcopy(PROFILE)],
            "notion": {"data_source_id": DATA_SOURCE},
            "apify": {"actor_id": ACTOR, "poll_seconds": 0.01, "timeout_seconds": 5, "env_file": self.env_file},
        }

    def save(self, cfg):
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)

    def use_config(self, apify=None, **top):
        cfg = self.base_config()
        cfg["apify"].update(apify or {})
        cfg.update(top)
        self.save(cfg)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = search.main(list(argv))
        raw = out.getvalue()
        return code, json.loads(raw), raw, err.getvalue()

    def test_run_starts_polls_and_prints_the_summary(self):
        self.fake.statuses = ["RUNNING", "SUCCEEDED"]
        code, out, raw, err = self.cli("run")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["run_id"], RUN_ID)
        self.assertEqual(out["status"], "SUCCEEDED")
        self.assertEqual(out["console_url"], CONSOLE)
        self.assertEqual(out["profile"], PROFILE["id"])
        self.assertEqual(out["missing_summary_fields"], [])
        summary = out["summary"]
        self.assertEqual(set(summary), {"sources", "change", "match", "rejected_by_requirement", "notion",
                                        "extraction_providers"})
        self.assertEqual(summary["change"], {"new": 3, "changed": 1, "unchanged": 8})
        self.assertEqual(summary["match"], {"strong": 2, "needs_info": 1, "rejected": 1})
        self.assertEqual(summary["rejected_by_requirement"], {"elevator": 1})
        self.assertEqual(set(summary["sources"][0]), {"portal", "status", "found", "fetched", "failed", "error"})
        self.assertEqual(summary["sources"][1]["portal"], "bezrealitky")
        self.assertEqual(summary["sources"][1]["status"], "failed")
        self.assertEqual(summary["sources"][1]["error"], "source not registered")
        self.assertEqual(summary["notion"], {"created": 3, "updated": 1, "errors": 0})
        self.assertEqual(summary["extraction_providers"], {"featherless": 4, "openai": 0, "cache": 8})
        [start] = self.fake.calls("POST", "/runs")
        self.assertEqual(start[2], "Bearer " + TOKEN)
        body = start[3]
        self.assertEqual(set(body), {"mode", "profile", "notion"})
        self.assertEqual(body["mode"], "search")
        self.assertEqual(body["profile"], PROFILE)
        self.assertEqual(body["notion"], {"dataSourceId": DATA_SOURCE})
        self.assertEqual(len(self.fake.calls("GET", RUN_PATH)), 2)  # RUNNING, then SUCCEEDED

    def test_failed_run_exits_1_and_reads_no_summary(self):
        self.fake.statuses = ["RUNNING", "FAILED"]
        code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 1, raw)
        self.assertEqual(out["status"], "FAILED")
        self.assertEqual(out["console_url"], CONSOLE)
        self.assertIn("FAILED", out["error"])
        self.assertNotIn("summary", out)
        self.assertEqual(self.fake.calls("GET", OUTPUT_PATH), [])

    def test_timeout_exits_1_names_the_resume_command_and_never_aborts(self):
        self.use_config({"timeout_seconds": 0.05})
        self.fake.statuses = ["RUNNING"]
        code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 1, raw)
        self.assertEqual(out["status"], "RUNNING")
        self.assertIn("status --run " + RUN_ID, out["error"])
        self.assertEqual(self.fake.calls("POST", "/abort"), [])

    def test_each_poll_request_gets_no_more_than_the_time_left(self):
        self.fake.statuses = ["RUNNING"]  # never finishes, so the deadline ends the wait
        seen = []
        real_urlopen = search.urllib.request.urlopen

        def recording(request, timeout=None, **kwargs):
            seen.append(timeout)
            return real_urlopen(request, timeout=timeout, **kwargs)

        with mock.patch.object(search.urllib.request, "urlopen", recording):
            code, out, raw, _ = self.cli("status", "--run", RUN_ID, "--timeout", "0.3")
        self.assertEqual(code, 1, raw)
        self.assertIn("status --run " + RUN_ID, out["error"])
        self.assertTrue(seen)
        self.assertTrue(all(0 < t <= 0.3 for t in seen), seen)
        self.fake.requests.clear()
        code, out, raw, _ = self.cli("status", "--run", RUN_ID, "--timeout", "0")
        self.assertEqual(code, 2, raw)
        self.assertEqual(self.fake.requests, [])  # a zero timeout is refused before any request

    def test_status_resumes_a_run_and_is_safe_to_repeat(self):
        for _ in range(2):
            code, out, raw, _ = self.cli("status", "--run", RUN_ID)
            self.assertEqual(code, 0, raw)
            self.assertEqual(out["summary"]["change"]["new"], 3)
        self.assertEqual(self.fake.calls("POST"), [])  # status never starts a run

    def test_no_wait_starts_the_run_and_returns_at_once(self):
        code, out, raw, _ = self.cli("run", "--no-wait")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["run_id"], RUN_ID)
        self.assertEqual(out["status"], "READY")
        self.assertIs(out["waited"], False)
        self.assertIn("status --run " + RUN_ID, out["next"])
        self.assertEqual(len(self.fake.calls("POST", "/runs")), 1)
        self.assertEqual(self.fake.calls("GET"), [])

    def test_refusals_happen_before_any_request(self):
        def two_active_profiles_missing(cfg):
            cfg.update(active_profile=None, profiles=[PROFILE, dict(PROFILE, id="other")])

        def same_id_twice(cfg):
            cfg["profiles"].append(copy.deepcopy(PROFILE))

        def no_filters(cfg):
            cfg["profiles"][0].pop("filters")

        def no_data_source(cfg):
            cfg["notion"] = {}

        cases = [
            ("no active profile and two profiles", two_active_profiles_missing, []),
            ("profile id listed twice", same_id_twice, []),
            ("--profile names no profile", lambda cfg: None, ["--profile", "nope"]),
            ("profile without filters", no_filters, []),
            ("no notion data source", no_data_source, []),
            ("--max-listings below 1", lambda cfg: None, ["--max-listings", "0"]),
        ]
        for name, change, extra in cases:
            with self.subTest(name):
                self.fake.requests.clear()
                cfg = self.base_config()
                change(cfg)
                self.save(cfg)
                code, out, raw, _ = self.cli("run", *extra)
                self.assertEqual(code, 2, raw)
                self.assertIs(out["refused"], True)
                self.assertEqual(self.fake.requests, [])

    def test_missing_token_is_refused_before_any_request(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("APIFY_TOKEN", None)
            code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 2, raw)
        self.assertEqual(self.fake.requests, [])
        self.assertNotIn(TOKEN, raw)

    def test_profile_flag_picks_that_profile(self):
        other = dict(copy.deepcopy(PROFILE), id="other-1kk-20k")
        self.use_config(profiles=[PROFILE, other])
        code, out, raw, _ = self.cli("run", "--profile", "other-1kk-20k")
        self.assertEqual(code, 0, raw)
        self.assertEqual(self.fake.calls("POST", "/runs")[0][3]["profile"]["id"], "other-1kk-20k")

    def test_token_and_notion_secret_never_reach_stdout_or_stderr(self):
        code, out, raw, err = self.cli("run")
        self.assertEqual(code, 0, raw)
        for text in (raw, err):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(NOTION_SECRET, text)
        self.assertNotIn(NOTION_SECRET, json.dumps(self.fake.requests))
        self.assertFalse(any(TOKEN in r[1] for r in self.fake.requests))  # token only in the header

    def test_an_error_that_echoes_the_token_is_scrubbed(self):
        self.fake.start_reply = (401, {"error": {"type": "auth", "message": "bad token " + TOKEN}})
        code, out, raw, err = self.cli("run")
        self.assertEqual(code, 1, raw)
        self.assertIn("HTTP 401", out["error"])
        self.assertIn("[token removed]", raw)
        self.assertNotIn(TOKEN, raw + err)

    def test_http_errors_are_readable_and_not_retried(self):
        self.fake.start_reply = (402, {"error": {"type": "payment-required", "message": "Monthly usage limit reached"}})
        code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 1, raw)
        self.assertEqual(out["error"], "Apify answered HTTP 402: Monthly usage limit reached")
        self.assertEqual(len(self.fake.calls("POST", "/runs")), 1)

    def test_a_start_that_fails_with_5xx_is_never_retried(self):
        self.fake.start_reply = (503, {"error": {"type": "unavailable", "message": "try again"}})
        code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 1, raw)
        self.assertIn("may have started", out["error"])
        self.assertEqual(len(self.fake.calls("POST", "/runs")), 1)

    def test_a_transient_poll_error_is_retried(self):
        self.fake.get_failures = 1
        code, out, raw, err = self.cli("status", "--run", RUN_ID)
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["status"], "SUCCEEDED")
        self.assertEqual(len(self.fake.calls("GET", RUN_PATH)), 2)
        self.assertIn("poll:", err)

    def test_max_listings_and_include_unchanged_reach_the_input(self):
        code, out, raw, _ = self.cli("run", "--max-listings", "20", "--include-unchanged")
        self.assertEqual(code, 0, raw)
        body = self.fake.calls("POST", "/runs")[0][3]
        self.assertEqual(body["profile"]["filters"]["max_listings"], 20)
        self.assertIs(body["includeUnchanged"], True)
        self.assertEqual(PROFILE["filters"]["max_listings"], 150)  # the profile itself is not changed

    def test_extra_input_is_merged_but_cannot_override_profile_mode_or_secrets(self):
        self.use_config(apify={"extra_input": {
            "priorityPropertyIds": ["p-HCWRU3OW3J"], "mode": "katastr_lookup", "profile": {"id": "other"},
            "notionToken": "leaked", "openaiApiKey": "leaked2"}})
        code, out, raw, err = self.cli("run")
        self.assertEqual(code, 0, raw)
        body = self.fake.calls("POST", "/runs")[0][3]
        self.assertEqual(body["priorityPropertyIds"], ["p-HCWRU3OW3J"])
        self.assertEqual(body["mode"], "search")
        self.assertEqual(body["profile"], PROFILE)
        self.assertEqual(body["notion"], {"dataSourceId": DATA_SOURCE})
        self.assertNotIn("includeUnchanged", body)
        self.assertNotIn("notionToken", body)
        self.assertNotIn("openaiApiKey", body)
        self.assertIn("notionToken", err)
        self.assertNotIn("leaked", err + raw)

    def test_include_unchanged_from_extra_input_takes_effect_and_the_flag_still_forces_true(self):
        self.use_config(apify={"extra_input": {"priorityPropertyIds": ["p-HCWRU3OW3J"], "includeUnchanged": True}})
        code, _, raw, _ = self.cli("run")  # no --include-unchanged: the config value is not blocked
        self.assertEqual(code, 0, raw)
        self.assertIs(self.fake.calls("POST", "/runs")[0][3]["includeUnchanged"], True)
        self.use_config(apify={"extra_input": {"includeUnchanged": False}})
        code, _, raw, _ = self.cli("run", "--include-unchanged")
        self.assertEqual(code, 0, raw)
        self.assertIs(self.fake.calls("POST", "/runs")[1][3]["includeUnchanged"], True)

    def test_extra_input_that_is_not_an_object_is_refused_before_any_request(self):
        self.use_config(apify={"extra_input": ["priorityPropertyIds"]})
        code, out, raw, _ = self.cli("run")
        self.assertEqual(code, 2, raw)
        self.assertIn("extra_input", out["reason"])
        self.assertEqual(self.fake.calls("POST", "/runs"), [])

    def test_absent_counts_print_as_null_not_zero(self):
        self.fake.output = {"change": {"new": 2}}
        code, out, raw, _ = self.cli("status", "--run", RUN_ID)
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["summary"]["change"], {"new": 2, "changed": None, "unchanged": None})
        self.assertIsNone(out["summary"]["sources"])
        self.assertIn("change.changed", out["missing_summary_fields"])
        self.assertIn("sources", out["missing_summary_fields"])
        self.assertIsNone(out["summary"]["rejected_by_requirement"])
        self.assertIn("rejected_by_requirement", out["missing_summary_fields"])
        self.assertIsNone(out["summary"]["extraction_providers"]["cache"])
        self.assertIn("extraction_providers.cache", out["missing_summary_fields"])

    def test_summary_fields_sit_where_the_run_summary_puts_them(self):
        # sources is a list of SourceStatus objects; rejected_by_requirement is top-level, not under match.
        self.fake.output = dict(OUTPUT, sources={"sreality": {"portal": "sreality", "status": "ok"}})
        code, out, raw, _ = self.cli("status", "--run", RUN_ID)
        self.assertEqual(code, 0, raw)
        self.assertIsNone(out["summary"]["sources"])
        self.assertIn("sources", out["missing_summary_fields"])
        moved = {k: v for k, v in OUTPUT.items() if k != "rejected_by_requirement"}
        moved["match"] = dict(OUTPUT["match"], rejected_by_requirement=OUTPUT["rejected_by_requirement"])
        self.fake.output = moved
        code, out, raw, _ = self.cli("status", "--run", RUN_ID)
        self.assertEqual(code, 0, raw)
        self.assertIsNone(out["summary"]["rejected_by_requirement"])
        self.assertIn("rejected_by_requirement", out["missing_summary_fields"])
        self.assertEqual(out["summary"]["match"], {"strong": 2, "needs_info": 1, "rejected": 1})

    def test_a_succeeded_run_without_output_exits_1(self):
        self.fake.output = None
        code, out, raw, _ = self.cli("status", "--run", RUN_ID)
        self.assertEqual(code, 1, raw)
        self.assertIn("no OUTPUT record", out["error"])
        self.assertEqual(out["console_url"], CONSOLE)


class CoworkEnvFileTest(unittest.TestCase):
    def test_domovoy_env_file_wins_over_apify_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cowork.env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("APIFY_TOKEN=file-token\n")
            cfg = {"apify": {"env_file": os.path.join(tmp, "config.env")}}
            with mock.patch.dict(os.environ, {"DOMOVOY_ENV_FILE": path}, clear=True):
                settings = search.apify_settings(cfg)
                self.assertEqual(settings["env_file"], path)
                self.assertEqual(search.apify_token(settings["env_file"]), "file-token")
            with mock.patch.dict(os.environ, {"DOMOVOY_ENV_FILE": path, "APIFY_TOKEN": "env-token"}, clear=True):
                self.assertEqual(search.apify_token(search.apify_settings(cfg)["env_file"]), "env-token")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(search.apify_settings(cfg)["env_file"], cfg["apify"]["env_file"])
                self.assertEqual(search.apify_settings({})["env_file"], search.DEFAULT_ENV_FILE)


if __name__ == "__main__":
    unittest.main()
