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

    Persisted identity wins over fuzzy matching. A listing whose "portal:source_id" is in `ids`
    keeps its property_id, and listings that share one stay one flat, even when their attributes
    have drifted. A new listing joins an established id only if no key of its own portal holds
    that id in `ids`, absent listings included, and it matches one of the listings present.
    Otherwise it joins another match or gets a new id. Established ids are never merged or
    reassigned. `ids` is updated in place with the new listings, and the caller saves it. The
    input order does not matter.
    """
    ordered = _ordered(listings)
    established: dict[str, list[Listing]] = {}
    for listing in ordered:
        known = ids.get(listing_key(listing))
        if known is not None:
            established.setdefault(known, []).append(listing)
    fresh = [listing for listing in ordered if listing_key(listing) not in ids]
    in_use = set(ids.values())
    clusters = _place_fresh(fresh, established, _portals_by_id(ids), ids)
    flats = [_flat(property_id, members) for property_id, members in established.items()]
    for members in clusters:
        property_id = _fresh_property_id(listing_key(members[0]), in_use)
        in_use.add(property_id)
        for listing in members:
            ids[listing_key(listing)] = property_id
        flats.append(_flat(property_id, members))
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


def _rank(listing: Listing) -> tuple[int, str]:
    """Portal priority, then source_id: the order in which listings are taken."""
    return (PORTAL_PRIORITY[listing.portal], listing.source_id)


def _ordered(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    unique: list[Listing] = []
    for listing in sorted(listings, key=_rank):
        key = listing_key(listing)
        if key not in seen:
            seen.add(key)
            unique.append(listing)
    return unique


def _place_fresh(
    fresh: list[Listing],
    established: dict[str, list[Listing]],
    portals: dict[str, set[str]],
    ids: PropertyIdMap,
) -> list[list[Listing]]:
    """New listings join an established id when they may. The rest group among themselves.

    The grouping is greedy: a listing joins a group only if it matches every member, so a chain of
    near-matches cannot pull two flats together. A group holds one listing per portal.
    """
    clusters: list[list[Listing]] = []
    for listing in fresh:
        joined = _joinable_id(listing, established, portals)
        if joined is not None:
            established[joined].append(listing)
            portals[joined].add(listing.portal)
            ids[listing_key(listing)] = joined
            continue
        for members in clusters:
            if all(same_flat(listing, member) for member in members):
                members.append(listing)
                break
        else:
            clusters.append([listing])
    return clusters


def _joinable_id(
    listing: Listing, established: dict[str, list[Listing]], portals: dict[str, set[str]]
) -> str | None:
    """The first established id this new listing may join, or None.

    `portals` holds, per id, the portals of every key in the persisted map, so a same-portal key
    blocks the join whether or not its listing is in this run. A listing that joins earlier in this
    run is added to `portals` as it joins. One match is enough: the listings of an established flat
    may have drifted apart, and requiring all of them would split the flat.
    """
    for property_id, members in established.items():
        if listing.portal in portals[property_id]:
            continue
        if any(same_flat(listing, member) for member in members):
            return property_id
    return None


def _portals_by_id(ids: PropertyIdMap) -> dict[str, set[str]]:
    """The portals of every key in the persisted map, grouped by the id each key holds."""
    portals: dict[str, set[str]] = {}
    for key, property_id in ids.items():
        portals.setdefault(property_id, set()).add(key.partition(":")[0])
    return portals


def _fresh_property_id(first_key: str, in_use: set[str]) -> str:
    """A new id from the first key seen, salted until it equals no id in use.

    In use: every persisted id, including those of listings absent from this run, and the ids given
    out in this run.
    """
    candidate = new_property_id(first_key)
    attempt = 0
    while candidate in in_use:
        attempt += 1
        candidate = new_property_id(f"{first_key}#{attempt}")
    return candidate


def _flat(property_id: str, members: list[Listing]) -> Flat:
    ranked = sorted(members, key=_rank)
    return Flat(
        property_id=property_id,
        sources=ranked,
        primary=_primary(ranked),
        cross_source=cross_source(ranked),
    )


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
