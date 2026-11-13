#!/usr/bin/env python3
"""DOMOVOY call command: one Interested flat -> call_context -> phone server -> rechecked result -> shortlist.

  call.py check  --windows W [--flat ID] [--listing F]   build and validate only, contacts nobody
  call.py run    --windows W [--flat ID] [--listing F]   post the call, poll, recheck, update the shortlist
  call.py resume --flat ID                               fetch the result again for a call already posted

W and F are a JSON file path, "-" for stdin, or inline JSON. Output is one JSON object on stdout.
Exit codes: 0 handled, 2 refused (nothing was contacted), 1 error.

The shortlist is reached only through the module named in config "backend.module". It must offer:
  list_flats(cfg, status) -> [{"id", "title", "url", "status"}]
  get_flat(cfg, id)       -> {"id", "title", "url", "listing": {call_context fields} or None, "text": page text or ""}
  set_status(cfg, id, status)
  append(cfg, id, text)
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
STATE_DIR = os.path.join(ROOT, ".state")
MARKER = "domovoy-call: %s"
MARKER_RE = re.compile(r"domovoy-call: ([\w.:-]+)")
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
    path = os.environ.get("DOMOVOY_CONFIG") or os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        raise RuntimeError("config not found: %s (copy config.example.json to config.json)" % path)
    with open(path) as f:
        return json.load(f)


def load_backend(cfg):
    path = os.path.join(ROOT, cfg["backend"]["module"])
    if not os.path.exists(path):
        raise RuntimeError("shortlist backend %s not found (config backend.module)" % cfg["backend"]["module"])
    spec = importlib.util.spec_from_file_location("domovoy_backend", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    with open(os.path.join(ROOT, "reference", name + ".schema.json")) as f:
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
    with open(os.path.expanduser(arg)) as f:
        return json.load(f)


def find_listing(flat, listing_arg):
    if not listing_arg:
        if isinstance(flat.get("listing"), dict):
            return flat["listing"]
        raise Refusal("the shortlist gave no listing fields for this flat: pass --listing with them as JSON")
    data = read_json_arg(listing_arg)
    if isinstance(data, list):
        wanted = (flat.get("listing") or {}).get("property_id")
        rows = [r for r in data if isinstance(r, dict) and (wanted is None or r.get("property_id") == wanted)]
        if len(rows) != 1:
            raise Refusal("the listing file has %d matching records, need exactly 1" % len(rows))
        data = rows[0]
    return data


def build_context(cfg, flat, windows, listing_arg=None):
    schema = load_schema("call_context")
    context = dict(find_listing(flat, listing_arg))
    for key, sub in schema["properties"].items():
        if key not in context and sub.get("type") == "array":
            context[key] = []
        elif key not in context and (None in sub.get("enum", []) or "null" in sub.get("type", [])):
            context[key] = None
    context.update(cfg["call_context"])
    context["budget_cap"] = budget_cap(cfg)
    context[cfg["backend"]["id_field"]] = flat["id"]
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
    path = os.path.expanduser(phone.get("env_file") or "")
    if env_name and os.path.isfile(path):
        with open(path) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key.replace("export ", "").strip() == env_name and value:
                    return value.strip().strip("'\"")
    if phone.get(name):
        return phone[name]
    raise RuntimeError("phone %s is not set (%s in the environment, in %s, or phone.%s in config.json)"
                       % (name, env_name, phone.get("env_file"), name))


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


def seen_conversations(flat):
    seen = set(MARKER_RE.findall(flat.get("text") or ""))
    if os.path.exists(handled_path()):
        with open(handled_path()) as f:
            seen |= set(json.load(f))
    return seen


def remember(conversation_id):
    os.makedirs(STATE_DIR, exist_ok=True)
    seen = set()
    if os.path.exists(handled_path()):
        with open(handled_path()) as f:
            seen = set(json.load(f))
    with open(handled_path(), "w") as f:
        json.dump(sorted(seen | {conversation_id}), f)


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


def apply_result(cfg, backend, flat_id, context, result):
    flat = backend.get_flat(cfg, flat_id)
    out = {"flat_id": flat["id"], "flat_url": flat.get("url"), "property_id": context["property_id"],
           "already_handled": False, "create_event": False}
    if result is not None and marker_id(result.get("conversation_id")) in seen_conversations(flat):
        out.update(already_handled=True, note="this conversation_id was handled before; nothing was changed")
        return out
    if result is None:
        booked, reason = False, "no result from the phone server within %d s" % cfg["phone"]["timeout_seconds"]
    else:
        booked, reason = recheck(context, result)
        out["conversation_id"] = result.get("conversation_id")
        remember(marker_id(result.get("conversation_id")))
    status = cfg["statuses"]["booked" if booked else "not_booked"]
    backend.append(cfg, flat["id"], comment_body(cfg, context, result, booked, reason))
    backend.set_status(cfg, flat["id"], status)
    out.update(status=status, booked=booked, reason=reason)
    if booked:
        start = parse_time(result["viewing_start"])
        cal = cfg.get("calendar", {})
        out.update(create_event=True, event={
            "title": cal.get("event_title", "Viewing (demo): {address}").format(address=context["address"]),
            "start": start.isoformat(),
            "end": (start + datetime.timedelta(minutes=cal.get("window_minutes", 60))).isoformat(),
            "description": "%s\n%s" % (flat.get("url") or "", clean(result["summary"])),
        })
        if hasattr(backend, "set_viewing_date"):
            backend.set_viewing_date(cfg, flat["id"], start.isoformat())
    return out


def state_path(flat_id):
    return os.path.join(STATE_DIR, "flat-%s.context.json" % re.sub(r"[^\w.-]", "_", str(flat_id)))


def pick_flat(cfg, backend, flat_id):
    interested = cfg["statuses"]["interested"]
    flats = backend.list_flats(cfg, interested)
    if not flats:
        raise Refusal("no flat has Status = %s; nobody was contacted. Move one flat to %s first."
                      % (interested, interested))
    if flat_id is not None:
        flat = next((f for f in flats if str(f["id"]) == str(flat_id)), None)
        if flat is None:
            raise Refusal("flat %s is not in %s; nobody was contacted" % (flat_id, interested))
        return flat
    if len(flats) > 1:
        raise Refusal("%d flats are in %s; ask which one and pass --flat ID: %s" % (
            len(flats), interested, "; ".join("%s %s" % (f["id"], f["title"]) for f in flats)))
    return flats[0]


def cmd_start(cfg, backend, args, post):
    windows = read_json_arg(args.windows)
    flat = backend.get_flat(cfg, pick_flat(cfg, backend, args.flat)["id"])
    context = build_context(cfg, flat, windows, args.listing)
    warnings = []
    if context["total_monthly"] is None:
        warnings.append("total_monthly is unknown: the recheck will end in Not booked")
    elif context["total_monthly"] > context["budget_cap"]:
        warnings.append("total_monthly is over budget_cap: the recheck will end in Not booked")
    if not post:
        return {"valid": True, "posted": False, "warnings": warnings, "call_context": context}
    seen = seen_conversations(flat)
    status, body = phone_request(cfg, "POST", "/api/call", context)
    if not 200 <= status < 300:
        raise RuntimeError("phone server refused the call_context with %s: %s; the flat stays in %s"
                           % (status, json.dumps(body)[:200], cfg["statuses"]["interested"]))
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(flat["id"]), "w") as f:
        json.dump(context, f, indent=2)
    backend.set_status(cfg, flat["id"], cfg["statuses"]["calling"])
    print("call posted for flat %s, waiting for the result" % flat["id"], file=sys.stderr)
    out = apply_result(cfg, backend, flat["id"], context, poll(cfg, context["property_id"], seen))
    out["warnings"] = warnings
    return out


def cmd_resume(cfg, backend, args):
    if args.flat is None or not os.path.exists(state_path(args.flat)):
        raise Refusal("resume needs --flat ID for a call posted from this machine")
    with open(state_path(args.flat)) as f:
        context = json.load(f)
    result = fetch_result(cfg, context["property_id"])
    if result is None:
        raise Refusal("the phone server has no result for %s yet" % context["property_id"])
    calling = cfg["statuses"]["calling"]
    if marker_id(result.get("conversation_id")) not in seen_conversations(backend.get_flat(cfg, args.flat)):
        if not any(str(f["id"]) == str(args.flat) for f in backend.list_flats(cfg, calling)):
            raise Refusal("flat %s is not in %s; nothing was changed" % (args.flat, calling))
    return apply_result(cfg, backend, args.flat, context, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "run", "resume"])
    parser.add_argument("--windows", help="free windows: [{start, end}] as a file, '-' or inline JSON")
    parser.add_argument("--flat", help="shortlist id of the flat, when several are Interested")
    parser.add_argument("--listing", help="listing record(s) as a file, '-' or inline JSON")
    args = parser.parse_args(argv)
    try:
        cfg = load_config()
        backend = load_backend(cfg)
        if args.command == "resume":
            out = cmd_resume(cfg, backend, args)
        elif not args.windows:
            raise Refusal("--windows is required: free windows from the calendar as [{start, end}]")
        else:
            out = cmd_start(cfg, backend, args, post=args.command == "run")
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
