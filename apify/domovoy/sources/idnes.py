"""iDNES Reality (reality.idnes.cz): Praha rentals over plain HTTP (WP3).

Access path, from apify/research/idnes.md (observed 13 Nov 2026):
- search pages are server-rendered: GET /s/pronajem/byty/<disposition>/<district>/?page=N.
  A page past the last one answers 302 to the last page, so redirects are never followed.
- detail pages are server-rendered: GET /detail/pronajem/byt/<slug>/<24-hex id>/.
- no JSON API, no XHR and no browser are needed.

Politeness: requests are started one at a time with a gap of delay_sec..2*delay_sec between
starts (0.5-1 s by default). At most MAX_IN_FLIGHT requests are in flight. One retry on 5xx and
network errors. 403 or 429 stops the source with SourceError. A failing listing is counted in
last_stats and skipped; it never stops the run.
"""

import asyncio
import json
import random
import re
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import date, datetime
from logging import Logger
from typing import Any, ClassVar
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from domovoy.models import (
    PRAGUE,
    AddressDetail,
    Contact,
    Furnished,
    GeoPoint,
    Listing,
    Portal,
    SearchProfile,
)
from domovoy.sources.base import SourceContext, SourceError

BASE_URL = "https://reality.idnes.cz"
MAX_PAGES_PER_QUERY = 10
MAX_IN_FLIGHT = 3
REDIRECT_CODES = (301, 302, 303, 307, 308)

# Praha district slug -> iDNES locality code. From GET /search-localities/ (observed 13 Nov 2026).
DISTRICT_CODES = {
    "praha-1": "MOP-19",
    "praha-2": "MOP-27",
    "praha-3": "MOP-35",
    "praha-4": "MOP-43",
    "praha-5": "MOP-51",
    "praha-6": "MOP-60",
    "praha-7": "MOP-78",
    "praha-8": "MOP-86",
    "praha-9": "MOP-94",
    "praha-10": "MOP-108",
}
# iDNES has no citypart filter. Vinohrady spans Praha 2, 3 and 10 (docs/prd/actor.md).
CITYPART_DISTRICTS: dict[str, tuple[str, ...]] = {"Vinohrady": ("praha-2", "praha-3", "praha-10")}
CITY_DISTRICTS: dict[str, tuple[str, ...]] = {"Praha": tuple(DISTRICT_CODES)}
# Profile disposition -> URL segment. On iDNES "6+kk-a-vetsi" means 6+kk and larger.
DISPOSITION_SEGMENT = {
    "1+kk": "1+kk", "1+1": "1+1",
    "2+kk": "2+kk", "2+1": "2+1",
    "3+kk": "3+kk", "3+1": "3+1",
    "4+kk": "4+kk", "4+1": "4+1",
    "5+kk": "5+kk", "5+1": "5+1",
    "6+kk": "6+kk-a-vetsi",
}
OWNERSHIP = {"osobní": "personal", "družstevní": "cooperative"}
PRAGUE_BOX = (49.9, 50.25, 14.2, 14.8)  # lat min, lat max, lon min, lon max

