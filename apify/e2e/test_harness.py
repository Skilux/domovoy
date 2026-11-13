"""Offline tests of the harness safety rails (e2e review, fix round 1). No network, no real config, counter or Notion.

Run: cd apify && .venv/bin/python -m pytest -q --rootdir=e2e e2e/test_harness.py
"""

import argparse
import json
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import checks
import run_e2e

SECRET = "SECRETMARKER-0123456789abcdef"
NAME = "Zdenka Markerova-Testova"
E2E_DS = "11111111-2222-3333-4444-555555555555"
E2E_DB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def title(text):
    return [{"plain_text": text}]


@pytest.fixture(autouse=True)
def clean_registry():
    checks.clear_sensitive()
    yield
    checks.clear_sensitive()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A round set up in tmp_path: env file with a secret marker, an e2e config, empty reports and data folders."""
    monkeypatch.setattr(run_e2e, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(run_e2e, "DATA", tmp_path / "data")
    env_file = tmp_path / "env"
    env_file.write_text("FEATHERLESS_API_KEY=%s\nNOTION_TOKEN=secret_notion_marker_123\n" % SECRET)
    monkeypatch.setattr(run_e2e, "ENV_FILE", env_file)
    profile = json.loads((run_e2e.HERE / "profile_e2e.json").read_text())
    config = tmp_path / "config.e2e.json"
    config.write_text(json.dumps({"notion": {"data_source_id": E2E_DS, "database_id": E2E_DB},
                                  "active_profile": profile["id"], "profiles": [profile]}))

    def make(**kw):
        values = dict(round="t", only=None, layers=None, config=str(config), offline_items=None, offline_summary=None)
        values.update(kw)
        return argparse.Namespace(**values)

    make.config = config
    make.tmp = tmp_path
    return make


class FakeNotion:
    ds = E2E_DS

    def guard(self, expected):
        pass


# 1. Sanitize before writing


def test_child_output_is_kept_raw_privately_and_published_sanitized(tmp_path):
    checks.register_secret(SECRET)
    checks.register_contact(NAME)
    checks.register_contact(" ".join(["+420", "777", "000", "111"]))  # built at run time: no phone in this file
    raw = tmp_path / "raw.log"
    code, _ = run_e2e.run_logged([sys.executable, "-c", "print(%r); print(%r); print('call 777000111')" % (SECRET, NAME)],
                                 raw, cwd=tmp_path, env={}, timeout=30)
    assert code == 0 and SECRET in raw.read_text()
    dest = tmp_path / "report.log"
    run_e2e.publish(raw, dest)
    text = dest.read_text()
    assert SECRET not in text and NAME not in text and "777000111" not in text
    assert "<secret>" in text and "<contact>" in text


def test_findings_notes_and_report_are_sanitized(harness):
    rnd = run_e2e.Round(harness())
    assert SECRET in checks.known_secrets()
    rnd.collect_contacts([{"sources": [{"contact": {"name": NAME, "email": None, "phone": None}}]}])
    f = checks.finding("L1.exit_zero", "blocker", "child said %s" % NAME, "apify/domovoy/main.py", "repro",
                       excerpt="token %s" % SECRET)
    assert NAME not in json.dumps(f) and SECRET not in json.dumps(f)
    rnd.findings.append({"check_id": "X.raw", "severity": "major", "summary": NAME, "owner_wp": "WP8",
                         "suspected_path": "p", "repro": SECRET,
                         "evidence": {"run_id": None, "property_id": None, "notion_page_id": None, "log_excerpt": NAME}})
    rnd.notes.append("error mentioning %s and %s" % (NAME, SECRET))
    (rnd.reports / "late.log").write_text("written before the contact was known: %s" % NAME)
    rnd.write_report(run_e2e.dt.datetime.now(run_e2e.PRAGUE))
    for f in rnd.reports.iterdir():
        assert NAME not in f.read_text() and SECRET not in f.read_text(), f.name


def test_pick_allowlists_child_output():
    assert json.loads(checks.pick({"status": "ok", "call_context": {"realtor_name": NAME}}, ("status",))) == {"status": "ok"}


# 2. Platform-run cap


def test_platform_cap_admits_exactly_one_of_two_concurrent_reservations(tmp_path):
    counter = tmp_path / "platform_runs.json"
    counter.write_text(json.dumps([{"id": "seed%d" % i, "run_id": "r%d" % i} for i in range(5)]))
    barrier, results = threading.Barrier(2), []

    def reserve(name):
        barrier.wait()
        try:
            results.append(run_e2e.reserve_platform_run(counter, name, "L2a", cap=6))
        except run_e2e.Refused:
            results.append(None)

    threads = [threading.Thread(target=reserve, args=(n,)) for n in ("A", "B")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    admitted = [r for r in results if r]
    assert len(admitted) == 1 and results.count(None) == 1
    entries = json.loads(counter.read_text())
    assert len(entries) == 6
    run_e2e.update_reservation(counter, admitted[0], "RUN-X")
    entries = json.loads(counter.read_text())
    assert [e["run_id"] for e in entries if e["id"] == admitted[0]] == ["RUN-X"]
    assert [e["run_id"] for e in entries[:5]] == ["r0", "r1", "r2", "r3", "r4"]


# 3. Guard


def test_guard_rejects_demo_titles_and_foreign_parents():
    e2e_source = {"title": title("DOMOVOY shortlist (e2e)"), "parent": {"database_id": E2E_DB}}
    e2e_db = {"id": E2E_DB, "title": title("DOMOVOY shortlist (e2e)")}
    demo_db = {"id": E2E_DB, "title": title("DOMOVOY shortlist")}
    run_e2e.check_target(E2E_DS, e2e_source, e2e_db, E2E_DB)  # the real e2e target passes
    refused = [
        (E2E_DS, e2e_source, demo_db, E2E_DB),  # mixed: e2e-titled source inside a demo-titled database
        (E2E_DS, dict(e2e_source, title=title("DOMOVOY shortlist")), e2e_db, E2E_DB),
        (E2E_DS, e2e_source, dict(e2e_db, id="ffffffff-0000-0000-0000-000000000000"), E2E_DB),
        (E2E_DS, {"title": title("DOMOVOY shortlist (e2e)")}, None, E2E_DB),  # no parent database
        (E2E_DS, e2e_source, e2e_db, None),  # no pinned database id
        (run_e2e.DEMO_DATA_SOURCE, e2e_source, e2e_db, E2E_DB),
    ]
    for args in refused:
        with pytest.raises(run_e2e.Refused):
            run_e2e.check_target(*args)


def test_mixed_target_never_reaches_a_write():
    calls = []

    class Mocked(run_e2e.Notion):
        def call(self, method, path, body=None, params=None):
            calls.append((method, path))
            if path.startswith("/data_sources/"):
                return {"title": title("DOMOVOY shortlist (e2e)"), "parent": {"database_id": E2E_DB}, "properties": {}}
            if path.startswith("/databases/"):
                return {"id": E2E_DB, "title": title("DOMOVOY shortlist")}
            return {"parent": {"data_source_id": E2E_DS}}

    n = Mocked("token", E2E_DS, "2026-03-11")
    with pytest.raises(run_e2e.Refused):
        n.guard(E2E_DB)
    with pytest.raises(run_e2e.Refused):
        n.write_page("page", {"Interested?": {"select": {"name": "Yes"}}})
    assert not [c for c in calls if c[0] == "PATCH"]


# 4. Config snapshot


def test_config_snapshot_is_private_and_detects_edits(harness):
    snap = run_e2e.ConfigSnapshot(harness.config, harness.tmp)
    assert stat.S_IMODE(snap.path.stat().st_mode) == 0o600
    snap.verify(E2E_DS)
    cfg = json.loads(harness.config.read_text())
    cfg["notion"]["data_source_id"] = run_e2e.DEMO_DATA_SOURCE
    harness.config.write_text(json.dumps(cfg))
    with pytest.raises(run_e2e.Refused):
        snap.verify(E2E_DS)
    snap.close()
    assert not snap.path.exists()


def test_config_edited_mid_round_refuses_the_platform_launch(harness, monkeypatch):
    rnd = run_e2e.Round(harness())
    rnd.notion = FakeNotion()
    launched = []
    monkeypatch.setattr(run_e2e.subprocess, "run", lambda *a, **k: launched.append(a) or subprocess.CompletedProcess(a, 0))
    cfg = json.loads(harness.config.read_text())
    cfg["notion"]["data_source_id"] = run_e2e.DEMO_DATA_SOURCE
    harness.config.write_text(json.dumps(cfg))
    with pytest.raises(run_e2e.Refused):
        rnd.platform_run("L2a", include_unchanged=True)
    assert launched == [] and not rnd.counter.exists()  # nothing launched, nothing reserved
    rnd.config.close()


# Notes: offline mode, incomplete rounds


def test_offline_items_never_refetch(harness, monkeypatch):
    fixture = Path(checks.__file__).resolve().parents[1] / "tests" / "fixtures" / "flatitem_example.json"
    items = harness.tmp / "items.json"
    items.write_text(json.dumps([json.loads(fixture.read_text())]))

    def boom(item):
        raise AssertionError("refetch_texts called in offline mode")

    monkeypatch.setattr(run_e2e, "refetch_texts", boom)
    code = run_e2e.main(["--round", "off", "--layers", "L3", "--offline-items", str(items), "--config", str(harness.config)])
    report = (run_e2e.REPORTS / "off" / "report.md").read_text()
    assert code in (0, 1) and "`L3.quotes_verified` | skipped: offline" in report


def test_round_without_candidates_is_incomplete_not_green(harness):
    rnd = run_e2e.Round(harness())
    rnd.launch_check = lambda: FakeNotion()
    rnd.snapshot = lambda **kw: []
    rnd.l4()
    rnd.l5()
    assert rnd.status().startswith("INCOMPLETE")
    rnd.config.close()


# Round-1 harness bugs


def test_quotes_are_checked_against_every_source_of_the_flat(monkeypatch):
    """A flat whose quotes come from two portals (the composite primary takes price_note from iDNES) passes."""
    pages = {"https://bezrealitky.example/936": "<html><body>Pets allowed. Furnished.</body></html>",
             "https://idnes.example/6af": "<html><body>Kauce 40 000 Kč, provize RK.</body></html>"}

    class Reply:
        def __init__(self, text):
            self.status_code, self.text = (200, text) if text else (404, "")

    monkeypatch.setattr(run_e2e, "REFETCH_GAP_SEC", 0)
    monkeypatch.setattr(run_e2e.httpx, "get", lambda url, **kw: Reply(pages.get(url)))
    item = {"property_id": "p-AAAAAAAAAA", "url": "https://bezrealitky.example/936",
            "sources": [{"portal": "bezrealitky", "source_id": "936", "url": "https://bezrealitky.example/936"},
                        {"portal": "idnes", "source_id": "6af", "url": "https://idnes.example/6af"}],
            "evidence": [{"field": "pets_allowed", "quote": "Pets allowed.", "confidence": 0.9},
                         {"field": "kauce", "quote": "Kauce 40 000 Kč", "confidence": 0.9}]}
    texts = run_e2e.refetch_texts(item)
    assert checks.check_quotes(item, texts, "r") == []
    assert [f["severity"] for f in checks.check_quotes(item, texts[:1], "r")] == ["major"]  # primary text alone
    item["sources"][1]["url"] = "https://idnes.example/gone"
    assert run_e2e.refetch_texts(item) is None  # one source missing: skipped, never a false finding


def test_status_is_never_green_with_a_major(harness):
    rnd = run_e2e.Round(harness())
    assert rnd.status() == "GREEN"
    rnd.findings.append({"severity": "minor"})
    assert rnd.status() == "GREEN"
    rnd.findings.append({"severity": "major"})
    assert rnd.status() == "MAJORS (1)"
    rnd.findings.append({"severity": "blocker"})
    assert rnd.status() == "BLOCKERS"
    rnd.config.close()
