"""Pipeline tests, offline. Sources, stage modules and the Actor platform are fakes with the contract signatures;
the real stages are tested in their own packages. An autouse fixture refuses every socket connect."""

import json
import logging
import socket
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import domovoy.costs as costs_stage
import domovoy.dedup as dedup_stage
import domovoy.notion.sink as notion_stage
import domovoy.pipeline as pipeline_module
from domovoy.assemble import address_for, build_flat_item
from domovoy.models import (
    Costs,
    CrossSource,
    Evaluation,
    Extraction,
    Flat,
    FlatState,
    Listing,
    ProfileState,
    SearchProfile,
    UpsertResult,
    Verdict,
)
from domovoy.pipeline import Modules, empty_extraction, llm_config, open_extractor, resolve_modules, run_search
from domovoy.profile import load_profile
from domovoy.sources.base import SourceError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOG = logging.getLogger("test-pipeline")
PROPERTY_IDS_STORE = "domovoy-property-ids"
PROFILE_STATE_STORE = "domovoy-profile-state"
NO_CROSS_SOURCE = CrossSource(cheapest_portal=None, commission_savings=None, price_spread=None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("pipeline tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def profile() -> SearchProfile:
    return load_profile(load_json("profile_vinohrady.json"))


def make_listing(source_id: str = "1", portal: str = "sreality", **changes: Any) -> Listing:
    data = load_json("listing_example.json")
    data.update(portal=portal, source_id=source_id, url=f"https://example.test/{portal}/{source_id}", **changes)
    return Listing.model_validate(data)


def extraction_with(provider: str | None = "featherless", **values: Any) -> Extraction:
    """An Extraction with the given field values, a quote on each, and the given provider."""
    data = empty_extraction().model_dump(mode="json")
    for name, value in values.items():
        data[name] = {"value": value, "quote": "test quote", "confidence": 0.9, "verified": True}
    data.update(
        provider=provider,
        model="test-model" if provider else None,
        status="ok" if provider else "failed",
    )
    return Extraction.model_validate(data)


class FakeSource:
    def __init__(self, name: str, listings: list[Listing], *, error: Exception | None = None, stats: Any = None):
        self.name = name
        self.listings = listings
        self.error = error
        self.called = False
        if stats is not None:
            self.last_stats = stats

    async def collect(self, profile: SearchProfile, ctx: Any):
        self.called = True
        for listing in self.listings:
            yield listing
        if self.error is not None:
            raise self.error

    def normalize(self, raw: dict[str, Any], collected_at: Any) -> Listing:
        raise NotImplementedError


class FakeKV:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def get_value(self, key: str) -> Any:
        return self.data.get(key)

    async def set_value(self, key: str, value: Any) -> None:
        self.data[key] = value


class FakePlatform:
    def __init__(self) -> None:
        self.output: dict[str, Any] = {}
        self.items: list[dict[str, Any]] = []
        self.stores: dict[str, FakeKV] = {}

    async def set_value(self, key: str, value: Any) -> None:
        self.output[key] = value

    async def push_data(self, items: list[dict[str, Any]]) -> None:
        self.items.extend(items)

    async def open_key_value_store(self, name: str) -> FakeKV:
        return self.stores.setdefault(name, FakeKV())


def fake_dedup(*, changes: dict[str, str] | None = None, cheapest: str | None = None) -> SimpleNamespace:
    """WP6 names and signatures, simplified: one flat per listing, property id "p-<portal>-<source_id>"."""
    overrides = changes or {}
    calls = SimpleNamespace(diff_states=[], saved_ids=[], saved_states=[], recorded=0)

    async def load_property_ids(store: FakeKV) -> dict[str, str]:
        return dict(await store.get_value("ids") or {})

    async def save_property_ids(store: FakeKV, ids: dict[str, str]) -> None:
        calls.saved_ids.append(dict(ids))
        await store.set_value("ids", dict(ids))

    async def load_profile_state(store: FakeKV, profile_id: str) -> ProfileState:
        stored = await store.get_value(profile_id)
        if stored:
            return ProfileState.model_validate(stored)
        return ProfileState(profile_id=profile_id, profile_hash=None)

    async def save_profile_state(store: FakeKV, state: ProfileState) -> None:
        calls.saved_states.append(state)
        await store.set_value(state.profile_id, state.model_dump(mode="json"))

    def merge(listings: list[Listing], ids: dict[str, str]) -> list[Flat]:
        flats = []
        for listing in listings:
            property_id = ids.setdefault(
                f"{listing.portal}:{listing.source_id}", f"p-{listing.portal}-{listing.source_id}"
            )
            flats.append(
                Flat(property_id=property_id, sources=[listing], primary=listing, cross_source=NO_CROSS_SOURCE)
            )
        return flats

    def diff(flats: list[Flat], state: ProfileState) -> list[tuple[Flat, str]]:
        calls.diff_states.append(state)
        result = []
        for flat in flats:
            seen = state.flats.get(flat.property_id)
            default = "new" if seen is None else "unchanged"
            result.append((flat, overrides.get(flat.primary.source_id, default)))
        return result

    def record_run(state: ProfileState, flats: list[Flat], now: datetime) -> ProfileState:
        calls.recorded += 1
        flat_states = dict(state.flats)
        for flat in flats:
            flat_states[flat.property_id] = FlatState(content_hash="fake", first_seen=now, last_seen=now)
        return ProfileState(profile_id=state.profile_id, profile_hash=state.profile_hash, flats=flat_states)

    def cross_source(sources: list[Listing], commissions: dict[str, int | None] | None = None) -> CrossSource:
        return CrossSource(cheapest_portal=cheapest, commission_savings=None, price_spread=None)

    return SimpleNamespace(
        PROPERTY_IDS_STORE=PROPERTY_IDS_STORE,
        PROFILE_STATE_STORE=PROFILE_STATE_STORE,
        load_property_ids=load_property_ids,
        save_property_ids=save_property_ids,
        load_profile_state=load_profile_state,
        save_profile_state=save_profile_state,
        merge=merge,
        diff=diff,
        record_run=record_run,
        cross_source=cross_source,
        calls=calls,
    )


def fake_costs(*, rejected_source_ids: tuple[str, ...] = ()) -> SimpleNamespace:
    def compute_costs(listing: Listing, ex: Extraction, profile: SearchProfile) -> Costs:
        return Costs(
            rent=listing.rent, services=None, energy=None, total_monthly=listing.rent, kauce=None,
            commission=None, one_time_fees=None, first_payment=None, upfront=None,
            missing_furniture=[], missing_furniture_cost=None, hidden_monthly=None, estimated=[],
        )

    def evaluate(listing: Listing, ex: Extraction, costs: Costs, profile: SearchProfile) -> Evaluation:
        if listing.source_id in rejected_source_ids:
            verdict = Verdict(name="max_total_monthly", verdict="fail", estimated=False, reason="over the cap")
            return Evaluation(match="rejected", requirements=[verdict], unknowns=[], match_reasons=[], risk_flags=[])
        verdict = Verdict(name="max_total_monthly", verdict="pass", estimated=False, reason="within the cap")
        return Evaluation(
            match="strong", requirements=[verdict], unknowns=[], match_reasons=["within the cap"], risk_flags=[]
        )

    return SimpleNamespace(compute_costs=compute_costs, evaluate=evaluate)


def fake_extraction(*, error: Exception | None = None, provider: str = "featherless") -> tuple[SimpleNamespace, list[str]]:
    """A stand-in for the WP4 Extractor: extract(listing) and aclose()."""
    calls: list[str] = []

    async def extract(listing: Listing) -> Extraction:
        calls.append(listing.source_id)
        if error is not None:
            raise error
        return extraction_with(provider=provider, rent=listing.rent)

    async def aclose() -> None:
        return None

    return SimpleNamespace(extract=extract, aclose=aclose), calls


def fake_notion(
    *, validate_error: Exception | None = None, upsert_error: Exception | None = None, action: str = "created"
) -> tuple[SimpleNamespace, list[str]]:
    upserts: list[str] = []
    closed: list[bool] = []

    class Sink:
        def __init__(self, *, token: str, data_source_id: str) -> None:
            self.token = token
            self.data_source_id = data_source_id

        async def validate(self) -> None:
            if validate_error is not None:
                raise validate_error

        async def aclose(self) -> None:
            closed.append(True)

        async def upsert(self, item: Any) -> UpsertResult:
            upserts.append(item.property_id)
            if upsert_error is not None:
                raise upsert_error
            return UpsertResult(page_id=f"page-{item.property_id}", action=action)

    Sink.closed = closed
    return SimpleNamespace(NotionSink=Sink), upserts


async def run_pipeline(sources, modules, *, actor_input=None, platform=None, environ=None):
    platform = platform if platform is not None else FakePlatform()
    actor_input = {"skipExtraction": True, **(actor_input or {})}
    summary = await run_search(
        profile(), actor_input, platform, LOG,
        sources=sources, modules=modules, environ=environ if environ is not None else {},
    )
    return summary, platform


# Source status and collection


async def test_a_failing_source_is_reported_and_the_run_still_succeeds():
    ok = FakeSource("sreality", [make_listing("1"), make_listing("2")])
    broken = FakeSource("bezrealitky", [make_listing("3", portal="bezrealitky")], error=SourceError("portal changed"))
    summary, platform = await run_pipeline({"sreality": ok, "bezrealitky": broken}, Modules())
    by_portal = {row.portal: row for row in summary.sources}
    assert (by_portal["sreality"].status, by_portal["sreality"].found) == ("ok", 2)
    assert (by_portal["bezrealitky"].status, by_portal["bezrealitky"].found, by_portal["bezrealitky"].error) == (
        "failed", 1, "portal changed",
    )
    assert by_portal["idnes"].error == "source not registered"
    assert len(platform.items) == 3
    assert summary.change["new"] == 3


@pytest.mark.parametrize(
    ("stats", "status", "found", "failed"),
    [
        (None, "ok", 2, 0),
        (SimpleNamespace(candidates=5, fetched=4, failed=0), "ok", 5, 0),
        (SimpleNamespace(candidates=5, fetched=3, failed=2), "degraded", 5, 2),
        ({"candidates": 5, "fetched": 4, "failed": 0, "skipped": 1}, "degraded", 5, 0),
    ],
)
async def test_last_stats_map_to_the_status_counts(stats, status, found, failed):
    source = FakeSource("sreality", [make_listing("1"), make_listing("2")], stats=stats)
    summary, _ = await run_pipeline({"sreality": source}, Modules())
    row = summary.sources[0]
    assert (row.status, row.found, row.failed) == (status, found, failed)


# Notion: validation, writes and the state gate


async def test_notion_schema_drift_stops_the_run_before_any_portal_is_contacted():
    sink, _ = fake_notion(validate_error=ValueError("schema drift: Status renamed"))
    source = FakeSource("sreality", [make_listing("1")])
    with pytest.raises(ValueError, match="schema drift"):
        await run_pipeline(
            {"sreality": source}, Modules(notion=sink),
            actor_input={"notion": {"dataSourceId": "ds-1"}}, environ={"NOTION_TOKEN": "ntn_test"},
        )
    assert source.called is False
    assert sink.NotionSink.closed == [True]  # the sink is closed even when validation fails


async def test_the_notion_sink_is_closed_after_a_run():
    ns, _ = fake_notion()
    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    await run_pipeline(
        sources, Modules(notion=ns), actor_input={"notion": {"dataSourceId": "ds-1"}},
        environ={"NOTION_TOKEN": "fake-notion-token-for-tests"},
    )
    assert ns.NotionSink.closed == [True]


async def test_a_notion_data_source_needs_a_token_before_scraping():
    sink, _ = fake_notion()
    source = FakeSource("sreality", [make_listing("1")])
    with pytest.raises(ValueError, match="no Notion token"):
        await run_pipeline(
            {"sreality": source}, Modules(notion=sink), actor_input={"notion": {"dataSourceId": "ds-1"}}, environ={},
        )
    assert source.called is False


async def test_rejected_flats_reach_the_dataset_but_not_notion():
    sink, upserts = fake_notion()
    dedup = fake_dedup()
    modules = Modules(dedup=dedup, costs=fake_costs(rejected_source_ids=("2",)), notion=sink)
    sources = {"sreality": FakeSource("sreality", [make_listing("1"), make_listing("2")])}
    summary, platform = await run_pipeline(
        sources, modules, actor_input={"notion": {"dataSourceId": "ds-1"}}, environ={"NOTION_TOKEN": "ntn_test"},
    )
    assert len(platform.items) == 2
    assert upserts == ["p-sreality-1"]
    assert summary.match == {"strong": 1, "needs_info": 0, "rejected": 1}
    assert summary.rejected_by_requirement == {"max_total_monthly": 1}
    assert summary.notion.created == 1
    assert dedup.calls.saved_ids == [{"sreality:1": "p-sreality-1", "sreality:2": "p-sreality-2"}]


async def test_a_failed_notion_write_is_counted_and_nothing_is_recorded_as_seen():
    sink, upserts = fake_notion(upsert_error=RuntimeError("429 from Notion"))
    dedup = fake_dedup()
    modules = Modules(dedup=dedup, costs=fake_costs(), notion=sink)
    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    summary, platform = await run_pipeline(
        sources, modules, actor_input={"notion": {"dataSourceId": "ds-1"}}, environ={"NOTION_TOKEN": "ntn_test"},
    )
    assert summary.notion.errors == 1
    assert upserts == ["p-sreality-1"]
    assert len(platform.items) == 1  # the dataset still gets the item
    assert dedup.calls.saved_ids == []
    assert dedup.calls.saved_states == []
    assert dedup.calls.recorded == 0


# Dedup wiring: state round trip, unchanged flats, cross-portal flag


async def test_a_clean_run_records_state_and_the_next_run_diffs_against_it():
    dedup = fake_dedup()
    modules = Modules(dedup=dedup, costs=fake_costs())

    def sources():
        return {"sreality": FakeSource("sreality", [make_listing("1")])}

    summary1, platform = await run_pipeline(sources(), modules)
    assert len(platform.items) == 1
    assert dedup.calls.saved_ids == [{"sreality:1": "p-sreality-1"}]
    assert "vinohrady-2kk-30k" in platform.stores[PROFILE_STATE_STORE].data

    summary2, platform = await run_pipeline(sources(), modules, platform=platform)
    assert dedup.calls.diff_states[-1].flats.keys() == {"p-sreality-1"}  # loaded from the store
    assert summary2.change == {"new": 0, "changed": 0, "unchanged": 1}
    assert len(platform.items) == 1  # unchanged is not emitted by default

    _, platform = await run_pipeline(sources(), modules, actor_input={"includeUnchanged": True}, platform=platform)
    assert len(platform.items) == 2
    assert platform.items[1]["change"] == "unchanged"


async def test_cheaper_on_another_portal_comes_from_cross_source():
    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    _, platform = await run_pipeline(sources, Modules(dedup=fake_dedup(cheapest="bezrealitky"), costs=fake_costs()))
    assert "cheaper on another portal" in platform.items[0]["risk_flags"]

    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    _, platform = await run_pipeline(sources, Modules(dedup=fake_dedup(cheapest="sreality"), costs=fake_costs()))
    assert "cheaper on another portal" not in platform.items[0]["risk_flags"]


# Fallbacks and extraction


async def test_without_stage_modules_each_listing_becomes_a_flat_with_unknown_values():
    sources = {"sreality": FakeSource("sreality", [make_listing("1"), make_listing("2")])}
    summary, platform = await run_pipeline(sources, Modules())
    items = platform.items
    assert len(items) == 2
    assert all(item["property_id"].startswith("tmp-") for item in items)
    assert all(item["match"] == "needs_info" for item in items)
    assert all(item["extraction"] is None for item in items)
    assert items[0]["rent"] == 24000 and items[0]["total_monthly"] is None
    assert summary.change == {"new": 2, "changed": 0, "unchanged": 0}


async def test_skip_extraction_never_calls_the_extractor():
    extraction, calls = fake_extraction()
    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    _, platform = await run_pipeline(
        sources, Modules(extraction=extraction, costs=fake_costs()), actor_input={"skipExtraction": True},
    )
    assert calls == []
    assert platform.items[0]["extraction"] is None


async def test_extraction_failure_keeps_the_flat_with_unknown_fields():
    extraction, calls = fake_extraction(error=RuntimeError("featherless down"))
    sources = {"sreality": FakeSource("sreality", [make_listing("1")])}
    summary, platform = await run_pipeline(
        sources, Modules(extraction=extraction, costs=fake_costs()), actor_input={"skipExtraction": False},
    )
    assert calls == ["1"]
    assert len(platform.items) == 1
    assert platform.items[0]["extraction"] is None
    assert summary.extraction_providers == {"featherless": 0, "openai": 0, "cache": 0}


async def test_extraction_providers_are_counted():
    extraction, _ = fake_extraction(provider="featherless")
    sources = {"sreality": FakeSource("sreality", [make_listing("1"), make_listing("2")])}
    summary, platform = await run_pipeline(
        sources, Modules(extraction=extraction, costs=fake_costs()), actor_input={"skipExtraction": False},
    )
    assert summary.extraction_providers["featherless"] == 2
    assert platform.items[0]["extraction"]["provider"] == "featherless"


async def test_secrets_never_reach_the_log_or_the_config_repr(caplog):
    caplog.set_level(logging.DEBUG)
    sink, _ = fake_notion()
    secret = "fake-notion-token-for-tests"
    await run_pipeline(
        {"sreality": FakeSource("sreality", [make_listing("1")])},
        Modules(notion=sink),
        actor_input={
            "notion": {"dataSourceId": "ds-1"},
            "featherlessApiKey": "fake-featherless-key-for-tests",
            "openaiApiKey": "fake-openai-key-for-tests",
        },
        environ={"NOTION_TOKEN": secret},
    )
    assert secret not in caplog.text
    assert "fake-featherless-key-for-tests" not in caplog.text
    assert "fake-featherless-key-for-tests" not in repr(llm_config({"featherlessApiKey": "fake-featherless-key-for-tests"}, {}))


# FlatItem assembly


def test_address_is_never_empty():
    assert address_for(make_listing(address="Mánesova 1, Praha 2"), profile()) == "Mánesova 1, Praha 2"
    assert address_for(make_listing(address=None, title="2+kk, Vinohrady"), profile()) == "2+kk, Vinohrady"
    assert address_for(make_listing(address=None, title=""), profile()) == "Praha, Vinohrady"


def test_flatitem_assembly_matches_the_hand_built_example():
    expected = load_json("flatitem_example.json")
    listing = Listing.model_validate(load_json("listing_example.json"))
    flat = Flat(property_id="p-EXAMPLE234", sources=[listing], primary=listing, cross_source=NO_CROSS_SOURCE)
    extraction = extraction_with(
        provider="openai", rent=24000, move_in_date="2027-01-01", lease_type="najem",
        lease_length_months=12, unit_type_hint="flat",
    ).model_copy(update={"model": "example-model", "status": "partial"})
    costs = Costs(
        rent=24000, services=2000, energy=1500, total_monthly=27500, kauce=24000, commission=0,
        one_time_fees=500, first_payment=27500, upfront=52000, missing_furniture=["washing machine"],
        missing_furniture_cost=8000, hidden_monthly=3500, estimated=["energy", "total_monthly"],
    )
    evaluation = Evaluation(
        match="needs_info",
        requirements=[Verdict(name="max_total_monthly", verdict="pass", estimated=True, reason="Energy is estimated")],
        unknowns=["Are energy costs included in the rent?"],
        match_reasons=["Rent is within the budget cap"],
        risk_flags=["fees not stated"],
    )
    item = build_flat_item(
        flat, extraction, costs, evaluation, profile=profile(), run_id="example-run", change="new",
        first_seen=datetime.fromisoformat(expected["first_seen"]),
        last_seen=datetime.fromisoformat(expected["last_seen"]), extraction_ran=True,
    )
    actual = item.model_dump(mode="json")
    assert {k: v for k, v in actual.items() if k != "evidence"} == {
        k: v for k, v in expected.items() if k != "evidence"
    }
    assert {entry["field"] for entry in actual["evidence"]} == {
        "rent", "move_in_date", "lease_type", "lease_length_months", "unit_type_hint",
    }


# Extraction wiring and LLM defaults


def test_llm_defaults_follow_the_wp4_decisions():
    cfg = llm_config({}, {})
    assert cfg.model == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert cfg.fallback_model == "deepseek-ai/DeepSeek-V4-Flash"
    assert cfg.concurrency == 1
    assert cfg.timeout_sec == 60
    assert cfg.featherless_api_key is None and cfg.openai_api_key is None
    custom = llm_config({"llm": {"model": "m2", "concurrency": 3, "fallbackModel": "f2", "timeoutSec": 30}}, {})
    assert (custom.model, custom.concurrency, custom.fallback_model, custom.timeout_sec) == ("m2", 3, "f2", 30)


def test_resolve_modules_returns_the_merged_stages():
    modules = resolve_modules(LOG)
    assert modules.dedup is dedup_stage
    assert modules.costs is costs_stage
    assert modules.notion is notion_stage
    assert modules.extraction is None  # the extractor is opened by open_extractor() inside the run


async def test_skip_extraction_never_opens_the_cache(monkeypatch):
    opened: list[bool] = []

    async def open_cache() -> None:
        opened.append(True)

    monkeypatch.setattr(pipeline_module, "open_apify_cache", open_cache)
    assert await open_extractor({"skipExtraction": True}, {}, LOG) is None
    assert opened == []


async def test_open_extractor_builds_the_extractor_over_the_cache(monkeypatch):
    built: dict[str, Any] = {}

    class Extractor:
        def __init__(self, cfg: Any, cache: Any, **kwargs: Any) -> None:
            built.update(cfg=cfg, cache=cache, kwargs=kwargs)

    cache = object()

    async def open_cache() -> object:
        return cache

    monkeypatch.setattr(pipeline_module, "open_apify_cache", open_cache)
    monkeypatch.setattr(pipeline_module, "Extractor", Extractor)
    extractor = await open_extractor(
        {"llm": {"concurrency": 1}}, {"FEATHERLESS_API_KEY": "fake-featherless-key-for-tests"}, LOG
    )
    assert isinstance(extractor, Extractor)
    assert built["cache"] is cache
    assert built["kwargs"] == {"min_confidence": 0.5}
    assert built["cfg"].model == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert built["cfg"].featherless_api_key.get_secret_value() == "fake-featherless-key-for-tests"
