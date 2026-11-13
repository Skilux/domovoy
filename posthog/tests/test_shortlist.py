#!/usr/bin/env python3
"""Offline tests for posthog/shortlist.py page parsing. No network. Run: python3 -m unittest discover -s posthog/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import shortlist  # noqa: E402


def page(**props):
    base = {"Property ID": {"rich_text": [{"plain_text": "synthetic-1"}]}, "Status": {"select": {"name": "Shortlisted"}}}
    base.update(props)
    return {"id": "page-1", "properties": base}


def num(value):
    return {"number": value}


class Upfront(unittest.TestCase):
    def test_empty_move_in_total_falls_back_to_filled_upfront(self):
        flat = shortlist._flat(page(**{"Move-in total": num(None), "Upfront": num(81000)}))
        self.assertEqual(flat["upfront"], 81000)

    def test_filled_move_in_total_wins(self):
        flat = shortlist._flat(page(**{"Move-in total": num(140000), "Move-in cost": num(1), "Upfront": num(81000)}))
        self.assertEqual(flat["upfront"], 140000)

    def test_move_in_cost_is_second(self):
        flat = shortlist._flat(page(**{"Move-in total": num(None), "Move-in cost": num(99000), "Upfront": num(81000)}))
        self.assertEqual(flat["upfront"], 99000)

    def test_zero_is_a_value_not_unknown(self):
        self.assertEqual(shortlist._flat(page(**{"Move-in total": num(0), "Upfront": num(81000)}))["upfront"], 0)

    def test_all_absent_or_empty_is_unknown(self):
        self.assertIsNone(shortlist._flat(page())["upfront"])
        self.assertIsNone(shortlist._flat(page(**{"Move-in total": num(None), "Upfront": num(None)}))["upfront"])


class Defensive(unittest.TestCase):
    def test_only_required_properties(self):
        flat = shortlist._flat(page())
        self.assertEqual((flat["property_id"], flat["status"]), ("synthetic-1", "Shortlisted"))
        for key in ("reason", "title"):
            self.assertEqual(flat[key], "")
        for key in ("elevator", "portal", "total_monthly", "floor", "interested", "furnished", "commission", "metro_m"):
            self.assertIsNone(flat[key])

    def test_interested_no_with_reason(self):
        flat = shortlist._flat(page(**{"Interested?": {"select": {"name": "No"}},
                                       "Reason": {"rich_text": [{"plain_text": "unfurnished"}]}}))
        self.assertEqual((flat["interested"], flat["reason"]), ("No", "unfurnished"))


if __name__ == "__main__":
    unittest.main()
