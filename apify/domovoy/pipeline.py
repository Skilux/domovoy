"""Search pipeline (docs/prd/actor.md Diagram), wired in the order WP6 set.

Run order: open the two dedup stores, load the property-id map, merge, extract and cost every flat, set
cross_source from the commissions, diff against the profile state; then, for each emitted flat, evaluate,
build the FlatItem, push it to the dataset and upsert new and changed flats (not rejected) to Notion. The
property-id map and the profile state are saved only when every Notion write of the run succeeded, so a
failed write is never recorded as seen.

The stages are the merged modules: dedup (WP6), costs (WP5), the Notion sink (WP7) and the extractor (WP4).
The extractor is opened inside the Actor run by open_extractor(), because its cache is an Apify store.
A failing source, extraction or Notion write is counted in the run summary; it never stops the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import Any, Protocol
from uuid import uuid4

import httpx
from pydantic import SecretStr

import domovoy.costs as costs_stage
import domovoy.dedup as dedup_stage
import domovoy.notion.sink as notion_stage
from domovoy.assemble import build_flat_item
from domovoy.extraction import Extractor, open_apify_cache
from domovoy.models import (
    PRAGUE,
    Costs,
    CrossSource,
    Evaluation,
    Extraction,
    Flat,
    FlatItem,
    LlmConfig,
    Listing,
    NotionCounts,
    RunSummary,
    SearchProfile,
    SourceStatus,
)
from domovoy.sources.base import Source, SourceContext, SourceError

DEFAULT_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"  # decided in #35
DEFAULT_FALLBACK_MODEL = "deepseek-ai/DeepSeek-V4-Flash"  # Featherless; takes 4 concurrency slots
DEFAULT_CONCURRENCY = 1
DEFAULT_TIMEOUT_SEC = 60
CONFIDENCE_THRESHOLD = 0.5  # Extractor(min_confidence=...): answers below it become unknown (open item 7)
NO_EXTRACTION_PROMPT_VERSION = "none"
EVIDENCE_FIELDS = tuple(
    name for name in Extraction.model_fields if name not in {"provider", "model", "prompt_version", "status"}
)


class KeyValue(Protocol):
    async def get_value(self, key: str) -> Any: ...
    async def set_value(self, key: str, value: Any) -> None: ...


class Platform(Protocol):
    """The Actor runtime as the pipeline sees it. The Actor class satisfies it; tests pass a fake."""

    async def set_value(self, key: str, value: Any) -> None: ...
    async def push_data(self, items: list[dict[str, Any]]) -> None: ...
    async def open_key_value_store(self, name: str) -> KeyValue: ...


@dataclass
class Modules:
    """The stage modules and objects. None means that stage's fallback is used; tests build partial sets."""

    dedup: Any = None  # domovoy.dedup (WP6)
    extraction: Any = None  # the Extractor (WP4), opened inside the run by open_extractor()
    costs: Any = None  # domovoy.costs (WP5)
    notion: Any = None  # domovoy.notion.sink (WP7)


@dataclass
class Analysis:
    extraction: Extraction
    ran: bool  # False: extraction was skipped or failed, so every field is unknown
    costs: Costs


def resolve_modules(log: Logger) -> Modules:
    """The merged stages: dedup, costs and the Notion sink. The extractor is opened by open_extractor()."""
    log.info("stages: dedup, costs and notion are the merged modules; extraction opens inside the run")
    return Modules(dedup=dedup_stage, costs=costs_stage, notion=notion_stage)


def _secret(actor_input: Mapping[str, Any], input_key: str, env_key: str, environ: Mapping[str, str]) -> str | None:
    """The input secret first, then the environment. The value is never logged."""
    return actor_input.get(input_key) or environ.get(env_key) or None


def llm_config(actor_input: Mapping[str, Any], environ: Mapping[str, str]) -> LlmConfig:
    llm = actor_input.get("llm") or {}
    featherless = _secret(actor_input, "featherlessApiKey", "FEATHERLESS_API_KEY", environ)
    openai_key = _secret(actor_input, "openaiApiKey", "OPENAI_API_KEY", environ)
    return LlmConfig(
        model=llm.get("model") or DEFAULT_MODEL,
        concurrency=llm.get("concurrency") or DEFAULT_CONCURRENCY,
        timeout_sec=llm.get("timeoutSec") or DEFAULT_TIMEOUT_SEC,
        fallback_model=llm.get("fallbackModel") or DEFAULT_FALLBACK_MODEL,
        featherless_api_key=SecretStr(featherless) if featherless else None,
        openai_api_key=SecretStr(openai_key) if openai_key else None,
    )


