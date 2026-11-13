"""WP7 Notion sink tests. Offline by default: every request goes to an httpx.MockTransport fake, and an autouse
fixture refuses socket connects. The live test runs only with DOMOVOY_LIVE=1 and -m live: it creates one page from
the fixture, edits it the way Vladimir and Claude do, upserts again, and archives the page it created."""

import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from domovoy.models import FlatItem, UpsertResult
from domovoy.notion.sink import (
    CREATE_ONLY,
    OWNED_ON_UPDATE,
    NotionError,
    NotionSink,
    SchemaDrift,
    Throttle,
    _error_code,
    body_blocks,
    owned_values,
    schema_problems,
)

TESTS = Path(__file__).resolve().parent
APIFY = TESTS.parent
REPO = APIFY.parent
FIXTURES = TESTS / "fixtures"
SKILL_CONTRACT = REPO / "skill" / "domovoy" / "reference" / "notion_contract.json"
PACKAGE_CONTRACT = APIFY / "domovoy" / "schemas" / "notion_contract.json"
CONTRACT = json.loads(SKILL_CONTRACT.read_text(encoding="utf-8"))
DS = "dddddddd-0000-4000-8000-00000000000d"  # offline fake data source id
PAGE = "cccccccc-0000-4000-8000-00000000000c"
TOKEN = "test-token"
FIXTURE_TITLE = "2+kk · 54 m² · Vinohrady, Example street"


def fixture_item(**changes: Any) -> FlatItem:
    data = json.loads((FIXTURES / "flatitem_example.json").read_text(encoding="utf-8"))
    data.update(changes)
    return FlatItem.model_validate(data)


def live_schema(remove: tuple[str, ...] = (), rename: tuple[str, str] | None = None,
                drop_option: tuple[str, str] | None = None) -> dict[str, Any]:
    """Properties as Notion returns them for a data source that matches the contract, with edits."""
    props: dict[str, Any] = {}
    for i, (name, spec) in enumerate(CONTRACT["properties"].items()):
        kind = spec["type"]
        value: dict[str, Any] = {"id": "p%d" % i, "type": kind, kind: {}}
        if kind in ("select", "multi_select"):
            value[kind] = {"options": [{"id": "%s/%d" % (name, j), "name": option}
                                       for j, option in enumerate(spec.get("options", []))]}
        elif kind == "number":
            value[kind] = {"format": spec.get("format", "number")}
        props[name] = value
    for name in remove:
        props.pop(name)
    if rename:
        props[rename[1]] = props.pop(rename[0])
    if drop_option:
        name, option = drop_option
        options = props[name][props[name]["type"]]["options"]
        props[name][props[name]["type"]]["options"] = [o for o in options if o["name"] != option]
    return props


class FakeNotion:
    """httpx.MockTransport handler. Each (method, path) gets its scripted replies in order, and every request is
    recorded. A reply is a dict (200) or a (status, dict, headers) tuple."""

    def __init__(self) -> None:
        self.replies: dict[tuple[str, str], list[Any]] = {}
        self.sent: list[tuple[str, str, Any]] = []

    def reply(self, method: str, path: str, *replies: Any) -> None:
        self.replies[(method, path)] = list(replies)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        body = json.loads(request.content) if request.content else None
        self.sent.append((request.method, path, body))
        queue = self.replies.get((request.method, path))
        if not queue:
            raise AssertionError("unexpected Notion call: %s %s" % (request.method, path))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        status, payload, headers = (200, item, {}) if isinstance(item, dict) else item
        return httpx.Response(status, json=payload, headers=headers)

    def writes(self) -> list[tuple[str, str, Any]]:
        return [c for c in self.sent if c[0] in ("POST", "PATCH") and not c[1].endswith("/query")]


def no_match_query() -> dict[str, Any]:
    return {"results": [], "has_more": False, "next_cursor": None}


async def run_upsert(fake: FakeNotion, item: FlatItem) -> UpsertResult:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        return await NotionSink(TOKEN, DS, client=client, retry_base=0.0).upsert(item)


