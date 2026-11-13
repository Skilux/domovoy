"""WP0 foundation tests. Offline: an autouse fixture refuses every socket connect."""

import json
import re
import socket
from logging import getLogger
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from domovoy import main as actor_main
from domovoy.models import FlatItem, Listing, RunSummary, SearchProfile
from domovoy.profile import load_profile, schema_errors
from domovoy.sources import SOURCES, register
from domovoy.sources.base import SourceError

TESTS = Path(__file__).resolve().parent
APIFY = TESTS.parent
REPO = APIFY.parent
FIXTURES = TESTS / "fixtures"
TEXTS = FIXTURES / "texts"
PACKAGE_SCHEMAS = APIFY / "domovoy" / "schemas"
SKILL_REFERENCE = REPO / "skill" / "domovoy" / "reference"
ACTOR_MD = REPO / "docs" / "prd" / "actor.md"
COPIED_SCHEMAS = ["call_context.schema.json", "submit_call_result.schema.json", "profile.schema.json"]
FLATITEM_FIELD_COUNT = 46
MONEY_FIELDS = ["rent", "total_monthly", "upfront", "missing_furniture_cost"]
TEXT_KEYS = {
    "portal", "source_id", "url", "description", "price_note", "rent",
    "area_m2", "disposition", "note", "synthetic",
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?420[  ]?)?\d{3}[  ]?\d{3}[  ]?\d{3}(?!\d)")
LOG = getLogger("test")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_fixture() -> dict[str, Any]:
    return load_json(FIXTURES / "profile_vinohrady.json")


def listing_fixture() -> Listing:
    return Listing.model_validate(load_json(FIXTURES / "listing_example.json"))


def actor_output_fields() -> list[str]:
    """Field names from the first column of the actor.md dataset-item table."""
    section = ACTOR_MD.read_text(encoding="utf-8").split("### Output: dataset item", 1)[1]
    section = section.split("### Extraction", 1)[0]
    names: list[str] = []
    for line in section.splitlines():
        if line.startswith("| `"):
            names += re.findall(r"`([a-z_0-9]+)`", line.split("|")[1])
    return names


class FakeStore:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def set_value(self, key: str, value: Any) -> None:
        self.values[key] = value


class FakeSource:
    name = "sreality"

    def __init__(self, listing: Listing, error: Exception | None = None) -> None:
        self.listing = listing
        self.error = error

    async def collect(self, profile: SearchProfile, ctx: Any):
        yield self.listing
        yield self.listing
        if self.error is not None:
            raise self.error

    def normalize(self, raw: dict[str, Any], collected_at: Any) -> Listing:
        return self.listing


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("WP0 tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def empty_registry():
    SOURCES.clear()
    yield SOURCES
    SOURCES.clear()


# Profile


def test_profile_fixture_validates_against_schema_and_model():
    data = profile_fixture()
    assert schema_errors(data) == []
    assert load_profile(data).household.occupants == 1


def test_profile_round_trips_exactly():
    data = profile_fixture()
    assert load_profile(data).model_dump(mode="json") == data


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["household"].update(occupants=0),
        lambda d: d["filters"].update(dispositions=["2kk"]),
        lambda d: d["filters"].update(sources=["sreality", "sreality"]),
        lambda d: d["requirements"].pop("max_total_monthly"),
        lambda d: d["requirements"].update(elevator="preferred"),
        lambda d: d.update(extra_key=1),
    ],
)
def test_schema_and_model_reject_the_same_bad_profiles(mutate):
    data = profile_fixture()
    mutate(data)
    assert schema_errors(data), "profile.schema.json should reject this profile"
    with pytest.raises(ValidationError):
        load_profile(data)


@pytest.mark.parametrize("name", COPIED_SCHEMAS)
def test_schema_copies_match_skill_reference(name):
    source = SKILL_REFERENCE / name
    assert source.exists(), f"missing {source}"
    assert (PACKAGE_SCHEMAS / name).read_bytes() == source.read_bytes(), (
        f"{name} drifted from skill/domovoy/reference/; copy it again"
    )


# Models and fixtures


