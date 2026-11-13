# DOMOVOY Actor (apify/)

The Actor turns a search profile into flats. It collects listings from the portals, merges them across portals, extracts fees, computes costs, checks requirements, and writes the result to the dataset and, when configured, to the Notion shortlist.

## Stages on main

| Stage | Package | State on main |
| --- | --- | --- |
| Sources | `domovoy/sources/` | Sreality is registered (WP1). Bezrealitky (WP2) and iDNES (WP3) register from `sources/__init__.py` when they merge. |
| Dedup and profile state | `domovoy/dedup/` | Not on main yet. Fallback: one flat per listing, all new, no state is read or written. |
| Extraction | `domovoy/extraction/` | Not on main yet. Fallback: every field unknown, `extraction` is null. |
| Costs and requirements | `domovoy/costs/` | Not on main yet. Fallback: no totals, `match` is `needs_info`. |
| Notion sink | `domovoy/notion/` | Not on main yet. Fallback: dataset only. |

Each stage is imported when a run starts. A stage that is not importable is replaced by its fallback, and the run log names every fallback in use. A failing stage inside one flat is counted, not fatal.

## Run order

1. Validate the profile. With `notion.dataSourceId` set, the Notion schema is checked before any portal is contacted.
2. Collect each source in `filters.sources`, one at a time. A source that raises is `failed`. A source whose stats report failed or skipped items is `degraded`.
3. Merge listings into flats (dedup), then extract the primary listing of every flat (cache, then Featherless, then OpenAI).
4. Compute costs, set `cross_source` from the commissions, diff against the profile state.
5. For each emitted flat: evaluate, build the FlatItem, push it to the dataset. Upsert `new` and `changed` flats that are not `rejected` to Notion.
6. Save the property-id map and the profile state only if every Notion write of the run succeeded. A failed write is never recorded as seen, so the next run retries it.
7. Write the `RunSummary` to the key `OUTPUT`.

## Flat fields worth knowing

- `match`: `strong`, `needs_info` or `rejected`. Any failed requirement makes a flat `rejected`; rejected flats go to the dataset only.
- Risk flag `cheaper on another portal`: added when `cross_source.cheapest_portal` is a different portal from the primary listing.
- `extraction`: null when extraction did not run (skipped, stage missing, or failed).

## Secrets

`notionToken`, `featherlessApiKey` and `openaiApiKey` are secret inputs. Each falls back to the environment variable `NOTION_TOKEN`, `FEATHERLESS_API_KEY` or `OPENAI_API_KEY`. On the platform those come from the Apify secrets of the same names, via `environmentVariables` in `.actor/actor.json`. Nothing is logged.

## Run the tests (offline)

    cd apify
    .venv/bin/python -m pytest -q -m "not live"

Live tests (`-m live`) call the portals and are run per source.

## Run the Actor locally

Write the input to a JSON file (a `profile`, `skipExtraction` for debugging, and an optional `notion` block), then from `apify/`:

    apify run --input-file <input.json> --user-agent apify-agent-skills/apify-actor-development

The summary is the key `OUTPUT` in `storage/key_value_stores/default/` (a JSON file named `OUTPUT`, with a metadata file beside it). Each dataset item is one file in `storage/datasets/default/`.

## Inputs and outputs

- `.actor/input_schema.json` is the source of truth. Required: `profile`, which follows `domovoy/schemas/profile.schema.json`.
- `OUTPUT` (default key-value store): a `RunSummary`, or `{"status": "NOT_IMPLEMENTED"}` for `katastr_lookup`.
- Default dataset: one `FlatItem` per emitted flat.

## Not done yet

Bezrealitky and iDNES sources (WP2, WP3). The dataset schema in `.actor/dataset_schema.json` is still empty. Phase 2: `katastr_lookup` and the PostHog events.

## Fixtures

`tests/fixtures/texts/`: five real Sreality texts (WP0). `tests/fixtures/sreality/`: Sreality payloads (WP1). See the README in each folder for their source and scrubbing.
