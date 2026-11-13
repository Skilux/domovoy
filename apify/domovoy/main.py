"""Actor mode dispatch (WP8). run() takes the platform and the logger as arguments, so the tests need neither the Actor runtime nor the network.

katastr_lookup returns NOT_IMPLEMENTED. search runs the pipeline in domovoy.pipeline and writes its RunSummary to
the key OUTPUT. Sources register themselves when domovoy.sources is imported (see domovoy/sources/__init__.py).
The extractor is opened by __main__ inside the Actor run and passed in; None means extraction is off (skipExtraction).
"""

from logging import Logger
from typing import Any

from domovoy.pipeline import Platform, resolve_modules, run_search
from domovoy.profile import load_profile
from domovoy.sources import SOURCES

OUTPUT_KEY = "OUTPUT"


async def run(
    actor_input: dict[str, Any], store: Platform, log: Logger, *, extractor: Any | None = None
) -> dict[str, Any]:
    mode = actor_input.get("mode", "search")
    if mode == "katastr_lookup":
        result: dict[str, Any] = {"status": "NOT_IMPLEMENTED"}
        await store.set_value(OUTPUT_KEY, result)
        return result
    if mode != "search":
        raise ValueError(f"unknown mode {mode!r}; expected 'search' or 'katastr_lookup'")
    if "profile" not in actor_input:
        raise ValueError("input.profile is required for mode 'search'")
    profile = load_profile(actor_input["profile"])
    modules = resolve_modules(log)
    modules.extraction = extractor
    summary = await run_search(profile, actor_input, store, log, sources=SOURCES, modules=modules)
    result = summary.model_dump(mode="json")
    await store.set_value(OUTPUT_KEY, result)
    return result