async def open_extractor(actor_input: Mapping[str, Any], environ: Mapping[str, str], log: Logger) -> Extractor | None:
    """The extraction stage (WP4), opened inside the Actor run: an Extractor over the Apify cache.

    Returns None when skipExtraction is set. The log says whether each key is set, never the key itself.
    The caller closes the result with aclose().
    """
    if actor_input.get("skipExtraction"):
        log.info("skipExtraction: extraction is off; costs and requirements run on unknown fields")
        return None
    cfg = llm_config(actor_input, environ)
    log.info(
        "extraction: model %s, fallback %s; Featherless key %s; OpenAI last-resort key %s",
        cfg.model,
        cfg.fallback_model,
        "set" if cfg.featherless_api_key else "not set",
        "set" if cfg.openai_api_key else "not set",
    )
    cache = await open_apify_cache()
    return Extractor(cfg, cache, min_confidence=CONFIDENCE_THRESHOLD)


async def open_notion(
    actor_input: Mapping[str, Any], modules: Modules, environ: Mapping[str, str], log: Logger
) -> Any:
    """Returns the Notion sink, or None for dataset-only runs. The schema is checked before any portal is contacted."""
    data_source_id = (actor_input.get("notion") or {}).get("dataSourceId")
    if not data_source_id:
        log.info("Notion: off, no notion.dataSourceId; results go to the dataset only")
        return None
    token = _secret(actor_input, "notionToken", "NOTION_TOKEN", environ)
    if token is None:
        raise ValueError("notion.dataSourceId is set but there is no Notion token: set notionToken or NOTION_TOKEN")
    if modules.notion is None:
        log.warning("Notion: fallback in use; results go to the dataset only")
        return None
    sink = modules.notion.NotionSink(token=token, data_source_id=data_source_id)
    try:
        await sink.validate()  # raises on schema drift, before any portal is contacted
    except BaseException:
        await sink.aclose()
        raise
    log.info("Notion: schema checked before scraping")
    return sink


async def collect_listings(
    profile: SearchProfile, sources: Mapping[str, Source], log: Logger
) -> tuple[list[SourceStatus], list[Listing]]:
    statuses: list[SourceStatus] = []
    listings: list[Listing] = []
    async with httpx.AsyncClient(trust_env=False) as http:
        for portal in profile.filters.sources:
            source = sources.get(portal)
            if source is None:
                log.warning("source %s: not registered, reported as failed", portal)
                statuses.append(SourceStatus(portal=portal, status="failed", error="source not registered"))
                continue
            status, collected = await _collect_one(portal, source, profile, http, log)
            statuses.append(status)
            listings.extend(collected)
    return statuses, listings


async def _collect_one(
    portal: str, source: Source, profile: SearchProfile, http: httpx.AsyncClient, log: Logger
) -> tuple[SourceStatus, list[Listing]]:
    ctx = SourceContext(http=http, log=log, max_listings=profile.filters.max_listings)
    collected: list[Listing] = []
    try:
        async for listing in source.collect(profile, ctx):
            collected.append(listing)
            if len(collected) >= ctx.max_listings:
                break
    except Exception as exc:  # one portal must never stop the run
        text = str(exc) or type(exc).__name__
        log.warning(
            "source %s: failed after %d listings: %s: %s",
            portal, len(collected), type(exc).__name__, text, exc_info=not isinstance(exc, SourceError),
        )
        return SourceStatus(portal=portal, status="failed", found=len(collected), fetched=len(collected), error=text), collected
    stats = getattr(source, "last_stats", None)
    status = status_from_stats(portal, stats, len(collected))
    log.info(
        "source %s: %s, found %d, fetched %d, failed %d, skipped %d",
        portal, status.status, status.found, status.fetched, status.failed, _stat(stats, "skipped", 0),
    )
    return status, collected


def status_from_stats(portal: str, stats: Any, yielded: int) -> SourceStatus:
    """A source without last_stats is ok with what it yielded. With stats, any failed or skipped item makes it degraded."""
    if stats is None:
        return SourceStatus(portal=portal, status="ok", found=yielded, fetched=yielded)
    candidates = _stat(stats, "candidates", yielded)
    fetched = _stat(stats, "fetched", yielded)
    failed = _stat(stats, "failed", 0)
    skipped = _stat(stats, "skipped", 0)
    if failed == 0 and skipped == 0:
        return SourceStatus(portal=portal, status="ok", found=candidates, fetched=fetched, failed=0)
    return SourceStatus(
        portal=portal,
        status="degraded",
        found=candidates,
        fetched=fetched,
        failed=failed,
        error=f"{failed} failed, {skipped} skipped",
    )


def _stat(stats: Any, name: str, default: int) -> int:
    value = stats.get(name) if isinstance(stats, Mapping) else getattr(stats, name, None)
    return default if value is None else int(value)


