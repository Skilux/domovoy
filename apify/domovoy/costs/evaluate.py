"""Requirement verdicts, match, unknowns and risk flags (docs/prd/actor.md: Requirements and match).

Verdicts use the extracted values as they are. An unverified value is still used, and the flat gets
the "extraction unverified" risk flag so Claude can check it. A value over a cap only because of
estimated energy is unknown (estimated), not a fail, and gets the "over budget (est.)" flag.
"""

from datetime import date
from typing import Any

from domovoy.models import (
    Costs,
    Evaluation,
    Evidence,
    Extraction,
    LeaseType,
    Listing,
    Match,
    Requirements,
    SearchProfile,
    Verdict,
    VerdictValue,
)

# ASSUMPTION, not sourced in actor.md: a lease shorter than a year is flagged as a short lease.
SHORT_LEASE_MONTHS = 12

_LEASE_NAMES: dict[LeaseType, str] = {
    "najem": "a regular lease",
    "podnajem": "a sublet",
}


def evaluate(
    listing: Listing, ex: Extraction, costs: Costs, profile: SearchProfile
) -> Evaluation:
    verdicts = _verdicts(listing, ex, costs, profile.requirements)
    return Evaluation(
        match=_match(verdicts),
        requirements=verdicts,
        unknowns=_unknowns(listing, ex, costs, profile.requirements),
        match_reasons=[
            verdict.reason for verdict in verdicts if verdict.verdict == "pass"
        ],
        risk_flags=_risk_flags(ex, costs, verdicts),
    )


def _verdict(
    name: str, verdict: VerdictValue, reason: str, estimated: bool = False
) -> Verdict:
    return Verdict(name=name, verdict=verdict, estimated=estimated, reason=reason)


def _verdicts(
    listing: Listing, ex: Extraction, costs: Costs, req: Requirements
) -> list[Verdict]:
    # Energy is the only estimate inside total_monthly and upfront.
    energy_estimate = (costs.energy or 0) if "energy" in costs.estimated else 0
    # Lower bounds from the known, stated parts only (estimated energy left out). They decide a cap
    # check when the full value is unknown: a known part already over the cap is a fail.
    stated_energy = 0 if "energy" in costs.estimated else costs.energy
    monthly_floor = _known_sum(costs.rent, costs.services, stated_energy)
    fees = ex.one_time_fees.value or []
    upfront_floor = monthly_floor + _known_sum(
        costs.kauce, costs.commission, *(fee.czk for fee in fees)
    )
    verdicts = [
        _cap_verdict(
            "max_total_monthly",
            "Total monthly cost",
            costs.total_monthly,
            req.max_total_monthly,
            "total_monthly" in costs.estimated,
            energy_estimate,
            monthly_floor,
        )
    ]
    if req.max_upfront is not None:
        verdicts.append(
            _cap_verdict(
                "max_upfront",
                "Upfront cost",
                costs.upfront,
                req.max_upfront,
                "upfront" in costs.estimated,
                energy_estimate,
                upfront_floor,
            )
        )
    if req.elevator == "required":
        verdicts.append(_elevator_verdict(listing.elevator))
    if req.lease_types:
        verdicts.append(_lease_verdict(ex.lease_type.value, req.lease_types))
    if req.move_in_by is not None:
        verdicts.append(_move_in_verdict(ex.move_in_date.value, req.move_in_by))
    if req.pets_allowed is not None:
        verdicts.append(_pets_verdict(ex.pets_allowed.value, req.pets_allowed))
    return verdicts


def _cap_verdict(
    name: str,
    label: str,
    value: int | None,
    cap: int,
    estimated: bool,
    energy_estimate: int,
    floor: int,
) -> Verdict:
    """`estimated`: the value includes estimated energy, worth `energy_estimate` CZK.

    Over the cap only because of that estimate is unknown, not a fail (decision 13 Nov): the call
    can ask about energy, so the flat lands in needs_info. When the value is unknown, `floor` (the
    sum of its known stated parts) over the cap is still a fail.
    """
    if value is None:
        if floor > cap:
            return _verdict(
                name,
                "fail",
                f"{label} is at least {floor:,} CZK from stated costs, above the {cap:,} CZK limit",
            )
        return _verdict(name, "unknown", f"{label} is unknown")
    note = " (estimated)" if estimated else ""
    if value <= cap:
        return _verdict(
            name,
            "pass",
            f"{label} {value:,} CZK is within the {cap:,} CZK limit{note}",
            estimated,
        )
    if estimated and value - energy_estimate <= cap:
        return _verdict(
            name,
            "unknown",
            f"{label} {value:,} CZK is over the {cap:,} CZK limit only with estimated energy",
            True,
        )
    return _verdict(
        name,
        "fail",
        f"{label} {value:,} CZK is above the {cap:,} CZK limit{note}",
        estimated,
    )


def _known_sum(*parts: int | None) -> int:
    """Sum of the known parts; unknown parts count as nothing (a lower bound, never shown as a cost)."""
    return sum(part for part in parts if part is not None)


def _elevator_verdict(elevator: bool | None) -> Verdict:
    if elevator is None:
        return _verdict("elevator", "unknown", "Elevator is not stated")
    if elevator:
        return _verdict("elevator", "pass", "Has an elevator")
    return _verdict("elevator", "fail", "No elevator")


