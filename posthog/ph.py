#!/usr/bin/env python3
"""DOMOVOY PostHog client: send events and read them back. Standard library only.

  ph.py capture EVENT [--id DISTINCT_ID] [--props JSON]   send one event
  ph.py query "HogQL"                                      run a query, print JSON rows
  ph.py smoke                                              send one test event, then read it back

Also imported by loop.py: capture, query, api (private REST), flags (public flag evaluation), mcp (one MCP tool call).

Reads ~/.config/domovoy/.env (or the file named by DOMOVOY_ENV_FILE); the environment wins:
  POSTHOG_PROJECT_TOKEN      phc_...  public by design, used for capture
  POSTHOG_INGEST_HOST        capture host, default https://eu.i.posthog.com
  POSTHOG_APP_HOST           app host for queries, default https://eu.posthog.com
  POSTHOG_PROJECT_ID         numeric project id, used for query
  POSTHOG_PERSONAL_API_KEY   phx_...  private, used for query

Exit codes: 0 ok, 1 error.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

ENV_FILE = os.environ.get("DOMOVOY_ENV_FILE") or os.path.expanduser("~/.config/domovoy/.env")
MCP_URL = "https://mcp.posthog.com/mcp?mode=cli"
DEFAULTS = {
    "POSTHOG_APP_HOST": "https://eu.posthog.com",
    "POSTHOG_INGEST_HOST": "https://eu.i.posthog.com",
}


def load_env(path=None):
    env = dict(DEFAULTS)
    path = path or ENV_FILE
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("'\"")
    for key, value in os.environ.items():
        if key.startswith("POSTHOG_") and value:
            env[key] = value
    return env


def need(env, key):
    if not env.get(key):
        raise SystemExit("missing %s: set it in %s" % (key, ENV_FILE))
    return env[key]


def post(url, body, headers=None, timeout=30):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "domovoy-posthog/1")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit("HTTP %s from %s: %s" % (e.code, url.split("?")[0], e.read().decode("utf-8")[:500]))


def capture(event, distinct_id, properties=None, env=None):
    env = env or load_env()
    body = {
        "api_key": need(env, "POSTHOG_PROJECT_TOKEN"),
        "event": event,
        "distinct_id": distinct_id,
        "properties": dict(properties or {}),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    status, _ = post(env["POSTHOG_INGEST_HOST"].rstrip("/") + "/i/v0/e/", body)
    return status


def query(hogql, env=None, name="domovoy"):
    env = env or load_env()
    url = "%s/api/projects/%s/query/" % (env["POSTHOG_APP_HOST"].rstrip("/"), need(env, "POSTHOG_PROJECT_ID"))
    body = {"query": {"kind": "HogQLQuery", "query": hogql}, "name": name, "refresh": "force_blocking"}
    _, out = post(url, body, {"Authorization": "Bearer " + need(env, "POSTHOG_PERSONAL_API_KEY")}, timeout=60)
    columns = out.get("columns") or []
    return [dict(zip(columns, row)) for row in out.get("results") or []]


def api(method, path, body=None, env=None):
    """Private REST API under /api/projects/<id>/. Returns parsed JSON."""
    env = env or load_env()
    url = "%s/api/projects/%s/%s" % (env["POSTHOG_APP_HOST"].rstrip("/"), need(env, "POSTHOG_PROJECT_ID"), path.lstrip("/"))
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "domovoy-posthog/1")
    req.add_header("Authorization", "Bearer " + need(env, "POSTHOG_PERSONAL_API_KEY"))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit("HTTP %s from %s %s: %s" % (e.code, method, path, e.read().decode("utf-8")[:500]))


def flags(distinct_id, env=None):
    """Evaluate feature flags with the public token. Returns {key: {"enabled", "payload"}}."""
    env = env or load_env()
    body = {"api_key": need(env, "POSTHOG_PROJECT_TOKEN"), "distinct_id": distinct_id}
    _, out = post(env["POSTHOG_INGEST_HOST"].rstrip("/") + "/flags?v=2", body)
    result = {}
    for key, flag in (out.get("flags") or {}).items():
        payload = (flag.get("metadata") or {}).get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                pass
        result[key] = {"enabled": bool(flag.get("enabled")), "payload": payload}
    return result


def mcp(tool, arguments, env=None):
    """Call one PostHog MCP tool over HTTP with the personal key. Returns the text result."""
    env = env or load_env()
    headers = {
        "Authorization": "Bearer " + need(env, "POSTHOG_PERSONAL_API_KEY"),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-posthog-project-id": need(env, "POSTHOG_PROJECT_ID"),
        "User-Agent": "domovoy-posthog/1",
    }
    session = {}

    def rpc(method, params, notify=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = 1
        h = dict(headers)
        if session.get("id"):
            h["Mcp-Session-Id"] = session["id"]
        req = urllib.request.Request(MCP_URL, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                session["id"] = resp.headers.get("Mcp-Session-Id") or session.get("id")
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise SystemExit("HTTP %s from MCP %s: %s" % (e.code, method, e.read().decode("utf-8")[:500]))
        if notify or not raw.strip():
            return None
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
        out = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    out = json.loads(line[5:].strip())
                except ValueError:
                    pass
        return out

    rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "domovoy", "version": "1"}})
    rpc("notifications/initialized", {}, notify=True)
    out = rpc("tools/call", {"name": "exec", "arguments": {"command": "call %s %s" % (tool, json.dumps(arguments))}})
    result = (out or {}).get("result") or {}
    text = "\n".join(c.get("text", "") for c in result.get("content") or [])
    if result.get("isError") or text.startswith("Error:") or not result:
        raise SystemExit("MCP %s failed: %s" % (tool, (text or json.dumps(out))[:800]))
    return text


def smoke(env=None, wait=90):
    env = env or load_env()
    marker = uuid.uuid4().hex
    started = time.time()
    status = capture("domovoy_smoke_test", "domovoy-setup", {"marker": marker, "synthetic": True}, env)
    print("capture: HTTP %s, marker %s" % (status, marker))
    sql = (
        "select uuid, event, distinct_id, timestamp from events "
        "where event = 'domovoy_smoke_test' and properties.marker = '%s' limit 1" % marker
    )
    while time.time() - started < wait:
        rows = query(sql, env, "domovoy smoke test")
        if rows:
            print("read back after %.0f s: %s" % (time.time() - started, json.dumps(rows[0], default=str)))
            return 0
        time.sleep(3)
    print("not visible through the query API after %s s" % wait)
    return 1


def main():
    parser = argparse.ArgumentParser(description="DOMOVOY PostHog client")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("event")
    c.add_argument("--id", default="domovoy-setup")
    c.add_argument("--props", default="{}")
    q = sub.add_parser("query")
    q.add_argument("hogql")
    sub.add_parser("smoke")
    args = parser.parse_args()
    if args.cmd == "capture":
        print("HTTP %s" % capture(args.event, args.id, json.loads(args.props)))
        return 0
    if args.cmd == "query":
        print(json.dumps(query(args.hogql), indent=2, default=str))
        return 0
    return smoke()


if __name__ == "__main__":
    sys.exit(main())
