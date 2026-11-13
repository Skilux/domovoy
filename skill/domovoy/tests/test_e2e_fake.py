"""End-to-end runs of call.py against the FAKE phone server and the FAKE Notion backend. No network."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import call  # noqa: E402
import fake_notion_backend as notion  # noqa: E402
import fake_phone_server  # noqa: E402

PAGE = "fake-page-001"
WINDOWS = json.dumps([{"start": "2026-11-16T17:00:00+01:00", "end": "2026-11-16T18:00:00+01:00"}])


def result(conversation_id, **changes):
    r = {"property_id": "synthetic-test-001", "conversation_id": conversation_id, "outcome": "booked",
         "viewing_start": "2026-11-16T17:00:00+01:00", "answers": [], "new_costs": [],
         "summary": "SYNTHETIC: agreed Monday 17:00."}
    r.update(changes)
    return r


class EndToEndFake(unittest.TestCase):
    BACKEND = "tests/fake_notion_backend.py"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        fake_phone_server.SECRET = "test-secret"
        fake_phone_server.STATE.update(pending=None, results={}, seen_conversations=set())
        self.server = fake_phone_server.ThreadingHTTPServer(("127.0.0.1", 0), fake_phone_server.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        with open(os.path.join(HERE, "..", "config.example.json")) as f:
            cfg = json.load(f)
        cfg["backend"]["module"] = self.BACKEND
        cfg["phone"].update(url=self.url, secret="test-secret", env_file="", url_env="", secret_env="",
                            poll_seconds=0.1, timeout_seconds=1)
        self.cfg = cfg
        config_path = os.path.join(self.tmp, "config.json")
        with open(config_path, "w") as f:
            json.dump(cfg, f)
        env = {"DOMOVOY_CONFIG": config_path, "FAKE_NOTION_DB": os.path.join(self.tmp, "notion.json")}
        for key, value in env.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key)
        self.old_state, call.STATE_DIR = call.STATE_DIR, os.path.join(self.tmp, "state")
        self.addCleanup(setattr, call, "STATE_DIR", self.old_state)

    VIEWING_DATE = None

    def page(self):
        return notion._page(notion._load(), PAGE)

    def post_result(self, body):
        request = urllib.request.Request(self.url + "/api/result", json.dumps(body).encode(),
                                         {"content-type": "application/json"})
        urllib.request.urlopen(request).read()

    def run_call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = call.main(list(argv))
        return code, json.loads(out.getvalue())

    def run_with_result(self, body):
        notion.set_status(self.cfg, PAGE, "Interested")
        seen = {}

        def answer():
            deadline = time.time() + 5
            while self.page()["status"] != "Calling" and time.time() < deadline:
                time.sleep(0.02)
            seen["status"] = self.page()["status"]
            seen["pending"] = fake_phone_server.STATE["pending"]
            if body is not None:
                self.post_result(body)

        thread = threading.Thread(target=answer)
        thread.start()
        code, out = self.run_call("run", "--windows", WINDOWS)
        thread.join()
        return code, out, seen

    def test_refuses_with_no_interested_flat(self):
        code, out = self.run_call("run", "--windows", WINDOWS)
        self.assertEqual((code, out["refused"]), (2, True))
        self.assertIsNone(fake_phone_server.STATE["pending"])
        self.assertEqual(self.page()["status"], "Shortlisted")

    def test_booked_then_same_result_twice(self):
        code, out, seen = self.run_with_result(result("conv-A"))
        self.assertEqual(seen["status"], "Calling")
        self.assertEqual(seen["pending"]["notion_page_id"], PAGE)
        self.assertEqual(seen["pending"]["budget_cap"], 30000)
        self.assertEqual((code, out["status"], out["create_event"]), (0, "Viewing booked", True))
        self.assertEqual(out["event"]["start"], "2026-11-16T17:00:00+01:00")
        self.assertEqual(self.page()["status"], "Viewing booked")
        self.assertEqual(self.page().get("viewing_date"), self.VIEWING_DATE)
        self.assertEqual(self.page()["body"].count("domovoy-call: conv-A"), 1)
        self.post_result(result("conv-A"))
        code, out = self.run_call("resume", "--page", PAGE)
        self.assertEqual((code, out["already_handled"], out["create_event"]), (0, True, False))
        self.assertEqual(self.page()["body"].count("Call result"), 1)
        self.assertEqual(self.page()["status"], "Viewing booked")

    def test_outside_windows_is_not_booked(self):
        code, out, _ = self.run_with_result(result("conv-B", viewing_start="2026-11-18T10:00:00+01:00"))
        self.assertEqual((out["status"], out["create_event"]), ("Not booked", False))
        self.assertIn("outside the approved windows", self.page()["body"])

    def test_over_budget_is_not_booked(self):
        costs = [{"label": "parking", "amount": 6000, "recurring": True}]
        code, out, _ = self.run_with_result(result("conv-C", new_costs=costs))
        self.assertEqual((out["status"], out["create_event"]), ("Not booked", False))
        self.assertIn("over the budget cap", self.page()["body"])

    def test_stale_result_is_skipped_and_timeout_is_not_booked(self):
        self.run_with_result(result("conv-A"))
        code, out, _ = self.run_with_result(None)
        self.assertEqual((code, out["status"], out["create_event"]), (0, "Not booked", False))
        self.assertIn("no result from the phone server", out["reason"])
        self.assertEqual(self.page()["body"].count("Call result"), 2)

    def test_two_interested_flats_need_a_choice(self):
        db = notion._load()
        db["pages"].append(dict(db["pages"][0], notion_page_id="fake-page-002", status="Interested"))
        db["pages"][0]["status"] = "Interested"
        notion._save(db)
        code, out = self.run_call("run", "--windows", WINDOWS)
        self.assertEqual((code, out["refused"]), (2, True))
        self.assertIsNone(fake_phone_server.STATE["pending"])
        code, out = self.run_call("check", "--windows", WINDOWS, "--page", "fake-page-002")
        self.assertEqual((code, out["call_context"]["notion_page_id"]), (0, "fake-page-002"))

    def test_real_fixture_resume_without_local_state(self):
        with open(os.path.join(HERE, "fixtures", "real_call_2026-11-13_booked.json")) as f:
            real = json.load(f)
        listing = {k: v for k, v in real["context"].items()
                   if k not in ("notion_page_id", "available_windows", "user_name", "budget_cap", "realtor_name")}
        db = notion._load()
        db["pages"] = [{"notion_page_id": "fake-page-real", "title": "[SAMPLE] Korunni 88", "status": "Calling",
                        "url": "https://example.com/fake-notion/fake-page-real", "listing": listing, "body": ""}]
        notion._save(db)
        self.post_result(real["result"])
        windows = json.dumps(real["context"]["available_windows"])
        code, out = self.run_call("resume", "--page", "fake-page-real", "--windows", windows)
        self.assertEqual((code, out["status"], out["create_event"]), (0, "Viewing booked", True))
        self.assertEqual(out["event"]["start"], "2026-11-16T17:00:00+01:00")
        self.assertEqual(out["answers"][0], {"question": "commission", "answer": "About thirty thousand CZK"})
        self.assertIsNone(fake_phone_server.STATE["pending"])
        page = notion._page(notion._load(), "fake-page-real")
        self.assertEqual(page["body"].count("Call result"), 1)
        code, out = self.run_call("resume", "--page", "fake-page-real", "--windows", windows)
        self.assertEqual((out["already_handled"], out["create_event"]), (True, False))
        page = notion._page(notion._load(), "fake-page-real")
        self.assertEqual((page["status"], page["body"].count("Call result")), ("Viewing booked", 1))

    def test_unreachable_phone_server_leaves_interested(self):
        notion.set_status(self.cfg, PAGE, "Interested")
        self.cfg["phone"]["url"] = "http://127.0.0.1:9"
        with open(os.environ["DOMOVOY_CONFIG"], "w") as f:
            json.dump(self.cfg, f)
        code, out = self.run_call("run", "--windows", WINDOWS)
        self.assertEqual(code, 1)
        self.assertEqual(self.page()["status"], "Interested")


class EndToEndFakeFlatsShape(EndToEndFake):
    BACKEND = "tests/fake_notion_backend_flats.py"
    VIEWING_DATE = "2026-11-16T17:00:00+01:00"


if __name__ == "__main__":
    unittest.main()
