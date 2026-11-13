#!/usr/bin/env python3
"""DOMOVOY e2e harness (issue #68): runs layers L0-L6 against the e2e Notion database and the Apify platform.

  apify/.venv/bin/python apify/e2e/run_e2e.py --round N [--only CHECK_ID[,CHECK_ID]] [--layers L0,L3,...]
                                              [--offline-items F --offline-summary F]

Writes ~/.config/domovoy/e2e-reports/<round>/report.md and findings.json (no contacts). Raw datasets, which hold
realtor contacts, go to ~/.config/domovoy/e2e-data/<round>/ only. Exit 0 green, 1 blocker, 2 refused, 3 harness error,
4 incomplete (L4/L5 had no candidate pages).

Safety: the config (DOMOVOY_CONFIG, default ~/.config/domovoy/config.e2e.json) must point at the database titled
"DOMOVOY shortlist (e2e)", never the demo shortlist; every page write checks the page's parent first. Platform runs
are counted in e2e-reports/platform_runs.json and refused past MAX_PLATFORM_RUNS. Secrets are read from the .env
file into child processes only and never printed. See README.md.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
APIFY_DIR = HERE.parent
REPO = APIFY_DIR.parent
SKILL_DIR = REPO / "skill" / "domovoy"
sys.path.insert(0, str(APIFY_DIR))
sys.path.insert(0, str(HERE))
import checks  # noqa: E402

HOME_CFG = Path.home() / ".config" / "domovoy"
DEFAULT_CONFIG = HOME_CFG / "config.e2e.json"
ENV_FILE = Path("/Users/vladimir/.config/domovoy/.env")
REPORTS = HOME_CFG / "e2e-reports"
DATA = HOME_CFG / "e2e-data"
HEAVY = Path("/Users/vladimir/.claude-orbox/skills/orchestrate-agents/scripts/heavy.sh")
HEAVY_DIR = Path("/Users/vladimir/Documents/domovoy-actor-orchestration/heavy")
UA = "apify-agent-skills/apify-actor-development"
DEMO_DATA_SOURCE = "03e7d4e2-76c9-49d2-a141-c162e4f3c1fe"
E2E_TITLE = "DOMOVOY shortlist (e2e)"
DEMO_TITLE = "DOMOVOY shortlist"
PROFILE_ID = "e2e-vinohrady"
MAX_PLATFORM_RUNS = 6
RUN_BUDGET_SEC = 600
REFETCH_GAP_SEC = 1.5
PHONE_PORT = 4230
NOTION = "https://api.notion.com/v1"
APIFY = "https://api.apify.com/v2"
PRAGUE = dt.timezone(dt.timedelta(hours=1))  # November: CET, +01:00
LAYERS = ("L0", "L1", "L2", "L3", "L4", "L5", "L6")
SECRET_KEYS = ("FEATHERLESS_API_KEY", "OPENAI_API_KEY", "NOTION_TOKEN", "APIFY_TOKEN", "DOMOVOY_SECRET",
               "CUZK_API_KN_KEY", "WSDP_PASSWORD", "NOTION_PARENT_PAGE_ID")
L0_OWNERS = {
    "test_sreality": "apify/domovoy/sources/sreality.py", "test_bezrealitky": "apify/domovoy/sources/bezrealitky.py",
    "test_idnes": "apify/domovoy/sources/idnes.py", "test_extraction": "apify/domovoy/extraction/",
    "test_costs": "apify/domovoy/costs/", "test_dedup": "apify/domovoy/dedup/",
    "test_notion_sink": "apify/domovoy/notion/sink.py", "test_pipeline": "apify/domovoy/pipeline.py",
    "test_foundation": "apify/domovoy/models.py", "test_call": "skill/domovoy/scripts/call.py",
    "test_e2e_fake": "skill/domovoy/scripts/call.py", "test_notion": "skill/domovoy/scripts/notion.py",
    "test_search": "skill/domovoy/scripts/search.py", "test_doctor": "skill/domovoy/scripts/doctor.py",
    "test_demo": "skill/domovoy/scripts/demo.py",
}


def log(msg: str) -> None:
    print("[e2e %s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), checks.scrub(msg, 1000)), file=sys.stderr, flush=True)


class Refused(RuntimeError):
    pass


def read_env() -> dict[str, str]:
    values = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            key, sep, value = line.strip().partition("=")
            key = key.replace("export ", "").strip()
            if sep and key and value.strip():
                values[key] = value.strip().strip("'\"")
    return values


# Notion (read everything, write only to pages of the e2e data source)


class Notion:
    def __init__(self, token: str, data_source_id: str, version: str):
        self.ds = data_source_id
        self.http = httpx.Client(timeout=30, headers={"Authorization": "Bearer " + token, "Notion-Version": version})

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        for attempt in range(5):
            r = self.http.request(method, NOTION + path, json=body, params=params)
            if r.status_code in (429, 502, 503, 529) and attempt < 4:
                time.sleep(float(r.headers.get("Retry-After") or 1.5))
                continue
            if r.status_code >= 300:
                code = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("code")
                raise RuntimeError("Notion %s %s: HTTP %d %s" % (method, path, r.status_code, code))
            time.sleep(0.34)
            return r.json()
        raise RuntimeError("Notion %s %s: retries exhausted" % (method, path))

    def guard(self, expected_database_id: str | None) -> None:
        """Enable writes only when the target is the e2e database (see check_target)."""
        self.writable = False
        check_target(self.ds, None, None, expected_database_id)  # id checks before any request
        source = self.call("GET", "/data_sources/%s" % self.ds)
        parent = source.get("parent") or source.get("database_parent") or {}
        database = self.call("GET", "/databases/%s" % parent["database_id"]) if parent.get("database_id") else None
        check_target(self.ds, source, database, expected_database_id)
        self.properties = source.get("properties") or {}
        self.writable = True

    def pages(self) -> list[dict]:
        out, cursor = [], None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            reply = self.call("POST", "/data_sources/%s/query" % self.ds, body)
            out += reply["results"]
            if not reply.get("has_more"):
                return out
            cursor = reply["next_cursor"]

    def body(self, block_id: str, depth: int = 0) -> str:
        lines, cursor = [], None
        while True:
            params = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            reply = self.call("GET", "/blocks/%s/children" % block_id, params=params)
            for block in reply["results"]:
                kind = block["type"]
                if kind == "table_row":
                    lines.append(" | ".join(plain(c) for c in block["table_row"]["cells"]))
                else:
                    lines.append(plain((block.get(kind) or {}).get("rich_text")))
                if block.get("has_children") and depth < 2:
                    lines.append(self.body(block["id"], depth + 1))
            if not reply.get("has_more"):
                return "\n".join(line for line in lines if line.strip())
            cursor = reply["next_cursor"]

    def _own_page(self, page_id: str) -> None:
        if not getattr(self, "writable", False):
            raise Refused("writes are not enabled: the target was not verified as the e2e database")
        page = self.call("GET", "/pages/%s" % page_id)
        if (page.get("parent") or {}).get("data_source_id", "").replace("-", "") != self.ds.replace("-", ""):
            raise Refused("page %s is not in the e2e data source; refusing to write" % page_id)

    def write_page(self, page_id: str, properties: dict) -> None:
        self._own_page(page_id)
        self.call("PATCH", "/pages/%s" % page_id, {"properties": properties})

    def append(self, page_id: str, text: str) -> None:
        self._own_page(page_id)
        self.call("PATCH", "/blocks/%s/children" % page_id, {"children": [{"object": "block", "type": "paragraph",
                  "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}]})


def _title(obj: dict | None) -> str:
    return "".join(t.get("plain_text", "") for t in (obj or {}).get("title") or []).strip()


def check_target(ds_id: str, source: dict | None, database: dict | None, expected_database_id: str | None) -> None:
    """Refuse unless the data source is the e2e one: not the demo id, neither the source nor its parent database
    titled like the demo shortlist, a parent database titled "DOMOVOY shortlist (e2e)", and that parent's id equal to
    the config's notion.database_id. source/database None: only the id checks (before any request)."""
    norm = lambda value: (value or "").replace("-", "").lower()
    if not ds_id or norm(ds_id) == norm(DEMO_DATA_SOURCE):
        raise Refused("the config points at the demo shortlist (or nowhere); refusing")
    if not expected_database_id:
        raise Refused("config notion.database_id (the e2e database) is not set; refusing")
    if source is None:
        return
    parent = source.get("parent") or source.get("database_parent") or {}
    if _title(source) == DEMO_TITLE or (database is not None and _title(database) == DEMO_TITLE):
        raise Refused("the data source or its parent database is titled %r (the demo shortlist); refusing" % DEMO_TITLE)
    if database is None or not parent.get("database_id"):
        raise Refused("data source %s has no parent database; refusing" % ds_id)
    if _title(database) != E2E_TITLE:
        raise Refused("the parent database is titled %r, not %r; refusing" % (_title(database), E2E_TITLE))
    if _title(source) not in ("", E2E_TITLE):
        raise Refused("the data source is titled %r, not %r; refusing" % (_title(source), E2E_TITLE))
    if norm(parent["database_id"]) != norm(expected_database_id) or norm(database.get("id")) != norm(expected_database_id):
        raise Refused("the parent database is not the e2e database %s; refusing" % expected_database_id)


