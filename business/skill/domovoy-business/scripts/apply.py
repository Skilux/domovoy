#!/usr/bin/env python3
"""DOMOVOY business edition: turn an agency's answers into a configured viewing desk.

  apply.py build    --business business.json --out DIR   write the setup into DIR
  apply.py check    --out DIR                            static checks on DIR; contacts nobody
  apply.py rehearse --out DIR [--save FILE]              run the core call.py on DIR against the FAKE phone
                                                         server with SYNTHETIC renters; no network, no voice

build writes, and never touches the core folders:
  DIR/domovoy.config.json   config for the core skill/domovoy/scripts/call.py (use DOMOVOY_CONFIG=...)
  DIR/agent/prompt.md       the voice prompt, in the place of phone/agent/prompt.md
  DIR/agent/agent.json      the agent config, in the place of phone/agent/agent.json
  DIR/leads.json            the agency's listings and enquiries (enquiries are kept on a rebuild)

The core is read, not copied: the phone block comes from skill/domovoy/config.example.json and the agent
config and its two client tools from phone/agent/agent.json. --repo names the checkout (default: this one).
Output is one JSON object on stdout. Exit 0 ok, 2 the answers or the setup are not valid, 1 error.
Standard library only.
"""
import argparse
import contextlib
import copy
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DEFAULT_REPO = os.path.abspath(os.path.join(SKILL, "..", "..", ".."))
BACKEND = "../../business/skill/domovoy-business/scripts/leads.py"
CONFIG_NAME = "domovoy.config.json"
NO_BUDGET_CHECK = 1000000000
PROMPT_VARIABLES = {"user_name", "realtor_name", "address", "unknowns", "available_windows", "context_text"}
STATUSES = {"interested": "Call approved", "calling": "Calling", "booked": "Viewing booked",
            "not_booked": "Not booked"}
OWN_STATUSES = {"new": "New enquiry", "closed": "Closed"}
LEASE_TYPES = ("najem", "podnajem", None)
MONEY = ("rent", "total_monthly", "upfront", "kauce", "commission", "missing_furniture_cost")
SECRET = re.compile(r"sk_[A-Za-z0-9]{16,}|phx_[A-Za-z0-9]{16,}|ntn_[A-Za-z0-9]{16,}|secret_[A-Za-z0-9]{16,}"
                    r"|apify_api_[A-Za-z0-9]{16,}|xi-api-key")
SENSITIVE = re.compile(r"nationalit|citizen|ethnic|\brace\b|religio|gender|sexual|pregnan|disab|marital|"
                       r"\bmarried\b|\bage\b|how old|children|kids|roma\b|foreign", re.IGNORECASE)
TEAM_ENV = "~/.config/domovoy/.env"


class Invalid(Exception):
    pass


def read_json(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return json.load(f)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def write_json(path, data):
    write(path, json.dumps(data, indent=2, ensure_ascii=False))


def variables(text):
    return set(re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text))


def need(errors, data, path, kind=str):
    value = data
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    ok = isinstance(value, kind) and not isinstance(value, bool) and (value or kind is not str)
    if kind is list:
        ok = isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
    if not ok:
        errors.append("%s: missing or not a %s" % (path, {str: "non-empty text", int: "whole number",
                                                           list: "list of texts"}[kind]))
    return value


