"""DOMOVOY e2e checks (issue #68). Pure functions over run summaries, dataset items and Notion pages.

Each check returns a list of findings; an empty list means it passed. A finding follows the issue #68 format:
{check_id, layer, severity, summary, evidence: {run_id, property_id, notion_page_id, log_excerpt}, suspected_path,
owner_wp, repro}. The runner adds the id. Evidence never carries realtor names, phones or emails: every excerpt goes
through scrub(), and checks quote only property ids, page ids, field names and amounts.

Pages are simplified by run_e2e.simple_page(): {"page_id", "property_id", "status", "interested", "reason",
"props": {name: plain value}, "body": str | None}.
"""

import json
import re
import unicodedata
from datetime import datetime
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
# Czech numbers as people write them: +420/00420 prefixed, or grouped in threes ("ddd ddd ddd"). A bare 9-digit run is not
# matched: Sreality ids and prices look the same. The exact contact strings seen in the datasets are checked too.
PHONE = re.compile(r"(?<![\w/.=-])(?:(?:\+|00)420[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}|[1-9]\d{2}[ -]\d{3}[ -]\d{3})(?![\w/-])")
URL = re.compile(r"https?://\S+")
ISO_OFFSET = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)$")
MONEY_FIELDS = ("rent", "services", "energy", "total_monthly", "kauce", "commission", "one_time_fees",
                "first_payment", "upfront", "move_in_cost", "missing_furniture_cost")
# A 0 here can only mean "unknown became 0": these are never legitimately zero for a listed rental.
NEVER_ZERO = ("rent", "total_monthly", "first_payment", "upfront", "move_in_cost")
# A 0 here is legitimate only when the listing states it (an evidence entry for the field).
ZERO_NEEDS_EVIDENCE = {"services": "services", "energy": "energy", "kauce": "kauce", "one_time_fees": "one_time_fees"}
TIME_FIELDS = ("collected_at", "first_seen", "last_seen")
AREA_TOLERANCE_M2 = 3.0
RENT_TOLERANCE = 0.05
OWNERS = [
    ("apify/domovoy/sources/sreality", "WP1"),
    ("apify/domovoy/sources/bezrealitky", "WP2"),
    ("apify/domovoy/sources/idnes", "WP3"),
    ("apify/domovoy/sources/", "WP1-3"),
    ("apify/domovoy/extraction/", "WP4"),
    ("apify/domovoy/costs/", "WP5"),
    ("apify/domovoy/dedup/", "WP6"),
    ("apify/domovoy/notion/", "WP7"),
    ("skill/domovoy/scripts/notion.py", "WP7"),
    ("skill/domovoy/scripts/call.py", "Danila"),
    ("phone/", "Danila"),
    ("apify/", "WP8"),
    ("skill/domovoy/scripts/search.py", "WP8"),
]
PORTAL_PATH = {"sreality": "apify/domovoy/sources/sreality.py", "bezrealitky": "apify/domovoy/sources/bezrealitky.py",
               "idnes": "apify/domovoy/sources/idnes.py"}


def owner_of(path: str) -> str:
    for prefix, owner in OWNERS:
        if path.startswith(prefix):
            return owner
    return "WP8"


def scrub(text: Any, limit: int = 400) -> str:
    """No contacts in evidence: emails and phone numbers are replaced, URLs kept."""
    text = str(text)
    text = EMAIL.sub("<email>", text)
    urls = URL.findall(text)
    text = PHONE.sub("<phone>", URL.sub("\x00", text))
    for url in urls:
        text = text.replace("\x00", url, 1)
    return text[:limit]


def finding(check_id: str, severity: str, summary: str, path: str, repro: str, *, run_id: str | None = None,
            property_id: str | None = None, page_id: str | None = None, excerpt: str | None = None) -> dict:
    return {
        "check_id": check_id,
        "layer": check_id.split(".")[0],
        "severity": severity,
        "summary": scrub(summary),
        "evidence": {"run_id": run_id, "property_id": property_id, "notion_page_id": page_id,
                     "log_excerpt": scrub(excerpt) if excerpt else None},
        "suspected_path": path,
        "owner_wp": owner_of(path),
        "repro": repro,
    }