async def run_validate(fake: FakeNotion) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
        await NotionSink(TOKEN, DS, client=client, retry_base=0.0).validate()


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("offline test tried to open a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)


# Contract and drift


def test_contract_copy_matches_skill_reference():
    assert PACKAGE_CONTRACT.read_bytes() == SKILL_CONTRACT.read_bytes(), (
        "notion_contract.json drifted from skill/domovoy/reference/; copy it again"
    )


def test_contract_states_the_write_rules_the_sink_relies_on():
    assert CONTRACT["upsert_key"] == "Property ID"
    assert CREATE_ONLY == ["Status"]
    assert {"Status", "Reason", "Notes", "Viewing date"}.isdisjoint(OWNED_ON_UPDATE)
    assert CONTRACT["properties"]["Status"]["options"][0] == "Shortlisted"


def test_every_owned_property_has_a_value_and_nothing_else_does():
    assert set(owned_values(fixture_item())) == set(OWNED_ON_UPDATE)


def test_the_contract_passes_its_own_schema_check():
    assert schema_problems(live_schema()) == []


async def test_validate_accepts_a_matching_database():
    fake = FakeNotion()
    fake.reply("GET", "/data_sources/%s" % DS, {"properties": live_schema()})
    await run_validate(fake)


async def test_validate_refuses_a_renamed_property_before_anything_is_scraped():
    fake = FakeNotion()
    fake.reply("GET", "/data_sources/%s" % DS, {"properties": live_schema(rename=("Rent", "Rent (CZK)"))})
    with pytest.raises(SchemaDrift, match="Rent is missing"):
        await run_validate(fake)


async def test_validate_refuses_a_missing_status_option():
    fake = FakeNotion()
    fake.reply("GET", "/data_sources/%s" % DS, {"properties": live_schema(drop_option=("Status", "Calling"))})
    with pytest.raises(SchemaDrift, match="Status has no option 'Calling'"):
        await run_validate(fake)


def test_schema_problems_name_a_wrong_type():
    props = live_schema()
    props["Reason"] = {"id": "x", "type": "select", "select": {"options": []}}
    assert schema_problems(props) == ["Reason is select (the contract needs rich_text)"]


# Upsert: create, update, refusal


async def test_create_sets_status_cover_and_one_body_in_one_request():
    item = fixture_item(photos=["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"])
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, no_match_query())
    fake.reply("POST", "/pages", {"id": PAGE})
    assert await run_upsert(fake, item) == UpsertResult(page_id=PAGE, action="created")
    [query] = [body for m, p, body in fake.sent if p.endswith("/query")]
    assert query == {"filter": {"property": "Property ID", "rich_text": {"equals": "p-EXAMPLE234"}},
                     "page_size": 2}
    [create] = [body for m, p, body in fake.sent if (m, p) == ("POST", "/pages")]
    assert create["parent"] == {"type": "data_source_id", "data_source_id": DS}
    assert create["properties"]["Status"] == {"select": {"name": "Shortlisted"}}
    assert create["cover"] == {"type": "external", "external": {"url": "https://img.example.com/1.jpg"}}
    assert len(create["children"]) <= 100
    headings = [b["heading_2"]["rich_text"][0]["text"]["content"] for b in create["children"]
                if b["type"] == "heading_2"]
    assert headings == ["Photos", "Why it matches", "Costs", "Quotes", "Unknowns", "Sources"]


async def test_fixture_create_has_no_cover_and_a_body_within_one_request():
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, no_match_query())
    fake.reply("POST", "/pages", {"id": PAGE})
    await run_upsert(fake, fixture_item())
    [create] = [body for m, p, body in fake.sent if (m, p) == ("POST", "/pages")]
    assert "cover" not in create
    assert 0 < len(create["children"]) <= 100


