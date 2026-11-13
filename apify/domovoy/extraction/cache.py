"""Extraction cache: an injectable async get/set over JSON values, keyed by sha256(text + model + prompt_version)."""

import hashlib
import json
from typing import Any, Protocol

from apify import Actor
from apify.storages import KeyValueStore

from domovoy.extraction.prompt import PROMPT_VERSION

CACHE_STORE_NAME = "domovoy-extraction-cache"


class ExtractionCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(self, key: str, value: dict[str, Any]) -> None: ...


def cache_key(text: str, model: str) -> str:
    return hashlib.sha256((text + model + PROMPT_VERSION).encode("utf-8")).hexdigest()


class MemoryCache:
    """In-process cache for tests and single runs. Values go through JSON, as they do in the Apify store."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = self._items.get(key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._items[key] = json.dumps(value)


class ApifyCache:
    """The named Apify key-value store domovoy-extraction-cache."""

    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    async def get(self, key: str) -> dict[str, Any] | None:
        return await self._store.get_value(key)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._store.set_value(key, value)


async def open_apify_cache() -> ApifyCache:
    """Open the named store. Call inside an Actor run (`async with Actor:`)."""
    return ApifyCache(await Actor.open_key_value_store(name=CACHE_STORE_NAME))