def profile_hash(profile: SearchProfile) -> str:
    """A hash of the profile's content, stored in the profile state. A change makes every flat count as changed."""
    text = json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def passthrough_flat(listing: Listing) -> Flat:
    """Dedup fallback: one flat per listing, with a temporary id that is stable across runs."""
    digest = hashlib.sha256(f"{listing.portal}:{listing.source_id}".encode("utf-8")).hexdigest()[:10]
    return Flat(
        property_id=f"tmp-{digest}",
        sources=[listing],
        primary=listing,
        cross_source=CrossSource(cheapest_portal=None, commission_savings=None, price_spread=None),
    )


def empty_extraction() -> Extraction:
    """Every field unknown. Used when extraction is skipped, missing or failed."""
    unknown = {"value": None, "quote": None, "confidence": 0.0, "verified": False}
    data: dict[str, Any] = {name: dict(unknown) for name in EVIDENCE_FIELDS}
    data.update(provider=None, model=None, prompt_version=NO_EXTRACTION_PROMPT_VERSION, status="failed")
    return Extraction.model_validate(data)


def fallback_costs(listing: Listing) -> Costs:
    """Costs module missing: nothing is derived. The listed rent is copied because it is stated, not computed."""
    return Costs(
        rent=listing.rent,
        services=None,
        energy=None,
        total_monthly=None,
        kauce=None,
        commission=None,
        one_time_fees=None,
        first_payment=None,
        upfront=None,
        missing_furniture=[],
        missing_furniture_cost=None,
        hidden_monthly=None,
        estimated=[],
    )


def fallback_evaluation() -> Evaluation:
    return Evaluation(match="needs_info", requirements=[], unknowns=[], match_reasons=[], risk_flags=[])


def commissions_for(flat: Flat, costs: Costs) -> dict[str, int | None]:
    """Commission per "portal:source_id". Only the primary listing is extracted, so the others stay None."""
    primary = flat.primary
    return {
        f"{listing.portal}:{listing.source_id}": (
            costs.commission if (listing.portal, listing.source_id) == (primary.portal, primary.source_id) else None
        )
        for listing in flat.sources
    }


async def analyse(
    flats: list[Flat], extractor: Any | None, profile: SearchProfile, modules: Modules, log: Logger
) -> list[Analysis]:
    """Extraction for every flat, then costs. The Extractor's own gate sets the concurrency (llm.concurrency).

    Unchanged flats are included too: cross_source needs their commissions before diff, and the extraction
    cache makes them cheap.
    """

    async def extract_one(flat: Flat) -> tuple[Extraction, bool]:
        if extractor is None:
            return empty_extraction(), False
        try:
            return await extractor.extract(flat.primary), True
        except Exception as exc:  # the flat goes on with every field unknown
            log.warning("extraction failed for %s: %s: %s", flat.property_id, type(exc).__name__, exc)
            return empty_extraction(), False

    extracted = await asyncio.gather(*(extract_one(flat) for flat in flats))
    analyses: list[Analysis] = []
    for flat, (extraction, ran) in zip(flats, extracted):
        if modules.costs is not None:
            costs = modules.costs.compute_costs(flat.primary, extraction, profile)
        else:
            costs = fallback_costs(flat.primary)
        analyses.append(Analysis(extraction=extraction, ran=ran, costs=costs))
    return analyses


async def write_notion(sink: Any, item: FlatItem, counts: NotionCounts, log: Logger) -> None:
    try:
        result = await sink.upsert(item)
    except Exception as exc:  # counted; the run goes on and the state is not saved
        counts.errors += 1
        log.warning("Notion: upsert failed for %s: %s: %s", item.property_id, type(exc).__name__, exc)
        return
    if result.action == "created":
        counts.created += 1
    elif result.action == "updated":
        counts.updated += 1


async def run_search(
    profile: SearchProfile,
    actor_input: Mapping[str, Any],
    platform: Platform,
    log: Logger,
    *,
    sources: Mapping[str, Source],
    modules: Modules,
    environ: Mapping[str, str] = os.environ,
) -> RunSummary:
    """Open the Notion sink (its schema is checked before any portal is contacted), run, then close the sink."""
    sink = await open_notion(actor_input, modules, environ, log)
    try:
        return await _search(
            profile, actor_input, platform, log, sources=sources, modules=modules, environ=environ, sink=sink
        )
    finally:
        if sink is not None:
            await sink.aclose()


