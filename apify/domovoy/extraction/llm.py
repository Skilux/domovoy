"""Provider calls: keys, the OpenAI-compatible clients, and one JSON answer per provider.

Each model gets the attempts it is given: the primary model gets two (one attempt and one retry), the fallbacks
one each. A transport error is retried as it was sent. An answer that is not valid JSON, or does not match the
schema, is retried with a repair message.
"""

import asyncio
import json
import logging
import os
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal

from openai import APIError, APIStatusError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from domovoy.extraction.prompt import SYSTEM_PROMPT
from domovoy.models import (
    Charge,
    Czk,
    Evidence,
    Furnished,
    Furniture,
    LeaseType,
    OneTimeFee,
    UnitType,
)

# Chosen by Vladimir in GitHub issue #35. See apify/research/featherless.md.
DEFAULT_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
# First fallback, on Featherless. The models API lists its concurrency_cost as 4 (Qwen: 1).
DEFAULT_FALLBACK_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
# Last resort, on OpenAI. Not a decision by Vladimir: the model that answered on this account in the live test.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
ENV_FILE = Path("/Users/vladimir/.config/domovoy/.env")
MAX_TOKENS = 2048
# Featherless concurrent units per call (GET /v1/models, concurrency_cost). A model not listed here counts as 4.
MODEL_SLOTS = {DEFAULT_MODEL: 1, DEFAULT_FALLBACK_MODEL: 4}
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BASE_WAIT = 1.0
RATE_LIMIT_MAX_WAIT = 30.0
REPAIR_HINT = (
    "Your reply is not valid for the required JSON shape ({error}). "
    "Reply with the complete corrected JSON object only, following the same rules."
)

log = logging.getLogger(__name__)


def _as_evidence(raw: Any) -> Any:
    """Normalize one field of the answer to {"value", "quote", "confidence"}.

    A bare value cannot be verified, so it is kept with confidence 0 and counts as unknown. A missing or null
    confidence also counts as 0. Schema errors on the value itself still fail the answer.
    """
    if isinstance(raw, dict) and ("value" in raw or "confidence" in raw):
        confidence = raw.get("confidence")
        return {**raw, "confidence": 0.0 if confidence is None else confidence}
    return {"value": raw, "quote": None, "confidence": 0.0}


class LlmFields(BaseModel):
    """The model's answer, one Evidence per extracted field. A missing or null field counts as unknown."""

    model_config = ConfigDict(extra="ignore")

    rent: Evidence[Czk] | None = None
    services: Evidence[Charge] | None = None
    energy: Evidence[Charge] | None = None
    kauce: Evidence[Charge] | None = None
    commission: Evidence[Charge] | None = None
    one_time_fees: Evidence[list[OneTimeFee]] | None = None
    move_in_date: Evidence[date | Literal["immediately", "by agreement"]] | None = None
    lease_type: Evidence[LeaseType] | None = None
    lease_length_months: Evidence[int] | None = None
    furnished: Evidence[Furnished] | None = None
    missing_furniture: Evidence[list[Furniture]] | None = None
    pets_allowed: Evidence[bool] | None = None
    permanent_residence: Evidence[bool] | None = None
    unit_type_hint: Evidence[UnitType] | None = None

    @model_validator(mode="before")
    @classmethod
    def wrap_bare_values(cls, data: Any) -> Any:
        """Pydantic skips underscore-prefixed validators, so this one has a public name."""
        if not isinstance(data, dict):
            return data
        wrapped = {name: _as_evidence(raw) for name, raw in data.items()}
        for name in CHARGE_FIELDS:
            if isinstance(wrapped.get(name), dict) and isinstance(wrapped[name].get("value"), dict):
                wrapped[name] = {**wrapped[name], "value": _whole_charge(wrapped[name]["value"])}
        return wrapped


CHARGE_FIELDS = ("services", "energy", "kauce", "commission")


