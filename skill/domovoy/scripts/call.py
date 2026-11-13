#!/usr/bin/env python3
"""DOMOVOY call command: one Interested card -> call_context -> phone server -> rechecked result -> board.

  call.py check  --windows W [--issue N] [--listing F]   build and validate only, contacts nobody
  call.py run    --windows W [--issue N] [--listing F]   post the call, poll, recheck, update the board
  call.py resume --issue N                               fetch the result again for a call already posted

W and F are a JSON file path, "-" for stdin, or inline JSON. Output is one JSON object on stdout.
Exit codes: 0 handled, 2 refused (nothing was contacted), 1 error.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board  # noqa: E402

ROOT = board.ROOT
STATE_DIR = os.path.join(ROOT, ".state")
MARKER = "<!-- domovoy-call: %s -->"
MARKER_RE = re.compile(r"<!-- domovoy-call: (\S+) -->")
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


def find_listing(issue, property_id, listing_arg):
    if listing_arg:
        data = read_json_arg(listing_arg)
        if isinstance(data, dict) and isinstance(data.get("listings"), list):
            data = data["listings"]
        if isinstance(data, list):
            data = next((r for r in data if isinstance(r, dict) and r.get("property_id") == property_id), None)
            if data is None:
                raise Refusal("no record with property_id %s in the listing file" % property_id)
        return data
    for block in re.findall(r"```json\s*\n(.*?)```", issue.get("body") or "", re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise Refusal("no listing data: pass --listing with the shortlist.json record or the issue's fields as JSON")


def build_context(cfg, issue, windows, listing_arg=None):
    found = re.search(cfg["issue"]["property_id_pattern"], issue.get("body") or "")
    issue_pid = found.group(1) if found else None
    listing = find_listing(issue, issue_pid, listing_arg)
    schema = load_schema("call_context")
    context = dict(listing)
    for key, sub in schema["properties"].items():
        if key not in context and sub.get("type") == "array":
            context[key] = []
        elif key not in context and (None in sub.get("enum", []) or "null" in sub.get("type", [])):
            context[key] = None
    context.update(cfg["call_context"])
    context.setdefault("property_id", issue_pid)
    context["issue_number"] = issue["number"]
    context["available_windows"] = windows
    errors = validate(context, schema) + check_windows(windows)
    if issue_pid and context.get("property_id") != issue_pid:
        errors.append("$.property_id: listing says %s, issue body says %s" % (context.get("property_id"), issue_pid))
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


def seen_conversations(issue):
    return set(m for c in issue.get("comments") or [] for m in MARKER_RE.findall(c.get("body") or ""))


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
    statuses = cfg["board"]["statuses"]
    lines = ["**Call result: %s**" % statuses["booked" if booked else "not_booked"], ""]
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


def apply_result(cfg, issue_number, context, result):
    statuses = cfg["board"]["statuses"]
    issue = board.get_issue(cfg, issue_number)
    out = {"issue_number": issue["number"], "issue_url": issue["url"], "property_id": context["property_id"],
           "already_handled": False, "create_event": False}
    if result is not None and marker_id(result.get("conversation_id")) in seen_conversations(issue):
        out.update(already_handled=True, note="this conversation_id was handled before; nothing was changed")
        return out
    if result is None:
        booked, reason = False, "no result from the phone server within %d s" % cfg["phone"]["timeout_seconds"]
    else:
        booked, reason = recheck(context, result)
        out["conversation_id"] = result.get("conversation_id")
    status = statuses["booked" if booked else "not_booked"]
    out["comment_url"] = board.comment(cfg, issue["number"], comment_body(cfg, context, result, booked, reason))
    board.set_status(cfg, issue["number"], status)
    out.update(status=status, booked=booked, reason=reason)
    if booked:
        start = parse_time(result["viewing_start"])
        cal = cfg.get("calendar", {})
        out.update(create_event=True, event={
            "title": cal.get("event_title", "Viewing (demo): {address}").format(address=context["address"]),
            "start": start.isoformat(),
            "end": (start + datetime.timedelta(minutes=cal.get("window_minutes", 60))).isoformat(),
            "description": "%s\n%s" % (issue["url"], clean(result["summary"])),
        })
    return out


def state_path(issue_number):
    return os.path.join(STATE_DIR, "issue-%d.context.json" % int(issue_number))


def pick_card(cfg, issue_number):
    interested = cfg["board"]["statuses"]["interested"]
    cards = board.list_cards(cfg, interested)
    if not cards:
        raise Refusal("no card has Status = %s; nobody was contacted. Move one card to %s on the board first."
                      % (interested, interested))
    if issue_number is not None:
        card = next((c for c in cards if c["issue_number"] == issue_number), None)
        if card is None:
            raise Refusal("issue #%d is not in %s; nobody was contacted" % (issue_number, interested))
        return card
    if len(cards) > 1:
        raise Refusal("%d cards are in %s; ask which one and pass --issue N: %s" % (
            len(cards), interested, "; ".join("#%d %s" % (c["issue_number"], c["title"]) for c in cards)))
    return cards[0]


def cmd_start(cfg, args, post):
    windows = read_json_arg(args.windows)
    card = pick_card(cfg, args.issue)
    issue = board.get_issue(cfg, card["issue_number"])
    context = build_context(cfg, issue, windows, args.listing)
    warnings = []
    if context["total_monthly"] is None:
        warnings.append("total_monthly is unknown: the recheck will end in Not booked")
    elif context["total_monthly"] > context["budget_cap"]:
        warnings.append("total_monthly is over budget_cap: the recheck will end in Not booked")
    if not post:
        return {"valid": True, "posted": False, "warnings": warnings, "call_context": context}
    seen = seen_conversations(issue)
    status, body = phone_request(cfg, "POST", "/api/call", context)
    if not 200 <= status < 300:
        raise RuntimeError("phone server refused the call_context with %s: %s; the card stays in %s"
                           % (status, json.dumps(body)[:200], card["status"]))
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(issue["number"]), "w") as f:
        json.dump(context, f, indent=2)
    board.set_status(cfg, issue["number"], cfg["board"]["statuses"]["calling"])
    print("call posted for issue #%d, waiting for the result" % issue["number"], file=sys.stderr)
    out = apply_result(cfg, issue["number"], context, poll(cfg, context["property_id"], seen))
    out["warnings"] = warnings
    return out


def cmd_resume(cfg, args):
    if args.issue is None or not os.path.exists(state_path(args.issue)):
        raise Refusal("resume needs --issue N for a call posted from this machine")
    with open(state_path(args.issue)) as f:
        context = json.load(f)
    result = fetch_result(cfg, context["property_id"])
    if result is None:
        raise Refusal("the phone server has no result for %s yet" % context["property_id"])
    issue = board.get_issue(cfg, args.issue)
    calling = cfg["board"]["statuses"]["calling"]
    if marker_id(result.get("conversation_id")) not in seen_conversations(issue):
        card = next((c for c in board.list_cards(cfg) if c["issue_number"] == args.issue), None)
        if card is None or card["status"] != calling:
            raise Refusal("issue #%d is not in %s; nothing was changed" % (args.issue, calling))
    return apply_result(cfg, args.issue, context, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "run", "resume"])
    parser.add_argument("--windows", help="free windows: [{start, end}] as a file, '-' or inline JSON")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--listing", help="listing record(s) as a file, '-' or inline JSON")
    args = parser.parse_args(argv)
    try:
        cfg = board.load_config()
        if args.command == "resume":
            out = cmd_resume(cfg, args)
        elif not args.windows:
            raise Refusal("--windows is required: free windows from the calendar as [{start, end}]")
        else:
            out = cmd_start(cfg, args, post=args.command == "run")
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