LISTING_PATH = re.compile(r"^/detail/pronajem/[^/]+/[^/]+/([0-9a-f]{24})/?$")
DISPOSITION = re.compile(r"(?<![\w+])([1-9]\+(?:kk|1))(?![\w+])")
AREA = re.compile(r"(\d+(?:[.,]\d+)?)\s*m(?![a-zA-Z])")
PRICE = re.compile(r"(\d{1,3}(?: \d{3})+|\d+)\s*Kč")
FLOOR = re.compile(r"\s*(\d+)\.\s*patro")
DATE_CZ = re.compile(r"\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
PHONE = re.compile(r"^\+?\d{9,15}$")
NO_EXACT_ADDRESS = "nemá přesnou adresu"


# Parsing helpers (pure)


def _clean(text: str | None) -> str | None:
    """Text as shown on the page: no zero-width joiners, no no-break spaces, single spaces."""
    if text is None:
        return None
    value = re.sub(r"\s+", " ", text.replace("‍", "").replace(" ", " ").replace(" ", " "))
    return value.strip() or None


def _text(element: Any) -> str | None:
    return _clean(element.get_text(" ", strip=True)) if element is not None else None


def _czk(text: str | None) -> int | None:
    """Last amount in CZK in the text ("24 500 Kč/měsíc" -> 24500). The header of a discounted
    listing shows the old and the new price; the new one comes last."""
    found = PRICE.findall(_clean(text) or "")
    return int(found[-1].replace(" ", "")) if found else None


def _area(text: str | None) -> float | None:
    match = AREA.search(_clean(text) or "")
    return float(match.group(1).replace(",", ".")) if match else None


def _disposition(text: str | None) -> str | None:
    match = DISPOSITION.search(_clean(text) or "")
    return match.group(1) if match else None


def _furnished(text: str | None) -> Furnished | None:
    value = (_clean(text) or "").lower()
    if "nezařízen" in value:
        return "none"
    if "částečně zařízen" in value:
        return "partial"
    if "zařízen" in value:
        return "full"
    return None


def _floor(text: str | None) -> int | None:
    value = (_clean(text) or "").lower()
    if value.startswith("přízemí"):
        return 0
    match = FLOOR.match(value)
    return int(match.group(1)) if match else None


def _iso_date(text: str | None) -> str | None:
    match = DATE_CZ.match(_clean(text) or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return None


def _split_address(line: str | None) -> tuple[str | None, str | None, str | None]:
    """"Korunní, Praha 2 - Vinohrady" -> (street, district, citypart)."""
    line = _clean(line)
    if not line:
        return None, None, None
    head, comma, rest = line.partition(",")
    if comma:
        street = head.strip() or None
    else:
        street, rest = None, line  # no street on the line: "Praha 2 - Vinohrady"
    district = re.search(r"Praha\s+\d+", rest)
    citypart = rest.split(" - ", 1)[1].strip() if " - " in rest else None
    return street, district.group(0) if district else None, citypart or None


def _split_heading(text: str | None) -> tuple[str | None, str | None]:
    """The author heading is "Name, Agency" or "Name" alone."""
    text = _clean(text)
    if not text:
        return None, None
    name, _, agency = text.partition(", ")
    return name.strip() or None, agency.strip() or None


def _email(href: str | None) -> str | None:
    if not href or not href.lower().startswith("mailto:"):
        return None
    value = unquote(href[len("mailto:"):].split("?", 1)[0]).strip()
    return value if EMAIL.match(value) else None


def _phone(href: str | None) -> str | None:
    if not href or not href.lower().startswith("tel:"):
        return None
    digits = re.sub(r"[^\d+]", "", href[len("tel:"):])
    return digits if PHONE.match(digits) else None


# Search pages (pure)


@dataclass(frozen=True)
class ListCard:
    source_id: str
    url: str
    title: str | None  # image alt: "Pronájem bytu 2+kk 56 m², Korunní, Praha 2 - Vinohrady"
    address: str | None  # "Korunní, Praha 2 - Vinohrady"
    price_text: str | None  # "30 000 Kč/měsíc"


def parse_list(html: str) -> list[ListCard]:
    """Listing cards of one search page. Advertisement slots have no listing link and are skipped."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[ListCard] = []
    for item in soup.select("div.c-products__item"):
        link = item.select_one("a.c-products__link[href]")
        if link is None:
            continue
        url = urljoin(BASE_URL, link["href"]).split("?", 1)[0]
        match = LISTING_PATH.match(urlsplit(url).path)
        if match is None:
            continue
        image = item.select_one("img[alt]")
        cards.append(
            ListCard(
                source_id=match.group(1),
                url=url,
                title=_clean(image["alt"]) if image else None,
                address=_text(item.select_one("p.c-products__info")),
                price_text=_text(item.select_one("p.c-products__price strong")),
            )
        )
    return cards


@dataclass(frozen=True)
class SearchQuery:
    district: str  # slug, e.g. "praha-2"
    disposition: str  # profile value, e.g. "2+kk"
    citypart: str | None  # exact citypart to keep from the cards, e.g. "Vinohrady"

    def url(self, page: int) -> str:
        base = f"{BASE_URL}/s/pronajem/byty/{DISPOSITION_SEGMENT[self.disposition]}/{self.district}/"
        return base if page == 1 else f"{base}?page={page}"


def build_queries(profile: SearchProfile, log: Logger) -> list[SearchQuery]:
    """One query per district and disposition. Unknown citypart or disposition is logged and skipped."""
    queries: list[SearchQuery] = []
    for location in profile.filters.locations:
        if location.citypart:
            districts = CITYPART_DISTRICTS.get(location.citypart)
        else:
            districts = CITY_DISTRICTS.get(location.city)
        if not districts:
            log.warning("iDNES: no districts for %s/%s; skipped", location.city, location.citypart)
            continue
        for district in districts:
            for disposition in profile.filters.dispositions:
                if disposition not in DISPOSITION_SEGMENT:
                    log.warning("iDNES: no URL segment for %s; skipped", disposition)
                    continue
                query = SearchQuery(district, disposition, location.citypart)
                if query not in queries:
                    queries.append(query)
    return queries


def card_matches(card: ListCard, query: SearchQuery, profile: SearchProfile) -> bool:
    """Cheap filters on the card, before any detail request. Unknown values pass."""
    filters = profile.filters
    if query.citypart is not None:
        parts = _split_address(card.address)[2]
        if parts is not None and parts != query.citypart:
            return False
    disposition = _disposition(card.title)
    if disposition is not None and disposition not in filters.dispositions:
        return False
    rent = _czk(card.price_text)
    if rent is not None and filters.max_rent is not None and rent > filters.max_rent:
        return False
    area = _area(card.title)
    if area is not None and filters.min_area_m2 is not None and area < filters.min_area_m2:
        return False
    return True


# Detail pages (pure)


def _params(soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
    """Label/value rows of the property parameters. A check icon marks a feature as present."""
    params: dict[str, dict[str, Any]] = {}
    for dt in soup.select("dl dt"):
        label = _text(dt)
        dd = dt.find_next_sibling("dd")
        if not label:
            continue
        params[label] = {
            "value": _text(dd) or "",
            "check": bool(dd is not None and dd.select_one(".icon--check") is not None),
        }
    return params


def _map_center(soup: BeautifulSoup) -> list[float] | None:
    """[lon, lat] of the map centre. It is the centre of the marked street, not the flat itself."""
    script = soup.select_one("script[data-maptiler-json]")
    if script is None or not script.string:
        return None
    try:
        center = json.loads(script.string)["mtMapOptions"]["center"]
        lon, lat = float(center[0]), float(center[1])
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return [lon, lat]


def _photos(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    for image in soup.select("div.b-gallery img"):
        for attribute in ("data-lazy", "src", "data-src"):
            value = image.get(attribute) or ""
            if "/sta/compile/thumbs/" in value:
                if value not in urls:
                    urls.append(value)
                break
    return urls


def _author(soup: BeautifulSoup) -> dict[str, Any] | None:
    block = soup.select_one("div.b-author")
    if block is None:
        return None
    phone_href = email_href = None
    for link in block.select("a[href]"):
        href = link["href"]
        if phone_href is None and href.lower().startswith("tel:"):
            phone_href = href
        elif email_href is None and href.lower().startswith("mailto:"):
            email_href = href
    return {
        "heading": _text(block.select_one("h2.b-author__title")),
        "phone_href": phone_href,
        "email_href": email_href,
    }


def parse_detail(html: str) -> dict[str, Any]:
    """Raw detail payload: strings as shown on the page, no conversion yet."""
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    og_title = soup.select_one('meta[property="og:title"]')
    og_description = soup.select_one('meta[property="og:description"]')
    description = "\n".join(p.get_text("\n", strip=True) for p in soup.select("div.b-desc p")).strip()
    body_text = _text(soup.body) or ""
    return {
        "url": canonical["href"] if canonical else None,
        "h1": _text(soup.select_one("h1.b-detail__title")),
        "headline": _clean(og_title["content"]) if og_title else None,
        "address_line": _text(soup.select_one("p.b-detail__info")),
        "header_price": _text(soup.select_one("p.b-detail__price")),
        "price_note": _text(soup.select_one("div.wrapper-price-notes strong")),
        "params": _params(soup),
        "description": description or None,
        "offer_kind": "agency"
        if og_description and "realitní kancelář" in og_description.get("content", "")
        else None,
        "map_center": _map_center(soup),
        "precision_note": NO_EXACT_ADDRESS in body_text,
        "photos": _photos(soup),
        "author": _author(soup),
        "enquiry_form": soup.select_one("form.form-contact") is not None,
    }


# Normalization (pure)


def _contact(detail: dict[str, Any], url: str | None) -> Contact | None:
    author = detail.get("author")
    if not author:
        return None
    name, agency = _split_heading(author.get("heading"))
    contact = Contact(
        name=name,
        agency=agency,
        ico=None,  # not on the detail page
        email=_email(author.get("email_href")),
        phone=_phone(author.get("phone_href")),
        form_url=url if detail.get("enquiry_form") else None,
    )
    if all(value is None for value in contact.model_dump().values()):
        return None
    return contact


def normalize_raw(raw: dict[str, Any], collected_at: datetime) -> Listing:
    """One raw payload ({"card": ..., "detail": ...}) to a Listing. Pure."""
    card = raw.get("card") or {}
    detail = raw["detail"]
    params = detail["params"]
    url = detail["url"] or card["url"]
    match = LISTING_PATH.match(urlsplit(url).path)
    if match is None:
        raise ValueError(f"not a listing URL: {url}")
    title = detail["h1"] or detail["headline"] or card.get("title")
    if not title:
        raise ValueError("listing has no title")

    address_line = detail["address_line"] or card.get("address")
    street, district, citypart = _split_address(address_line)

    disposition = _disposition(detail["h1"]) or _disposition(card.get("title"))
    area_row = params.get("Užitná plocha")
    area = _area(area_row["value"]) if area_row else None
    area = area if area is not None else _area(detail["h1"] or card.get("title"))

    floor_row = params.get("Podlaží")
    floor = _floor(floor_row["value"]) if floor_row else None

    elevator_row = params.get("Výtah")
    elevator = True if elevator_row and elevator_row["check"] else None

    furnished_row = params.get("Vybavení")
    furnished = _furnished(furnished_row["value"]) if furnished_row else None
    if furnished is None:
        furnished = _furnished(detail["headline"])

    rent_row = params.get("Cena")
    rent = _czk(rent_row["value"]) if rent_row else None
    if rent is None:
        rent = _czk(detail["header_price"]) or _czk(card.get("price_text"))

    ready_row = params.get("Datum nastěhování")
    ready_date = _iso_date(ready_row["value"]) if ready_row else None

    ownership_row = params.get("Vlastnictví")
    ownership = OWNERSHIP.get((ownership_row["value"] if ownership_row else "").lower())

    gps = None
    if detail["map_center"] is not None:
        lon, lat = detail["map_center"]
        lat_min, lat_max, lon_min, lon_max = PRAGUE_BOX
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            gps = GeoPoint(lat=lat, lon=lon)
    precision = "street" if street else ("district" if district else None)

    return Listing(
        portal="idnes",
        source_id=match.group(1),
        url=url,
        collected_at=collected_at,
        title=title,
        address=address_line,
        address_detail=AddressDetail(
            street=street,
            house_number=None,  # iDNES shows no house number
            citypart=citypart,
            district=district,
            gps=gps,
            precision=precision,
        ),
        disposition=disposition,
        area_m2=area,
        floor=floor,
        elevator=elevator,
        furnished=furnished,
        rent=rent,
        price_note=detail["price_note"],
        description=detail["description"],
        ready_date=ready_date,
        ownership=ownership,
        is_owner_listing=False if detail["offer_kind"] == "agency" else None,
        contact=_contact(detail, url),
        photos=detail["photos"],
        poi=None,  # no structured distances on the page
        raw_ref=None,
    )


# Source


@dataclass
class IdnesStats:
    list_pages: int = 0
    empty_queries: int = 0  # first page answered 200 with no listing cards: no results, not an error
    candidates: int = 0
    detail_pages: int = 0
    emitted: int = 0
    failed: int = 0  # search pages and detail pages that failed or could not be parsed


class _Pacer:
    """One clock per source. Consecutive request starts are spaced by delay..2*delay seconds."""

    def __init__(self, delay_sec: float) -> None:
        self._delay = max(0.0, delay_sec)
        self._next_start = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next_start > now:
                await asyncio.sleep(self._next_start - now)
                now = time.monotonic()
            self._next_start = now + random.uniform(self._delay, 2 * self._delay)


class IdnesSource:
    """Rentals in Praha for a search profile. last_stats holds the counts of the last collect()."""

    name: ClassVar[Portal] = "idnes"

    def __init__(self) -> None:
        self.last_stats = IdnesStats()

    async def collect(self, profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
        """Yield normalized listings that pass the cheap card filters, up to max_listings."""
        stats = self.last_stats = IdnesStats()
        limit = min(ctx.max_listings, profile.filters.max_listings)
        queries = build_queries(profile, ctx.log)
        if not queries:
            raise SourceError("iDNES has no search pages for the profile's locations and dispositions")
        if limit < 1:
            return
        pacer = _Pacer(ctx.delay_sec)
        in_flight = asyncio.Semaphore(MAX_IN_FLIGHT)
        seen: set[str] = set()
        for query in queries:
            query_seen: set[str] = set()
            page = 1
            while page <= MAX_PAGES_PER_QUERY:
                status, html = await self._get(ctx, pacer, in_flight, query.url(page))
                if status in REDIRECT_CODES:
                    break  # past the last page
                if status != 200:
                    stats.failed += 1
                    ctx.log.warning("iDNES search page %s: HTTP %s; skipped", query.url(page), status)
                    break
                stats.list_pages += 1
                try:
                    cards = parse_list(html)
                except Exception as exc:  # a changed layout ends this query; the run goes on
                    stats.failed += 1
                    ctx.log.warning("iDNES search page %s not parsed: %s", query.url(page), exc)
                    break
                if not cards:
                    if page == 1:
                        stats.empty_queries += 1
                        ctx.log.info("iDNES: no listings on %s", query.url(page))
                    break
                fresh = [card for card in cards if card.source_id not in query_seen]
                if not fresh:
                    break  # the server repeats a page
                query_seen.update(card.source_id for card in cards)
                for card in fresh:
                    if card.source_id in seen or not card_matches(card, query, profile):
                        continue
                    seen.add(card.source_id)
                    stats.candidates += 1
                    listing = await self._listing(ctx, pacer, in_flight, card, stats)
                    if listing is None:
                        continue
                    stats.emitted += 1
                    yield listing
                    if stats.emitted >= limit:
                        return
                page += 1
        if stats.list_pages == 0:
            raise SourceError(f"iDNES returned no search page ({stats.failed} errors)")

    def normalize(self, raw: dict[str, Any], collected_at: datetime) -> Listing:
        return normalize_raw(raw, collected_at)

    async def _listing(
        self,
        ctx: SourceContext,
        pacer: _Pacer,
        in_flight: asyncio.Semaphore,
        card: ListCard,
        stats: IdnesStats,
    ) -> Listing | None:
        stats.detail_pages += 1
        status, html = await self._get(ctx, pacer, in_flight, card.url)
        if status != 200:
            stats.failed += 1
            ctx.log.warning("iDNES detail %s: HTTP %s; skipped", card.source_id, status)
            return None
        try:
            raw = {"card": asdict(card), "detail": parse_detail(html)}
            return normalize_raw(raw, datetime.now(PRAGUE))
        except Exception as exc:  # one odd page must not stop the run
            stats.failed += 1
            ctx.log.warning("iDNES listing %s skipped: %s", card.source_id, exc)
            return None

    async def _get(
        self, ctx: SourceContext, pacer: _Pacer, in_flight: asyncio.Semaphore, url: str
    ) -> tuple[int, str]:
        """GET with one retry on 5xx and network errors. Returns (status, text); status 0 means no
        answer. 403 and 429 raise SourceError: the portal refused the plain request, so we stop."""
        for attempt in (1, 2):
            await pacer.wait()
            try:
                async with in_flight:
                    response = await ctx.http.get(
                        url,
                        headers={"Accept": "text/html"},
                        follow_redirects=False,
                        timeout=30.0,
                    )
            except httpx.HTTPError as exc:
                ctx.log.warning("iDNES %s: %s (attempt %d)", url, type(exc).__name__, attempt)
                continue
            if response.status_code in (403, 429):
                raise SourceError(
                    f"iDNES refused the plain request (HTTP {response.status_code}); source stopped"
                )
            if response.status_code >= 500:
                ctx.log.warning("iDNES %s: HTTP %d (attempt %d)", url, response.status_code, attempt)
                continue
            return response.status_code, response.text
        return 0, ""
