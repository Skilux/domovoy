"""Offline tests of the e2e checks: each check passes on good data and fires on a planted defect.

Run: cd apify && .venv/bin/python -m pytest -q e2e/test_checks.py
"""

import copy
import json
from pathlib import Path

import checks

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "flatitem_example.json"


def item(**changes):
    value = json.loads(FIXTURE.read_text())
    value.update(changes)
    return value


def ids(found):
    return sorted({f["check_id"] for f in found})


def test_good_item_passes():
    assert checks.check_items([item()], "run1") == []


def test_money_float_zero_and_time_without_offset_fire():
    found = checks.check_items([item(rent=25000.5), item(total_monthly=0), item(collected_at="2026-11-13T10:00:00")],
                               "run1")
    assert ids(found) == ["L3.flatitem_schema", "L3.money_int", "L3.time_offset"]
    assert {f["severity"] for f in found if f["check_id"] == "L3.money_int"} == {"blocker", "major"}


def test_zero_services_needs_evidence():
    bare = item(services=0, evidence=[])
    assert ids(checks.check_items([bare], "r")) == ["L3.money_int"]
    stated = item(services=0, evidence=[{"field": "services", "quote": "no fees", "confidence": 0.9}])
    assert checks.check_items([stated], "r") == []


def test_empty_dataset_schema_is_minor():
    found = checks.check_items([], "r", {"actorSpecification": 1, "fields": {}})
    assert [(f["check_id"], f["severity"], f["owner_wp"]) for f in found] == [("L3.dataset_schema", "minor", "WP8")]


def test_quotes_must_be_in_the_refetched_text():
    good = item(evidence=[{"field": "rent", "quote": "Nájem  25 000 Kč", "confidence": 0.9}])
    assert checks.check_quotes(good, ["… Nájem 25 000 Kč měsíčně"], "r") == []
    assert ids(checks.check_quotes(good, ["something else"], "r")) == ["L3.quotes_verified"]
    assert checks.check_quotes(good, None, "r") == []
    two = item(evidence=[{"field": "rent", "quote": "Nájem 25 000 Kč", "confidence": 0.9},
                         {"field": "kauce", "quote": "kauce 50 000 Kč", "confidence": 0.9}])
    assert [f["severity"] for f in checks.check_quotes(two, ["Nájem 25 000 Kč"], "r")] == ["major"]
    assert [f["severity"] for f in checks.check_quotes(two, ["edited text"], "r")] == ["minor"]
    assert checks.scan_text("/opt/homebrew/Cellar/python@3.15/lib", [], []) == []


def flat(pid, portal, street="Korunní", number="12", area=55.0, rent=25000):
    value = item(property_id=pid, area_m2=area, rent=rent)
    value["address_detail"] = dict(value["address_detail"], street=street, house_number=number)
    value["sources"] = [dict(value["sources"][0], portal=portal)]
    return value


def test_missed_dedup_fires_only_across_portals_within_tolerance():
    assert ids(checks.check_dedup([flat("p-a", "sreality"), flat("p-b", "idnes", area=57.0, rent=26000)], "r")) == [
        "L3.dedup_missed"]
    assert checks.check_dedup([flat("p-a", "sreality"), flat("p-b", "sreality")], "r") == []
    assert checks.check_dedup([flat("p-a", "sreality"), flat("p-b", "idnes", rent=30000)], "r") == []
    assert checks.check_dedup([flat("p-a", "sreality"), flat("p-b", "idnes", number="14")], "r") == []


def page_for(it, page_id="pg1", status="Shortlisted", **props):
    base = {"Rent": it["rent"], "Total monthly": it["total_monthly"], "Kauce": it["kauce"],
            "Commission": it["commission"], "Upfront": checks.item_move_in(it), "Missing furniture cost": it["missing_furniture_cost"],
            "URL": it["url"], "Match": {"strong": "Strong", "needs_info": "Needs info"}.get(it["match"]),
            "Unknowns": "\n".join(it["unknowns"]) or None}
    base.update(props)
    return {"page_id": page_id, "property_id": it["property_id"], "status": status, "interested": None,
            "reason": None, "props": base, "body": "Costs\nRent | 25,000 CZK"}


