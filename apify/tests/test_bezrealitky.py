"""Bezrealitky source tests (WP2).

Offline by default: an autouse fixture refuses socket connects, and the end-to-end tests run the real
collect() against an httpx.MockTransport that serves the fixtures. The live smoke test needs
DOMOVOY_LIVE=1 and -m live.
"""

import json
import os
import socket
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import Any

import httpx
import pytest

from domovoy.models import PRAGUE, Listing, SearchProfile
from domovoy.profile import load_profile
from domovoy.sources import SOURCES
from domovoy.sources import bezrealitky as bz
from domovoy.sources.base import SourceContext, SourceError

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "bezrealitky"
PROFILE_PATH = TESTS / "fixtures" / "profile_vinohrady.json"
COLLECTED_AT = datetime(2026, 11, 13, 13, 0, tzinfo=PRAGUE)
LOG = getLogger("test-bezrealitky")
REGISTERED_AT_IMPORT = SOURCES.get("bezrealitky")  # test_foundation clears the registry during its tests
BUILD_ID = "fixture-build"
DETAIL_FIXTURES = {"686144": "detail_686144.json", "932647": "detail_932647.json", "1089140": "detail_1089140.json"}
# Vinohrady list adverts that pass the demo profile at list level (2+kk or 2+1, rent <= 30000, area >= 45).
VINOHRADY_CANDIDATES = ["686144", "1088787", "936312", "222297", "1082825", "795353", "620170", "1086538"]


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _profile(**filters: Any) -> SearchProfile:
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    data["filters"].update(filters)
    return load_profile(data)


