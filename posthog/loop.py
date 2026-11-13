#!/usr/bin/env python3
"""DOMOVOY self-improvement loop on PostHog's free plan. Standard library only.

  loop.py sync                      shortlist -> PostHog events (shortlisted, rejected, interested), each sent once
  loop.py report                    wait until PostHog shows what sync sent, then read today's rejections,
                                    earlier decisions and the scout instructions from PostHog
  loop.py propose --key K --title T --change JSON --ids a,b,c
                                    file the report: an inactive feature flag that holds the change, and a notebook
  loop.py decide --key K --yes|--no record the human answer; on yes switch the flag on and re-filter the shortlist
  loop.py apply                     re-filter the shortlist by every approved change (safe to repeat)
  loop.py overrides                 print the approved requirement changes, for search.py to merge into the profile

Claude does the judgement between report and propose: it normalizes the free-text reasons to a short key,
groups them, and proposes only when one undecided key covers 3 or more rejected flats.

The renter's name and the Notion data source come from the skill's config.json: the file named by DOMOVOY_CONFIG,
else skill/domovoy/config.json in this checkout. That is the same rule call.py uses.

--dataset (default "live", or the DOMOVOY_DATASET variable) tags every event. Use --dataset synthetic for tests; those events also carry synthetic=true.
Output is one JSON object on stdout. Exit codes: 0 ok, 2 refused, 1 error.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shortlist  # noqa: E402
from ph import api, capture, load_env, mcp, query, skill_config  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("DOMOVOY_LOOP_STATE") or os.path.join(HERE, ".state", "sent.json")
SCOUT_SKILL = "domovoy-rejections"
LIVE_PREFIX = "domovoy-criteria-"
MEASURE_INSIGHT = "DOMOVOY: shown, rejected and interested flats by criteria version"
CONTACTED = ("Interested", "Calling", "Viewing booked", "Not booked")
FILTERED = "filtered: "


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    return code


def renter():
    return (skill_config().get("call_context") or {}).get("user_name") or "renter"


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def flag_prefix(dataset):
    """Live changes use domovoy-criteria-*. Any other dataset gets its own prefix, so tests never touch live flags."""
    if dataset == "live":
        return LIVE_PREFIX
    return "domovoy-test-%s-" % re.sub(r"[^a-z0-9]+", "-", dataset.lower()).strip("-")


def criteria_flags(dataset):
    """This dataset's criteria flags from the private API (immediate, unlike public flag evaluation)."""
    found, prefix = [], flag_prefix(dataset)
    for flag in api("GET", "feature_flags/?search=%s&limit=100" % prefix).get("results", []):
        if not flag["key"].startswith(prefix) or flag.get("deleted"):
            continue
        payload = ((flag.get("filters") or {}).get("payloads") or {}).get("true")
        try:
            payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
        except ValueError:
            payload = {}
        found.append({"id": flag["id"], "key": flag["key"], "active": bool(flag.get("active")), "payload": payload})
    return found


def approved_requirements(flags):
    merged = {}
    for flag in flags:
        if flag["active"]:
            merged.update(flag["payload"].get("requirements") or {})
    return merged


def fails(flat, requirements):
    """Why a flat fails the approved requirements, or None. Unknown values never fail."""
    if requirements.get("elevator") == "required" and flat.get("elevator") == "No":
        return "elevator required"
    cap = requirements.get("max_total_monthly")
    if cap is not None and flat.get("total_monthly") is not None and flat["total_monthly"] > cap:
        return "total monthly over %s CZK" % cap
    cap = requirements.get("max_upfront")
    if cap is not None and flat.get("upfront") is not None and flat["upfront"] > cap:
        return "upfront over %s CZK" % cap
    return None


def base_props(args, flags):
    active = sorted(f["key"] for f in flags if f["active"])
    props = {"dataset": args.dataset, "criteria_version": len(active), "active_changes": active}
    for key in active:
        props["$feature/" + key] = True
    if args.dataset != "live":
        props["synthetic"] = True
    return props