def rerun(check_id: str) -> str:
    return "apify/.venv/bin/python apify/e2e/run_e2e.py --round <N> --only %s" % check_id


# L1 / L2: run summary


def check_run(layer: str, *, run_id: str | None, ok: bool, how: str, elapsed: float, budget: float,
              summary: dict | None, readable: dict | None = None) -> list[dict]:
    """ok: exit 0 (L1) or SUCCEEDED (L2). readable: search.py's printed object (L2 only)."""
    out = []
    end_id = "%s.exit_zero" % layer if layer == "L1" else "L2.run_succeeded"
    path = "apify/domovoy/main.py" if layer == "L1" else "skill/domovoy/scripts/search.py"
    if not ok:
        out.append(finding(end_id, "blocker", "the run did not end cleanly: %s" % how, path, rerun(end_id),
                           run_id=run_id, excerpt=how))
    if elapsed > budget:
        out.append(finding("%s.time_budget" % layer, "major", "the run took %d s, budget %d s" % (elapsed, budget),
                           "apify/domovoy/pipeline.py", rerun("%s.time_budget" % layer), run_id=run_id))
    if readable is not None:
        missing = readable.get("missing_summary_fields")
        if "summary" not in readable or missing:
            out.append(finding("L2.summary_readable", "major", "search.py printed no complete summary; missing: %s"
                               % missing, "skill/domovoy/scripts/search.py", rerun("L2.summary_readable"),
                               run_id=run_id, excerpt=json.dumps(readable)[:300]))
    if summary is None:
        if ok:
            out.append(finding("%s.summary_valid" % layer, "blocker", "no OUTPUT RunSummary",
                               "apify/domovoy/main.py", rerun("%s.summary_valid" % layer), run_id=run_id))
        return out
    try:
        from domovoy.models import RunSummary
        RunSummary.model_validate(summary)
    except Exception as e:  # pydantic ValidationError or import error
        out.append(finding("%s.summary_valid" % layer, "blocker", "OUTPUT is not a valid RunSummary",
                           "apify/domovoy/models.py", rerun("%s.summary_valid" % layer), run_id=run_id,
                           excerpt=str(e)[:300]))
    for source in summary.get("sources") or []:
        portal = source.get("portal")
        path = PORTAL_PATH.get(portal, "apify/domovoy/sources/")
        cid = "%s.sources_ok" % layer
        if source.get("status") == "ok" and (source.get("found") or 0) > 0:
            continue
        if source.get("status") == "ok":
            out.append(finding(cid, "major", "%s: ok but found 0 listings" % portal, path, rerun(cid),
                               run_id=run_id, excerpt=json.dumps(source)))
        elif source.get("error"):
            sev = "major" if source.get("status") == "failed" else "minor"
            out.append(finding(cid, sev, "%s: %s with a named error" % (portal, source.get("status")), path,
                               rerun(cid), run_id=run_id, excerpt=json.dumps(source)))
        else:
            out.append(finding(cid, "major", "%s: %s without a named error" % (portal, source.get("status")), path,
                               rerun(cid), run_id=run_id, excerpt=json.dumps(source)))
    errors = (summary.get("notion") or {}).get("errors") or 0
    if errors:
        out.append(finding("%s.notion_errors" % layer, "blocker", "%d Notion write(s) failed" % errors,
                           "apify/domovoy/notion/sink.py", rerun("%s.notion_errors" % layer), run_id=run_id))
    return out


# L3: dataset items


