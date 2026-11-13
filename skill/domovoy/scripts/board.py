#!/usr/bin/env python3
"""DOMOVOY board access for the call command: list cards by Status, set Status, comment.

Thin wrappers over gh. Names of the repo, board, field and statuses come from config.json.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    path = path or os.environ.get("DOMOVOY_CONFIG") or os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        raise SystemExit("config not found: %s (copy config.example.json to config.json)" % path)
    with open(path) as f:
        return json.load(f)


def gh(args, stdin=None):
    p = subprocess.run(["gh"] + [str(a) for a in args], input=stdin, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(str(a) for a in args[:3]), p.stderr.strip()))
    return p.stdout


def _project(cfg):
    g = cfg["github"]
    return [g["project_number"], "--owner", g["owner"], "--format", "json"]


def list_cards(cfg, status=None):
    g = cfg["github"]
    key = cfg["board"]["status_field"].lower()
    items = json.loads(gh(["project", "item-list"] + _project(cfg) + ["--limit", "500"]))["items"]
    cards = []
    for item in items:
        content = item.get("content") or {}
        if content.get("type") != "Issue" or content.get("repository", "").lower() != g["repo"].lower():
            continue
        card = {
            "item_id": item["id"],
            "issue_number": content["number"],
            "title": content.get("title") or item.get("title"),
            "url": content.get("url"),
            "status": item.get(key),
        }
        if status is None or card["status"] == status:
            cards.append(card)
    return cards


def set_status(cfg, issue_number, status):
    name = cfg["board"]["status_field"]
    card = next((c for c in list_cards(cfg) if c["issue_number"] == int(issue_number)), None)
    if card is None:
        raise RuntimeError("issue #%s is not on the board" % issue_number)
    fields = json.loads(gh(["project", "field-list"] + _project(cfg)))["fields"]
    field = next((f for f in fields if f["name"] == name), None)
    if field is None:
        raise RuntimeError("board has no field %r" % name)
    option = next((o for o in field.get("options", []) if o["name"] == status), None)
    if option is None:
        raise RuntimeError("field %r has no option %r" % (name, status))
    project_id = json.loads(gh(["project", "view"] + _project(cfg)))["id"]
    gh(["project", "item-edit", "--id", card["item_id"], "--project-id", project_id,
        "--field-id", field["id"], "--single-select-option-id", option["id"]])
    return status


def get_issue(cfg, issue_number):
    return json.loads(gh(["issue", "view", issue_number, "--repo", cfg["github"]["repo"],
                          "--json", "number,title,body,url,comments"]))


def comment(cfg, issue_number, body):
    return gh(["issue", "comment", issue_number, "--repo", cfg["github"]["repo"], "--body-file", "-"],
              stdin=body).strip()


def main(argv):
    cfg = load_config()
    if len(argv) >= 1 and argv[0] == "list":
        print(json.dumps(list_cards(cfg, argv[1] if len(argv) > 1 else None), indent=2))
    elif len(argv) == 3 and argv[0] == "set-status":
        print(set_status(cfg, argv[1], argv[2]))
    elif len(argv) == 3 and argv[0] == "comment":
        print(comment(cfg, argv[1], argv[2]))
    else:
        raise SystemExit("usage: board.py list [STATUS] | set-status ISSUE STATUS | comment ISSUE TEXT")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except RuntimeError as e:
        raise SystemExit("error: %s" % e)
