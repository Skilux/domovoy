#!/usr/bin/env python3
"""TEST backend for call.py. Not a DOMOVOY surface: the real shortlist is the Notion database.

It keeps flats as GitHub issues on a Projects board so the call flow can be run end to end
before notion.py lands. It implements the four functions call.py needs from a backend:
list_flats, get_flat, set_status, append. Names come from the "gh_test" block of config.json.
"""
import json
import re
import subprocess

def gh(args, stdin=None):
    p = subprocess.run(["gh"] + [str(a) for a in args], input=stdin, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(str(a) for a in args[:3]), p.stderr.strip()))
    return p.stdout


def _project(cfg):
    g = cfg["gh_test"]
    return [g["project_number"], "--owner", g["owner"], "--format", "json"]


def list_flats(cfg, status=None):
    g = cfg["gh_test"]
    key = g["status_field"].lower()
    items = json.loads(gh(["project", "item-list"] + _project(cfg) + ["--limit", "500"]))["items"]
    flats = []
    for item in items:
        content = item.get("content") or {}
        if content.get("type") != "Issue" or content.get("repository", "").lower() != g["repo"].lower():
            continue
        flat = {"id": str(content["number"]), "title": content.get("title") or item.get("title"),
                "url": content.get("url"), "status": item.get(key), "item_id": item["id"]}
        if status is None or flat["status"] == status:
            flats.append(flat)
    return flats


def get_flat(cfg, flat_id):
    issue = json.loads(gh(["issue", "view", flat_id, "--repo", cfg["gh_test"]["repo"],
                           "--json", "number,title,body,url,comments"]))
    listing = None
    for block in re.findall(r"```json\s*\n(.*?)```", issue["body"] or "", re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict):
            listing = data
            break
    text = "\n".join([issue["body"] or ""] + [c.get("body") or "" for c in issue["comments"]])
    return {"id": str(issue["number"]), "title": issue["title"], "url": issue["url"],
            "listing": listing, "text": text}


def set_status(cfg, flat_id, status):
    name = cfg["gh_test"]["status_field"]
    flat = next((f for f in list_flats(cfg) if f["id"] == str(flat_id)), None)
    if flat is None:
        raise RuntimeError("issue #%s is not on the test board" % flat_id)
    fields = json.loads(gh(["project", "field-list"] + _project(cfg)))["fields"]
    field = next((f for f in fields if f["name"] == name), None)
    if field is None:
        raise RuntimeError("test board has no field %r" % name)
    option = next((o for o in field.get("options", []) if o["name"] == status), None)
    if option is None:
        raise RuntimeError("field %r has no option %r" % (name, status))
    project_id = json.loads(gh(["project", "view"] + _project(cfg)))["id"]
    gh(["project", "item-edit", "--id", flat["item_id"], "--project-id", project_id,
        "--field-id", field["id"], "--single-select-option-id", option["id"]])
    return status


def append(cfg, flat_id, text):
    return gh(["issue", "comment", flat_id, "--repo", cfg["gh_test"]["repo"], "--body-file", "-"],
              stdin=text).strip()
