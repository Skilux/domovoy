#!/usr/bin/env python3
"""DOMOVOY demo: run the call command end to end with no accounts and no network. Standard library only.

  demo.py call [--outcome booked|not_booked]

Everything is SYNTHETIC. The shortlist is the FAKE Notion backend (tests/fake_notion_backend.py, one made-up
flat), the phone is the FAKE phone server (tests/fake_phone_server.py) started inside this process on
127.0.0.1, and nobody speaks: a made-up call result is posted in place of the voice agent. The real call.py
runs against them, so the context checks, the status changes, the recheck and the printed event are the real
code. Nothing is written outside a temporary folder, and config.json and the env file are not read.

Output is one JSON object: {"synthetic": true, "note", "call": <what call.py printed>, "page": <the fake page>}.
The event inside "call" is part of the demo: do not create it in a real calendar.
Exit codes are those of call.py: 0 handled, 2 refused, 1 error.
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import call  # noqa: E402
import fake_notion_backend  # noqa: E402
import fake_phone_server  # noqa: E402

PAGE = "fake-page-001"
NOTE = ("SYNTHETIC demo run: fake shortlist, fake phone server, made-up call result. No service was contacted "
        "and nobody was called. Do not create the event in a real calendar.")
PRAGUE = datetime.timezone(datetime.timedelta(hours=1))  # the demo window is in winter time


def demo_window():
    """One made-up free window: the next Monday, 17:00 to 18:00."""
    day = datetime.date.today() + datetime.timedelta(days=1)
    while day.weekday() != 0:
        day += datetime.timedelta(days=1)
    start = datetime.datetime.combine(day, datetime.time(17, 0), PRAGUE)
    return {"start": start.isoformat(), "end": (start + datetime.timedelta(hours=1)).isoformat()}


def answer_the_phone(url, outcome, window, stop):
    """Stands in for the phone page and the voice agent: takes the pending call and posts a made-up result."""
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url + "/api/pending", timeout=5) as response:
                context = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            time.sleep(0.1)
            continue
        booked = outcome == "booked"
        result = {
            "property_id": context["property_id"],
            "conversation_id": "synthetic-demo-" + secrets.token_hex(4),
            "outcome": outcome,
            "viewing_start": window["start"] if booked else None,
            "answers": [{"question": question, "answer": "SYNTHETIC answer, not from a real person."}
                        for question in context.get("unknowns") or []],
            "new_costs": [],
            "summary": ("SYNTHETIC: the demo realtor agreed to a viewing at the offered time." if booked
                        else "SYNTHETIC: the demo realtor could not offer a time inside the free windows."),
        }
        request = urllib.request.Request(url + "/api/result", json.dumps(result).encode("utf-8"),
                                         {"content-type": "application/json"})
        urllib.request.urlopen(request, timeout=5).read()
        return


def run_call(outcome):
    tmp = tempfile.mkdtemp(prefix="domovoy-demo-")
    secret = secrets.token_hex(16)
    fake_phone_server.SECRET = secret
    fake_phone_server.STATE.update(pending=None, results={}, seen_conversations=set())
    server = fake_phone_server.ThreadingHTTPServer(("127.0.0.1", 0), fake_phone_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % server.server_address[1]
    stop = threading.Event()
    saved_env = {name: os.environ.get(name) for name in ("DOMOVOY_CONFIG", "FAKE_NOTION_DB")}
    saved_state = call.STATE_DIR
    try:
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["backend"]["module"] = "tests/fake_notion_backend.py"
        cfg["phone"].update(url=url, secret=secret, env_file="", url_env="", secret_env="",
                            poll_seconds=0.2, timeout_seconds=20)
        cfg["call_context"].update(user_name="Demo Renter", realtor_name="Demo Realtor")
        config_path = os.path.join(tmp, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.environ["DOMOVOY_CONFIG"] = config_path
        os.environ["FAKE_NOTION_DB"] = os.path.join(tmp, "fake_notion.json")
        call.STATE_DIR = os.path.join(tmp, "state")
        fake_notion_backend.set_status(cfg, PAGE, "Interested")
        window = demo_window()
        threading.Thread(target=answer_the_phone, args=(url, outcome, window, stop), daemon=True).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = call.main(["run", "--windows", json.dumps([window])])
        page = fake_notion_backend._page(fake_notion_backend._load(), PAGE)
        return code, {
            "synthetic": True,
            "note": NOTE,
            "call": json.loads(out.getvalue()),
            "page": {"title": page["title"], "status": page["status"], "body": page["body"]},
        }
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        call.STATE_DIR = saved_state
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["call"])
    parser.add_argument("--outcome", choices=["booked", "not_booked"], default="booked",
                        help="what the made-up realtor answers")
    args = parser.parse_args(argv)
    code, result = run_call(args.outcome)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