def cmd_sync(args):
    flags = criteria_flags(args.dataset)
    state, sent = load_state(), []
    for flat in shortlist.list_flats():
        pid = flat["property_id"]
        props = dict(base_props(args, flags), property_id=pid, portal=flat["portal"], elevator=flat["elevator"],
                     floor=flat["floor"], total_monthly=flat["total_monthly"], upfront=flat["upfront"])
        events = [("listing_shortlisted", {})]
        reason = flat.get("reason") or ""
        if flat["status"] == "Not interested" and reason and not reason.startswith(FILTERED):
            events.append(("listing_rejected", {"reason": reason}))
        if flat["status"] in CONTACTED:
            events.append(("listing_interested", {}))
        for event, extra in events:
            mark = "%s:%s:%s:%s" % (args.dataset, event, pid, extra.get("reason", ""))
            if state.get(mark):
                continue
            capture(event, renter(), dict(props, **extra))
            state[mark] = datetime.datetime.now().astimezone().isoformat()
            sent.append({"event": event, "property_id": pid})
    save_state(state)
    return out({"sent": sent, "note": "report waits until PostHog shows these events, usually 30 to 100 s"})


def wait_for_events(args):
    """Poll until PostHog shows every event sync sent today for this dataset. Returns (complete, seconds waited)."""
    today = datetime.date.today().isoformat()
    expected = sum(1 for mark, when in load_state().items()
                   if mark.startswith(args.dataset + ":listing_") and str(when).startswith(today))
    ds, started = args.dataset.replace("'", ""), time.time()
    while True:
        seen = query("select count() as n from events where event like 'listing_%%' and properties.dataset = '%s' "
                     "and timestamp >= today()" % ds)[0]["n"]
        if seen >= expected or time.time() - started >= args.wait:
            return seen >= expected, round(time.time() - started), expected, seen
        time.sleep(5)


def cmd_report(args):
    ds = args.dataset.replace("'", "")
    complete, waited, expected, seen = wait_for_events(args)
    rejections = query(
        "select properties.property_id as property_id, argMax(properties.reason, timestamp) as reason, "
        "argMax(properties.portal, timestamp) as portal, argMax(properties.elevator, timestamp) as elevator, "
        "argMax(properties.floor, timestamp) as floor, argMax(toString(uuid), timestamp) as event_uuid "
        "from events where event = 'listing_rejected' and properties.dataset = '%s' "
        "and timestamp >= today() group by property_id order by property_id" % ds)
    decided = query(
        "select properties.change as change, properties.approved as approved, timestamp from events "
        "where event = 'criteria_change_decided' and properties.dataset = '%s' order by timestamp" % ds)
    shown = query(
        "select count(distinct properties.property_id) as n from events "
        "where event = 'listing_shortlisted' and properties.dataset = '%s' and timestamp >= today()" % ds)
    skill = api("GET", "llm_skills/name/%s/" % SCOUT_SKILL)
    return out({
        "complete": complete,
        "events": "%d of %d events sent by sync today are visible in PostHog after waiting %d s" % (seen, expected, waited),
        "shown_today": shown[0]["n"] if shown else 0,
        "rejections": rejections,
        "already_decided": decided,
        "approved_requirements": approved_requirements(criteria_flags(args.dataset)),
        "scout_instructions": {"source": "PostHog skills store", "name": skill["name"], "version": skill["version"],
                               "body": skill["body"]},
    })


