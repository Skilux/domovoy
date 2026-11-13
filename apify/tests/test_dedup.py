"""WP6 dedup tests. Offline: an autouse fixture refuses every socket connect.

Listings are synthetic, built from the hand-made fixture listing_example.json.
"""

import json
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from domovoy.dedup import (
    PROFILE_STATE_STORE,
    PROPERTY_IDS_STORE,
    content_hash,
    cross_source,
    diff,
    load_profile_state,
    load_property_ids,
    merge,
    record_run,
    save_profile_state,
    save_property_ids,
)
from domovoy.dedup.keys import distance_m, new_property_id, normalize_street
from domovoy.models import PRAGUE, CrossSource, GeoPoint, Listing, ProfileState, PropertyIdMap

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROPERTY_ID = re.compile(r"^p-[A-Z2-7]{10}$")
PROFILE_ID = "vinohrady-2kk-30k"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=PRAGUE)
LATER = datetime(2026, 11, 13, 13, 0, tzinfo=PRAGUE)


def make(
    portal: str,
    source_id: str,
    *,
    street: str | None = "Mánesova",
    gps: tuple[float, float] | None = None,
    **fields: Any,
) -> Listing:
    """A listing from the fixture, with the street, GPS and fields under test overridden."""
    data = json.loads((FIXTURES / "listing_example.json").read_text(encoding="utf-8"))
    data.update(
        portal=portal, source_id=source_id, url=f"https://example.test/{portal}/{source_id}"
    )
    data["address_detail"] = {
        **data["address_detail"],
        "street": street,
        "gps": None if gps is None else {"lat": gps[0], "lon": gps[1]},
    }
    data.update(fields)
    return Listing.model_validate(data)


def agent(name: str) -> dict[str, Any]:
    return {
        "name": name, "agency": None, "ico": None, "email": None, "phone": None, "form_url": None,
    }


def empty_state() -> ProfileState:
    return ProfileState(profile_id=PROFILE_ID, profile_hash=None)


