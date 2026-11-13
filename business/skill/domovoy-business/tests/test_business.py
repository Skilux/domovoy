"""Business edition: build, check and rehearse on SYNTHETIC answers. No network."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import apply  # noqa: E402
import leads  # noqa: E402

EXAMPLE = os.path.join(SKILL, "business.example.json")


def run(module, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = module.main(list(argv))
    text = out.getvalue()
    return code, json.loads(text[text.rindex("\n{", 0, len(text) - 2) + 1:] if text.count("\n{") else text)


class BusinessEdition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = os.path.join(self.tmp, "out")
        with open(EXAMPLE, encoding="utf-8") as f:
            self.biz = json.load(f)
        for key in ("DOMOVOY_CONFIG", "DOMOVOY_LEADS"):
            self.addCleanup(os.environ.pop, key, None)

    def answers(self):
        path = os.path.join(self.tmp, "business.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.biz, f)
        return path

    def build(self):
        return run(apply, "build", "--business", self.answers(), "--out", self.out)

    def test_build_check_rehearse(self):
        code, out = self.build()
        self.assertEqual((code, out["built"], out["warnings"]), (0, True, []))
        code, out = run(apply, "check", "--out", self.out)
        self.assertEqual((code, out["ok"]), (0, True))
        code, out = run(apply, "rehearse", "--out", self.out)
        self.assertEqual((code, out["ok"]), (0, True))
        self.assertEqual([s["enquiry_status"] for s in out["steps"]],
                         ["New enquiry", "Viewing booked", "Not booked", "Not booked"])
        self.assertEqual(out["report"]["by_status"], {"Viewing booked": 1, "Not booked": 2})
        with open(os.path.join(self.out, "leads.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["enquiries"], [], "rehearsal must not touch the real leads file")

    def test_unknown_monthly_total_is_refused(self):
        self.biz["listings"][0]["total_monthly"] = None
        code, out = self.build()
        self.assertEqual(code, 2)
        self.assertIn("total_monthly", out["invalid"])
        self.assertFalse(os.path.exists(self.out))

    def test_variable_the_phone_page_does_not_send_is_refused(self):
        self.biz["voice"]["first_message"] = "Hello {{lead_surname}}, I am an AI assistant."
        code, out = self.build()
        self.assertEqual(code, 2)
        self.assertIn("lead_surname", out["invalid"])

    def test_protected_characteristic_gives_a_warning(self):
        self.biz["qualifying_questions"].append("What is your nationality?")
        code, out = self.build()
        self.assertEqual(code, 0)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("protected characteristic", out["warnings"][0])

    def test_rebuild_keeps_enquiries_and_only_first_name_reaches_the_call(self):
        self.build()
        config = os.path.join(self.out, "domovoy.config.json")
        code, new = run(leads, "--config", config, "add-enquiry", "--listing", "syn-flat-002", "--name", "Sam",
                        "--contact", "sam@example.com")
        self.assertEqual((code, new["status"]), (0, "New enquiry"))
        code, out = run(leads, "--config", config, "add-enquiry", "--listing", "syn-flat-002", "--name", "Sam 777")
        self.assertEqual(code, 1)
        code, out = self.build()
        self.assertEqual(out["enquiries_kept"], 1)
        run(leads, "--config", config, "approve", new["id"])
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        pages = leads.list_pages(cfg, "Call approved")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["listing"]["realtor_name"], "Sam")
        self.assertNotIn("example.com/sam", json.dumps(pages))
        self.assertNotIn("sam@example.com", json.dumps(pages))
        code, out = run(leads, "--config", config, "close", new["id"], "--reason", "SYNTHETIC: found another flat")
        code, out = run(leads, "--config", config, "report")
        self.assertEqual(out["dropped"][0]["reason"], "SYNTHETIC: found another flat")


if __name__ == "__main__":
    unittest.main()
