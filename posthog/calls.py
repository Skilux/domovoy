#!/usr/bin/env python3
"""DOMOVOY voice calls -> PostHog LLM traces, with one score per call. Standard library only.

  calls.py prompt     store the deployed voice prompt in PostHog prompt management when it changed
  calls.py sync       send every finished call not sent before: one trace, one generation per agent turn,
                      and one call_finished event with the score
  calls.py report     per prompt version: calls, unknowns asked and answered, the questions left unanswered

Reads calls from the ElevenLabs API (ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID), so no other lane's code changes.
The score is deterministic: how many of the call's `unknowns` got an answer in `submit_call_result`.

--dataset (default "live", or the DOMOVOY_DATASET variable) tags every event. Calls shorter than --min-seconds (default 20) are skipped as test dials.
Output is one JSON object on stdout.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ph import api, load_env, need, post, query  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("DOMOVOY_CALLS_STATE") or os.path.join(HERE, ".state", "calls.json")
PROMPT_NAME = "domovoy-voice-agent"
EMPTY = ("", "unknown", "n/a", "none", "not answered", "no answer")


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    return code


def eleven(path):
    env = load_env()
    key = env.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("missing ELEVENLABS_API_KEY")
    req = urllib.request.Request("https://api.elevenlabs.io/v1/convai" + path, headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("ElevenLabs HTTP %s on %s: %s" % (e.code, path, e.read().decode("utf-8")[:300]))


def agent_id():
    env = load_env()
    return env.get("ELEVENLABS_AGENT_ID") or need(os.environ, "ELEVENLABS_AGENT_ID")


def send(event, distinct_id, properties, when):
    env = load_env()
    body = {"api_key": need(env, "POSTHOG_PROJECT_TOKEN"), "event": event, "distinct_id": distinct_id,
            "properties": properties, "timestamp": when.isoformat()}
    post(env["POSTHOG_INGEST_HOST"].rstrip("/") + "/i/v0/e/", body)


def prompt_versions():
    """{elevenlabs agent version id: PostHog prompt version}, from the config stored with each prompt version."""
    found = [p for p in api("GET", "llm_prompts/?search=%s" % PROMPT_NAME).get("results", []) if p["name"] == PROMPT_NAME]
    if not found:
        return {}, None
    latest = api("GET", "llm_prompts/name/%s/" % PROMPT_NAME)
    mapping = {}
    for number in range(1, (latest.get("latest_version") or latest.get("version") or 1) + 1):
        version = latest if number == latest.get("version") else api("GET", "llm_prompts/name/%s/?version=%d" % (PROMPT_NAME, number))
        for agent_version in (version.get("config") or {}).get("elevenlabs_version_ids", []):
            mapping.setdefault(agent_version, number)
    return mapping, latest


def cmd_prompt(args):
    agent = eleven("/agents/" + agent_id())
    text = agent["conversation_config"]["agent"]["prompt"]["prompt"].strip()
    model = agent["conversation_config"]["agent"]["prompt"].get("llm")
    agent_version = agent.get("version_id")
    mapping, latest = prompt_versions()
    if latest is None:
        made = api("POST", "llm_prompts/", {"name": PROMPT_NAME, "prompt": text,
                                            "config": {"model": model, "elevenlabs_version_ids": [agent_version]},
                                            "version_description": "Deployed voice prompt, first tracked version"})
        return out({"prompt": PROMPT_NAME, "version": made["version"], "created": True})
    config = dict(latest.get("config") or {})
    known = list(config.get("elevenlabs_version_ids", []))
    same_text = (latest.get("prompt") or "").strip() == text
    if same_text and agent_version in known:
        return out({"prompt": PROMPT_NAME, "version": latest["version"], "created": False})
    body = {"prompt": text, "base_version": latest["version"],
            "config": {"model": model, "elevenlabs_version_ids": (known if same_text else []) + [agent_version]},
            "version_description": args.note or ("Same text, new agent version" if same_text else "Deployed voice prompt changed")}
    made = api("PATCH", "llm_prompts/name/%s/" % PROMPT_NAME, body)
    return out({"prompt": PROMPT_NAME, "version": made.get("version"), "created": True, "text_changed": not same_text})


def parse_unknowns(raw):
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    lines = [re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", line).strip() for line in str(raw or "").splitlines()]
    return [line for line in lines if line]


def call_result(transcript):
    for turn in transcript:
        for call in turn.get("tool_calls") or []:
            if call.get("tool_name") == "submit_call_result":
                try:
                    return json.loads(call.get("params_as_json") or "{}")
                except ValueError:
                    return {}
    return None


def score(unknowns, result):
    answers = [a for a in (result or {}).get("answers") or []
               if str(a.get("answer") or "").strip().lower() not in EMPTY]
    answered = min(len(answers), len(unknowns))
    return {"unknowns_total": len(unknowns), "unknowns_answered": answered,
            "all_unknowns_answered": bool(unknowns) and answered == len(unknowns),
            "questions_answered": [str(a.get("question")) for a in answers]}


def cmd_sync(args):
    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
    mapping, _ = prompt_versions()
    for row in query("select distinct properties.conversation_id as cid from events where event = 'call_finished' "
                     "and properties.dataset = '%s'" % args.dataset.replace("'", "")):
        state.setdefault("%s:%s" % (args.dataset, row["cid"]), "already in PostHog")
    listed = eleven("/conversations?agent_id=%s&page_size=100" % agent_id()).get("conversations", [])
    sent, skipped = [], 0
    for item in sorted(listed, key=lambda c: c.get("start_time_unix_secs") or 0):
        cid = item["conversation_id"]
        mark = "%s:%s" % (args.dataset, cid)
        if state.get(mark) or item.get("status") != "done":
            continue
        if (item.get("call_duration_secs") or 0) < args.min_seconds:
            skipped += 1
            continue
        detail = eleven("/conversations/" + cid)
        variables = (detail.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}
        transcript = detail.get("transcript") or []
        meta = detail.get("metadata") or {}
        start = datetime.datetime.fromtimestamp(meta.get("start_time_unix_secs") or item["start_time_unix_secs"], datetime.timezone.utc)
        unknowns = parse_unknowns(variables.get("unknowns"))
        result = call_result(transcript)
        renter = variables.get("user_name") or "renter"
        common = {"dataset": args.dataset, "property_id": variables.get("property_id"), "conversation_id": cid,
                  "agent_version": detail.get("version_id"), "prompt_version": mapping.get(detail.get("version_id")),
                  "$ai_trace_id": cid}
        if args.dataset != "live":
            common["synthetic"] = True
        history = []
        for turn in transcript:
            role = "assistant" if turn.get("role") == "agent" else "user"
            text = turn.get("message") or ""
            when = start + datetime.timedelta(seconds=turn.get("time_in_call_secs") or 0)
            if role == "assistant" and (text or turn.get("tool_calls")):
                usage = ((turn.get("llm_usage") or {}).get("model_usage") or {})
                model = turn.get("producing_llm") or next(iter(usage), None)
                tokens = usage.get(model) or {}
                metrics = ((turn.get("conversation_turn_metrics") or {}).get("metrics") or {})
                tools = [c.get("tool_name") for c in turn.get("tool_calls") or []]
                props = dict(common, **{
                    "$ai_model": model, "$ai_provider": "elevenlabs",
                    "$ai_input": list(history),
                    "$ai_output_choices": [{"role": "assistant", "content": text or ("[tool call: %s]" % ", ".join(tools))}],
                    "$ai_input_tokens": (tokens.get("input") or {}).get("tokens"),
                    "$ai_output_tokens": (tokens.get("output_total") or {}).get("tokens"),
                    "$ai_latency": (metrics.get("convai_llm_service_tt_last_sentence") or {}).get("elapsed_time"),
                    "$ai_time_to_first_token": (metrics.get("convai_llm_service_ttfb") or {}).get("elapsed_time"),
                    "$ai_input_cost_usd": (tokens.get("input") or {}).get("price"),
                    "$ai_output_cost_usd": (tokens.get("output_total") or {}).get("price"),
                    "tools_called": tools,
                })
                send("$ai_generation", renter, {k: v for k, v in props.items() if v is not None}, when)
            if text:
                history.append({"role": role, "content": text})
        asked = [c for turn in transcript for c in (turn.get("tool_calls") or []) if c.get("tool_name") == "mark_question_asked"]
        scored = dict(score(unknowns, result), questions_marked_asked=len(asked))
        outcome = (result or {}).get("outcome")
        send("$ai_trace", renter, dict(common, **{
            "$ai_span_name": "DOMOVOY viewing call",
            "$ai_input_state": {"property_id": variables.get("property_id"), "unknowns": unknowns,
                                "budget_cap": variables.get("budget_cap")},
            "$ai_output_state": result or {"note": "the agent never called submit_call_result"},
            "$ai_latency": meta.get("call_duration_secs"),
        }), start)
        end = start + datetime.timedelta(seconds=meta.get("call_duration_secs") or 0)
        send("call_finished", renter, dict(common, **scored, **{
            "outcome": outcome, "result_submitted": result is not None,
            "new_costs_count": len((result or {}).get("new_costs") or []),
            "unknowns": unknowns, "duration_seconds": meta.get("call_duration_secs"),
            "termination_reason": meta.get("termination_reason"),
        }), end)
        state[mark] = start.isoformat()
        sent.append({"conversation_id": cid, "property_id": variables.get("property_id"), "outcome": outcome,
                     "unknowns": "%d of %d answered" % (scored["unknowns_answered"], scored["unknowns_total"]),
                     "prompt_version": mapping.get(detail.get("version_id"))})
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return out({"sent": sent, "skipped_short_calls": skipped,
                "note": "PostHog shows new events to queries after 30 to 100 s"})


def cmd_report(args):
    ds = args.dataset.replace("'", "")
    calls = query(
        "select properties.conversation_id as conversation_id, properties.property_id as property_id, "
        "properties.prompt_version as prompt_version, properties.agent_version as agent_version, "
        "properties.outcome as outcome, properties.result_submitted as result_submitted, "
        "properties.unknowns_total as unknowns_total, properties.unknowns_answered as unknowns_answered, "
        "properties.unknowns as unknowns, properties.questions_answered as questions_answered, "
        "properties.duration_seconds as duration_seconds, timestamp from events "
        "where event = 'call_finished' and properties.dataset = '%s' order by timestamp" % ds)
    seen, first = set(), []
    for call in calls:
        if call["conversation_id"] not in seen:
            seen.add(call["conversation_id"])
            first.append(call)
    calls, versions = first, {}
    for call in calls:
        key = str(int(call["prompt_version"])) if call["prompt_version"] is not None else "untracked"
        v = versions.setdefault(key, {"calls": 0, "booked": 0, "unknowns_total": 0, "unknowns_answered": 0, "no_result": 0})
        v["calls"] += 1
        v["booked"] += 1 if call["outcome"] == "booked" else 0
        v["unknowns_total"] += int(call["unknowns_total"] or 0)
        v["unknowns_answered"] += int(call["unknowns_answered"] or 0)
        v["no_result"] += 0 if call["result_submitted"] else 1
    return out({"by_prompt_version": versions, "calls": calls})


def main():
    parser = argparse.ArgumentParser(description="DOMOVOY calls to PostHog")
    parser.add_argument("--dataset", default=os.environ.get("DOMOVOY_DATASET") or "live")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt")
    p.add_argument("--note", default="")
    s = sub.add_parser("sync")
    s.add_argument("--min-seconds", type=int, default=20)
    sub.add_parser("report")
    args = parser.parse_args()
    return {"prompt": cmd_prompt, "sync": cmd_sync, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
