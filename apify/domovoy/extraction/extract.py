"""Extraction of one listing: cache, provider chain, quote check and confidence threshold."""

import logging
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import SecretStr, ValidationError

from domovoy.extraction.cache import ExtractionCache, cache_key
from domovoy.extraction.llm import (
    FEATHERLESS_BASE_URL,
    FALLBACK_MIN_TIMEOUT_SEC,
    FALLBACK_REASONING_EFFORT,
    OPENAI_CONCURRENCY,
    FlatBudget,
    LlmFields,
    SlotLimiter,
    ask,
    make_client,
    resolve_key,
    slot_cost,
)
from domovoy.extraction.prompt import PROMPT_VERSION, listing_input
from domovoy.models import Evidence, Extraction, Listing, LlmConfig, Provider

DEFAULT_MIN_CONFIDENCE = 0.5
log = logging.getLogger(__name__)
EVIDENCE_FIELDS = tuple(LlmFields.model_fields)


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace, non-breaking spaces included, to a single space."""
    return " ".join(text.split())


def source_text(listing: Listing) -> str:
    """The text a quote must come from: description and price_note, whitespace-normalized."""
    return normalize_ws(f"{listing.description or ''} {listing.price_note or ''}")


def is_verbatim(quote: str | None, source: str) -> bool:
    """True when the quote, after whitespace normalization, is a substring of the source."""
    needle = normalize_ws(quote or "")
    return bool(needle) and needle in normalize_ws(source)


def _evidence(value: Any, quote: str | None, confidence: float, verified: bool) -> dict[str, Any]:
    return {"value": value, "quote": quote, "confidence": confidence, "verified": verified}


def to_extraction(
    fields: LlmFields,
    listing: Listing,
    *,
    min_confidence: float,
    provider: Provider,
    model: str,
) -> Extraction:
    """Apply the checks to the model's answer and build the contract object."""
    source = source_text(listing)
    checked: dict[str, dict[str, Any]] = {}
    dropped = False
    for name in EVIDENCE_FIELDS:
        answer: Evidence | None = getattr(fields, name)
        if answer is None:
            checked[name] = _evidence(None, None, 0.0, False)
        elif answer.value is None:
            checked[name] = _evidence(None, None, answer.confidence, False)
        elif answer.confidence < min_confidence:
            dropped = True
            checked[name] = _evidence(None, None, answer.confidence, False)
        elif not (answer.quote or "").strip():
            dropped = True  # a value needs a quote; without one it cannot be checked, so it is unknown
            checked[name] = _evidence(None, None, answer.confidence, False)
        elif is_verbatim(answer.quote, source):
            quote = (answer.quote or "").strip()
            checked[name] = _evidence(answer.value, quote, answer.confidence, True)
        else:
            dropped = True
            checked[name] = _evidence(answer.value, None, answer.confidence, False)
    # The structured price is the portal's own number. A rent that disagrees with it cannot be confirmed.
    rent = checked["rent"]
    if listing.rent is not None and rent["value"] is not None and rent["value"] != listing.rent:
        dropped = True
        checked["rent"] = _evidence(None, None, rent["confidence"], False)
    return Extraction(
        **checked,
        provider=provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        status="partial" if dropped else "ok",
    )


def failed_extraction(status: Literal["failed", "timeout"] = "failed") -> Extraction:
    """Every provider failed (failed), or the flat's budget ran out (timeout): all fields unknown, no provider."""
    unknown = {name: _evidence(None, None, 0.0, False) for name in EVIDENCE_FIELDS}
    return Extraction(
        **unknown,
        provider=None,
        model=None,
        prompt_version=PROMPT_VERSION,
        status=status,
    )


def _from_cache(raw: Any) -> tuple[LlmFields, str] | None:
    """A stored raw answer and the model that gave it. A damaged or outdated entry counts as a miss."""
    if not isinstance(raw, dict) or not isinstance(raw.get("model"), str):
        return None
    try:
        return LlmFields.model_validate(raw.get("answer")), raw["model"]
    except ValidationError:
        return None


