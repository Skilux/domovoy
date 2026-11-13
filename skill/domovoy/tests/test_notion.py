"""Tests for scripts/notion.py: the contract, setup planning, the shortlist backend and the HTTP layer.

Offline by default. Every Notion call goes to FakeNotion, which answers by method and path and records each call.
Nothing here touches the network. LiveNotion runs only with DOMOVOY_LIVE=1 and then uses the real workspace.
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import call  # noqa: E402
import notion  # noqa: E402

PARENT = "11111111-2222-3333-4444-555555555555"
DB_ID = "aaaaaaaa-0000-4000-8000-000000000001"
DS_ID = "bbbbbbbb-0000-4000-8000-000000000002"
PAGE_ID = "cccccccc-0000-4000-8000-000000000003"
OTHER_DB_ID = "dddddddd-0000-4000-8000-000000000004"
TABLE_ID = "eeeeeeee-0000-4000-8000-000000000005"
OTHER_PAGE_ID = "99999999-0000-4000-8000-000000000009"
DB_URL = "https://www.notion.so/synthetic-shortlist"
PAGE_URL = "https://www.notion.so/synthetic-flat-001"
ENV = {"NOTION_TOKEN": "test-token", "NOTION_PARENT_PAGE_ID": PARENT}
STATUSES = ["Shortlisted", "Not interested", "Interested", "Calling", "Viewing booked", "Not booked"]
WINDOWS = [{"start": "2026-11-16T17:00:00+01:00", "end": "2026-11-16T18:00:00+01:00"}]

with open(os.path.join(HERE, "..", "config.example.json")) as f:
    CFG_NOTION = dict(json.load(f), notion={"data_source_id": DS_ID})

EXPECTED_LISTING = {
    "property_id": "synthetic-test-001",
    "address": "Synthetic Street 1, Testville",
    "url": "https://example.com/synthetic-listing-001",
    "collected_at": "2026-11-13T12:00:00+01:00",
    "rent": 22000,
    "total_monthly": 24500,
    "upfront": 46500,  # call_context upfront, read from the "Move-in cost" property
    "kauce": 22000,
    "commission": None,
    "move_in_date": None,
    "lease_type": "najem",
    "missing_furniture_cost": None,
    "unknowns": ["Commission not stated", "Move-in date unknown"],
}


class FakeNotion:
    """Canned answers keyed by (method, path). A callable answer gets (body, query). Records every call."""

    def __init__(self):
        self.answers = {}
        self.calls = []

    def answer(self, method, path, value):
        self.answers[(method, path)] = value

    def __call__(self, method, path, body=None, query=None):
        self.calls.append((method, path, body))
        if (method, path) not in self.answers:
            raise AssertionError("unexpected Notion call: %s %s" % (method, path))
        value = self.answers[(method, path)]
        return value(body, query) if callable(value) else copy.deepcopy(value)

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH") and not c[1].endswith("/query")]


def live(remove=(), replace=None):
    """Properties as Notion returns them for a data source that matches the contract."""
    props = {}
    for name, spec in notion.PROPS.items():
        kind = spec["type"]
        value = {"id": "p-%s" % name, "type": kind}
        if kind in ("select", "multi_select"):
            value[kind] = {"options": [{"id": "%s/%d" % (name, i), "name": option, "color": "default"}
                                       for i, option in enumerate(spec.get("options", []))]}
        elif kind == "number":
            value[kind] = {"format": spec.get("format", "number")}
        else:
            value[kind] = {}
        props[name] = value
    for name in remove:
        del props[name]
    props.update(replace or {})
    return props


def database_object(db_id=DB_ID):
    return {"id": db_id, "url": DB_URL, "data_sources": [{"id": DS_ID, "name": notion.DB_TITLE}]}


def child_block(block_id, title=notion.DB_TITLE):
    return {"id": block_id, "type": "child_database", "child_database": {"title": title}}


def no_more(results):
    return {"results": results, "has_more": False, "next_cursor": None}


def flat_page(page_id=PAGE_ID, status="Interested"):
    def text(value):
        return [{"plain_text": value}] if value else []
    return {
        "id": page_id,
        "url": PAGE_URL,
        "properties": {
            "Name": {"type": "title", "title": text("2+kk · SYNTHETIC · Testville")},
            "Property ID": {"type": "rich_text", "rich_text": text("synthetic-test-001")},
            "Status": {"type": "select", "select": {"name": status}},
            "Reason": {"type": "rich_text", "rich_text": []},
            "Notes": {"type": "rich_text", "rich_text": []},
            "Viewing date": {"type": "date", "date": None},
            "Address": {"type": "rich_text", "rich_text": text("Synthetic Street 1, Testville")},
            "URL": {"type": "url", "url": "https://example.com/synthetic-listing-001"},
            "Collected at": {"type": "date", "date": {"start": "2026-11-13T12:00:00+01:00"}},
            "Rent": {"type": "number", "number": 22000},
            "Total monthly": {"type": "number", "number": 24500},
            "Move-in cost": {"type": "number", "number": 46500},
            "Kauce": {"type": "number", "number": 22000},
            "Commission": {"type": "number", "number": None},
            "Move-in date": {"type": "date", "date": None},
            "Lease type": {"type": "select", "select": {"name": "Lease"}},
            "Missing furniture cost": {"type": "number", "number": None},
            "Unknowns": {"type": "rich_text", "rich_text": text("Commission not stated\nMove-in date unknown")},
            "Agency": {"type": "rich_text", "rich_text": text("SYNTHETIC Agency")},
            "Contact": {"type": "rich_text", "rich_text": text("SYNTHETIC Person")},
            "Email": {"type": "email", "email": "synthetic@example.com"},
            "Phone": {"type": "phone_number", "phone_number": "SYNTHETIC-PHONE"},
            "Owner listing": {"type": "checkbox", "checkbox": False},
        },
    }


class ContractTest(unittest.TestCase):
    def test_statuses_are_the_six_from_the_plan(self):
        self.assertEqual(notion.STATUSES, STATUSES)

    def test_every_property_has_a_known_type_and_owner(self):
        known = {"title", "rich_text", "select", "multi_select", "number", "date", "url", "email",
                 "phone_number", "checkbox"}
        for name, spec in notion.PROPS.items():
            self.assertIn(spec["type"], known, name)
            self.assertIn(spec["owner"], {"actor", "vladimir", "claude"}, name)
        self.assertEqual(sum(1 for spec in notion.PROPS.values() if spec["type"] == "title"), 1)

    def test_actor_updates_only_owned_properties_and_never_status_reason_notes_or_viewing_date(self):
        self.assertEqual(notion.PROPS[notion.CONTRACT["upsert_key"]]["type"], "rich_text")
        updatable = {name for name, spec in notion.PROPS.items()
                     if spec["owner"] == "actor" and spec.get("actor_writes") != "create"}
        for name in ("Status", "Reason", "Notes", "Viewing date"):
            self.assertNotIn(name, updatable)
        self.assertIn("Rent", updatable)
        self.assertIn("Name", updatable)

    def test_lease_type_labels_match_the_call_context_values(self):
        self.assertEqual(set(notion.PROPS["Lease type"]["options"]), set(notion.LEASE_TYPE))
        self.assertEqual(set(notion.LEASE_TYPE.values()), {"najem", "podnajem", None})

    def test_property_schema_shapes(self):
        self.assertEqual(notion.property_schema(notion.PROPS["Rent"]), {"number": {"format": "koruna"}})
        self.assertEqual(notion.property_schema({"type": "select", "options": ["A"]}),
                         {"select": {"options": [{"name": "A"}]}})
        self.assertEqual(notion.property_schema({"type": "checkbox"}), {"checkbox": {}})


class EnvTest(unittest.TestCase):
    def test_env_file_lines_are_read_and_comments_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write('# NOTION_TOKEN=commented\nexport NOTION_TOKEN="file-token"\n'
                        'NOTION_PARENT_PAGE_ID=abc=def\n\nOTHER=1\n')
            values = notion.read_env_file(path)
        self.assertEqual(values["NOTION_TOKEN"], "file-token")
        self.assertEqual(values["NOTION_PARENT_PAGE_ID"], "abc=def")
        self.assertNotIn("# NOTION_TOKEN", values)

    def test_environment_wins_and_a_missing_value_names_only_the_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("NOTION_TOKEN=file-token\n")
            with mock.patch.dict(os.environ, {"NOTION_TOKEN": "env-token"}), \
                    mock.patch.object(notion, "ENV_FILE", path):
                self.assertEqual(notion.setting("NOTION_TOKEN"), "env-token")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(notion, "ENV_FILE", path):
                self.assertEqual(notion.setting("NOTION_TOKEN"), "file-token")
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(notion, "ENV_FILE", os.path.join(tmp, "missing.env")):
                with self.assertRaisesRegex(RuntimeError, "NOTION_TOKEN is not set"):
                    notion.setting("NOTION_TOKEN")


class HttpTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_request_sends_the_version_the_token_and_the_json_body(self):
        seen = {}

        class Reply:
            status = 200
            headers = {}

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(req, timeout):
            seen.update(method=req.get_method(), url=req.full_url, timeout=timeout,
                        headers={k.lower(): v for k, v in req.header_items()}, body=req.data)
            return Reply()

        with mock.patch.object(notion.urllib.request, "urlopen", urlopen):
            self.assertEqual(notion.request("POST", "/data_sources/x/query", {"page_size": 100}), {"ok": True})
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], notion.API + "/data_sources/x/query")
        self.assertEqual(seen["headers"]["notion-version"], "2026-03-11")
        self.assertEqual(seen["headers"]["authorization"], "Bearer test-token")
        self.assertEqual(json.loads(seen["body"]), {"page_size": 100})

    def test_429_waits_for_retry_after_then_succeeds(self):
        replies = [(429, b'{"object": "error", "code": "rate_limited", "message": "slow down"}',
                    {"Retry-After": "2"}),
                   (200, b'{"ok": 1}', {})]
        with mock.patch.object(notion, "_send", side_effect=replies) as send, \
                mock.patch.object(notion.time, "sleep") as sleep:
            self.assertEqual(notion.request("GET", "/pages/x"), {"ok": 1})
        self.assertEqual(send.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_429_gives_up_after_the_last_try(self):
        replies = [(429, b'{"code": "rate_limited", "message": "slow"}', {})] * notion.MAX_TRIES
        with mock.patch.object(notion, "_send", side_effect=replies) as send, \
                mock.patch.object(notion.time, "sleep"):
            with self.assertRaisesRegex(notion.NotionError, "rate_limited"):
                notion.request("GET", "/pages/x")
        self.assertEqual(send.call_count, notion.MAX_TRIES)

    def test_an_error_reply_names_the_code_and_not_the_token(self):
        reply = (400, b'{"object": "error", "code": "validation_error", "message": "body failed validation"}', {})
        with mock.patch.object(notion, "_send", return_value=reply):
            with self.assertRaises(notion.NotionError) as caught:
                notion.request("POST", "/databases", {})
        self.assertIn("validation_error", str(caught.exception))
        self.assertIn("body failed validation", str(caught.exception))
        self.assertNotIn("test-token", str(caught.exception))


class SetupTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeNotion()
        patcher = mock.patch.object(notion, "request", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def existing_database(self, props):
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, no_more([child_block(DB_ID)]))
        self.fake.answer("GET", "/databases/%s" % DB_ID, database_object())
        self.fake.answer("GET", "/data_sources/%s" % DS_ID, {"properties": props})
        self.fake.answer("PATCH", "/data_sources/%s" % DS_ID, {"id": DS_ID})

    def test_fresh_setup_creates_the_database_from_the_contract(self):
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, no_more([]))
        self.fake.answer("POST", "/databases", {"id": DB_ID, "url": DB_URL})
        self.fake.answer("GET", "/databases/%s" % DB_ID, database_object())
        out = notion.setup()
        [create] = [c for c in self.fake.calls if c[:2] == ("POST", "/databases")]
        body = create[2]
        self.assertEqual(body["parent"], {"type": "page_id", "page_id": PARENT})
        self.assertEqual(body["title"], [{"type": "text", "text": {"content": "DOMOVOY shortlist"}}])
        schema = body["initial_data_source"]["properties"]
        self.assertEqual(set(schema), set(notion.PROPS))
        self.assertEqual(schema["Status"], {"select": {"options": [{"name": s} for s in STATUSES]}})
        self.assertEqual(schema["Rent"], {"number": {"format": "koruna"}})
        self.assertEqual(schema["Email"], {"email": {}})
        self.assertEqual([c[:2] for c in self.fake.writes()], [("POST", "/databases")])
        self.assertTrue(out["created"])
        self.assertTrue(out["changed"])
        self.assertEqual(out["data_source_id"], DS_ID)
        self.assertEqual(out["database_url"], DB_URL)
        self.assertEqual(out["conflicts"], [])

    def test_second_run_changes_nothing(self):
        self.existing_database(live())
        out = notion.setup()
        self.assertFalse(out["created"])
        self.assertFalse(out["changed"])
        self.assertEqual(out["data_source_id"], DS_ID)
        self.assertEqual((out["added_properties"], out["added_options"], out["conflicts"]), ([], {}, []))
        self.assertEqual(self.fake.writes(), [])

    def test_fresh_setup_colors_the_interested_options(self):
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, no_more([]))
        self.fake.answer("POST", "/databases", {"id": DB_ID, "url": DB_URL})
        self.fake.answer("GET", "/databases/%s" % DB_ID, database_object())
        notion.setup()
        [create] = [c for c in self.fake.calls if c[:2] == ("POST", "/databases")]
        schema = create[2]["initial_data_source"]["properties"]
        self.assertEqual(schema["Interested?"], {"select": {"options": [{"name": "Yes", "color": "green"},
                                                                        {"name": "No", "color": "red"}]}})
        self.assertEqual(schema["Move-in cost"], {"number": {"format": "koruna"}})
        self.assertNotIn("Upfront", schema)
        self.assertEqual(schema["Move-in note"], {"rich_text": {}})

    def test_live_database_renames_upfront_in_place_then_changes_nothing(self):
        # The live shortlist: Interested? added by hand with its colors, Upfront not yet renamed, no Move-in note.
        props = live(remove=["Move-in note"])
        props["Upfront"] = dict(props.pop("Move-in cost"), id="p-upfront")
        props["Interested?"]["select"]["options"] = [{"id": "y", "name": "Yes", "color": "green"},
                                                     {"id": "n", "name": "No", "color": "red"}]
        self.existing_database(props)
        out = notion.setup()
        self.assertEqual(self.fake.writes(), [("PATCH", "/data_sources/%s" % DS_ID, {"properties": {
            "p-upfront": {"name": "Move-in cost"}, "Move-in note": {"rich_text": {}}}})])
        self.assertEqual(out["renamed_properties"], {"Upfront": "Move-in cost"})
        self.assertEqual(out["added_properties"], ["Move-in note"])
        self.assertEqual((out["added_options"], out["conflicts"]), ({}, []))
        self.assertTrue(out["changed"])
        self.fake.calls.clear()
        self.existing_database(live())
        out = notion.setup()
        self.assertFalse(out["changed"])
        self.assertEqual(out["renamed_properties"], {})
        self.assertEqual(self.fake.writes(), [])

    def test_an_old_name_of_another_type_is_not_renamed(self):
        props = live()
        props["Upfront"] = {"id": "p-upfront", "type": "rich_text", "rich_text": {}}
        del props["Move-in cost"]
        self.existing_database(props)
        out = notion.setup()
        self.assertEqual(self.fake.writes(), [("PATCH", "/data_sources/%s" % DS_ID, {"properties": {
            "Move-in cost": {"number": {"format": "koruna"}}}})])
        self.assertEqual((out["renamed_properties"], out["added_properties"]), ({}, ["Move-in cost"]))

    def test_database_title_from_config_targets_a_separate_database(self):
        e2e = "DOMOVOY shortlist (e2e)"
        # The parent holds the real shortlist only: the e2e database is created next to it, never the real one used.
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, no_more([child_block(DB_ID)]))
        self.fake.answer("POST", "/databases", {"id": "e2e-db", "url": DB_URL})
        self.fake.answer("GET", "/databases/e2e-db", database_object("e2e-db"))
        out = notion.setup({"notion": {"database_title": e2e}})
        [create] = [c for c in self.fake.calls if c[:2] == ("POST", "/databases")]
        self.assertEqual(create[2]["title"], [{"type": "text", "text": {"content": e2e}}])
        self.assertEqual((out["database"], out["database_title_from"]), (e2e, "config notion.database_title"))
        self.assertTrue(out["created"])
        # Default: the contract title, reported as such.
        self.fake.calls.clear()
        self.existing_database(live())
        out = notion.setup({"notion": {}})
        self.assertEqual((out["database"], out["database_title_from"]), ("DOMOVOY shortlist",
                                                                        "contract database_title"))
        self.assertFalse(out["changed"])
        with self.assertRaisesRegex(RuntimeError, "database_title"):
            notion.setup({"notion": {"database_title": " "}})

    def test_a_missing_colored_option_is_added_with_its_color(self):
        props = live()
        props["Interested?"]["select"]["options"] = [{"id": "y", "name": "Yes", "color": "blue"}]
        self.existing_database(props)
        out = notion.setup()
        [(_, _, body)] = self.fake.writes()
        self.assertEqual(body, {"properties": {"Interested?": {"select": {"options": [
            {"id": "y"}, {"name": "No", "color": "red"}]}}}})
        self.assertEqual(out["added_options"], {"Interested?": ["No"]})

    def test_a_missing_property_is_added_alone(self):
        self.existing_database(live(remove=["Owner listing"]))
        out = notion.setup()
        self.assertEqual(self.fake.writes(), [("PATCH", "/data_sources/%s" % DS_ID,
                                               {"properties": {"Owner listing": {"checkbox": {}}}})])
        self.assertEqual(out["added_properties"], ["Owner listing"])
        self.assertTrue(out["changed"])

    def test_a_missing_option_keeps_the_existing_options(self):
        props = live()
        props["Status"]["select"]["options"] = [o for o in props["Status"]["select"]["options"]
                                                if o["name"] != "Viewing booked"]
        self.existing_database(props)
        out = notion.setup()
        [(method, path, body)] = self.fake.writes()
        self.assertEqual((method, path), ("PATCH", "/data_sources/%s" % DS_ID))
        self.assertEqual(list(body["properties"]), ["Status"])
        self.assertEqual(body["properties"]["Status"]["select"]["options"],
                         [{"id": "Status/0"}, {"id": "Status/1"}, {"id": "Status/2"}, {"id": "Status/3"},
                          {"id": "Status/5"}, {"name": "Viewing booked"}])
        self.assertEqual(out["added_options"], {"Status": ["Viewing booked"]})
        self.assertEqual(out["added_properties"], [])

    def test_a_type_conflict_is_refused_and_nothing_is_written(self):
        self.existing_database(live(replace={"Reason": {"id": "p-Reason", "type": "select",
                                                        "select": {"options": []}}}))
        out = notion.setup()
        self.assertEqual(len(out["conflicts"]), 1)
        self.assertIn("Reason is select in Notion", out["conflicts"][0])
        self.assertFalse(out["changed"])
        self.assertEqual(self.fake.writes(), [])

    def test_a_renamed_title_is_a_conflict(self):
        props = live()
        props["Title"] = props.pop("Name")
        self.existing_database(props)
        out = notion.setup()
        self.assertIn("the title property is ['Title'], the contract needs 'Name'", out["conflicts"])
        self.assertEqual(self.fake.writes(), [])

    def test_a_renamed_plain_property_is_added_under_the_contract_name(self):
        props = live()
        props["Property Id"] = props.pop("Property ID")
        self.existing_database(props)
        out = notion.setup()
        self.assertEqual(out["conflicts"], [])
        self.assertEqual(self.fake.writes(), [("PATCH", "/data_sources/%s" % DS_ID,
                                               {"properties": {"Property ID": {"rich_text": {}}}})])

    def test_two_databases_with_the_title_are_refused(self):
        self.fake.answer("GET", "/blocks/%s/children" % PARENT,
                         no_more([child_block(DB_ID), child_block(OTHER_DB_ID)]))
        with self.assertRaisesRegex(RuntimeError, "2 databases"):
            notion.setup()
        self.assertEqual(self.fake.writes(), [])

    def test_other_databases_are_not_taken_for_the_shortlist(self):
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, no_more([child_block(OTHER_DB_ID, "Something else")]))
        self.fake.answer("POST", "/databases", {"id": DB_ID, "url": DB_URL})
        self.fake.answer("GET", "/databases/%s" % DB_ID, database_object())
        self.assertTrue(notion.setup()["created"])

    def test_children_are_read_to_the_end(self):
        first = {"results": [{"id": "ffffffff-0000-4000-8000-000000000006", "type": "paragraph",
                              "paragraph": {"rich_text": []}}],
                 "has_more": True, "next_cursor": "c2"}
        second = no_more([child_block(DB_ID)])
        self.fake.answer("GET", "/blocks/%s/children" % PARENT,
                         lambda body, query: second if query.get("start_cursor") == "c2" else first)
        self.fake.answer("GET", "/databases/%s" % DB_ID, database_object())
        self.fake.answer("GET", "/data_sources/%s" % DS_ID, {"properties": live()})
        out = notion.setup()
        self.assertFalse(out["created"])
        self.assertEqual(out["data_source_id"], DS_ID)

    def test_an_unshared_parent_page_gets_a_hint(self):
        def refused(body, query):
            raise notion.NotionError("Notion GET /blocks/%s/children failed: object_not_found Could not find block."
                                     % PARENT)
        self.fake.answer("GET", "/blocks/%s/children" % PARENT, refused)
        with self.assertRaisesRegex(RuntimeError, "connect the DOMOVOY integration"):
            notion.setup()

    def test_main_prints_json_and_returns_the_exit_code(self):
        self.existing_database(live())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = notion.main(["setup"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["data_source_id"], DS_ID)

        self.existing_database(live(replace={"Reason": {"id": "p-Reason", "type": "select",
                                                        "select": {"options": []}}}))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = notion.main(["setup"])
        self.assertEqual(code, 1)
        self.assertIn("conflicts", json.loads(buffer.getvalue()))

    def test_a_missing_parent_setting_is_an_error_message_not_a_traceback(self):
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NOTION_TOKEN": "test-token"}, clear=True), \
                mock.patch.object(notion, "ENV_FILE", os.path.join(HERE, "no-such.env")), \
                contextlib.redirect_stdout(buffer):
            code = notion.main(["setup"])
        self.assertEqual(code, 1)
        self.assertIn("NOTION_PARENT_PAGE_ID is not set", json.loads(buffer.getvalue())["error"])
        self.assertEqual(self.fake.calls, [])


class BackendTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeNotion()
        patcher = mock.patch.object(notion, "request", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake.answer("POST", "/data_sources/%s/query" % DS_ID, no_more([flat_page()]))
        self.fake.answer("PATCH", "/pages/%s" % PAGE_ID, flat_page())

    def test_list_flats_filters_by_status_and_reads_each_listing(self):
        rows = notion.list_flats(CFG_NOTION, "Interested")
        [query] = [c for c in self.fake.calls if c[1].endswith("/query")]
        self.assertEqual(query[2]["filter"], {"property": "Status", "select": {"equals": "Interested"}})
        self.assertEqual(rows, [{"id": PAGE_ID, "title": "2+kk · SYNTHETIC · Testville", "url": PAGE_URL,
                                 "status": "Interested", "listing": EXPECTED_LISTING}])

    def test_list_flats_without_a_status_has_no_filter(self):
        notion.list_flats(CFG_NOTION)
        query = self.fake.calls[-1][2]
        self.assertNotIn("filter", query)
        self.assertEqual(query["page_size"], 100)

    def test_list_flats_follows_the_cursor(self):
        def answer_query(body, query):
            if body.get("start_cursor") == "c2":
                return no_more([flat_page(OTHER_PAGE_ID)])
            return {"results": [flat_page()], "has_more": True, "next_cursor": "c2"}
        self.fake.answer("POST", "/data_sources/%s/query" % DS_ID, answer_query)
        rows = notion.list_flats(CFG_NOTION, "Interested")
        self.assertEqual([row["id"] for row in rows], [PAGE_ID, OTHER_PAGE_ID])

    def test_the_listing_never_carries_contacts(self):
        listing = notion.list_flats(CFG_NOTION)[0]["listing"]
        text = json.dumps(listing)
        for leaked in ("SYNTHETIC Agency", "SYNTHETIC Person", "synthetic@example.com", "SYNTHETIC-PHONE"):
            self.assertNotIn(leaked, text)
        self.assertEqual(set(listing), set(EXPECTED_LISTING))

    def test_get_flat_reads_the_page_body_with_nested_blocks(self):
        self.fake.answer("GET", "/pages/%s" % PAGE_ID, flat_page())
        self.fake.answer("GET", "/blocks/%s/children" % PAGE_ID, no_more([
            {"id": "f1", "type": "paragraph", "has_children": False,
             "paragraph": {"rich_text": [{"plain_text": "Photos below."}]}},
            {"id": TABLE_ID, "type": "table", "has_children": True, "table": {}},
            {"id": "f2", "type": "image", "has_children": False, "image": {}},
        ]))
        self.fake.answer("GET", "/blocks/%s/children" % TABLE_ID, no_more([
            {"id": "f3", "type": "table_row", "has_children": False,
             "table_row": {"cells": [[{"plain_text": "Rent"}], [{"plain_text": "22000 CZK"}]]}},
        ]))
        flat = notion.get_flat(CFG_NOTION, PAGE_ID)
        self.assertEqual(flat["text"], "Photos below.\nRent | 22000 CZK")
        self.assertEqual(flat["listing"], EXPECTED_LISTING)
        self.assertEqual((flat["id"], flat["url"], flat["title"]),
                         (PAGE_ID, PAGE_URL, "2+kk · SYNTHETIC · Testville"))

    def test_set_status_writes_the_select_and_refuses_unknown_values(self):
        notion.set_status(CFG_NOTION, PAGE_ID, "Calling")
        self.assertEqual(self.fake.writes(), [("PATCH", "/pages/%s" % PAGE_ID,
                                               {"properties": {"Status": {"select": {"name": "Calling"}}}})])
        before = len(self.fake.calls)
        with self.assertRaisesRegex(RuntimeError, "not in the contract"):
            notion.set_status(CFG_NOTION, PAGE_ID, "Maybe later")
        self.assertEqual(len(self.fake.calls), before)

    def test_append_writes_one_paragraph_per_line_in_batches_of_100(self):
        self.fake.answer("PATCH", "/blocks/%s/children" % PAGE_ID, no_more([]))
        text = "\n".join(["line %d" % i for i in range(150)] + ["", "x" * 4500])
        notion.append(CFG_NOTION, PAGE_ID, text)
        writes = self.fake.writes()
        self.assertEqual([len(body["children"]) for _, _, body in writes], [100, 51])
        self.assertEqual({path for _, path, _ in writes}, {"/blocks/%s/children" % PAGE_ID})
        self.assertEqual(writes[0][2]["children"][0]["paragraph"]["rich_text"][0]["text"]["content"], "line 0")
        last = writes[-1][2]["children"][-1]["paragraph"]["rich_text"]
        self.assertEqual([len(part["text"]["content"]) for part in last], [2000, 2000, 500])

    def test_the_viewing_date_needs_a_utc_offset(self):
        self.fake.answer("PATCH", "/pages/%s" % PAGE_ID, flat_page())
        notion.set_viewing_date(CFG_NOTION, PAGE_ID, "2026-11-16T17:00:00+01:00")
        self.assertEqual(self.fake.writes(), [("PATCH", "/pages/%s" % PAGE_ID, {"properties": {
            "Viewing date": {"date": {"start": "2026-11-16T17:00:00+01:00"}}}})])
        with self.assertRaisesRegex(RuntimeError, "UTC offset"):
            notion.set_viewing_date(CFG_NOTION, PAGE_ID, "2026-11-16T17:00:00")

    def test_ids_and_config_are_checked_before_any_call(self):
        with self.assertRaisesRegex(RuntimeError, "not a Notion ID"):
            notion.get_flat(CFG_NOTION, "../databases/x")
        with self.assertRaisesRegex(RuntimeError, "notion.data_source_id"):
            notion.list_flats({}, "Interested")
        self.assertEqual(self.fake.calls, [])


class CallShapeTest(unittest.TestCase):
    """The backend as call.py uses it: shape B, with a listing that builds a valid call_context."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeNotion()
        patcher = mock.patch.object(notion, "request", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake.answer("POST", "/data_sources/%s/query" % DS_ID, no_more([flat_page()]))

    def test_call_py_loads_the_file_as_its_backend(self):
        backend = call.load_backend(dict(CFG_NOTION, backend={"module": "scripts/notion.py"}))
        for name in ("list_flats", "get_flat", "set_status", "append", "set_viewing_date"):
            self.assertTrue(hasattr(backend.module, name), name)

    def test_the_interested_flat_gives_a_valid_call_context(self):
        pages = call.Shortlist(notion).list_pages(CFG_NOTION, "Interested")
        self.assertEqual(pages[0]["notion_page_id"], PAGE_ID)
        context = call.build_context(CFG_NOTION, pages[0], WINDOWS)
        self.assertEqual(context["property_id"], "synthetic-test-001")
        self.assertEqual(context["notion_page_id"], PAGE_ID)
        self.assertEqual(call.validate(context, call.load_schema("call_context")), [])
        self.assertEqual([c for c in self.fake.calls if c[1].startswith("/pages/")], [])


@unittest.skipUnless(os.environ.get("DOMOVOY_LIVE") == "1",
                     "live: set DOMOVOY_LIVE=1 (uses NOTION_TOKEN and NOTION_PARENT_PAGE_ID)")
class LiveNotion(unittest.TestCase):
    def test_setup_twice_then_the_backend_reads_the_database(self):
        first = notion.setup()
        second = notion.setup()
        self.assertEqual(second["data_source_id"], first["data_source_id"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["conflicts"], [])
        config = {"notion": {"data_source_id": first["data_source_id"]}}
        self.assertIsInstance(notion.list_flats(config, "Interested"), list)


if __name__ == "__main__":
    unittest.main()
