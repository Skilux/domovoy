"""Provider calls: keys, the OpenAI-compatible clients, and one JSON answer per provider.

Each model gets the attempts it is given: the primary model gets two (one attempt and one retry), the fallbacks
one each. A transport error is retried as it was sent. An answer that is not valid JSON, or does not match the
schema, is retried with a repair message.
"""

import asyncio
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

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
        return {name: _as_evidence(raw) for name, raw in data.items()}


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


async def ask(
    client: AsyncOpenAI,
    *,
    model: str,
    user_text: str,
    timeout_sec: int,
    gate: asyncio.Semaphore,
    attempts: int,
) -> LlmFields | None:
    """One model's answer, or None once its attempts are used up.

    attempts=2 is one attempt and one retry: a transport error is retried as it was sent, and an invalid answer
    is retried with a repair message.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    for attempt in range(1, attempts + 1):
        try:
            async with gate:
                async with asyncio.timeout(timeout_sec):
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0,
                        max_tokens=MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
            content = response.choices[0].message.content or ""
        except (APIError, TimeoutError, IndexError, AttributeError) as exc:
            log.warning("%s attempt %d failed: %s", model, attempt, type(exc).__name__)
            continue
        try:
            return _parse_answer(content)
        except ValueError as exc:  # invalid JSON and schema errors are both ValueError
            log.warning("%s attempt %d gave an invalid answer", model, attempt)
            messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": REPAIR_HINT.format(error=str(exc)[:500])},
            ]
    return None
