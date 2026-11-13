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
2. Featherless, the primary model `llm.model` (Qwen), two attempts.
3. Featherless, the fallback model `llm.fallbackModel` (DeepSeek-V4-Flash), one attempt.
4. OpenAI `gpt-4o-mini`, a last resort set in code, one attempt. It runs only when an OpenAI key is set.

An answer whose confidence is below 0.5 becomes unknown. `llm.concurrency` defaults to 1, because the DeepSeek fallback takes 4 slots of the Featherless plan. The extractor is opened in `__main__` inside the Actor run and closed after it.

## Run order

1. Validate the profile. With `notion.dataSourceId` set, the Notion schema is checked before any portal is contacted.
2. Collect each source in `filters.sources`, one at a time. A source that raises is `failed`. A source whose stats report failed or skipped items is `degraded`.
3. Merge listings into flats across portals (dedup). Extract and cost every flat, unchanged ones too, because `cross_source` needs their commissions before diff. Skipped when `skipExtraction` is set.
4. Set `cross_source` from the commissions, then diff against the profile state.
5. For each emitted flat: evaluate, build the FlatItem, push it to the dataset. Upsert `new` and `changed` flats that are not `rejected` to Notion. A failed upsert is counted in `notion.errors`.
6. Save the property-id map and the profile state only if every Notion write of the run succeeded. A failed write is never recorded as seen, so the next run retries it.
7. Write the `RunSummary` to the key `OUTPUT`. The Notion sink is closed at the end of the run, also when the run fails.

## Flat fields worth knowing

- `match`: `strong`, `needs_info` or `rejected`. Any failed requirement makes a flat `rejected`; rejected flats go to the dataset only.
- Risk flag `cheaper on another portal`: added when `cross_source.cheapest_portal` is a different portal from the primary listing.
- `change`: `new`, `changed` or `unchanged`. Unchanged flats reach the dataset only with `includeUnchanged`, and never reach Notion.
- `extraction`: null when extraction did not run (skipped, stage missing, or the run skipped it). When every model fails, it is an object with `status` `failed` and no provider.

## Secrets

`notionToken`, `featherlessApiKey` and `openaiApiKey` are secret inputs. Each falls back to the environment variable `NOTION_TOKEN`, `FEATHERLESS_API_KEY` or `OPENAI_API_KEY`. On the platform those come from the Apify secrets of the same names, via `environmentVariables` in `.actor/actor.json`. Locally, the extraction stage also falls back to `/Users/vladimir/.config/domovoy/.env` by design. Nothing is logged; the run log only says whether each key is set.

## Run the tests (offline)

    cd apify
    .venv/bin/python -m pytest -q -m "not live"

Live tests (`-m live`) call the portals and are run per source.

## Run the Actor locally

Write the input to a JSON file (a `profile`, `skipExtraction` for debugging, and an optional `notion` block), then from `apify/`:

    apify run --input-file <input.json> --user-agent apify-agent-skills/apify-actor-development

The summary is the key `OUTPUT` in `storage/key_value_stores/default/` (a JSON file named `OUTPUT`, with a metadata file beside it). Each dataset item is one file in `storage/datasets/default/`. The named stores `domovoy-property-ids` and `domovoy-profile-state` persist between local runs, so a second run reports unchanged flats.

## Inputs and outputs

- `.actor/input_schema.json` is the source of truth. Required: `profile`, which follows `domovoy/schemas/profile.schema.json`.
- `OUTPUT` (default key-value store): a `RunSummary`, or `{"status": "NOT_IMPLEMENTED"}` for `katastr_lookup`.
- Default dataset: one `FlatItem` per emitted flat.

## Not done yet

The dataset schema in `.actor/dataset_schema.json` is still an empty placeholder. Phase 2: `katastr_lookup` and the PostHog events.

## Fixtures

`tests/fixtures/texts/`: five real Sreality texts (WP0). `tests/fixtures/sreality/`, `tests/fixtures/bezrealitky/` and `tests/fixtures/idnes/`: portal payloads (WP1 to WP3). See the README in each folder for their source and scrubbing.