def plain(items: Any) -> str:
    return "".join(i.get("plain_text", "") for i in items or [])


def prop_value(p: dict) -> Any:
    kind = p.get("type")
    value = p.get(kind)
    if kind in ("title", "rich_text"):
        return plain(value) or None
    if kind == "select":
        return value["name"] if value else None
    if kind == "multi_select":
        return [v["name"] for v in value or []]
    if kind == "date":
        return value["start"] if value else None
    return value


def simple_page(page: dict, body: str | None = None) -> dict:
    props = {name: prop_value(p) for name, p in (page.get("properties") or {}).items()}
    return {"page_id": page["id"], "property_id": props.get("Property ID"), "status": props.get("Status"),
            "interested": props.get("Interested?"), "reason": props.get("Reason"), "props": props, "body": body}


# Process helpers


def child_env(env: dict[str, str], keys: tuple[str, ...], extra: dict | None = None) -> dict[str, str]:
    out = {k: v for k, v in os.environ.items() if k not in SECRET_KEYS}
    out.update({k: env[k] for k in keys if k in env})
    out.update(extra or {})
    return out


def run_logged(cmd: list[str], raw: Path, *, cwd: Path, env: dict, timeout: float, heavy: str | None = None) -> tuple[int, float]:
    """Run a child; its output goes to raw (the private data folder), never to the reports. publish() writes the
    sanitized copy."""
    if heavy:
        cmd = [str(HEAVY), "--dir", str(HEAVY_DIR), "--label", "e2e-" + heavy, "--"] + cmd
    start = time.monotonic()
    with open(raw, "w") as f:
        try:
            code = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = -9
    return code, time.monotonic() - start


def publish(raw: Path | str, dest: Path) -> str:
    """Write the sanitized text of raw (a path or the text itself) to dest in the reports; return that text."""
    text = raw.read_text(errors="replace") if isinstance(raw, Path) else raw
    clean = checks.sanitize(text)
    dest.write_text(clean)
    return clean


