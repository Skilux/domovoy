"""Notion sink for the DOMOVOY shortlist: schema check, upsert by Property ID, page body once, paced requests.

WP7. The contract is domovoy/schemas/notion_contract.json, a copy of skill/domovoy/reference/ (drift test in
tests/test_notion_sink.py). The Actor writes the properties the contract marks as owned by "actor". Status is set
on page creation only. Reason, Notes, Viewing date and the page body are never written after creation.
Listing text is data: it is written as text and never interpreted. Contact details go only to properties.
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from domovoy.models import FlatItem, SourceRef, UpsertResult

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "schemas" / "notion_contract.json"
CONTRACT: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
API = "https://api.notion.com/v1"
VERSION: str = CONTRACT["notion_api_version"]
UPSERT_KEY: str = CONTRACT["upsert_key"]
PROPERTIES: dict[str, dict[str, Any]] = CONTRACT["properties"]
CREATE_ONLY = [name for name, spec in PROPERTIES.items() if spec.get("actor_writes") == "create"]
OWNED_ON_UPDATE = [
    name for name, spec in PROPERTIES.items() if spec["owner"] == "actor" and spec.get("actor_writes") != "create"
]
SHORTLISTED = "Shortlisted"
LEASE_NAMES = {value: label for label, value in CONTRACT["call_context_values"]["lease_type"].items() if value}
MATCH_NAMES = {"strong": "Strong", "needs_info": "Needs info"}
FURNISHED_NAMES = {"full": "Yes", "partial": "Partly", "none": "No"}
PORTAL_NAMES = {"sreality": "Sreality", "bezrealitky": "Bezrealitky", "idnes": "iDNES"}
TEXT_LIMIT = 2000  # Notion: characters per rich text object
# Caps keep one create request under Notion's 100 top-level blocks (89 at most, with every cap reached). A flat has at
# most one source link per portal (3 today), so the source cap of 10 never drops a link from a real item.
BODY_LIMITS = {"photos": 12, "reasons": 20, "quotes": 20, "unknowns": 20, "sources": 10}
RATE_PER_SECOND = 3.0
MAX_RETRIES = 5
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?420\s?)?\d{3}\s?\d{3}\s?\d{3}(?!\d)")


class SchemaDrift(RuntimeError):
    """The live database does not match notion_contract.json. Raised before anything is scraped."""


class NotionError(RuntimeError):
    """A Notion call failed. It carries the method, path, HTTP status and Notion's error code, and nothing else from
    the reply. Notion's free-text message is never kept: validation messages can echo the submitted values, and those
    include realtor contacts, which would then reach logs and tracebacks (WP7 review, fix round 1)."""

    def __init__(self, message: str, *, method: str = "", path: str = "", status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.method = method
        self.path = path
        self.status = status
        self.code = code


class Throttle:
    """Spaces requests at `rate` per second. Slots are reserved under a lock, so concurrent callers queue up.

    One sink, one throttle: the pipeline's per-flat tasks share the sink, so the run stays at `rate` in total.
    pause() sets a shared cooldown. A caller that already holds a slot rechecks it right before dispatch and, if a
    cooldown started while it waited, reserves a new slot after the cooldown, still spaced at `rate`.
    """

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._next_slot = 0.0
        self._cooldown_until = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                slot = max(now, self._next_slot, self._cooldown_until)
                self._next_slot = slot + self._interval
            if slot > now:
                await asyncio.sleep(slot - now)
            if time.monotonic() >= self._cooldown_until:
                return

    def pause(self, seconds: float) -> None:
        """Hold every caller, queued ones included: no request starts before `seconds` from now."""
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)


def option_name(name: str) -> str:
    """Notion option names hold no commas and at most 100 characters."""
    return name.replace(",", ";")[:100]


def _text(text: str | None) -> list[dict[str, Any]]:
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + TEXT_LIMIT]}} for i in range(0, len(text), TEXT_LIMIT)]


def _select(name: str | None) -> dict[str, Any]:
    return {"select": {"name": option_name(name)} if name else None}


def _multi(names: list[str]) -> dict[str, Any]:
    return {"multi_select": [{"name": option_name(n)} for n in dict.fromkeys(names) if n]}


def _money(value: int | None, estimated: bool = False) -> str:
    if value is None:
        return "unknown"
    return "{:,} CZK{}".format(value, " (est.)" if estimated else "")


def scrub(text: str) -> str:
    """Quotes come from listing text. Emails and phone numbers stay out of the page body."""
    return PHONE.sub("<phone>", EMAIL.sub("<email>", text))


def _primary(item: FlatItem) -> SourceRef | None:
    """The source whose URL is the item's URL. Contact and owner-listing fields come from it."""
    return next((s for s in item.sources if s.url == item.url), item.sources[0] if item.sources else None)


def _yes_no_unknown(value: bool | None) -> str:
    return "Unknown" if value is None else ("Yes" if value else "No")


def _name(item: FlatItem) -> str:
    place = ", ".join(p for p in [item.address_detail.citypart, item.address_detail.street] if p)
    area = None if item.area_m2 is None else "{:g} m²".format(item.area_m2)
    return " · ".join(p for p in [item.disposition, area, place] if p) or item.title


