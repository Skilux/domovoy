"""Offline tests for the exact parts of call.py: validation, context build, recheck."""
import copy
import json
import os
import sys
import types
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
        self.assertEqual(context["unknowns"], CFG["call_context"]["ask_also"])

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


def flat(flat_id, status, interested=None):
    return {"id": flat_id, "title": flat_id, "url": "https://example.com/" + flat_id, "status": status,
            "interested": interested, "listing": {}}


def backend_with(*rows, calls=None):
    """call.py's Shortlist over in-memory rows. A status of None returns every row, as scripts/notion.py does."""
    def list_flats(cfg, status=None):
        if calls is not None:
            calls.append(status)
        return [dict(row) for row in rows if status is None or row["status"] == status]
    module = types.SimpleNamespace(list_flats=list_flats, set_status=lambda cfg, flat_id, status: None,
                                   append=lambda cfg, flat_id, text: None)
    return call.Shortlist(module)


def config_with(ask_also):
    cfg = copy.deepcopy(CFG)
    cfg["call_context"].pop("ask_also", None)
    if ask_also is not None:
        cfg["call_context"]["ask_also"] = ask_also
    return cfg


class AskAlsoTest(unittest.TestCase):
    def test_questions_follow_the_flats_own_unknowns(self):
        context = call.build_context(config_with(["the unit number of the flat", "who the landlord is"]),
                                     PAGE, WINDOWS)
        self.assertEqual(context["unknowns"],
                         ["commission", "move_in_date", "the unit number of the flat", "who the landlord is"])
        self.assertNotIn("ask_also", context)
        self.assertEqual(call.validate(context, call.load_schema("call_context")), [])

    def test_duplicates_are_skipped_case_insensitive(self):
        context = call.build_context(config_with(["Commission", " who the landlord is ", "WHO THE LANDLORD IS"]),
                                     PAGE, WINDOWS)
        self.assertEqual(context["unknowns"], ["commission", "move_in_date", "who the landlord is"])

    def test_absent_or_empty_changes_nothing(self):
        for ask_also in (None, []):
            context = call.build_context(config_with(ask_also), PAGE, WINDOWS)
            self.assertEqual(context["unknowns"], ["commission", "move_in_date"])
            self.assertNotIn("ask_also", context)

    def test_at_most_two_extra_questions(self):
        context = call.build_context(config_with(["one", "two", "three"]), PAGE, WINDOWS)
        self.assertEqual(context["unknowns"], ["commission", "move_in_date", "one", "two"])


class CallableTest(unittest.TestCase):
    """Who may be called: Status = Interested, or "Interested?" = Yes whatever the Status."""

    def test_interested_yes_is_callable_whatever_the_status(self):
        for status in ("Shortlisted", "Calling", "Viewing booked", "Not booked"):
            with self.subTest(status=status):
                page = call.pick_page(CFG, backend_with(flat("a", status, True)), None)
                self.assertEqual(page[call.PAGE_ID], "a")

    def test_status_interested_is_callable_without_a_yes(self):
        page = call.pick_page(CFG, backend_with(flat("a", "Interested")), None)
        self.assertEqual(page[call.PAGE_ID], "a")

    def test_a_shortlisted_flat_without_a_yes_is_refused(self):
        backend = backend_with(flat("a", "Shortlisted", False), flat("b", "Shortlisted"),
                               flat("c", "Not booked", False))
        with self.assertRaisesRegex(call.Refusal, "nobody was contacted"):
            call.pick_page(CFG, backend, None)
        with self.assertRaisesRegex(call.Refusal, "nobody was contacted"):
            call.pick_page(CFG, backend, "a")

    def test_two_callable_flats_need_a_choice(self):
        backend = backend_with(flat("a", "Not booked", True), flat("b", "Interested"),
                               flat("c", "Shortlisted", False))
        with self.assertRaisesRegex(call.Refusal, "--page ID"):
            call.pick_page(CFG, backend, None)
        self.assertEqual(call.pick_page(CFG, backend, "a")[call.PAGE_ID], "a")
        self.assertEqual(call.pick_page(CFG, backend, "b")[call.PAGE_ID], "b")
        with self.assertRaisesRegex(call.Refusal, "nobody was contacted"):
            call.pick_page(CFG, backend, "c")

    def test_all_rows_come_in_one_query(self):
        calls = []
        backend = backend_with(flat("a", "Calling", True), flat("b", "Shortlisted"), calls=calls)
        self.assertEqual([p[call.PAGE_ID] for p in call.callable_pages(CFG, backend)], ["a"])
        self.assertEqual(calls, [None])


if __name__ == "__main__":
    unittest.main()