def write_private(path: Path, value: Any) -> None:
    """JSON readable by the user only (0600), written atomically."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# Platform-run cap: one locked check-and-reserve, written atomically before the launch


@contextlib.contextmanager
def _locked_counter(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            entries = load_json(path) or []
            yield entries
            fd, tmp = tempfile.mkstemp(prefix=".platform_runs-", dir=path.parent)
            with os.fdopen(fd, "w") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp, path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def reserve_platform_run(path: Path, round_name: str, label: str, cap: int = MAX_PLATFORM_RUNS) -> str:
    """Reserve one platform run under the lock, or refuse when cap entries exist. Returns the reservation id."""
    with _locked_counter(path) as entries:
        if len(entries) >= cap:
            raise Refused("the platform run cap (%d) is reached; see %s" % (cap, path))
        rid = uuid.uuid4().hex
        entries.append({"id": rid, "round": round_name, "label": label, "run_id": None,
                        "at": dt.datetime.now(PRAGUE).isoformat()})
        return rid


def update_reservation(path: Path, rid: str, run_id: str | None) -> None:
    with _locked_counter(path) as entries:
        for entry in entries:
            if entry.get("id") == rid:
                entry["run_id"] = run_id


class ConfigSnapshot:
    """The validated config, frozen in a private file (0600) at round start. Children get this path, never the
    user's file; verify() runs at every launch and refuses when either file changed or the target moved."""

    def __init__(self, source: Path, private_dir: Path):
        self.source = Path(source)
        raw = self.source.read_bytes()
        self.digest = hashlib.sha256(raw).hexdigest()
        self.cfg = json.loads(raw)
        fd, path = tempfile.mkstemp(prefix="config-snapshot-", suffix=".json", dir=private_dir)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.chmod(path, 0o600)
        self.path = Path(path)

    def target(self) -> str:
        return (self.cfg.get("notion") or {}).get("data_source_id") or ""

    def verify(self, data_source_id: str) -> None:
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.digest:
            raise Refused("the config snapshot changed during the round; refusing to launch")
        if not self.source.is_file() or hashlib.sha256(self.source.read_bytes()).hexdigest() != self.digest:
            raise Refused("the config %s was edited during the round; refusing to launch" % self.source)
        if self.target() != data_source_id:
            raise Refused("the config targets %s, the round verified %s; refusing to launch"
                          % (self.target(), data_source_id))

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


