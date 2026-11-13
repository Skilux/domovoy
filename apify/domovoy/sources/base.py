"""Source interface for WP1-3. A failing source is reported in the summary and never stops the run."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import Any, ClassVar, Protocol

import httpx

from domovoy.models import Listing, Portal, SearchProfile


class SourceError(Exception):
    """One source failed. The run goes on and the summary says so."""


@dataclass(frozen=True)
class SourceContext:
    http: httpx.AsyncClient  # plain HTTP, built with trust_env=False (no environment proxies)
    log: Logger  # Actor.log in a real run
    max_listings: int
    delay_sec: float = 0.5  # 0.5-1 s between requests to one portal
    browser_factory: Callable[[], Awaitable[Any]] | None = None  # placeholder, always None in WP0
    proxy_configuration: None = None  # always None; enabling proxies is a team decision


class Source(Protocol):
    name: ClassVar[Portal]

    def collect(self, profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
        """Implemented as an async generator: async def with yield."""
        ...

    def normalize(self, raw: dict[str, Any], collected_at: datetime) -> Listing:
        """Pure: one raw portal payload to a Listing. Tested on fixtures."""
        ...
