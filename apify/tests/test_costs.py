"""WP5 costs tests: pure functions, offline, table-driven. One table per bullet of the WP5 brief.

Expected numbers are the spec. When the team retunes a table in domovoy/costs/tables.py, update the
matching expectations here in the same change.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any, get_args

import pytest

from domovoy.costs import compute_costs, evaluate
from domovoy.costs.tables import ENERGY_CZK_PER_M2_BANDS, FURNITURE_CZK
from domovoy.models import (
    Charge,
    Costs,
    Evaluation,
    Evidence,
    Extraction,
    Furniture,
    Listing,
    OneTimeFee,
    SearchProfile,
    Verdict,
)
from domovoy.profile import load_profile

FIXTURES = Path(__file__).parent / "fixtures"
EVIDENCE_FIELDS = (
    "rent",
    "services",
    "energy",
    "kauce",
    "commission",
    "one_time_fees",
    "move_in_date",
    "lease_type",
    "lease_length_months",
    "furnished",
    "missing_furniture",
    "pets_allowed",
    "permanent_residence",
    "unit_type_hint",
)
# Every requirement off except the budget cap, so each test switches on only what it checks.
NO_REQUIREMENTS: dict[str, Any] = {
    "max_upfront": None,
    "elevator": None,
    "lease_types": [],
    "move_in_by": None,
    "pets_allowed": None,
}


def _listing(**changes: Any) -> Listing:
    data = json.loads((FIXTURES / "listing_example.json").read_text(encoding="utf-8"))
    return Listing.model_validate({**data, **changes})


def _profile(occupants: int = 1, **requirements: Any) -> SearchProfile:
    data = json.loads((FIXTURES / "profile_vinohrady.json").read_text(encoding="utf-8"))
    data["household"] = {"occupants": occupants}
    data["requirements"] = {**data["requirements"], **NO_REQUIREMENTS, **requirements}
    return load_profile(data)


def _ev(value: Any = None, verified: bool = True) -> Evidence:
    """One extracted field. A None value is unknown; `verified` only matters for a value."""
    if value is None:
        return Evidence(value=None, quote=None, confidence=0.0, verified=False)
    return Evidence(value=value, quote="quoted text", confidence=0.9, verified=verified)


def _extraction(**fields: Any) -> Extraction:
    """Every field unknown unless given. A keyword holds a raw value, or an Evidence for full control."""
    evidence: dict[str, Evidence] = {name: _ev() for name in EVIDENCE_FIELDS}
    for name, value in fields.items():
        evidence[name] = value if isinstance(value, Evidence) else _ev(value)
    return Extraction(
        provider="featherless",
        model="test-model",
        prompt_version="test",
        status="ok",
        **evidence,
    )


def _compute(
    *,
    rent: int | None = 23000,
    area: float | None = 49.0,
    occupants: int = 1,
    **fields: Any,
) -> Costs:
    listing = _listing(rent=rent, area_m2=area)
    return compute_costs(listing, _extraction(**fields), _profile(occupants=occupants))


def _assess(
    *,
    rent: int | None = 23000,
    area: float | None = 49.0,
    lift: bool | None = True,
    occupants: int = 1,
    requirements: dict[str, Any] | None = None,
    **fields: Any,
) -> Evaluation:
    listing = _listing(rent=rent, area_m2=area, elevator=lift)
    ex = _extraction(**fields)
    profile = _profile(occupants=occupants, **(requirements or {}))
    return evaluate(listing, ex, compute_costs(listing, ex, profile), profile)


def _verdict(result: Evaluation, name: str) -> Verdict | None:
    return next(
        (verdict for verdict in result.requirements if verdict.name == name), None
    )


# Costs: kauce as N x rent


@pytest.mark.parametrize(
    ("rent", "kauce", "expected"),
    [
        pytest.param(
            23000, Charge(czk=24000), 24000, id="stated amount wins over a multiple"
        ),
        pytest.param(23000, Charge(rent_multiple=1), 23000, id="one month's rent"),
        pytest.param(28000, Charge(rent_multiple=3), 84000, id="three months' rent"),
        pytest.param(23000, Charge(czk=0), 0, id="stated none"),
        pytest.param(
            None, Charge(rent_multiple=2), None, id="rent unknown, so N x rent unknown"
        ),
        pytest.param(23000, Charge(), None, id="charge with no amount"),
        pytest.param(23000, None, None, id="not stated"),
    ],
)
def test_kauce_is_stated_amount_or_n_times_rent(
    rent: int | None, kauce: Charge | None, expected: int | None
) -> None:
    assert _compute(rent=rent, kauce=kauce).kauce == expected


# Costs: commission with VAT


@pytest.mark.parametrize(
    ("rent", "commission", "expected"),
    [
        pytest.param(
            23000,
            Charge(rent_multiple=1, vat_extra=False),
            23000,
            id="one month, VAT-free",
        ),
        pytest.param(
            23000,
            Charge(rent_multiple=1, vat_extra=True),
            27830,
            id="one month plus VAT",
        ),
        pytest.param(
            23000,
            Charge(rent_multiple=1, vat_extra=None),
            23000,
            id="VAT not stated: no uplift",
        ),
        pytest.param(
            23000, Charge(czk=1000, vat_extra=True), 1210, id="stated amount plus VAT"
        ),
        pytest.param(
            23000, Charge(czk=50, vat_extra=True), 61, id="60.5 rounds half up to 61"
        ),
        pytest.param(
            23000, Charge(czk=0, vat_extra=True), 0, id="stated none stays 0 with VAT"
        ),
        pytest.param(
            None, Charge(rent_multiple=1, vat_extra=True), None, id="rent unknown"
        ),
        pytest.param(23000, None, None, id="not stated"),
    ],
)
def test_commission_with_vat_and_rounding(
    rent: int | None, commission: Charge | None, expected: int | None
) -> None:
    assert _compute(rent=rent, commission=commission).commission == expected


# Costs: energy included, stated, or estimated from the per-m2 table; per person x occupants


@pytest.mark.parametrize(
    ("energy", "area", "occupants", "expected", "estimated"),
    [
        pytest.param(
            Charge(included=True), 49.0, 1, 0, False, id="included in the rent"
        ),
        pytest.param(
            Charge(included=True), None, 1, 0, False, id="included, so no area needed"
        ),
        pytest.param(
            Charge(czk=2000, per_person=True),
            42.0,
            1,
            2000,
            False,
            id="per person, one occupant",
        ),
        pytest.param(
            Charge(czk=2000, per_person=True),
            42.0,
            2,
            4000,
            False,
            id="per person, two occupants",
        ),
        pytest.param(
            Charge(czk=1500, per_person=False),
            42.0,
            2,
            1500,
            False,
            id="per flat is not multiplied",
        ),
        pytest.param(Charge(czk=0), 42.0, 1, 0, False, id="stated none"),
        pytest.param(
            Charge(included=False),
            49.0,
            1,
            1960,
            True,
            id="not included, no amount: table",
        ),
        pytest.param(None, 49.0, 1, 1960, True, id="missing: table, 49 m2 x 40"),
        pytest.param(
            Charge(included=None), 75.0, 1, 2625, True, id="75 m2 in the 61-90 band"
        ),
        pytest.param(None, None, 1, None, False, id="no area, so no estimate"),
        pytest.param(
            None, 40.0, 1, 2000, True, id="band edge: 40 m2 is in the first band"
        ),
        pytest.param(
            None, 40.5, 1, 1620, True, id="just over 40 m2 uses the second band"
        ),
        pytest.param(
            None, 60.0, 1, 2400, True, id="band edge: 60 m2 is in the second band"
        ),
        pytest.param(
            None, 61.0, 1, 2135, True, id="just over 60 m2 uses the third band"
        ),
        pytest.param(
            None, 90.0, 1, 3150, True, id="band edge: 90 m2 is in the third band"
        ),
        pytest.param(None, 91.0, 1, 2912, True, id="above 90 m2 uses the last band"),
    ],
)
def test_energy_included_stated_or_estimated(
    energy: Charge | None,
    area: float | None,
    occupants: int,
    expected: int | None,
    estimated: bool,
) -> None:
    costs = _compute(area=area, occupants=occupants, energy=energy)
    assert costs.energy == expected
    assert ("energy" in costs.estimated) is estimated


@pytest.mark.parametrize(
    ("services", "occupants", "expected"),
    [
        pytest.param(
            Charge(czk=1900, per_person=True), 1, 1900, id="per person, one occupant"
        ),
        pytest.param(
            Charge(czk=1900, per_person=True), 2, 3800, id="per person, two occupants"
        ),
        pytest.param(Charge(czk=1500, per_person=False), 2, 1500, id="per flat"),
        pytest.param(
            Charge(czk=1900, per_person=None),
            2,
            1900,
            id="basis not stated: counted per flat",
        ),
        pytest.param(Charge(czk=0), 2, 0, id="stated none"),
        pytest.param(Charge(), 2, None, id="fees with no amount"),
        pytest.param(None, 2, None, id="not stated"),
    ],
)
def test_services_per_person_times_occupants(
    services: Charge | None, occupants: int, expected: int | None
) -> None:
    assert _compute(occupants=occupants, services=services).services == expected


def test_energy_table_bands_end_with_an_open_band() -> None:
    assert ENERGY_CZK_PER_M2_BANDS[-1][0] is None  # the last band has no upper limit
    assert all(rate > 0 for _, rate in ENERGY_CZK_PER_M2_BANDS)


# Costs: furniture table, separate from upfront


def test_furniture_table_covers_the_fixed_list() -> None:
    assert set(FURNITURE_CZK) == set(get_args(Furniture))
    assert all(isinstance(price, int) and price > 0 for price in FURNITURE_CZK.values())


@pytest.mark.parametrize("item", list(get_args(Furniture)))
def test_each_missing_item_is_priced_from_the_table(item: Furniture) -> None:
    assert (
        _compute(missing_furniture=[item]).missing_furniture_cost == FURNITURE_CZK[item]
    )


@pytest.mark.parametrize(
    ("missing", "expected_items", "expected_cost"),
    [
        pytest.param(None, [], None, id="listing does not say"),
        pytest.param([], [], 0, id="stated none missing"),
        pytest.param(
            ["bed", "desk"],
            ["bed", "desk"],
            FURNITURE_CZK["bed"] + FURNITURE_CZK["desk"],
            id="two items summed",
        ),
        pytest.param(
            ["bed", "bed"], ["bed"], FURNITURE_CZK["bed"], id="duplicate counted once"
        ),
    ],
)
def test_missing_furniture_cost(
    missing: list[Furniture] | None,
    expected_items: list[str],
    expected_cost: int | None,
) -> None:
    costs = _compute(missing_furniture=missing)
    assert costs.missing_furniture == expected_items
    assert costs.missing_furniture_cost == expected_cost


# Costs: totals, upfront and estimated flags. Unknown inputs stay None.

CASE_STATED: dict[str, Any] = {
    "rent": 23000,
    "services": Charge(czk=3400),
    "energy": Charge(included=True),
    "kauce": Charge(rent_multiple=1),
    "commission": Charge(rent_multiple=1, vat_extra=False),
    "one_time_fees": [OneTimeFee(label="key fee", czk=500)],
    "missing_furniture": [],
}


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        pytest.param(
            {**CASE_STATED},
            {
                "total_monthly": 26400,
                "hidden_monthly": 3400,
                "upfront": 72900,
                "missing_furniture_cost": 0,
                "estimated": [],
            },
            id="all stated, energy included",
        ),
        pytest.param(
            {**CASE_STATED, "missing_furniture": ["wardrobe"]},
            {
                "upfront": 72900,
                "missing_furniture_cost": 6000,
                "estimated": ["missing_furniture_cost"],
            },
            id="furniture is separate: upfront does not include it",
        ),
        pytest.param(
            {**CASE_STATED, "one_time_fees": []},
            {"one_time_fees": 0, "upfront": 72400},
            id="stated no one-time fees counts as 0",
        ),
        pytest.param(
            {**CASE_STATED, "one_time_fees": [OneTimeFee(label="key fee", czk=None)]},
            {"one_time_fees": None, "upfront": None},
            id="one-time fee without an amount: upfront unknown",
        ),
        pytest.param(
            {**CASE_STATED, "one_time_fees": None},
            {"one_time_fees": None, "upfront": None, "total_monthly": 26400},
            id="one-time fees not stated: upfront unknown, total still known",
        ),
        pytest.param(
            {**CASE_STATED, "commission": None},
            {"commission": None, "upfront": None, "total_monthly": 26400},
            id="commission not stated: upfront unknown",
        ),
        pytest.param(
            {**CASE_STATED, "services": None},
            {
                "total_monthly": None,
                "hidden_monthly": None,
                "first_payment": None,
                "upfront": None,
                "energy": 0,
            },
            id="services not stated: total and upfront unknown",
        ),
        pytest.param(
            {**CASE_STATED, "rent": None, "kauce": Charge(czk=23000)},
            {
                "total_monthly": None,
                "hidden_monthly": None,
                "first_payment": None,
                "upfront": None,
                "kauce": 23000,
            },
            id="rent unknown: total unknown, a stated deposit is still known",
        ),
        pytest.param(
            {**CASE_STATED, "energy": None, "area": 49.0},
            {
                "energy": 1960,
                "total_monthly": 28360,
                "hidden_monthly": 5360,
                "first_payment": 28360,
                "upfront": 74860,
                "estimated": [
                    "energy",
                    "total_monthly",
                    "hidden_monthly",
                    "first_payment",
                    "upfront",
                ],
            },
            id="estimated energy flows into total, first payment and upfront",
        ),
        pytest.param(
            {
                "rent": 23000,
                "services": Charge(czk=3400),
                "energy": Charge(czk=2000, per_person=True),
                "kauce": Charge(rent_multiple=1),
                "commission": Charge(rent_multiple=1, vat_extra=False),
            },
            {
                "total_monthly": 28400,
                "hidden_monthly": 5400,
                "kauce": 23000,
                "commission": 23000,
                "one_time_fees": None,
                "upfront": None,
                "estimated": [],
            },
            id="real listing 1015095372: fees and energy stated, one-time fees not stated",
        ),
        pytest.param(
            {
                "rent": 28000,
                "services": Charge(czk=1500),
                "energy": None,
                "area": 55.0,
                "kauce": Charge(rent_multiple=3),
                "commission": Charge(rent_multiple=1),
            },
            {
                "energy": 2200,
                "total_monthly": 31700,
                "kauce": 84000,
                "commission": 28000,
                "upfront": None,
                "estimated": [
                    "energy",
                    "total_monthly",
                    "hidden_monthly",
                    "first_payment",
                ],
            },
            id="real listing 688549964: energy estimated, VAT not stated on commission",
        ),
        pytest.param(
            {
                "rent": 27500,
                "services": Charge(czk=1900, per_person=True),
                "energy": None,
                "area": 49.0,
                "kauce": Charge(rent_multiple=2),
                "commission": Charge(rent_multiple=1, vat_extra=False),
            },
            {
                "energy": 1960,
                "total_monthly": 31360,
                "kauce": 55000,
                "commission": 27500,
                "upfront": None,
            },
            id="real listing 2073653324: per-person fee, energy transferred",
        ),
    ],
)
def test_costs_scenarios(case: dict[str, Any], expected: dict[str, Any]) -> None:
    costs = _compute(**{"area": 49.0, **case})
    for field, value in expected.items():
        assert getattr(costs, field) == value, field


# Evaluate: requirement verdicts (pass, fail, unknown), estimated flags


BASE: dict[str, Any] = {
    "services": Charge(czk=0),
    "energy": Charge(included=True),
}  # total 23000, under the cap


@pytest.mark.parametrize(
    ("kwargs", "requirements", "name", "verdict", "estimated"),
    [
        pytest.param(
            {**BASE}, {}, "max_total_monthly", "pass", False, id="total under the cap"
        ),
        pytest.param(
            {**BASE, "rent": 30000},
            {},
            "max_total_monthly",
            "pass",
            False,
            id="total exactly at the cap",
        ),
        pytest.param(
            {**BASE, "rent": 31000},
            {},
            "max_total_monthly",
            "fail",
            False,
            id="total above the cap",
        ),
        pytest.param(
            {"services": None, "energy": Charge(included=True)},
            {},
            "max_total_monthly",
            "unknown",
            False,
            id="services unknown: total unknown",
        ),
        pytest.param(
            {**BASE, "rent": None},
            {},
            "max_total_monthly",
            "unknown",
            False,
            id="rent unknown: total unknown",
        ),
        pytest.param(
            {"services": Charge(czk=1000), "energy": None},
            {},
            "max_total_monthly",
            "pass",
            True,
            id="pass depends on the estimated energy",
        ),
        pytest.param(
            {"rent": 28000, "services": Charge(czk=1500), "energy": None, "area": 55.0},
            {},
            "max_total_monthly",
            "unknown",
            True,
            id="over budget only with estimated energy (31,700 CZK): unknown, not a fail",
        ),
        pytest.param(
            {"rent": 31000, "services": Charge(czk=0), "energy": None, "area": 49.0},
            {},
            "max_total_monthly",
            "fail",
            True,
            id="over budget even without the estimate (31,000 CZK stated): fail",
        ),
        pytest.param(
            {**BASE},
            {"max_upfront": 50000},
            "max_upfront",
            "unknown",
            False,
            id="upfront unknown: deposit and commission not stated",
        ),
        pytest.param(
            {
                "services": Charge(czk=3400),
                "energy": Charge(included=True),
                "kauce": Charge(rent_multiple=1),
                "commission": Charge(rent_multiple=1),
                "one_time_fees": [OneTimeFee(label="key", czk=500)],
            },
            {"max_upfront": 50000},
            "max_upfront",
            "fail",
            False,
            id="upfront 72,900 above the cap",
        ),
        pytest.param(
            {
                "services": Charge(czk=3400),
                "energy": Charge(included=True),
                "kauce": Charge(rent_multiple=1),
                "commission": Charge(rent_multiple=1),
                "one_time_fees": [OneTimeFee(label="key", czk=500)],
            },
            {"max_upfront": 80000},
            "max_upfront",
            "pass",
            False,
            id="upfront 72,900 under the cap",
        ),
        pytest.param(
            {
                "services": Charge(czk=3400),
                "energy": None,
                "area": 49.0,
                "kauce": Charge(rent_multiple=1),
                "commission": Charge(rent_multiple=1, vat_extra=False),
                "one_time_fees": [OneTimeFee(label="key", czk=500)],
            },
            {"max_upfront": 73000},
            "max_upfront",
            "unknown",
            True,
            id="upfront 74,860 over only with estimated energy (72,900 stated): unknown",
        ),
        pytest.param(
            {
                "services": Charge(czk=3400),
                "energy": None,
                "area": 49.0,
                "kauce": Charge(rent_multiple=1),
                "commission": Charge(rent_multiple=1, vat_extra=False),
                "one_time_fees": [OneTimeFee(label="key", czk=500)],
            },
            {"max_upfront": 50000},
            "max_upfront",
            "fail",
            True,
            id="upfront fails even without the estimate (72,900 stated): fail",
        ),
        pytest.param(
            {**BASE},
            {"elevator": "required"},
            "elevator",
            "pass",
            False,
            id="elevator listed",
        ),
        pytest.param(
            {**BASE, "lift": False},
            {"elevator": "required"},
            "elevator",
            "fail",
            False,
            id="no elevator",
        ),
        pytest.param(
            {**BASE, "lift": None},
            {"elevator": "required"},
            "elevator",
            "unknown",
            False,
            id="elevator not stated",
        ),
        pytest.param(
            {**BASE, "lease_type": "najem"},
            {"lease_types": ["najem"]},
            "lease_types",
            "pass",
            False,
            id="regular lease wanted",
        ),
        pytest.param(
            {**BASE, "lease_type": "podnajem"},
            {"lease_types": ["najem"]},
            "lease_types",
            "fail",
            False,
            id="sublet, regular lease wanted",
        ),
        pytest.param(
            {**BASE},
            {"lease_types": ["najem"]},
            "lease_types",
            "unknown",
            False,
            id="lease type not stated",
        ),
        pytest.param(
            {**BASE, "move_in_date": date(2027, 1, 1)},
            {"move_in_by": "2027-01-31"},
            "move_in_by",
            "pass",
            False,
            id="move-in before the deadline",
        ),
        pytest.param(
            {**BASE, "move_in_date": date(2027, 2, 1)},
            {"move_in_by": "2027-01-31"},
            "move_in_by",
            "fail",
            False,
            id="move-in after the deadline",
        ),
        pytest.param(
            {**BASE, "move_in_date": "immediately"},
            {"move_in_by": "2027-01-31"},
            "move_in_by",
            "pass",
            False,
            id="available immediately",
        ),
        pytest.param(
            {**BASE, "move_in_date": "by agreement"},
            {"move_in_by": "2027-01-31"},
            "move_in_by",
            "unknown",
            False,
            id="move-in by agreement is not fixed",
        ),
        pytest.param(
            {**BASE},
            {"move_in_by": "2027-01-31"},
            "move_in_by",
            "unknown",
            False,
            id="move-in date not stated",
        ),
        pytest.param(
            {**BASE, "pets_allowed": True},
            {"pets_allowed": True},
            "pets_allowed",
            "pass",
            False,
            id="pets wanted and allowed",
        ),
        pytest.param(
            {**BASE, "pets_allowed": False},
            {"pets_allowed": True},
            "pets_allowed",
            "fail",
            False,
            id="pets wanted, not allowed",
        ),
        pytest.param(
            {**BASE},
            {"pets_allowed": True},
            "pets_allowed",
            "unknown",
            False,
            id="pet policy not stated",
        ),
    ],
)
def test_requirement_verdicts(
    kwargs: dict[str, Any],
    requirements: dict[str, Any],
    name: str,
    verdict: str,
    estimated: bool,
) -> None:
    result = _assess(requirements=requirements, **kwargs)
    found = _verdict(result, name)
    assert found is not None
    assert (found.verdict, found.estimated) == (verdict, estimated)
    assert found.reason


def test_only_the_budget_cap_is_checked_when_nothing_else_is_set() -> None:
    result = _assess(**BASE)
    assert [verdict.name for verdict in result.requirements] == ["max_total_monthly"]


# Unknown totals: a known stated lower bound over the cap is still a fail (review fix round 1).


@pytest.mark.parametrize(
    ("kwargs", "requirements", "name", "verdict", "match"),
    [
        pytest.param(
            {"rent": 31000, "services": None, "energy": Charge(included=True)},
            {},
            "max_total_monthly",
            "fail",
            "rejected",
            id="rent 31,000 alone is over the 30,000 cap, services unknown: fail",
        ),
        pytest.param(
            {
                "services": Charge(czk=0),
                "energy": Charge(included=True),
                "kauce": Charge(czk=100000),
                "commission": None,
                "one_time_fees": None,
            },
            {"max_upfront": 80000},
            "max_upfront",
            "fail",
            "rejected",
            id="known upfront 123,000 over the 80,000 cap, commission and fees unknown: fail",
        ),
        pytest.param(
            {"rent": 23000, "services": None, "energy": Charge(included=True)},
            {},
            "max_total_monthly",
            "unknown",
            "needs_info",
            id="known 23,000 under the cap, services unknown: still unknown",
        ),
        pytest.param(
            {
                "services": Charge(czk=0),
                "energy": Charge(included=True),
                "kauce": Charge(czk=23000),
                "one_time_fees": [OneTimeFee(label="key", czk=None)],
            },
            {"max_upfront": 80000},
            "max_upfront",
            "unknown",
            "needs_info",
            id="known upfront 46,000 under the cap: still unknown",
        ),
        pytest.param(
            {"rent": 29000, "services": None, "energy": None, "area": 49.0},
            {},
            "max_total_monthly",
            "unknown",
            "needs_info",
            id="estimated energy is left out of the lower bound: still unknown",
        ),
    ],
)
def test_unknown_total_with_known_lower_bound(
    kwargs: dict[str, Any],
    requirements: dict[str, Any],
    name: str,
    verdict: str,
    match: str,
) -> None:
    result = _assess(requirements=requirements, **kwargs)
    found = _verdict(result, name)
    assert found is not None
    assert (found.verdict, found.estimated, result.match) == (verdict, False, match)


def test_flat_over_budget_only_by_estimated_energy_is_needs_info() -> None:
    # Sreality 688549964: rent 28,000 + fees 1,500 + estimated energy 2,200 (55 m² x 40) = 31,700 CZK.
    flat: dict[str, Any] = {
        "rent": 28000,
        "area": 55.0,
        "services": Charge(czk=1500),
        "energy": None,
        "kauce": Charge(rent_multiple=3),
        "commission": Charge(rent_multiple=1, vat_extra=False),
    }
    result = _assess(**flat)
    total = _verdict(result, "max_total_monthly")
    assert total is not None
    assert (total.verdict, total.estimated) == ("unknown", True)
    assert "only with estimated energy" in total.reason
    assert result.match == "needs_info"
    assert "over budget (est.)" in result.risk_flags
    assert (
        "Are energy costs included in the rent? If not, what is the monthly energy advance?"
        in (result.unknowns)
    )
    # The same flat with a hard fail elsewhere is rejected.
    rejected = _assess(**flat, lift=False, requirements={"elevator": "required"})
    assert rejected.match == "rejected"


# Evaluate: match


@pytest.mark.parametrize(
    ("kwargs", "requirements", "expected"),
    [
        pytest.param(
            {**BASE, "lease_type": "najem"},
            {"elevator": "required", "lease_types": ["najem"]},
            "strong",
            id="every requirement passes: strong",
        ),
        pytest.param(
            {**BASE, "lease_type": "podnajem"},
            {"lease_types": ["najem"], "pets_allowed": True},
            "rejected",
            id="one fail with an unknown still: rejected",
        ),
        pytest.param(
            {**BASE},
            {"lease_types": ["najem"]},
            "needs_info",
            id="unknown and no fail: needs info",
        ),
    ],
)
def test_match_is_rejected_on_any_fail_strong_on_all_pass(
    kwargs: dict[str, Any], requirements: dict[str, Any], expected: str
) -> None:
    result = _assess(requirements=requirements, **kwargs)
    assert result.match == expected
    assert result.match_reasons == [
        v.reason for v in result.requirements if v.verdict == "pass"
    ]


# Evaluate: unknowns, one plain-English line per unknown topic

FULLY_KNOWN: dict[str, Any] = {
    "services": Charge(czk=3400),
    "energy": Charge(included=True),
    "kauce": Charge(rent_multiple=1),
    "commission": Charge(rent_multiple=1, vat_extra=False),
    "one_time_fees": [OneTimeFee(label="key fee", czk=500)],
    "missing_furniture": [],
    "lease_type": "najem",
    "move_in_date": date(2027, 1, 1),
    "pets_allowed": False,
    "permanent_residence": True,
    "unit_type_hint": "flat",
    "lease_length_months": 12,
    "furnished": "full",
}
FULLY_KNOWN_REQUIREMENTS: dict[str, Any] = {
    "elevator": "required",
    "lease_types": ["najem"],
    "move_in_by": "2027-01-31",
    "pets_allowed": False,
}


def test_fully_known_flat_has_no_unknowns_and_is_strong() -> None:
    result = _assess(requirements=FULLY_KNOWN_REQUIREMENTS, **FULLY_KNOWN)
    assert result.unknowns == []
    assert result.match == "strong"


def test_nothing_known_asks_once_per_topic() -> None:
    result = _assess(
        lift=None,
        requirements={
            "elevator": "required",
            "lease_types": ["najem"],
            "move_in_by": "2027-01-31",
            "pets_allowed": True,
        },
    )
    assert result.unknowns == [
        "What are the monthly service fees, and are they per flat or per person?",
        "Are energy costs included in the rent? If not, what is the monthly energy advance?",
        "How much is the deposit?",
        "What is the agency commission, and is VAT added on top?",
        "Are there one-time fees at move-in, and how much are they?",
        (
            "Which of these are missing from the flat: bed, wardrobe, fridge, washing machine, "
            "stove, sofa, dining table, desk?"
        ),
        "Is the lease a regular lease or a sublet?",
        "What is the earliest move-in date?",
        "Is there a lift (elevator) in the building?",
        "Are pets allowed?",
    ]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param(
            {**BASE, "commission": Charge(czk=23000, vat_extra=None)},
            ["Is VAT added on top of the agency commission?"],
            id="commission known, VAT not stated",
        ),
        pytest.param(
            {**BASE, "commission": Charge(czk=0, vat_extra=None)},
            [],
            id="stated none: no VAT question",
        ),
        pytest.param(
            {**BASE, "commission": Charge(czk=23000, vat_extra=True)},
            [],
            id="VAT stated: no question",
        ),
    ],
)
def test_commission_vat_question(kwargs: dict[str, Any], expected: list[str]) -> None:
    fields: dict[str, Any] = {**FULLY_KNOWN, **kwargs}
    result = _assess(**fields)
    assert result.unknowns == expected


# Evaluate: risk flags, as in actor.md

CLEAN: dict[str, Any] = {
    **FULLY_KNOWN,
    "lease_type": "najem",
    "unit_type_hint": "flat",
    "permanent_residence": True,
}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param({}, [], id="clean flat, no flags"),
        pytest.param({"lease_type": "podnajem"}, ["sublet"], id="sublet"),
        pytest.param(
            {"unit_type_hint": "studio"},
            ["possible studio / no permanent residence"],
            id="studio",
        ),
        pytest.param(
            {"unit_type_hint": "non-residential"},
            ["possible studio / no permanent residence"],
            id="non-residential",
        ),
        pytest.param(
            {"permanent_residence": False},
            ["possible studio / no permanent residence"],
            id="no permanent residence",
        ),
        pytest.param(
            {"commission": Charge(rent_multiple=1, vat_extra=True)},
            ["commission + VAT"],
            id="commission with VAT",
        ),
        pytest.param({"services": None}, ["fees not stated"], id="services not stated"),
        pytest.param(
            {"one_time_fees": None}, ["fees not stated"], id="one-time fees not stated"
        ),
        pytest.param({"lease_length_months": 6}, ["short lease"], id="six-month lease"),
        pytest.param(
            {"lease_length_months": 12}, [], id="twelve-month lease is not short"
        ),
        pytest.param(
            {"kauce": _ev(Charge(rent_multiple=1), verified=False)},
            ["extraction unverified"],
            id="a value with an unverified quote",
        ),
        pytest.param(
            {"pets_allowed": _ev(None, verified=False)},
            [],
            id="unverified but unknown: no flag",
        ),
        pytest.param(
            {"rent": 28000, "services": Charge(czk=1500), "energy": None, "area": 55.0},
            ["over budget (est.)"],
            id="over budget only with estimated energy",
        ),
        pytest.param(
            {"rent": 31000, "services": Charge(czk=0), "energy": Charge(included=True)},
            [],
            id="stated over budget is a fail, not an estimate flag",
        ),
        pytest.param(
            {"one_time_fees": [OneTimeFee(label="key", czk=None)]},
            ["fees not stated"],
            id="a one-time fee without an amount",
        ),
    ],
)
def test_risk_flags(changes: dict[str, Any], expected: list[str]) -> None:
    fields: dict[str, Any] = {**CLEAN, **changes}
    result = _assess(**fields)
    assert result.risk_flags == expected
