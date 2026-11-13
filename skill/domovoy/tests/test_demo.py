"""demo.py runs the real call.py against the fakes with a made-up result. No network beyond 127.0.0.1."""
import contextlib
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import demo  # noqa: E402


def run_demo(*argv):
    out = io.StringIO()
    before = {name: os.environ.get(name) for name in ("DOMOVOY_CONFIG", "FAKE_NOTION_DB")}
    with contextlib.redirect_stdout(out):
        code = demo.main(["call"] + list(argv))
    after = {name: os.environ.get(name) for name in ("DOMOVOY_CONFIG", "FAKE_NOTION_DB")}
    return code, json.loads(out.getvalue()), before == after


class DemoTest(unittest.TestCase):
    def test_booked_run_is_labelled_synthetic(self):
        code, result, env_restored = run_demo()
        self.assertEqual(code, 0)
        self.assertTrue(env_restored)
        self.assertIs(result["synthetic"], True)
        self.assertIn("SYNTHETIC", result["note"])
        self.assertIs(result["call"]["create_event"], True)
        self.assertEqual(result["call"]["event"]["start"], demo.demo_window()["start"])
        self.assertEqual(result["page"]["status"], "Viewing booked")
        self.assertIn("[SYNTHETIC]", result["page"]["title"])
        self.assertIn("SYNTHETIC", result["page"]["body"])

    def test_not_booked_run_creates_no_event(self):
        code, result, _ = run_demo("--outcome", "not_booked")
        self.assertEqual(code, 0)
        self.assertIs(result["call"]["booked"], False)
        self.assertFalse(result["call"].get("create_event"))
        self.assertEqual(result["page"]["status"], "Not booked")

    def test_window_is_a_monday_evening_in_the_future(self):
        window = demo.demo_window()
        start = demo.datetime.datetime.fromisoformat(window["start"])
        self.assertEqual(start.weekday(), 0)
        self.assertEqual(start.hour, 17)
        self.assertGreater(start.date(), demo.datetime.date.today())


if __name__ == "__main__":
    unittest.main()