def owned_values(item: FlatItem) -> dict[str, dict[str, Any]]:
    """Values for every property the Actor owns, except the create-only ones (Status)."""
    primary = _primary(item)
    contact = primary.contact if primary else None
    return {
        "Name": {"title": _text(_name(item))},
        "Property ID": {"rich_text": _text(item.property_id)},
        "Profiles": _multi([item.profile_id]),
        "Match": _select(MATCH_NAMES[item.match]),
        "Disposition": _select(item.disposition),
        "Citypart": _select(item.address_detail.citypart),
        "Area m²": {"number": item.area_m2},
        "Floor": {"number": item.floor},
        "Metro m": {"number": item.poi.metro_m if item.poi else None},
        "Elevator": _select(_yes_no_unknown(item.elevator)),
        "Furnished": _select(FURNISHED_NAMES.get(item.furnished or "", "Unknown")),
        "Address": {"rich_text": _text(item.address)},
        "Rent": {"number": item.rent},
        "Services": {"number": item.services},
        "Energy": {"number": item.energy},
        "Total monthly": {"number": item.total_monthly},
        "Kauce": {"number": item.kauce},
        "Commission": {"number": item.commission},
        "Upfront": {"number": item.upfront},
        "Missing furniture cost": {"number": item.missing_furniture_cost},
        "Estimated": _multi(item.estimated),
        "Lease type": _select(LEASE_NAMES.get(item.lease_type or "", "Unknown")),
        "Move-in date": {"date": {"start": item.move_in_date.isoformat()} if item.move_in_date else None},
        "Unknowns": {"rich_text": _text("\n".join(item.unknowns))},
        "Risk flags": _multi(item.risk_flags),
        "Sources": _multi([PORTAL_NAMES[s.portal] for s in item.sources]),
        "URL": {"url": item.url},
        "Collected at": {"date": {"start": item.collected_at.isoformat()}},
        "First seen": {"date": {"start": item.first_seen.isoformat()}},
        "Last seen": {"date": {"start": item.last_seen.isoformat()}},
        "Agency": {"rich_text": _text(contact.agency if contact else None)},
        "Contact": {"rich_text": _text(contact.name if contact else None)},
        "Email": {"email": contact.email if contact else None},
        "Phone": {"phone_number": contact.phone if contact else None},
        "Owner listing": {"checkbox": bool(primary and primary.is_owner_listing)},
    }


def _block(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: payload}


def _heading(text: str) -> dict[str, Any]:
    return _block("heading_2", {"rich_text": _text(text)})


def _paragraph(text: str) -> dict[str, Any]:
    return _block("paragraph", {"rich_text": _text(text)})


def _bullet(text: str) -> dict[str, Any]:
    return _block("bulleted_list_item", {"rich_text": _text(text)})


def _quote(text: str) -> dict[str, Any]:
    return _block("quote", {"rich_text": _text(text)})


def _image(url: str) -> dict[str, Any]:
    return _block("image", {"type": "external", "external": {"url": url}})


def _cost_table(item: FlatItem) -> dict[str, Any]:
    estimated = set(item.estimated)
    rows = [
        ("Rent", item.rent, False),
        ("Services", item.services, "services" in estimated),
        ("Energy", item.energy, "energy" in estimated),
        ("Total monthly", item.total_monthly, "total_monthly" in estimated),
        ("Kauce (deposit)", item.kauce, False),
        ("Commission", item.commission, False),
        ("One-time fees", item.one_time_fees, False),
        ("First payment", item.first_payment, False),
        ("Upfront", item.upfront, False),
        ("Missing furniture cost", item.missing_furniture_cost, False),
    ]
    table_rows = [("Item", "Amount")] + [(label, _money(value, est)) for label, value, est in rows]
    children = [
        {"object": "block", "type": "table_row", "table_row": {"cells": [_text(cell) for cell in row]}}
        for row in table_rows
    ]
    return _block("table", {"table_width": 2, "has_column_header": True, "has_row_header": False,
                            "children": children})


def _source_line(source: SourceRef) -> str:
    return "%s: %s, rent %s, commission %s, collected %s" % (
        PORTAL_NAMES[source.portal], source.url, _money(source.rent), _money(source.commission),
        source.collected_at.isoformat())


def body_blocks(item: FlatItem) -> list[dict[str, Any]]:
    """The page body, written once with the page. Contact details never appear here."""
    blocks: list[dict[str, Any]] = []
    if item.photos:
        blocks.append(_heading("Photos"))
        blocks += [_image(url) for url in item.photos[:BODY_LIMITS["photos"]]]
    blocks.append(_heading("Why it matches"))
    reasons = [_bullet(text) for text in item.match_reasons[:BODY_LIMITS["reasons"]]]
    blocks += reasons or [_paragraph("No match reasons recorded.")]
    blocks += [_heading("Costs"), _cost_table(item)]
    blocks.append(_heading("Quotes"))
    quotes = [e for e in item.evidence if e.quote][:BODY_LIMITS["quotes"]]
    blocks += [_quote('%s: "%s" (confidence %.2f)' % (e.field, scrub(e.quote or ""), e.confidence)) for e in quotes]
    if not quotes:
        blocks.append(_paragraph("No verified quotes."))
    blocks.append(_heading("Unknowns"))
    blocks += [_bullet(text) for text in item.unknowns[:BODY_LIMITS["unknowns"]]] or [_paragraph("None.")]
    blocks.append(_heading("Sources"))
    blocks += [_bullet(_source_line(s)) for s in item.sources[:BODY_LIMITS["sources"]]]
    return blocks


