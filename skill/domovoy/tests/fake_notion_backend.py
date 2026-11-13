#!/usr/bin/env python3
"""FAKE Notion backend for call.py, for local tests only. It never talks to Notion or the network.

Pages live in one JSON file: $FAKE_NOTION_DB, else .state/fake_notion.json next to config.json,
created from tests/fake_notion_seed.json on first use. It offers the three functions of the
shortlist interface described in scripts/call.py: list_pages, set_status, append.

By hand:  fake_notion_backend.py show | reset | move PAGE_ID STATUS
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _path():
    return os.environ.get("FAKE_NOTION_DB") or os.path.join(HERE, "..", ".state", "fake_notion.json")


def _load():
    if not os.path.exists(_path()):
        os.makedirs(os.path.dirname(os.path.abspath(_path())), exist_ok=True)
        shutil.copy(os.path.join(HERE, "fake_notion_seed.json"), _path())
    with open(_path()) as f:
        return json.load(f)


def _save(db):
    with open(_path(), "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _page(db, notion_page_id):
    page = next((p for p in db["pages"] if p["notion_page_id"] == notion_page_id), None)
    if page is None:
        raise RuntimeError("fake Notion has no page %s" % notion_page_id)
    return page


def list_pages(cfg, status):
    return [{k: p[k] for k in ("notion_page_id", "title", "url", "listing")}
            for p in _load()["pages"] if p["status"] == status]


def set_status(cfg, notion_page_id, status):
    db = _load()
    _page(db, notion_page_id)["status"] = status
    _save(db)


def append(cfg, notion_page_id, text):
    db = _load()
    page = _page(db, notion_page_id)
    page["body"] = (page["body"] + "\n\n" + text).strip()
    _save(db)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["reset"]:
        if os.path.exists(_path()):
            os.remove(_path())
        _load()
    elif len(args) == 3 and args[0] == "move":
        set_status(None, args[1], args[2])
    elif args != ["show"]:
        raise SystemExit("usage: fake_notion_backend.py show | reset | move PAGE_ID STATUS")
    for p in _load()["pages"]:
        print("FAKE %s [%s] %s\n%s" % (p["notion_page_id"], p["status"], p["title"], p["body"]))
