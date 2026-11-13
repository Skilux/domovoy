# DOMOVOY Actor (apify/)

The Actor turns a search profile into flats. It collects listings from the three portals (Sreality, Bezrealitky, iDNES), merges them across portals, extracts fees, computes costs, checks requirements, and writes the result to the dataset and, when configured, to the Notion shortlist.

## Stages on main

| Stage | Package | State on main |
| --- | --- | --- |
| Sources | `domovoy/sources/` | Sreality (WP1), Bezrealitky (WP2) and iDNES (WP3) are registered. |
| Dedup and profile state | `domovoy/dedup/` | Live (WP6). Property ids and profile state live in the named stores `domovoy-property-ids` and `domovoy-profile-state`. |
| Costs and requirements | `domovoy/costs/` | Live (WP5). Without extraction, most costs are unknown and most flats are `needs_info`. |
| Notion sink | `domovoy/notion/` | Live (WP7). Runs only when `notion.dataSourceId` is set. |
| Extraction | `domovoy/extraction/` | Live (WP4). Needs a Featherless or OpenAI key; without one, every field is unknown and `extraction` is null. |

The stages are imported directly from their merged packages; there is no fallback in production. A failing stage inside one flat is counted, not fatal.

## Extraction chain (WP4)

For each listing, in order:

1. The cache (`domovoy-extraction-cache`, keyed by listing text, model and prompt version).
2. Featherless, the primary model `llm.model` (Qwen), two attempts, within the per-flat budget.
3. OpenAI, the fallback model `llm.fallbackModel` (`gpt-6-luna` at reasoning effort medium), one attempt. It is the only fallback and runs only when an OpenAI key is set.

An answer whose confidence is below 0.5 becomes unknown. `llm.concurrency` is the number of Featherless concurrent units the run may hold, 40 by default (the plan allows 100): a Qwen call takes 1; OpenAI calls take none and have their own limit of 8. A 429 is waited out with backoff. Each Qwen attempt times out after `llm.timeoutSec` (20 s); the fallback gets at least 30 s. Each flat has `llm.flatBudgetSec` (45 s) of Qwen request time; waiting for a slot does not count. When a flat has no answer and the chain ran out of time, it goes on with extraction `status` `timeout`, every field unknown and "fees not extracted yet" in its unknowns. Nothing is cached for it, and its profile state is recorded as pending, so the next Notion run extracts it again and delivers it as `changed`. Every failed attempt is logged with its reason class (for example `truncated` or `schema:kauce.value.rent_multiple`), never the content. See `research/featherless.md`. The extractor is opened in `__main__` inside the Actor run and closed after it.

## Run order

1. Validate the profile. With `notion.dataSourceId` set, the Notion schema is checked before any portal is contacted.
2. Collect every source in `filters.sources` at the same time; each keeps its own pacing, and their results keep the profile's order. A source that raises is `failed`. A source whose stats report failed or skipped items is `degraded`.
3. Merge listings into flats across portals (dedup).
4. Every flat then runs as its own task, as soon as its extraction is done: extract (skipped when `skipExtraction` is set) and cost, set `cross_source` from its commissions, diff against the profile state, evaluate, build the FlatItem and push it to the dataset. Unchanged flats are extracted too, because `cross_source` needs their commissions before diff; the cache makes that cheap. The tasks share the extraction slot limit and the Notion sink's throttle (3 requests per second in total), so dataset items arrive in completion order. Flats whose property ID is in `priorityPropertyIds` (for example a demo flat) run first, on their own: their Notion upsert completes before any other flat starts. An ID that is not found or is rejected changes nothing else.
5. In the same task, upsert `new` and `changed` flats that are not `rejected` to Notion, and with `includeUnchanged` the unchanged ones too. A failed upsert is counted in `notion.errors`. An unexpected error in one flat is logged by its class, counted in the `run done` log line and leaves that flat out of the profile state, so the next run retries it; the other flats go on.
6. Save the property-id map when every Notion write of the run succeeded. Save the profile state too only when the run has a Notion sink: a dataset-only run saves no state, so a later Notion run still delivers every flat. The state stores a hash of the profile; a changed profile re-evaluates every flat, which counts as `changed`. A failed write is never recorded as seen, so the next run retries it.
7. Write the `RunSummary` to the key `OUTPUT`. The Notion sink is closed at the end of the run, also when the run fails.

