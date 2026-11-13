# PostHog

Owner: Danila. Spec: [docs/prd/posthog.md](../docs/prd/posthog.md). Status on 13 Nov 2026: the project exists, `ph.py` can send an event and read it back, and `loop.py` runs the rejection loop end to end on synthetic data. It has not run on the real shortlist yet.

## The project

| | |
| --- | --- |
| Account | Danila's personal PostHog account, organization `NotHomeless`. Not a work account |
| Plan | Free. No card on file. 1M events per month, 1 project |
| Region | EU Cloud |
| Project | `DOMOVOY`, id `348322`, timezone `Europe/Prague` |
| App host (queries, UI) | `https://eu.posthog.com` |
| Ingest host (capture) | `https://eu.i.posthog.com` |

## Keys

Nothing below is committed. All five live in `~/.config/domovoy/.env`, the one env file every DOMOVOY script reads. Names match the root [`.env.example`](../.env.example).

| Variable | What | Secret? | Where it goes |
| --- | --- | --- | --- |
| `POSTHOG_PROJECT_TOKEN` | `phc_...`, write-only capture token | No, public by design | Env file, and Vercel if the phone page sends events |
| `POSTHOG_INGEST_HOST` | `https://eu.i.posthog.com` | No | Env file, Vercel |
| `POSTHOG_PERSONAL_API_KEY` | `phx_...`, reads data as Danila | Yes | Env file on the laptop only. Never Vercel, never the browser, never the Actor |
| `POSTHOG_PROJECT_ID` | `348322` | No | Env file |
| `POSTHOG_APP_HOST` | `https://eu.posthog.com`, for queries and the UI | No | Env file |

The phone page needs only `POSTHOG_PROJECT_TOKEN` and `POSTHOG_INGEST_HOST`. The Apify Actor, if it ever sends events (phase 2), also needs only those two.

## Use the same project (Vladimir)

1. Ask Danila for the project token and the personal key. He sends them outside the repo.
2. Append to `~/.config/domovoy/.env`:

   ```
   POSTHOG_PROJECT_TOKEN=phc_...
   POSTHOG_INGEST_HOST=https://eu.i.posthog.com
   POSTHOG_APP_HOST=https://eu.posthog.com
   POSTHOG_PROJECT_ID=348322
   POSTHOG_PERSONAL_API_KEY=phx_...
   ```

3. Check it: `python3 posthog/ph.py smoke`. Expected output: `capture: HTTP 200, marker ...` and then `read back after NN s: {...}`.

Sending events needs only the token. Skip the personal key if you never query.

## The self-improvement loop (free plan)

PostHog's own scouts and Inbox are paid (0 free credits; a scout run returned 429 and filing a report returned 402 on 13 Nov 2026). `loop.py` runs the same loop on the free parts. Do not claim the native Inbox on stage.

| Step | What happens | PostHog feature |
| --- | --- | --- |
| Signals | `loop.py sync` reads the Notion shortlist and sends `listing_shortlisted`, `listing_rejected` (with the typed `Reason`) and `listing_interested`, each once | Events |
| Instructions | `loop.py report` returns today's rejections, earlier decisions, and the scout instructions `domovoy-rejections` | HogQL query API, skills store |
| Judgement | Claude normalizes the free-text reasons to a short key and groups them. One undecided key on 3 or more flats makes a proposal | none, this is the agent |
| Report | `loop.py propose` creates an inactive flag `domovoy-criteria-<key>` whose payload holds the change, and a notebook with the finding, a live evidence query, the flag editor and the measurement chart | Feature flags, notebooks |
| Yes or no | `loop.py decide --key K --yes` switches the flag on, moves Shortlisted flats that now fail to Not interested with `Reason = filtered: ...`, and adds a chart annotation. `--no` only records the answer | Feature flags, annotations |
| Memory | Every decision is appended to the scout instructions as a new version, and sent as `criteria_change_decided`. A decided key is refused the second time | Skills store, events |
| Measure | Every event carries `criteria_version` and `$feature/<flag>`. The saved chart "DOMOVOY: shown, rejected and interested flats by criteria version" splits by it | Insights |
| Next search | `loop.py overrides` prints the approved requirements for `search.py` to merge into the profile | Feature flags |

```
python3 posthog/loop.py sync
python3 posthog/loop.py report
python3 posthog/loop.py propose --key no_elevator --title "3 of 5 rejected flats: no elevator" \
    --finding "..." --change '{"elevator": "required"}' --ids id1,id2,id3
python3 posthog/loop.py decide --key no_elevator --yes
```

