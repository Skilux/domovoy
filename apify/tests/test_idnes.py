"""iDNES source (WP3). Offline by default; the live smoke test runs only with `-m live`.

The offline tests use scrubbed fixtures (tests/fixtures/idnes) and an httpx.MockTransport that
serves them. No socket is opened.
"""

import json
import re
import socket
import time
from dataclasses import asdict
from datetime import date, datetime
from logging import getLogger
from pathlib import Path

import httpx
import pytest

from domovoy.models import PRAGUE, Listing
from domovoy.profile import load_profile
from domovoy.sources import idnes as idnes_module
from domovoy.sources.base import SourceContext, SourceError
from domovoy.sources.idnes import (
    CITYPART_DISTRICTS,
    DISTRICT_CODES,
    IdnesSource,
    ListCard,
    SearchQuery,
    _czk,
    _floor,
    _furnished,
    _iso_date,
    _split_address,
    build_queries,
    card_matches,
    normalize_raw,
    parse_detail,
    parse_list,
)

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "idnes"
PROFILE_JSON = TESTS / "fixtures" / "profile_vinohrady.json"
LOG = getLogger("test-idnes")
NOW = datetime(2026, 11, 13, 13, 30, tzinfo=PRAGUE)

KORUNNI = "6ad5ce02475d52a1040d8535"  # Praha 2, Vinohrady, 56 m2, 30 000 CZK
VRATISLAVOVA = "03c2be"  # suffix: Praha 2, Vyšehrad (wrong citypart)
ZVONARKY = "0e13b9"  # suffix: Praha 2, Vinohrady, 35 000 CZK (over max_rent)
PISECKA = "6ae1eb246b7c43e2ec04de6c"  # Praha 3, Vinohrady, 55 m2, 25 000 CZK
HORNI = "6ad889ce0749c654dc06c50d"  # Praha 3, Vinohrady, 43 m2 (under min_area)
ONDRICKOVA = "059769"  # suffix: Praha 3, Žižkov (wrong citypart)
DETAIL_FILES = {
    KORUNNI: "detail_praha-2_korunni.html",
    PISECKA: "detail_praha-3_pisecka.html",
    HORNI: "detail_praha-3_horni-stromce.html",
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?420[  ]?)?\d{3}[  ]?\d{3}[  ]?\d{3}(?!\d)")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def profile(**filters):
    data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    data["filters"].update(filters)
    return load_profile(data)


def cards_by_suffix() -> dict[str, ListCard]:
    cards = parse_list(fixture("list_praha-2_2kk_p1.html")) + parse_list(fixture("list_praha-3_2kk_p2.html"))
    return {card.source_id: card for card in cards}


def raw_for(source_id: str) -> dict:
    card = cards_by_suffix()[source_id]
    return {"card": asdict(card), "detail": parse_detail(fixture(DETAIL_FILES[source_id]))}