class Round:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.name = str(args.round) + ("-only-" + args.only.replace(",", "+") if args.only else "")
        self.reports = REPORTS / self.name
        self.data = DATA / str(args.round)  # shared by reruns of one round, so --only can reuse artifacts
        for d in (self.reports, self.data):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        self.env = read_env()
        for key, value in self.env.items():  # registered before anything is written
            if key in SECRET_KEYS or re.search(r"KEY|TOKEN|SECRET|PASSWORD", key):
                checks.register_secret(value)
        self.config = ConfigSnapshot(Path(args.config), self.data)  # children only ever see this frozen copy
        self.cfg = self.config.cfg
        self.counter = REPORTS / "platform_runs.json"
        self.incomplete: list[str] = []
        self.profile = json.loads((HERE / "profile_e2e.json").read_text())
        self.findings: list[dict] = []
        self.results: dict[str, str] = {}
        self.skipped: set[str] = set()
        self.runs: list[dict] = []
        self.notes: list[str] = []
        self.notion: Notion | None = None
        self.only = set(args.only.split(",")) if args.only else None
        self.contacts: set[str] = set()
        for f in sorted(DATA.glob("*/*-items.json")):  # contacts of earlier rounds are scrubbed too
            with contextlib.suppress(ValueError, OSError):
                self.collect_contacts(json.loads(f.read_text()) or [])
        for f in sorted(DATA.glob("*/*-pages.json")):
            with contextlib.suppress(ValueError, OSError):
                self.page_contacts(json.loads(f.read_text()) or [])

    # bookkeeping

    def wanted(self, check_id: str) -> bool:
        return self.only is None or check_id in self.only or check_id.split(".")[0] in self.only

    def record(self, check_ids: list[str], found: list[dict]) -> None:
        found = [f for f in found if self.wanted(f["check_id"])]
        for cid in check_ids:
            if not self.wanted(cid) or cid in self.skipped:
                continue
            mine = [f for f in found if f["check_id"] == cid]
            worst = min((["blocker", "major", "minor"].index(f["severity"]) for f in mine), default=None)
            self.results[cid] = "pass" if worst is None else "FAIL (%s, %d)" % (["blocker", "major", "minor"][worst], len(mine))
        self.findings += found

    def skip(self, check_id: str, why: str) -> None:
        if self.wanted(check_id):
            self.results[check_id] = "skipped: " + why
            self.skipped.add(check_id)

    def open_notion(self) -> Notion:
        if self.notion is None:
            version = json.loads((SKILL_DIR / "reference" / "notion_contract.json").read_text())["notion_api_version"]
            self.notion = Notion(self.env["NOTION_TOKEN"], self.config.target(), version)
            self.notion.guard((self.cfg.get("notion") or {}).get("database_id"))
        return self.notion

    def launch_check(self) -> Notion:
        """At every launch boundary: the config is unchanged since round start and Notion still says e2e."""
        n = self.open_notion()
        self.config.verify(n.ds)
        n.guard((self.cfg.get("notion") or {}).get("database_id"))
        return n

    def snapshot(self, bodies_for: set[str] | None = None, all_bodies: bool = False) -> list[dict]:
        n = self.open_notion()
        pages = []
        for page in n.pages():
            want = all_bodies or (bodies_for is not None and page["id"] in bodies_for)
            pages.append(simple_page(page, n.body(page["id"]) if want else None))
        self.page_contacts(pages)
        return pages

    def page_contacts(self, pages: list[dict]) -> None:
        for p in pages:
            if not isinstance(p, dict):  # before-pages.json holds page ids only
                continue
            for key in ("Contact", "Email", "Phone"):
                if (p.get("props") or {}).get(key):
                    self.contacts.add(str(p["props"][key]))
                    checks.register_contact(str(p["props"][key]))

    def collect_contacts(self, items: list[dict]) -> None:
        for item in items:
            for source in item.get("sources") or []:
                for key in ("name", "email", "phone"):
                    value = (source.get("contact") or {}).get(key)
                    if value:
                        self.contacts.add(str(value))
                        checks.register_contact(str(value))

    # round setup: the pages L4 and L5 change are recorded, and reset at the next round start

    def touched_file(self) -> Path:
        return DATA / "touched-pages.json"

    def touched(self) -> list[str]:
        known = load_json(self.touched_file())
        if known is None:  # first use: seed with what earlier rounds changed (L4 edits, call.py's Not booked)
            known = [e["page_id"] for f in sorted(DATA.glob("*/L4-edited.json")) for e in [load_json(f) or {}]
                     if e.get("page_id")]
            known += [p["page_id"] for p in self.snapshot() if p["status"] == "Not booked"]
            known = sorted(set(known))
            save_json(self.touched_file(), known)
        return known

    def touch(self, page_id: str) -> None:
        known = set(self.touched())
        known.add(page_id)
        save_json(self.touched_file(), sorted(known))

    def prepare_pool(self, needed: int) -> None:
        """Make sure `needed` Shortlisted pages exist for L4 (1) and L5 (2). Only pages this harness changed in an
        earlier round are reset (Status Shortlisted, Interested? and Reason cleared), only in the e2e database (every
        write goes through the guarded client), and only as many as are missing."""
        n = self.launch_check()
        pages = self.snapshot()
        spare = [p for p in pages if p["status"] == "Shortlisted" and p["property_id"]
                 and p["props"].get("Match") in ("Strong", "Needs info")]
        missing = needed - len(spare)
        touched = set(self.touched())
        resettable = sorted((p for p in pages if p["page_id"] in touched and p["status"] != "Shortlisted"
                             and p["property_id"] and p["props"].get("Match") in ("Strong", "Needs info")),
                            key=lambda p: p["property_id"])
        reset = []
        for page in resettable[:max(missing, 0)]:
            properties = {"Status": {"select": {"name": "Shortlisted"}}, "Reason": {"rich_text": []}}
            if "Interested?" in n.properties:
                properties["Interested?"] = {"select": None}
            n.write_page(page["page_id"], properties)
            reset.append(page["property_id"])
        self.notes.append("setup: %d Shortlisted pages, %d needed, reset %d touched by earlier rounds %s"
                          % (len(spare), needed, len(reset), reset))

    # layers

    def l0(self) -> None:
        for cid, cmd, cwd in (
            ("L0.apify_pytest", [str(APIFY_DIR / ".venv/bin/python"), "-m", "pytest", "-q", "-m", "not live"], APIFY_DIR),
            ("L0.skill_unittest", ["python3", "-m", "unittest", "discover", "-s", "tests"], SKILL_DIR),
        ):
            if not self.wanted(cid):
                continue
            raw = self.data / ("%s.log" % cid)
            code, secs = run_logged(cmd, raw, cwd=cwd, env=child_env({}, ()), timeout=900)
            text = publish(raw, self.reports / raw.name)
            found = []
            if code != 0:
                failing = sorted(set(re.findall(r"(?:FAILED|ERROR) tests/(test_\w+)\.py", text)
                                     + re.findall(r"^(?:FAIL|ERROR): \w+ \((test_\w+)\.", text, re.M)))
                for name in failing or ["unknown"]:
                    path = L0_OWNERS.get(name, "apify/domovoy/pipeline.py")
                    excerpt = "\n".join(l for l in text.splitlines() if name in l)[:300]
                    found.append(checks.finding(cid, "blocker", "offline tests fail in %s (exit %d)" % (name, code), path,
                                                "cd %s && %s" % (cwd.relative_to(REPO), " ".join(cmd[1:] if "pytest" in cmd else cmd)),
                                                excerpt=excerpt))
            self.record([cid], found)
            self.notes.append("%s: exit %d in %.0f s; last line: %s" % (cid, code, secs, (text.strip().splitlines() or [""])[-1][:120]))

    def l1(self) -> None:
        cids = ["L1.exit_zero", "L1.summary_valid", "L1.sources_ok", "L1.time_budget", "L1.notion_errors"]
        n = self.launch_check()
        storage = APIFY_DIR / "storage"
        shutil.rmtree(storage / "datasets" / "default", ignore_errors=True)
        for f in (storage / "key_value_stores" / "default").glob("OUTPUT*"):
            f.unlink()
        input_file = self.data / "L1-input.json"
        write_private(input_file, {"mode": "search", "profile": self.profile, "notion": {"dataSourceId": n.ds},
                                   "includeUnchanged": True})
        cmd = ["apify", "run", "--input-file", str(input_file), "--user-agent", UA]
        raw = self.data / "L1-local-run.log"
        log("L1: local apify run (budget %d s)" % RUN_BUDGET_SEC)
        code, secs = run_logged(cmd, raw, cwd=APIFY_DIR, timeout=RUN_BUDGET_SEC * 1.5, heavy="l1-local",
                                env=child_env(self.env, ("NOTION_TOKEN", "FEATHERLESS_API_KEY", "OPENAI_API_KEY")))
        summary = None
        outputs = sorted((storage / "key_value_stores" / "default").glob("OUTPUT*"))
        outputs = [o for o in outputs if not o.name.endswith("__metadata__.json")]
        if outputs:
            summary = json.loads(outputs[0].read_text())
        items = [json.loads(p.read_text()) for p in sorted((storage / "datasets" / "default").glob("*.json"))
                 if not p.name.startswith("__")]
        save_json(self.data / "L1-items.json", items)
        save_json(self.data / "L1-summary.json", summary)
        self.collect_contacts(items)
        run_id = (summary or {}).get("run_id")
        self.runs.append({"layer": "L1", "kind": "local", "run_id": run_id, "exit": code, "seconds": round(secs),
                          "items": len(items)})
        how = "exit %d" % code + (" (killed after %d s)" % secs if code == -9 else "")
        tail = "\n".join(publish(raw, self.reports / raw.name).splitlines()[-5:])  # after the contacts are known
        self.record(cids, checks.check_run("L1", run_id=run_id, ok=code == 0, how=how + "\n" + tail, elapsed=secs,
                                           budget=RUN_BUDGET_SEC, summary=summary))

    def platform_run(self, label: str, include_unchanged: bool) -> tuple[dict | None, list[dict], dict | None, float]:
        self.launch_check()
        rid = reserve_platform_run(self.counter, self.name, label)  # locked check-and-reserve before the launch
        cmd = ["python3", str(SKILL_DIR / "scripts" / "search.py"), "run"]
        if include_unchanged:
            cmd.append("--include-unchanged")
        log("%s: platform run via search.py (reserved %d/%d)" % (label, len(load_json(self.counter) or []),
                                                                  MAX_PLATFORM_RUNS))
        out_file, err_file = self.data / ("%s-search.json" % label), self.data / ("%s-search.log" % label)
        start = time.monotonic()
        with open(out_file, "w") as out, open(err_file, "w") as err:
            heavy = [str(HEAVY), "--dir", str(HEAVY_DIR), "--label", "e2e-" + label, "--"]
            code = subprocess.run(heavy + cmd, cwd=REPO, stdout=out, stderr=err, timeout=1800,
                                  env=child_env(self.env, ("APIFY_TOKEN",), {"DOMOVOY_CONFIG": str(self.config.path)})).returncode
        secs = time.monotonic() - start
        try:
            printed = json.loads(out_file.read_text())
        except ValueError:
            printed = {"error": "search.py printed no JSON (exit %d)" % code}
        run_id = printed.get("run_id")
        update_reservation(self.counter, rid, run_id)
        platform_log = None
        summary, items = None, []
        if run_id:
            api = httpx.Client(timeout=60, headers={"Authorization": "Bearer " + self.env["APIFY_TOKEN"]})
            run = api.get("%s/actor-runs/%s" % (APIFY, run_id)).json()["data"]
            r = api.get("%s/key-value-stores/%s/records/OUTPUT" % (APIFY, run["defaultKeyValueStoreId"]))
            summary = r.json() if r.status_code == 200 else None
            items = api.get("%s/datasets/%s/items" % (APIFY, run["defaultDatasetId"]), params={"clean": 1, "format": "json"}).json()
            platform_log = self.data / ("%s-platform.log" % label)
            platform_log.write_text(api.get("%s/actor-runs/%s/log" % (APIFY, run_id)).text)
            printed["build"] = run.get("buildNumber")
        save_json(self.data / ("%s-items.json" % label), items)
        save_json(self.data / ("%s-summary.json" % label), summary)
        self.collect_contacts(items)
        for raw in (out_file, err_file, platform_log):  # sanitized copies, once this run's contacts are known
            if raw is not None:
                publish(raw, self.reports / raw.name)
        self.runs.append({"layer": label, "kind": "platform", "run_id": run_id, "status": printed.get("status"),
                          "exit": code, "seconds": round(secs), "items": len(items), "build": printed.get("build")})
        return printed, items, summary, secs

    def l2(self) -> None:
        cids = ["L2.run_succeeded", "L2.summary_readable", "L2.summary_valid", "L2.sources_ok", "L2.time_budget",
                "L2.notion_errors"]
        self.open_notion()
        printed, items, summary, secs = self.platform_run("L2a", include_unchanged=True)
        ok = printed.get("status") == "SUCCEEDED"
        self.record(cids, checks.check_run("L2", run_id=printed.get("run_id"), ok=ok,
                                           how="%s %s" % (printed.get("status"), printed.get("error") or ""),
                                           elapsed=secs, budget=RUN_BUDGET_SEC, summary=summary, readable=printed))

    def l3(self, before_ids: set[str]) -> None:
        cids = ["L3.dataset_schema", "L3.flatitem_schema", "L3.money_int", "L3.time_offset", "L3.url_collected",
                "L3.quotes_verified", "L3.dedup_missed", "L3.one_page_per_property", "L3.new_page_shortlisted",
                "L3.page_body", "L3.item_has_page", "L3.page_matches_item", "L3.summary_counts", "L3.body_no_contacts"]
        schema = load_json(APIFY_DIR / ".actor" / "dataset_schema.json")
        sets = []
        for label in ("L1", "L2a"):
            items, summary = load_json(self.data / ("%s-items.json" % label)), load_json(self.data / ("%s-summary.json" % label))
            if items is not None:
                sets.append((label, items, summary))
        if self.args.offline_items:
            sets = [("offline", json.loads(Path(self.args.offline_items).read_text()),
                     json.loads(Path(self.args.offline_summary).read_text()) if self.args.offline_summary else None)]
        if not sets:
            for cid in cids:
                self.skip(cid, "no dataset (L1/L2 did not run)")
            return
        found = []
        for i, (label, items, summary) in enumerate(sets):
            run_id = (summary or {}).get("run_id") or label
            self.collect_contacts(items)
            found += checks.check_items(items, run_id, schema if i == 0 else None)
            found += checks.check_dedup(items, run_id)
            if summary is not None:
                found += checks.check_counts(items, summary, run_id, include_unchanged=True)
        label, items, summary = sets[-1]
        run_id = (summary or {}).get("run_id") or label
        if self.args.offline_items:
            self.skip("L3.quotes_verified", "offline (no portal requests)")
        elif self.wanted("L3.quotes_verified"):
            verified = skipped = 0
            for item in items[:15]:
                texts = refetch_texts(item)
                if texts is None:
                    skipped += 1
                else:
                    verified += 1
                found += checks.check_quotes(item, texts, run_id)
            self.notes.append("L3.quotes_verified: %d items re-fetched (every source), %d skipped (a source could not be fetched)" % (verified, skipped))
        if self.args.offline_items:
            for cid in cids[7:]:
                self.skip(cid, "offline")
            self.skip("L3.summary_counts", "offline")
        else:
            pages = self.snapshot()
            new_ids = {p["page_id"] for p in pages if p["page_id"] not in before_ids}
            pages = self.snapshot(bodies_for=new_ids)
            save_json(self.data / "L3-pages.json", pages)
            found += checks.check_pages(pages, items, before_ids, run_id, include_unchanged=True)
            found += checks.check_bodies([p for p in pages if p["body"] is not None], run_id)
            self.notes.append("L3: %d pages in the e2e database, %d created this round" % (len(pages), len(new_ids)))
        self.record(cids, found)

    def l4(self) -> None:
        cids = ["L4.no_new_pages", "L4.unchanged_reported", "L4.edits_kept", "L4.property_ids_stable", "L2b.run_succeeded"]
        n = self.launch_check()
        pages = self.snapshot()
        candidates = sorted((p for p in pages if p["status"] == "Shortlisted" and p["property_id"]),
                            key=lambda p: p["property_id"])
        if not candidates:
            for cid in cids:
                self.skip(cid, "no Shortlisted page to edit")
            self.incomplete.append("L4 had no Shortlisted page to edit")
            return
        target = candidates[0]
        edited = {"page_id": target["page_id"], "status": "Not interested", "reason": "e2e round %s edit" % self.args.round,
                  "marker": "e2e-marker r%s %s" % (self.args.round, uuid.uuid4().hex[:8])}
        self.touch(target["page_id"])
        n.write_page(target["page_id"], {"Status": {"select": {"name": edited["status"]}},
                                         "Reason": {"rich_text": [{"type": "text", "text": {"content": edited["reason"]}}]}})
        n.append(target["page_id"], edited["marker"])
        save_json(self.data / "L4-edited.json", edited)
        self.notes.append("L4: edited page %s (property %s)" % (target["page_id"], target["property_id"]))
        before = self.snapshot()
        items1 = load_json(self.data / "L2a-items.json") or []
        printed, items2, summary2, secs = self.platform_run("L2b", include_unchanged=False)
        found = []
        if printed.get("status") != "SUCCEEDED":
            found.append(checks.finding("L2b.run_succeeded", "blocker", "second platform run: %s" % printed.get("status"),
                                        "skill/domovoy/scripts/search.py", checks.rerun("L4"), run_id=printed.get("run_id")))
        after_ids = {p["page_id"] for p in self.snapshot()} - {p["page_id"] for p in before}
        after = self.snapshot(bodies_for=after_ids | {target["page_id"]})
        found += checks.check_idempotency(before, after, summary2, items1, items2, edited, printed.get("run_id"))
        if summary2:
            found += checks.check_counts(items2, summary2, printed.get("run_id"), include_unchanged=False)
        self.record(cids + ["L3.summary_counts"] if self.wanted("L3.summary_counts") else cids, found)

    def l5(self) -> None:
        cids = ["L5.context_schema", "L5.context_matches_page", "L5.budget_cap", "L5.interested_trigger", "L5.fake_phone_run"]
        n = self.launch_check()
        pages = self.snapshot()
        edited = (load_json(self.data / "L4-edited.json") or {}).get("page_id")
        cap = self.profile["requirements"]["max_total_monthly"]
        pool = [p for p in pages if p["status"] == "Shortlisted" and p["page_id"] != edited and p["property_id"]
                and p["props"].get("Match") in ("Strong", "Needs info")]
        pool.sort(key=lambda p: (p["props"].get("Total monthly") is None, p["property_id"]))
        if len(pool) < 2:
            for cid in cids:
                self.skip(cid, "fewer than 2 Shortlisted pages")
            self.incomplete.append("L5 had %d of 2 Shortlisted pages" % len(pool))
            return
        work = self.data / "L5"
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(SKILL_DIR, work / "skill", ignore=shutil.ignore_patterns(".state", "config.json", "__pycache__"))
        cfg = json.loads(json.dumps(self.cfg))
        cfg["backend"] = {"module": "scripts/notion.py"}
        cfg["phone"] = {"url": "", "secret": "", "env_file": str(work / "no-env-file"), "url_env": "E2E_PHONE_URL",
                        "secret_env": "E2E_PHONE_SECRET", "poll_seconds": 1, "timeout_seconds": 40}
        cfg.setdefault("call_context", {}).update({"user_name": "E2E Tester", "realtor_name": "Demo Realtor"})
        cfg["call_context"].pop("budget_cap", None)
        cfg_path = work / "config.l5.json"
        write_private(cfg_path, cfg)
        secret = uuid.uuid4().hex
        env = child_env(self.env, ("NOTION_TOKEN",), {"DOMOVOY_CONFIG": str(cfg_path), "E2E_PHONE_URL":
                        "http://127.0.0.1:%d" % PHONE_PORT, "E2E_PHONE_SECRET": secret, "DOMOVOY_SECRET": secret})
        server = subprocess.Popen(["python3", str(SKILL_DIR / "tests" / "fake_phone_server.py"), str(PHONE_PORT)],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        server.stdout.readline()
        schema = json.loads((work / "skill" / "reference" / "call_context.schema.json").read_text())
        import jsonschema
        tomorrow = (dt.datetime.now(PRAGUE) + dt.timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        windows = json.dumps([{"start": tomorrow.isoformat(), "end": (tomorrow + dt.timedelta(hours=3)).isoformat()}])
        has_interested = "Interested?" in n.properties
        found = []
        try:
            for i, page in enumerate(pool[:2]):
                via_select = i == 1 and has_interested
                self.touch(page["page_id"])
                if via_select:
                    n.write_page(page["page_id"], {"Interested?": {"select": {"name": "Yes"}}})
                else:
                    n.write_page(page["page_id"], {"Status": {"select": {"name": "Interested"}}})
                self.notes.append("L5: page %s (property %s) marked via %s" % (page["page_id"], page["property_id"],
                                  "Interested? = Yes" if via_select else "Status = Interested"))
                call = ["python3", str(work / "skill" / "scripts" / "call.py")]
                self.launch_check()
                check = subprocess.run(call + ["check", "--windows", windows, "--page", page["page_id"]], env=env,
                                       capture_output=True, text=True, timeout=120)
                try:
                    out = json.loads(check.stdout)
                except ValueError:
                    out = {"error": "call.py printed no JSON (exit %d)" % check.returncode}
                context = out.get("call_context")
                if context is None:
                    cid = "L5.interested_trigger" if via_select and out.get("refused") else "L5.context_schema"
                    path = "skill/domovoy/scripts/notion.py" if via_select else "skill/domovoy/scripts/call.py"
                    found.append(checks.finding(cid, "major" if via_select else "blocker",
                                                "call.py check built no call_context (exit %d)" % check.returncode, path,
                                                checks.rerun("L5"), property_id=page["property_id"], page_id=page["page_id"],
                                                excerpt=checks.pick(out, ("refused", "reason", "error", "valid"))))
                    continue
                errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(context)]
                found += checks.check_call_context(context, page, cap, errors)
                found += self.fake_call(call, windows, page, env, secret)
        finally:
            server.terminate()
        self.record(cids, found)

    def fake_call(self, call: list[str], windows: str, page: dict, env: dict, secret: str) -> list[dict]:
        base = "http://127.0.0.1:%d" % PHONE_PORT
        self.launch_check()
        proc = subprocess.Popen(call + ["run", "--windows", windows, "--page", page["page_id"]], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        pending = None
        for _ in range(60):
            r = httpx.get(base + "/api/pending")
            if r.status_code == 200:
                pending = r.json()
                break
            time.sleep(0.5)
        def fail(why: str, excerpt: str = "") -> list[dict]:
            return [checks.finding("L5.fake_phone_run", "major", why, "skill/domovoy/scripts/call.py", checks.rerun("L5"),
                                   property_id=page["property_id"], page_id=page["page_id"], excerpt=excerpt)]
        if pending is None:
            proc.kill()
            return fail("call.py run posted nothing to the fake phone server")
        result = {"property_id": pending["property_id"], "conversation_id": "e2e-r%s-%s" % (self.args.round, uuid.uuid4().hex[:8]),
                  "outcome": "not_booked", "viewing_start": None, "answers": [], "new_costs": [],
                  "summary": "E2E synthetic result from the fake phone server; no call happened."}
        httpx.post(base + "/api/result", json=result)
        try:
            stdout, _ = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            return fail("call.py run did not finish within 90 s")
        try:
            out = json.loads(stdout)
        except ValueError:
            return fail("call.py run printed no JSON (exit %d)" % proc.returncode)
        status = simple_page(self.open_notion().call("GET", "/pages/%s" % page["page_id"]))["status"]
        if proc.returncode != 0 or out.get("status") != "Not booked" or status != "Not booked":
            return fail("call.py run: exit %d, reported %r, page Status %r (expected Not booked)"
                        % (proc.returncode, out.get("status"), status),
                        checks.pick(out, ("status", "booked", "reason", "error", "refused", "already_handled")))
        return []

    def l6(self) -> None:
        cids = ["L6.no_secrets", "L6.no_contacts_reports", "L6.no_contacts_repo", "L6.fixture_scrub"]
        for label in ("L1", "L2a", "L2b"):
            self.collect_contacts(load_json(self.data / ("%s-items.json" % label)) or [])
        secrets, contacts = checks.known_secrets(), checks.known_contacts()
        found = []
        allow = ("noreply@anthropic.com", "example.com", "example.org")
        for f in sorted(REPORTS.rglob("*")):
            if f.is_file() and f.suffix in (".md", ".json", ".log", ".txt"):
                kinds = checks.scan_text(f.read_text(errors="replace"), secrets, contacts, allow)
                for kind in kinds:
                    cid = "L6.no_secrets" if kind == "secret" else "L6.no_contacts_reports"
                    path = "apify/domovoy/pipeline.py" if f.name.startswith(("L1-", "L2")) else "apify/e2e/run_e2e.py"
                    found.append(checks.finding(cid, "blocker", "%s found in %s" % (kind, f.relative_to(REPORTS)),
                                                path, checks.rerun("L6")))
        base = subprocess.run(["git", "merge-base", "origin/main", "HEAD"], cwd=REPO, capture_output=True,
                              text=True).stdout.strip()
        diff = subprocess.run(["git", "diff", base], cwd=REPO, capture_output=True, text=True).stdout  # ours only
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO, capture_output=True,
                                   text=True).stdout.split()
        for name in untracked:
            try:
                diff += (REPO / name).read_text(errors="replace")
            except OSError:
                pass
        for kind in checks.scan_text(diff, secrets, contacts, allow):
            found.append(checks.finding("L6.no_secrets" if kind == "secret" else "L6.no_contacts_repo", "blocker",
                                        "%s found in the branch diff (merge base with origin/main)" % kind, "apify/e2e/",
                                        checks.rerun("L6")))
        for root in (APIFY_DIR / "tests" / "fixtures", SKILL_DIR / "tests"):
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.suffix in (".json", ".html", ".txt", ".md"):
                    kinds = [k for k in checks.scan_text(f.read_text(errors="replace"), secrets, contacts, allow)]
                    for kind in kinds:
                        found.append(checks.finding("L6.fixture_scrub", "blocker", "%s in fixture %s" % (kind, f.relative_to(REPO)),
                                                    str(f.relative_to(REPO)), checks.rerun("L6.fixture_scrub")))
        self.notes.append("L6: scanned reports, the repo diff and fixtures against %d secrets and %d contact strings"
                          % (len(secrets), len(contacts)))
        self.record(cids, found)

    # report

    def status(self) -> str:
        if any(f["severity"] == "blocker" for f in self.findings):
            return "BLOCKERS"
        if self.incomplete:
            return "INCOMPLETE (%s)" % "; ".join(self.incomplete)
        majors = sum(1 for f in self.findings if f["severity"] == "major")
        if majors:
            return "MAJORS (%d)" % majors  # never GREEN with a major recorded
        return "GREEN" if self.args.only is None and self.args.layers is None else "PASS (partial: %s)" % (
            self.args.only or self.args.layers)

    def write_report(self, started: dt.datetime) -> None:
        for f in sorted(self.reports.iterdir()):  # logs written earlier get every contact known by now
            if f.is_file() and f.name not in ("report.md", "findings.json"):
                publish(f, f)
        self.findings = checks.sanitize_tree(self.findings)
        self.notes = [checks.sanitize(n) for n in self.notes]
        for i, f in enumerate(self.findings, 1):
            f["id"] = "r%s-%03d" % (self.name, i)
        (self.reports / "findings.json").write_text(checks.sanitize(json.dumps(self.findings, indent=2, ensure_ascii=False)))
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        lines = ["# DOMOVOY e2e round %s" % self.name, "", "**Status: %s**" % self.status(), "",
                 "Started %s, finished %s. Repo %s at %s. Profile `%s`. Data source %s." % (
                     started.isoformat(timespec="seconds"), dt.datetime.now(PRAGUE).isoformat(timespec="seconds"), REPO.name,
                     sha, PROFILE_ID, (self.cfg.get("notion") or {}).get("data_source_id")), "",
                 "## Runs", "", "| Layer | Kind | Run ID | Status / exit | Seconds | Items | Build |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in self.runs:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (r["layer"], r["kind"], r.get("run_id"),
                         r.get("status") or r.get("exit"), r["seconds"], r["items"], r.get("build") or ""))
        counter = load_json(self.counter) or []
        lines += ["", "Platform runs used so far: %d of %d." % (len(counter), MAX_PLATFORM_RUNS), "", "## Checks", "",
                  "| Check | Result |", "| --- | --- |"]
        lines += ["| `%s` | %s |" % (cid, res) for cid, res in self.results.items()]
        lines += ["", "## Notes", ""] + ["- " + checks.scrub(n) for n in self.notes]
        for sev in ("blocker", "major", "minor"):
            mine = [f for f in self.findings if f["severity"] == sev]
            if not mine:
                continue
            lines += ["", "## %ss (%d)" % (sev.capitalize(), len(mine)), ""]
            for f in sorted(mine, key=lambda f: (f["owner_wp"], f["check_id"])):
                e = f["evidence"]
                lines.append("- **%s** `%s` [%s] %s. run %s, property %s, page %s. Path `%s`. Repro: `%s`%s" % (
                    f["id"], f["check_id"], f["owner_wp"], f["summary"], e["run_id"], e["property_id"], e["notion_page_id"],
                    f["suspected_path"], f["repro"], ("\n  - excerpt: `%s`" % e["log_excerpt"].replace("`", "'").replace("\n", " ⏎ ")) if e["log_excerpt"] else ""))
        (self.reports / "report.md").write_text(checks.sanitize("\n".join(lines) + "\n"))


