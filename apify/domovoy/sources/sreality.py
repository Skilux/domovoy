"""Sreality source (WP1): plain HTTP to the public v1 JSON API.

Search: GET /api/v1/estates/search, rent flats in the profile's districts, paged by offset.
Detail: GET /api/v1/estates/{hash_id}. No browser, no cookies, no redirect following.
Pacing: at most 3 requests in flight, and 0.5-1 s between request starts, shared by search and detail.
Access basis: research/sreality.md and the team decisions in docs/decisions.md (13 Nov 2026).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import httpx

from domovoy.models import (
    PRAGUE,
    AddressDetail,
    Contact,
    Furnished,
    GeoPoint,
    Listing,
    Poi,
    Portal,
    SearchProfile,
)
from domovoy.sources.base import SourceContext, SourceError

API_BASE = "https://www.sreality.cz/api/v1/estates"
SITE_BASE = "https://www.sreality.cz"
HEADERS = {"User-Agent": "DOMOVOY-actor/0.1", "Accept": "application/json"}
TIMEOUT_SEC = 30.0
PAGE_SIZE = 100  # verified 13 Nov 2026: limit 100 and 500 are both honored
MAX_PAGES = 5
CONCURRENCY = 3

# District ids, verified 13 Nov 2026: 5002 = Praha 2, 5003 = Praha 3, 5010 = Praha 10.
DISTRICT_IDS = {"Praha 2": 5002, "Praha 3": 5003, "Praha 10": 5010}
# Citypart name, as locality.citypart spells it, -> the districts that contain it.
CITYPART_DISTRICTS = {"Vinohrady": ("Praha 2", "Praha 3", "Praha 10")}
# category_sub_cb codes, verified 13 Nov 2026: 4 = 2+kk, 5 = 2+1. Other dispositions are not mapped yet.
DISPOSITION_CODES = {"2+kk": 4, "2+1": 5}
RENT_UNIT = "za měsíc"  # price_unit_cb name for monthly prices
YES, NO = "Ano", "Ne"  # yes/no codebook names
PRECISION = {"address": "exact", "street": "street", "ward": "district", "quarter": "district"}
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)")


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _codebook_name(obj: Any) -> str | None:
    """Name of a {name, value} codebook entry. Value 0 and '- ...' names are placeholders: unknown."""
    entry = _dict(obj)
    name = _text(entry.get("name"))
    if name is None or entry.get("value") == 0 or name.startswith("- "):
        return None
    return name


def _yes_no(obj: Any) -> bool | None:
    name = _codebook_name(obj)
    if name == YES:
        return True
    if name == NO:
        return False
    return None


def _furnished(obj: Any) -> Furnished | None:
    name = _codebook_name(obj)
    if name == YES:
        return "full"
    if name == NO:
        return "none"
    return None  # a partial value has not been seen in the API yet


def _rent(detail: dict[str, Any]) -> int | None:
    price = _float(detail.get("price_czk"))
    if _codebook_name(detail.get("price_unit_cb")) != RENT_UNIT or price is None or price <= 0:
        return None
    return int(round(price))


def _address_detail(loc: dict[str, Any]) -> AddressDetail:
    lat, lon = _float(loc.get("gps_lat")), _float(loc.get("gps_lon"))
    gps = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return AddressDetail(
        street=_text(loc.get("street")),
        house_number=_text(loc.get("streetnumber")) or _text(loc.get("housenumber")),
        citypart=_text(loc.get("citypart")),
        district=_text(loc.get("district")),
        gps=gps,
        precision=PRECISION.get(_text(loc.get("inaccuracy_type")) or ""),
    )


def _address_line(ad: AddressDetail) -> str | None:
    street = ad.street
    if street and ad.house_number:
        street = f"{street} {ad.house_number}"
    parts = [part for part in (street, ad.citypart, ad.district) if part]
    return ", ".join(parts) or None


def _detail_url(loc: dict[str, Any], disposition: str | None, hid: int) -> str:
    """Public link built from the API's seo fields. Not checked in a browser (see research/sreality.md)."""
    slug = "-".join(
        part
        for part in (
            _text(loc.get("city_seo_name")),
            _text(loc.get("citypart_seo_name")),
            _text(loc.get("street_seo_name")),
        )
        if part
    )
    segments = ["detail", "pronajem", "byt"]
    if disposition:
        segments.append(disposition)
    if slug:
        segments.append(slug)
    segments.append(str(hid))
    return f"{SITE_BASE}/" + "/".join(segments)


