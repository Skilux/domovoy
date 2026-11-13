"""Bezrealitky source (WP2): plain HTTP to the JSON and HTML the page itself loads. No Playwright.

Access path (apify/research/bezrealitky.md):
- region listing, page 1: the HTML route /vypis/nabidka-pronajem/byt/<slug>. Its __NEXT_DATA__ gives the
  buildId and page 1 of the list.
- region listing, pages 2+: the page's own JSON route /_next/data/<buildId>/cs/vyhledat.json with
  regionOsmIds=R<osm id>. The bare id returns HTTP 500.
- details: /nemovitosti-byty-domy/<uri>. The data is props.pageProps.origAdvert in __NEXT_DATA__, plus
  the JSON-LD RealEstateListing.

Plain requests only: no header or fingerprint changes, no stealth, no CAPTCHA handling, no proxies.
"""

import asyncio
import json
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import urlencode, urlsplit

import httpx

from domovoy.models import PRAGUE, AddressDetail, Contact, GeoPoint, Listing, Portal, SearchProfile
from domovoy.sources.base import SourceContext, SourceError

BASE_URL = "https://www.bezrealitky.cz"
DETAIL_PREFIX = f"{BASE_URL}/nemovitosti-byty-domy/"
MAX_CONCURRENCY = 3  # detail requests in flight at once
MIN_GAP_SEC = 0.5  # request starts are at least this far apart (team rule: 0.5-1 s)
RETRY_SLEEP_SEC = 2.0  # one retry after a timeout or a 5xx
RATE_LIMITED_SLEEP_SEC = 10.0  # one retry after HTTP 429
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_LIST_PAGES = 40  # 40 pages x 15 adverts per region at most
TIMEOUT = httpx.Timeout(30.0)
ADDRESS_KEY = 'address({"locale":"CS"})'  # list-payload key; the detail payload uses "address"
ELEVATOR_TAG = "Výtah"
PARTLY_FURNISHED_TAG = "Částečně vybaveno"
FURNISHED_BY_ENUM = {"VYBAVENY": "full", "NEVYBAVENY": "none"}
# Portal enum to label. The enum-to-label pairs for 1+kk, 1+1, 2+kk, 3+kk and 3+1 were checked against the
# labels the page shows. DISP_N_KK and DISP_N_1 map by pattern (2+1 is inferred, 4+kk is enum-only).
# GARSONIERA is a studio: it gets its own label, so it never matches a profile disposition.
DISPOSITION_LABELS = {"GARSONIERA": "garsonka"}
_ENUM_DISPOSITION = re.compile(r"^DISP_([1-9])_(KK|1)$")
_TEXT_DISPOSITION = re.compile(r"\b([1-9]\+(?:kk|1))\b")
_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_JSON_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _fold(text: str) -> str:
    """Case- and diacritics-insensitive key for a name ("Žižkov" -> "zizkov")."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# Regions. The ids come from the regionTree of detail pages (checked 13 Nov 2026).


@dataclass(frozen=True)
class Region:
    slug: str  # HTML route segment under /vypis/nabidka-pronajem/byt/
    osm_id: int  # Bezrealitky region id, sent as "R<osm_id>"
    citypart: str | None  # the quarter this region is; None means the whole city


PRAHA = Region(slug="praha", osm_id=435514, citypart=None)
VINOHRADY = Region(slug="praha-vinohrady", osm_id=428841, citypart="Vinohrady")
REGION_BY_CITYPART = {_fold("Vinohrady"): VINOHRADY}


@dataclass(frozen=True)
class Plan:
    region: Region
    citypart: str | None  # the quarter the profile asks for; None = no quarter filter


def build_plan(profile: SearchProfile) -> list[Plan]:
    plans: list[Plan] = []
    for location in profile.filters.locations:
        if _fold(location.city) != "praha":
            raise SourceError(f"bezrealitky: city not supported: {location.city}")
        if location.citypart:
            region = REGION_BY_CITYPART.get(_fold(location.citypart), PRAHA)
            plan = Plan(region=region, citypart=location.citypart)
        else:
            plan = Plan(region=PRAHA, citypart=None)
        if plan not in plans:
            plans.append(plan)
    return plans


def disposition_label(enum: Any, about_name: str | None = None) -> str | None:
    """Portal enum -> "2+kk" style label. UNDEFINED falls back to a label in the JSON-LD name."""
    if isinstance(enum, str) and enum in DISPOSITION_LABELS:
        return DISPOSITION_LABELS[enum]
    if isinstance(enum, str):
        match = _ENUM_DISPOSITION.match(enum)
        if match:
            return f"{match.group(1)}+{'kk' if match.group(2) == 'KK' else '1'}"
    if about_name:
        match = _TEXT_DISPOSITION.search(about_name)
        if match:
            return match.group(1)
    return None


def quarter_from_label(label: str | None) -> str | None:
    """'Praha - Vinohrady', 'Praha-Praha-Vinohrady' or 'Praha-Žižkov' -> 'Vinohrady' or 'Žižkov'."""
    if not label:
        return None
    name = label.split(" - ")[-1].strip().split("-")[-1].strip()
    if not name or _fold(name) == "praha":
        return None
    return name


def quarter_from_address(address: Any) -> str | None:
    """The list address ends with 'Praha - <quarter>', e.g. 'Cimburkova, Praha - Žižkov'."""
    if not isinstance(address, str) or not address:
        return None
    return quarter_from_label(address.split(",")[-1].strip())


@dataclass(frozen=True)
class Candidate:
    advert_id: str
    uri: str
    citypart: str | None  # the profile's quarter this advert was listed for
    disposition: str | None
    rent: int | None
    area_m2: float | None
    quarter: str | None  # the quarter read from the list address


def passes_filters(
    profile: SearchProfile,
    *,
    disposition: str | None,
    rent: int | None,
    area_m2: float | None,
    quarter: str | None,
    citypart: str | None,
) -> bool:
    """Profile filters. A value that is unknown (None) never excludes an advert."""
    filters = profile.filters
    if disposition is not None and disposition not in filters.dispositions:
        return False
    if rent is not None and filters.max_rent is not None and rent > filters.max_rent:
        return False
    if area_m2 is not None and filters.min_area_m2 is not None and area_m2 < filters.min_area_m2:
        return False
    if citypart is not None and quarter is not None and _fold(quarter) != _fold(citypart):
        return False
    return True


# Parsing the payloads (pure)


def _page_props(data: dict[str, Any]) -> dict[str, Any]:
    if "pageProps" in data:
        return data["pageProps"]
    return data.get("props", {}).get("pageProps", {})


def parse_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if match is None:
        raise SourceError("bezrealitky: page has no __NEXT_DATA__ (layout changed?)")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceError("bezrealitky: __NEXT_DATA__ is not JSON") from exc
    if not isinstance(data, dict):
        raise SourceError("bezrealitky: __NEXT_DATA__ is not an object")
    return data


def parse_jsonld_listing(html: str) -> dict[str, Any] | None:
    for raw in _JSON_LD.findall(html):
        try:
            block = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(block, dict):
            continue
        for node in block.get("@graph", [block]):
            if isinstance(node, dict) and node.get("@type") == "RealEstateListing":
                return node
    return None


def parse_detail(html: str, source_url: str) -> dict[str, Any]:
    advert = _page_props(parse_next_data(html)).get("origAdvert")
    if not isinstance(advert, dict):
        raise SourceError("bezrealitky: detail payload has no origAdvert")
    return {"advert": advert, "jsonld": parse_jsonld_listing(html), "source_url": source_url}


@dataclass(frozen=True)
class ListPage:
    total: int
    adverts: list[dict[str, Any]]


def parse_list_page(data: dict[str, Any]) -> ListPage:
    cache = _page_props(data).get("apolloCache") or {}
    root = cache.get("ROOT_QUERY") or {}
    key = next((k for k in root if k.startswith("listAdverts(") and "discountedOnly" not in k), None)
    if key is None:
        raise SourceError("bezrealitky: list payload has no listAdverts entry")
    listing = root[key]
    adverts = [cache[ref["__ref"]] for ref in listing.get("list") or [] if ref.get("__ref") in cache]
    return ListPage(total=int(listing.get("totalCount") or 0), adverts=adverts)


def candidate_from_advert(advert: dict[str, Any], citypart: str | None) -> Candidate | None:
    if advert.get("id") is None or not advert.get("uri"):
        return None
    rent = advert.get("price")
    area = advert.get("surface")
    return Candidate(
        advert_id=str(advert["id"]),
        uri=str(advert["uri"]),
        citypart=citypart,
        disposition=disposition_label(advert.get("disposition")),
        rent=rent if _is_int(rent) and rent > 0 else None,
        area_m2=float(area) if _is_int(area) and area > 0 else None,
        quarter=quarter_from_address(advert.get(ADDRESS_KEY) or advert.get("address")),
    )


def _district_and_quarter(tree: Any) -> tuple[str | None, str | None]:
    district = quarter = None
    for node in tree or []:
        if not isinstance(node, dict) or not node.get("name"):
            continue
        if node.get("subType") == "REGION":
            district = str(node["name"])
        elif node.get("subType") == "CITY_DISTRICT":
            quarter = quarter_from_label(str(node["name"]))
    return district, quarter


def _geo(gps: Any) -> GeoPoint | None:
    if isinstance(gps, dict) and gps.get("lat") is not None and gps.get("lng") is not None:
        return GeoPoint(lat=float(gps["lat"]), lon=float(gps["lng"]))
    return None


def _elevator(lift: Any, tags: list[str]) -> bool | None:
    if isinstance(lift, bool):
        return lift
    return True if ELEVATOR_TAG in tags else None


def _furnished(equipped: Any, tags: list[str]) -> str | None:
    if isinstance(equipped, str) and equipped in FURNISHED_BY_ENUM:
        return FURNISHED_BY_ENUM[equipped]
    return "partial" if PARTLY_FURNISHED_TAG in tags else None


def _price_note(data_json: Any) -> str | None:
    if not isinstance(data_json, str):
        return None
    try:
        parsed = json.loads(data_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return (parsed.get("priceNote") or {}).get("cs") or None


def _ready_date(timestamp: Any) -> str | None:
    if not _is_int(timestamp):
        return None
    return datetime.fromtimestamp(timestamp, PRAGUE).date().isoformat()


def _ownership(value: Any) -> str | None:
    return value if isinstance(value, str) and value not in ("", "UNDEFINED") else None


def _is_owner_listing(advert: dict[str, Any]) -> bool:
    """Team default (13:00): Bezrealitky lists without agencies, so True unless an advert field
    clearly marks an agency. None of the fields checked so far does (research note, section 8)."""
    return True


def normalize_detail(raw: dict[str, Any], collected_at: datetime) -> Listing:
    """Pure: one detail payload (see parse_detail) to a Listing."""
    advert: dict[str, Any] = raw["advert"]
    ld: dict[str, Any] = raw.get("jsonld") or {}
    about: dict[str, Any] = ld.get("about") or {}
    seller: dict[str, Any] = (ld.get("offers") or {}).get("seller") or {}
    message: dict[str, Any] = advert.get("messageData") or {}
    tags = [str(tag) for tag in advert.get("tags") or []]
    district, quarter = _district_and_quarter(advert.get("regionTree"))
    quarter = quarter or quarter_from_address(advert.get("address"))
    street = advert.get("street") or None
    address_detail = AddressDetail(
        street=street,
        house_number=None,  # withheld on the portal (withHouseNumber:false)
        citypart=quarter,
        district=district,
        gps=_geo(advert.get("gps")),
        precision="street" if street else ("district" if (quarter or district) else None),
    )
    name = seller.get("name") or None
    form_url = message.get("url") if message.get("messageType") == "LINK" and message.get("url") else None
    contact = (
        Contact(name=name, agency=None, ico=None, email=None, phone=None, form_url=form_url)
        if name or form_url
        else None
    )
    return Listing(
        portal="bezrealitky",
        source_id=str(advert["id"]),
        url=str(ld.get("url") or raw.get("source_url") or f"{DETAIL_PREFIX}{advert['uri']}"),
        collected_at=collected_at,
        title=str(ld.get("name") or advert.get("pageTitle") or advert.get("address") or advert["id"]),
        address=advert.get("address") or None,
        address_detail=address_detail,
        disposition=disposition_label(advert.get("disposition"), about.get("name")),
        area_m2=float(advert["surface"]) if _is_int(advert.get("surface")) and advert["surface"] > 0 else None,
        floor=advert["etage"] if _is_int(advert.get("etage")) else None,
        elevator=_elevator(advert.get("lift"), tags),
        furnished=_furnished(advert.get("equipped"), tags),
        rent=advert["price"] if _is_int(advert.get("price")) and advert["price"] > 0 else None,
        price_note=_price_note(advert.get("dataJson")),
        description=advert.get("description") or None,
        ready_date=_ready_date(advert.get("availableFrom")),
        ownership=_ownership(advert.get("ownership")),
        is_owner_listing=_is_owner_listing(advert),
        contact=contact,
        photos=[str(p["url"]) for p in advert.get("publicImages") or [] if isinstance(p, dict) and p.get("url")],
        poi=None,  # the portal gives walking minutes to public transport only, not metres
        raw_ref=None,
    )


# Network


class _Pacer:
    """One clock for every request to the portal: request starts are at least `gap` seconds apart."""

    def __init__(self, gap: float) -> None:
        self._gap = gap
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def turn(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
                now = loop.time()
            self._next = now + self._gap


async def _get(ctx: SourceContext, pacer: _Pacer, url: str) -> httpx.Response:
    problem = "no attempt"
    pause = RETRY_SLEEP_SEC
    for attempt in range(2):
        await pacer.turn()
        try:
            response = await ctx.http.get(url, timeout=TIMEOUT, follow_redirects=True)
        except httpx.HTTPError as exc:
            problem = type(exc).__name__
            pause = RETRY_SLEEP_SEC
        else:
            if response.status_code == 200:
                return response
            problem = f"HTTP {response.status_code}"
            if response.status_code not in TRANSIENT_STATUS:
                break
            pause = RATE_LIMITED_SLEEP_SEC if response.status_code == 429 else RETRY_SLEEP_SEC
        if attempt == 0:
            await asyncio.sleep(pause)
    raise SourceError(f"bezrealitky request failed ({problem}): {urlsplit(url).path}")


def _json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise SourceError("bezrealitky: the JSON route did not return JSON") from exc
    if not isinstance(body, dict):
        raise SourceError("bezrealitky: the JSON route body is not an object")
    return body


def _json_route_url(build_id: str, region: Region, page: int) -> str:
    query = urlencode(
        {
            "estateType": "BYT",
            "offerType": "PRONAJEM",
            "country": "ceska-republika",
            "currency": "CZK",
            "locale": "CS",
            "location": "exact",
            "regionOsmIds": f"R{region.osm_id}",
            "page": page,
        }
    )
    return f"{BASE_URL}/_next/data/{build_id}/cs/vyhledat.json?{query}"


async def _list_candidates(
    profile: SearchProfile,
    plans: list[Plan],
    limit: int,
    ctx: SourceContext,
    pacer: _Pacer,
) -> list[Candidate]:
    found: list[Candidate] = []
    seen: set[str] = set()
    for plan in plans:
        build_id = ""
        page = 1
        while len(found) < limit and page <= MAX_LIST_PAGES:
            try:
                if page == 1:
                    response = await _get(ctx, pacer, f"{BASE_URL}/vypis/nabidka-pronajem/byt/{plan.region.slug}")
                    data = parse_next_data(response.text)
                    build_id = str(data.get("buildId") or "")
                    if not build_id:
                        raise SourceError("bezrealitky: page has no buildId")
                else:
                    response = await _get(ctx, pacer, _json_route_url(build_id, plan.region, page))
                    data = _json_body(response)
                listing_page = parse_list_page(data)
            except SourceError as exc:
                if page == 1 and not found:
                    raise
                ctx.log.warning("bezrealitky: list page %d (%s) skipped: %s", page, plan.region.slug, exc)
                break
            for advert in listing_page.adverts:
                candidate = candidate_from_advert(advert, citypart=plan.citypart)
                if candidate is None or candidate.advert_id in seen:
                    continue
                seen.add(candidate.advert_id)
                if passes_filters(
                    profile,
                    disposition=candidate.disposition,
                    rent=candidate.rent,
                    area_m2=candidate.area_m2,
                    quarter=candidate.quarter,
                    citypart=plan.citypart,
                ):
                    found.append(candidate)
                    if len(found) >= limit:
                        break
            if not listing_page.adverts or page * len(listing_page.adverts) >= listing_page.total:
                break
            page += 1
    return found


async def _fetch_detail(candidate: Candidate, ctx: SourceContext, pacer: _Pacer) -> dict[str, Any]:
    url = f"{DETAIL_PREFIX}{candidate.uri}"
    response = await _get(ctx, pacer, url)
    return parse_detail(response.text, source_url=str(response.url))


async def _collect(profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
    plans = build_plan(profile)
    limit = ctx.max_listings
    pacer = _Pacer(max(MIN_GAP_SEC, ctx.delay_sec))
    candidates = await _list_candidates(profile, plans, limit, ctx, pacer)
    yielded = attempted = failed = 0
    queue = list(candidates)
    while queue and yielded < limit:
        chunk, queue = queue[:MAX_CONCURRENCY], queue[MAX_CONCURRENCY:]
        attempted += len(chunk)
        results = await asyncio.gather(
            *(_fetch_detail(candidate, ctx, pacer) for candidate in chunk), return_exceptions=True
        )
        for candidate, result in zip(chunk, results, strict=True):
            if isinstance(result, BaseException):
                failed += 1
                ctx.log.warning("bezrealitky: detail %s skipped: %s", candidate.advert_id, result)
                continue
            try:
                listing = normalize_detail(result, datetime.now(PRAGUE))
            except (KeyError, TypeError, ValueError) as exc:
                failed += 1
                ctx.log.warning("bezrealitky: detail %s not normalized: %s", candidate.advert_id, exc)
                continue
            if not passes_filters(
                profile,
                disposition=listing.disposition,
                rent=listing.rent,
                area_m2=listing.area_m2,
                quarter=listing.address_detail.citypart,
                citypart=candidate.citypart,
            ):
                continue
            yield listing
            yielded += 1
            if yielded >= limit:
                break
    if attempted and not yielded and failed == attempted:
        raise SourceError("bezrealitky: every detail request failed")


class BezrealitkySource:
    name: ClassVar[Portal] = "bezrealitky"

    async def collect(self, profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
        try:
            async for listing in _collect(profile, ctx):
                yield listing
        except SourceError:
            raise
        except Exception as exc:  # an unexpected shape must fail this source, not the whole run
            raise SourceError(f"bezrealitky failed: {type(exc).__name__}: {exc}") from exc

    def normalize(self, raw: dict[str, Any], collected_at: datetime) -> Listing:
        return normalize_detail(raw, collected_at)


SOURCE = BezrealitkySource()