def cmd_propose(args):
    key = re.sub(r"[^a-z0-9_]", "", args.key.lower())
    change = json.loads(args.change)
    ids = [i for i in args.ids.split(",") if i]
    ds = args.dataset.replace("'", "")
    decided = query("select count() as n from events where event = 'criteria_change_decided' "
                    "and properties.change = '%s' and properties.dataset = '%s'" % (key, ds))
    if decided and decided[0]["n"]:
        return out({"refused": True, "reason": "%s was already decided; not proposing it twice" % key}, 2)
    if len(ids) < 3:
        return out({"refused": True, "reason": "a proposal needs 3 or more rejected flats, got %d" % len(ids)}, 2)
    flag_key = flag_prefix(args.dataset) + key.replace("_", "-")
    existing = [f for f in criteria_flags(args.dataset) if f["key"] == flag_key]
    if existing:
        return out({"refused": True, "reason": "%s was already proposed (flag %s is %s); not proposing it twice" % (key, flag_key, "on" if existing[0]["active"] else "off")}, 2)
    would_remove = [f["property_id"] for f in shortlist.list_flats()
                    if f["status"] == "Shortlisted" and fails(f, change)]
    flag = api("POST", "feature_flags/", {
        "key": flag_key,
        "name": "DOMOVOY approved criteria change: %s. Off = proposed or declined, on = approved." % args.title,
        "active": False,
        "tags": ["domovoy"],
        "filters": {"groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": json.dumps({"requirements": change, "reason_key": key})}},
    })
    id_list = ", ".join("'%s'" % i.replace("'", "") for i in ids)
    markdown = "\n\n".join([
        "**Finding.** %s" % (args.finding or args.title),
        "**Proposal.** Add `%s` to the search requirements." % json.dumps(change),
        "**Expected effect.** %d flats now in Shortlisted would be removed%s." % (
            len(would_remove), (": " + ", ".join(would_remove)) if would_remove else ""),
        "**Measurement pending.** One change shows that it was applied, not that results got better. "
        "Later rejections and Interested rate, split by this flag, will show the effect.",
        "**Your answer.** Yes switches the flag below on. No leaves it off. Either answer is recorded, "
        "so this proposal is not made twice.",
        "Dataset: `%s`. Written by the DOMOVOY agent from scout instructions `%s` stored in PostHog." % (ds, SCOUT_SKILL),
    ])
    title = "DOMOVOY report: " + args.title
    mcp("notebooks-create-markdown", {"title": title, "markdown": markdown})
    short_id = next((n["short_id"] for n in api("GET", "notebooks/?limit=50").get("results", []) if n.get("title") == title), None)
    notebook_url = None
    if short_id:
        notebook_url = "%s/project/%s/notebooks/%s" % (load_env()["POSTHOG_APP_HOST"], load_env()["POSTHOG_PROJECT_ID"], short_id)
        mcp("notebooks-add-cell", {
            "notebook_id": short_id, "cell_type": "sql", "title": "Evidence: the rejections behind this report",
            "code": "select properties.property_id as flat, properties.portal as portal, properties.reason as reason, "
                    "timestamp from events where event = 'listing_rejected' and properties.dataset = '%s' "
                    "and properties.property_id in (%s) order by timestamp" % (ds, id_list)})
        mcp("notebooks-add-cell", {"notebook_id": short_id, "cell_type": "component", "tag_name": "FeatureFlag",
                                   "props": {"id": flag["id"], "view": "editor"}})
        chart = next((i["short_id"] for i in api("GET", "insights/?search=DOMOVOY&saved=true&limit=20").get("results", [])
                      if (i.get("name") or "").startswith(MEASURE_INSIGHT)), None)
        if chart:
            mcp("notebooks-add-cell", {"notebook_id": short_id, "cell_type": "saved_insight", "insight_short_id": chart,
                                       "title": "Measure: flats by criteria version"})
    capture("criteria_change_proposed", renter(), dict(
        base_props(args, criteria_flags(args.dataset)), change=key, flag=flag_key, requirements=change,
        evidence_property_ids=ids, would_remove=len(would_remove), notebook=notebook_url))
    return out({"proposed": key, "flag": flag_key, "flag_id": flag["id"], "would_remove": would_remove,
                "notebook": notebook_url,
                "flag_url": "%s/project/%s/feature_flags/%s" % (load_env()["POSTHOG_APP_HOST"], load_env()["POSTHOG_PROJECT_ID"], flag["id"])})


