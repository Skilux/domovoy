"""Per-profile state: content hashes, the diff against it, and the two named key-value stores."""

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from domovoy.dedup.keys import listing_key
from domovoy.models import Change, Flat, FlatState, ProfileState, PropertyIdMap

PROPERTY_IDS_STORE = "domovoy-property-ids"
PROFILE_STATE_STORE = "domovoy-profile-state"
PROPERTY_IDS_KEY = "ids"  # one key holds the whole map
# Price-relevant fields plus the structured fields the extraction reads (WP4 confirms the list).
HASHED_FIELDS = (
    "rent", "price_note", "description", "disposition", "area_m2", "floor", "elevator", "furnished",
)


class KeyValueStore(Protocol):
    """The part of an Apify named key-value store that dedup uses. Tests pass an in-memory fake."""

    async def get_value(self, key: str) -> Any: ...

    async def set_value(self, key: str, value: Any) -> None: ...


def content_hash(flat: Flat) -> str:
    """Hash of the hashed fields of every source, sorted by key. Timestamps are not hashed."""
    rows = [
        {"key": listing_key(source), **{name: getattr(source, name) for name in HASHED_FIELDS}}
        for source in flat.sources
    ]
    rows.sort(key=lambda row: row["key"])
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def diff(flats: list[Flat], state: ProfileState) -> list[tuple[Flat, Change]]:
    """Each flat as new (not in the state), changed (content hash moved) or unchanged."""
    result: list[tuple[Flat, Change]] = []
    for flat in flats:
        seen = state.flats.get(flat.property_id)
        change: Change
        if seen is None:
            change = "new"
        elif seen.content_hash != content_hash(flat):
            change = "changed"
        else:
            change = "unchanged"
        result.append((flat, change))
    return result


def record_run(state: ProfileState, flats: list[Flat], now: datetime) -> ProfileState:
    """The state after a run. Flats of this run get their hash and last_seen, and keep first_seen.
    Flats missing from this run keep their entries: nothing is deleted."""
    flat_states = dict(state.flats)
    for flat in flats:
        previous = flat_states.get(flat.property_id)
        flat_states[flat.property_id] = FlatState(
            content_hash=content_hash(flat),
            first_seen=previous.first_seen if previous is not None else now,
            last_seen=now,
        )
    return ProfileState(
        profile_id=state.profile_id, profile_hash=state.profile_hash, flats=flat_states
    )


async def load_property_ids(store: KeyValueStore) -> PropertyIdMap:
    value = await store.get_value(PROPERTY_IDS_KEY)
    return dict(value) if value else {}


async def save_property_ids(store: KeyValueStore, ids: PropertyIdMap) -> None:
    await store.set_value(PROPERTY_IDS_KEY, ids)


async def load_profile_state(store: KeyValueStore, profile_id: str) -> ProfileState:
    value = await store.get_value(profile_id)
    if value is None:
        return ProfileState(profile_id=profile_id, profile_hash=None)
    return ProfileState.model_validate(value)


async def save_profile_state(store: KeyValueStore, state: ProfileState) -> None:
    await store.set_value(state.profile_id, state.model_dump(mode="json"))
