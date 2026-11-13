# DOMOVOY Actor (apify/)

WP0 foundation. The Actor runs, but it does not search any portal yet.

## What works now

- Profile validation: `profile` is validated into `SearchProfile` (`domovoy/models.py`). The schema copy is `domovoy/schemas/profile.schema.json`.
- `mode: search`: runs the registered portal sources. `idnes` (WP3) is registered; Sreality and Bezrealitky are not yet, so their summaries say `failed` with "source not registered".
- `mode: katastr_lookup`: returns `{"status": "NOT_IMPLEMENTED"}`.
- An unknown mode raises an error, so the run fails.
- `skipExtraction` is logged. No LLM client exists yet.

## Not implemented yet

Portal sources (WP1-WP3), extraction (WP4), costs and requirement verdicts (WP5), dedup and profile state (WP6), the Notion sink (WP7) and the pipeline wiring (WP8). WP0 reads none of the API keys or the Notion settings.

## Run the tests (offline)

    cd apify
    /opt/homebrew/bin/python3.11 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m pytest -q

## Run the Actor locally

Put the input in `storage/key_value_stores/default/INPUT.json`, then run from `apify/`:

    apify run --user-agent apify-agent-skills/apify-actor-development

The summary is written to `storage/key_value_stores/default/OUTPUT.json`.

## Inputs

`.actor/input_schema.json` is the source of truth. Required: `profile`. The profile follows `domovoy/schemas/profile.schema.json`, a copy of `skill/domovoy/reference/profile.schema.json`.

## Outputs

- `OUTPUT` (default key-value store): a `RunSummary`, or `{"status": "NOT_IMPLEMENTED"}` for `katastr_lookup`.
- Default dataset: empty in WP0. `FlatItem` is defined, but nothing writes it yet.

## Fixtures

`tests/fixtures/texts/` holds 5 real Sreality listing texts. See `tests/fixtures/README.md` for their source, scrubbing and the variety each covers.