def refilter(args, flags):
    requirements = approved_requirements(flags)
    moved = []
    for flat in shortlist.list_flats():
        why = fails(flat, requirements) if flat["status"] == "Shortlisted" else None
        if why:
            shortlist.reject(flat, FILTERED + why)
            moved.append({"property_id": flat["property_id"], "title": flat["title"], "reason": FILTERED + why})
    remaining = sorted((f for f in shortlist.list_flats() if f["status"] == "Shortlisted"),
                       key=lambda f: (f["total_monthly"] is None, f["total_monthly"] or 0))
    return {"approved_requirements": requirements, "moved_to_not_interested": moved,
            "shortlisted_now": [{"property_id": f["property_id"], "title": f["title"], "total_monthly": f["total_monthly"]}
                                for f in remaining]}


def write_back(args, key, approved, requirements):
    """Append the decision to the scout instructions in PostHog as a new skill version: the loop's memory."""
    skill = api("GET", "llm_skills/name/%s/" % SCOUT_SKILL)
    line = "- %s, dataset `%s`: `%s` %s%s." % (
        datetime.date.today().isoformat(), args.dataset, key, "approved" if approved else "declined",
        (", requirement now " + json.dumps(requirements)) if approved and requirements else "")
    body = skill["body"].replace("- None yet.\n", "").rstrip("\n") + "\n" + line + "\n"
    mcp("skill-update", {"skill_name": SCOUT_SKILL, "body": body, "base_version": skill["version"],
                         "version_description": "Learned: %s %s (%s)" % (key, "approved" if approved else "declined", args.dataset)})
    return {"skill": SCOUT_SKILL, "version": skill["version"] + 1, "line": line}


def cmd_decide(args):
    key = re.sub(r"[^a-z0-9_]", "", args.key.lower())
    flag_key = flag_prefix(args.dataset) + key.replace("_", "-")
    flag = next((f for f in criteria_flags(args.dataset) if f["key"] == flag_key), None)
    if not flag:
        return out({"refused": True, "reason": "no proposal %s; run propose first" % flag_key}, 2)
    approved = bool(args.yes)
    if approved and not flag["active"]:
        api("PATCH", "feature_flags/%s/" % flag["id"], {"active": True})
    if not approved and flag["active"]:
        api("PATCH", "feature_flags/%s/" % flag["id"], {"active": False})
    flags = criteria_flags(args.dataset)
    capture("criteria_change_decided", renter(), dict(
        base_props(args, flags), change=key, approved=approved, flag=flag_key,
        requirements=flag["payload"].get("requirements")))
    now = datetime.datetime.now().astimezone().isoformat()
    api("POST", "annotations/", {
        "content": "DOMOVOY criteria change %s: %s (%s)" % ("approved" if approved else "declined", key, args.dataset),
        "date_marker": now, "scope": "project"})
    result = {"change": key, "approved": approved, "flag": flag_key,
              "learned": write_back(args, key, approved, flag["payload"].get("requirements"))}
    if approved:
        result.update(refilter(args, flags))
    return out(result)


def cmd_apply(args):
    return out(refilter(args, criteria_flags(args.dataset)))


def cmd_overrides(args):
    flags = criteria_flags(args.dataset)
    return out({"requirements": approved_requirements(flags), "from_flags": sorted(f["key"] for f in flags if f["active"])})


def main():
    parser = argparse.ArgumentParser(description="DOMOVOY PostHog loop")
    parser.add_argument("--dataset", default=os.environ.get("DOMOVOY_DATASET") or "live")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "apply", "overrides"):
        sub.add_parser(name)
    r = sub.add_parser("report")
    r.add_argument("--wait", type=int, default=150, help="seconds to wait for PostHog to show the events sync sent")
    p = sub.add_parser("propose")
    p.add_argument("--key", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--finding", default="")
    p.add_argument("--change", required=True)
    p.add_argument("--ids", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--key", required=True)
    group = d.add_mutually_exclusive_group(required=True)
    group.add_argument("--yes", action="store_true")
    group.add_argument("--no", action="store_true")
    args = parser.parse_args()
    return {"sync": cmd_sync, "report": cmd_report, "propose": cmd_propose, "decide": cmd_decide,
            "apply": cmd_apply, "overrides": cmd_overrides}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
