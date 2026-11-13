#!/usr/bin/env python3
"""Offline tests for posthog/schedule.py: the launchd plist, the ask decision and the reading of Claude's answer.
No network, no subprocess. Run: python3 -m unittest discover -s posthog/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import schedule  # noqa: E402

REPO = "/Users/someone/domovoy"
PYTHON = "/usr/local/bin/python3"


class Plist(unittest.TestCase):
    def test_interval_is_in_seconds_and_runs_only_on_the_timer(self):
        body = schedule.plist(10, None, {"PATH": "/usr/bin"}, PYTHON, REPO)
        self.assertEqual(body["StartInterval"], 600)
        self.assertIs(body["RunAtLoad"], False)

    def test_program_runs_tick_with_the_absolute_python_and_repo(self):
        body = schedule.plist(15, None, {"PATH": "/usr/bin"}, PYTHON, REPO)
        self.assertEqual(body["ProgramArguments"], [PYTHON, REPO + "/posthog/schedule.py", "tick"])
        self.assertEqual(body["WorkingDirectory"], REPO)
        self.assertEqual(body["StartInterval"], 900)

    def test_logs_go_to_the_log_file(self):
        body = schedule.plist(10, None, {}, PYTHON, REPO)
        self.assertEqual(body["StandardOutPath"], schedule.LOG)
        self.assertEqual(body["StandardErrorPath"], schedule.LOG)

    def test_path_is_passed_through(self):
        body = schedule.plist(10, None, {"PATH": "/opt/homebrew/bin:/usr/bin"}, PYTHON, REPO)
        self.assertEqual(body["EnvironmentVariables"]["PATH"], "/opt/homebrew/bin:/usr/bin")

    def test_config_argument_wins_over_the_current_env(self):
        body = schedule.plist(10, "/cfg/a.json", {"DOMOVOY_CONFIG": "/cfg/b.json"}, PYTHON, REPO)
        self.assertEqual(body["EnvironmentVariables"]["DOMOVOY_CONFIG"], "/cfg/a.json")

    def test_config_falls_back_to_the_current_env(self):
        body = schedule.plist(10, None, {"DOMOVOY_CONFIG": "/cfg/b.json"}, PYTHON, REPO)
        self.assertEqual(body["EnvironmentVariables"]["DOMOVOY_CONFIG"], "/cfg/b.json")

    def test_config_is_omitted_when_neither_is_set(self):
        body = schedule.plist(10, None, {"PATH": "/usr/bin"}, PYTHON, REPO)
        self.assertNotIn("DOMOVOY_CONFIG", body["EnvironmentVariables"])

    def test_claude_config_dir_only_when_set(self):
        with_dir = schedule.plist(10, None, {"CLAUDE_CONFIG_DIR": "/Users/x/.claude-personal"}, PYTHON, REPO)
        without = schedule.plist(10, None, {"PATH": "/usr/bin"}, PYTHON, REPO)
        self.assertEqual(with_dir["EnvironmentVariables"]["CLAUDE_CONFIG_DIR"], "/Users/x/.claude-personal")
        self.assertNotIn("CLAUDE_CONFIG_DIR", without["EnvironmentVariables"])

    def test_claude_bin_only_when_found(self):
        found = schedule.plist(10, None, {"DOMOVOY_CLAUDE_BIN": "/opt/bin/claude"}, PYTHON, REPO)
        missing = schedule.plist(10, None, {"PATH": "/usr/bin"}, PYTHON, REPO)
        self.assertEqual(found["EnvironmentVariables"]["DOMOVOY_CLAUDE_BIN"], "/opt/bin/claude")
        self.assertNotIn("DOMOVOY_CLAUDE_BIN", missing["EnvironmentVariables"])

    def test_no_other_env_keys_leak_in(self):
        body = schedule.plist(10, "/cfg/a.json", {"PATH": "/usr/bin", "NOTION_TOKEN": "secret", "HOME": "/Users/x"}, PYTHON, REPO)
        self.assertEqual(set(body["EnvironmentVariables"]), {"PATH", "DOMOVOY_CONFIG"})


class ShouldAsk(unittest.TestCase):
    THREE = ["p1|no elevator", "p2|too far from metro", "p3|no elevator"]

    def test_fewer_than_three_rejections_do_not_ask(self):
        self.assertFalse(schedule.should_ask([], None)[0])
        self.assertFalse(schedule.should_ask(["p1|no elevator"], None)[0])
        self.assertFalse(schedule.should_ask(self.THREE[:2], None)[0])

    def test_fewer_than_three_does_not_ask_even_when_the_list_changed(self):
        self.assertFalse(schedule.should_ask(self.THREE[:2], self.THREE)[0])

    def test_three_rejections_with_no_earlier_list_ask(self):
        asked, reason = schedule.should_ask(self.THREE, None)
        self.assertTrue(asked)
        self.assertIn("no earlier tick", reason)

    def test_unchanged_list_does_not_ask_again(self):
        asked, reason = schedule.should_ask(self.THREE, list(self.THREE))
        self.assertFalse(asked)
        self.assertIn("same", reason)

    def test_order_of_the_saved_list_does_not_matter(self):
        self.assertFalse(schedule.should_ask(self.THREE, list(reversed(self.THREE)))[0])

    def test_changed_list_asks_again(self):
        asked, reason = schedule.should_ask(self.THREE + ["p4|no elevator"], self.THREE)
        self.assertTrue(asked)
        self.assertIn("changed", reason)

    def test_a_different_reason_on_the_same_flat_counts_as_a_change(self):
        self.assertTrue(schedule.should_ask(["p1|too far", "p2|too far from metro", "p3|no elevator"], self.THREE)[0])


class ParseOutcome(unittest.TestCase):
    URL = "https://eu.posthog.com/project/348322/notebooks/abc123"

    def test_proposed(self):
        self.assertEqual(schedule.parse_outcome("PROPOSED: " + self.URL), {"proposed": self.URL})

    def test_proposed_after_other_text_uses_the_last_line(self):
        text = "Read the report.\nGrouped 4 flats.\n\nPROPOSED: %s\n" % self.URL
        self.assertEqual(schedule.parse_outcome(text), {"proposed": self.URL})

    def test_proposed_with_markdown_around_it(self):
        self.assertEqual(schedule.parse_outcome("**PROPOSED: %s**" % self.URL), {"proposed": self.URL})

    def test_nothing_gives_the_reason(self):
        self.assertEqual(schedule.parse_outcome("Checked.\nNOTHING: report incomplete"), {"nothing": "report incomplete"})

    def test_nothing_without_a_reason(self):
        self.assertEqual(schedule.parse_outcome("NOTHING:"), {"nothing": "no reason given"})

    def test_proposed_without_a_link_is_no_clear_answer(self):
        self.assertEqual(schedule.parse_outcome("PROPOSED:"), {"nothing": "no clear answer from Claude"})

    def test_proposed_with_something_that_is_not_a_link_is_no_clear_answer(self):
        self.assertEqual(schedule.parse_outcome("PROPOSED: done"), {"nothing": "no clear answer from Claude"})

    def test_garbage(self):
        self.assertEqual(schedule.parse_outcome("I think the flats are fine."), {"nothing": "no clear answer from Claude"})

    def test_answer_not_on_the_last_line_is_no_clear_answer(self):
        self.assertEqual(schedule.parse_outcome("PROPOSED: %s\nthanks" % self.URL), {"nothing": "no clear answer from Claude"})

    def test_empty(self):
        self.assertEqual(schedule.parse_outcome(""), {"nothing": "no clear answer from Claude"})

    def test_none(self):
        self.assertEqual(schedule.parse_outcome(None), {"nothing": "no clear answer from Claude"})


if __name__ == "__main__":
    unittest.main()