def schema_problems(live: dict[str, Any]) -> list[str]:
    """Differences between the live properties and the contract. An empty list means a match."""
    problems: list[str] = []
    for name, spec in PROPERTIES.items():
        have = live.get(name)
        if have is None:
            problems.append("%s is missing (the contract needs %s)" % (name, spec["type"]))
            continue
        if have.get("type") != spec["type"]:
            problems.append("%s is %s (the contract needs %s)" % (name, have.get("type"), spec["type"]))
            continue
        if spec["type"] in ("select", "multi_select"):
            known = {option["name"] for option in have[spec["type"]].get("options", [])}
            problems += ["%s has no option %r" % (name, option)
                         for option in spec.get("options", []) if option not in known]
    return problems


def _retry_after(response: httpx.Response, fallback: float) -> float:
    try:
        return min(float(response.headers["Retry-After"]), 60.0)
    except (KeyError, ValueError):
        return min(fallback, 60.0)


ERROR_CODE = re.compile(r"[a-z_]{1,40}")  # Notion codes are slugs such as validation_error and rate_limited


def _error_code(response: httpx.Response) -> str:
    """Notion's error code, or "unknown". Only a plain slug counts; the reply's message is never read into the error."""
    try:
        data = response.json()
    except ValueError:
        return "unknown"
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) and ERROR_CODE.fullmatch(code) else "unknown"


class NotionSink:
    def __init__(self, token: str, data_source_id: str, *, client: httpx.AsyncClient | None = None,
                 rate: float = RATE_PER_SECOND, max_retries: int = MAX_RETRIES, retry_base: float = 1.0) -> None:
        self.data_source_id = data_source_id
        self.max_retries = max_retries
        self.retry_base = retry_base
        self._headers = {"Authorization": "Bearer " + token, "Notion-Version": VERSION,
                         "Content-Type": "application/json"}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._throttle = Throttle(rate)

    async def __aenter__(self) -> "NotionSink":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """One paced call. A 429 pauses the shared throttle for Retry-After (or a backoff), up to max_retries times."""
        attempt = 0
        while True:
            await self._throttle.wait()
            response = await self._client.request(method, API + path, json=body, headers=self._headers)
            if response.status_code != 429 or attempt >= self.max_retries:
                break
            self._throttle.pause(_retry_after(response, self.retry_base * 2 ** attempt))
            attempt += 1
        if response.status_code >= 400:
            code = _error_code(response)
            raise NotionError("Notion %s %s failed: HTTP %d %s" % (method, path, response.status_code, code),
                              method=method, path=path, status=response.status_code, code=code)
        return response.json()

    async def validate(self) -> None:
        """Compare the live schema with the contract. Call before scraping."""
        live = (await self._request("GET", "/data_sources/%s" % self.data_source_id))["properties"]
        problems = schema_problems(live)
        if problems:
            raise SchemaDrift("the Notion database does not match notion_contract.json: " + "; ".join(problems))

    async def _find_page(self, property_id: str) -> str | None:
        query = {"filter": {"property": UPSERT_KEY, "rich_text": {"equals": property_id}}, "page_size": 2}
        found = (await self._request("POST", "/data_sources/%s/query" % self.data_source_id, query))["results"]
        if len(found) > 1:
            raise NotionError("two pages have %s = %s; fix the database before the next run"
                              % (UPSERT_KEY, property_id))
        return found[0]["id"] if found else None

    def _create_body(self, item: FlatItem) -> dict[str, Any]:
        properties = owned_values(item)
        properties["Status"] = _select(SHORTLISTED)
        body: dict[str, Any] = {
            "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
            "properties": properties,
            "children": body_blocks(item),
        }
        if item.photos:
            body["cover"] = {"type": "external", "external": {"url": item.photos[0]}}
        return body

    async def upsert(self, item: FlatItem) -> UpsertResult:
        """Create the page for this flat, or update the Actor's properties on the existing page."""
        if item.match == "rejected":
            raise ValueError("rejected flats never reach Notion (actor.md: hard fails stay in the dataset)")
        page_id = await self._find_page(item.property_id)
        if page_id is None:
            page = await self._request("POST", "/pages", self._create_body(item))
            return UpsertResult(page_id=page["id"], action="created")
        values = owned_values(item)
        await self._request("PATCH", "/pages/%s" % page_id,
                            {"properties": {name: values[name] for name in OWNED_ON_UPDATE}})
        return UpsertResult(page_id=page_id, action="updated")