def validate_business(biz):
    errors, warnings = [], []
    for path in ("agency.name", "agency.slug", "agency.assistant_name", "agency.viewing_agent_first_name",
                 "agency.offer", "voice.language", "voice.language_name", "voice.tone", "voice.first_message",
                 "viewings.calendar_id", "viewings.timezone", "viewings.from", "viewings.to",
                 "viewings.event_title", "handoff"):
        need(errors, biz, path)
    for path in ("voice.call_seconds", "voice.max_call_seconds", "viewings.days_ahead",
                 "viewings.window_minutes", "viewings.viewing_minutes", "viewings.max_windows"):
        need(errors, biz, path, int)
    for path in ("viewings.weekdays", "qualifying_questions", "rules", "may_promise", "must_not_promise"):
        need(errors, biz, path, list)
    if errors:
        return errors, warnings
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", biz["agency"]["slug"]):
        errors.append("agency.slug: use lower-case letters, digits and dashes")
    if biz["viewings"]["timezone"] != "Europe/Prague":
        errors.append("viewings.timezone: the core phone page and voice prompt are fixed to Europe/Prague")
    if biz["viewings"]["viewing_minutes"] > biz["viewings"]["window_minutes"]:
        errors.append("viewings.viewing_minutes is longer than viewings.window_minutes")
    extra = variables(biz["voice"]["first_message"]) - PROMPT_VARIABLES
    if extra:
        errors.append("voice.first_message uses variables the phone page does not send: %s" % sorted(extra))
    if "AI" not in biz["voice"]["first_message"] and biz["voice"]["language"] == "en":
        errors.append("voice.first_message must say the caller is an AI assistant")
    if not biz["qualifying_questions"]:
        warnings.append("no qualifying questions: the voice agent will only book a time")
    if len(biz["qualifying_questions"]) > 6:
        warnings.append("more than 6 qualifying questions makes the call long; the limit is %d s"
                        % biz["voice"]["max_call_seconds"])
    for kind in ("qualifying_questions", "rules"):
        for line in biz[kind]:
            if SENSITIVE.search(line):
                warnings.append("%s: %r may touch a protected characteristic. Ask the agency's lawyer "
                                "before using it; the person must confirm it in the chat." % (kind, line))
    if biz["voice"]["language"] != "en":
        warnings.append("voice.language is %r: the core is rehearsed in English only. Check in the ElevenLabs "
                        "dashboard that the agent's voice and model support this language."
                        % biz["voice"]["language"])
    listings = biz.get("listings")
    if not isinstance(listings, list) or not listings:
        errors.append("listings: at least one listing is needed")
        return errors, warnings
    seen = set()
    for i, item in enumerate(listings):
        where = "listings[%d]" % i
        if not isinstance(item, dict) or not re.fullmatch(r"[A-Za-z0-9][\w.-]{0,60}", str(item.get("id") or "")):
            errors.append("%s.id: needs letters, digits, dots or dashes" % where)
            continue
        if item["id"] in seen:
            errors.append("%s.id: %s is used twice" % (where, item["id"]))
        seen.add(item["id"])
        for key in ("address", "url", "collected_at"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                errors.append("%s.%s: missing" % (where, key))
        for key in MONEY:
            value = item.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                errors.append("%s.%s: whole CZK or null for unknown" % (where, key))
        if item.get("total_monthly") is None:
            errors.append("%s.total_monthly: required. The core call.py ends in Not booked when the monthly "
                          "total is unknown." % where)
        if item.get("lease_type") not in LEASE_TYPES:
            errors.append("%s.lease_type: najem, podnajem or null" % where)
        if not isinstance(item.get("facts") or {}, dict):
            errors.append("%s.facts: must be an object" % where)
    return errors, warnings


def bullets(lines, numbered=False):
    return "\n".join(("%d. %s" % (i + 1, line)) if numbered else ("- " + line) for i, line in enumerate(lines))


def render_prompt(biz):
    with open(os.path.join(SKILL, "templates", "prompt.md.tmpl"), encoding="utf-8") as f:
        text = f.read()
    values = {
        "assistant_name": biz["agency"]["assistant_name"],
        "agency_name": biz["agency"]["name"],
        "offer": biz["agency"]["offer"],
        "call_seconds": str(biz["voice"]["call_seconds"]),
        "language_name": biz["voice"]["language_name"],
        "tone": biz["voice"]["tone"],
        "rules": bullets(biz["rules"], numbered=True) if biz["rules"] else "No extra rules.",
        "viewing_minutes": str(biz["viewings"]["viewing_minutes"]),
        "may_promise": bullets(biz["may_promise"]),
        "must_not_promise": bullets(biz["must_not_promise"]),
        "handoff": biz["handoff"],
    }
    for key, value in values.items():
        if "{{" in value or "[[" in value:
            raise Invalid("the answer for %s contains {{ or [[, which the prompt reserves" % key)
        text = text.replace("[[%s]]" % key, value)
    return text.strip()


def reword(value):
    if isinstance(value, dict):
        return {k: reword(v) for k, v in value.items()}
    if isinstance(value, list):
        return [reword(v) for v in value]
    if isinstance(value, str):
        return value.replace("the realtor's", "the caller's").replace("the realtor", "the caller")
    return value


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [shape(v) for v in value]
    return value


def render_agent(biz, core_agent):
    out = copy.deepcopy(core_agent)
    first = biz["listings"][0]
    agent = out["agent"]
    agent["name"] = "%s viewing desk" % biz["agency"]["name"]
    agent["tags"] = ["domovoy-business", biz["agency"]["slug"]]
    conv = agent["conversation_config"]
    conv["agent"]["first_message"] = biz["voice"]["first_message"]
    conv["agent"]["language"] = biz["voice"]["language"]
    conv["agent"]["prompt"]["timezone"] = biz["viewings"]["timezone"]
    conv["conversation"]["max_duration_seconds"] = biz["voice"]["max_call_seconds"]
    conv["agent"]["dynamic_variables"]["dynamic_variable_placeholders"] = {
        "user_name": biz["agency"]["viewing_agent_first_name"],
        "realtor_name": "Sam",
        "address": first["address"],
        "unknowns": "\n".join("%d. %s" % (i + 1, q) for i, q in enumerate(biz["qualifying_questions"])),
        "available_windows": "1. Monday 16 November, 10:00 to 11:00 "
                             "(2026-11-16T10:00:00+01:00 to 2026-11-16T11:00:00+01:00)",
        "context_text": "address: %s\nrent: %s\ntotal_monthly: %s" % (first["address"], first.get("rent"),
                                                                       first["total_monthly"]),
    }
    out["tools"] = reword(out["tools"])
    return out


def render_config(biz, core_config, repo_path):
    v = biz["viewings"]
    phone = dict(core_config["phone"], url="", secret="",
                 env_file="~/.config/domovoy-%s/.env" % biz["agency"]["slug"])
    return {
        "_label": biz.get("_label") or "Generated by business/skill/domovoy-business/scripts/apply.py",
        "repo_path": repo_path,
        "backend": {"module": BACKEND},
        "statuses": dict(STATUSES),
        "phone": phone,
        "call_context": {"user_name": biz["agency"]["viewing_agent_first_name"], "budget_cap": NO_BUDGET_CHECK},
        "calendar": {
            "calendar_id": v["calendar_id"], "timezone": v["timezone"], "viewing_weekdays": v["weekdays"],
            "viewing_from": v["from"], "viewing_to": v["to"], "days_ahead": v["days_ahead"],
            "window_minutes": v["window_minutes"], "max_windows": v["max_windows"],
            "event_title": v["event_title"],
        },
        "business": {
            "edition": "viewing-desk",
            "agency_name": biz["agency"]["name"],
            "leads_file": "leads.json",
            "statuses": dict(OWN_STATUSES),
            "qualifying_questions": list(biz["qualifying_questions"]),
        },
    }


def build(args):
    biz = read_json(args.business)
    errors, warnings = validate_business(biz)
    if errors:
        raise Invalid("; ".join(errors))
    repo = os.path.abspath(os.path.expanduser(args.repo))
    core_agent = read_json(os.path.join(repo, "phone", "agent", "agent.json"))
    core_config = read_json(os.path.join(repo, "skill", "domovoy", "config.example.json"))
    out = os.path.abspath(os.path.expanduser(args.out))
    leads_file = os.path.join(out, "leads.json")
    leads = read_json(leads_file) if os.path.exists(leads_file) else {"enquiries": []}
    leads["_label"] = biz.get("_label") or "Private: listings and enquiries of %s" % biz["agency"]["name"]
    leads["listings"] = {item["id"]: {k: v for k, v in item.items() if k != "id"} for item in biz["listings"]}
    orphans = sorted({e["listing_id"] for e in leads["enquiries"]} - set(leads["listings"]))
    if orphans:
        raise Invalid("enquiries in %s name listings the answers no longer have: %s" % (leads_file, orphans))
    write(os.path.join(out, "agent", "prompt.md"), render_prompt(biz))
    write_json(os.path.join(out, "agent", "agent.json"), render_agent(biz, core_agent))
    write_json(os.path.join(out, CONFIG_NAME), render_config(biz, core_config, args.repo_path or "~/domovoy"))
    write_json(leads_file, leads)
    return {"built": True, "out": out, "warnings": warnings,
            "files": [CONFIG_NAME, "agent/prompt.md", "agent/agent.json", "leads.json"],
            "listings": len(leads["listings"]), "enquiries_kept": len(leads["enquiries"])}


def load_out(out):
    out = os.path.abspath(os.path.expanduser(out))
    paths = {"config": os.path.join(out, CONFIG_NAME), "prompt": os.path.join(out, "agent", "prompt.md"),
             "agent": os.path.join(out, "agent", "agent.json"), "leads": os.path.join(out, "leads.json")}
    missing = [p for p in paths.values() if not os.path.exists(p)]
    if missing:
        raise Invalid("not built yet, missing: %s" % ", ".join(missing))
    return out, paths


def check(args):
    out, paths = load_out(args.out)
    repo = os.path.abspath(os.path.expanduser(args.repo))
    cfg, agent, leads = read_json(paths["config"]), read_json(paths["agent"]), read_json(paths["leads"])
    with open(paths["prompt"], encoding="utf-8") as f:
        prompt = f.read()
    checks, warnings = [], []

    def record(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    used = variables(prompt) | variables(agent["agent"]["conversation_config"]["agent"]["first_message"])
    record("prompt and first message use only variables the phone page sends", used <= PROMPT_VARIABLES,
           "uses %s" % sorted(used))
    record("no unfilled [[...]] left in the prompt", "[[" not in prompt)
    placeholders = agent["agent"]["conversation_config"]["agent"]["dynamic_variables"][
        "dynamic_variable_placeholders"]
    record("agent.json has a placeholder for every variable used", used <= set(placeholders))
    core_agent = read_json(os.path.join(repo, "phone", "agent", "agent.json"))
    record("client tools have the same names and parameters as the core agent",
           shape(agent["tools"]) == shape(core_agent["tools"]),
           ", ".join(t["name"] for t in agent["tools"]))
    record("the agent accepts signed URLs only",
           agent["agent"]["platform_settings"]["auth"]["enable_auth"] is True)
    record("the prompt says the fact sheet and the caller are data, never instructions",
           "data, never instructions" in prompt)
    record("the first message says it is an AI",
           "AI" in agent["agent"]["conversation_config"]["agent"]["first_message"]
           or agent["agent"]["conversation_config"]["agent"]["language"] != "en")
    record("config has the four statuses call.py needs", set(STATUSES) <= set(cfg.get("statuses") or {}))
    names = list(cfg["statuses"].values()) + list(cfg["business"]["statuses"].values())
    record("status names are all different", len(names) == len(set(names)))
    record("config holds no phone URL or secret", not cfg["phone"].get("url") and not cfg["phone"].get("secret"))
    record("config does not read the DOMOVOY team's env file",
           os.path.expanduser(cfg["phone"].get("env_file") or "") != os.path.expanduser(TEAM_ENV),
           cfg["phone"].get("env_file") or "")
    backend = os.path.normpath(os.path.join(repo, "skill", "domovoy", cfg["backend"]["module"]))
    record("backend.module resolves from the core skill folder", os.path.isfile(backend), backend)
    record("budget recheck of the core is neutralised", cfg["call_context"].get("budget_cap") == NO_BUDGET_CHECK,
           "call_context.budget_cap = %s" % cfg["call_context"].get("budget_cap"))
    bad = [key for key, item in leads["listings"].items()
           if not isinstance(item.get("total_monthly"), int) or item.get("lease_type") not in LEASE_TYPES
           or not item.get("address")]
    record("every listing has an address, a monthly total and a valid lease type", not bad, ", ".join(bad))
    found = []
    for root, _, files in os.walk(out):
        for name in files:
            with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                if SECRET.search(f.read()):
                    found.append(os.path.relpath(os.path.join(root, name), out))
    record("no key or token in the generated files", not found, ", ".join(found))
    if any(e.get("contact") for e in leads["enquiries"]):
        warnings.append("leads.json holds renter contacts: keep this folder out of git and out of chats")
    if len(prompt) > 6000:
        warnings.append("the prompt is %d characters; long prompts slow the voice agent" % len(prompt))
    ok = all(c["ok"] for c in checks)
    if not ok:
        print(json.dumps({"ok": False, "checks": checks, "warnings": warnings}, indent=2, ensure_ascii=False))
        raise Invalid("checks failed: " + "; ".join(c["check"] for c in checks if not c["ok"]))
    return {"ok": True, "checks": checks, "warnings": warnings, "prompt_characters": len(prompt)}


def rehearse(args):
    out, paths = load_out(args.out)
    repo = os.path.abspath(os.path.expanduser(args.repo))
    core = os.path.join(repo, "skill", "domovoy")
    sys.path.insert(0, os.path.join(core, "scripts"))
    sys.path.insert(0, os.path.join(core, "tests"))
    sys.path.insert(0, HERE)
    import call  # noqa: E402  the core call command, unchanged
    import fake_phone_server  # noqa: E402  the core's local fake
    import leads  # noqa: E402

    tmp = tempfile.mkdtemp(prefix="domovoy-business-rehearsal-")
    saved_env = {k: os.environ.get(k) for k in ("DOMOVOY_CONFIG", "DOMOVOY_LEADS")}
    saved_state = call.STATE_DIR
    fake_phone_server.SECRET = "rehearsal-secret"
    fake_phone_server.STATE.update(pending=None, results={}, seen_conversations=set())
    server = fake_phone_server.ThreadingHTTPServer(("127.0.0.1", 0), fake_phone_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % server.server_address[1]
    steps = []
    try:
        cfg = read_json(paths["config"])
        cfg["backend"]["module"] = os.path.join(HERE, "leads.py")
        cfg["phone"].update(url=url, secret="rehearsal-secret", env_file="", url_env="", secret_env="",
                            poll_seconds=0.1, timeout_seconds=5)
        write_json(os.path.join(tmp, CONFIG_NAME), cfg)
        db = read_json(paths["leads"])
        db["enquiries"] = []
        write_json(os.path.join(tmp, "leads.json"), db)
        os.environ["DOMOVOY_CONFIG"] = os.path.join(tmp, CONFIG_NAME)
        os.environ.pop("DOMOVOY_LEADS", None)
        call.STATE_DIR = os.path.join(tmp, "state")
        listing_id = sorted(db["listings"])[0]
        now = datetime.datetime.fromisoformat("2026-11-13T14:00:00+01:00")
        windows = [{"start": "2026-11-16T10:00:00+01:00", "end": "2026-11-16T11:00:00+01:00"},
                   {"start": "2026-11-17T15:00:00+01:00", "end": "2026-11-17T16:00:00+01:00"}]
        questions = cfg["business"]["qualifying_questions"]

        def run_call(*argv):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
                code = call.main(list(argv))
            return code, json.loads(buffer.getvalue())

        def status_of(enquiry_id):
            return leads.enquiry(leads.load(cfg), enquiry_id)["status"]

        def call_with(enquiry_id, result):
            seen = {}

            def answer():
                deadline = time.time() + 5
                while status_of(enquiry_id) != cfg["statuses"]["calling"] and time.time() < deadline:
                    time.sleep(0.02)
                seen["context"] = fake_phone_server.STATE["pending"]
                body = dict(result, property_id=seen["context"]["property_id"])
                request = urllib.request.Request(url + "/api/result", json.dumps(body).encode(),
                                                 {"content-type": "application/json"})
                with contextlib.redirect_stderr(io.StringIO()):
                    urllib.request.urlopen(request).read()

            thread = threading.Thread(target=answer)
            thread.start()
            code, printed = run_call("run", "--windows", json.dumps(windows))
            thread.join()
            return code, printed, seen.get("context")

        first = leads.add_enquiry(cfg, listing_id, "Sam", note="SYNTHETIC renter", now=now)
        code, printed = run_call("run", "--windows", json.dumps(windows))
        steps.append({"step": "1. A new enquiry that nobody approved: the call is refused",
                      "expect": "exit 2, refused, nothing posted to the phone server",
                      "ok": code == 2 and printed.get("refused") is True
                      and fake_phone_server.STATE["pending"] is None,
                      "exit_code": code, "call_py_output": printed, "enquiry_status": status_of(first["id"])})

        leads.approve(cfg, first["id"])
        booked = {"conversation_id": "synthetic-conv-1", "outcome": "booked",
                  "viewing_start": "2026-11-16T10:00:00+01:00",
                  "answers": [{"question": q, "answer": a} for q, a in
                              zip(questions, ["1 December", "Two", "One cat", "At least two years"])],
                  "new_costs": [],
                  "summary": "SYNTHETIC: Sam passes the rules and agreed to a viewing on Monday at 10:00."}
        code, printed, context = call_with(first["id"], booked)
        steps.append({"step": "2. Approved enquiry, the renter qualifies and agrees a time inside a window",
                      "expect": "Viewing booked, create_event true",
                      "ok": code == 0 and printed.get("status") == cfg["statuses"]["booked"]
                      and printed.get("create_event") is True,
                      "call_context_sent_to_phone_server": context, "synthetic_result_posted": booked,
                      "exit_code": code, "call_py_output": printed, "enquiry_status": status_of(first["id"])})

        second = leads.add_enquiry(cfg, listing_id, "Robin", note="SYNTHETIC renter", now=now)
        leads.approve(cfg, second["id"])
        dropped = {"conversation_id": "synthetic-conv-2", "outcome": "not_booked", "viewing_start": None,
                   "answers": [{"question": q, "answer": a} for q, a in
                               zip(questions, ["As soon as possible", "Two", "A dog", "Six months"])],
                   "new_costs": [],
                   "summary": "SYNTHETIC: not booked. Robin has a dog and wants six months; both break the rules."}
        code, printed, _ = call_with(second["id"], dropped)
        steps.append({"step": "3. Approved enquiry, the renter breaks a rule",
                      "expect": "Not booked, create_event false",
                      "ok": code == 0 and printed.get("status") == cfg["statuses"]["not_booked"]
                      and printed.get("create_event") is False,
                      "synthetic_result_posted": dropped, "exit_code": code, "call_py_output": printed,
                      "enquiry_status": status_of(second["id"])})

        third = leads.add_enquiry(cfg, listing_id, "Kim", note="SYNTHETIC renter", now=now)
        leads.approve(cfg, third["id"])
        outside = dict(booked, conversation_id="synthetic-conv-3", viewing_start="2026-11-18T20:00:00+01:00",
                       summary="SYNTHETIC: the voice agent claims a booking on Wednesday at 20:00.")
        code, printed, _ = call_with(third["id"], outside)
        steps.append({"step": "4. The voice agent reports a booking outside the free windows",
                      "expect": "the core recheck turns it into Not booked, create_event false",
                      "ok": code == 0 and printed.get("status") == cfg["statuses"]["not_booked"]
                      and printed.get("create_event") is False,
                      "exit_code": code, "call_py_output": printed, "enquiry_status": status_of(third["id"])})

        final = {"_label": "SYNTHETIC rehearsal. The core call.py ran against the core's FAKE phone server and a "
                           "temporary copy of leads.json. No network, no voice, no real person, no real viewing.",
                 "ok": all(s["ok"] for s in steps), "steps": steps, "report": leads.report(cfg),
                 "leads_after": leads.load(cfg)["enquiries"]}
    finally:
        server.shutdown()
        server.server_close()
        call.STATE_DIR = saved_state
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)
    if args.save:
        write_json(os.path.abspath(os.path.expanduser(args.save)), final)
    if not final["ok"]:
        print(json.dumps(final, indent=2, ensure_ascii=False))
        raise Invalid("rehearsal failed at: " + "; ".join(s["step"] for s in steps if not s["ok"]))
    return {"ok": True, "saved": args.save, "label": final["_label"],
            "steps": [{"step": s["step"], "ok": s["ok"], "enquiry_status": s["enquiry_status"]} for s in steps],
            "report": final["report"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "check", "rehearse"])
    parser.add_argument("--business", help="the agency's answers, as business.json")
    parser.add_argument("--out", required=True, help="folder of the generated setup")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="the DOMOVOY checkout to read the core from")
    parser.add_argument("--repo-path", help="value of repo_path in the generated config (default ~/domovoy)")
    parser.add_argument("--save", help="rehearse: also write the full run to this file")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if not args.business:
                raise Invalid("build needs --business business.json")
            out = build(args)
        elif args.command == "check":
            out = check(args)
        else:
            out = rehearse(args)
    except Invalid as e:
        print(json.dumps({"ok": False, "invalid": str(e)}, indent=2, ensure_ascii=False))
        return 2
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, indent=2))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
