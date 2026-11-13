#!/usr/bin/env python3
"""DOMOVOY self-improvement loop on PostHog's free plan. Standard library only.

  loop.py sync                      shortlist -> PostHog events (shortlisted, rejected, interested), each sent once
  loop.py report                    wait until PostHog shows what sync sent, then read today's rejections,
                                    earlier decisions and the scout instructions from PostHog
  loop.py propose --key K --title T --change JSON --ids a,b,c
                                    file the report: an inactive feature flag that holds the change, and a notebook
  loop.py decide --key K --yes|--no [--real]
                                    record the human answer; on yes switch the flag on and re-filter the shortlist
  loop.py measure [--key K]         after a later search: compare shown and rejected flats before and after each approved
                                    change, write the result into its notebook and into the agent's memory
  loop.py apply [--real]            re-filter the shortlist by every approved change (safe to repeat)
  loop.py overrides                 print the approved requirement changes, for search.py to merge into the profile

Claude does the judgement between report and propose: it normalizes the free-text reasons to a short key,
groups them, and proposes only when one undecided key covers 3 or more rejected flats.

The renter's name and the Notion data source come from the skill's config.json: the file named by DOMOVOY_CONFIG,
else skill/domovoy/config.json in this checkout. That is the same rule call.py uses.

--dataset (default "live", or the DOMOVOY_DATASET variable) tags every event. Use --dataset synthetic for tests; those events also carry synthetic=true.
Writes to Notion happen only in decide --yes and apply. Both first print the target database's title and id on
stderr, and refuse a database whose title has no "test" or "synthetic" in it unless --real is given.
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


def active_profile_requirements():
    """Hard filters the search already applies, so the agent does not propose one of them again."""
    cfg = skill_config()
    for profile in cfg.get("profiles") or []:
        if profile.get("id") == cfg.get("active_profile"):
            return profile.get("requirements") or {}
    return {}


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


SUPPORTED = ("elevator", "furnished", "min_floor", "max_total_monthly", "max_upfront", "max_commission", "max_metro_m")
PROFILE_REQUIREMENTS = ("elevator", "max_total_monthly", "max_upfront")  # names profile.schema.json also knows


def fails(flat, requirements):
    """Why a flat fails the approved requirements, or None. Unknown values never fail."""
    def over(name, field, label):
        cap = requirements.get(name)
        if cap is not None and flat.get(field) is not None and flat[field] > cap:
            return label % cap
        return None

    if requirements.get("elevator") == "required" and flat.get("elevator") == "No":
        return "elevator required"
    if requirements.get("furnished") == "required" and flat.get("furnished") == "No":
        return "furnished required"
    floor = requirements.get("min_floor")
    if floor is not None and flat.get("floor") is not None and flat["floor"] < floor:
        return "floor below %s" % floor
    return (over("max_total_monthly", "total_monthly", "total monthly over %s CZK")
            or over("max_upfront", "upfront", "move-in cost over %s CZK")
            or over("max_commission", "commission", "commission over %s CZK")
            or over("max_metro_m", "metro_m", "metro farther than %s m"))


def describe(name, value):
    return {
        "elevator": "only flats with an elevator",
        "furnished": "only furnished flats",
        "min_floor": "only flats on floor %s or higher" % value,
        "max_total_monthly": "only flats that cost %s CZK a month or less in total" % value,
        "max_upfront": "only flats with a move-in cost of %s CZK or less" % value,
        "max_commission": "only flats with a commission of %s CZK or less" % value,
        "max_metro_m": "only flats within %s m of a metro station" % value,
    }[name]


def rejected_by_renter(flat):
    """The renter's own no: Status = Not interested, or "Interested?" = No, each with a typed Reason."""
    reason = flat.get("reason") or ""
    said_no = flat["status"] == "Not interested" or flat.get("interested") == "No"
    return said_no and bool(reason) and not reason.startswith(FILTERED)