def _whole_charge(charge: dict[str, Any]) -> dict[str, Any]:
    """Charge.czk and Charge.rent_multiple are integers. A whole float (2.0) becomes 2. A fraction becomes null.

    A fraction is unknown, not an invalid answer: "kauce 1 a 1/2 měsíčního nájmu" gave rent_multiple 1.5, which failed
    the whole answer, and the repair retry then rounded it to a wrong 1 (13:48 platform run and the perf local run).
    """
    fixed = dict(charge)
    for key in ("czk", "rent_multiple"):
        value = fixed.get(key)
        if isinstance(value, float):
            fixed[key] = int(value) if value.is_integer() else None
    return fixed


def _parse_answer(content: str) -> LlmFields:
    """Parse one answer. DeepSeek-V4-Flash on Featherless sometimes drops the opening brace, so it is put back.

    Only that shape is repaired. The quotes are still checked against the text, so nothing unverified gets through.
    """
    text = content.strip()
    if text.startswith('"') and text.endswith("}"):
        text = "{" + text
    return LlmFields.model_validate_json(text)


def resolve_key(name: str, configured: SecretStr | None) -> str | None:
    """A key from the config, else the environment, else the shared env file. Never logged."""
    if configured is not None and configured.get_secret_value():
        return configured.get_secret_value()
    return os.environ.get(name) or read_env_file(ENV_FILE).get(name) or None


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines. Comments and blank lines are skipped. A missing file gives no values."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


def make_client(api_key: str, base_url: str | None, timeout_sec: int) -> AsyncOpenAI:
    """An OpenAI-compatible client. The SDK's own retries are off: ask() owns the single retry."""
    if base_url is None:
        return AsyncOpenAI(api_key=api_key, timeout=timeout_sec, max_retries=0)
    return AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec, max_retries=0)


class SlotLimiter:
    """A weighted, first-come-first-served limit on Featherless concurrent units.

    A call holds `cost` slots of `capacity` while it is in flight (Qwen3-30B 1, DeepSeek-V4-Flash 4). A cost is never
    lowered: a cost above the capacity is refused, and the Extractor leaves such a model out of its chain. Waiters
    are served in order: a 4-slot fallback is not starved by a stream of 1-slot calls behind it.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self.used = 0
        self._waiters: deque[tuple[int, asyncio.Future[None]]] = deque()

    async def acquire(self, cost: int) -> int:
        """Wait for `cost` slots and hold them. Returns the cost; release() it."""
        if not 1 <= cost <= self.capacity:
            raise ValueError("a call of %d units cannot run within %d units" % (cost, self.capacity))
        if not self._waiters and self.used + cost <= self.capacity:
            self.used += cost
            return cost
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (cost, future)
        self._waiters.append(entry)
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self.release(cost)  # granted and cancelled at once: give the slots back
            else:
                self._waiters.remove(entry)
                self._wake()
            raise
        return cost

    def release(self, cost: int) -> None:
        self.used -= cost
        self._wake()

    def _wake(self) -> None:
        while self._waiters and self.used + self._waiters[0][0] <= self.capacity:
            cost, future = self._waiters.popleft()
            if future.done():
                continue
            self.used += cost
            future.set_result(None)

    @asynccontextmanager
    async def slots(self, cost: int) -> AsyncIterator[None]:
        held = await self.acquire(cost)
        try:
            yield
        finally:
            self.release(held)


def slot_cost(model: str) -> int:
    """Featherless concurrent units for one call of this model. An unknown model counts as 4, the largest class."""
    return MODEL_SLOTS.get(model, 4)


def _retry_after(exc: APIStatusError, attempt: int) -> float:
    try:
        return min(float(exc.response.headers["Retry-After"]), RATE_LIMIT_MAX_WAIT)
    except (KeyError, ValueError, TypeError, AttributeError):
        return min(RATE_LIMIT_BASE_WAIT * 2**attempt, RATE_LIMIT_MAX_WAIT)


def failure_reason(exc: BaseException) -> str:
    """The reason class of a failed call. Never the content: listing text and contacts stay out of the log."""
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_url=False, include_input=False, include_context=False)
        if any(error.get("type") == "json_invalid" for error in errors):
            return "json_parse"
        paths = sorted({".".join(str(part) for part in error.get("loc", ())) or "<root>" for error in errors})
        return "schema:" + ",".join(paths[:5])
    if isinstance(exc, APIStatusError):
        return "http_%d" % exc.status_code
    return "transport:" + type(exc).__name__


class InvalidAnswer(ValueError):
    """The call answered, but the answer cannot be used. `reason` is the class that is logged."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _content(response: Any) -> str:
    """The answer text, or InvalidAnswer with the reason class: no choices, empty, truncated, refusal."""
    choices = getattr(response, "choices", None)
    if not choices:
        raise InvalidAnswer("no_choices")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if getattr(message, "refusal", None):
        raise InvalidAnswer("refusal")
    content = getattr(message, "content", None) or ""
    if getattr(choice, "finish_reason", None) == "length":
        # Cut at max_tokens. Usable only if a complete JSON object came first (then e.g. endless whitespace).
        complete = _first_object(content)
        if complete is None:
            raise InvalidAnswer("truncated")
        log.warning("answer cut at max_tokens after a complete JSON object; the object is used")
        return complete
    if not content.strip():
        raise InvalidAnswer("empty")
    return content


