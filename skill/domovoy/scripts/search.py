#!/usr/bin/env python3
"""DOMOVOY research command: start the Apify Actor run for the active search profile, wait, print the summary.

  search.py run    [--profile ID] [--max-listings N] [--include-unchanged] [--no-wait] [--timeout S]
  search.py status --run RUN_ID [--timeout S]     wait for an existing run and print its summary; safe to repeat

Output is one JSON object on stdout; progress lines go to stderr.
Exit codes: 0 succeeded, 1 error (run failed, timed out, HTTP error, no summary), 2 refused (nothing started).

Settings come from config.json (or DOMOVOY_CONFIG): active_profile, profiles[], apify.actor_id (then env
APIFY_ACTOR_ID, then vladb~domovoy), apify.timeout_seconds (900), apify.poll_seconds (5), apify.env_file
(~/.config/domovoy/.env), notion.data_source_id (then env NOTION_DATA_SOURCE_ID). The Apify token is APIFY_TOKEN,
from the environment or the env file. APIFY_API_BASE replaces https://api.apify.com (the tests use it).
The Notion token is never sent: the Actor reads its own secret on the platform.

The run input is {"mode": "search", "profile": ..., "notion": {"dataSourceId": ...}}. The summary is the run's
key-value record OUTPUT. Its counts are read by name (see summarize); a count that is absent prints as null.
"""
import argparse
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_API = "https://api.apify.com"
DEFAULT_ACTOR = "vladb~domovoy"
DEFAULT_ENV_FILE = "~/.config/domovoy/.env"
OUTPUT_KEY = "OUTPUT"
TERMINAL = ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")
REQUEST_TIMEOUT = 30  # seconds per HTTP request; a poll also gets no more than the time left before the deadline
GROUPS = {"change": ("new", "changed", "unchanged"),
          "match": ("strong", "needs_info", "rejected"),
          "notion": ("created", "updated", "errors")}
SOURCE_FIELDS = ("name", "status", "found", "fetched", "failed")
SECRETS = set()  # the Apify token; scrubbed from everything printed
TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


class Refusal(Exception):
    """Checked before any request: nothing was contacted or started."""


class ApiError(RuntimeError):
    def __init__(self, message, http_status=None, transient=False):
        super().__init__(message)
        self.http_status = http_status
        self.transient = transient  # network, 429 or 5xx: safe to poll again


class RunTimeout(RuntimeError):
    def __init__(self, run, message):
        super().__init__(message)
        self.run = run


def log(message):
    print(scrub(message), file=sys.stderr)


def scrub(text):
    for secret in SECRETS:
        text = text.replace(secret, "[token removed]")
    return text


def load_config():
    path = os.environ.get("DOMOVOY_CONFIG") or os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        raise RuntimeError("config not found: %s (copy config.example.json to config.json)" % path)
    with open(path) as f:
        return json.load(f)


def validate(value, schema, path="$"):
    # Copied from call.py (not imported): the small subset of JSON Schema the contracts use.
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


def choose_profile(cfg, wanted):
    profiles = [p for p in cfg.get("profiles") or [] if isinstance(p, dict)]
    active = wanted if wanted is not None else cfg.get("active_profile")
    matches = [p for p in profiles if active is not None and p.get("id") == active]
    if len(matches) > 1:
        raise Refusal("profile id %s appears %d times in profiles[] in config.json" % (active, len(matches)))
    if matches:
        return matches[0]
    if wanted is None and len(profiles) == 1:  # the same rule call.py uses: the only profile
        return profiles[0]
    if active is None:
        raise Refusal("no active profile: set active_profile in config.json to a profiles[] id, "
                      "or pass --profile ID. Nothing was started.")
    raise Refusal("profile %s is not in profiles[] in config.json. Nothing was started." % active)


def profile_errors(profile):
    schema_path = os.path.join(ROOT, "reference", "profile.schema.json")
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            return validate(profile, json.load(f))
    errors = []  # until the schema lands: the keys the Actor cannot run without
    if not isinstance(profile.get("id"), str) or not profile.get("id"):
        errors.append("$.id: missing")
    for key in ("filters", "requirements"):
        if not isinstance(profile.get(key), dict):
            errors.append("$.%s: missing" % key)
    return errors


def env_file_value(path, name):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        for line in f:
            key, _, value = line.strip().partition("=")
            if key.replace("export ", "").strip() == name and value.strip():
                return value.strip().strip("'\"")
    return None


