"""Cost math in Python (docs/prd/actor.md, Cost math). The model extracts; this module computes.

None means unknown and is never replaced by 0. A 0 appears only where the listing states
none: a stated "none" commission or deposit, energy in the rent, no missing furniture, no fees.
"""

from decimal import ROUND_HALF_UP, Decimal

from domovoy.costs.tables import FURNITURE_CZK, VAT_MULTIPLIER, energy_czk_per_m2
from domovoy.models import (
    Charge,
    Costs,
    Extraction,
    Furniture,
    Listing,
    OneTimeFee,
    SearchProfile,
)

# Order of the `estimated` list. A name appears only if its value is known and rests on an estimate.
ESTIMATED_ORDER = (
    "energy",
    "total_monthly",
    "hidden_monthly",
    "first_payment",
    "upfront",
    "missing_furniture_cost",
)


def compute_costs(listing: Listing, ex: Extraction, profile: SearchProfile) -> Costs:
    occupants = profile.household.occupants
    # The structured portal price. The extracted rent is only a cross-check, owned by WP4.
    rent = listing.rent
    services = _per_household(ex.services.value, occupants)
    energy, energy_estimated = _energy(ex.energy.value, listing.area_m2, occupants)
    total = _sum(rent, services, energy)
    hidden = _sum(services, energy) if total is not None else None
    kauce = _amount(ex.kauce.value, rent)
    commission = _commission(ex.commission.value, rent)
    one_time = _one_time_fees(ex.one_time_fees.value)
    first_payment = total
    upfront = _sum(first_payment, kauce, commission, one_time)
    furniture, furniture_cost = _missing_furniture(ex.missing_furniture.value)

    values: dict[str, int | None] = {
        "energy": energy,
        "total_monthly": total,
        "hidden_monthly": hidden,
        "first_payment": first_payment,
        "upfront": upfront,
        "missing_furniture_cost": furniture_cost,
    }
    depends_on_estimate = {
        "energy": energy_estimated,
        "total_monthly": energy_estimated,
        "hidden_monthly": energy_estimated,
        "first_payment": energy_estimated,
        "upfront": energy_estimated,
        # The furniture prices come from a table, so their total is an estimate.
        "missing_furniture_cost": bool(furniture),
    }
    estimated = [
        name
        for name in ESTIMATED_ORDER
        if depends_on_estimate[name] and values[name] is not None
    ]
    return Costs(
        rent=rent,
        services=services,
        energy=energy,
        total_monthly=total,
        kauce=kauce,
        commission=commission,
        one_time_fees=one_time,
        first_payment=first_payment,
        upfront=upfront,
        missing_furniture=furniture,
        missing_furniture_cost=furniture_cost,
        hidden_monthly=hidden,
        estimated=estimated,
    )


def _czk(value: Decimal) -> int:
    """Round half up to whole CZK. Decimal, not float, so that 23000 × 1.21 is exactly 27830."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _sum(*parts: int | None) -> int | None:
    """Sum of the parts, or None when any part is unknown."""
    known = [part for part in parts if part is not None]
    return sum(known) if len(known) == len(parts) else None


def _per_household(charge: Charge | None, occupants: int) -> int | None:
    """A stated monthly charge. A per-person amount is multiplied by the household size."""
    if charge is None or charge.czk is None:
        return None
    return charge.czk * occupants if charge.per_person else charge.czk


def _energy(
    charge: Charge | None, area_m2: float | None, occupants: int
) -> tuple[int | None, bool]:
    """Energy on top of the rent, and whether that figure is an estimate."""
    if charge is not None and charge.included:
        return 0, False  # the listing says energy is already in the rent
    stated = _per_household(charge, occupants)
    if stated is not None:
        return stated, False
    if area_m2 is None:
        return None, False
    # Table rate × area. The table is per flat, so it is not multiplied by occupants.
    return _czk(Decimal(str(area_m2)) * energy_czk_per_m2(area_m2)), True


def _amount(charge: Charge | None, rent: int | None) -> int | None:
    """Stated amount of a deposit or commission, or N × rent when the listing gives a multiple of rent."""
    if charge is None:
        return None
    if charge.czk is not None:
        return charge.czk
    if charge.rent_multiple is not None and rent is not None:
        return charge.rent_multiple * rent
    return None


def _commission(charge: Charge | None, rent: int | None) -> int | None:
    if charge is None:
        return None
    amount = _amount(charge, rent)
    if amount is None:
        return None
    return _czk(Decimal(amount) * VAT_MULTIPLIER) if charge.vat_extra else amount


def _one_time_fees(fees: list[OneTimeFee] | None) -> int | None:
    """Sum of the stated one-time fees. An empty list means the listing states none."""
    if fees is None:
        return None
    return _sum(*(fee.czk for fee in fees))


def _missing_furniture(items: list[Furniture] | None) -> tuple[list[str], int | None]:
    """Missing items, each counted once, and their table cost. None: the listing does not say."""
    if items is None:
        return [], None
    unique = list(dict.fromkeys(items))
    names: list[str] = list(unique)
    return names, sum(FURNITURE_CZK[item] for item in unique)
