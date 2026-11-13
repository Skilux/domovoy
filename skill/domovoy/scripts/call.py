#!/usr/bin/env python3
"""DOMOVOY call command: one Interested flat -> call_context -> phone server -> rechecked result -> Notion.

  call.py check  --windows W [--page ID] [--listing F]   build and validate only, contacts nobody
  call.py run    --windows W [--page ID] [--listing F]   post the call, poll, recheck, update the shortlist
  call.py start  --windows W [--page ID] [--listing F]   post the call and return at once; finish with resume
  call.py resume --page ID [--windows W]                 fetch the result again for a call already posted;
                                                         posts nothing. W is needed only when the call was
                                                         not posted from this machine (flat must be Calling)

W and F are a JSON file path, "-" for stdin, or inline JSON. Output is one JSON object on stdout.
Paths: config.json is DOMOVOY_CONFIG, else the skill folder. The env file is DOMOVOY_ENV_FILE, else
phone.env_file in config.json, else ~/.config/domovoy/.env. Call state is kept in DOMOVOY_STATE_DIR, else
.state in the skill folder. Nothing depends on the working directory, and nothing reads a terminal.
Exit codes: 0 handled, 2 refused (nothing was contacted), 1 error.

SHORTLIST INTERFACE. call.py reaches the shortlist only through the module named in config.json
"backend.module" (scripts/notion.py; the modules in tests/ are local fakes). cfg is the parsed config.json.
load_backend() accepts either of two shapes, so the module needs one of them, not both.

Shape A:
  list_pages(cfg, status) -> list of {"notion_page_id": str, "title": str, "url": str, "status": str,
                                      "listing": dict}
  set_status(cfg, notion_page_id, status)
  append(cfg, notion_page_id, text)

Shape B:
  list_flats(cfg, status=None) -> list of {"id": str, "title": str, "url": str, "status": str}
  get_flat(cfg, flat_id)       -> {"id", "title", "url", "listing": dict, "text": str}
  set_status(cfg, flat_id, status)
  append(cfg, flat_id, text)

Both take status None for every row, and every row carries its "status". Optional in both: a listed row may
carry "interested": true, read from the user's "Interested?" column. A flat is callable when its Status is
Interested, or when "interested" is true whatever its Status, so a retry after a failed call is allowed.
call.py sets Calling and then the final status on each call.

Optional in both: set_viewing_date(cfg, id, start) is called after a booked result that passes the
recheck, with start as ISO 8601 with offset.

The id is an opaque Notion page id string. "listing" holds the flat's fields under the call_context
names (property_id, address, url, collected_at, rent, total_monthly, upfront, kauce, commission,
move_in_date, lease_type, missing_furniture_cost, unknowns). Unknown values are None. Extra keys are
passed through to the call_context. No realtor contacts in "listing". get_flat is called only when a
listed flat has no "listing". append gets plain text, lines separated by "\n", for the end of the page
body. Errors are raised as RuntimeError with a message for the user.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.expanduser(os.environ.get("DOMOVOY_STATE_DIR") or os.path.join(ROOT, ".state"))
DEFAULT_ENV_FILE = "~/.config/domovoy/.env"
MARKER = "domovoy-call: %s"
PAGE_ID = "notion_page_id"
TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


class Refusal(Exception):
    pass


def load_config():
    path = os.path.expanduser(os.environ.get("DOMOVOY_CONFIG") or os.path.join(ROOT, "config.json"))
    if not os.path.exists(path):
        raise RuntimeError("config not found: %s (copy config.example.json to config.json)" % path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_backend(cfg):
    path = os.path.join(ROOT, cfg["backend"]["module"])
    if not os.path.exists(path):
        raise RuntimeError("shortlist backend %s not found (config backend.module)" % cfg["backend"]["module"])
    spec = importlib.util.spec_from_file_location("domovoy_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Shortlist(module)


class Shortlist:
    def __init__(self, module):
        self.module = module
        self.set_status = module.set_status
        self.append = module.append

    def list_pages(self, cfg, status):
        m = self.module
        rows = m.list_pages(cfg, status) if hasattr(m, "list_pages") else m.list_flats(cfg, status)
        pages = []
        for row in rows:
            if status is not None and row.get("status", status) != status:
                continue
            page_id = row.get(PAGE_ID) or row.get("id")
            if not isinstance(row.get("listing"), dict) and hasattr(m, "get_flat"):
                row = dict(row, **m.get_flat(cfg, page_id))
            pages.append(dict(row, **{PAGE_ID: str(page_id)}))
        return pages

    def set_viewing_date(self, cfg, page_id, start):
        if hasattr(self.module, "set_viewing_date"):
            self.module.set_viewing_date(cfg, page_id, start)


def budget_cap(cfg):
    if cfg["call_context"].get("budget_cap") is not None:
        return cfg["call_context"]["budget_cap"]
    profiles = cfg.get("profiles") or []
    profile = next((p for p in profiles if p.get("id") == cfg.get("active_profile")), None)
    if profile is None and len(profiles) == 1:
        profile = profiles[0]
    if profile is None:
        raise Refusal("no active profile: set active_profile to one of the profiles[] ids in config.json")
    return profile["requirements"]["max_total_monthly"]


def load_schema(name):
    with open(os.path.join(ROOT, "reference", name + ".schema.json"), encoding="utf-8") as f:
        return json.load(f)


def validate(value, schema, path="$"):
    errors = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(TYPES[t](value) for t in types):
            return ["%s: expected %s, got %s" % (path, " or ".join(types), json.dumps(value)[:60])]
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %s is not one of %s" % (path, json.dumps(value)[:60], json.dumps(schema["enum"])))
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append("%s: is empty" % path)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append("%s: needs at least %d item(s)" % (path, schema["minItems"]))
        for i, item in enumerate(value):
            errors += validate(item, schema.get("items", {}), "%s[%d]" % (path, i))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append("%s.%s: missing" % (path, key))
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors += validate(value[key], sub, "%s.%s" % (path, key))
    return errors


def parse_time(text):
    if not isinstance(text, str):
        return None
    try:
        t = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def check_windows(windows):
    errors = []
    for i, w in enumerate(windows if isinstance(windows, list) else []):
        start, end = parse_time((w or {}).get("start")), parse_time((w or {}).get("end"))
        if not start or not end:
            errors.append("$.available_windows[%d]: start and end must be ISO 8601 with offset" % i)
        elif start >= end:
            errors.append("$.available_windows[%d]: start is not before end" % i)
    return errors


def monthly_after_call(context, result):
    base = context.get("total_monthly")
    extra = [c.get("amount") for c in result.get("new_costs") or [] if c.get("recurring")]
    if base is None or any(a is None for a in extra):
        return None
    return base + sum(extra)


def recheck(context, result):
    errors = validate(result, load_schema("submit_call_result"))
    if errors:
        return False, "result does not match the contract: " + "; ".join(errors[:3])
    if result["property_id"] != context["property_id"]:
        return False, "result is for another property_id"
    if result["outcome"] != "booked":
        return False, "the call ended without an agreed viewing"
    start = parse_time(result["viewing_start"])
    if start is None:
        return False, "booked without a valid viewing_start"
    inside = any(parse_time(w["start"]) <= start < parse_time(w["end"]) for w in context["available_windows"])
    if not inside:
        return False, "agreed time %s is outside the approved windows" % result["viewing_start"]
    total = monthly_after_call(context, result)
    if total is None:
        return False, "monthly total is unknown, so the budget cannot be confirmed"
    if total > context["budget_cap"]:
        return False, "monthly total %d CZK is over the budget cap %d CZK" % (total, context["budget_cap"])
    return True, None


def read_json_arg(arg):
    if arg == "-":
        return json.load(sys.stdin)
    if arg.lstrip()[:1] in "[{":
        return json.loads(arg)
    with open(os.path.expanduser(arg), encoding="utf-8") as f:
        return json.load(f)


def find_listing(page, listing_arg):
    if not listing_arg:
        if isinstance(page.get("listing"), dict):
            return page["listing"]
        raise Refusal("the shortlist gave no listing fields for this page: pass --listing with them as JSON")
    data = read_json_arg(listing_arg)
    if not isinstance(data, dict):
        raise Refusal("--listing must be one JSON object with the listing fields")
    return data


def build_context(cfg, page, windows, listing_arg=None):
    schema = load_schema("call_context")
    context = dict(find_listing(page, listing_arg))
    for key, sub in schema["properties"].items():
        if key not in context and sub.get("type") == "array":
            context[key] = []
        elif key not in context and (None in sub.get("enum", []) or "null" in sub.get("type", [])):
            context[key] = None
    context.update(cfg["call_context"])
    context["budget_cap"] = budget_cap(cfg)
    context[PAGE_ID] = page[PAGE_ID]
    context["available_windows"] = windows
    errors = validate(context, schema) + check_windows(windows)
    if errors:
        raise Refusal("call_context is not valid: " + "; ".join(errors))
    return context


def phone_setting(cfg, name):
    phone = cfg["phone"]
    env_name = phone.get(name + "_env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    env_file = os.environ.get("DOMOVOY_ENV_FILE") or phone.get("env_file") or DEFAULT_ENV_FILE
    path = os.path.expanduser(env_file)
    if env_name and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key.replace("export ", "").strip() == env_name and value:
                    return value.strip().strip("'\"")
    if phone.get(name):
        return phone[name]
    raise RuntimeError("phone %s is not set (%s in the environment, in %s, or phone.%s in config.json)"
                       % (name, env_name, env_file, name))


def phone_request(cfg, method, path, body=None):
    url = phone_setting(cfg, "url").rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "content-type": "application/json", "x-domovoy-secret": phone_setting(cfg, "secret")})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw.decode() or "null")
    except ValueError:
        return status, raw.decode(errors="replace")[:200]


def handled_path():
    return os.path.join(STATE_DIR, "handled.json")


def seen_conversations():
    if not os.path.exists(handled_path()):
        return set()
    with open(handled_path(), encoding="utf-8") as f:
        return set(json.load(f))


def remember(conversation_id):
    seen = sorted(seen_conversations() | {conversation_id})
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(handled_path(), "w", encoding="utf-8") as f:
        json.dump(seen, f)


def marker_id(conversation_id):
    return re.sub(r"[^\w.:-]", "_", str(conversation_id))[:120]


def fetch_result(cfg, property_id):
    status, body = phone_request(cfg, "GET", "/api/result/" + urllib.parse.quote(property_id, safe=""))
    if status == 404:
        return None
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError("phone server answered %s to the result request" % status)
    return body["result"] if isinstance(body.get("result"), dict) else body


def poll(cfg, property_id, seen):
    phone = cfg["phone"]
    deadline = time.time() + phone["timeout_seconds"]
    while True:
        try:
            result = fetch_result(cfg, property_id)
        except (RuntimeError, OSError) as e:
            result = None
            print("poll: %s" % e, file=sys.stderr)
        if result is not None and marker_id(result.get("conversation_id")) not in seen:
            return result
        if time.time() + phone["poll_seconds"] > deadline:
            return None
        time.sleep(phone["poll_seconds"])


def clean(text, limit=600):
    text = re.sub(r"\S+@\S+", "[contact removed]", str(text))
    text = re.sub(r"(?:\+|00)?\d(?:[\s-]?\d){8,}", "[contact removed]", text)
    text = re.sub(r"\s+", " ", text.replace("<", "(").replace(">", ")").replace("@", "(at)"))
    return text.strip()[:limit]


def comment_body(cfg, context, result, booked, reason):
    lines = ["Call result: %s" % cfg["statuses"]["booked" if booked else "not_booked"], ""]
    if result is not None:
        lines += ["Demo call in the browser with a consenting demo participant. No real viewing was arranged.", ""]
    if booked:
        lines.append("- Viewing: %s" % clean(result["viewing_start"]))
    else:
        lines.append("- Reason: %s" % reason)
    if result is None:
        return "\n".join(lines)
    total = monthly_after_call(context, result)
    lines.append("- Monthly total after the call: %s (budget cap %d CZK)"
                 % ("unknown" if total is None else "%d CZK" % total, context["budget_cap"]))
    if isinstance(result.get("summary"), str) and result["summary"].strip():
        lines.append("- Summary: %s" % clean(result["summary"]))
    for a in [a for a in result.get("answers") or [] if isinstance(a, dict)]:
        lines.append("- Asked: %s Answer: %s" % (clean(a.get("question"), 200), clean(a.get("answer"), 300)))
    for c in [c for c in result.get("new_costs") or [] if isinstance(c, dict)]:
        amount = "unknown amount" if c.get("amount") is None else "%s CZK" % clean(c.get("amount"), 20)
        lines.append("- New cost: %s, %s, %s" % (clean(c.get("label"), 120), amount,
                                                  "monthly" if c.get("recurring") else "one-time"))
    lines += ["", MARKER % marker_id(result.get("conversation_id"))]
    return "\n".join(lines)


def apply_result(cfg, backend, page, context, result):
    out = {PAGE_ID: page[PAGE_ID], "page_url": page.get("url"), "property_id": context["property_id"],
           "already_handled": False, "create_event": False}
    if result is not None and marker_id(result.get("conversation_id")) in seen_conversations():
        out.update(already_handled=True, note="this conversation_id was handled before; nothing was changed")
        return out
    if result is None:
        booked, reason = False, "no result from the phone server within %d s" % cfg["phone"]["timeout_seconds"]
    else:
        booked, reason = recheck(context, result)
        out["conversation_id"] = result.get("conversation_id")
        out["summary"] = clean(result.get("summary") or "")
        out["answers"] = [{"question": clean(a.get("question"), 200), "answer": clean(a.get("answer"), 300)}
                          for a in result.get("answers") or [] if isinstance(a, dict)]
        out["new_costs"] = [c for c in result.get("new_costs") or [] if isinstance(c, dict)]
    status = cfg["statuses"]["booked" if booked else "not_booked"]
    backend.append(cfg, page[PAGE_ID], comment_body(cfg, context, result, booked, reason))
    if result is not None:
        remember(marker_id(result.get("conversation_id")))
    backend.set_status(cfg, page[PAGE_ID], status)
    out.update(status=status, booked=booked, reason=reason)
    if booked:
        start = parse_time(result["viewing_start"])
        cal = cfg.get("calendar", {})
        out.update(create_event=True, event={
            "title": cal.get("event_title", "Viewing (demo): {address}").format(address=context["address"]),
            "start": start.isoformat(),
            "end": (start + datetime.timedelta(minutes=cal.get("window_minutes", 60))).isoformat(),
            "description": "%s\n%s" % (page.get("url") or "", clean(result["summary"])),
        })
        backend.set_viewing_date(cfg, page[PAGE_ID], start.isoformat())
    return out


def state_path(page_id):
    return os.path.join(STATE_DIR, "page-%s.json" % re.sub(r"[^\w.-]", "_", str(page_id)))


def callable_pages(cfg, backend):
    """Flats that may be called: Status = Interested, or "Interested?" = Yes whatever the Status. One query."""
    interested = cfg["statuses"]["interested"]
    return [p for p in backend.list_pages(cfg, None) if p.get("status") == interested or p.get("interested") is True]


def pick_page(cfg, backend, page_id):
    interested = cfg["statuses"]["interested"]
    pages = callable_pages(cfg, backend)
    if not pages:
        raise Refusal('no flat is marked Interested; nobody was contacted. Set "Interested?" to Yes on one flat, '
                      'whatever its Status, or set its Status to %s.' % interested)
    if page_id is not None:
        page = next((p for p in pages if p[PAGE_ID] == page_id), None)
        if page is None:
            raise Refusal('page %s is not marked Interested (Interested? Yes, or Status %s); nobody was contacted'
                          % (page_id, interested))
        return page
    if len(pages) > 1:
        raise Refusal("%d flats are marked Interested; ask which one and pass --page ID: %s" % (
            len(pages), "; ".join("%s %s" % (p[PAGE_ID], p.get("title")) for p in pages)))
    return pages[0]


def cmd_start(cfg, backend, args, post, wait=True):
    windows = read_json_arg(args.windows)
    page = pick_page(cfg, backend, args.page)
    context = build_context(cfg, page, windows, args.listing)
    warnings = []
    if context["total_monthly"] is None:
        warnings.append("total_monthly is unknown: the recheck will end in Not booked")
    elif context["total_monthly"] > context["budget_cap"]:
        warnings.append("total_monthly is over budget_cap: the recheck will end in Not booked")
    if not post:
        return {"valid": True, "posted": False, "warnings": warnings, "call_context": context}
    os.makedirs(STATE_DIR, exist_ok=True)
    status, body = phone_request(cfg, "POST", "/api/call", context)
    if not 200 <= status < 300:
        raise RuntimeError("phone server refused the call_context with %s: %s; the flat's Status is not changed"
                           % (status, json.dumps(body)[:200]))
    os.makedirs(STATE_DIR, exist_ok=True)
    saved = {"context": context, "page": {PAGE_ID: page[PAGE_ID], "url": page.get("url")}}
    with open(state_path(page[PAGE_ID]), "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2)
    backend.set_status(cfg, page[PAGE_ID], cfg["statuses"]["calling"])
    if not wait:
        return {"posted": True, PAGE_ID: page[PAGE_ID], "page_url": page.get("url"),
                "property_id": context["property_id"], "status": cfg["statuses"]["calling"],
                "warnings": warnings, "next": "call.py resume --page %s" % page[PAGE_ID]}
    print("call posted for page %s, waiting for the result" % page[PAGE_ID], file=sys.stderr)
    result = poll(cfg, context["property_id"], seen_conversations())
    if result is None:
        # Remembered so that resume may still apply a result that arrives after this timeout.
        with open(state_path(page[PAGE_ID]), "w", encoding="utf-8") as f:
            json.dump(dict(saved, timed_out=True), f, indent=2)
    out = apply_result(cfg, backend, page, context, result)
    out["warnings"] = warnings
    return out


def cmd_resume(cfg, backend, args):
    calling = cfg["statuses"]["calling"]
    if args.page is not None and os.path.exists(state_path(args.page)):
        with open(state_path(args.page), encoding="utf-8") as f:
            saved = json.load(f)
    elif args.page is not None and args.windows:
        page = next((p for p in backend.list_pages(cfg, calling) if p[PAGE_ID] == args.page), None)
        if page is None:
            raise Refusal("page %s is not in %s; nothing was changed" % (args.page, calling))
        saved = {"context": build_context(cfg, page, read_json_arg(args.windows), args.listing),
                 "page": {PAGE_ID: page[PAGE_ID], "url": page.get("url")}}
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_path(args.page), "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=2)
    else:
        raise Refusal("resume needs --page ID, and --windows W when the call was not posted from this machine")
    result = fetch_result(cfg, saved["context"]["property_id"])
    if result is None:
        raise Refusal("the phone server has no result for %s yet" % saved["context"]["property_id"])
    if marker_id(result.get("conversation_id")) not in seen_conversations():
        allowed = [calling] + ([cfg["statuses"]["not_booked"]] if saved.get("timed_out") else [])
        if not any(p[PAGE_ID] == args.page for status in allowed for p in backend.list_pages(cfg, status)):
            raise Refusal("page %s is not in %s; nothing was changed" % (args.page, calling))
    out = apply_result(cfg, backend, saved["page"], saved["context"], result)
    if saved.pop("timed_out", None):
        with open(state_path(args.page), "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=2)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "run", "start", "resume"])
    parser.add_argument("--windows", help="free windows: [{start, end}] as a file, '-' or inline JSON")
    parser.add_argument("--page", help="notion_page_id of the flat, when several are Interested")
    parser.add_argument("--listing", help="listing fields as a file, '-' or inline JSON")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        cfg = load_config()
        backend = load_backend(cfg)
        if args.command == "resume":
            out = cmd_resume(cfg, backend, args)
        elif not args.windows:
            raise Refusal("--windows is required: free windows from the calendar as [{start, end}]")
        else:
            out = cmd_start(cfg, backend, args, post=args.command != "check", wait=args.command != "start")
    except Refusal as e:
        print(json.dumps({"refused": True, "reason": str(e)}, indent=2, ensure_ascii=False))
        return 2
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, indent=2))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
