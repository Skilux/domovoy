"""FAKE Notion backend, shape B of the shortlist interface in scripts/call.py. Local tests only.

Same JSON file as fake_notion_backend.py, offered under the other set of names:
list_flats, get_flat, set_status, append, set_viewing_date.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_notion_backend as fake  # noqa: E402

set_status = fake.set_status
append = fake.append


def list_flats(cfg, status=None):
    return [{"id": p["notion_page_id"], "title": p["title"], "url": p["url"], "status": p["status"],
             "interested": p.get("interested")}
            for p in fake._load()["pages"] if status is None or p["status"] == status]


def get_flat(cfg, flat_id):
    p = fake._page(fake._load(), flat_id)
    return {"id": p["notion_page_id"], "title": p["title"], "url": p["url"], "listing": p["listing"],
            "text": p["body"]}


def set_viewing_date(cfg, flat_id, start):
    db = fake._load()
    fake._page(db, flat_id)["viewing_date"] = start
    fake._save(db)