def listing_for(source_id: str) -> Listing:
    return normalize_raw(raw_for(source_id), NOW)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def refuse(*_args, **_kwargs):
        raise AssertionError("offline iDNES test opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)


# Search pages and filters


def test_list_pages_yield_real_cards_and_skip_advertisement_slots():
    cards = parse_list(fixture("list_praha-2_2kk_p1.html"))
    assert [card.source_id for card in cards][0] == KORUNNI
    assert len(cards) == 3  # the advertisement slot has no listing link
    first = cards[0]
    assert first.url == f"https://reality.idnes.cz/detail/pronajem/byt/praha-2-korunni/{KORUNNI}/"
    assert first.title == "Pronájem bytu 2+kk 56 m², Korunní, Praha 2 - Vinohrady"
    assert first.address == "Korunní, Praha 2 - Vinohrady"
    assert first.price_text == "30 000 Kč/měsíc"
    assert len(parse_list(fixture("list_praha-3_2kk_p2.html"))) == 3


def _by_suffix(suffix: str) -> ListCard:
    return next(card for sid, card in cards_by_suffix().items() if sid.endswith(suffix))


def test_card_filters_apply_citypart_disposition_rent_and_area():
    wanted = SearchQuery("praha-2", "2+kk", "Vinohrady")
    cards = cards_by_suffix()
    passing = {sid for sid, card in cards.items() if card_matches(card, wanted, profile())}
    assert passing == {KORUNNI, PISECKA}
    for suffix, reason in [
        (VRATISLAVOVA, "citypart Vyšehrad"),
        (ZVONARKY, "rent 35 000 over max_rent"),
        (HORNI, "43 m2 under min_area_m2"),
        (ONDRICKOVA, "citypart Žižkov"),
    ]:
        assert not card_matches(_by_suffix(suffix), wanted, profile()), reason


def test_build_queries_covers_each_district_and_disposition():
    queries = build_queries(profile(), LOG)
    assert [(q.district, q.disposition) for q in queries] == [
        ("praha-2", "2+kk"), ("praha-2", "2+1"),
        ("praha-3", "2+kk"), ("praha-3", "2+1"),
        ("praha-10", "2+kk"), ("praha-10", "2+1"),
    ]
    assert queries[0].url(1) == "https://reality.idnes.cz/s/pronajem/byty/2+kk/praha-2/"
    assert queries[0].url(2) == "https://reality.idnes.cz/s/pronajem/byty/2+kk/praha-2/?page=2"


def test_six_plus_kk_uses_the_larger_flats_segment_and_unknown_dispositions_are_skipped():
    queries = build_queries(profile(dispositions=["6+kk", "7+kk"]), LOG)
    assert [q.url(1) for q in queries][0] == "https://reality.idnes.cz/s/pronajem/byty/6+kk-a-vetsi/praha-2/"
    assert all(q.disposition == "6+kk" for q in queries)


def test_region_tables_match_the_observed_locality_codes():
    assert CITYPART_DISTRICTS["Vinohrady"] == ("praha-2", "praha-3", "praha-10")
    assert {DISTRICT_CODES[d] for d in ("praha-2", "praha-3", "praha-10")} == {"MOP-27", "MOP-35", "MOP-108"}


# Detail pages and normalize (offline, fixtures)


def test_korunni_normalizes_every_field_from_the_fixture():
    listing = listing_for(KORUNNI)
    assert listing.portal == "idnes"
    assert listing.source_id == KORUNNI
    assert listing.url == f"https://reality.idnes.cz/detail/pronajem/byt/praha-2-korunni/{KORUNNI}/"
    assert listing.title == "Pronájem bytu 2+kk 56 m²"
    assert listing.address == "Korunní, Praha 2 - Vinohrady"
    assert listing.disposition == "2+kk"
    assert listing.area_m2 == 56.0
    assert listing.floor == 3
    assert listing.elevator is True
    assert listing.furnished == "full"  # from the headline "zařízeného"; no parameter row
    assert listing.rent == 30000 and type(listing.rent) is int
    assert listing.price_note == "+ poplatky na služby a energie 6.000 Kč"
    assert listing.ready_date == "2027-01-02"
    assert listing.ownership == "personal"
    assert listing.is_owner_listing is False  # the page offers it through a real-estate agency
    assert listing.poi is None and listing.raw_ref is None
    assert "zařízený" in listing.description
    detail = listing.address_detail
    assert (detail.street, detail.house_number, detail.district, detail.citypart) == (
        "Korunní", None, "Praha 2", "Vinohrady",
    )
    assert detail.precision == "street"
    assert detail.gps is not None
    assert round(detail.gps.lat, 4) == 50.0754 and round(detail.gps.lon, 4) == 14.4557
    assert len(listing.photos) == 12
    assert listing.photos[0].startswith("https://sta-reality2.1gr.cz/sta/compile/thumbs/")


def test_contact_fields_are_placeholders_in_the_fixture_and_not_contact_values():
    contact = listing_for(KORUNNI).contact
    assert contact is not None
    assert contact.name == "<name>" and contact.agency == "<agency>"
    assert contact.ico is None
    assert contact.email is None  # the fixture carries the placeholder "<email>": not an address
    assert contact.phone is None  # the fixture carries the placeholder "<phone>": not a number
    assert contact.form_url == listing_for(KORUNNI).url


def test_horni_stromce_takes_furnishing_rent_and_area_from_the_parameter_rows():
    listing = listing_for(HORNI)
    assert listing.furnished == "partial"  # "Vybavení: částečně zařízený"
    assert listing.rent == 24500  # "Cena": the new price; the header also shows the old 25 000
    assert listing.area_m2 == 43.0  # "Užitná plocha"; the og:title says 44 m2 and is not used
    assert listing.price_note == "bez poplatků, + provize RK, včetně právního servisu"
    assert listing.ready_date == "2026-09-26"
    assert listing.contact is not None and listing.contact.agency is None  # heading has no agency


def test_unknown_values_stay_none_and_are_never_false():
    listing = listing_for(PISECKA)
    assert listing.elevator is None  # no "Výtah" row: unknown, not False
    assert listing.furnished is None  # no row and no furnishing word in the headline
    assert listing.ready_date is None  # no "Datum nastěhování" row
    assert listing.rent == 25000
    assert listing.price_note == "inkaso 300,-Kč/os.voda, el. si nájemník přepíše na sebe"
    assert len(listing.photos) == 14


def test_normalize_rejects_a_payload_without_title_or_listing_url():
    raw = raw_for(KORUNNI)
    raw["detail"].update(h1=None, headline=None)
    raw["card"]["title"] = None
    with pytest.raises(ValueError, match="no title"):
        normalize_raw(raw, NOW)
    raw = raw_for(KORUNNI)
    raw["detail"]["url"] = "https://reality.idnes.cz/rk/detail/example/5a85b616a26e3a321d4f6dc5/"
    raw["card"]["url"] = raw["detail"]["url"]
    with pytest.raises(ValueError, match="not a listing URL"):
        normalize_raw(raw, NOW)


# Parsers, offline


def test_text_parsers_read_the_formats_the_pages_use():
    assert _czk("30‍000 Kč/měsíc") == 30000
    assert _czk("25 000 Kč/měsíc 24 500 Kč/měsíc") == 24500  # old and new price: the new one is last
    assert _iso_date("02.01.2027") == date(2027, 1, 2).isoformat()
    assert _iso_date("31.02.2027") is None
    assert _floor("3. patro (4. NP)") == 3 and _floor("přízemí") == 0 and _floor("sklep") is None
    assert _furnished("Pronájem zařízeného bytu") == "full"
    assert _furnished("částečně zařízený") == "partial"
    assert _furnished("nezařízený") == "none"
    assert _split_address("Korunní, Praha 2 - Vinohrady") == ("Korunní", "Praha 2", "Vinohrady")
    assert _split_address("Praha 2 - Vinohrady") == (None, "Praha 2", "Vinohrady")


def test_phone_and_email_come_from_real_looking_links_only():
    from domovoy.sources.idnes import _email, _phone

    assert _phone("tel:+420 000 000 000") == "+420000000000"
    assert _phone("tel:<phone>") is None
    assert _email("mailto:jane.doe@example.com?subject=Dotaz") == "jane.doe@example.com"
    assert _email("mailto:<email>") is None


# End to end against a fake iDNES (MockTransport)


class FakeIdnes:
    """Serves the fixtures like the site does: page 1 has cards, a page past the end is a 302,
    other rentals answer an empty page, unknown URLs are 404."""

    def __init__(self, *, repeat_page_two=False, list_status=None, detail_status=None):
        self.repeat_page_two = repeat_page_two
        self.list_status = list_status
        self.detail_status = detail_status or {}
        self.requests: list[tuple[float, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((time.monotonic(), str(request.url)))
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        if path.startswith("/detail/pronajem/"):
            source_id = path.rstrip("/").split("/")[-1]
            if source_id in self.detail_status:
                return httpx.Response(self.detail_status[source_id])
            if source_id in DETAIL_FILES:
                return httpx.Response(200, text=fixture(DETAIL_FILES[source_id]))
            return httpx.Response(404)
        match = re.match(r"^/s/pronajem/byty/([^/]+)/([^/]+)/$", path)
        if match is None:
            return httpx.Response(404)
        if self.list_status is not None:
            return httpx.Response(self.list_status)
        disposition, district = match.groups()
        if (disposition, district) == ("2+kk", "praha-2"):
            if page == 1:
                return httpx.Response(200, text=fixture("list_praha-2_2kk_p1.html"))
            if page == 2 and self.repeat_page_two:
                return httpx.Response(200, text=fixture("list_praha-2_2kk_p1.html"))
            return httpx.Response(302, headers={"location": path})
        if (disposition, district) == ("2+kk", "praha-3"):
            if page == 1:
                return httpx.Response(200, text=fixture("list_praha-3_2kk_p2.html"))
            return httpx.Response(302, headers={"location": path})
        return httpx.Response(200, text='<div class="c-products__list grid"></div>')

    def count(self, fragment: str) -> int:
        return sum(1 for _, url in self.requests if fragment in url)


async def collect_all(fake: FakeIdnes, *, max_listings=150, delay_sec=0.0, **profile_filters):
    source = IdnesSource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake), trust_env=False) as client:
        ctx = SourceContext(http=client, log=LOG, max_listings=max_listings, delay_sec=delay_sec)
        listings = [listing async for listing in source.collect(profile(**profile_filters), ctx)]
    return listings, source.last_stats


async def test_collect_yields_the_matching_listings_in_query_order():
    fake = FakeIdnes()
    listings, stats = await collect_all(fake)
    assert [listing.source_id for listing in listings] == [KORUNNI, PISECKA]
    assert (stats.emitted, stats.candidates, stats.detail_pages, stats.failed) == (2, 2, 2, 0)
    assert (stats.list_pages, stats.empty_queries) == (6, 4)
    assert fake.count("page=2") == 2  # the two queries with cards ask for page 2, get a 302, stop
    assert fake.count("page=3") == 0


async def test_max_listings_stops_the_source_early():
    fake = FakeIdnes()
    listings, stats = await collect_all(fake, max_listings=1)
    assert [listing.source_id for listing in listings] == [KORUNNI]
    assert stats.detail_pages == 1


async def test_a_page_that_repeats_the_previous_one_ends_the_query():
    fake = FakeIdnes(repeat_page_two=True)
    listings, stats = await collect_all(fake)
    assert [listing.source_id for listing in listings] == [KORUNNI, PISECKA]
    assert fake.count("page=3") == 0


async def test_a_detail_500_is_retried_once_then_skipped_without_stopping_the_run():
    fake = FakeIdnes(detail_status={KORUNNI: 500})
    listings, stats = await collect_all(fake)
    assert fake.count(KORUNNI) == 2  # one retry
    assert [listing.source_id for listing in listings] == [PISECKA]
    assert stats.failed == 1


async def test_a_detail_404_is_skipped_and_counted():
    fake = FakeIdnes(detail_status={PISECKA: 404})
    listings, stats = await collect_all(fake)
    assert [listing.source_id for listing in listings] == [KORUNNI]
    assert stats.failed == 1


async def test_a_listing_that_cannot_be_normalized_is_counted_not_fatal(monkeypatch):
    real = idnes_module.normalize_raw

    def boom(raw, collected_at):
        if raw["card"]["source_id"] == KORUNNI:
            raise ValueError("unexpected layout")
        return real(raw, collected_at)

    monkeypatch.setattr(idnes_module, "normalize_raw", boom)
    listings, stats = await collect_all(FakeIdnes())
    assert [listing.source_id for listing in listings] == [PISECKA]
    assert stats.failed == 1


async def test_a_search_page_that_cannot_be_parsed_is_counted_not_fatal(monkeypatch):
    def broken(html):
        raise RuntimeError("layout changed")

    monkeypatch.setattr(idnes_module, "parse_list", broken)
    listings, stats = await collect_all(FakeIdnes())
    assert listings == []
    assert stats.failed >= 1


async def test_403_or_429_stops_the_source_with_a_source_error():
    fake = FakeIdnes(list_status=429)
    with pytest.raises(SourceError, match="HTTP 429"):
        await collect_all(fake)
    assert fake.count("/detail/") == 0


async def test_search_pages_that_always_fail_are_a_source_error():
    fake = FakeIdnes(list_status=500)
    with pytest.raises(SourceError, match="no search page"):
        await collect_all(fake)


async def test_requests_are_spaced_by_the_delay():
    fake = FakeIdnes()
    await collect_all(fake, delay_sec=0.05)
    times = [t for t, _ in fake.requests]
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    assert gaps and min(gaps) >= 0.045
    assert idnes_module.MAX_IN_FLIGHT <= 3


def test_source_is_named_idnes_and_normalizes_through_the_method():
    source = IdnesSource()
    assert source.name == "idnes"
    assert source.normalize(raw_for(KORUNNI), NOW).source_id == KORUNNI


# Privacy of the fixtures (the repo goes public at 17:30)


URL_ATTRIBUTE = re.compile(r'(?:src|href|data-src|data-lazy)="[^"]*"')


def test_fixtures_hold_no_email_or_phone_and_only_placeholder_contacts():
    for path in sorted(FIXTURES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        # Photo URLs carry hex digests, which can contain digit runs; they are not phone numbers.
        visible = URL_ATTRIBUTE.sub("", text)
        assert not EMAIL.search(text), f"email-like text in {path.name}"
        assert not PHONE.search(visible), f"phone-like digits in {path.name}"
        assert not re.search(r'href="tel:[^"]*\d', text), f"tel link with digits in {path.name}"
        assert not re.search(r'href="mailto:[^"]*@', text), f"mailto link with an address in {path.name}"
    for source_id, name in DETAIL_FILES.items():
        heading = parse_detail(fixture(name))["author"]["heading"]
        assert heading in {"<name>", "<name>, <agency>"}, name


# Live smoke test (run with: pytest -m live)


@pytest.mark.live
async def test_live_smoke_vinohrady_profile(request):
    if "live" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("live smoke test: run with -m live")
    source = IdnesSource()
    async with httpx.AsyncClient(trust_env=False) as client:
        ctx = SourceContext(http=client, log=LOG, max_listings=8, delay_sec=0.5)
        listings = [listing async for listing in source.collect(profile(), ctx)]
    stats = source.last_stats
    with_photos = sum(1 for listing in listings if listing.photos)
    with_contact = sum(
        1
        for listing in listings
        if listing.contact and (listing.contact.name or listing.contact.phone or listing.contact.email)
    )
    print(
        f"\nlive iDNES: listings={len(listings)} with_photos={with_photos} "
        f"with_contact={with_contact} stats={stats}"
    )
    assert len(listings) >= 5, stats
    for listing in listings:
        assert listing.url.startswith("https://reality.idnes.cz/detail/pronajem/")
        assert listing.address_detail.citypart == "Vinohrady"
        assert listing.rent is None or listing.rent <= 30000
        assert listing.area_m2 is None or listing.area_m2 >= 45