async def _search(
    profile: SearchProfile,
    actor_input: Mapping[str, Any],
    platform: Platform,
    log: Logger,
    *,
    sources: Mapping[str, Source],
    modules: Modules,
    environ: Mapping[str, str],
    sink: Any,
) -> RunSummary:
    started = datetime.now(PRAGUE)
    run_id = environ.get("APIFY_ACTOR_RUN_ID") or f"local-{uuid4().hex[:8]}"
    include_unchanged = bool(actor_input.get("includeUnchanged"))
    skip_extraction = bool(actor_input.get("skipExtraction"))
    current_hash = profile_hash(profile)

    statuses, listings = await collect_listings(profile, sources, log)

    dd = modules.dedup
    dedup_on = dd is not None and bool(listings)
    property_store: KeyValue | None = None
    state_store: KeyValue | None = None
    ids: dict[str, str] | None = None
    state: Any = None
    if dedup_on:
        property_store = await platform.open_key_value_store(name=dd.PROPERTY_IDS_STORE)
        state_store = await platform.open_key_value_store(name=dd.PROFILE_STATE_STORE)
        ids = await dd.load_property_ids(property_store)
        flats = dd.merge(listings, ids)  # updates ids in place
        state = await dd.load_profile_state(state_store, profile.id)
    else:
        flats = [passthrough_flat(listing) for listing in listings]  # no state I/O in the fallback

    extractor = None if skip_extraction else modules.extraction
    analyses = await analyse(flats, extractor, profile, modules, log)

    providers = {"featherless": 0, "openai": 0, "cache": 0}
    for analysis in analyses:
        if analysis.ran and analysis.extraction.provider is not None:
            providers[analysis.extraction.provider] += 1

    if dedup_on:
        flats = [
            flat.model_copy(update={"cross_source": dd.cross_source(flat.sources, commissions_for(flat, analysis.costs))})
            for flat, analysis in zip(flats, analyses)
        ]
        changes = dd.diff(flats, state)
        if state.profile_hash != current_hash:  # the profile changed: every flat is re-evaluated
            changes = [(flat, "changed" if change == "unchanged" else change) for flat, change in changes]
    else:
        changes = [(flat, "new") for flat in flats]

    by_id = {flat.property_id: analysis for flat, analysis in zip(flats, analyses)}
    change_counts = {"new": 0, "changed": 0, "unchanged": 0}
    match_counts = {"strong": 0, "needs_info": 0, "rejected": 0}
    rejected_by: dict[str, int] = {}
    notion = NotionCounts()
    for flat, change in changes:
        change_counts[change] += 1
        if change == "unchanged" and not include_unchanged:
            continue
        analysis = by_id[flat.property_id]
        if modules.costs is not None:
            evaluation = modules.costs.evaluate(flat.primary, analysis.extraction, analysis.costs, profile)
        else:
            evaluation = fallback_evaluation()
        seen = state.flats.get(flat.property_id) if state is not None else None
        item = build_flat_item(
            flat,
            analysis.extraction,
            analysis.costs,
            evaluation,
            profile=profile,
            run_id=run_id,
            change=change,
            first_seen=seen.first_seen if seen is not None else started,
            last_seen=started,
            extraction_ran=analysis.ran,
        )
        match_counts[item.match] += 1
        if item.match == "rejected":  # every failed requirement counts, so one flat can count under several
            for verdict in evaluation.requirements:
                if verdict.verdict == "fail":
                    rejected_by[verdict.name] = rejected_by.get(verdict.name, 0) + 1
        await platform.push_data([item.model_dump(mode="json")])
        delivers = change in ("new", "changed") or include_unchanged
        if sink is not None and delivers and item.match != "rejected":
            await write_notion(sink, item, notion, log)

    if dedup_on and flats:
        if notion.errors:
            log.warning(
                "state not saved: %d Notion write(s) failed; the next run retries those flats", notion.errors
            )
        else:
            await dd.save_property_ids(property_store, ids)
            if sink is None:
                # Nothing reached Notion, so nothing may be recorded as seen: a later Notion run must deliver these flats.
                log.info("profile state not saved: this run had no Notion sink")
            else:
                new_state = dd.record_run(state, flats, started).model_copy(update={"profile_hash": current_hash})
                await dd.save_profile_state(state_store, new_state)
                log.info("state saved for profile %s: %d flats recorded", profile.id, len(flats))

    summary = RunSummary(
        run_id=run_id,
        profile_id=profile.id,
        started_at=started,
        finished_at=datetime.now(PRAGUE),
        sources=statuses,
        change=change_counts,
        match=match_counts,
        rejected_by_requirement=rejected_by,
        notion=notion,
        extraction_providers=providers,
    )
    log.info(
        "run done: change %s, match %s, notion created %d updated %d errors %d",
        change_counts, match_counts, notion.created, notion.updated, notion.errors,
    )
    return summary