def _contact(user: dict[str, Any], premise: dict[str, Any]) -> Contact | None:
    phone = None
    phones = user.get("user_phones")
    if isinstance(phones, list):
        for entry in phones:
            phone = _text(_dict(entry).get("phone"))
            if phone:
                break
    company = _dict(premise.get("company"))
    ico = _text(company.get("company_ic"))
    if ico is None and _int(company.get("company_ic")) is not None:
        ico = str(company["company_ic"])
    contact = Contact(
        name=_text(user.get("user_name")),
        agency=_text(premise.get("name")),
        ico=ico,
        email=_text(user.get("user_email")),
        phone=phone,
        form_url=None,
    )
    if all(value is None for value in contact.model_dump().values()):
        return None
    return contact


def _photos(images: Any) -> list[str]:
    urls: list[str] = []
    if not isinstance(images, list):
        return urls
    for entry in images:
        url = _text(_dict(entry).get("url") if isinstance(entry, dict) else entry)
        if url is None:
            continue
        urls.append("https:" + url if url.startswith("//") else url)
    return urls


def _poi(search: dict[str, Any]) -> Poi | None:
    if not any(str(key).startswith("poi_") for key in search):
        return None
    # tram_m stays None: the API has no tram distance. poi_bus_public_transport_distance is not mapped.
    return Poi(
        metro_m=_int(search.get("poi_metro_distance")),
        tram_m=None,
        shop_m=_int(search.get("poi_shop_distance")),
    )


def _area_from_title(title: Any) -> float | None:
    text = _text(title)
    match = AREA_RE.search(text) if text else None
    return float(match.group(1).replace(",", ".")) if match else None


def normalize_listing(raw: dict[str, Any], collected_at: datetime) -> Listing:
    """Pure: map one {"detail": result, "search": item} pair to a Listing. Raises ValueError if unusable."""
    detail = _dict(raw.get("detail"))
    search = _dict(raw.get("search"))
    if not detail:
        raise ValueError("raw has no detail object")
    hid = _int(detail.get("hash_id"))
    if hid is None:
        hid = _int(search.get("hash_id"))
    if hid is None:
        raise ValueError("missing hash_id")
    title = _text(detail.get("advert_name")) or _text(search.get("advert_name"))
    if title is None:
        raise ValueError("missing title")
    loc = _dict(detail.get("locality")) or _dict(search.get("locality"))
    disposition = _codebook_name(detail.get("category_sub_cb")) or _codebook_name(search.get("category_sub_cb"))
    address_detail = _address_detail(loc)
    return Listing(
        portal="sreality",
        source_id=str(hid),
        url=_detail_url(loc, disposition, hid),
        collected_at=collected_at,
        title=title,
        address=_address_line(address_detail),
        address_detail=address_detail,
        disposition=disposition,
        area_m2=_float(detail.get("usable_area")),
        floor=_int(detail.get("floor_number")),
        elevator=_yes_no(detail.get("elevator")),
        furnished=_furnished(detail.get("furnished")),
        rent=_rent(detail),
        price_note=_text(detail.get("price_note")),
        description=_text(detail.get("advert_description")),
        ready_date=_text(detail.get("ready_date")),
        ownership=_codebook_name(detail.get("ownership")),
        is_owner_listing=None,  # not in the API
        contact=_contact(_dict(detail.get("user")), _dict(detail.get("premise"))),
        photos=_photos(detail.get("advert_images")),
        poi=_poi(search),
        raw_ref=None,
    )