def wanted_by_renter(flat):
    return flat["status"] in CONTACTED or (flat["status"] == "Shortlisted" and flat.get("interested") == "Yes")


def open_for_review(flat):
    """Still on the shortlist with no answer from the renter. Only these are ever filtered."""
    return flat["status"] == "Shortlisted" and flat.get("interested") not in ("Yes", "No")


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
                     floor=flat["floor"], total_monthly=flat["total_monthly"], upfront=flat["upfront"],
                     furnished=flat.get("furnished"), commission=flat.get("commission"), metro_m=flat.get("metro_m"))
        events = [("listing_shortlisted", {})]
        if rejected_by_renter(flat):
            events.append(("listing_rejected", {"reason": flat["reason"]}))
        if wanted_by_renter(flat):
            events.append(("listing_interested", {}))
        for event, extra in events:
            mark = "%s:%s:%s:%s" % (args.dataset, event, pid, extra.get("reason", ""))
            if state.get(mark):
                continue
            capture(event, renter(), dict(props, **extra))
            state[mark] = datetime.datetime.now().astimezone().isoformat()
            sent.append({"event": event, "property_id": pid})
    save_state(state)
    return out({"shortlist": shortlist.target()["title"], "missing_properties": list(shortlist.MISSING), "sent": sent, "note": "report waits until PostHog shows these events, usually 30 to 100 s"})


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
        "profile_requirements": active_profile_requirements(),
        "supported_changes": {"elevator": "required", "furnished": "required", "min_floor": "N", "max_total_monthly": "N CZK",
                              "max_upfront": "N CZK", "max_commission": "N CZK (0 = no agency fee)", "max_metro_m": "N metres"},
        "scout_instructions": {"source": "PostHog skills store", "name": skill["name"], "version": skill["version"],
                               "body": skill["body"]},
    })


STATUS = "**Status: "
NOTHING_YET = "Nothing yet. This part fills in by itself after the answer."
RESULT = "**Result:** "


def measure_sql(ds, base_version, pretty=False):
    """Flats shown and rejected by the renter, before and after the change that follows rules version base_version."""
    names = ("`When`", "`Flats shown`", "`Rejected by the renter`", "`Rejection rate`") if pretty else ("period", "shown", "rejected", "rate")
    return (
        "select if(toInt(properties.criteria_version) <= %d, 'Before this change', 'After this change') as %s, "
        "count(distinct if(event = 'listing_shortlisted', properties.property_id, null)) as %s, "
        "count(distinct if(event = 'listing_rejected', properties.property_id, null)) as %s, "
        "concat(toString(round(100 * %s / %s)), ' %%') as %s "
        "from events where event in ('listing_shortlisted', 'listing_rejected') and properties.dataset = '%s' "
        "group by 1 order by 1 desc" % (base_version, names[0], names[1], names[2], names[2], names[1], names[3], ds))


def edit_notebook(short_id, replace):
    """Rewrite lines of a report notebook. `replace` maps a text that marks a line to the new line."""
    if not short_id:
        return False
    notebook = api("GET", "notebooks/%s/" % short_id)
    content = notebook["content"]
    node = content["content"][0]["attrs"]
    lines = node["markdown"].split("\n")
    for index, line in enumerate(lines):
        for marker, new in replace.items():
            if marker in line.replace("\\", ""):
                lines[index] = new
    node["markdown"] = "\n".join(lines)
    api("PATCH", "notebooks/%s/" % short_id, {"content": content, "version": notebook["version"]})
    return True


