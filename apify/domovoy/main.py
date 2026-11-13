"""Actor mode dispatch. WP0 stub: no portal source is registered, so search returns zero listings.

The integrator rewrites this module in WP8. run() takes the key-value store and the logger as
arguments, so the tests need neither the Actor runtime nor the network.
"""

import os
from datetime import datetime
from logging import Logger
from typing import Any, Protocol
from uuid import uuid4

import httpx

from domovoy.models import PRAGUE, Portal, RunSummary, SearchProfile, SourceStatus
from domovoy.profile import load_profile
from domovoy.sources import SOURCES
from domovoy.sources.base import SourceContext, SourceError

OUTPUT_KEY = "OUTPUT"


class KeyValueWriter(Protocol):
    async def set_value(self, key: str, value: Any) -> None: ...


async def run(actor_input: dict[str, Any], store: KeyValueWriter, log: Logger) -> dict[str, Any]:
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
    started = datetime.now(PRAGUE)
    log.info("skipExtraction=%s; extraction is not wired in WP0", bool(actor_input.get("skipExtraction")))
    statuses = [await _run_source(portal, profile, log) for portal in profile.filters.sources]
    summary = RunSummary(
        run_id=os.environ.get("APIFY_ACTOR_RUN_ID", f"local-{uuid4().hex[:8]}"),
        profile_id=profile.id,
        started_at=started,
        finished_at=datetime.now(PRAGUE),
        sources=statuses,
    )
    result = summary.model_dump(mode="json")
    await store.set_value(OUTPUT_KEY, result)
    return result


async def _run_source(portal: Portal, profile: SearchProfile, log: Logger) -> SourceStatus:
    source = SOURCES.get(portal)
    if source is None:
        return SourceStatus(portal=portal, status="failed", error="source not registered")
    found = 0
    async with httpx.AsyncClient(trust_env=False) as http:
        ctx = SourceContext(http=http, log=log, max_listings=profile.filters.max_listings)
        try:
            async for _listing in source.collect(profile, ctx):
                found += 1
                if found >= ctx.max_listings:
                    break
        except SourceError as exc:
            return SourceStatus(
                portal=portal, status="failed", found=found, fetched=found, error=str(exc)
            )
    return SourceStatus(portal=portal, status="ok", found=found, fetched=found)