async def test_update_writes_owned_properties_only_and_leaves_the_body_alone():
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, {"results": [{"id": PAGE}], "has_more": False,
                                                       "next_cursor": None})
    fake.reply("PATCH", "/pages/%s" % PAGE, {"id": PAGE})
    assert await run_upsert(fake, fixture_item(rent=25000)) == UpsertResult(page_id=PAGE, action="updated")
    [(method, path, body)] = fake.writes()
    assert (method, path) == ("PATCH", "/pages/%s" % PAGE)
    assert set(body["properties"]) == set(OWNED_ON_UPDATE)
    assert {"Status", "Reason", "Notes", "Viewing date"}.isdisjoint(body["properties"])
    assert "children" not in body and "cover" not in body
    assert body["properties"]["Rent"] == {"number": 25000}


async def test_rejected_flats_never_reach_notion():
    fake = FakeNotion()
    with pytest.raises(ValueError, match="rejected"):
        await run_upsert(fake, fixture_item(match="rejected"))
    assert fake.sent == []


async def test_a_429_waits_for_retry_after_and_then_creates_the_page():
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, no_match_query())
    fake.reply("POST", "/pages", (429, {"code": "rate_limited", "message": "slow down"}, {"Retry-After": "0"}),
               {"id": PAGE})
    assert (await run_upsert(fake, fixture_item())).action == "created"
    assert len([1 for m, p, _ in fake.sent if (m, p) == ("POST", "/pages")]) == 2


async def test_api_errors_name_the_code_but_never_the_message_or_token():
    fake = FakeNotion()
    fake.reply("GET", "/data_sources/%s" % DS, (400, {"code": "validation_error", "message": "bad schema"}, {}))
    with pytest.raises(NotionError) as caught:
        await run_validate(fake)
    error = caught.value
    assert (error.method, error.path, error.status, error.code) == (
        "GET", "/data_sources/%s" % DS, 400, "validation_error")
    assert "validation_error" in str(error)
    assert "bad schema" not in str(error)
    assert TOKEN not in str(error)


async def test_validation_error_echoing_a_contact_stays_out_of_the_exception_and_the_log(caplog):
    """Notion can echo a rejected value in its message. The synthetic contact must reach neither the exception nor
    a log record, even when a caller logs the exception with logger.exception (WP7 review, fix round 1)."""
    email, phone = "synthetic@example.com", "+420 000 000 000"
    echoed = "body.properties.Email.email is not valid: '%s'. Phone '%s' is not valid." % (email, phone)
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, no_match_query())
    fake.reply("POST", "/pages", (400, {"object": "error", "status": 400, "code": "validation_error",
                                        "message": echoed}, {}))
    data = fixture_item().model_dump(mode="json")
    data["sources"][0]["contact"].update(name="Synthetic Agent", email=email, phone=phone)
    item = FlatItem.model_validate(data)
    caplog.set_level(logging.DEBUG)
    try:
        await run_upsert(fake, item)
    except NotionError as error:
        logging.getLogger("domovoy.test.notion_sink").exception("upsert failed for %s", item.property_id)
        caught = error
    else:
        raise AssertionError("a 400 reply must raise NotionError")
    assert (caught.method, caught.path, caught.status, caught.code) == ("POST", "/pages", 400, "validation_error")
    seen = [str(caught), repr(caught), str(vars(caught)), caplog.text, *(r.getMessage() for r in caplog.records)]
    for text in seen:
        assert email not in text and phone not in text


@pytest.mark.parametrize("payload, expected", [
    ({"code": "validation_error", "message": "x"}, "validation_error"),
    ({"code": "Phone synthetic@example.com"}, "unknown"),
    ({"message": "no code here"}, "unknown"),
])
def test_error_code_is_read_only_when_it_is_a_plain_slug(payload, expected):
    assert _error_code(httpx.Response(400, json=payload)) == expected


def test_a_non_json_error_reply_gives_an_unknown_code():
    assert _error_code(httpx.Response(502, content=b"<html>synthetic@example.com</html>")) == "unknown"