def clock():
    return datetime.datetime.now().astimezone().strftime("%H:%M")


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
    unknown_names = sorted(set(change) - set(SUPPORTED))
    if unknown_names:
        return out({"refused": True, "reason": "unsupported change %s; supported: %s" % (unknown_names, ", ".join(SUPPORTED))}, 2)
    flats = shortlist.list_flats()
    would_remove = [f["property_id"] for f in flats if open_for_review(f) and fails(f, change)]
    base_version = sum(1 for f in criteria_flags(args.dataset) if f["active"])
    flag = api("POST", "feature_flags/", {
        "key": flag_key,
        "name": "DOMOVOY approved criteria change: %s. Off = proposed or declined, on = approved." % args.title,
        "active": False,
        "tags": ["domovoy"],
        "filters": {"groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": json.dumps({"requirements": change, "reason_key": key})}},
    })
    by_id = {f["property_id"]: f for f in flats}
    understood = key.replace("_", " ")
    rows = "\n".join("| %s | \"%s\" | %s |" % (i, ((by_id.get(i) or {}).get("reason") or "not in the shortlist now").replace("|", "/"), understood)
                     for i in ids)
    wish = "; ".join(describe(name, value) for name, value in sorted(change.items()))
    who = renter() if renter() != "renter" else "the renter"
    title = "DOMOVOY suggests: " + args.title
    env = load_env()
    intro = [] if ds == "live" else ["> Example on synthetic flats (dataset `%s`). No real listing is shown here." % ds]
    mcp("notebooks-create-markdown", {"title": title, "markdown": "\n\n".join(intro + [
        STATUS + "🟡 Waiting for your answer**",
        "DOMOVOY finds flats for %s and learns from every flat that gets rejected. "
        "This page is one thing it learned, and one question to you." % who,
        "## 1. What the agent noticed",
        args.finding or args.title,
        "| Flat | What %s wrote | What the agent understood |\n| --- | --- | --- |\n%s" % (who, rows),
        "## 2. What it suggests",
        "> From now on, show **%s**." % wish,
        ("%d flat%s on the shortlist now would be removed: %s." % (len(would_remove), "" if len(would_remove) == 1 else "s", ", ".join(would_remove))
         if would_remove else "No flat on the shortlist now would be removed.")
        + " A flat where the answer is unknown always stays.",
        "## 3. Your answer",
        "Switch on = yes. Leave it off = no. The agent remembers either answer and does not ask twice.",
    ])})
    short_id = next((n["short_id"] for n in api("GET", "notebooks/?limit=50").get("results", []) if n.get("title") == title), None)
    notebook_url = None
    if short_id:
        notebook_url = "%s/project/%s/notebooks/%s" % (env["POSTHOG_APP_HOST"], env["POSTHOG_PROJECT_ID"], short_id)

        def cell(cell_type, **fields):
            mcp("notebooks-add-cell", dict(fields, notebook_id=short_id, cell_type=cell_type))

        cell("component", tag_name="FeatureFlag", props={"id": flag["id"], "view": "editor"})
        cell("markdown", markdown="## 4. What happened next\n\n" + NOTHING_YET)
        table = api("POST", "insights/", {
            "name": "DOMOVOY before and after: %s (%s)" % (args.title, ds), "saved": True, "tags": ["domovoy"],
            "query": {"kind": "DataVisualizationNode", "display": "ActionsTable",
                      "source": {"kind": "HogQLQuery", "query": measure_sql(ds, base_version, pretty=True)}}})
        cell("saved_insight", insight_short_id=table["short_id"], title="Flats shown and rejected, before and after this change")
        cell("markdown", markdown="---\n\nWritten by the DOMOVOY agent from PostHog events. Its instructions and memory: skill `%s`. "
                                  "The switch: feature flag `%s`." % (SCOUT_SKILL, flag_key))
        api("PATCH", "feature_flags/%s/" % flag["id"], {"filters": {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": json.dumps({"requirements": change, "reason_key": key, "notebook": short_id,
                                             "base_version": base_version, "title": args.title})}}})
    capture("criteria_change_proposed", renter(), dict(
        base_props(args, criteria_flags(args.dataset)), change=key, flag=flag_key, requirements=change,
        evidence_property_ids=ids, would_remove=len(would_remove), notebook=notebook_url))
    return out({"proposed": key, "flag": flag_key, "flag_id": flag["id"], "would_remove": would_remove,
                "notebook": notebook_url,
                "flag_url": "%s/project/%s/feature_flags/%s" % (load_env()["POSTHOG_APP_HOST"], load_env()["POSTHOG_PROJECT_ID"], flag["id"])})


