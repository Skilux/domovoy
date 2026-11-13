#!/usr/bin/env python3
"""DOMOVOY Notion shortlist: the setup command, and the shortlist backend that call.py loads.

  notion.py setup   Create "DOMOVOY shortlist" under NOTION_PARENT_PAGE_ID from reference/notion_contract.json,
                    or add what is missing, and rename a property listed under renamed_from in place.
                    Changes nothing when the database already matches the contract.
                    config.json (DOMOVOY_CONFIG, else the skill folder; optional for setup) may set
                    notion.database_title to target another database under the same parent, e.g. for e2e tests.
                    Prints one JSON object. Put its data_source_id in config.json as notion.data_source_id.
                    Exit 0 when done; exit 1 on an error or a conflict (then nothing is changed).

SHORTLIST BACKEND, shape B of the call.py docstring (config.json "backend.module": "scripts/notion.py"):
  list_flats(cfg, status=None)          -> [{"id", "title", "url", "status", "listing"}]
  get_flat(cfg, flat_id)                -> {"id", "title", "url", "listing", "text"}
  set_status(cfg, flat_id, status)
  append(cfg, flat_id, text)            text lines, one paragraph each, added to the page body
  set_viewing_date(cfg, flat_id, start) ISO 8601 with a UTC offset
"listing" holds the call_context fields read from the page properties. Realtor contacts are never read.
call_context's "upfront" is read from the "Move-in cost" property (the Actor renamed Upfront) until the
call_context field is renamed.

Secrets: NOTION_TOKEN and NOTION_PARENT_PAGE_ID come from the environment, else from ~/.config/domovoy/.env.
Nothing secret is printed. Standard library only: call.py loads this module, so call needs no packages.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.expanduser("~/.config/domovoy/.env")
API = "https://api.notion.com/v1"
TIMEOUT_SECONDS = 30
MAX_TRIES = 5                  # 429 and 529 are retried after Retry-After
PAGE_SIZE = 100                # largest page for list and query endpoints
CHILDREN_LIMIT = 100           # block children per append request
TEXT_LIMIT = 2000              # characters per rich text object
BODY_DEPTH = 3                 # nested blocks followed when reading a page body
UNKNOWNS_SEPARATOR = "\n"      # the Unknowns property holds one line per unknown
ID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.IGNORECASE)
OFFSET = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

with open(os.path.join(ROOT, "reference", "notion_contract.json"), encoding="utf-8") as f:
    CONTRACT = json.load(f)
DB_TITLE = CONTRACT["database_title"]
VERSION = CONTRACT["notion_api_version"]
PROPS = CONTRACT["properties"]
STATUSES = PROPS["Status"]["options"]
LEASE_TYPE = CONTRACT["call_context_values"]["lease_type"]


class NotionError(RuntimeError):
    pass


def read_env_file(path=None):
    values = {}
    path = path or ENV_FILE
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            key, sep, value = line.strip().partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            if sep and key:
                values[key] = value.strip().strip("'\"")
    return values


def setting(name):
    value = os.environ.get(name) or read_env_file().get(name)
    if not value:
        raise RuntimeError("%s is not set: export it, or put it in %s" % (name, ENV_FILE))
    return value


def checked_id(value, what):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RuntimeError("%s is not a Notion ID" % what)
    return value


def _send(method, url, body):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + setting("NOTION_TOKEN"),
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers
    except urllib.error.URLError as e:
        raise NotionError("cannot reach Notion: %s" % e.reason)


def retry_seconds(headers):
    try:
        return min(float(headers.get("Retry-After")), 60.0)
    except (TypeError, ValueError):
        return 1.0


def request(method, path, body=None, query=None):
    """One Notion API call; returns the parsed JSON. Waits and retries on 429 and 529."""
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    for attempt in range(1, MAX_TRIES + 1):
        status, raw, headers = _send(method, url, body)
        if status not in (429, 529) or attempt == MAX_TRIES:
            break
        time.sleep(retry_seconds(headers))
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        data = None
    if not 200 <= status < 300:
        if isinstance(data, dict):
            code, message = data.get("code", "http_%d" % status), data.get("message", "")
        else:
            code, message = "http_%d" % status, raw[:200].decode("utf-8", "replace")
        raise NotionError("Notion %s %s failed: %s %s" % (method, path, code, message))
    return data


def paginate(method, path, params):
    """Every result of a list or query endpoint. Follows next_cursor until has_more is false."""
    results, cursor = [], None
    while True:
        page_params = dict(params, page_size=PAGE_SIZE)
        if cursor:
            page_params["start_cursor"] = cursor
        if method == "GET":
            page = request(method, path, query=page_params)
        else:
            page = request(method, path, body=page_params)
        results += page["results"]
        if not page.get("has_more"):
            return results
        cursor = page.get("next_cursor")
        if not cursor:
            raise NotionError("Notion said has_more without next_cursor for %s" % path)


def prop(page, name):
    props = page.get("properties") or {}
    if name not in props:
        raise RuntimeError("the Notion page has no %r property: check the database against the contract "
                           "(notion.py setup)" % name)
    return props[name]


def plain(items):
    return "".join(item.get("plain_text", "") for item in items or [])


def page_title(page):
    for value in (page.get("properties") or {}).values():
        if value.get("type") == "title":
            return plain(value["title"])
    return ""


def select_name(page, name):
    value = prop(page, name)["select"]
    return value["name"] if value else None


def text_or_none(page, name):
    return plain(prop(page, name)["rich_text"]) or None


def money(page, name):
    value = prop(page, name)["number"]
    return None if value is None else int(value)


def date_start(page, name):
    value = prop(page, name)["date"]
    return value["start"] if value else None


def listing_of(page):
    """The call_context fields of one flat, read from its properties. Contacts are never read."""
    unknowns = plain(prop(page, "Unknowns")["rich_text"])
    return {
        "property_id": text_or_none(page, "Property ID"),
        "address": text_or_none(page, "Address"),
        "url": prop(page, "URL")["url"],
        "collected_at": date_start(page, "Collected at"),
        "rent": money(page, "Rent"),
        "total_monthly": money(page, "Total monthly"),
        "upfront": money(page, "Move-in cost"),  # call_context still names it upfront
        "kauce": money(page, "Kauce"),
        "commission": money(page, "Commission"),
        "move_in_date": date_start(page, "Move-in date"),
        "lease_type": LEASE_TYPE.get(select_name(page, "Lease type")),
        "missing_furniture_cost": money(page, "Missing furniture cost"),
        "unknowns": [line.strip() for line in unknowns.split(UNKNOWNS_SEPARATOR) if line.strip()],
    }


def flat_row(page):
    return {"id": page["id"], "title": page_title(page), "url": page.get("url"),
            "status": select_name(page, "Status"), "listing": listing_of(page)}


def data_source(cfg):
    value = (cfg.get("notion") or {}).get("data_source_id")
    if not value:
        raise RuntimeError("config.json has no notion.data_source_id: run scripts/notion.py setup and put "
                           "the data_source_id it prints there")
    return checked_id(value, "notion.data_source_id")


def body_lines(block_id, depth=0):
    """The text of the blocks under block_id: one line per block, nested blocks included."""
    lines = []
    for block in paginate("GET", "/blocks/%s/children" % block_id, {}):
        kind = block["type"]
        if kind == "table_row":
            text = " | ".join(plain(cell) for cell in block["table_row"]["cells"])
        else:
            text = plain((block.get(kind) or {}).get("rich_text"))
        if text.strip():
            lines.append(text)
        if block.get("has_children") and depth < BODY_DEPTH:
            lines += body_lines(block["id"], depth + 1)
    return lines


def list_flats(cfg, status=None):
    params = {"filter": {"property": "Status", "select": {"equals": status}}} if status else {}
    pages = paginate("POST", "/data_sources/%s/query" % data_source(cfg), params)
    return [flat_row(page) for page in pages]


def get_flat(cfg, flat_id):
    page = request("GET", "/pages/%s" % checked_id(flat_id, "flat id"))
    return {"id": page["id"], "title": page_title(page), "url": page.get("url"),
            "listing": listing_of(page), "text": "\n".join(body_lines(page["id"]))}


def set_status(cfg, flat_id, status):
    if status not in STATUSES:
        raise RuntimeError("status %r is not in the contract; use one of: %s" % (status, ", ".join(STATUSES)))
    request("PATCH", "/pages/%s" % checked_id(flat_id, "flat id"),
            {"properties": {"Status": {"select": {"name": status}}}})


def paragraph(line):
    pieces = [line[i:i + TEXT_LIMIT] for i in range(0, len(line), TEXT_LIMIT)]
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": piece}} for piece in pieces]}}


def append(cfg, flat_id, text):
    blocks = [paragraph(line) for line in text.split("\n") if line.strip()]
    path = "/blocks/%s/children" % checked_id(flat_id, "flat id")
    for start in range(0, len(blocks), CHILDREN_LIMIT):
        request("PATCH", path, {"children": blocks[start:start + CHILDREN_LIMIT]})


def set_viewing_date(cfg, flat_id, start):
    if not isinstance(start, str) or not OFFSET.search(start):
        raise RuntimeError("the viewing date must be ISO 8601 with a UTC offset")
    request("PATCH", "/pages/%s" % checked_id(flat_id, "flat id"),
            {"properties": {"Viewing date": {"date": {"start": start}}}})


def new_option(spec, name):
    """An option to create. Carries the contract's color for it, if the contract names one."""
    color = spec.get("colors", {}).get(name)
    return {"name": name, "color": color} if color else {"name": name}