- Supported changes: `{"elevator": "required"}`, `{"max_total_monthly": N}`, `{"max_upfront": N}`. An unknown value never fails a flat.
- `loop.py` reads the skill's `config.json` the way `call.py` does: the file named by `DOMOVOY_CONFIG`, else `skill/domovoy/config.json` in this checkout. It takes the renter's name from it.
- The shortlist is the Notion data source named by `NOTION_DATA_SOURCE_ID`, else a `data_source_id` in that config, else the one titled "DOMOVOY shortlist". It reads `Property ID`, `Status`, `Reason`, `Elevator`, `Floor`, `Total monthly`, `Upfront`, `Sources` and writes only `Status` and `Reason`.
- `--dataset NAME` before the command runs a test: events carry `synthetic: true` and flags are named `domovoy-test-NAME-...`, so a test never changes live criteria. `DOMOVOY_FAKE_SHORTLIST=posthog/tests/fake_shortlist_seed.json` (use a copy) replaces Notion with a file.
- PostHog needs 30 to 100 s to show new events to queries. `report` waits for every event `sync` sent (at most 150 s) and prints `"complete": false` if they are not all there. `propose` and `decide` do not wait.
- `scout/rejection-scout.md` is the source of the instructions stored in PostHog. A paused paid scout with the same instructions exists in the project; it is not used.

### Run and seen on 13 Nov 2026 (synthetic data only)

- Stage timing on the Notion test database, events already ingested: `report` 3.3 s, `propose` 6.9 s, `decide` 3.6 s. `sync` 3.3 s, run beforehand.

- Fake shortlist: `sync` sent 15 events, a second `sync` sent 0. `report` read back 5 rejections. `propose` with 2 flats was refused. `propose` with 3 created the flag and the notebook. `decide --no` recorded the answer, and proposing the same key again was refused.
- Notion test database with 9 synthetic flats: `decide --yes` took 4 s, moved the one Shortlisted flat without an elevator to Not interested with `Reason = filtered: elevator required`, and published version 4 of the instructions.
- Not run: the real "DOMOVOY shortlist" database (it did not exist yet), and nobody has looked at the notebook or the chart in a browser.

## Calls as traces: calls.py

Reads finished calls from the ElevenLabs API and sends them to PostHog. No code in `phone/` or the skill changes.

```
python3 posthog/calls.py prompt    # after every voice prompt deploy: store it as a version of `domovoy-voice-agent`
python3 posthog/calls.py sync      # every finished call not sent before
python3 posthog/calls.py report    # per prompt version: calls, booked, unknowns asked and answered
```

- Each call becomes one `$ai_trace`, one `$ai_generation` per agent turn (model, tokens, cost, latency from ElevenLabs) and one `call_finished` event. They appear under AI observability in PostHog.
- The score is deterministic: how many of the call's `unknowns` have an answer in `submit_call_result`. `call_finished` carries `unknowns_total`, `unknowns_answered`, `all_unknowns_answered`, `outcome`, `prompt_version`.
- `prompt_version` is set when the call's ElevenLabs agent version was recorded by `calls.py prompt`. Earlier calls show as `untracked`.
- Calls shorter than 20 s are skipped as test dials (`--min-seconds`).
- Needs `ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID` in the env file. It only reads from ElevenLabs.
- Not built: proposing a prompt change from these scores. Today the report only shows the numbers.

## ph.py

Standard library only, runs on Python 3.9. The PostHog Python SDK needs 3.10, so it is not used.

```
python3 posthog/ph.py capture listing_rejected --id Vladimir --props '{"property_id": "x", "reason": "no elevator"}'
python3 posthog/ph.py query "select event, count() from events group by event"
python3 posthog/ph.py smoke
```

From Python: `from ph import capture, query, api, flags, mcp`. `capture(event, distinct_id, properties)` posts to `/i/v0/e/`. `query(hogql)` posts a `HogQLQuery` to `/api/projects/348322/query/` and returns a list of dicts.

## What was run and seen (13 Nov 2026)

- `ph.py capture`: HTTP 200.
- `ph.py smoke`: the event came back through the query API 63 s after capture in one run and 26 s in another. An earlier run had not returned it after 90 s; that run reused a cached query result, so `query()` now sends `"refresh": "force_blocking"`.
- Plan for up to 100 s between sending an event and reading it. Send the demo events before the PostHog minute on stage, not during it.

## Rules

- Events carry `property_id`, never realtor names, phones or emails.
- Test or seeded events carry `"synthetic": true`. The `domovoy_smoke_test` events in the project are synthetic.
- PostHog holds telemetry only. State lives in the Notion `Status`.
