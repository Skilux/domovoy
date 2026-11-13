#!/usr/bin/env python3
"""DOMOVOY doctor: check every integration and say how to fix what is missing. Standard library only.

  doctor.py check [--json] [--only local,notion,apify,featherless,phone,elevenlabs,posthog,calendar]

Read-only. It creates nothing, changes nothing, starts no Actor run and rings no phone. Each check is one or
two GET requests with the keys from the environment or the env file. No key is ever printed.

Reads config.json (DOMOVOY_CONFIG, else the skill folder) and the env file (DOMOVOY_ENV_FILE, else
phone.env_file in config.json, else ~/.config/domovoy/.env). The environment wins over the env file.

Statuses: PASS, FAIL (required, blocks the core path), WARN (optional or cosmetic), SKIP (not checked, with the
reason). Exit codes: 0 no FAIL, 1 at least one FAIL, 2 bad arguments.

With --json the output is one object:
  {"ok": bool, "checks": [{"id", "status", "detail", "fix"}], "next": "<fix of the first FAIL, or null>"}

The API hosts can be replaced for tests: NOTION_API_BASE, APIFY_API_BASE, FEATHERLESS_API_BASE,
ELEVENLABS_API_BASE.
"""
import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_FILE = "~/.config/domovoy/.env"
DEFAULT_ACTOR = "vladb~domovoy"
DEFAULT_POSTHOG_APP = "https://eu.posthog.com"
TIMEOUT_SECONDS = 15
GROUPS = ("local", "notion", "apify", "featherless", "phone", "elevenlabs", "posthog", "calendar")
PROBE_ID = "doctor-probe"
SECRETS = set()  # every key that was read; scrubbed from everything printed

with open(os.path.join(ROOT, "reference", "notion_contract.json"), encoding="utf-8") as f:
    CONTRACT = json.load(f)


def scrub(text):
    for secret in SECRETS:
        text = text.replace(secret, "[key removed]")
    return text


def load_config():
    """(config, problem). A missing or broken config is reported as a check, and the other checks still run."""
    path = os.path.expanduser(os.environ.get("DOMOVOY_CONFIG") or os.path.join(ROOT, "config.json"))
    if not os.path.exists(path):
        return {}, "config not found: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        return {}, "config %s cannot be read: %s" % (path, e)
    if not isinstance(cfg, dict):
        return {}, "config %s is not a JSON object" % path
    return cfg, None


def env_file_path(cfg):
    return os.path.expanduser(os.environ.get("DOMOVOY_ENV_FILE")
                              or (cfg.get("phone") or {}).get("env_file") or DEFAULT_ENV_FILE)


def read_env_file(path):
    values = {}
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


class Settings:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env_file = env_file_path(cfg)
        self.file_values = read_env_file(self.env_file)

    def get(self, name, secret=True):
        value = os.environ.get(name) or self.file_values.get(name) or ""
        if value and secret:
            SECRETS.add(value)
        return value


def http_get(url, headers):
    """(status, parsed JSON or None). status is None when the host cannot be reached; the body is then the reason."""
    request = urllib.request.Request(url, method="GET", headers=dict(headers, Accept="application/json"))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, str(getattr(e, "reason", e))
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


def row(check_id, status, detail, fix=None):
    return {"id": check_id, "status": status, "detail": detail, "fix": fix}


def unreachable(check_id, host, reason):
    return row(check_id, "FAIL", "cannot reach %s: %s" % (host, reason), "Check the network, then run the check again.")


