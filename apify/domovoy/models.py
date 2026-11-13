"""Pydantic contracts for the DOMOVOY Actor.

Frozen after WP0; change them only through the integrator (docs/prd/actor-implementation.md, section 3).

Rules:
- money is an integer CZK: Czk rejects floats and bools and is never negative;
- None means unknown, never 0; the one exception is a stated "none" commission, which is 0;
- times are timezone-aware and converted to Europe/Prague;
- output models keep every key: nullable keys are required, so the JSON shape never varies.
"""

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    Strict,
    StringConstraints,
)

PRAGUE = ZoneInfo("Europe/Prague")
T = TypeVar("T")


def _in_prague(value: datetime) -> datetime:
    return value.astimezone(PRAGUE)


def _unique(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("values must be unique")
    return values


PragueTime = Annotated[AwareDatetime, AfterValidator(_in_prague)]
Czk = Annotated[int, Strict(), Field(ge=0)]
Disposition = Annotated[str, StringConstraints(pattern=r"^[1-9]\+(kk|1)$")]
ProfileId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]

Portal = Literal["sreality", "bezrealitky", "idnes"]
Change = Literal["new", "changed", "unchanged"]
Match = Literal["strong", "needs_info", "rejected"]
VerdictValue = Literal["pass", "fail", "unknown"]
Furnished = Literal["full", "partial", "none"]
LeaseType = Literal["najem", "podnajem"]
UnitType = Literal["flat", "studio", "non-residential"]
Precision = Literal["exact", "street", "district"]
Provider = Literal["featherless", "openai", "cache"]
ExtractionStatus = Literal["ok", "partial", "failed"]
Furniture = Literal[
    "bed", "wardrobe", "fridge", "washing machine", "stove", "sofa", "dining table", "desk"
]
# "portal:source_id" -> property_id. How it is filled belongs to WP6.
PropertyIdMap = dict[str, str]


# Search profile (validated by profile.schema.json)


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1)
    citypart: str | None = None


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_type: Literal["rent"]
    property_type: Literal["flat"]
    locations: list[Location] = Field(min_length=1)
    dispositions: list[Disposition] = Field(min_length=1)
    max_rent: Czk | None = None
    min_area_m2: int | None = Field(default=None, ge=0)
    sources: Annotated[list[Portal], Field(min_length=1), AfterValidator(_unique)]
    max_listings: int = Field(default=150, ge=1)


