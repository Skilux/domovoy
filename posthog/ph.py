#!/usr/bin/env python3
"""DOMOVOY PostHog client: send events and read them back. Standard library only.

  ph.py capture EVENT [--id DISTINCT_ID] [--props JSON]   send one event
  ph.py query "HogQL"                                      run a query, print JSON rows
  ph.py smoke                                              send one test event, then read it back

Reads the repo-root .env (or the environment):
  POSTHOG_PROJECT_TOKEN      phc_...  public by design, used for capture
  POSTHOG_PERSONAL_API_KEY   phx_...  private, scope query:read, used for query
  POSTHOG_PROJECT_ID         numeric project id, used for query
  POSTHOG_HOST               app host, default https://eu.posthog.com
  POSTHOG_INGEST_HOST        capture host, default https://eu.i.posthog.com

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = {
    "POSTHOG_HOST": "https://eu.posthog.com",
    "POSTHOG_INGEST_HOST": "https://eu.i.posthog.com",
}


def load_env(path=None):
    env = dict(DEFAULTS)
    path = path or os.path.join(ROOT, ".env")
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
        raise SystemExit("missing %s: set it in %s" % (key, os.path.join(ROOT, ".env")))
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
    url = "%s/api/projects/%s/query/" % (env["POSTHOG_HOST"].rstrip("/"), need(env, "POSTHOG_PROJECT_ID"))
    body = {"query": {"kind": "HogQLQuery", "query": hogql}, "name": name, "refresh": "force_blocking"}
    _, out = post(url, body, {"Authorization": "Bearer " + need(env, "POSTHOG_PERSONAL_API_KEY")}, timeout=60)
    columns = out.get("columns") or []
    return [dict(zip(columns, row)) for row in out.get("results") or []]


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
