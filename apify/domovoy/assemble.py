"""FlatItem assembly: one Flat, its Extraction, Costs and Evaluation become one dataset item (actor.md, Output: dataset item)."""

from datetime import date, datetime

from domovoy.models import (
    Change,
    Costs,
    CrossSource,
    Evaluation,
    Extraction,
    ExtractionMeta,
    FieldEvidence,
    Flat,
    FlatItem,
    Listing,
    SearchProfile,
    SourceRef,
)

CHEAPER_ELSEWHERE = "cheaper on another portal"
EXTRACTION_META_FIELDS = frozenset({"provider", "model", "prompt_version", "status"})


def build_flat_item(
    flat: Flat,
    extraction: Extraction,
    costs: Costs,
    evaluation: Evaluation,
    *,
    profile: SearchProfile,
    run_id: str,
    change: Change,
    first_seen: datetime,
    last_seen: datetime,
    extraction_ran: bool,
) -> FlatItem:
    """One dataset item. extraction_ran False means extraction did not run, so the item's extraction is null."""
    primary = flat.primary
    risk_flags = list(evaluation.risk_flags)
    # The evaluator sees one listing only, so the cross-portal flag is added here from Flat.cross_source.
    if is_cheaper_elsewhere(flat.cross_source, primary) and CHEAPER_ELSEWHERE not in risk_flags:
        risk_flags.append(CHEAPER_ELSEWHERE)
    return FlatItem(
        property_id=flat.property_id,
        profile_id=profile.id,
        run_id=run_id,
        change=change,
        match=evaluation.match,
        url=primary.url,
        collected_at=primary.collected_at,
        title=primary.title,
        address=address_for(primary, profile),
        address_detail=primary.address_detail,
        disposition=primary.disposition,
        area_m2=primary.area_m2,
        floor=primary.floor,
        elevator=primary.elevator,
        furnished=primary.furnished if primary.furnished is not None else extraction.furnished.value,
        rent=costs.rent,
        services=costs.services,
        energy=costs.energy,
        total_monthly=costs.total_monthly,
        estimated=costs.estimated,
        kauce=costs.kauce,
        commission=costs.commission,
        one_time_fees=costs.one_time_fees,
        first_payment=costs.first_payment,
        upfront=costs.upfront,
        missing_furniture=costs.missing_furniture,
        missing_furniture_cost=costs.missing_furniture_cost,
        move_in_total=costs.move_in_total,
        move_in_note=costs.move_in_note,
        move_in_date=_date_or_none(extraction.move_in_date.value),
        lease_type=extraction.lease_type.value,
        lease_length_months=extraction.lease_length_months.value,
        pets_allowed=extraction.pets_allowed.value,
        permanent_residence=extraction.permanent_residence.value,
        unit_type_hint=extraction.unit_type_hint.value,
        evidence=evidence_for(extraction),
        unknowns=evaluation.unknowns,
        match_reasons=evaluation.match_reasons,
        requirements=evaluation.requirements,
        risk_flags=risk_flags,
        sources=[source_ref(listing, primary, costs) for listing in flat.sources],
        cross_source=flat.cross_source,
        image_url=primary.photos[0] if primary.photos else None,
        photos=primary.photos,
        poi=primary.poi,
        extraction=(
            ExtractionMeta(provider=extraction.provider, model=extraction.model, status=extraction.status)
            if extraction_ran
            else None
        ),
        first_seen=first_seen,
        last_seen=last_seen,
    )


def is_cheaper_elsewhere(cross: CrossSource, primary: Listing) -> bool:
    return cross.cheapest_portal is not None and cross.cheapest_portal != primary.portal


def address_for(listing: Listing, profile: SearchProfile) -> str:
    """Never empty: the listed address, then the title, then "Praha, <citypart>"."""
    for text in (listing.address, listing.title):
        if text and text.strip():
            return text.strip()
    citypart = listing.address_detail.citypart or next(
        (location.citypart for location in profile.filters.locations if location.citypart), None
    )
    return f"Praha, {citypart}" if citypart else "Praha"


def evidence_for(extraction: Extraction) -> list[FieldEvidence]:
    """One entry per extracted field that has a value."""
    entries: list[FieldEvidence] = []
    for name in Extraction.model_fields:
        if name in EXTRACTION_META_FIELDS:
            continue
        evidence = getattr(extraction, name)
        if evidence.value is not None:
            entries.append(FieldEvidence(field=name, quote=evidence.quote, confidence=evidence.confidence))
    return entries


def source_ref(listing: Listing, primary: Listing, costs: Costs) -> SourceRef:
    """Only the primary listing is extracted, so only its commission is known; the others stay null."""
    is_primary = (listing.portal, listing.source_id) == (primary.portal, primary.source_id)
    return SourceRef(
        portal=listing.portal,
        source_id=listing.source_id,
        url=listing.url,
        rent=listing.rent,
        commission=costs.commission if is_primary else None,
        is_owner_listing=listing.is_owner_listing,
        collected_at=listing.collected_at,
        contact=listing.contact,
    )


def _date_or_none(value: object) -> date | None:
    return value if isinstance(value, date) else None