def test_listing_example_round_trips():
    data = load_json(FIXTURES / "listing_example.json")
    assert Listing.model_validate(data).model_dump(mode="json") == data


def test_flatitem_example_round_trips():
    data = load_json(FIXTURES / "flatitem_example.json")
    assert FlatItem.model_validate(data).model_dump(mode="json") == data


def test_flatitem_fields_match_actor_output_table():
    names = actor_output_fields()
    assert len(names) == FLATITEM_FIELD_COUNT, names
    assert set(names) == set(FlatItem.model_fields), set(names) ^ set(FlatItem.model_fields)


@pytest.mark.parametrize("field", MONEY_FIELDS)
@pytest.mark.parametrize("bad", [12000.0, True])
def test_money_fields_reject_floats_and_bools(field, bad):
    data = load_json(FIXTURES / "flatitem_example.json")
    data[field] = bad
    with pytest.raises(ValidationError):
        FlatItem.model_validate(data)


def test_money_none_means_unknown():
    data = load_json(FIXTURES / "flatitem_example.json")
    data["rent"] = None
    assert FlatItem.model_validate(data).rent is None


def test_datetimes_must_be_aware_and_land_in_prague():
    data = load_json(FIXTURES / "listing_example.json")
    data["collected_at"] = "2026-11-13T12:00:00"
    with pytest.raises(ValidationError):
        Listing.model_validate(data)
    data["collected_at"] = "2026-11-13T11:00:00+00:00"
    listing = Listing.model_validate(data)
    assert listing.collected_at.utcoffset().total_seconds() == 3600
    assert listing.collected_at.hour == 12


# Fixtures: texts and privacy


def test_text_fixtures_are_complete():
    files = sorted(TEXTS.glob("*.json"))
    assert len(files) == 5
    for path in files:
        text = load_json(path)
        assert set(text) == TEXT_KEYS, path.name
        assert text["portal"] == "sreality", path.name
        assert isinstance(text["synthetic"], bool), path.name


def test_fixtures_contain_no_emails_or_phone_numbers():
    for path in FIXTURES.rglob("*.json"):
        assert not EMAIL.search(path.read_text(encoding="utf-8")), f"email-like text in {path.name}"
    for path in TEXTS.glob("*.json"):
        text = load_json(path)
        for key in ("description", "price_note", "note"):
            assert not PHONE.search(text[key] or ""), f"phone-like digits in {path.name}:{key}"


# Mode dispatch and sources, no network


async def test_katastr_lookup_is_not_implemented():
    store = FakeStore()
    result = await actor_main.run({"mode": "katastr_lookup"}, store, LOG)
    assert result == {"status": "NOT_IMPLEMENTED"}
    assert store.values == {"OUTPUT": result}


async def test_unknown_mode_fails_clearly():
    with pytest.raises(ValueError, match="unknown mode 'scrape'"):
        await actor_main.run({"mode": "scrape"}, FakeStore(), LOG)


async def test_search_without_registered_sources_reports_zero_listings(empty_registry):
    store = FakeStore()
    actor_input = {"mode": "search", "profile": profile_fixture(), "skipExtraction": True}
    result = await actor_main.run(actor_input, store, LOG)
    summary = RunSummary.model_validate(result)
    assert summary.profile_id == "vinohrady-2kk-30k"
    assert [s.portal for s in summary.sources] == ["sreality", "bezrealitky", "idnes"]
    assert all(
        (s.status, s.found, s.error) == ("failed", 0, "source not registered")
        for s in summary.sources
    )
    assert store.values == {"OUTPUT": result}


async def test_search_runs_a_registered_source(empty_registry):
    register(FakeSource(listing_fixture(), error=SourceError("portal changed")))
    actor_input = {"mode": "search", "profile": profile_fixture(), "skipExtraction": True}
    result = await actor_main.run(actor_input, FakeStore(), LOG)
    first = RunSummary.model_validate(result).sources[0]
    assert (first.portal, first.status, first.found, first.error) == (
        "sreality", "failed", 2, "portal changed",
    )


def test_registry_rejects_duplicate_names(empty_registry):
    register(FakeSource(listing_fixture()))
    with pytest.raises(ValueError, match="already registered"):
        register(FakeSource(listing_fixture()))
