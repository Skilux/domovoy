"""Fixed tables for the cost math (docs/prd/actor.md, Cost math).

Every value is an assumption unless its comment says it is a fact. The team sanity-checks both tables
before the demo. Furniture prices never come from the model.
"""

from decimal import Decimal
from typing import Final

from domovoy.models import Furniture

# Energy advance estimate, CZK per m² per month, by flat area.
# Used only when the listing gives no energy amount and does not say energy is in the rent.
# Each row is (largest area in m² for the band, or None for no upper limit; CZK per m² per month).
# ASSUMPTION, not sourced: a rough planning figure for heating, hot water and electricity in a Prague
# rental flat. The rate falls as the flat grows, because fixed costs are spread over more m².
ENERGY_CZK_PER_M2_BANDS: Final[tuple[tuple[float | None, Decimal], ...]] = (
    (40, Decimal(50)),  # up to 40 m²: ASSUMPTION
    (60, Decimal(40)),  # 41 to 60 m²: ASSUMPTION
    (90, Decimal(35)),  # 61 to 90 m²: ASSUMPTION
    (None, Decimal(32)),  # above 90 m²: ASSUMPTION
)

# One-off purchase price in CZK for each furniture item a listing can leave out.
# ASSUMPTION, not sourced: a rough mid-range price for a new item in Prague. Used only for
# missing_furniture_cost, which is shown next to upfront and is never added into it.
FURNITURE_CZK: Final[dict[Furniture, int]] = {
    "bed": 8000,  # ASSUMPTION: bed frame and mattress
    "wardrobe": 6000,  # ASSUMPTION: freestanding
    "fridge": 8000,  # ASSUMPTION: full-size
    "washing machine": 8000,  # ASSUMPTION: front-loading
    "stove": 9000,  # ASSUMPTION: cooker with oven
    "sofa": 12000,  # ASSUMPTION: three-seat
    "dining table": 5000,  # ASSUMPTION: table for four with chairs
    "desk": 3000,  # ASSUMPTION: basic
}

# Czech standard VAT rate, 21%. A fact, not an assumption. It applies to a commission only when the
# listing says VAT is charged on top of it.
VAT_MULTIPLIER: Final[Decimal] = Decimal("1.21")


def energy_czk_per_m2(area_m2: float) -> Decimal:
    """Rate of the first band the area fits in. The last band has no upper limit."""
    return next(
        rate
        for max_area, rate in ENERGY_CZK_PER_M2_BANDS
        if max_area is None or area_m2 <= max_area
    )