class Household(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occupants: int = Field(default=1, ge=1)


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_monthly: Czk  # required: it is call_context.budget_cap
    max_upfront: Czk | None = None
    elevator: Literal["required"] | None = None
    lease_types: Annotated[list[LeaseType], AfterValidator(_unique)] = Field(default_factory=list)
    move_in_by: date | None = None
    pets_allowed: bool | None = None


class SearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ProfileId
    version: int = Field(ge=1)
    filters: Filters
    household: Household = Field(default_factory=Household)
    requirements: Requirements


# Source output


class GeoPoint(BaseModel):
    lat: float
    lon: float


class AddressDetail(BaseModel):
    street: str | None
    house_number: str | None
    citypart: str | None
    district: str | None
    gps: GeoPoint | None
    precision: Precision | None


class Contact(BaseModel):
    name: str | None
    agency: str | None
    ico: str | None
    email: str | None
    phone: str | None
    form_url: str | None


class Poi(BaseModel):
    metro_m: int | None
    tram_m: int | None
    shop_m: int | None


class Listing(BaseModel):
    """One normalized portal listing."""

    portal: Portal
    source_id: str
    url: str
    collected_at: PragueTime
    title: str
    address: str | None
    address_detail: AddressDetail
    disposition: str | None
    area_m2: float | None
    floor: int | None
    elevator: bool | None
    furnished: Furnished | None
    rent: Czk | None
    price_note: str | None
    description: str | None
    ready_date: str | None
    ownership: str | None
    is_owner_listing: bool | None
    contact: Contact | None
    photos: list[str]
    poi: Poi | None
    raw_ref: str | None


# LLM output


class Charge(BaseModel):
    """One money statement from a listing. None = not stated; czk 0 = stated as none."""

    czk: Czk | None = None
    rent_multiple: int | None = None  # N x rent, e.g. a deposit of one month's rent
    per_person: bool | None = None
    included: bool | None = None  # energy: included in the rent
    vat_extra: bool | None = None  # commission: VAT added on top


class OneTimeFee(BaseModel):
    label: str
    czk: Czk | None = None


class Evidence(BaseModel, Generic[T]):
    value: T | None = None
    quote: str | None = None
    confidence: float = Field(ge=0, le=1)
    verified: bool = False


class Extraction(BaseModel):
    """One Evidence per extracted field in actor.md, plus the provider metadata."""

    rent: Evidence[Czk]
    services: Evidence[Charge]
    energy: Evidence[Charge]
    kauce: Evidence[Charge]
    commission: Evidence[Charge]
    one_time_fees: Evidence[list[OneTimeFee]]
    move_in_date: Evidence[date | Literal["immediately", "by agreement"]]
    lease_type: Evidence[LeaseType]
    lease_length_months: Evidence[int]
    furnished: Evidence[Furnished]
    missing_furniture: Evidence[list[Furniture]]
    pets_allowed: Evidence[bool]
    permanent_residence: Evidence[bool]
    unit_type_hint: Evidence[UnitType]
    provider: Provider | None
    model: str | None
    prompt_version: str
    status: ExtractionStatus


# Python output


class Costs(BaseModel):
    rent: Czk | None
    services: Czk | None
    energy: Czk | None
    total_monthly: Czk | None
    kauce: Czk | None
    commission: Czk | None
    one_time_fees: Czk | None
    first_payment: Czk | None
    upfront: Czk | None
    missing_furniture: list[str]
    missing_furniture_cost: Czk | None
    hidden_monthly: Czk | None
    estimated: list[str]


class Verdict(BaseModel):
    name: str
    verdict: VerdictValue
    estimated: bool
    reason: str


class Evaluation(BaseModel):
    match: Match
    requirements: list[Verdict]
    unknowns: list[str]
    match_reasons: list[str]
    risk_flags: list[str]


class CrossSource(BaseModel):
    cheapest_portal: Portal | None
    commission_savings: Czk | None
    price_spread: Czk | None


class Flat(BaseModel):
    """One deduplicated flat across portals."""

    property_id: str
    sources: Annotated[list[Listing], Field(min_length=1)]
    primary: Listing
    cross_source: CrossSource


# Dataset item = Notion input


class SourceRef(BaseModel):
    portal: Portal
    source_id: str
    url: str
    rent: Czk | None
    commission: Czk | None
    is_owner_listing: bool | None
    collected_at: PragueTime
    contact: Contact | None


class FieldEvidence(BaseModel):
    field: str
    quote: str | None
    confidence: float = Field(ge=0, le=1)


class ExtractionMeta(BaseModel):
    provider: Provider | None
    model: str | None
    status: ExtractionStatus


class FlatItem(BaseModel):
    """Dataset item and Notion input: the 46 fields of the actor.md output table, same names."""

    property_id: str
    profile_id: str
    run_id: str
    change: Change
    match: Match
    url: str
    collected_at: PragueTime
    title: str
    address: str  # required: call_context.address is a string, and call.py rejects null
    address_detail: AddressDetail
    disposition: str | None
    area_m2: float | None
    floor: int | None
    elevator: bool | None
    furnished: Furnished | None
    rent: Czk | None
    services: Czk | None
    energy: Czk | None
    total_monthly: Czk | None
    estimated: list[str]
    kauce: Czk | None
    commission: Czk | None
    one_time_fees: Czk | None
    first_payment: Czk | None
    upfront: Czk | None
    missing_furniture: list[str]
    missing_furniture_cost: Czk | None
    move_in_date: date | None
    lease_type: LeaseType | None
    lease_length_months: int | None
    pets_allowed: bool | None
    permanent_residence: bool | None
    unit_type_hint: UnitType | None
    evidence: list[FieldEvidence]
    unknowns: list[str]
    match_reasons: list[str]
    requirements: list[Verdict]
    risk_flags: list[str]
    sources: list[SourceRef]
    cross_source: CrossSource
    image_url: str | None
    photos: list[str]
    poi: Poi | None
    extraction: ExtractionMeta | None
    first_seen: PragueTime
    last_seen: PragueTime


# Extra contract types


class LlmConfig(BaseModel):
    """Extraction settings. The model has no default until WP4 picks one (open item 7)."""

    model: str
    concurrency: int = Field(default=2, ge=1)
    timeout_sec: int = Field(default=60, ge=1)
    fallback_model: str | None = None
    featherless_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None


class FlatState(BaseModel):
    content_hash: str
    first_seen: PragueTime
    last_seen: PragueTime


class ProfileState(BaseModel):
    """Per-profile state (key-value store domovoy-profile-state). flats is keyed by property_id."""

    profile_id: str
    profile_hash: str | None
    flats: dict[str, FlatState] = Field(default_factory=dict)


class UpsertResult(BaseModel):
    page_id: str
    action: Literal["created", "updated", "unchanged"]


class SourceStatus(BaseModel):
    portal: Portal
    status: Literal["ok", "degraded", "failed"]
    found: int = 0
    fetched: int = 0
    failed: int = 0
    error: str | None = None


class NotionCounts(BaseModel):
    created: int = 0
    updated: int = 0
    errors: int = 0


class RunSummary(BaseModel):
    """Written to the default key-value store under the key OUTPUT."""

    run_id: str
    profile_id: str
    started_at: PragueTime
    finished_at: PragueTime | None
    sources: list[SourceStatus]
    change: dict[Change, int] = Field(
        default_factory=lambda: {"new": 0, "changed": 0, "unchanged": 0}
    )
    match: dict[Match, int] = Field(
        default_factory=lambda: {"strong": 0, "needs_info": 0, "rejected": 0}
    )
    rejected_by_requirement: dict[str, int] = Field(default_factory=dict)
    notion: NotionCounts = Field(default_factory=NotionCounts)
    extraction_providers: dict[Provider, int] = Field(
        default_factory=lambda: {"featherless": 0, "openai": 0, "cache": 0}
    )
