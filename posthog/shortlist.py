#!/usr/bin/env python3
"""Read and update the DOMOVOY shortlist for the PostHog loop. Standard library only.

Two backends with the same functions:
  Notion   the data source named by NOTION_DATA_SOURCE_ID, else a `data_source_id` in the skill's config.json,
           else the data source titled "DOMOVOY shortlist" that NOTION_TOKEN can see.
           Property names follow docs/prd/actor.md.
  Fake     a JSON file named by DOMOVOY_FAKE_SHORTLIST, for tests. Never talks to Notion.

A flat is a dict: page_id, property_id, title, status, reason, elevator, portal, total_monthly, upfront, floor,
interested (the renter's "Interested?" column: Yes, No or None; None also when the column does not exist),
furnished, commission, metro_m. `upfront` is, per flat, the first filled value of "Move-in total", "Move-in cost", "Upfront".
Only Property ID and Status are required; any other missing property reads as None and is listed in MISSING.
Only Status and Reason are ever written, and only to a test or synthetic database unless ALLOW_REAL is set.
"""
import json
import os
import urllib.error
import urllib.request

from ph import find_key, load_env, skill_config

NOTION_VERSION = "2025-09-03"
TITLE = "DOMOVOY shortlist"


def _fake_path():
    return os.environ.get("DOMOVOY_FAKE_SHORTLIST")


def _notion(method, path, body=None):
    env = load_env()
    token = env.get("NOTION_TOKEN") or os.environ.get("NOTION_TOKEN")
    if not token:
        raise SystemExit("missing NOTION_TOKEN")
    req = urllib.request.Request(
        "https://api.notion.com/v1" + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
    )
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("Notion HTTP %s on %s %s: %s" % (e.code, method, path, e.read().decode("utf-8")[:300]))


def _plain(prop):
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(i.get("plain_text", "") for i in items).strip()


def _select(prop):
    return ((prop or {}).get("select") or {}).get("name")


def explicit_data_source():
    """A data source named on purpose: NOTION_DATA_SOURCE_ID, a data_source_id in the skill config, or the fake file."""
    return (_fake_path() or os.environ.get("NOTION_DATA_SOURCE_ID") or load_env().get("NOTION_DATA_SOURCE_ID")
            or find_key(skill_config(), "data_source_id"))


def data_source_id():
    known = explicit_data_source()
    if known:
        return known
    title = os.environ.get("DOMOVOY_SHORTLIST_TITLE") or TITLE
    found = _notion("POST", "/search", {"query": title, "filter": {"property": "object", "value": "data_source"}})
    for item in found.get("results", []):
        if "".join(t.get("plain_text", "") for t in item.get("title", [])).strip() == title:
            return item["id"]
    raise SystemExit('no Notion data source titled "%s" is shared with the integration' % title)


REQUIRED = ("Property ID", "Status")
OPTIONAL = ("Name", "Reason", "Interested?", "Elevator", "Furnished", "Floor", "Metro m", "Commission",
            "Total monthly", "Sources")
UPFRONT_NAMES = ("Move-in total", "Move-in cost", "Upfront")  # per page the first filled one wins (issue #84)
MISSING = []  # optional properties the last list_flats() did not find; reported by loop.py
ALLOW_REAL = False  # set by loop.py --real; without it only a test or synthetic database is ever written


def _number(p, name):
    value = (p.get(name) or {}).get("number")
    return value if isinstance(value, (int, float)) else None


def _flat(page):
    p = page.get("properties") or {}
    sources = [s.get("name") for s in (p.get("Sources") or {}).get("multi_select") or [] if s.get("name")]
    upfront = next((v for v in (_number(p, name) for name in UPFRONT_NAMES) if v is not None), None)
    return {
        "page_id": page["id"],
        "property_id": _plain(p.get("Property ID") or {}),
        "title": _plain(p.get("Name") or {}),
        "status": _select(p.get("Status")),
        "reason": _plain(p.get("Reason") or {}),
        "elevator": _select(p.get("Elevator")),
        "portal": sources[0].lower() if sources else None,
        "total_monthly": _number(p, "Total monthly"),
        "upfront": upfront,
        "floor": _number(p, "Floor"),
        "interested": _select(p.get("Interested?")),
        "furnished": _select(p.get("Furnished")),
        "commission": _number(p, "Commission"),
        "metro_m": _number(p, "Metro m"),
    }


def target():
    """The shortlist every command reads and writes: {"title", "id", "is_test"}. A title counts as a test
    when it contains "test" or "synthetic"; the fake file always does."""
    if _fake_path():
        return {"title": "fake file (synthetic test) " + _fake_path(), "id": "fake", "is_test": True}
    source = data_source_id()
    info = _notion("GET", "/data_sources/" + source)
    title = "".join(t.get("plain_text", "") for t in info.get("title") or []).strip()
    names = set(info.get("properties") or {})
    absent = [name for name in REQUIRED if name not in names]
    if absent:
        raise SystemExit('Notion database "%s" has no %s property; the loop cannot run on it' % (title, " or ".join(absent)))
    MISSING[:] = [name for name in OPTIONAL if name not in names]
    if not any(name in names for name in UPFRONT_NAMES):
        MISSING.append(" / ".join(UPFRONT_NAMES))
    return {"title": title, "id": source, "is_test": any(w in title.lower() for w in ("test", "synthetic"))}


def list_flats():
    if _fake_path():
        with open(_fake_path(), encoding="utf-8") as f:
            return json.load(f)["flats"]
    source = target()["id"]
    flats, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        out = _notion("POST", "/data_sources/%s/query" % source, body)
        flats += [_flat(page) for page in out.get("results", [])]
        if not out.get("has_more"):
            return [f for f in flats if f["property_id"]]
        cursor = out.get("next_cursor")


def reject(flat, reason, status="Not interested"):
    """Move one flat to Not interested and write the Reason. Refuses a real database unless ALLOW_REAL is set."""
    where = target()
    if not where["is_test"] and not ALLOW_REAL:
        raise SystemExit('refusing to write to "%s" (%s): not a test database and --real was not given' % (where["title"], where["id"]))
    if _fake_path():
        with open(_fake_path(), encoding="utf-8") as f:
            db = json.load(f)
        for item in db["flats"]:
            if item["page_id"] == flat["page_id"]:
                item["status"], item["reason"] = status, reason
        with open(_fake_path(), "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        return
    _notion("PATCH", "/pages/" + flat["page_id"], {"properties": {
        "Status": {"select": {"name": status}},
        "Reason": {"rich_text": [{"type": "text", "text": {"content": reason}}]},
    }})