class MemoryStore:
    """In-memory key-value store. Values go through JSON, as they do on the Apify platform."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get_value(self, key: str) -> Any:
        return json.loads(json.dumps(self.values[key])) if key in self.values else None

    async def set_value(self, key: str, value: Any) -> None:
        self.values[key] = json.loads(json.dumps(value))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("dedup tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)


# Matching across portals


def test_same_flat_on_two_portals_is_one_flat():
    sreality = make("sreality", "1")
    bezrealitky = make("bezrealitky", "b-9", street="MANESOVA", rent=24500, area_m2=55.5)
    flats = merge([sreality, bezrealitky], {})
    assert len(flats) == 1
    assert [source.portal for source in flats[0].sources] == ["sreality", "bezrealitky"]


@pytest.mark.parametrize(
    ("rent", "area", "expected_flats"),
    [
        (24000, 54.0, 1),
        (24000, 57.0, 1),  # area +3 m2: the edge is inside
        (24000, 57.5, 2),  # area +3.5 m2: outside
        (25000, 54.0, 1),  # rent +4.2 %: inside
        (26000, 54.0, 2),  # rent +8.3 %: outside
    ],
)
def test_area_and_rent_tolerances(rent, area, expected_flats):
    listings = [make("sreality", "1"), make("bezrealitky", "b-9", rent=rent, area_m2=area)]
    assert len(merge(listings, {})) == expected_flats


def test_rent_tolerance_is_five_percent_of_the_higher_rent():
    inside = [make("sreality", "1", rent=20000), make("bezrealitky", "b-9", rent=19000)]
    outside = [make("sreality", "1", rent=19000), make("bezrealitky", "b-9", rent=18000)]
    assert len(merge(inside, {})) == 1
    assert len(merge(outside, {})) == 2


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"disposition": None}, {}),  # missing on one side
        ({"disposition": None}, {"disposition": None}),  # missing on both sides
        ({}, {"disposition": "2+1"}),  # different disposition
        ({"area_m2": None}, {}),
        ({"area_m2": None}, {"area_m2": None}),
        ({"rent": None}, {}),
        ({"rent": None}, {"rent": None}),
        ({"street": None}, {}),  # no street and no GPS on one side
        ({"street": None}, {"street": None}),  # no street and no GPS on either side
    ],
)
def test_a_missing_value_never_matches(first, second):
    listings = [make("sreality", "1", **first), make("bezrealitky", "b-9", **second)]
    assert len(merge(listings, {})) == 2


def test_different_streets_with_gps_within_150_m_are_one_flat():
    sreality = make("sreality", "1", street="Mánesova", gps=(50.07550, 14.43780))
    bezrealitky = make("bezrealitky", "b-9", street="Vinohradská", gps=(50.07570, 14.43800))
    assert len(merge([sreality, bezrealitky], {})) == 1


def test_gps_200_m_apart_with_different_streets_is_two_flats():
    sreality = make("sreality", "1", street="Mánesova", gps=(50.07550, 14.43780))
    bezrealitky = make("bezrealitky", "b-9", street="Vinohradská", gps=(50.07730, 14.43780))
    assert len(merge([sreality, bezrealitky], {})) == 2


def test_two_listings_on_one_portal_never_merge():
    assert len(merge([make("sreality", "1"), make("sreality", "2")], {})) == 2


def test_a_repeated_listing_counts_once():
    flats = merge([make("sreality", "1"), make("sreality", "1")], {})
    assert len(flats) == 1
    assert len(flats[0].sources) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mánesova", "manesova"),
        ("MÁNESOVA", "manesova"),
        ("ulice Mánesova", "manesova"),
        ("Ulice Mánesova č.p. 12", "manesova"),
        ("Vinohradská 1234/5", "vinohradska"),
        ("ul. Korunní", "korunni"),
        ("Dr. Janského 3a", "dr janskeho"),
        ("28. října", "28 rijna"),  # a number inside the name stays
        ("č.p. 5", None),
        ("", None),
        (None, None),
    ],
)
def test_street_normalization(raw, expected):
    assert normalize_street(raw) == expected


def test_distance_is_haversine_in_metres():
    origin = GeoPoint(lat=50.0, lon=14.4)
    assert distance_m(origin, origin) == 0
    assert 111.0 < distance_m(origin, GeoPoint(lat=50.001, lon=14.4)) < 111.4


# Stable property_id


def test_property_id_has_the_fixed_format_and_value():
    assert new_property_id("sreality:1000000001") == "p-Z32VKG2YTL"
    assert PROPERTY_ID.match(new_property_id("bezrealitky:b-9"))


def test_property_id_is_stable_across_runs_and_input_order():
    sreality = make("sreality", "1")
    bezrealitky = make("bezrealitky", "b-9", rent=24500)
    ids: PropertyIdMap = {}
    first = merge([sreality, bezrealitky], ids)
    saved = dict(ids)
    second = merge([bezrealitky, sreality], dict(saved))  # reversed input, map reloaded
    assert [flat.property_id for flat in first] == [flat.property_id for flat in second]
    assert first[0].property_id == new_property_id("sreality:1")
    assert saved == {
        "sreality:1": first[0].property_id,
        "bezrealitky:b-9": first[0].property_id,
    }


def test_a_duplicate_found_later_joins_the_existing_flat():
    ids: PropertyIdMap = {}
    only_sreality = merge([make("sreality", "1")], ids)
    both = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=24500)], ids)
    assert [flat.property_id for flat in both] == [only_sreality[0].property_id]
    assert ids["bezrealitky:b-9"] == only_sreality[0].property_id


def test_an_id_stays_with_one_flat_in_a_run():
    old = new_property_id("sreality:1")
    # The old run had both listings in one flat. Now the rent gap is too wide and they split.
    ids: PropertyIdMap = {"sreality:1": old, "bezrealitky:b-9": old}
    flats = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=30000)], ids)
    assert flats[0].property_id == old
    assert flats[1].property_id != old
    assert ids == {"sreality:1": old, "bezrealitky:b-9": flats[1].property_id}


def test_a_new_id_never_reuses_a_claimed_id():
    # A stale map gives sreality:1 the id that hashing "bezrealitky:b-9" would produce.
    stale = new_property_id("bezrealitky:b-9")
    ids: PropertyIdMap = {"sreality:1": stale}
    flats = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=30000)], ids)
    assert flats[0].property_id == stale
    assert flats[1].property_id != stale


# Merged fields and cross-source figures


def test_the_top_source_keeps_its_own_photos():
    listings = [
        make("sreality", "1", photos=["https://example.test/s.jpg"]),
        make("bezrealitky", "b-9", photos=["https://example.test/b.jpg"]),
    ]
    (flat,) = merge(listings, {})
    assert flat.primary.photos == ["https://example.test/s.jpg"]


def test_primary_is_the_top_source_with_gaps_filled_from_the_next():
    sreality = make("sreality", "1", price_note=None, photos=[], contact=agent("Agent A"))
    bezrealitky = make(
        "bezrealitky",
        "b-9",
        area_m2=55.5,
        price_note="Fees: services 2 000 CZK per month.",
        photos=["https://example.test/1.jpg"],
        contact=agent("Agent B"),
    )
    (flat,) = merge([bezrealitky, sreality], {})
    assert flat.primary.portal == "sreality"
    assert flat.primary.url == sreality.url
    assert flat.primary.area_m2 == 54.0  # the top source's value wins
    assert flat.primary.price_note == "Fees: services 2 000 CZK per month."
    assert flat.primary.photos == ["https://example.test/1.jpg"]
    assert flat.primary.contact == sreality.contact  # contact stays with its own source


def test_cross_source_gives_cheapest_portal_and_price_spread():
    (flat,) = merge([make("sreality", "1", rent=24000), make("bezrealitky", "b-9", rent=24500)], {})
    assert flat.cross_source == CrossSource(
        cheapest_portal="sreality", commission_savings=None, price_spread=500
    )


def test_cheapest_portal_tie_goes_to_the_higher_priority_portal():
    listings = [make("bezrealitky", "b-9", rent=24000), make("sreality", "1", rent=24000)]
    (flat,) = merge(listings, {})
    assert flat.cross_source.cheapest_portal == "sreality"
    assert flat.cross_source.price_spread == 0


def test_commission_savings_needs_a_commission_from_every_source():
    sources = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=24500)], {})[0].sources
    both = {"sreality:1": 0, "bezrealitky:b-9": 24000}
    assert cross_source(sources, both).commission_savings == 24000
    assert cross_source(sources, {"sreality:1": 0}).commission_savings is None
    assert cross_source(sources, None).commission_savings is None


def test_cross_source_is_unknown_when_a_rent_is_unknown():
    sources = [make("sreality", "1", rent=24000), make("bezrealitky", "b-9", rent=None)]
    assert cross_source(sources) == CrossSource(
        cheapest_portal=None, commission_savings=None, price_spread=None
    )


def test_a_single_source_has_no_cross_source_figures():
    (flat,) = merge([make("sreality", "1")], {})
    assert flat.cross_source == CrossSource(
        cheapest_portal=None, commission_savings=None, price_spread=None
    )


# Diff against the profile state


def test_diff_marks_new_then_unchanged_then_changed():
    ids: PropertyIdMap = {}
    flats = merge([make("sreality", "1")], ids)
    state = empty_state()
    assert [change for _, change in diff(flats, state)] == ["new"]

    state = record_run(state, flats, NOW)
    assert [change for _, change in diff(flats, state)] == ["unchanged"]

    moved = merge([make("sreality", "1", rent=24500)], dict(ids))
    assert [change for _, change in diff(moved, state)] == ["changed"]


@pytest.mark.parametrize(
    "fields",
    [
        {"rent": 24500},
        {"price_note": "Fees: 500 CZK per month."},
        {"description": "A new description."},
        {"furnished": "full"},
    ],
)
def test_a_changed_hashed_field_marks_the_flat_changed(fields):
    state = record_run(empty_state(), merge([make("sreality", "1")], {}), NOW)
    after = merge([make("sreality", "1", **fields)], {})
    assert [change for _, change in diff(after, state)] == ["changed"]


def test_a_new_collection_time_alone_leaves_the_flat_unchanged():
    state = record_run(empty_state(), merge([make("sreality", "1")], {}), NOW)
    later = merge([make("sreality", "1", collected_at="2026-11-13T13:00:00+01:00")], {})
    assert [change for _, change in diff(later, state)] == ["unchanged"]


def test_a_duplicate_found_later_marks_the_flat_changed():
    ids: PropertyIdMap = {}
    state = record_run(empty_state(), merge([make("sreality", "1")], ids), NOW)
    both = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=24500)], dict(ids))
    assert [change for _, change in diff(both, state)] == ["changed"]


def test_content_hash_ignores_source_order():
    flats = merge([make("sreality", "1"), make("bezrealitky", "b-9", rent=24500)], {})
    reversed_sources = flats[0].model_copy(update={"sources": list(reversed(flats[0].sources))})
    assert content_hash(reversed_sources) == content_hash(flats[0])


def test_record_run_keeps_first_seen_and_moves_last_seen():
    flats = merge([make("sreality", "1")], {})
    first = record_run(empty_state(), flats, NOW)
    second = record_run(first, flats, LATER)
    entry = second.flats[flats[0].property_id]
    assert (entry.first_seen, entry.last_seen) == (NOW, LATER)
    assert entry.content_hash == content_hash(flats[0])


def test_flats_missing_from_a_run_keep_their_state():
    kept = merge([make("sreality", "1")], {})
    gone = merge([make("sreality", "2", street="Dlouhá")], {})
    state = record_run(empty_state(), kept + gone, NOW)
    later = record_run(state, kept, LATER)
    assert set(later.flats) == {kept[0].property_id, gone[0].property_id}
    assert later.flats[gone[0].property_id].last_seen == NOW


# Storage through the injected key-value store


async def test_property_ids_round_trip_through_the_store():
    store = MemoryStore()
    assert await load_property_ids(store) == {}
    ids = {"sreality:1": new_property_id("sreality:1")}
    await save_property_ids(store, ids)
    assert await load_property_ids(store) == ids


async def test_profile_state_round_trips_and_defaults_when_missing():
    store = MemoryStore()
    assert await load_profile_state(store, PROFILE_ID) == empty_state()
    state = record_run(empty_state(), merge([make("sreality", "1")], {}), NOW)
    await save_profile_state(store, state)
    assert PROFILE_ID in store.values
    assert await load_profile_state(store, PROFILE_ID) == state


def test_named_stores_are_the_planned_ones():
    assert PROPERTY_IDS_STORE == "domovoy-property-ids"
    assert PROFILE_STATE_STORE == "domovoy-profile-state"