## Flat fields worth knowing

- `match`: `strong`, `needs_info` or `rejected`. Any failed requirement makes a flat `rejected`; rejected flats go to the dataset only.
- Risk flag `cheaper on another portal`: added when `cross_source.cheapest_portal` is a different portal from the primary listing.
- `change`: `new`, `changed` or `unchanged`. Unchanged flats reach the dataset and Notion only with `includeUnchanged`.
- `rejected_by_requirement` (run summary): counts every failed requirement of each rejected flat, so one flat can count under several requirements.
- `extraction`: null when extraction did not run (skipped, stage missing, or the run skipped it). When every model fails, it is an object with `status` `failed` and no provider; when the flat's budget ran out, `status` `timeout`.

## Secrets

`notionToken`, `featherlessApiKey` and `openaiApiKey` are secret inputs. Each falls back to the environment variable `NOTION_TOKEN`, `FEATHERLESS_API_KEY` or `OPENAI_API_KEY`. On the platform those come from the Apify secrets of the same names, via `environmentVariables` in `.actor/actor.json`. Locally, the extraction stage also falls back to `/Users/vladimir/.config/domovoy/.env` by design. Nothing is logged; the run log only says whether each key is set.

## Public Store Actor

The same code is also pushed as a public Actor, `vladb/prague-flat-rentals`, with `./push_public.sh`. The script pushes a temporary copy whose only environment variable is `DOMOVOY_STORE_SUFFIX=-public`, so the public Actor carries none of our keys (users pass their own `featherlessApiKey`, `openaiApiKey` and `notionToken`) and has its own named stores (`domovoy-*-public`); a limited-permission Actor may not open the stores the demo Actor created in the same account. Never push the public Actor with plain `apify push`, and never add environment variables to it in the Console. Its Store page is `.actor/README.md`; this file stays the developer notes. The Store tests every public Actor daily with the input schema's `prefill`, and expects a succeeded run with a non-empty dataset within 5 minutes.

## Run the tests (offline)

    cd apify
    .venv/bin/python -m pytest -q -m "not live"

Live tests (`-m live`) call the portals and are run per source.

## Run the Actor locally

Write the input to a JSON file (a `profile`, `skipExtraction` for debugging, and an optional `notion` block), then from `apify/`:

    apify run --input-file <input.json> --user-agent apify-agent-skills/apify-actor-development

The summary is the key `OUTPUT` in `storage/key_value_stores/default/` (a JSON file named `OUTPUT`, with a metadata file beside it). Each dataset item is one file in `storage/datasets/default/`. The named stores `domovoy-property-ids` and `domovoy-profile-state` persist between local runs. A run with a Notion data source updates the profile state; a dataset-only run does not, so a second dataset-only run reports the same flats as new.

## Inputs and outputs

- `.actor/input_schema.json` is the source of truth. Required: `profile`, which follows `domovoy/schemas/profile.schema.json`.
- `OUTPUT` (default key-value store): a `RunSummary`, or `{"status": "NOT_IMPLEMENTED"}` for `katastr_lookup`.
- Default dataset: one `FlatItem` per emitted flat.

## Not done yet

The dataset schema in `.actor/dataset_schema.json` is still an empty placeholder. Phase 2: `katastr_lookup` and the PostHog events.

## Fixtures

`tests/fixtures/texts/`: five real Sreality texts (WP0). `tests/fixtures/sreality/`, `tests/fixtures/bezrealitky/` and `tests/fixtures/idnes/`: portal payloads (WP1 to WP3). See the README in each folder for their source and scrubbing.