def apify_token(env_file):
    token = os.environ.get("APIFY_TOKEN") or env_file_value(env_file, "APIFY_TOKEN")
    if not token:
        raise Refusal("APIFY_TOKEN is not set: export it or put it in %s. Nothing was contacted." % env_file)
    SECRETS.add(token)
    return token


def data_source_id(cfg):
    value = (cfg.get("notion") or {}).get("data_source_id") or os.environ.get("NOTION_DATA_SOURCE_ID")
    if not value:
        raise Refusal("notion.data_source_id is not set in config.json: run scripts/notion.py setup and put "
                      "the printed data source id there. Nothing was started.")
    return value


def apify_settings(cfg, timeout=None):
    apify = cfg.get("apify") or {}
    seconds = float(timeout if timeout is not None else apify.get("timeout_seconds", 900))
    if seconds <= 0:
        raise Refusal("the timeout must be more than 0 seconds. Nothing was started.")
    return {
        "actor": apify.get("actor_id") or os.environ.get("APIFY_ACTOR_ID") or DEFAULT_ACTOR,
        "timeout": seconds,
        "poll": max(float(apify.get("poll_seconds", 5)), 0.01),
        "env_file": apify.get("env_file") or DEFAULT_ENV_FILE,
    }


def error_text(raw, fallback):
    text = raw.decode(errors="replace").strip()
    try:
        error = json.loads(text).get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
    except (ValueError, AttributeError):
        pass
    return text[:200] or str(fallback)


class Api:
    def __init__(self, token):
        self.token = token
        self.base = (os.environ.get("APIFY_API_BASE") or DEFAULT_API).rstrip("/")

    def call(self, method, path, body=None, timeout=REQUEST_TIMEOUT):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise ApiError("Apify answered HTTP %d: %s" % (e.code, error_text(e.read(), e.reason)),
                           e.code, transient=e.code == 429 or e.code >= 500)
        except OSError as e:  # URLError and socket timeouts
            raise ApiError("could not reach the Apify API: %s" % (getattr(e, "reason", None) or e),
                           transient=True)
        try:
            return json.loads(raw.decode() or "null")
        except ValueError:
            raise ApiError("the Apify API answered with something that is not JSON")


def unwrap(reply):
    run = reply.get("data") if isinstance(reply, dict) and isinstance(reply.get("data"), dict) else reply
    if not isinstance(run, dict) or not run.get("id"):
        raise ApiError("Apify answered without a run id")
    return run


def start_run(api, actor, body):
    # Never retried: a second POST could start a second run.
    try:
        return unwrap(api.call("POST", "/v2/actors/%s/runs" % urllib.parse.quote(actor, safe="~"), body))
    except ApiError as e:
        if e.transient:
            raise ApiError("%s. The run may have started: check the Apify console before running again" % e)
        raise


def get_run(api, run_id, timeout=REQUEST_TIMEOUT):
    return unwrap(api.call("GET", "/v2/actor-runs/%s" % urllib.parse.quote(run_id, safe=""), timeout=timeout))


def wait_for_run(api, run, timeout, poll, shown_log):
    """Poll until the run is terminal. Each poll request gets at most the time left before the deadline, so
    --timeout holds even when a request is slow. Transient errors are retried until the deadline."""
    deadline = time.monotonic() + timeout
    shown = None
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise RunTimeout(run, "run %s is still %s after %d s and keeps running on Apify. Check it later with: "
                                  "python3 scripts/search.py status --run %s"
                             % (run["id"], run.get("status") or "unknown", timeout, run["id"]))
        try:
            run = get_run(api, run["id"], min(REQUEST_TIMEOUT, left))
            if run.get("status") != shown:
                shown = run.get("status")
                shown_log("run %s: %s" % (run["id"], shown))
            if shown in TERMINAL:
                return run
        except ApiError as e:
            if not e.transient:
                raise
            shown_log("poll: %s" % e)
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))


def console_url(run):
    return run.get("consoleUrl") or "https://console.apify.com/view/runs/%s" % run.get("id")


def read_output(api, store_id):
    if not store_id:
        raise ApiError("the run has no default key-value store")
    try:
        output = api.call("GET", "/v2/key-value-stores/%s/records/%s"
                          % (urllib.parse.quote(store_id, safe=""), OUTPUT_KEY))
    except ApiError as e:
        if e.http_status == 404:
            raise ApiError("the run finished but wrote no %s record" % OUTPUT_KEY)
        raise
    if not isinstance(output, dict):
        raise ApiError("the %s record is not a JSON object" % OUTPUT_KEY)
    return output


