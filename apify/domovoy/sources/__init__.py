"""Source registry: portal name -> Source. Empty in WP0; WP1-3 call register()."""

from domovoy.sources.base import Source
from domovoy.sources.sreality import SrealitySource

SOURCES: dict[str, Source] = {}


def register(source: Source) -> None:
    if source.name in SOURCES:
        raise ValueError(f"source already registered: {source.name}")
    SOURCES[source.name] = source


register(SrealitySource())