def write_target(args):
    """Name the Notion database about to be written, on stderr first, and refuse a real one without --real."""
    where = shortlist.target()
    sys.stderr.write('Notion write target: "%s" (%s)%s\n' % (where["title"], where["id"], "" if where["is_test"] else " REAL"))
    sys.stderr.flush()
    if not where["is_test"] and not getattr(args, "real", False):
        return where, {"refused": True, "notion_target": where,
                       "reason": 'this would write to "%s", which is not a test database. Pass --real to write to the real shortlist.' % where["title"]}
    shortlist.ALLOW_REAL = bool(getattr(args, "real", False))
    return where, None


def refilter(args, flags):
    requirements = approved_requirements(flags)
    moved, kept = [], []
    for flat in shortlist.list_flats():
        why = fails(flat, requirements) if flat["status"] == "Shortlisted" else None
        if why and open_for_review(flat):
            shortlist.reject(flat, FILTERED + why)
            moved.append({"property_id": flat["property_id"], "title": flat["title"], "reason": FILTERED + why})
        elif why and flat.get("interested") == "Yes":
            kept.append({"property_id": flat["property_id"], "title": flat["title"], "would_fail": why,
                         "kept_because": "the renter marked it Interested? = Yes"})
    remaining = sorted((f for f in shortlist.list_flats() if f["status"] == "Shortlisted" and f.get("interested") != "No"),
                       key=lambda f: (f["total_monthly"] is None, f["total_monthly"] or 0))
    return {"notion_target": shortlist.target(), "missing_properties": list(shortlist.MISSING),
            "approved_requirements": requirements, "moved_to_not_interested": moved, "kept_despite_failing": kept,
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
    if approved:
        _, refusal = write_target(args)
        if refusal:
            return out(refusal, 2)
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
    learned, moved = result["learned"], result.get("moved_to_not_interested") or []
    memory = "The agent then rewrote its own instructions (PostHog skill `%s`, version %d → %d). New line in its memory: \"%s\"" % (
        SCOUT_SKILL, learned["version"] - 1, learned["version"], learned["line"].lstrip("- ").replace("`", ""))
    if approved:
        story = "**%s: you said yes.** %s %s" % (
            clock(), ("%d flat%s left the shortlist: %s." % (len(moved), "" if len(moved) == 1 else "s", ", ".join(m["property_id"] for m in moved))
                      if moved else "No flat had to leave the shortlist."), memory)
        status = STATUS + "🟢 Approved at %s. Waiting for the next search to measure it**" % clock()
        tail = ["", RESULT + "not measured yet. The numbers appear after the next search."]
    else:
        story = "**%s: you said no.** Nothing changed in the search. %s It will not ask this again." % (clock(), memory)
        status, tail = STATUS + "⚪ Declined at %s. Remembered, not asked again**" % clock(), []
    result["notebook_updated"] = edit_notebook(flag["payload"].get("notebook"), {STATUS: status, NOTHING_YET: "\n".join([story] + tail)})
    return out(result)


def cmd_measure(args):
    """Compare flats shown and rejected before and after each approved change; write the result into its notebook
    and into the agent's memory."""
    ds, results = args.dataset.replace("'", ""), []
    for flag in criteria_flags(args.dataset):
        payload = flag["payload"]
        if not flag["active"] or "base_version" not in payload:
            continue
        key = payload.get("reason_key")
        if args.key and key != re.sub(r"[^a-z0-9_]", "", args.key.lower()):
            continue
        rows = {r["period"]: r for r in query(measure_sql(ds, int(payload["base_version"])))}
        before, after = rows.get("Before this change") or {}, rows.get("After this change") or {}
        entry = {"change": key, "before": before, "after": after}
        if not after.get("shown"):
            entry["verdict"] = "not measurable yet: no flat was shown after the change"
            results.append(entry)
            continue
        rate = lambda r: round(100.0 * r["rejected"] / r["shown"]) if r.get("shown") else 0
        numbers = "before %d of %d flats shown were rejected (%d %%), after %d of %d (%d %%)" % (
            before.get("rejected", 0), before.get("shown", 0), rate(before), after["rejected"], after["shown"], rate(after))
        better = rate(after) < rate(before)
        small = " Small sample: %d flats so far." % after["shown"] if after["shown"] < 10 else ""
        entry["verdict"] = ("helped: " if better else "no improvement yet: ") + numbers
        status = STATUS + ("✅ Helped: rejection rate %d %% → %d %%**" if better else "🟠 No improvement yet: rejection rate %d %% → %d %%**") % (rate(before), rate(after))
        entry["notebook_updated"] = edit_notebook(payload.get("notebook"), {
            STATUS: status,
            RESULT: RESULT + "%s at %s: %s.%s The agent wrote this result into its memory too." % (
                "it helped" if better else "no improvement yet", clock(), numbers, small)})
        skill = api("GET", "llm_skills/name/%s/" % SCOUT_SKILL)
        mark = "measured `%s`, dataset `%s`:" % (key, ds)
        kept = [line for line in skill["body"].rstrip("\n").split("\n") if mark not in line]
        line = "- %s %s %s.%s" % (datetime.date.today().isoformat(), mark, entry["verdict"], small)
        mcp("skill-update", {"skill_name": SCOUT_SKILL, "body": "\n".join(kept + [line]) + "\n", "base_version": skill["version"],
                             "version_description": "Measured: %s (%s)" % (key, ds)})
        entry["learned"] = {"skill": SCOUT_SKILL, "version": skill["version"] + 1, "line": line}
        capture("criteria_change_measured", renter(), dict(
            base_props(args, criteria_flags(args.dataset)), change=key, helped=better,
            shown_before=before.get("shown", 0), rejected_before=before.get("rejected", 0),
            shown_after=after["shown"], rejected_after=after["rejected"]))
        results.append(entry)
    return out({"measured": results})


def cmd_apply(args):
    _, refusal = write_target(args)
    if refusal:
        return out(refusal, 2)
    return out(refilter(args, criteria_flags(args.dataset)))


def cmd_overrides(args):
    flags = criteria_flags(args.dataset)
    merged = approved_requirements(flags)
    return out({"requirements": {k: v for k, v in merged.items() if k in PROFILE_REQUIREMENTS},
                "not_in_profile_schema": {k: v for k, v in merged.items() if k not in PROFILE_REQUIREMENTS},
                "from_flags": sorted(f["key"] for f in flags if f["active"])})


REAL_HELP = "allow writing to a Notion database whose title has no \"test\" or \"synthetic\" in it"


def main():
    parser = argparse.ArgumentParser(description="DOMOVOY PostHog loop")
    parser.add_argument("--dataset", default=os.environ.get("DOMOVOY_DATASET") or "live")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "overrides"):
        sub.add_parser(name)
    a = sub.add_parser("apply")
    a.add_argument("--real", action="store_true", help=REAL_HELP)
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
    d.add_argument("--real", action="store_true", help=REAL_HELP)
    m = sub.add_parser("measure")
    m.add_argument("--key", default="")
    args = parser.parse_args()
    if args.dataset != "live" and not shortlist.explicit_data_source():
        return out({"refused": True, "reason": "a test dataset needs an explicit shortlist: set NOTION_DATA_SOURCE_ID or "
                    "DOMOVOY_FAKE_SHORTLIST. Without one this would read and re-filter the real DOMOVOY shortlist."}, 2)
    return {"sync": cmd_sync, "report": cmd_report, "propose": cmd_propose, "decide": cmd_decide,
            "apply": cmd_apply, "overrides": cmd_overrides, "measure": cmd_measure}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
