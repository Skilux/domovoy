"""Offline tests for the exact parts of call.py: validation, context build, recheck."""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import call  # noqa: E402

with open(os.path.join(HERE, "..", "config.example.json")) as f:
    CFG = json.load(f)
with open(os.path.join(HERE, "fake_notion_seed.json")) as f:
    PAGE = dict(json.load(f)["pages"][0], notion_page_id="page-7")
WINDOWS = [{"start": "2026-11-16T17:00:00+01:00", "end": "2026-11-16T18:00:00+01:00"},
           {"start": "2026-11-17T18:00:00+01:00", "end": "2026-11-17T19:00:00+01:00"}]
RESULT = {"property_id": "synthetic-test-001", "conversation_id": "conv_1", "outcome": "booked",
          "viewing_start": "2026-11-16T17:00:00+01:00", "answers": [], "new_costs": [], "summary": "Agreed."}


def result(**changes):
    r = copy.deepcopy(RESULT)
    r.update(changes)
    return r


class CallTest(unittest.TestCase):
    def setUp(self):
        self.context = call.build_context(CFG, PAGE, WINDOWS)

    def test_context_is_valid_and_complete(self):
        self.assertEqual(call.validate(self.context, call.load_schema("call_context")), [])
        self.assertEqual(self.context["notion_page_id"], "page-7")
        self.assertEqual(self.context["budget_cap"], CFG["profiles"][0]["requirements"]["max_total_monthly"])
        self.assertIsNone(self.context["commission"])

    def test_unknown_listing_fields_pass_through(self):
        listing = json.dumps({"property_id": "synthetic-test-001", "address": "A", "url": "u",
                              "collected_at": "t", "new_field": {"x": 1}})
        context = call.build_context(CFG, PAGE, WINDOWS, listing)
        self.assertEqual(context["new_field"], {"x": 1})
        self.assertIsNone(context["rent"])
        self.assertEqual(context["unknowns"], [])

    def test_bad_context_is_refused(self):
        with self.assertRaises(call.Refusal):
            call.build_context(CFG, PAGE, [])
        with self.assertRaises(call.Refusal):
            call.build_context(CFG, PAGE, [{"start": "2026-11-16T17:00:00", "end": "2026-11-16T18:00:00"}])
        with self.assertRaises(call.Refusal):
            call.build_context(CFG, PAGE, WINDOWS, json.dumps([{"property_id": "wrong"}]))
        with self.assertRaises(call.Refusal):
            call.build_context(CFG, {"notion_page_id": "p", "listing": None}, WINDOWS)
        with self.assertRaises(call.Refusal):
            call.build_context(dict(CFG, active_profile="none", profiles=CFG["profiles"] * 2), PAGE, WINDOWS)

    def test_booked_inside_window_and_budget(self):
        self.assertEqual(call.recheck(self.context, result()), (True, None))
        self.assertTrue(call.recheck(self.context, result(viewing_start="2026-11-16T16:30:00Z"))[0])

    def test_outside_windows(self):
        for start in ("2026-11-16T18:00:00+01:00", "2026-11-18T17:00:00+01:00", None, "tomorrow at five"):
            self.assertFalse(call.recheck(self.context, result(viewing_start=start))[0], start)

    def test_over_budget(self):
        over = [{"label": "parking", "amount": 6000, "recurring": True}]
        ok, reason = call.recheck(self.context, result(new_costs=over))
        self.assertFalse(ok)
        self.assertIn("over the budget cap", reason)
        once = [{"label": "key fee", "amount": 6000, "recurring": False}]
        self.assertTrue(call.recheck(self.context, result(new_costs=once))[0])
        unknown = [{"label": "internet", "amount": None, "recurring": True}]
        self.assertFalse(call.recheck(self.context, result(new_costs=unknown))[0])
        self.context["total_monthly"] = None
        self.assertFalse(call.recheck(self.context, result())[0])

    def test_other_ends(self):
        self.assertFalse(call.recheck(self.context, result(outcome="not_booked", viewing_start=None))[0])
        self.assertFalse(call.recheck(self.context, result(property_id="other"))[0])
        self.assertFalse(call.recheck(self.context, {"outcome": "booked"})[0])

    def test_comment_has_marker_and_no_contacts(self):
        r = result(summary="Call me on +420 777 123 456 or a.b@example.com <!-- x --> @someone")
        body = call.comment_body(CFG, self.context, r, True, None)
        self.assertIn(call.MARKER % "conv_1", body)
        for leaked in ("777", "example.com", "<!-- x", "@someone"):
            self.assertNotIn(leaked, body)


    def test_real_booked_fixture_passes_and_one_time_fee_keeps_it_booked(self):
        with open(os.path.join(HERE, "fixtures", "real_call_2026-11-13_booked.json")) as f:
            real = json.load(f)
        context, res = real["context"], real["result"]
        self.assertEqual(call.validate(context, call.load_schema("call_context")), [])
        self.assertEqual(call.validate(res, call.load_schema("submit_call_result")), [])
        self.assertEqual(call.recheck(context, res), (True, None))
        self.assertEqual(call.monthly_after_call(context, res), 27500)
        fee = dict(res, new_costs=[{"label": "commission", "amount": 30000, "recurring": False}])
        self.assertEqual(call.recheck(context, fee), (True, None))
        monthly = dict(res, new_costs=[{"label": "fee", "amount": 30000, "recurring": True}])
        self.assertFalse(call.recheck(context, monthly)[0])
        body = call.comment_body(CFG, context, res, True, None)
        self.assertIn("Asked: commission Answer: About thirty thousand CZK", body)
        self.assertIn("Asked: Are pets allowed? Answer: Depends on the pets", body)


if __name__ == "__main__":
    unittest.main()