@pytest.fixture(autouse=True)
def offline(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def refuse(*_args, **_kwargs):
        raise AssertionError("offline bezrealitky test opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def fast(monkeypatch):
    """No pacing or retry sleeps in the offline end-to-end tests."""
    monkeypatch.setattr(bz, "MIN_GAP_SEC", 0.0)
    monkeypatch.setattr(bz, "RETRY_SLEEP_SEC", 0.0)
    monkeypatch.setattr(bz, "RATE_LIMITED_SLEEP_SEC", 0.0)


# Rules and fixtures


def test_source_is_registered_at_import():
    assert bz.SOURCE.name == "bezrealitky"
    assert REGISTERED_AT_IMPORT is bz.SOURCE


def test_pacing_and_concurrency_follow_the_team_rules():
    assert bz.MIN_GAP_SEC >= 0.5
    assert bz.MAX_CONCURRENCY == 3


def test_list_fixtures_are_two_pages_of_fifteen_from_one_region():
    pages = [bz.parse_list_page(_load(name)) for name in ("list_vinohrady_page1.json", "list_vinohrady_page2.json")]
    assert [page.total for page in pages] == [71, 71]
    assert [len(page.adverts) for page in pages] == [15, 15]
    first, second = ({str(advert["id"]) for advert in page.adverts} for page in pages)
    assert len(first) == 15 and len(second) == 15
    assert not first & second


def test_list_filters_keep_the_expected_vinohrady_adverts():
    profile = _profile()
    citypart = bz.build_plan(profile)[0].citypart
    kept = []
    for name in ("list_vinohrady_page1.json", "list_vinohrady_page2.json"):
        for advert in bz.parse_list_page(_load(name)).adverts:
            cand = bz.candidate_from_advert(advert, citypart=citypart)
            if bz.passes_filters(
                profile,
                disposition=cand.disposition,
                rent=cand.rent,
                area_m2=cand.area_m2,
                quarter=cand.quarter,
                citypart=cand.citypart,
            ):
                kept.append(cand.advert_id)
    assert kept == VINOHRADY_CANDIDATES


def test_plan_maps_vinohrady_to_its_region_and_rejects_other_cities():
    assert bz.build_plan(_profile()) == [bz.Plan(region=bz.VINOHRADY, citypart="Vinohrady")]
    with pytest.raises(SourceError, match="city not supported"):
        bz.build_plan(_profile(locations=[{"city": "Brno", "citypart": None}]))


def test_unknown_or_zero_values_become_none_not_zero():
    advert = {
        "id": 1,
        "uri": "1-x",
        "disposition": "DISP_2_KK",
        "price": 0,
        "surface": 0,
        'address({"locale":"CS"})': "X, Praha - Vinohrady",
    }
    cand = bz.candidate_from_advert(advert, citypart="Vinohrady")
    assert cand.rent is None and cand.area_m2 is None
    assert cand.quarter == "Vinohrady"


# Normalize (pure, on the fixtures)


def test_normalize_686144_maps_the_detail_fields():
    listing = bz.normalize_detail(_load("detail_686144.json"), COLLECTED_AT)
    assert isinstance(listing, Listing)
    assert listing.portal == "bezrealitky"
    assert listing.source_id == "686144"
    assert listing.url == (
        "https://www.bezrealitky.cz/nemovitosti-byty-domy/686144-nabidka-pronajem-bytu-na-folimance-hlavni-mesto-praha"
    )
    assert listing.title == "Pronájem bytu 2+kk • 63\xa0m² • Na Folimance • Praha - Vinohrady • bez RK"  # as published
    assert listing.address == "Na Folimance, Praha - Vinohrady"
    detail = listing.address_detail
    assert (detail.street, detail.house_number, detail.citypart, detail.district, detail.precision) == (
        "Na Folimance", None, "Vinohrady", "Praha", "street",
    )
    assert detail.gps.lat == pytest.approx(50.06615) and detail.gps.lon == pytest.approx(14.43427)
    assert (listing.disposition, listing.area_m2, listing.floor, listing.elevator, listing.furnished) == (
        "2+kk", 63.0, 5, True, "none",
    )
    assert listing.rent == 25000
    assert listing.price_note is None
    assert listing.ready_date == "2026-12-01"
    assert listing.ownership == "OSOBNI"
    assert listing.is_owner_listing is True
    assert len(listing.photos) == 9
    assert all(photo.startswith("https://api.bezrealitky.cz/media/cache/") for photo in listing.photos)
    assert listing.poi is None and listing.raw_ref is None
    assert listing.contact.name == "<name>" and listing.contact.form_url is None


def test_normalize_932647_is_outside_the_profile_on_disposition():
    listing = bz.normalize_detail(_load("detail_932647.json"), COLLECTED_AT)
    assert (listing.disposition, listing.area_m2, listing.furnished, listing.ready_date) == (
        "3+1", 72.0, "full", "2027-02-15",
    )
    assert listing.ownership is None
    assert len(listing.photos) == 20
    assert not bz.passes_filters(
        _profile(),
        disposition=listing.disposition,
        rent=listing.rent,
        area_m2=listing.area_m2,
        quarter=listing.address_detail.citypart,
        citypart="Vinohrady",
    )


def test_normalize_1089140_keeps_the_price_note_and_the_quarter():
    listing = bz.normalize_detail(_load("detail_1089140.json"), COLLECTED_AT)
    assert listing.disposition is None  # UNDEFINED, and the JSON-LD name carries no label
    assert listing.address_detail.citypart == "Žižkov"
    assert listing.price_note.startswith("Nájemné i poplatky platí pro pronájem na 12 měsíců")
    assert listing.contact.name == "<name>" and listing.contact.form_url == "<form-url>"
    assert (listing.furnished, listing.elevator, listing.rent) == ("full", True, 31570)
    assert not bz.passes_filters(
        _profile(),
        disposition=None,
        rent=listing.rent,
        area_m2=listing.area_m2,
        quarter=listing.address_detail.citypart,
        citypart="Vinohrady",
    )


@pytest.mark.parametrize("name", ["detail_686144.json", "detail_932647.json", "detail_1089140.json"])
def test_phone_and_email_are_never_taken_from_the_page(name):
    listing = bz.normalize_detail(_load(name), COLLECTED_AT)
    assert listing.contact is not None
    assert listing.contact.phone is None and listing.contact.email is None


@pytest.mark.parametrize("name", ["detail_686144.json", "detail_932647.json", "detail_1089140.json"])
def test_normalized_listings_satisfy_the_contract(name):
    listing = bz.normalize_detail(_load(name), COLLECTED_AT)
    assert listing.is_owner_listing is True  # team default, see the research note, section 8
    assert listing.collected_at.utcoffset().total_seconds() == 3600
    assert Listing.model_validate(listing.model_dump(mode="json")) == listing


def test_normalize_handles_missing_optional_fields():
    raw = {
        "advert": {
            "id": 9,
            "uri": "9-x",
            "address": "X, Praha - Vinohrady",
            "price": 20000,
            "surface": 40,
            "disposition": "UNDEFINED",
            "publicImages": [],
            "tags": [],
        },
        "jsonld": None,
        "source_url": None,
    }
    listing = bz.SOURCE.normalize(raw, COLLECTED_AT)
    assert listing.url == f"{bz.DETAIL_PREFIX}9-x"
    assert listing.title == "X, Praha - Vinohrady"
    assert listing.disposition is None and listing.photos == [] and listing.contact is None


# End-to-end collect() against the fixtures, through a mock transport


def _list_page_html(page: dict[str, Any]) -> str:
    payload = {"buildId": BUILD_ID, "props": {"pageProps": page["pageProps"]}}
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></head><body></body></html>"
    )


def _detail_html(name: str) -> str:
    raw = _load(name)
    payload = {"props": {"pageProps": {"origAdvert": raw["advert"]}}}
    jsonld = {"@graph": [raw["jsonld"]]}
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script>"
        f'<script type="application/ld+json">{json.dumps(jsonld)}</script></head><body></body></html>'
    )