@dataclass(frozen=True)
class _Plan:
    district_ids: tuple[int, ...]
    cityparts: frozenset[str]
    dispositions: frozenset[str]
    sub_codes: tuple[int, ...]
    max_rent: int | None
    min_area: int | None

    def search_url(self, offset: int) -> str:
        parts = [
            "category_main_cb=1",
            "category_type_cb=2",
            "category_sub_cb=" + ",".join(str(code) for code in self.sub_codes),
            "locality_district_id=" + ",".join(str(i) for i in self.district_ids),
        ]
        if self.max_rent is not None:
            parts.append(f"price_to={self.max_rent}")
        parts += [f"limit={PAGE_SIZE}", f"offset={offset}"]
        return f"{API_BASE}/search?" + "&".join(parts)


def _make_plan(profile: SearchProfile, log: logging.Logger) -> _Plan:
    filters = profile.filters
    cityparts: set[str] = set()
    district_ids: set[int] = set()
    for location in filters.locations:
        if location.city != "Praha" or location.citypart not in CITYPART_DISTRICTS:
            log.warning("sreality: location not supported, skipped (city=%s)", location.city)
            continue
        cityparts.add(location.citypart)
        district_ids.update(DISTRICT_IDS[name] for name in CITYPART_DISTRICTS[location.citypart])
    if not cityparts:
        raise SourceError("sreality: no supported location in the profile")
    dispositions = {name for name in filters.dispositions if name in DISPOSITION_CODES}
    skipped = sorted(set(filters.dispositions) - dispositions)
    if skipped:
        log.warning("sreality: dispositions not mapped, skipped: %s", ", ".join(skipped))
    if not dispositions:
        raise SourceError("sreality: no supported disposition in the profile")
    return _Plan(
        district_ids=tuple(sorted(district_ids)),
        cityparts=frozenset(cityparts),
        dispositions=frozenset(dispositions),
        sub_codes=tuple(sorted(DISPOSITION_CODES[name] for name in dispositions)),
        max_rent=filters.max_rent,
        min_area=filters.min_area_m2,
    )


def _accepts_search_item(item: dict[str, Any], plan: _Plan) -> bool:
    """Cheap pre-filter on search data, before any detail request."""
    if _dict(item.get("locality")).get("citypart") not in plan.cityparts:
        return False
    if _codebook_name(item.get("category_sub_cb")) not in plan.dispositions:
        return False
    price = _float(item.get("price_czk"))
    if plan.max_rent is not None and price is not None and price > plan.max_rent:
        return False
    area = _area_from_title(item.get("advert_name"))
    if plan.min_area is not None and area is not None and area < plan.min_area:
        return False
    return True


def _accepts_listing(listing: Listing, plan: _Plan) -> bool:
    """Final filter on the normalized listing; unknown values are kept for the matcher to judge."""
    if listing.address_detail.citypart not in plan.cityparts:
        return False
    if plan.max_rent is not None and listing.rent is not None and listing.rent > plan.max_rent:
        return False
    if plan.min_area is not None and listing.area_m2 is not None and listing.area_m2 < plan.min_area:
        return False
    return True