def _first_object(content: str) -> str | None:
    """The first complete JSON object at the start of the text, or None."""
    text = content.strip()
    try:
        _, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    return text[:end] if text.startswith("{") else None


def _usage(response: Any) -> str:
    usage = getattr(response, "usage", None)
    if usage is None:
        return "no usage"
    return "prompt %s, completion %s tokens" % (
        getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))


async def ask(
    client: AsyncOpenAI,
    *,
    model: str,
    user_text: str,
    timeout_sec: int,
    gate: SlotLimiter,
    attempts: int,
    cost: int = 1,
) -> LlmFields | None:
    """One model's answer, or None once its attempts are used up.

    attempts=2 is one attempt and one retry: a transport error is retried as it was sent, and an invalid answer
    is retried with a repair message. A 429 (Featherless concurrent units or model switch) is waited out with
    backoff, outside the slots and without using an attempt, up to RATE_LIMIT_RETRIES times per call.
    Every failure is logged with its reason class only (failure_reason, InvalidAnswer), never the content.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    attempt = 0
    rate_limited = 0
    while attempt < attempts:
        attempt += 1
        try:
            async with gate.slots(cost):
                async with asyncio.timeout(timeout_sec):
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0,
                        max_tokens=MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
        except RateLimitError as exc:
            if rate_limited < RATE_LIMIT_RETRIES:
                wait = _retry_after(exc, rate_limited)
                rate_limited += 1
                attempt -= 1  # a 429 is the plan saying "not now", not a failed attempt
                log.warning("%s: HTTP 429, waiting %.1f s (%d of %d)", model, wait, rate_limited, RATE_LIMIT_RETRIES)
                await asyncio.sleep(wait)
                continue
            log.warning("%s attempt %d failed: http_429, retries for 429 used up", model, attempt)
            continue
        except (APIError, TimeoutError) as exc:
            log.warning("%s attempt %d failed: %s", model, attempt, failure_reason(exc))
            continue
        try:
            content = _content(response)
        except InvalidAnswer as exc:
            log.warning("%s attempt %d gave an invalid answer: %s (%s)", model, attempt, exc.reason, _usage(response))
            continue  # nothing to repair: the same request is sent again
        try:
            return _parse_answer(content)
        except ValidationError as exc:  # invalid JSON and schema errors
            log.warning(
                "%s attempt %d gave an invalid answer: %s (%s)", model, attempt, failure_reason(exc), _usage(response)
            )
            messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": REPAIR_HINT.format(error=_repair_detail(exc))},
            ]
    return None


def _repair_detail(exc: ValidationError) -> str:
    """What to fix, for the model: the field paths and pydantic's messages, without the submitted values."""
    errors = exc.errors(include_url=False, include_input=False, include_context=False)
    return "; ".join("%s: %s" % (".".join(str(p) for p in e.get("loc", ())) or "<root>", e.get("msg", ""))
                     for e in errors[:8])[:500]