class _Site:
    """Serves the fixtures the way the portal does, and records every request URL."""

    def __init__(self, *, detail_ok=("686144",), page1_status=200, json_page2_status=200):
        self.requests: list[str] = []
        self.detail_ok = set(detail_ok)
        self.page1_status = page1_status
        self.json_page2_status = json_page2_status
        self.page1 = _load("list_vinohrady_page1.json")
        self.page2 = _load("list_vinohrady_page2.json")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        path = request.url.path
        if path == "/vypis/nabidka-pronajem/byt/praha-vinohrady":
            if self.page1_status != 200:
                return httpx.Response(self.page1_status)
            return httpx.Response(200, text=_list_page_html(self.page1))
        if path == f"/_next/data/{BUILD_ID}/cs/vyhledat.json":
            if request.url.params.get("page") == "2":
                if self.json_page2_status != 200:
                    return httpx.Response(self.json_page2_status)
                return httpx.Response(200, json=self.page2)
            return httpx.Response(404)
        if path.startswith("/nemovitosti-byty-domy/"):
            advert_id = path.rsplit("/", 1)[-1].split("-", 1)[0]
            if advert_id in self.detail_ok and advert_id in DETAIL_FIXTURES:
                return httpx.Response(200, text=_detail_html(DETAIL_FIXTURES[advert_id]))
        return httpx.Response(404)


async def _collect(site: _Site, max_listings: int) -> list[Listing]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(site), trust_env=False) as http:
        ctx = SourceContext(http=http, log=LOG, max_listings=max_listings, delay_sec=0.0)
        return [listing async for listing in bz.SOURCE.collect(_profile(), ctx)]


async def test_collect_yields_the_first_good_listing(fast):
    site = _Site(detail_ok=("686144",))
    listings = await _collect(site, max_listings=1)
    assert [listing.source_id for listing in listings] == ["686144"]
    assert site.requests[0].endswith("/vypis/nabidka-pronajem/byt/praha-vinohrady")
    assert not any("page=2" in url for url in site.requests)  # one match on page 1 is enough


async def test_collect_skips_failed_details_and_keeps_going(fast):
    site = _Site(detail_ok=("686144",))
    listings = await _collect(site, max_listings=2)
    assert [listing.source_id for listing in listings] == ["686144"]


async def test_collect_raises_when_every_detail_fails(fast):
    site = _Site(detail_ok=())
    with pytest.raises(SourceError, match="every detail request failed"):
        await _collect(site, max_listings=2)


async def test_failing_second_page_keeps_the_first_page_candidates(fast):
    site = _Site(detail_ok=("686144",), json_page2_status=500)
    listings = await _collect(site, max_listings=20)
    assert [listing.source_id for listing in listings] == ["686144"]
    json_requests = [url for url in site.requests if "vyhledat.json" in url]
    assert len(json_requests) == 2  # the page-2 request and its one retry
    assert all("regionOsmIds=R428841" in url and "page=2" in url for url in json_requests)


async def test_failing_first_list_page_fails_the_source(fast):
    site = _Site(page1_status=500)
    with pytest.raises(SourceError, match="request failed"):
        await _collect(site, max_listings=5)


# Live smoke (needs DOMOVOY_LIVE=1 and -m live)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("DOMOVOY_LIVE") != "1", reason="live smoke: set DOMOVOY_LIVE=1")
async def test_live_vinohrady_smoke():
    async with httpx.AsyncClient(trust_env=False) as http:
        ctx = SourceContext(http=http, log=LOG, max_listings=5, delay_sec=0.5)
        listings = [listing async for listing in bz.SOURCE.collect(_profile(), ctx)]
    with_photos = sum(1 for listing in listings if listing.photos)
    with_contact = sum(1 for listing in listings if listing.contact and listing.contact.name)
    print(f"\nlive bezrealitky: {len(listings)} listings, {with_photos} with photos, {with_contact} with contact name")
    for listing in listings:
        print(
            f"  {listing.source_id} {listing.disposition} rent={listing.rent} area={listing.area_m2} "
            f"quarter={listing.address_detail.citypart} photos={len(listing.photos)} owner={listing.is_owner_listing}"
        )
    assert len(listings) >= 5
    assert all(listing.is_owner_listing is True for listing in listings)
    assert all(listing.url.startswith(bz.DETAIL_PREFIX) for listing in listings)