def _round_robin(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave candidates by district, so one district does not fill the whole run."""
    buckets: dict[str, deque[dict[str, Any]]] = {}
    for item in items:
        key = _text(_dict(item.get("locality")).get("district")) or ""
        buckets.setdefault(key, deque()).append(item)
    ordered: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while any(buckets[key] for key in keys):
        for key in keys:
            if buckets[key]:
                ordered.append(buckets[key].popleft())
    return ordered


class _Pacer:
    """Enforces a minimum spacing between request starts, across search and detail calls."""

    def __init__(self, delay_sec: float) -> None:
        self._delay = delay_sec
        self._next_start = 0.0
        self._lock = asyncio.Lock()

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_start:
                await asyncio.sleep(self._next_start - now)
                now = time.monotonic()
            self._next_start = now + self._delay


async def _get_json(http: httpx.AsyncClient, pacer: _Pacer, url: str) -> dict[str, Any]:
    failure = "no attempt"
    for attempt in (1, 2):
        await pacer.wait_turn()
        try:
            response = await http.get(url, headers=HEADERS, follow_redirects=False, timeout=TIMEOUT_SEC)
        except httpx.HTTPError as exc:
            failure = type(exc).__name__
        else:
            status = response.status_code
            if 300 <= status < 400:
                raise SourceError(f"redirect refused (HTTP {status})")
            if status == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise SourceError("response is not JSON") from exc
                if not isinstance(payload, dict):
                    raise SourceError("unexpected JSON shape")
                return payload
            if status < 500:
                raise SourceError(f"HTTP {status}")
            failure = f"HTTP {status}"
        if attempt == 1:
            await asyncio.sleep(2.0)
    raise SourceError(f"request failed after retry ({failure})")


@dataclass
class SrealityRunStats:
    search_items: int = 0
    candidates: int = 0
    fetched: int = 0
    failed: int = 0
    filtered: int = 0
    search_error: str | None = None


async def _search(
    http: httpx.AsyncClient,
    pacer: _Pacer,
    plan: _Plan,
    log: logging.Logger,
    stats: SrealityRunStats,
    limit: int,
) -> list[dict[str, Any]]:
    target = max(limit * 2, limit + 10)
    seen: set[int] = set()
    candidates: list[dict[str, Any]] = []
    offset = 0
    for page in range(MAX_PAGES):
        try:
            payload = await _get_json(http, pacer, plan.search_url(offset))
            results = payload.get("results")
            if not isinstance(results, list):
                raise SourceError("unexpected search payload")
        except SourceError as exc:
            if page == 0:
                raise
            stats.search_error = str(exc)
            log.warning("sreality: search page %d failed (%s); keeping %d candidates", page, exc, len(candidates))
            break
        total = _int(_dict(payload.get("pagination")).get("total")) or 0
        for item in results:
            hid = _int(_dict(item).get("hash_id"))
            if hid is None or hid in seen:
                continue
            seen.add(hid)
            stats.search_items += 1
            if _accepts_search_item(item, plan):
                candidates.append(item)
        offset += len(results)
        if not results or offset >= total or len(candidates) >= target:
            break
    stats.candidates = len(candidates)
    return _round_robin(candidates)


async def _detail(http: httpx.AsyncClient, pacer: _Pacer, item: dict[str, Any]) -> dict[str, Any]:
    payload = await _get_json(http, pacer, f"{API_BASE}/{item['hash_id']}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SourceError("detail payload has no result object")
    return {"detail": result, "search": item}


class SrealitySource:
    """Source protocol (WP0): collect yields Listings, normalize is pure."""

    name: ClassVar[Portal] = "sreality"

    def __init__(self) -> None:
        self.last_stats = SrealityRunStats()

    def collect(self, profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
        return self._collect(profile, ctx)

    def normalize(self, raw: dict[str, Any], collected_at: datetime) -> Listing:
        return normalize_listing(raw, collected_at)

    async def _collect(self, profile: SearchProfile, ctx: SourceContext) -> AsyncIterator[Listing]:
        stats = self.last_stats = SrealityRunStats()
        limit = min(ctx.max_listings, profile.filters.max_listings)
        if limit <= 0:
            return
        plan = _make_plan(profile, ctx.log)
        pacer = _Pacer(min(max(ctx.delay_sec, 0.5), 1.0))
        candidates = await _search(ctx.http, pacer, plan, ctx.log, stats, limit)
        yielded = 0
        for start in range(0, len(candidates), CONCURRENCY):
            if yielded >= limit:
                break
            chunk = candidates[start : start + CONCURRENCY]
            outcomes = await asyncio.gather(
                *(_detail(ctx.http, pacer, item) for item in chunk), return_exceptions=True
            )
            for item, outcome in zip(chunk, outcomes):
                hid = item.get("hash_id")
                if isinstance(outcome, BaseException):
                    stats.failed += 1
                    ctx.log.warning("sreality: detail %s failed (%s)", hid, type(outcome).__name__)
                    continue
                try:
                    listing = normalize_listing(outcome, datetime.now(PRAGUE))
                except (KeyError, TypeError, ValueError) as exc:
                    stats.failed += 1
                    ctx.log.warning("sreality: detail %s could not be normalized (%s)", hid, type(exc).__name__)
                    continue
                if not _accepts_listing(listing, plan):
                    stats.filtered += 1
                    continue
                stats.fetched += 1
                yielded += 1
                yield listing
                if yielded >= limit:
                    break