def property_schema(spec):
    kind = spec["type"]
    if kind in ("select", "multi_select"):
        return {kind: {"options": [new_option(spec, name) for name in spec.get("options", [])]}}
    if kind == "number":
        return {kind: {"format": spec.get("format", "number")}}
    return {kind: {}}


def plan_changes(live):
    """What setup must change so that Notion matches the contract: (conflicts, payload, added_options, renamed).

    payload is the body of PATCH data_sources. It holds new properties, and full option lists where options are
    missing. Existing options are sent by id, because Notion removes every option a PATCH leaves out, and so keep
    their color: setup never recolors an option.
    A contract property that is missing while one of its renamed_from names exists with the same type is renamed:
    the payload key is the live property id and the value {"name": <contract name>}; renamed maps old to new.
    Nothing is removed and no type is changed: a mismatch is a conflict.
    """
    conflicts, payload, added_options, renamed = [], {}, {}, {}
    titles = [name for name, value in live.items() if value["type"] == "title"]
    for name, spec in PROPS.items():
        kind = spec["type"]
        if name not in live:
            old = next((old for old in spec.get("renamed_from", [])
                        if old in live and old not in PROPS and live[old]["type"] == kind), None)
            if old is not None:
                # Renamed in place by property id, so every page keeps its value.
                payload[live[old]["id"]] = {"name": name}
                renamed[old] = name
            elif kind == "title":
                conflicts.append("the title property is %s, the contract needs %r" % (titles, name))
            else:
                payload[name] = property_schema(spec)
            continue
        have = live[name]
        if have["type"] != kind:
            conflicts.append("%s is %s in Notion, the contract says %s" % (name, have["type"], kind))
        elif kind in ("select", "multi_select"):
            existing = have[kind].get("options", [])
            known = {option["name"] for option in existing}
            missing = [option for option in spec.get("options", []) if option not in known]
            if missing:
                kept = [{"id": option["id"]} for option in existing]
                payload[name] = {kind: {"options": kept + [new_option(spec, option) for option in missing]}}
                added_options[name] = missing
    return conflicts, payload, added_options, renamed