def _money_ok(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _iso_offset(value: Any) -> bool:
    if not isinstance(value, str) or not ISO_OFFSET.match(value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def check_items(items: list[dict], run_id: str | None, dataset_schema: dict | None = None) -> list[dict]:
    out: list[dict] = []
    try:
        from domovoy.models import FlatItem
    except Exception:  # run without the apify venv: the schema check is skipped, everything else runs
        FlatItem = None
    if dataset_schema is not None and not (dataset_schema.get("fields") or {}):
        out.append(finding("L3.dataset_schema", "minor", "apify/.actor/dataset_schema.json is an empty placeholder; "
                           "items can only be checked against the FlatItem model", "apify/.actor/dataset_schema.json",
                           rerun("L3.dataset_schema"), run_id=run_id))
    for item in items:
        pid = item.get("property_id")
        if FlatItem is not None:
            try:
                FlatItem.model_validate(item)
            except Exception as e:
                out.append(finding("L3.flatitem_schema", "blocker", "dataset item is not a valid FlatItem",
                                   "apify/domovoy/assemble.py", rerun("L3.flatitem_schema"), run_id=run_id,
                                   property_id=pid, excerpt=str(e)[:300]))
        evidence_fields = {e.get("field") for e in item.get("evidence") or [] if isinstance(e, dict)}
        for field in MONEY_FIELDS:
            if field not in item:
                continue
            value = item[field]
            if not _money_ok(value):
                out.append(finding("L3.money_int", "blocker", "%s is %r, not an integer CZK or null" % (field, value),
                                   "apify/domovoy/costs/compute.py", rerun("L3.money_int"), run_id=run_id,
                                   property_id=pid))
            elif value == 0 and field in NEVER_ZERO:
                out.append(finding("L3.money_int", "major", "%s is 0: unknown must be null" % field,
                                   "apify/domovoy/costs/compute.py", rerun("L3.money_int"), run_id=run_id,
                                   property_id=pid))
            elif value == 0 and field in ZERO_NEEDS_EVIDENCE and ZERO_NEEDS_EVIDENCE[field] not in evidence_fields:
                out.append(finding("L3.money_int", "major", "%s is 0 with no evidence that the listing says so" % field,
                                   "apify/domovoy/costs/compute.py", rerun("L3.money_int"), run_id=run_id,
                                   property_id=pid))
        if item.get("missing_furniture_cost") == 0 and item.get("missing_furniture"):
            out.append(finding("L3.money_int", "major", "missing_furniture_cost is 0 while furniture is missing",
                               "apify/domovoy/costs/compute.py", rerun("L3.money_int"), run_id=run_id,
                               property_id=pid))
        for source in item.get("sources") or []:
            for field in ("rent", "commission"):
                if not _money_ok(source.get(field)):
                    out.append(finding("L3.money_int", "blocker", "sources[].%s is not an integer CZK or null" % field,
                                       "apify/domovoy/assemble.py", rerun("L3.money_int"), run_id=run_id,
                                       property_id=pid))
        times = [(f, item.get(f)) for f in TIME_FIELDS]
        times += [("sources[].collected_at", s.get("collected_at")) for s in item.get("sources") or []]
        for field, value in times:
            if not _iso_offset(value):
                out.append(finding("L3.time_offset", "blocker", "%s is %r, not ISO 8601 with offset" % (field, value),
                                   "apify/domovoy/assemble.py", rerun("L3.time_offset"), run_id=run_id,
                                   property_id=pid))
        if not (isinstance(item.get("url"), str) and item["url"].startswith("http")) or not item.get("collected_at"):
            out.append(finding("L3.url_collected", "blocker", "item lacks url or collected_at",
                               "apify/domovoy/assemble.py", rerun("L3.url_collected"), run_id=run_id,
                               property_id=pid))
    return out


def normalize_ws(text: str) -> str:
    return " ".join((text or "").split())


def check_quotes(item: dict, source_texts: list[str] | None, run_id: str | None) -> list[dict]:
    """Every evidence quote must be a substring of the listing's text (whitespace-normalized), as re-fetched.
    source_texts None means the listing could not be re-fetched: not a finding, reported as skipped by the runner."""
    if source_texts is None:
        return []
    haystack = [normalize_ws(t) for t in source_texts]
    quoted = [e for e in item.get("evidence") or [] if normalize_ws(e.get("quote") or "")]
    missing = [e for e in quoted if not any(normalize_ws(e["quote"]) in text for text in haystack)]
    if not missing:
        return []
    pid = item.get("property_id")
    if len(missing) == len(quoted) and len(quoted) > 1:  # nothing matches: the listing was most likely edited
        return [finding("L3.quotes_verified", "minor", "none of the %d quotes is in the listing as re-fetched: the "
                        "listing was probably edited after the run" % len(quoted), "apify/domovoy/extraction/extract.py",
                        rerun("L3.quotes_verified"), run_id=run_id, property_id=pid)]
    return [finding("L3.quotes_verified", "major", "the quote for %s is not in the listing text as re-fetched (other "
                    "quotes of the item are)" % e.get("field"), "apify/domovoy/extraction/extract.py",
                    rerun("L3.quotes_verified"), run_id=run_id, property_id=pid) for e in missing]


# L3: dedup across items


def _fold(text: str | None) -> str | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\bul(ice)?\.?\s", " ", text)
    return " ".join(re.findall(r"[0-9a-z]+", text)) or None


def check_dedup(items: list[dict], run_id: str | None) -> list[dict]:
    """Two flats with the same street and house number, area within 3 m² and rent within 5 %, on different portals,
    should have been merged into one property_id."""
    latest: dict[str, dict] = {}
    for item in items:
        latest[item["property_id"]] = item
    flats = list(latest.values())
    out = []
    for i, a in enumerate(flats):
        for b in flats[i + 1:]:
            da, db = a.get("address_detail") or {}, b.get("address_detail") or {}
            street_a, street_b = _fold(da.get("street")), _fold(db.get("street"))
            if not street_a or street_a != street_b:
                continue
            if not da.get("house_number") or _fold(da.get("house_number")) != _fold(db.get("house_number")):
                continue
            if a.get("disposition") != b.get("disposition"):
                continue
            if a.get("area_m2") is None or b.get("area_m2") is None or abs(a["area_m2"] - b["area_m2"]) > AREA_TOLERANCE_M2:
                continue
            if a.get("rent") is None or b.get("rent") is None:
                continue
            if abs(a["rent"] - b["rent"]) > RENT_TOLERANCE * max(a["rent"], b["rent"]):
                continue
            portals_a = {s.get("portal") for s in a.get("sources") or []}
            portals_b = {s.get("portal") for s in b.get("sources") or []}
            if portals_a & portals_b:
                continue
            out.append(finding("L3.dedup_missed", "major",
                               "%s and %s look like one flat (same street and number, area and rent within "
                               "tolerance) but were not merged" % (a["property_id"], b["property_id"]),
                               "apify/domovoy/dedup/matcher.py", rerun("L3.dedup_missed"), run_id=run_id,
                               property_id=a["property_id"], excerpt="other property_id %s" % b["property_id"]))
    return out


# L3: Notion pages against the dataset


def move_in_name(props: dict) -> str:
    return "Move-in cost" if "Move-in cost" in props else "Upfront"


def item_move_in(item: dict) -> Any:
    return item["move_in_cost"] if "move_in_cost" in item else item.get("upfront")


def check_pages(pages: list[dict], items: list[dict], before_ids: set[str], run_id: str | None,
                summary: dict | None = None, include_unchanged: bool = False) -> list[dict]:
    """pages: the whole e2e database after the run. items: the run's dataset. before_ids: page ids that existed
    before the round started (pages not in it were created by this round)."""
    out = []
    by_pid: dict[str, list[dict]] = {}
    for page in pages:
        by_pid.setdefault(page.get("property_id") or "", []).append(page)
    for pid, group in by_pid.items():
        if not pid:
            out.extend(finding("L3.one_page_per_property", "major", "page without a Property ID",
                               "apify/domovoy/notion/sink.py", rerun("L3.one_page_per_property"), run_id=run_id,
                               page_id=p["page_id"]) for p in group)
        elif len(group) > 1:
            out.append(finding("L3.one_page_per_property", "blocker", "%d pages share Property ID %s" % (len(group), pid),
                               "apify/domovoy/notion/sink.py", rerun("L3.one_page_per_property"), run_id=run_id,
                               property_id=pid, page_id=",".join(p["page_id"] for p in group)))
    for page in pages:
        if page["page_id"] in before_ids:
            continue
        if page.get("status") != "Shortlisted":
            out.append(finding("L3.new_page_shortlisted", "blocker", "a page created this round has Status %r"
                               % page.get("status"), "apify/domovoy/notion/sink.py", rerun("L3.new_page_shortlisted"),
                               run_id=run_id, property_id=page.get("property_id"), page_id=page["page_id"]))
        if page.get("interested"):
            out.append(finding("L3.new_page_shortlisted", "major", "a page created this round has Interested? set",
                               "apify/domovoy/notion/sink.py", rerun("L3.new_page_shortlisted"), run_id=run_id,
                               property_id=page.get("property_id"), page_id=page["page_id"]))
        if page.get("body") is not None and not page["body"].strip():
            out.append(finding("L3.page_body", "major", "a page created this round has an empty body",
                               "apify/domovoy/notion/sink.py", rerun("L3.page_body"), run_id=run_id,
                               property_id=page.get("property_id"), page_id=page["page_id"]))
    for item in items:
        pid = item["property_id"]
        delivered = item.get("change") in ("new", "changed") or include_unchanged
        group = by_pid.get(pid) or []
        if item.get("match") == "rejected":
            created = [p for p in group if p["page_id"] not in before_ids]
            if created:
                out.append(finding("L3.item_has_page", "major", "a rejected flat got a new page",
                                   "apify/domovoy/pipeline.py", rerun("L3.item_has_page"), run_id=run_id,
                                   property_id=pid, page_id=created[0]["page_id"]))
            continue
        if delivered and not group:
            out.append(finding("L3.item_has_page", "blocker", "a delivered, non-rejected flat has no Notion page",
                               "apify/domovoy/notion/sink.py", rerun("L3.item_has_page"), run_id=run_id,
                               property_id=pid))
        if delivered and len(group) == 1:
            out += compare_page(item, group[0], run_id)
    if summary is not None:
        out += check_counts(items, summary, run_id, include_unchanged)
    return out


def compare_page(item: dict, page: dict, run_id: str | None) -> list[dict]:
    props = page.get("props") or {}
    expected = {
        "Rent": item.get("rent"), "Total monthly": item.get("total_monthly"), "Kauce": item.get("kauce"),
        "Commission": item.get("commission"), move_in_name(props): item_move_in(item),
        "Missing furniture cost": item.get("missing_furniture_cost"), "URL": item.get("url"),
        "Match": {"strong": "Strong", "needs_info": "Needs info"}.get(item.get("match")),
        "Unknowns": "\n".join(item.get("unknowns") or []) or None,
    }
    if "Move-in note" in props and "move_in_note" in item:
        expected["Move-in note"] = item.get("move_in_note")
    wrong = []
    for name, want in expected.items():
        have = props.get(name)
        if isinstance(have, float) and have.is_integer():
            have = int(have)
        have = None if have == "" else have
        want = None if want == "" else want
        if have != want:
            shown = ("…", "…") if name == "URL" else (have, want)
            wrong.append("%s: page %r, item %r" % (name, shown[0], shown[1]))
    if not wrong:
        return []
    return [finding("L3.page_matches_item", "major", "page properties differ from the dataset item: %s"
                    % "; ".join(n.split(":")[0] for n in wrong), "apify/domovoy/notion/sink.py",
                    rerun("L3.page_matches_item"), run_id=run_id, property_id=item["property_id"],
                    page_id=page["page_id"], excerpt="; ".join(wrong))]


def check_counts(items: list[dict], summary: dict, run_id: str | None, include_unchanged: bool = False) -> list[dict]:
    """The RunSummary counts against the run's dataset. Without includeUnchanged only new and changed flats are
    emitted; with it, every flat is, and every non-rejected one is written to Notion."""
    out = []
    match = summary.get("match") or {}
    counted = {k: sum(1 for i in items if i.get("match") == k) for k in ("strong", "needs_info", "rejected")}
    if {k: match.get(k, 0) for k in counted} != counted:
        out.append(finding("L3.summary_counts", "major", "summary.match %s differs from the dataset %s"
                           % (match, counted), "apify/domovoy/pipeline.py", rerun("L3.summary_counts"), run_id=run_id))
    change = summary.get("change") or {}
    expected = sum(change.get(k, 0) for k in (("new", "changed", "unchanged") if include_unchanged else ("new", "changed")))
    if expected != len(items):
        out.append(finding("L3.summary_counts", "major", "summary.change says %d flats emitted, the dataset has %d"
                           % (expected, len(items)), "apify/domovoy/pipeline.py", rerun("L3.summary_counts"),
                           run_id=run_id))
    notion = summary.get("notion") or {}
    deliverable = sum(1 for i in items if i.get("match") != "rejected"
                      and (include_unchanged or i.get("change") in ("new", "changed")))
    written = notion.get("created", 0) + notion.get("updated", 0) + notion.get("errors", 0)
    if written != deliverable:
        out.append(finding("L3.summary_counts", "major", "notion created+updated+errors %d differs from %d deliverable "
                           "items" % (written, deliverable), "apify/domovoy/pipeline.py", rerun("L3.summary_counts"),
                           run_id=run_id))
    return out


def check_bodies(pages: list[dict], run_id: str | None) -> list[dict]:
    out = []
    for page in pages:
        body = page.get("body")
        if not body:
            continue
        stripped = URL.sub(" ", body)
        if EMAIL.search(stripped) or PHONE.search(stripped):
            out.append(finding("L3.body_no_contacts", "blocker", "the page body holds an email or phone number",
                               "apify/domovoy/notion/sink.py", rerun("L3.body_no_contacts"), run_id=run_id,
                               property_id=page.get("property_id"), page_id=page["page_id"]))
    return out


# L4: idempotency


def check_idempotency(before: list[dict], after: list[dict], summary2: dict | None, items1: list[dict],
                      items2: list[dict], edited: dict, run_id: str | None) -> list[dict]:
    """before/after: the e2e database around the second run. edited: {page_id, status, reason, marker}."""
    out = []
    before_ids = {p["page_id"] for p in before}
    new_pages = [p for p in after if p["page_id"] not in before_ids]
    known = {p.get("property_id") for p in before}
    for page in new_pages:
        sev = "blocker" if page.get("property_id") in known else "minor"
        why = "a second page for a known Property ID" if sev == "blocker" else "a new page (new listing on the portal?)"
        out.append(finding("L4.no_new_pages", sev, why, "apify/domovoy/notion/sink.py", rerun("L4.no_new_pages"),
                           run_id=run_id, property_id=page.get("property_id"), page_id=page["page_id"]))
    pid_to_page = {p.get("property_id"): p["page_id"] for p in before}
    for page in after:
        pid = page.get("property_id")
        if pid in pid_to_page and page["page_id"] in before_ids and pid_to_page[pid] != page["page_id"]:
            out.append(finding("L4.property_ids_stable", "blocker", "the Property ID moved to another page",
                               "apify/domovoy/dedup/state.py", rerun("L4.property_ids_stable"), run_id=run_id,
                               property_id=pid, page_id=page["page_id"]))
    after_by_id = {p["page_id"]: p for p in after}
    for page in before:
        if page["page_id"] in after_by_id and after_by_id[page["page_id"]].get("property_id") != page.get("property_id"):
            out.append(finding("L4.property_ids_stable", "blocker", "a page's Property ID changed",
                               "apify/domovoy/notion/sink.py", rerun("L4.property_ids_stable"), run_id=run_id,
                               property_id=page.get("property_id"), page_id=page["page_id"]))
    first_ids = {i["property_id"] for i in items1}
    for item in items2:
        if item["property_id"] in first_ids and item.get("change") == "new":
            out.append(finding("L4.unchanged_reported", "blocker", "a flat from the first run is reported new again",
                               "apify/domovoy/dedup/state.py", rerun("L4.unchanged_reported"), run_id=run_id,
                               property_id=item["property_id"]))
        elif item["property_id"] in first_ids and item.get("change") == "changed":
            out.append(finding("L4.unchanged_reported", "minor", "a flat from the first run is reported changed "
                               "(a real portal edit, or an unstable content hash)", "apify/domovoy/dedup/state.py",
                               rerun("L4.unchanged_reported"), run_id=run_id, property_id=item["property_id"]))
    if summary2 is not None:
        created = (summary2.get("notion") or {}).get("created", 0)
        if created and not new_pages:
            out.append(finding("L4.no_new_pages", "major", "summary says %d pages created, the database has none new"
                               % created, "apify/domovoy/pipeline.py", rerun("L4.no_new_pages"), run_id=run_id))
        if (summary2.get("change") or {}).get("unchanged", 0) == 0 and first_ids:
            out.append(finding("L4.unchanged_reported", "blocker", "the second run reports 0 unchanged flats",
                               "apify/domovoy/dedup/state.py", rerun("L4.unchanged_reported"), run_id=run_id))
    page = after_by_id.get(edited.get("page_id"))
    if page is None:
        out.append(finding("L4.edits_kept", "blocker", "the hand-edited page is gone", "apify/domovoy/notion/sink.py",
                           rerun("L4.edits_kept"), run_id=run_id, page_id=edited.get("page_id")))
    else:
        lost = [name for name, ok in (("Status", page.get("status") == edited["status"]),
                                      ("Reason", page.get("reason") == edited["reason"]),
                                      ("body", edited["marker"] in (page.get("body") or ""))) if not ok]
        if lost:
            out.append(finding("L4.edits_kept", "blocker", "the run overwrote the hand edits: %s" % ", ".join(lost),
                               "apify/domovoy/notion/sink.py", rerun("L4.edits_kept"), run_id=run_id,
                               property_id=page.get("property_id"), page_id=page["page_id"]))
    return out


# L5: call_context from a real page


def check_call_context(context: dict | None, page: dict, budget_cap: int, schema_errors: list[str],
                       how: str | None = None) -> list[dict]:
    pid, page_id = page.get("property_id"), page["page_id"]
    if context is None:
        return [finding("L5.context_schema", "blocker", "call.py check built no call_context: %s" % how,
                        "skill/domovoy/scripts/call.py", rerun("L5.context_schema"), property_id=pid,
                        page_id=page_id, excerpt=how)]
    out = []
    if schema_errors:
        out.append(finding("L5.context_schema", "blocker", "call_context does not validate", "skill/domovoy/scripts/notion.py",
                           rerun("L5.context_schema"), property_id=pid, page_id=page_id,
                           excerpt="; ".join(schema_errors)[:300]))
    props = page.get("props") or {}
    unknowns = [line.strip() for line in (props.get("Unknowns") or "").split("\n") if line.strip()]

    def num(name):
        value = props.get(name)
        return int(value) if isinstance(value, float) and value.is_integer() else value

    pairs = {"rent": num("Rent"), "total_monthly": num("Total monthly"), "upfront": num(move_in_name(props)),
             "unknowns": unknowns, "property_id": pid}
    wrong = [k for k, want in pairs.items() if context.get(k) != want]
    if wrong:
        out.append(finding("L5.context_matches_page", "major", "call_context differs from the page in: %s"
                           % ", ".join(wrong), "skill/domovoy/scripts/notion.py", rerun("L5.context_matches_page"),
                           property_id=pid, page_id=page_id,
                           excerpt="; ".join("%s ctx %r page %r" % (k, context.get(k), pairs[k]) for k in wrong
                                             if k != "unknowns")))
    if context.get("budget_cap") != budget_cap:
        out.append(finding("L5.budget_cap", "major", "budget_cap %r, profile max_total_monthly %r"
                           % (context.get("budget_cap"), budget_cap), "skill/domovoy/scripts/call.py",
                           rerun("L5.budget_cap"), property_id=pid, page_id=page_id))
    return out


# L6: hygiene


def scan_text(text: str, secrets: list[str], contacts: list[str], allow: tuple[str, ...] = ()) -> list[str]:
    """Kinds of leak found in text, never the values: 'secret', 'contact', 'email', 'phone'."""
    kinds = []
    if any(s and len(s) >= 8 and s in text for s in secrets):
        kinds.append("secret")
    if any(c and len(c) >= 5 and c in text for c in contacts):
        kinds.append("contact")
    stripped = URL.sub(" ", text)
    emails = [e for e in EMAIL.findall(stripped) if not any(a in e for a in allow)]
    if emails:
        kinds.append("email")
    if PHONE.search(stripped):
        kinds.append("phone")
    return kinds