def summarize(output):
    """Pick the counts out of the OUTPUT record by name. An absent count is null, never 0."""
    missing = []
    sources = output.get("sources")
    if isinstance(sources, dict):  # also accept {name: {...}}
        sources = [dict(v, name=k) for k, v in sources.items() if isinstance(v, dict)]
    if not isinstance(sources, list):
        sources = None
        missing.append("sources")
    summary = {"sources": None if sources is None else
               [{k: s.get(k) for k in SOURCE_FIELDS} for s in sources if isinstance(s, dict)]}
    for group, keys in GROUPS.items():
        block = output.get(group) if isinstance(output.get(group), dict) else {}
        summary[group] = {}
        for key in keys:
            value = block.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                value = None
                missing.append("%s.%s" % (group, key))
            summary[group][key] = value
    match = output.get("match") if isinstance(output.get("match"), dict) else {}
    reasons = match.get("rejected_by_requirement")
    if not isinstance(reasons, dict):
        reasons = None
        missing.append("match.rejected_by_requirement")
    summary["match"]["rejected_by_requirement"] = reasons
    return summary, missing


def report_base(run, profile_id):
    out = {"run_id": run.get("id"), "status": run.get("status"), "console_url": console_url(run)}
    if profile_id is not None:
        out["profile"] = profile_id
    return out


def report(api, run, profile_id):
    out = report_base(run, profile_id)
    if run.get("status") != "SUCCEEDED":
        out["error"] = "the Actor run ended with %s; its log is at console_url" % run.get("status")
        return out, 1
    try:
        output = read_output(api, run.get("defaultKeyValueStoreId"))
    except ApiError as e:
        out["error"] = "%s; its log is at console_url" % e
        return out, 1
    out["summary"], out["missing_summary_fields"] = summarize(output)
    return out, 0


def finish(api, run, profile_id, settings):
    try:
        run = wait_for_run(api, run, settings["timeout"], settings["poll"], log)
    except RunTimeout as e:
        return dict(report_base(e.run, profile_id), error=str(e)), 1
    return report(api, run, profile_id)


def cmd_run(cfg, args):
    profile = choose_profile(cfg, args.profile)
    errors = profile_errors(profile)
    if errors:
        raise Refusal("profile %s is not valid: %s. Nothing was started." % (profile.get("id"), "; ".join(errors[:3])))
    if args.max_listings is not None and args.max_listings < 1:
        raise Refusal("--max-listings must be a whole number of at least 1. Nothing was started.")
    settings = apify_settings(cfg, args.timeout)
    token = apify_token(settings["env_file"])
    datasource = data_source_id(cfg)
    profile = copy.deepcopy(profile)
    if args.max_listings is not None:
        profile["filters"]["max_listings"] = args.max_listings
    body = {"mode": "search", "profile": profile, "notion": {"dataSourceId": datasource}}
    if args.include_unchanged:
        body["includeUnchanged"] = True
    api = Api(token)
    run = start_run(api, settings["actor"], body)
    log("started run %s: %s" % (run["id"], console_url(run)))
    if args.no_wait:
        out = report_base(run, profile["id"])
        out.update(waited=False, next="python3 scripts/search.py status --run %s" % run["id"])
        return out, 0
    return finish(api, run, profile["id"], settings)


def cmd_status(cfg, args):
    settings = apify_settings(cfg, args.timeout)
    api = Api(apify_token(settings["env_file"]))
    return finish(api, {"id": args.run}, None, settings)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start the Actor run for the active profile, wait, print the summary")
    run.add_argument("--profile", help="profiles[] id to run instead of active_profile")
    run.add_argument("--max-listings", type=int, help="cap the listings for this run (filters.max_listings)")
    run.add_argument("--include-unchanged", action="store_true", help="also return flats already seen")
    run.add_argument("--no-wait", action="store_true", help="start the run and print its id without waiting")
    run.add_argument("--timeout", type=float, help="seconds to wait (default apify.timeout_seconds, 900)")
    status = sub.add_parser("status", help="wait for an existing run and print its summary; safe to repeat")
    status.add_argument("--run", required=True, help="the Apify run id that run printed")
    status.add_argument("--timeout", type=float, help="seconds to wait (default apify.timeout_seconds, 900)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config()
        out, code = cmd_run(cfg, args) if args.command == "run" else cmd_status(cfg, args)
    except Refusal as e:
        out, code = {"refused": True, "reason": str(e)}, 2
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        out = {"error": str(e) if isinstance(e, RuntimeError) else "%s: %s" % (type(e).__name__, e)}
        code = 1
    print(scrub(json.dumps(out, indent=2, ensure_ascii=False)))
    return code


if __name__ == "__main__":
    sys.exit(main())