class Extractor:
    """Extracts listings for one run: one cache, one slot limit per provider, one client per provider.

    Chain: Qwen on Featherless (one attempt and one retry, within the per-flat budget), then cfg.fallback_model on
    OpenAI (gpt-6-luna at reasoning effort medium, one attempt, its own timeout). cfg.concurrency is the number of
    Featherless concurrent units this run may hold (Qwen takes 1); OpenAI calls have their own limit.
    The budget counts model-request time only. A flat with no answer whose chain ran out of time gets status
    "timeout" (nothing cached, retried by a later run); with no answer for any other reason, "failed".

    Clients passed in are used as they are. Clients this object builds from the keys are closed by aclose().
    The cache holds raw model answers. Every read, fresh or cached, goes through to_extraction().
    """

    def __init__(
        self,
        cfg: LlmConfig,
        cache: ExtractionCache | None = None,
        *,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        featherless: AsyncOpenAI | None = None,
        openai: AsyncOpenAI | None = None,
        flat_budget_sec: float | None = None,
    ) -> None:
        self._cfg = cfg
        self._flat_budget_sec = flat_budget_sec
        self._cache = cache
        self._min_confidence = min_confidence
        self._gate = SlotLimiter(cfg.concurrency)
        self._openai_gate = SlotLimiter(OPENAI_CONCURRENCY)
        self._fallback_timeout = max(cfg.timeout_sec, FALLBACK_MIN_TIMEOUT_SEC)
        self._built: list[AsyncOpenAI] = []
        if featherless is not None:
            self._featherless: AsyncOpenAI | None = featherless
        else:
            self._featherless = self._build(
                "FEATHERLESS_API_KEY", cfg.featherless_api_key, FEATHERLESS_BASE_URL, cfg.timeout_sec
            )
        if openai is not None:
            self._openai: AsyncOpenAI | None = openai
        else:
            self._openai = self._build("OPENAI_API_KEY", cfg.openai_api_key, None, self._fallback_timeout)
        self._primary_ok = self._featherless is not None and slot_cost(cfg.model) <= cfg.concurrency
        if self._featherless is not None and not self._primary_ok:
            log.warning(
                "%s needs %d Featherless units, more than llm.concurrency %d: left out of the chain",
                cfg.model, slot_cost(cfg.model), cfg.concurrency,
            )

    def _build(
        self, env_name: str, configured: SecretStr | None, base_url: str | None, timeout_sec: int
    ) -> AsyncOpenAI | None:
        key = resolve_key(env_name, configured)
        if key is None:
            return None
        client = make_client(key, base_url, timeout_sec)
        self._built.append(client)
        return client

    async def aclose(self) -> None:
        for client in self._built:
            await client.close()

    async def extract(self, listing: Listing) -> Extraction:
        text = listing_input(listing)
        key = cache_key(text, self._cfg.model)
        if self._cache is not None:
            hit = _from_cache(await self._cache.get(key))
            if hit is not None:
                # A stored answer is gated like a fresh one: against this listing and the active threshold.
                fields, model = hit
                return to_extraction(
                    fields,
                    listing,
                    min_confidence=self._min_confidence,
                    provider="cache",
                    model=model,
                )
        budget = FlatBudget(self._flat_budget_sec)
        answer = await self._ask_chain(text, budget)
        if answer is None:
            if budget.timed_out:
                # Out of time, not out of models: nothing is cached, so a later run extracts this flat again.
                log.warning("extraction ran out of time (budget %s s): status timeout", self._flat_budget_sec)
                return failed_extraction("timeout")
            return failed_extraction()
        fields, provider, model = answer
        if self._cache is not None:
            # The raw answer is stored, not the gated result, so every later read gates it again.
            await self._cache.set(key, {"model": model, "answer": fields.model_dump(mode="json")})
        return to_extraction(
            fields,
            listing,
            min_confidence=self._min_confidence,
            provider=provider,
            model=model,
        )

    async def _ask_chain(self, text: str, budget: FlatBudget) -> tuple[LlmFields, Provider, str] | None:
        """Qwen within the budget, then the OpenAI fallback. The answer records who actually answered."""
        if self._primary_ok and self._featherless is not None:
            fields = await ask(
                self._featherless,
                model=self._cfg.model,
                user_text=text,
                timeout_sec=self._cfg.timeout_sec,
                gate=self._gate,
                attempts=2,
                cost=slot_cost(self._cfg.model),
                budget=budget,
            )
            if fields is not None:
                return fields, "featherless", self._cfg.model
        if self._openai is not None and self._cfg.fallback_model is not None:
            fields = await ask(
                self._openai,
                model=self._cfg.fallback_model,
                user_text=text,
                timeout_sec=self._fallback_timeout,
                gate=self._openai_gate,
                attempts=1,
                budget=budget,
                budgeted=False,
                reasoning_effort=FALLBACK_REASONING_EFFORT,
            )
            if fields is not None:
                return fields, "openai", self._cfg.fallback_model
        return None


async def extract(listing: Listing, cfg: LlmConfig, extractor: Extractor | None = None) -> Extraction:
    """The WP0 contract: one listing to one Extraction.

    Pass a shared Extractor for the cache and the run-wide concurrency limit.
    """
    if extractor is not None:
        return await extractor.extract(listing)
    owner = Extractor(cfg)
    try:
        return await owner.extract(listing)
    finally:
        await owner.aclose()
