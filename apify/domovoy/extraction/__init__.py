"""Extraction (WP4): Featherless Qwen, then OpenAI gpt-6-luna as the only fallback, quote check, cache.

Use extract(listing, cfg) for one listing, or Extractor(cfg, cache) for a whole run.
"""

from domovoy.extraction.cache import (
    ApifyCache,
    ExtractionCache,
    MemoryCache,
    cache_key,
    open_apify_cache,
)
from domovoy.extraction.extract import DEFAULT_MIN_CONFIDENCE, Extractor, extract
from domovoy.extraction.llm import DEFAULT_FALLBACK_MODEL, DEFAULT_MODEL
from domovoy.extraction.prompt import PROMPT_VERSION

__all__ = [
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_MODEL",
    "PROMPT_VERSION",
    "ApifyCache",
    "ExtractionCache",
    "Extractor",
    "MemoryCache",
    "cache_key",
    "extract",
    "open_apify_cache",
]