async def test_throttle_spaces_requests():
    throttle = Throttle(rate=50)
    start = time.monotonic()
    for _ in range(3):
        await throttle.wait()
    assert time.monotonic() - start >= 0.035


# Field mapping and the page body


def text_of(value: dict[str, Any]) -> str:
    return "".join(part["text"]["content"] for part in value.get("title", value.get("rich_text", [])))


def test_name_reads_like_the_actor_md_example():
    assert text_of(owned_values(fixture_item())["Name"]) == FIXTURE_TITLE


def test_unknowns_are_one_line_each_and_long_text_is_split_into_parts():
    item = fixture_item(unknowns=["Energy included?", "x" * 2500])
    value = owned_values(item)["Unknowns"]["rich_text"]
    assert [len(part["text"]["content"]) for part in value] == [2000, 517]
    assert text_of(owned_values(item)["Unknowns"]).split("\n") == ["Energy included?", "x" * 2500]


def test_the_body_keeps_contacts_out_and_scrubs_quotes():
    item = fixture_item(evidence=[{"field": "rent", "quote": "Call +420 777 123 456 or write to jan@example.com",
                                   "confidence": 0.9}])
    text = json.dumps(body_blocks(item), ensure_ascii=False)
    assert "<phone>" in text and "<email>" in text
    for leaked in ("777 123 456", "jan@example.com", "Example Agent"):
        assert leaked not in text


def test_the_cost_table_marks_estimates_and_unknowns():
    def rows(item: FlatItem) -> dict[str, str]:
        table = next(b for b in body_blocks(item) if b["type"] == "table")["table"]
        return {r["table_row"]["cells"][0][0]["text"]["content"]: r["table_row"]["cells"][1][0]["text"]["content"]
                for r in table["children"]}

    shown = rows(fixture_item())
    assert shown["Energy"] == "1,500 CZK (est.)"
    assert shown["Total monthly"] == "27,500 CZK (est.)"
    assert shown["Services"] == "2,000 CZK"
    assert shown["Upfront"] == "52,000 CZK"
    assert rows(fixture_item(energy=None))["Energy"] == "unknown"


@pytest.mark.parametrize(
    "changes, name, expected",
    [
        ({"elevator": True}, "Elevator", "Yes"),
        ({"elevator": None}, "Elevator", "Unknown"),
        ({"furnished": "partial"}, "Furnished", "Partly"),
        ({"furnished": None}, "Furnished", "Unknown"),
        ({"lease_type": "podnajem"}, "Lease type", "Sublet"),
        ({"lease_type": None}, "Lease type", "Unknown"),
        ({"match": "strong"}, "Match", "Strong"),
        ({"match": "needs_info"}, "Match", "Needs info"),
    ],
)
def test_select_values_follow_the_contract_names(changes, name, expected):
    assert owned_values(fixture_item(**changes))[name]["select"]["name"] == expected


def test_multi_select_names_hold_no_commas():
    values = owned_values(fixture_item(risk_flags=["fees not stated, short lease"]))
    assert values["Risk flags"] == {"multi_select": [{"name": "fees not stated; short lease"}]}


# Live: one page from the fixture, edited the way Vladimir and Claude edit it, then archived


def _secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env = Path("~/.config/domovoy/.env").expanduser()
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, found = line.partition("=")
            if sep and key.strip().removeprefix("export ").strip() == name:
                return found.strip().strip("'\"") or None
    return None


def _plain(prop: dict[str, Any]) -> str:
    return "".join(part["plain_text"] for part in prop.get("rich_text", prop.get("title", [])))