def check_local(settings, config_problem):
    rows = []
    version = "%d.%d" % sys.version_info[:2]
    if sys.version_info >= (3, 9):
        rows.append(row("local.python", "PASS", "Python " + version))
    else:
        rows.append(row("local.python", "FAIL", "Python %s, the scripts need 3.9 or newer" % version,
                        "Install Python 3.9 or newer and run the scripts with it."))
    if config_problem:
        rows.append(row("local.config", "FAIL", config_problem,
                        "Copy config.example.json to config.json in the skill folder and fill it in."))
    else:
        cfg = settings.cfg
        ids = [p.get("id") for p in cfg.get("profiles") or [] if isinstance(p, dict)]
        active = cfg.get("active_profile")
        if not ids:
            rows.append(row("local.config", "WARN", "config.json has no search profile",
                            "Ask the agent to find flats: it writes the profile to profiles[] in config.json."))
        elif active not in ids and len(ids) != 1:
            rows.append(row("local.config", "FAIL", "active_profile %r is not one of %s" % (active, ids),
                            "Set active_profile in config.json to one of the profile ids."))
        else:
            rows.append(row("local.config", "PASS", "config.json, %d profile(s)" % len(ids)))
    path = settings.env_file
    if not os.path.isfile(path):
        rows.append(row("local.env_file", "WARN", "no env file at %s; only exported variables are used" % path,
                        "Copy .env.example from the repo to %s, run chmod 600 on it and fill it in." % path))
    else:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            rows.append(row("local.env_file", "WARN", "%s is readable by other users (mode %o)" % (path, mode),
                            "Run: chmod 600 %s" % path))
        else:
            rows.append(row("local.env_file", "PASS", "%s, mode %o" % (path, mode)))
    installed = os.path.expanduser("~/.claude/skills/domovoy")
    if os.path.isfile(os.path.join(installed, "SKILL.md")):
        rows.append(row("local.skill", "PASS", "skill found at %s" % installed))
    else:
        rows.append(row("local.skill", "WARN", "no skill at %s; Claude Code will not load DOMOVOY" % installed,
                        "Run: ln -s %s %s" % (ROOT, installed)))
    return rows


def schema_problems(live):
    """What an existing data source lacks against reference/notion_contract.json."""
    problems = []
    for name, spec in CONTRACT["properties"].items():
        have = live.get(name)
        if not isinstance(have, dict):
            problems.append("%s is missing" % name)
        elif have.get("type") != spec["type"]:
            problems.append("%s is %s, the contract says %s" % (name, have.get("type"), spec["type"]))
        elif spec["type"] in ("select", "multi_select"):
            known = {option.get("name") for option in (have.get(spec["type"]) or {}).get("options", [])}
            missing = [option for option in spec.get("options", []) if option not in known]
            if missing:
                problems.append("%s lacks the options %s" % (name, ", ".join(missing)))
    return problems


def check_notion(settings):
    module = (settings.cfg.get("backend") or {}).get("module", "scripts/notion.py")
    if os.path.basename(module) != "notion.py":
        reason = "backend.module is %s, not Notion" % module
        return [row("notion.token", "SKIP", reason), row("notion.schema", "SKIP", reason)]
    base = os.environ.get("NOTION_API_BASE", "https://api.notion.com").rstrip("/")
    token = settings.get("NOTION_TOKEN")
    if not token:
        return [row("notion.token", "FAIL", "NOTION_TOKEN is not set",
                    "Create an internal integration at https://www.notion.so/profile/integrations and put its "
                    "secret in %s as NOTION_TOKEN." % settings.env_file),
                row("notion.schema", "SKIP", "blocked by notion.token")]
    headers = {"Authorization": "Bearer " + token, "Notion-Version": CONTRACT["notion_api_version"]}
    status, body = http_get(base + "/v1/users/me", headers)
    if status is None:
        return [unreachable("notion.token", "Notion", body), row("notion.schema", "SKIP", "blocked by notion.token")]
    if status != 200:
        return [row("notion.token", "FAIL", "Notion rejected NOTION_TOKEN (HTTP %d)" % status,
                    "Copy the Internal Integration Secret again from https://www.notion.so/profile/integrations."),
                row("notion.schema", "SKIP", "blocked by notion.token")]
    name = (body or {}).get("name") or "integration"
    rows = [row("notion.token", "PASS", "token accepted, integration %r" % name)]
    ds_id = (settings.cfg.get("notion") or {}).get("data_source_id") or os.environ.get("NOTION_DATA_SOURCE_ID")
    if not ds_id:
        rows.append(row("notion.schema", "FAIL", "notion.data_source_id is not set in config.json",
                        "Put the parent page id in the env file as NOTION_PARENT_PAGE_ID, run "
                        "python3 scripts/notion.py setup, and copy the data_source_id it prints into config.json."))
        return rows
    status, body = http_get(base + "/v1/data_sources/" + urllib.parse.quote(str(ds_id), safe=""), headers)
    if status is None:
        rows.append(unreachable("notion.schema", "Notion", body))
    elif status == 404:
        rows.append(row("notion.schema", "FAIL", "Notion cannot see the data source in notion.data_source_id",
                        "Open the DOMOVOY parent page in Notion, page menu > Connections, add your integration. "
                        "If the id is wrong, run python3 scripts/notion.py setup again."))
    elif status != 200:
        rows.append(row("notion.schema", "FAIL", "Notion answered HTTP %d for the data source" % status,
                        "Run python3 scripts/notion.py setup and read its error."))
    else:
        problems = schema_problems((body or {}).get("properties") or {})
        total = len(CONTRACT["properties"])
        if problems:
            shown = "; ".join(problems[:5]) + ("; and %d more" % (len(problems) - 5) if len(problems) > 5 else "")
            rows.append(row("notion.schema", "FAIL", "%d of %d properties differ: %s" % (len(problems), total, shown),
                            "Run python3 scripts/notion.py setup: it adds what is missing and lists type conflicts."))
        else:
            rows.append(row("notion.schema", "PASS", "%d of %d properties match the contract" % (total, total)))
    return rows


