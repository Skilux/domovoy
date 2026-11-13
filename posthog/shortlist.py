#!/usr/bin/env python3
"""Read and update the DOMOVOY shortlist for the PostHog loop. Standard library only.

Two backends with the same functions:
  Notion   the data source named by NOTION_DATA_SOURCE_ID, else a `data_source_id` in the skill's config.json,
           else the data source titled "DOMOVOY shortlist" that NOTION_TOKEN can see.
           Property names follow docs/prd/actor.md.
  Fake     a JSON file named by DOMOVOY_FAKE_SHORTLIST, for tests. Never talks to Notion.

A flat is a dict: page_id, property_id, title, status, reason, elevator, portal, total_monthly, upfront, floor,
interested (the renter's "Interested?" column: Yes, No or None; None also when the column does not exist),
furnished, commission, metro_m. Only Status and Reason are ever written.
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


def _flat(page):
    p = page["properties"]
    sources = [s["name"] for s in (p.get("Sources") or {}).get("multi_select", [])]
    return {
        "page_id": page["id"],
        "property_id": _plain(p.get("Property ID") or {}),
        "title": _plain(p.get("Name") or {}),
        "status": _select(p.get("Status")),
        "reason": _plain(p.get("Reason") or {}),
        "elevator": _select(p.get("Elevator")),
        "portal": sources[0].lower() if sources else None,
        "total_monthly": (p.get("Total monthly") or {}).get("number"),
        "upfront": (p.get("Upfront") or {}).get("number"),
        "floor": (p.get("Floor") or {}).get("number"),
        "interested": _select(p.get("Interested?")),
        "furnished": _select(p.get("Furnished")),
        "commission": (p.get("Commission") or {}).get("number"),
        "metro_m": (p.get("Metro m") or {}).get("number"),
    }


def list_flats():
    if _fake_path():
        with open(_fake_path(), encoding="utf-8") as f:
            return json.load(f)["flats"]
    source = data_source_id()
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
    """Move one flat to Not interested and write the Reason."""
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
