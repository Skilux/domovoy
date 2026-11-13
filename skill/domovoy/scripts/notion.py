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
  list_flats(cfg, status=None)          -> [{"id", "title", "url", "status", "interested", "listing"}]
  get_flat(cfg, flat_id)                -> {"id", "title", "url", "interested", "listing", "text"}
  set_status(cfg, flat_id, status)
  append(cfg, flat_id, text)            text lines added to the page body, one block per line (see append)
  set_viewing_date(cfg, flat_id, start) ISO 8601 with a UTC offset
  attach_file(cfg, flat_id, path, caption=None, marker=None)
                                        upload a PDF (katastr.py attach) and add it to the page body
"interested" is the user's "Interested?" column: True (Yes), False (No) or None (empty). call.py calls a flat
when its Status is Interested or this is True, whatever the Status. "listing" holds the call_context fields read from the page properties. Realtor contacts are never read.
call_context's "upfront" is read from the "Move-in cost" property (the Actor renamed Upfront) until the
call_context field is renamed.

Secrets: NOTION_TOKEN and NOTION_PARENT_PAGE_ID come from the environment, else from the env file:
DOMOVOY_ENV_FILE, else ~/.config/domovoy/.env.
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
ENV_FILE = os.path.expanduser(os.environ.get("DOMOVOY_ENV_FILE") or "~/.config/domovoy/.env")
API = "https://api.notion.com/v1"
TIMEOUT_SECONDS = 30
MAX_TRIES = 5                  # 429 and 529 are retried after Retry-After
PAGE_SIZE = 100                # largest page for list and query endpoints
CHILDREN_LIMIT = 100           # block children per append request
TEXT_LIMIT = 2000              # characters per rich text object
BODY_DEPTH = 3                 # nested blocks followed when reading a page body
UNKNOWNS_SEPARATOR = "\n"      # the Unknowns property holds one line per unknown
TITLE_LINE = re.compile(r"^(Call result: .+|Katastr check)$")   # section titles call.py and katastr.py write
MARKER_LINE = re.compile(r"^domovoy-[a-z-]+: ")                # internal markers: kept, shown small and gray
TOGGLE_INDENT = "  "                                           # lines under a "+ " line go inside its toggle
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


INTERESTED = {"Yes": True, "No": False}


def interested_of(page):
    """The user's "Interested?" column: True for Yes, False for No, None when empty (call.py's "interested")."""
    return INTERESTED.get(select_name(page, "Interested?"))


def flat_row(page):
    return {"id": page["id"], "title": page_title(page), "url": page.get("url"),
            "status": select_name(page, "Status"), "interested": interested_of(page), "listing": listing_of(page)}


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
            if kind == "bulleted_list_item" and text.strip():
                text = "- " + text           # the "- " append turned into a bullet, so readers see the same line
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
    return {"id": page["id"], "title": page_title(page), "url": page.get("url"), "interested": interested_of(page),
            "listing": listing_of(page), "text": "\n".join(body_lines(page["id"]))}


def set_status(cfg, flat_id, status):
    if status not in STATUSES:
        raise RuntimeError("status %r is not in the contract; use one of: %s" % (status, ", ".join(STATUSES)))
    request("PATCH", "/pages/%s" % checked_id(flat_id, "flat id"),
            {"properties": {"Status": {"select": {"name": status}}}})


def text_block(kind, line, color=None, bold=False):
    pieces = [line[i:i + TEXT_LIMIT] for i in range(0, len(line), TEXT_LIMIT)]
    rich = [{"type": "text", "text": {"content": piece}} for piece in pieces]
    if bold:
        for item in rich:
            item["annotations"] = {"bold": True}
    body = {"rich_text": rich}
    if color:
        body["color"] = color
    return {"object": "block", "type": kind, kind: body}


def paragraph(line, color=None):
    return text_block("paragraph", line, color)


def line_block(line):
    """One text line as one block, by its shape."""
    if TITLE_LINE.match(line):
        return text_block("heading_3", line)
    if MARKER_LINE.match(line):
        return paragraph(line, "gray")
    if line.startswith("- "):
        return text_block("bulleted_list_item", line[2:])
    if line.endswith(":") and len(line) <= 80:
        return text_block("paragraph", line, bold=True)
    return paragraph(line)


def text_blocks(text):
    """Plain text -> blocks. A title line ("Call result: ...", "Katastr check") is a heading; "- x" is a bullet;
    a short line ending in ":" is bold; a domovoy-* marker is gray; "+ Title" is a closed toggle that holds the
    lines under it indented by two spaces. Empty lines are dropped."""
    blocks = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        parent = blocks[-1] if blocks and blocks[-1]["type"] == "toggle" else None
        if parent is not None and line.startswith(TOGGLE_INDENT):
            children = parent["toggle"].setdefault("children", [])
            if len(children) >= CHILDREN_LIMIT:
                parent = text_block("toggle", plain_text_of(parent) + " (continued)")
                children = parent["toggle"]["children"] = []
                blocks.append(parent)
            children.append(line_block(line[len(TOGGLE_INDENT):]))
        elif line.startswith("+ "):
            blocks.append(text_block("toggle", line[2:]))
        else:
            blocks.append(line_block(line))
    return blocks


def plain_text_of(block):
    return "".join(item["text"]["content"] for item in block[block["type"]]["rich_text"])


def append(cfg, flat_id, text):
    blocks = text_blocks(text)
    path = "/blocks/%s/children" % checked_id(flat_id, "flat id")
    for start in range(0, len(blocks), CHILDREN_LIMIT):
        request("PATCH", path, {"children": blocks[start:start + CHILDREN_LIMIT]})


def _send_bytes(url, data, content_type):
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + setting("NOTION_TOKEN"),
        "Notion-Version": VERSION,
        "Content-Type": content_type,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS * 4) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise NotionError("cannot reach Notion: %s" % e.reason)


def upload_file(path, content_type="application/pdf"):
    """Single-part Notion file upload (up to 20 MB). Returns the file upload id."""
    name = re.sub(r'[^\w.\- ]', "_", os.path.basename(path))[:100]
    with open(path, "rb") as f:
        data = f.read()
    if len(data) > 20 * 1024 * 1024:
        raise NotionError("the file is larger than 20 MB, the single-part upload limit")
    created = request("POST", "/file_uploads", {"filename": name, "content_type": content_type})
    upload_id = checked_id(created.get("id"), "file upload id")
    boundary = "domovoy-%s" % os.urandom(12).hex()
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
             % (boundary, name, content_type)).encode("utf-8") + data + ("\r\n--%s--\r\n" % boundary).encode())
    status, raw = _send_bytes(API + "/file_uploads/%s/send" % upload_id, body,
                              "multipart/form-data; boundary=" + boundary)
    try:
        reply = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        reply = {}
    if not 200 <= status < 300 or reply.get("status") != "uploaded":
        raise NotionError("Notion file upload failed: %s" % (reply.get("code") or "http_%d" % status))
    return upload_id


def attach_file(cfg, flat_id, path, caption=None, marker=None):
    """Upload a PDF and add it to the page body as a PDF block, then a marker paragraph (if given)."""
    upload_id = upload_file(path)
    block = {"object": "block", "type": "pdf",
             "pdf": {"type": "file_upload", "file_upload": {"id": upload_id},
                     "caption": [{"type": "text", "text": {"content": (caption or "")[:TEXT_LIMIT]}}]
                     if caption else []}}
    children = [block] + ([paragraph(marker, "gray")] if marker else [])
    request("PATCH", "/blocks/%s/children" % checked_id(flat_id, "flat id"), {"children": children})


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