def check_apify(settings):
    base = os.environ.get("APIFY_API_BASE", "https://api.apify.com").rstrip("/")
    apify = settings.cfg.get("apify") or {}
    actor = apify.get("actor_id") or os.environ.get("APIFY_ACTOR_ID") or DEFAULT_ACTOR
    token = settings.get("APIFY_TOKEN")
    if not token:
        return [row("apify.token", "FAIL", "APIFY_TOKEN is not set",
                    "Copy a token from console.apify.com > Settings > API & Integrations into %s as APIFY_TOKEN."
                    % settings.env_file),
                row("apify.actor", "SKIP", "blocked by apify.token")]
    headers = {"Authorization": "Bearer " + token}
    status, body = http_get(base + "/v2/users/me", headers)
    if status is None:
        return [unreachable("apify.token", "Apify", body), row("apify.actor", "SKIP", "blocked by apify.token")]
    if status != 200:
        return [row("apify.token", "FAIL", "Apify rejected APIFY_TOKEN (HTTP %d)" % status,
                    "Copy a new token from console.apify.com > Settings > API & Integrations."),
                row("apify.actor", "SKIP", "blocked by apify.token")]
    user = ((body or {}).get("data") or {}).get("username") or "account"
    rows = [row("apify.token", "PASS", "token accepted, user %r" % user)]
    status, body = http_get(base + "/v2/acts/" + urllib.parse.quote(actor, safe="~"), headers)
    if status is None:
        rows.append(unreachable("apify.actor", "Apify", body))
    elif status == 200:
        rows.append(row("apify.actor", "PASS", "Actor %s is visible to this account" % actor))
    else:
        rows.append(row("apify.actor", "FAIL", "Actor %s is not visible to this account (HTTP %d)" % (actor, status),
                        "Build your own copy: run `apify push` in the repo's apify/ folder, then set apify.actor_id "
                        "in config.json to <your username>~domovoy."))
    return rows


def check_featherless(settings):
    base = os.environ.get("FEATHERLESS_API_BASE", "https://api.featherless.ai").rstrip("/")
    key = settings.get("FEATHERLESS_API_KEY")
    if not key:
        return [row("featherless.key", "SKIP",
                    "FEATHERLESS_API_KEY is not set here. The Actor reads its own copy as a secret input on Apify, "
                    "which this script cannot see",
                    "To check the key from this machine, put it in %s as FEATHERLESS_API_KEY." % settings.env_file)]
    status, body = http_get(base + "/v1/models", {"Authorization": "Bearer " + key})
    if status is None:
        return [unreachable("featherless.key", "Featherless", body)]
    if status == 200:
        return [row("featherless.key", "PASS", "key accepted")]
    return [row("featherless.key", "FAIL", "Featherless rejected FEATHERLESS_API_KEY (HTTP %d)" % status,
                "Create a key on the API keys page of your featherless.ai account. Extraction needs a paid plan.")]


