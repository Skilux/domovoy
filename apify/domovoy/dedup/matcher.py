"""Cross-portal matching and the merge into Flats (actor-implementation.md, section 3)."""

from collections.abc import Mapping
from typing import Any

from domovoy.dedup.keys import distance_m, listing_key, new_property_id, normalize_street
from domovoy.models import CrossSource, Flat, Listing, Portal, PropertyIdMap

PORTAL_PRIORITY: dict[Portal, int] = {"sreality": 0, "bezrealitky": 1, "idnes": 2}
AREA_TOLERANCE_M2 = 3.0
RENT_TOLERANCE_DIVISOR = 20  # 5 %: |a - b| * 20 <= max(a, b)
GPS_RADIUS_M = 150.0
# A lower-priority source fills these fields when the top listing has None.
FILLABLE = (
    "address", "disposition", "area_m2", "floor", "elevator", "furnished", "rent", "price_note",
    "description", "ready_date", "ownership", "is_owner_listing", "poi",
)


def same_flat(a: Listing, b: Listing) -> bool:
    """True when two listings from two portals describe one flat.

    A missing value never matches.
    """
    if a.portal == b.portal:
        return False
    if a.disposition is None or a.disposition != b.disposition:
        return False
    if a.area_m2 is None or b.area_m2 is None or abs(a.area_m2 - b.area_m2) > AREA_TOLERANCE_M2:
        return False
    if a.rent is None or b.rent is None:
        return False
    if abs(a.rent - b.rent) * RENT_TOLERANCE_DIVISOR > max(a.rent, b.rent):
        return False
    return _same_street(a, b) or _same_gps(a, b)


def _same_street(a: Listing, b: Listing) -> bool:
    street = normalize_street(a.address_detail.street)
    return street is not None and street == normalize_street(b.address_detail.street)


def _same_gps(a: Listing, b: Listing) -> bool:
    gps_a, gps_b = a.address_detail.gps, b.address_detail.gps
    return gps_a is not None and gps_b is not None and distance_m(gps_a, gps_b) <= GPS_RADIUS_M


def merge(listings: list[Listing], ids: PropertyIdMap) -> list[Flat]:
    """Group listings into flats, each with a stable property_id.

    `ids` maps "portal:source_id" to property_id. It is updated in place with every listing in the
    result, and the caller saves it. The input order does not matter: listings are taken in portal
    priority order, then by source_id, and a repeated portal:source_id counts once.
    """
    flats: list[Flat] = []
    claimed: set[str] = set()
    for members in _clusters(_ordered(listings)):
        property_id = _property_id_for(members, ids, claimed)
        claimed.add(property_id)
        for listing in members:
            ids[listing_key(listing)] = property_id
        flats.append(
            Flat(
                property_id=property_id,
                sources=members,
                primary=_primary(members),
                cross_source=cross_source(members),
            )
        )
    return flats


def cross_source(
    sources: list[Listing], commissions: Mapping[str, int | None] | None = None
) -> CrossSource:
    """Price and commission differences between the sources of one flat, in priority order.

    Each figure needs a value from every source, otherwise it is None (unknown). Commission is not
    on Listing, so the caller passes `commissions` (listing key to CZK) once extraction has run.
    """
    if len(sources) < 2:
        return CrossSource(cheapest_portal=None, commission_savings=None, price_spread=None)
    cheapest_portal = None
    price_spread = None
    priced: list[tuple[Portal, int]] = [(s.portal, s.rent) for s in sources if s.rent is not None]
    if len(priced) == len(sources):
        cheapest_portal = min(priced, key=lambda pair: pair[1])[0]  # first lowest wins a tie
        rents = [rent for _, rent in priced]
        price_spread = max(rents) - min(rents)
    commission_savings = None
    if commissions is not None:
        fees = [commissions.get(listing_key(s)) for s in sources]
        known = [fee for fee in fees if fee is not None]
        if len(known) == len(sources):
            commission_savings = max(known) - min(known)
    return CrossSource(
        cheapest_portal=cheapest_portal,
        commission_savings=commission_savings,
        price_spread=price_spread,
    )


def _ordered(listings: list[Listing]) -> list[Listing]:
    ordered = sorted(
        listings, key=lambda listing: (PORTAL_PRIORITY[listing.portal], listing.source_id)
    )
    seen: set[str] = set()
    unique: list[Listing] = []
    for listing in ordered:
        key = listing_key(listing)
        if key not in seen:
            seen.add(key)
            unique.append(listing)
    return unique


def _clusters(listings: list[Listing]) -> list[list[Listing]]:
    """Greedy grouping. A listing joins a flat only if it matches every member: a chain of
    near-matches cannot pull two flats together. A flat holds one listing per portal."""
    clusters: list[list[Listing]] = []
    for listing in listings:
        for members in clusters:
            if all(same_flat(listing, member) for member in members):
                members.append(listing)
                break
        else:
            clusters.append([listing])
    return clusters


def _property_id_for(members: list[Listing], ids: PropertyIdMap, claimed: set[str]) -> str:
    """The first existing id of a member that no earlier flat in this run has claimed. Otherwise a
    new id from the first key seen, salted until it is not claimed in this run."""
    for listing in members:
        existing = ids.get(listing_key(listing))
        if existing is not None and existing not in claimed:
            return existing
    first_key = listing_key(members[0])
    candidate = new_property_id(first_key)
    attempt = 0
    while candidate in claimed:
        attempt += 1
        candidate = new_property_id(f"{first_key}#{attempt}")
    return candidate


def _primary(members: list[Listing]) -> Listing:
    """The top-priority listing, with each missing field taken from the next source that has it.
    Contact stays with the source it came from."""
    top = members[0]
    updates: dict[str, Any] = {}
    for name in FILLABLE:
        if getattr(top, name) is None:
            value = next(
                (getattr(m, name) for m in members[1:] if getattr(m, name) is not None), None
            )
            if value is not None:
                updates[name] = value
    if not top.photos:
        photos = next((m.photos for m in members if m.photos), None)
        if photos is not None:
            updates["photos"] = photos
    return top.model_copy(update=updates)