def test_pages_pass_and_fire():
    it = item(change="new", match="strong")
    page = page_for(it)
    summary = {"match": {"strong": 1, "needs_info": 0, "rejected": 0}, "change": {"new": 1, "changed": 0, "unchanged": 0},
               "notion": {"created": 1, "updated": 0, "errors": 0}}
    assert checks.check_pages([page], [it], set(), "r", summary) == []
    dup = dict(page_for(it, "pg2"))
    wrong = page_for(it, status="Interested", Rent=1)
    found = checks.check_pages([wrong, dup], [it], set(), "r", summary)
    assert ids(found) == ["L3.new_page_shortlisted", "L3.one_page_per_property"]
    found = checks.check_pages([wrong], [it], {"pg1"}, "r", summary)
    assert ids(found) == ["L3.page_matches_item"]
    assert ids(checks.check_pages([], [it], set(), "r", summary)) == ["L3.item_has_page"]


def test_move_in_cost_is_read_after_contract2():
    it = item(change="new", match="strong")
    it["move_in_cost"] = it.pop("upfront")
    page = page_for(it)
    page["props"]["Move-in cost"] = page["props"].pop("Upfront")
    assert checks.compare_page(it, page, "r") == []


def test_counts_with_and_without_include_unchanged():
    items = [item(change="unchanged", match="strong"), item(change="new", match="rejected")]
    summary = {"match": {"strong": 1, "needs_info": 0, "rejected": 1}, "change": {"new": 1, "changed": 0, "unchanged": 1},
               "notion": {"created": 0, "updated": 1, "errors": 0}}
    assert checks.check_counts(items, summary, "r", include_unchanged=True) == []
    assert ids(checks.check_counts(items, summary, "r", include_unchanged=False)) == ["L3.summary_counts"]


def test_idempotency():
    it = item()
    before = [page_for(it)]
    before[0].update(status="Not interested", reason="e2e", body="x\ne2e-marker r1 abc")
    edited = {"page_id": "pg1", "status": "Not interested", "reason": "e2e", "marker": "e2e-marker r1 abc"}
    summary = {"notion": {"created": 0}, "change": {"new": 0, "changed": 0, "unchanged": 1}}
    assert checks.check_idempotency(before, copy.deepcopy(before), summary, [it], [], edited, "r") == []
    after = copy.deepcopy(before)
    after[0].update(status="Shortlisted", body="x")
    after.append(page_for(it, "pg9"))
    found = checks.check_idempotency(before, after, summary, [it], [dict(it, change="new")], edited, "r")
    assert ids(found) == ["L4.edits_kept", "L4.no_new_pages", "L4.unchanged_reported"]


def test_call_context():
    it = item()
    page = page_for(it)
    context = {"property_id": it["property_id"], "rent": it["rent"], "total_monthly": it["total_monthly"],
               "upfront": it["upfront"], "unknowns": it["unknowns"], "budget_cap": 30000}
    assert checks.check_call_context(context, page, 30000, []) == []
    found = checks.check_call_context(dict(context, rent=1, budget_cap=1), page, 30000, ["$.x: missing"])
    assert ids(found) == ["L5.budget_cap", "L5.context_matches_page", "L5.context_schema"]


def test_scan_and_scrub_never_echo_contacts():
    phone = " ".join(["+420", "777", "123", "456"])  # built at run time, so this file holds no phone number
    text = "call %s or %s, see https://www.sreality.cz/detail/270794828" % (phone, "jan.novak" + "@" + "agency.cz")
    assert checks.scan_text(text, [], []) == ["email", "phone"]
    assert checks.scan_text("price 25 000 Kč, id 270794828, run U6wPhiVWKvrc0OsXq", [], []) == []
    assert checks.scan_text("token sk-abcdefgh123", ["sk-abcdefgh123"], []) == ["secret"]
    scrubbed = checks.scrub(text)
    assert "777" not in scrubbed and "novak" not in scrubbed and "270794828" in scrubbed


def test_owner_mapping():
    assert checks.owner_of("apify/domovoy/sources/idnes.py") == "WP3"
    assert checks.owner_of("skill/domovoy/scripts/notion.py") == "WP7"
    assert checks.owner_of("skill/domovoy/scripts/call.py") == "Danila"
    assert checks.owner_of("apify/domovoy/pipeline.py") == "WP8"
