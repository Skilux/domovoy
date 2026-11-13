"""Search profile: Pydantic validation and the profile.schema.json check."""

import json
from pathlib import Path
from typing import Any

import jsonschema

from domovoy.models import SearchProfile

SCHEMA_PATH = Path(__file__).parent / "schemas" / "profile.schema.json"


def load_profile(data: Any) -> SearchProfile:
    """Validate a raw profile dict. Raises pydantic.ValidationError that names the bad field."""
    return SearchProfile.model_validate(data)


def schema_errors(data: Any) -> list[str]:
    """Errors from profile.schema.json, one line each. An empty list means the profile is valid."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(data)
    ]