def _lease_verdict(lease: LeaseType | None, wanted: list[LeaseType]) -> Verdict:
    if lease is None:
        return _verdict("lease_types", "unknown", "Lease type is not stated")
    if lease in wanted:
        return _verdict("lease_types", "pass", f"Lease is {_LEASE_NAMES[lease]}")
    wanted_names = " or ".join(_LEASE_NAMES[item] for item in wanted)
    return _verdict(
        "lease_types",
        "fail",
        f"Lease is {_LEASE_NAMES[lease]}, profile wants {wanted_names}",
    )


def _move_in_verdict(move_in: date | str | None, deadline: date) -> Verdict:
    if move_in == "immediately":
        return _verdict(
            "move_in_by",
            "pass",
            f"Available immediately, before {deadline.isoformat()}",
        )
    if isinstance(move_in, date):
        if move_in <= deadline:
            return _verdict(
                "move_in_by",
                "pass",
                f"Move-in {move_in.isoformat()} is by {deadline.isoformat()}",
            )
        return _verdict(
            "move_in_by",
            "fail",
            f"Move-in {move_in.isoformat()} is after {deadline.isoformat()}",
        )
    reason = (
        "Move-in date is by agreement, not fixed"
        if move_in == "by agreement"
        else "Move-in date is not stated"
    )
    return _verdict("move_in_by", "unknown", reason)


def _pets_verdict(pets: bool | None, wanted: bool) -> Verdict:
    if pets is None:
        return _verdict("pets_allowed", "unknown", "Pet policy is not stated")
    if pets == wanted:
        return _verdict("pets_allowed", "pass", f"Pets allowed: {_yes_no(pets)}")
    return _verdict(
        "pets_allowed",
        "fail",
        f"Pets allowed: {_yes_no(pets)}, profile wants {_yes_no(wanted)}",
    )


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def _match(verdicts: list[Verdict]) -> Match:
    if any(verdict.verdict == "fail" for verdict in verdicts):
        return "rejected"
    if all(verdict.verdict == "pass" for verdict in verdicts):
        return "strong"
    return "needs_info"


def _unknowns(
    listing: Listing, ex: Extraction, costs: Costs, req: Requirements
) -> list[str]:
    """One plain-English question per unknown topic, in call order. Each topic adds one line.

    Every unknown verdict is covered here: a verdict is unknown only when one of these topics is.
    """
    lines: list[str] = []
    if costs.rent is None:
        lines.append("What is the monthly rent?")
    if costs.services is None:
        lines.append(
            "What are the monthly service fees, and are they per flat or per person?"
        )
    if costs.energy is None or "energy" in costs.estimated:
        lines.append(
            "Are energy costs included in the rent? If not, what is the monthly energy advance?"
        )
    if costs.kauce is None:
        lines.append("How much is the deposit?")
    if costs.commission is None:
        lines.append("What is the agency commission, and is VAT added on top?")
    elif (
        costs.commission
        and ex.commission.value is not None
        and ex.commission.value.vat_extra is None
    ):
        lines.append("Is VAT added on top of the agency commission?")
    if costs.one_time_fees is None:
        lines.append("Are there one-time fees at move-in, and how much are they?")
    if costs.missing_furniture_cost is None:
        lines.append(
            "Which of these are missing from the flat: bed, wardrobe, fridge, washing machine, "
            "stove, sofa, dining table, desk?"
        )
    if ex.lease_type.value is None:
        lines.append("Is the lease a regular lease or a sublet?")
    move_in = ex.move_in_date.value
    if move_in is None:
        lines.append("What is the earliest move-in date?")
    elif move_in == "by agreement":
        lines.append("Is the move-in date fixed, or only by agreement?")
    if req.elevator == "required" and listing.elevator is None:
        lines.append("Is there a lift (elevator) in the building?")
    if req.pets_allowed is not None and ex.pets_allowed.value is None:
        lines.append("Are pets allowed?")
    return lines


def _risk_flags(ex: Extraction, costs: Costs, verdicts: list[Verdict]) -> list[str]:
    flags: list[str] = []
    if ex.lease_type.value == "podnajem":
        flags.append("sublet")
    if (
        ex.unit_type_hint.value in ("studio", "non-residential")
        or ex.permanent_residence.value is False
    ):
        flags.append("possible studio / no permanent residence")
    if ex.commission.value is not None and ex.commission.value.vat_extra:
        flags.append("commission + VAT")
    # Only a cap check is unknown and estimated: over the cap only because of estimated energy.
    if any(v.verdict == "unknown" and v.estimated for v in verdicts):
        flags.append("over budget (est.)")
    # costs.one_time_fees is None when the fees are not stated or any fee has no amount.
    if costs.services is None or costs.one_time_fees is None:
        flags.append("fees not stated")
    if (
        ex.lease_length_months.value is not None
        and ex.lease_length_months.value < SHORT_LEASE_MONTHS
    ):
        flags.append("short lease")
    if any(field.value is not None and not field.verified for field in _evidence(ex)):
        flags.append("extraction unverified")
    return flags


def _evidence(ex: Extraction) -> list[Evidence[Any]]:
    return [
        ex.rent,
        ex.services,
        ex.energy,
        ex.kauce,
        ex.commission,
        ex.one_time_fees,
        ex.move_in_date,
        ex.lease_type,
        ex.lease_length_months,
        ex.furnished,
        ex.missing_furniture,
        ex.pets_allowed,
        ex.permanent_residence,
        ex.unit_type_hint,
    ]
