"""Sreality source tests.

Offline (default): normalize on the scrubbed fixtures in tests/fixtures/sreality/, the search
pre-filter, the search URL, failure handling, and collect() end to end on an httpx.MockTransport.
Live (-m live): the real v1 JSON API at polite pacing, with the Vinohrady profile.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from domovoy.models import SearchProfile
from domovoy.sources.base import SourceContext, SourceError
from domovoy.sources.sreality import (
    API_BASE,
    SrealitySource,
    _accepts_search_item,
    _get_json,
    _make_plan,
    _Pacer,
    normalize_listing,
)

FIXTURES = Path(__file__).parent / "fixtures"
SREALITY = FIXTURES / "sreality"
PRAGUE = ZoneInfo("Europe/Prague")
COLLECTED_AT = datetime(2026, 11, 13, 13, 0, tzinfo=PRAGUE)
LOG = logging.getLogger("test_sreality")

S1 = 1032417356  # Vinohrady, 2+kk, 40 m2
S2 = 270794828  # Nusle, 2+1, 75 m2 (placeholders for elevator and furnished)
S3 = 552337484  # Nové Město, 2+kk, 74 m2 (a commercial office in the flat category)


def _load(name: str) -> dict:
    return json.loads((SREALITY / name).read_text(encoding="utf-8"))


def _search_items() -> dict[int, dict]:
    items: dict[int, dict] = {}
    for name in ("search_praha2_page1.json", "search_praha2_page2.json"):
        for item in _load(name)["results"]:
            items[item["hash_id"]] = item
    return items


def _detail(hid: int) -> dict:
    return _load(f"detail_{hid}.json")["result"]


def _raw(hid: int) -> dict:
    return {"detail": copy.deepcopy(_detail(hid)), "search": copy.deepcopy(_search_items().get(hid, {}))}


def _profile(**filter_overrides) -> SearchProfile:
    data = json.loads((FIXTURES / "profile_vinohrady.json").read_text(encoding="utf-8"))
    data["filters"].update(filter_overrides)
    return SearchProfile.model_validate(data)


# --- normalize: offline, pure, on the fixtures ---


def test_normalize_vinohrady_listing_maps_the_detail_fields():
    listing = normalize_listing(_raw(S1), COLLECTED_AT)
    assert listing.portal == "sreality"
    assert listing.source_id == str(S1)
    assert listing.url == f"https://www.sreality.cz/detail/pronajem/byt/2+kk/praha-vinohrady-na-kozacce/{S1}"
    assert listing.title == "Pronájem bytu 2+kk 40 m²"  # the title as listed, with a non-breaking space
    assert listing.disposition == "2+kk"
    assert listing.area_m2 == 40.0
    assert listing.floor == 0
    assert listing.elevator is True
    assert listing.furnished == "full"
    assert listing.rent == 25000 and isinstance(listing.rent, int)
    assert listing.ownership == "Osobní"
    assert listing.ready_date == "2026-11-10"
    assert listing.price_note and "Kauce" in listing.price_note
    assert listing.description and "@" not in listing.description
    assert listing.address == "Na Kozačce, Vinohrady, Praha 2"
    assert listing.address_detail.citypart == "Vinohrady"
    assert listing.address_detail.district == "Praha 2"
    assert listing.address_detail.precision == "street"
    assert listing.address_detail.gps is not None
    assert listing.is_owner_listing is None and listing.raw_ref is None
    assert listing.collected_at.utcoffset() == COLLECTED_AT.utcoffset()
    assert listing.photos and all(url.startswith("https://") for url in listing.photos)
    assert listing.contact is not None
    assert listing.contact.name == "Example Agent"
    assert listing.contact.agency == "Example Agency"
    assert listing.contact.email is None and listing.contact.phone is None


def test_normalize_maps_poi_distances_from_the_search_item():
    listing = normalize_listing(_raw(S1), COLLECTED_AT)
    search = _search_items()[S1]
    assert listing.poi is not None
    assert listing.poi.metro_m == search["poi_metro_distance"]
    assert listing.poi.shop_m == search["poi_shop_distance"]
    assert listing.poi.tram_m is None  # the API has no tram distance


def test_normalize_placeholder_codes_become_unknown():
    listing = normalize_listing(_raw(S2), COLLECTED_AT)
    assert listing.elevator is None  # "- nezadáno", value 0
    assert listing.furnished is None  # "- vyber vybavení", value 0
    assert listing.address_detail.citypart == "Nusle"
    assert listing.address_detail.precision == "exact"  # inaccuracy_type "address"
    assert listing.disposition == "2+1"
    assert listing.rent == 28000
    assert listing.area_m2 == 75.0
    assert listing.floor == 2
    assert listing.url.startswith("https://www.sreality.cz/detail/pronajem/byt/2+1/praha-nusle-")
    assert listing.url.endswith(f"/{S2}")


def test_normalize_second_sample_reads_no_and_a_commercial_listing_as_is():
    listing = normalize_listing(_raw(S3), COLLECTED_AT)
    assert listing.furnished == "none"  # "Ne"
    assert listing.elevator is True
    assert listing.address_detail.citypart == "Nové Město"
    assert listing.address_detail.precision == "street"
    assert listing.rent == 60000


def test_rent_needs_a_monthly_price_unit():
    raw = _raw(S1)
    raw["detail"]["price_unit_cb"] = {"name": "za týden", "value": 1}
    assert normalize_listing(raw, COLLECTED_AT).rent is None


def test_contact_fields_map_from_user_and_premise():
    raw = _raw(S1)
    raw["detail"]["user"] = {
        "user_name": "Test Person",
        "user_email": "agent@example.invalid",
        "user_phones": [{"phone": "+420 000 000 000", "phone_type": "mobile"}],
    }
    raw["detail"]["premise"] = {"name": "Test Agency", "company": {"company_ic": 12345678}}
    contact = normalize_listing(raw, COLLECTED_AT).contact
    assert contact is not None
    assert (contact.name, contact.agency, contact.ico, contact.email, contact.phone) == (
        "Test Person",
        "Test Agency",
        "12345678",
        "agent@example.invalid",
        "+420 000 000 000",
    )


def test_normalize_rejects_a_payload_without_hash_id():
    with pytest.raises(ValueError, match="hash_id"):
        normalize_listing({"detail": {"advert_name": "x"}, "search": {}}, COLLECTED_AT)


def test_normalize_does_not_change_its_input():
    raw = _raw(S1)
    before = copy.deepcopy(raw)
    normalize_listing(raw, COLLECTED_AT)
    assert raw == before


# --- search: pre-filter, URL, unsupported profiles ---


def test_pre_filter_keeps_vinohrady_within_budget_and_area():
    plan = _make_plan(_profile(), LOG)
    accepted = {hid for hid, item in _search_items().items() if _accepts_search_item(item, plan)}
    assert accepted == {2178154572, 1399586892, 3042771020}


def test_search_url_carries_districts_dispositions_and_price_cap():
    plan = _make_plan(_profile(), LOG)
    assert plan.search_url(0) == (
        f"{API_BASE}/search?category_main_cb=1&category_type_cb=2&category_sub_cb=4,5"
        "&locality_district_id=5002,5003,5010&price_to=30000&limit=100&offset=0"
    )


def test_unsupported_location_or_disposition_raises():
    with pytest.raises(SourceError, match="location"):
        _make_plan(_profile(locations=[{"city": "Praha", "citypart": "Žižkov"}]), LOG)
    with pytest.raises(SourceError, match="disposition"):
        _make_plan(_profile(dispositions=["3+kk"]), LOG)


# --- collect: offline, end to end on a mock transport ---


class _Mock:
    """Serves the saved list payloads and detail payloads, and records every request.

    The collector pages by the number of results it got (8 here), so offset 8 serves page 2.
    """

    def __init__(self, details: dict[int, dict], redirect: frozenset[int] = frozenset()) -> None:
        self.lists = {0: _load("search_praha2_page1.json"), 8: _load("search_praha2_page2.json")}
        self.details = details
        self.redirect = redirect
        self.requests: list[tuple[float, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((time.monotonic(), str(request.url)))
        path = request.url.path
        if path.endswith("/estates/search"):
            offset = int(request.url.params.get("offset", "0"))
            if offset in self.lists:
                return httpx.Response(200, json=self.lists[offset])
            return httpx.Response(200, json={"results": [], "pagination": {"total": 132, "offset": offset, "limit": 100}})
        hid = int(path.rsplit("/", 1)[-1])
        if hid in self.redirect:
            return httpx.Response(302, headers={"location": "https://login.example.invalid/"})
        if hid in self.details:
            return httpx.Response(200, json={"result": self.details[hid], "status_code": 200, "status_message": "OK"})
        return httpx.Response(404, json={"status_code": 404, "status_message": "not found"})


async def test_collect_yields_matching_listings_and_counts_failures_without_stopping():
    mock = _Mock({S1: _detail(S1)}, redirect=frozenset({3852103756}))
    source = SrealitySource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock), trust_env=False) as http:
        ctx = SourceContext(http=http, log=LOG, max_listings=5, delay_sec=0.5)
        listings = [listing async for listing in source.collect(_profile(min_area_m2=30), ctx)]

    assert [listing.source_id for listing in listings] == [str(S1)]
    stats = source.last_stats
    assert stats.candidates == 7
    assert stats.fetched == 1
    assert stats.failed == stats.candidates - 1  # the 302 and the 404s are counted, the run goes on

    urls = [url for _, url in mock.requests]
    first_search = next(url for url in urls if "/estates/search" in url)
    assert "category_sub_cb=4,5" in first_search and "locality_district_id=5002,5003,5010" in first_search
    times = sorted(t for t, _ in mock.requests)
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    assert min(gaps) >= 0.45  # polite pacing between request starts


async def test_collect_raises_when_the_first_search_page_fails():
    source = SrealitySource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)), trust_env=False) as http:
        ctx = SourceContext(http=http, log=LOG, max_listings=5, delay_sec=0.5)
        with pytest.raises(SourceError, match="HTTP 404"):
            _ = [listing async for listing in source.collect(_profile(), ctx)]


# --- live: real API, polite pacing (python -m pytest -m live -s) ---


@pytest.fixture
def live_guard(request):
    """Live tests run only when selected with -m live; a plain pytest run skips them."""
    if "live" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("live test: select it with -m live")


@pytest.mark.live
async def test_live_price_to_limits_the_search_results(live_guard):
    plan = _make_plan(_profile(), LOG)
    async with httpx.AsyncClient(trust_env=False) as http:
        payload = await _get_json(http, _Pacer(0.5), plan.search_url(0))
    prices = [item["price_czk"] for item in payload["results"] if isinstance(item.get("price_czk"), (int, float))]
    print(f"\nLIVE price_to: results={len(payload['results'])} priced={len(prices)} max_price={max(prices) if prices else None}")
    assert prices and max(prices) <= 30000


@pytest.mark.live
async def test_live_vinohrady_profile_yields_listings_across_three_districts(live_guard):
    profile = SearchProfile.model_validate(json.loads((FIXTURES / "profile_vinohrady.json").read_text(encoding="utf-8")))
    source = SrealitySource()
    async with httpx.AsyncClient(trust_env=False) as http:
        ctx = SourceContext(http=http, log=LOG, max_listings=15, delay_sec=0.5)
        listings = [listing async for listing in source.collect(profile, ctx)]

    by_district = Counter(listing.address_detail.district for listing in listings)
    with_photos = sum(1 for listing in listings if listing.photos)
    with_contact = sum(1 for listing in listings if listing.contact is not None)
    print(
        f"\nLIVE sreality: listings={len(listings)} by_district={dict(by_district)} "
        f"with_photos={with_photos} with_contact={with_contact} stats={source.last_stats}"
    )
    assert len(listings) >= 10
    assert {listing.address_detail.citypart for listing in listings} == {"Vinohrady"}
    assert set(by_district) == {"Praha 2", "Praha 3", "Praha 10"}
    assert with_photos == len(listings)
    # Observed on 13 Nov: 14 of 15 carried contact fields. The one without had no name, email, phone or agency.
    assert with_contact >= 0.9 * len(listings)
    assert all(listing.rent is None or listing.rent <= 30000 for listing in listings)
    assert all(listing.area_m2 is None or listing.area_m2 >= 45 for listing in listings)
