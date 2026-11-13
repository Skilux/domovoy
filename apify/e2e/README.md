# DOMOVOY e2e harness (issue #68)

End-to-end checks of the Actor half: profile → `search.py` → Apify run → dataset + `OUTPUT` → Notion pages →
`call.py` builds `call_context` from a page. The phone side stops at `skill/domovoy/tests/fake_phone_server.py`;
no real call happens. The tester owns this folder and nothing else: a failing check is a finding, never a product fix.

## Run

    apify/.venv/bin/python apify/e2e/run_e2e.py --round 1                 # L0-L6, unattended
    apify/.venv/bin/python apify/e2e/run_e2e.py --round 1 --only L3.money_int   # one check again
    apify/.venv/bin/python apify/e2e/run_e2e.py --round dry --layers L0,L3,L6 \
        --offline-items items.json --offline-summary summary.json          # offline, recorded dataset, no portal requests

Exit 0: green (or a passing partial run). 1: at least one blocker. 2: refused (safety guard). 3: harness error.
4: incomplete, e.g. L4 or L5 found no candidate pages; an incomplete round is never green. A report with a
**Status** line is written in every case: BLOCKERS, INCOMPLETE, MAJORS (n) or GREEN (no blocker and no major).

`--only` takes check ids or layers. L3 checks reuse the round's recorded datasets from L1/L2; L4 always makes a new
platform run. Offline tests of the checks and the safety rails: `cd apify && .venv/bin/python -m pytest -q --rootdir=e2e e2e/`.

## Isolation and safety

- Config: `DOMOVOY_CONFIG`, default `~/.config/domovoy/config.e2e.json`, with `notion.data_source_id` and
  `notion.database_id` (the e2e database). Writes are enabled only when the data source's parent database is that id
  and is titled **DOMOVOY shortlist (e2e)**; the demo data source id and the title "DOMOVOY shortlist" on either the
  data source or its parent are refused. Every page write also checks that the page sits in the e2e data source.
- The config is frozen at round start into a private snapshot (0600) in the round's data folder. `search.py` and
  `call.py` get only the snapshot path, and every launch (apify run, search.py, call.py) re-checks that neither file
  changed and that Notion still says e2e; otherwise the launch is refused.
- Profile: `profile_e2e.json`, id `e2e-vinohrady`, `max_listings` 5 (the cap applies per portal). The config's active
  profile must equal this file.
- Platform runs (L2 and L4) are reserved in `~/.config/domovoy/e2e-reports/platform_runs.json` under an `flock`, with
  an atomic write, before the launch; the 7th reservation is refused. Each reservation has an id, and the run id is
  filled in by that id.
- Secrets are read from `/Users/vladimir/.config/domovoy/.env` into child processes only, never printed.
- Child output, run logs, datasets and page snapshots are written raw only to `~/.config/domovoy/e2e-data/<round>/`
  (0700). Everything in `~/.config/domovoy/e2e-reports/<round>/` (logs, `report.md`, `findings.json`) goes through
  one sanitizer first: exact secret values from the env file, exact contact names, emails and phones seen in any
  round's datasets or pages, then email and phone patterns. Evidence from child JSON output is allowlisted keys only.
- Heavy jobs (`apify run`, `search.py run`) go through the orchestration `heavy.sh` slots.

## Layers and checks

| Layer | Runs | Check ids |
| --- | --- | --- |
| L0 | `pytest -m "not live"` in `apify/`, `unittest discover` in `skill/domovoy/` | `L0.apify_pytest`, `L0.skill_unittest` |
| L1 | local `apify run`, e2e Notion target, `includeUnchanged` | `L1.exit_zero`, `L1.summary_valid`, `L1.sources_ok`, `L1.time_budget` (600 s), `L1.notion_errors` |
| L2 | `search.py run --include-unchanged` with the e2e config (platform run 1 of the round) | `L2.run_succeeded`, `L2.summary_readable`, `L2.summary_valid`, `L2.sources_ok`, `L2.time_budget`, `L2.notion_errors` |
| L3 | L1 + L2 datasets, the e2e database | `L3.dataset_schema`, `L3.flatitem_schema`, `L3.money_int`, `L3.time_offset`, `L3.url_collected`, `L3.quotes_verified` (re-fetches every source of up to 15 flats, 1.5 s apart: the extracted text is the merged primary, whose missing fields come from the other portals; a flat with an unreachable source is skipped), `L3.dedup_missed`, `L3.one_page_per_property`, `L3.new_page_shortlisted`, `L3.page_body`, `L3.item_has_page`, `L3.page_matches_item`, `L3.summary_counts`, `L3.body_no_contacts` |
| L4 | edit one page (Status Not interested, Reason, a body marker), then `search.py run` again (platform run 2) | `L2b.run_succeeded`, `L4.no_new_pages`, `L4.unchanged_reported`, `L4.edits_kept`, `L4.property_ids_stable` |
| L5 | two Shortlisted pages: one set to Status Interested, one to Interested? = Yes; `call.py check`, then `call.py run` against the fake phone server with a synthetic `not_booked` result | `L5.context_schema`, `L5.context_matches_page`, `L5.budget_cap`, `L5.interested_trigger`, `L5.fake_phone_run` |
| L6 | the round's reports and logs, `git diff origin/main`, test fixtures | `L6.no_secrets`, `L6.no_contacts_reports`, `L6.no_contacts_repo`, `L6.fixture_scrub` |

`call.py` runs from a copy of `skill/domovoy/` in the round's data folder, so its `.state/` never touches the repo.
After contract2, money checks read `move_in_cost` and the Notion "Move-in cost" property; before it, `upfront` and
"Upfront". `call_context.upfront` is compared with whichever the page has.

## Findings

`findings.json` holds one object per finding, in the issue #68 format: `id`, `check_id`, `layer`, `severity`
(blocker, major, minor), `summary`, `evidence` (`run_id`, `property_id`, `notion_page_id`, `log_excerpt` with
contacts scrubbed), `suspected_path`, `owner_wp` (from the path: sources WP1-3, extraction WP4, costs WP5, dedup WP6,
notion and `notion.py` WP7, the rest of `apify/` and `search.py` WP8, `call.py` and `phone/` Danila) and `repro`.
