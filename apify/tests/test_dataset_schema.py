"""The dataset schema describes the FlatItem output (e2e check L3.dataset_schema).

Offline. Fails when .actor/dataset_schema.json and domovoy/models.py FlatItem drift apart.
"""

import json
from pathlib import Path
from typing import get_args

from domovoy.models import FlatItem

SCHEMA_PATH = Path(__file__).resolve().parents[1] / ".actor" / "dataset_schema.json"
MONEY_FIELDS = [
    "rent", "services", "energy", "total_monthly", "kauce", "commission",
    "one_time_fees", "first_payment", "move_in_cost", "missing_furniture_cost",
]


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def properties() -> dict:
    return schema()["fields"]["properties"]


def test_every_flatitem_field_is_in_the_schema():
    assert set(FlatItem.model_fields) - set(properties()) == set()


def test_schema_has_no_field_that_flatitem_lacks():
    assert set(properties()) - set(FlatItem.model_fields) == set()


def test_nullable_is_set_exactly_where_the_model_allows_none():
    for name, field in FlatItem.model_fields.items():
        allows_none = type(None) in get_args(field.annotation)
        assert bool(properties()[name].get("nullable")) == allows_none, name


def test_money_fields_are_integers():
    for name in MONEY_FIELDS:
        assert properties()[name]["type"] == "integer", name


def test_overview_view_names_schema_fields():
    view = schema()["views"]["overview"]
    fields = view["transformation"]["fields"]
    assert 8 <= len(fields) <= 12
    assert set(fields) <= set(properties())
    assert set(view["display"]["properties"]) == set(fields)