def setup_config():
    """config.json for setup. Optional: without it setup targets the contract's database title."""
    path = os.environ.get("DOMOVOY_CONFIG")
    if path:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise RuntimeError("DOMOVOY_CONFIG points to a missing file: %s" % path)
    else:
        path = os.path.join(ROOT, "config.json")
        if not os.path.isfile(path):
            return {}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise RuntimeError("config %s is not a JSON object" % path)
    return cfg


def database_title(cfg):
    """(title, where it came from). notion.database_title in config.json, else the contract's database_title."""
    title = (cfg.get("notion") or {}).get("database_title")
    if title is None:
        return DB_TITLE, "contract database_title"
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("config notion.database_title must be a non-empty string")
    return title.strip(), "config notion.database_title"


def find_databases(parent_id, title=DB_TITLE):
    try:
        blocks = paginate("GET", "/blocks/%s/children" % parent_id, {})
    except NotionError as e:
        if "object_not_found" in str(e):
            raise RuntimeError("Notion cannot see the parent page: connect the DOMOVOY integration to it "
                               "(page menu > Connections), then run setup again") from e
        raise
    return [block["id"] for block in blocks
            if block.get("type") == "child_database" and block["child_database"].get("title") == title]


def single_data_source(database):
    sources = database.get("data_sources") or []
    if len(sources) != 1:
        raise RuntimeError("expected one data source in database %s, found %d" % (database.get("id"), len(sources)))
    return sources[0]["id"]


def report(database, ds_id, created, added_properties, added_options, conflicts, renamed=None,
           title=DB_TITLE, title_source="contract database_title"):
    return {
        "database": title,
        "database_title_from": title_source,
        "database_id": database["id"],
        "database_url": database.get("url"),
        "data_source_id": ds_id,
        "created": created,
        "changed": created or bool(added_properties or added_options or renamed),
        "added_properties": added_properties,
        "renamed_properties": renamed or {},
        "added_options": added_options,
        "conflicts": conflicts,
        "config_key": "notion.data_source_id",
    }


def setup(cfg=None):
    title, title_source = database_title(cfg or {})
    parent_id = checked_id(setting("NOTION_PARENT_PAGE_ID"), "NOTION_PARENT_PAGE_ID")
    found = find_databases(parent_id, title)
    if len(found) > 1:
        raise RuntimeError("%d databases named %r sit under the parent page: keep one, archive the rest in Notion, "
                           "then run setup again" % (len(found), title))
    if not found:
        database_id = request("POST", "/databases", {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "initial_data_source": {"properties": {name: property_schema(spec) for name, spec in PROPS.items()}},
        })["id"]
        database = request("GET", "/databases/%s" % database_id)
        return report(database, single_data_source(database), True, sorted(PROPS), {}, [],
                      title=title, title_source=title_source)
    database = request("GET", "/databases/%s" % found[0])
    ds_id = single_data_source(database)
    live = request("GET", "/data_sources/%s" % ds_id)["properties"]
    conflicts, payload, added_options, renamed = plan_changes(live)
    if conflicts:
        return report(database, ds_id, False, [], {}, conflicts, title=title, title_source=title_source)
    if payload:
        request("PATCH", "/data_sources/%s" % ds_id, {"properties": payload})
    added_properties = sorted(name for name, spec in payload.items() if name in PROPS and name not in live)
    return report(database, ds_id, False, added_properties, added_options, [], renamed,
                  title=title, title_source=title_source)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["setup"])
    parser.parse_args(argv)
    try:
        out = setup(setup_config())
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if out["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