def refetch_texts(item: dict) -> list[str] | None:
    """The text of every source listing of the flat as the portals serve it now. The extractor reads a composite
    primary whose missing fields (price_note, description, ...) are filled from the other sources (dedup _primary,
    FILLABLE), so a quote can come from any of them. None unless every source could be fetched: a missing source
    would turn its quotes into false findings."""
    sources = item.get("sources") or []
    if not sources:
        return None
    texts: list[str] = []
    for source in sources:
        fetched = fetch_source_texts(source)
        if fetched is None:
            return None
        texts += fetched
    return texts


def fetch_source_texts(source: dict) -> list[str] | None:
    """One listing: every string of the Sreality API detail, or the visible text plus every JSON string of the HTML
    page (Bezrealitky, iDNES). None when it cannot be fetched."""
    time.sleep(REFETCH_GAP_SEC)  # polite: one request per 1.5 s
    try:
        if source.get("portal") == "sreality":
            r = httpx.get("https://www.sreality.cz/api/v1/estates/%s" % source["source_id"], timeout=30,
                          headers={"User-Agent": "DOMOVOY-actor/0.1", "Accept": "application/json"})
            return list(json_strings(r.json())) if r.status_code == 200 else None
        r = httpx.get(source["url"], timeout=30, headers={"Accept": "text/html"}, follow_redirects=True)
        if r.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        texts = [soup.get_text(" ")]
        for script in soup.find_all("script"):
            try:
                texts += list(json_strings(json.loads(script.string or "")))
            except ValueError:
                pass
        return texts
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def json_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from json_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from json_strings(v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--round", required=True)
    parser.add_argument("--only", help="comma-separated check ids or layers (L3.money_int, L5)")
    parser.add_argument("--layers", help="comma-separated layers to run (default all, or those --only needs)")
    parser.add_argument("--config", default=os.environ.get("DOMOVOY_CONFIG") or str(DEFAULT_CONFIG))
    parser.add_argument("--offline-items", help="L3 on a recorded dataset file instead of L1/L2 (no Notion)")
    parser.add_argument("--offline-summary", help="the RunSummary for --offline-items")
    args = parser.parse_args(argv)
    if args.layers:
        layers = args.layers.split(",")
    elif args.only:
        layers = sorted({c.split(".")[0].replace("L2b", "L4") for c in args.only.split(",")})
    else:
        layers = list(LAYERS)
    try:
        rnd = Round(args)
    except (OSError, ValueError, Refused) as e:
        log("REFUSED before the round started: %s" % e)
        return 2
    started = dt.datetime.now(PRAGUE)
    code = 0
    try:
        if rnd.profile["id"] != PROFILE_ID or rnd.profile["filters"].get("max_listings", 150) > 5:
            raise Refused("profile_e2e.json must be %s with max_listings <= 5" % PROFILE_ID)
        cfg_profiles = [p for p in rnd.cfg.get("profiles") or [] if p.get("id") == rnd.cfg.get("active_profile")]
        if not cfg_profiles or cfg_profiles[0] != rnd.profile:
            raise Refused("config active profile must equal apify/e2e/profile_e2e.json")
        before_file = rnd.data / "before-pages.json"
        needed = (1 if "L4" in layers else 0) + (2 if "L5" in layers else 0)
        if needed:
            rnd.prepare_pool(needed)
        if "L0" in layers:
            rnd.l0()
        if any(l in layers for l in ("L1", "L2", "L4", "L5")) or ("L3" in layers and not args.offline_items):
            if not before_file.exists() or "L1" in layers or "L2" in layers:
                save_json(before_file, [p["page_id"] for p in rnd.snapshot()])
        if "L1" in layers:
            rnd.l1()
        if "L2" in layers:
            rnd.l2()
        if "L3" in layers:
            rnd.l3(set(load_json(before_file) or []))
        if "L4" in layers:
            rnd.l4()
        if "L5" in layers:
            rnd.l5()
        if "L6" in layers:
            rnd.l6()
    except Refused as e:
        log("REFUSED: %s" % e)
        rnd.notes.append("refused: %s" % e)
        rnd.incomplete.append("refused: %s" % e)
        code = 2
    except Exception as e:  # the report is still written
        log("harness error: %s: %s" % (type(e).__name__, e))
        rnd.notes.append("harness error: %s: %s" % (type(e).__name__, checks.scrub(e)))
        rnd.incomplete.append("harness error")
        code = 3
    finally:
        rnd.config.close()
    rnd.write_report(started)
    blockers = [f for f in rnd.findings if f["severity"] == "blocker"]
    majors = [f for f in rnd.findings if f["severity"] == "major"]
    log("round %s: %s; %d blockers, %d majors, %d findings; report %s" % (
        rnd.name, rnd.status(), len(blockers), len(majors), len(rnd.findings), rnd.reports / "report.md"))
    if code:
        return code
    if blockers:
        return 1
    return 4 if rnd.incomplete else 0  # an incomplete round is never green


if __name__ == "__main__":
    sys.exit(main())