def check_phone(settings):
    phone = settings.cfg.get("phone") or {}
    url = settings.get(phone.get("url_env") or "PHONE_URL", secret=False) or phone.get("url") or ""
    secret = settings.get(phone.get("secret_env") or "DOMOVOY_SECRET") or phone.get("secret") or ""
    if secret:
        SECRETS.add(secret)
    blocked = [row("phone.secret", "SKIP", "blocked by phone.url"), row("phone.store", "SKIP", "blocked by phone.url")]
    if not url:
        return [row("phone.url", "FAIL", "PHONE_URL is not set",
                    "Deploy the repo's phone/ folder to Vercel and put its URL in %s as PHONE_URL."
                    % settings.env_file)] + blocked
    if "://" not in url:
        url = "https://" + url
    status, body = http_get(url.rstrip("/") + "/api/result/" + PROBE_ID, {"x-domovoy-secret": secret})
    if status is None:
        return [row("phone.url", "FAIL", "cannot reach the phone server at %s: %s" % (url, body),
                    "Check PHONE_URL and that the Vercel deployment is up.")] + blocked
    known = isinstance(body, dict) and "error" in body
    if status == 401 and known:
        fix = ("Set the same DOMOVOY_SECRET in %s and in the Vercel project's env vars, then redeploy."
               % settings.env_file)
        detail = "the phone server rejected DOMOVOY_SECRET" if secret else "DOMOVOY_SECRET is not set"
        return [row("phone.url", "PASS", "phone server answers at %s" % url),
                row("phone.secret", "FAIL", detail, fix),
                row("phone.store", "SKIP", "blocked by phone.secret")]
    if status == 404 and known:
        return [row("phone.url", "PASS", "phone server answers at %s" % url),
                row("phone.secret", "PASS", "secret accepted"),
                row("phone.store", "PASS", "store answers (no result for the probe id, as expected)")]
    if status == 200:
        return [row("phone.url", "PASS", "phone server answers at %s" % url),
                row("phone.secret", "PASS", "secret accepted"),
                row("phone.store", "PASS", "store answers")]
    if status >= 500:
        return [row("phone.url", "PASS", "phone server answers at %s" % url),
                row("phone.secret", "PASS", "secret accepted"),
                row("phone.store", "FAIL", "the phone server failed reading its store (HTTP %d)" % status,
                    "Add an Upstash Redis store to the Vercel project (Storage tab), check that KV_REST_API_URL "
                    "and KV_REST_API_TOKEN are set, then redeploy.")]
    return [row("phone.url", "FAIL", "%s answered HTTP %d, which is not the DOMOVOY phone server" % (url, status),
                "Check PHONE_URL: it must be the root URL of the deployed phone/ app.")] + blocked


def check_elevenlabs(settings):
    base = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io").rstrip("/")
    key = settings.get("ELEVENLABS_API_KEY")
    agent_id = settings.get("ELEVENLABS_AGENT_ID", secret=False)
    if not key:
        reason = ("ELEVENLABS_API_KEY is not set here. The phone server reads its own copy from Vercel env vars, "
                  "which this script cannot see")
        return [row("elevenlabs.key", "SKIP", reason,
                    "To check the key from this machine, put it in %s as ELEVENLABS_API_KEY." % settings.env_file),
                row("elevenlabs.agent", "SKIP", "blocked by elevenlabs.key")]
    headers = {"xi-api-key": key}
    status, body = http_get(base + "/v1/convai/agents?page_size=1", headers)
    if status is None:
        return [unreachable("elevenlabs.key", "ElevenLabs", body),
                row("elevenlabs.agent", "SKIP", "blocked by elevenlabs.key")]
    if status != 200:
        return [row("elevenlabs.key", "FAIL", "ElevenLabs rejected ELEVENLABS_API_KEY for Agents (HTTP %d)" % status,
                    "Create an API key in your ElevenLabs account that may read and write Agents."),
                row("elevenlabs.agent", "SKIP", "blocked by elevenlabs.key")]
    rows = [row("elevenlabs.key", "PASS", "key accepted for Agents")]
    create = "Run: set -a; . %s; set +a; node phone/agent/sync-agent.mjs" % settings.env_file
    if not agent_id:
        rows.append(row("elevenlabs.agent", "FAIL", "ELEVENLABS_AGENT_ID is not set",
                        create + " from the repo root. It prints the new agent id: put it in the env file and in "
                                 "the Vercel env vars."))
        return rows
    status, body = http_get(base + "/v1/convai/agents/" + urllib.parse.quote(agent_id, safe=""), headers)
    if status is None:
        rows.append(unreachable("elevenlabs.agent", "ElevenLabs", body))
    elif status == 200:
        rows.append(row("elevenlabs.agent", "PASS", "agent %r exists" % ((body or {}).get("name") or agent_id)))
    else:
        rows.append(row("elevenlabs.agent", "FAIL", "agent %s was not found (HTTP %d)" % (agent_id, status),
                        "Clear ELEVENLABS_AGENT_ID, then " + create[0].lower() + create[1:] + " to create a new one."))
    return rows


