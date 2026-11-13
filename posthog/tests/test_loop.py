#!/usr/bin/env python3
"""Offline tests for posthog/loop.py: the rule-breaking SQL and the measure verdict. No network.
Run: python3 -m unittest discover -s posthog/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import loop  # noqa: E402


class BreaksSql(unittest.TestCase):
    def test_elevator_required(self):
        self.assertEqual(loop.breaks_sql({"elevator": "required"}), "(isNotNull(elevator) and elevator = 'No')")

    def test_furnished_required(self):
        self.assertEqual(loop.breaks_sql({"furnished": "required"}), "(isNotNull(furnished) and furnished = 'No')")

    def test_min_floor_uses_the_floor_column(self):
        self.assertEqual(loop.breaks_sql({"min_floor": 2}), "(isNotNull(flat_floor) and toFloat(flat_floor) < 2)")

    def test_max_total_monthly(self):
        self.assertEqual(loop.breaks_sql({"max_total_monthly": 25000}),
                         "(isNotNull(total_monthly) and toFloat(total_monthly) > 25000)")

    def test_max_upfront(self):
        self.assertEqual(loop.breaks_sql({"max_upfront": 90000}), "(isNotNull(upfront) and toFloat(upfront) > 90000)")

    def test_max_commission_zero_means_no_fee_allowed(self):
        self.assertEqual(loop.breaks_sql({"max_commission": 0}), "(isNotNull(commission) and toFloat(commission) > 0)")

    def test_max_metro_m(self):
        self.assertEqual(loop.breaks_sql({"max_metro_m": 800}), "(isNotNull(metro_m) and toFloat(metro_m) > 800)")

    def test_two_keys_join_with_or(self):
        self.assertEqual(loop.breaks_sql({"elevator": "required", "max_upfront": 90000}),
                         "(isNotNull(elevator) and elevator = 'No') or (isNotNull(upfront) and toFloat(upfront) > 90000)")

    def test_other_values_and_unknown_names_break_nothing(self):
        self.assertEqual(loop.breaks_sql({"elevator": "preferred"}), "false")
        self.assertEqual(loop.breaks_sql({"no_such_rule": 1}), "false")

    def test_non_numeric_value_is_refused(self):
        with self.assertRaises(ValueError):
            loop.breaks_sql({"max_upfront": "90000; drop"})
        with self.assertRaises(ValueError):
            loop.breaks_sql({"min_floor": True})


class MeasureSql(unittest.TestCase):
    def test_plain_names_and_filtered_test(self):
        sql = loop.measure_sql("story", 0, {"elevator": "required"})
        self.assertTrue(sql.startswith("select period as period, count() as shown, countIf("))
        self.assertIn("as reached from (select if(min(toInt(properties.criteria_version)) <= 0, "
                      "'Before this change', 'After this change') as period, properties.property_id in "
                      "(select properties.property_id from events where event = 'listing_filtered' "
                      "and properties.dataset = 'story') as filtered, argMax(properties.elevator, timestamp) as elevator "
                      "from events where event = 'listing_shortlisted' and properties.dataset = 'story' "
                      "group by properties.property_id) group by 1 order by 1 desc", sql)

    def test_only_needed_properties_are_read(self):
        sql = loop.measure_sql("story", 0, {"max_upfront": 90000})
        self.assertIn("argMax(properties.upfront, timestamp) as upfront", sql)
        self.assertNotIn("properties.elevator", sql)

    def test_floor_gets_its_own_column_name(self):
        sql = loop.measure_sql("story", 0, {"min_floor": 2})
        self.assertIn("argMax(properties.floor, timestamp) as flat_floor", sql)

    def test_pretty_names(self):
        sql = loop.measure_sql("story", 0, {"furnished": "required"}, pretty=True)
        for name in ("`When`", "`Flats shown`", "`Break the rule`", "`Reached the renter anyway`"):
            self.assertIn("as %s" % name, sql)


class Verdict(unittest.TestCase):
    BEFORE = {"shown": 45, "breaking": 11, "reached": 11}

    def test_not_measurable_without_a_flat_after_the_change(self):
        self.assertEqual(loop.verdict(self.BEFORE, {}),
                         (None, "not measurable yet: no flat was shown after the change"))
        self.assertEqual(loop.verdict(self.BEFORE, {"shown": 0, "breaking": 0, "reached": 0}),
                         (None, "not measurable yet: no flat was shown after the change"))

    def test_helped(self):
        after = {"shown": 12, "breaking": 3, "reached": 0}
        self.assertEqual(loop.verdict(self.BEFORE, after), (
            True, "helped: before 11 of 45 flats shown broke this rule and reached the renter (24 %), "
                  "after 0 of 12 (0 %); the agent filtered out 3."))

    def test_not_helped(self):
        after = {"shown": 12, "breaking": 3, "reached": 3}
        helped, text = loop.verdict(self.BEFORE, after)
        self.assertIs(helped, False)
        self.assertEqual(text, "no improvement yet: before 11 of 45 flats shown broke this rule and reached the renter "
                               "(24 %), after 3 of 12 (25 %); the agent filtered out 0.")

    def test_same_share_is_not_helped(self):
        after = {"shown": 45, "breaking": 11, "reached": 11}
        self.assertIs(loop.verdict(self.BEFORE, after)[0], False)

    def test_no_effect_when_the_rule_broke_nothing_before(self):
        before = {"shown": 45, "breaking": 0, "reached": 0}
        after = {"shown": 12, "breaking": 2, "reached": 2}
        self.assertEqual(loop.verdict(before, after),
                         (False, "no effect: no flat broke this rule before the change."))

    def test_small_sample_note_under_ten_flats(self):
        after = {"shown": 4, "breaking": 1, "reached": 0}
        helped, text = loop.verdict(self.BEFORE, after)
        self.assertIs(helped, True)
        self.assertTrue(text.endswith("the agent filtered out 1. Small sample: 4 flats so far."), text)

    def test_no_small_sample_note_at_ten_flats(self):
        after = {"shown": 10, "breaking": 0, "reached": 0}
        self.assertNotIn("Small sample", loop.verdict(self.BEFORE, after)[1])


if __name__ == "__main__":
    unittest.main()