async def _call(sink: NotionSink, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await sink._request(method, path, body)


async def _body(sink: NotionSink, page_id: str) -> list[tuple[str, str, str]]:
    blocks = (await _call(sink, "GET", "/blocks/%s/children?page_size=100" % page_id))["results"]
    return [(b["id"], b["type"], json.dumps(b.get(b["type"]), sort_keys=True)) for b in blocks]


@pytest.mark.live
async def test_live_create_edit_upsert_and_archive_the_fixture_page():
    token = _secret("NOTION_TOKEN")
    data_source = _secret("DOMOVOY_NOTION_DATA_SOURCE_ID")
    if os.environ.get("DOMOVOY_LIVE") != "1" or not token or not data_source:
        pytest.skip("live: set DOMOVOY_LIVE=1, NOTION_TOKEN (env or ~/.config/domovoy/.env) and "
                    "DOMOVOY_NOTION_DATA_SOURCE_ID")
    fixture = fixture_item()
    pid = None
    identity_ok = False
    async with NotionSink(token, data_source) as sink:
        await sink.validate()
        try:
            created = await sink.upsert(fixture)
            pid = created.page_id
            assert created.action == "created"
            props = (await _call(sink, "GET", "/pages/%s" % pid))["properties"]
            assert _plain(props["Property ID"]) == "p-EXAMPLE234"
            assert _plain(props["Name"]) == FIXTURE_TITLE
            assert props["Status"]["select"]["name"] == "Shortlisted"
            assert _plain(props["Unknowns"]) == "Are energy costs included in the rent?"
            identity_ok = True

            # Vladimir and Claude edit the page: a rejection with a reason, a viewing date, a note in the body.
            await _call(sink, "PATCH", "/pages/%s" % pid, {"properties": {
                "Status": {"select": {"name": "Not interested"}},
                "Reason": {"rich_text": [{"type": "text", "text": {"content": "wp7 live check"}}]},
                "Viewing date": {"date": {"start": "2026-11-16T17:00:00+01:00"}},
            }})
            note = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
                {"type": "text", "text": {"content": "wp7 live check: call summary placeholder"}}]}}
            await _call(sink, "PATCH", "/blocks/%s/children" % pid, {"children": [note]})
            body_before = await _body(sink, pid)

            changed = FlatItem.model_validate({
                **fixture.model_dump(mode="json"),
                "rent": 25000,
                "total_monthly": 28500,
                "unknowns": ["Are energy costs included in the rent?", "Is a parking space included?"],
            })
            assert await sink.upsert(changed) == UpsertResult(page_id=pid, action="updated")

            props = (await _call(sink, "GET", "/pages/%s" % pid))["properties"]
            assert props["Rent"]["number"] == 25000
            assert props["Status"]["select"]["name"] == "Not interested"
            assert _plain(props["Reason"]) == "wp7 live check"
            raw_unknowns = _plain(props["Unknowns"])
            assert "\n" in raw_unknowns
            assert raw_unknowns.split("\n") == changed.unknowns
            start = props["Viewing date"]["date"]["start"]
            assert datetime.fromisoformat(start) == datetime.fromisoformat("2026-11-16T17:00:00+01:00"), start
            assert await _body(sink, pid) == body_before
        finally:
            if pid is not None and identity_ok:
                await _call(sink, "PATCH", "/pages/%s" % pid, {"in_trash": True})
    if pid is not None and identity_ok:
        async with NotionSink(token, data_source) as sink:
            archived = await _call(sink, "GET", "/pages/%s" % pid)
            assert archived["in_trash"] is True


async def test_concurrent_upserts_share_one_throttle():
    """The pipeline runs one task per flat on one sink: the run stays at `rate` requests per second in total."""
    stamps: list[float] = []
    fake = FakeNotion()
    fake.reply("POST", "/data_sources/%s/query" % DS, no_match_query())
    fake.reply("POST", "/pages", {"id": PAGE})

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return fake(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sink = NotionSink(TOKEN, DS, client=client, rate=20, retry_base=0.0)
        await asyncio.gather(*(sink.upsert(fixture_item(property_id="p-%d" % i)) for i in range(3)))
    assert len(stamps) == 6
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= 0.04


async def test_a_429_pauses_every_caller_of_the_throttle():
    throttle = Throttle(rate=1000)
    throttle.pause(0.05)
    start = time.monotonic()
    await throttle.wait()
    assert time.monotonic() - start >= 0.04
