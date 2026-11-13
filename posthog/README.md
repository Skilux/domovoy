# PostHog

Owner: Danila. Spec: [docs/prd/posthog.md](../docs/prd/posthog.md). Status on 13 Nov 2026: the project exists and `ph.py` can send an event and read it back. No DOMOVOY flow sends events yet.

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

## ph.py

Standard library only, runs on Python 3.9. The PostHog Python SDK needs 3.10, so it is not used.

```
python3 posthog/ph.py capture listing_rejected --id Vladimir --props '{"property_id": "x", "reason": "no elevator"}'
python3 posthog/ph.py query "select event, count() from events group by event"
python3 posthog/ph.py smoke
```

From Python: `from ph import capture, query`. `capture(event, distinct_id, properties)` posts to `/i/v0/e/`. `query(hogql)` posts a `HogQLQuery` to `/api/projects/348322/query/` and returns a list of dicts.

## What was run and seen (13 Nov 2026)

- `ph.py capture`: HTTP 200.
- `ph.py smoke`: the event came back through the query API 63 s after capture in one run and 26 s in another. An earlier run had not returned it after 90 s; that run reused a cached query result, so `query()` now sends `"refresh": "force_blocking"`.
- Plan for up to 100 s between sending an event and reading it. Send the demo events before the PostHog minute on stage, not during it.

## Rules

- Events carry `property_id`, never realtor names, phones or emails.
- Test or seeded events carry `"synthetic": true`. The `domovoy_smoke_test` events in the project are synthetic.
- PostHog holds telemetry only. State lives in the Notion `Status`.