def check_posthog(settings):
    token = settings.get("POSTHOG_PROJECT_TOKEN", secret=False)
    key = settings.get("POSTHOG_PERSONAL_API_KEY")
    project = settings.get("POSTHOG_PROJECT_ID", secret=False)
    app = (settings.get("POSTHOG_APP_HOST", secret=False) or DEFAULT_POSTHOG_APP).rstrip("/")
    if not (token or key):
        return [row("posthog.keys", "SKIP", "optional: no PostHog keys are set, the improve command is off",
                    "Only for the improve command: see posthog/README.md in the repo.")]
    missing = [name for name, value in (("POSTHOG_PROJECT_TOKEN", token), ("POSTHOG_PERSONAL_API_KEY", key),
                                        ("POSTHOG_PROJECT_ID", project)) if not value]
    if missing:
        return [row("posthog.keys", "WARN", "optional: %s not set, the improve command will stop" % ", ".join(missing),
                    "Add the missing values to %s; names are in posthog/README.md." % settings.env_file)]
    status, body = http_get("%s/api/projects/%s/" % (app, urllib.parse.quote(project, safe="")),
                            {"Authorization": "Bearer " + key})
    if status is None:
        return [row("posthog.keys", "WARN", "optional: cannot reach PostHog at %s: %s" % (app, body),
                    "Check POSTHOG_APP_HOST (EU is https://eu.posthog.com, US is https://us.posthog.com).")]
    if status == 200:
        return [row("posthog.keys", "PASS", "personal key reads project %s" % project)]
    return [row("posthog.keys", "WARN", "optional: PostHog rejected the personal key for project %s (HTTP %d)"
                % (project, status),
                "Create a personal API key in PostHog settings that may read this project and run queries.")]


def check_calendar(settings):
    calendar_id = (settings.cfg.get("calendar") or {}).get("calendar_id") or "primary"
    return [row("calendar.access", "SKIP",
                "a script cannot see the agent's calendar tools (calendar_id %r)" % calendar_id,
                "Ask the agent: \"list my calendars\". If it cannot, connect a calendar tool to it.")]


def run_checks(only=None):
    cfg, config_problem = load_config()
    settings = Settings(cfg)
    steps = {
        "local": lambda: check_local(settings, config_problem),
        "notion": lambda: check_notion(settings),
        "apify": lambda: check_apify(settings),
        "featherless": lambda: check_featherless(settings),
        "phone": lambda: check_phone(settings),
        "elevenlabs": lambda: check_elevenlabs(settings),
        "posthog": lambda: check_posthog(settings),
        "calendar": lambda: check_calendar(settings),
    }
    rows = []
    for group in GROUPS:
        if only and group not in only:
            continue
        try:
            rows += steps[group]()
        except Exception as e:  # one broken check must not hide the others
            rows.append(row(group + ".check", "FAIL", "the check itself failed: %s: %s" % (type(e).__name__, e),
                            "Report this with the output of doctor.py check --json."))
    for item in rows:
        item["detail"] = scrub(item["detail"])
        item["fix"] = scrub(item["fix"]) if item["fix"] else None
    failed = [item for item in rows if item["status"] == "FAIL"]
    return {"ok": not failed, "checks": rows, "next": failed[0]["fix"] if failed else None}


def render(result):
    width = max(len(item["id"]) for item in result["checks"])
    lines = []
    for item in result["checks"]:
        lines.append("%-4s  %-*s  %s" % (item["status"], width, item["id"], item["detail"]))
        if item["fix"] and item["status"] != "PASS":
            lines.append("%-4s  %-*s  fix: %s" % ("", width, "", item["fix"]))
    counts = {status: sum(1 for item in result["checks"] if item["status"] == status)
              for status in ("PASS", "FAIL", "WARN", "SKIP")}
    lines.append("")
    lines.append("%(PASS)d pass, %(FAIL)d fail, %(WARN)d warn, %(SKIP)d skipped" % counts)
    if result["next"]:
        lines.append("Next: " + result["next"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--only", help="comma-separated groups: " + ",".join(GROUPS))
    args = parser.parse_args(argv)
    only = None
    if args.only:
        only = [name.strip() for name in args.only.split(",") if name.strip()]
        unknown = [name for name in only if name not in GROUPS]
        if unknown:
            parser.error("unknown group %s; choose from %s" % (", ".join(unknown), ", ".join(GROUPS)))
    result = run_checks(only)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
