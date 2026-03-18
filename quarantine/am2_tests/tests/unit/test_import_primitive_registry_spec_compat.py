"""Issue 102: primitive registry spec compatibility."""

from __future__ import annotations

from importlib import import_module

import pytest

FieldSchemaValidationError = import_module(
    "plugins.import.field_schema_validation"
).FieldSchemaValidationError
validate_primitive_registry = import_module(
    "plugins.import.dsl.primitive_registry_model"
).validate_primitive_registry


def _minimal_registry() -> dict[str, object]:
    return {
        "registry_version": 1,
        "primitives": [
            {
                "primitive_id": "import.phase1_runtime",
                "version": 1,
                "phase": 1,
                "inputs_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "outputs_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "allowed_errors": [],
            }
        ],
    }


def test_registry_accepts_minimal_spec_entry_without_determinism_notes() -> None:
    registry = _minimal_registry()

    out = validate_primitive_registry(registry)

    assert out["registry_version"] == 1
    assert out["primitives"][0]["primitive_id"] == "import.phase1_runtime"
    assert "determinism_notes" not in out["primitives"][0]


def test_registry_allows_extra_primitive_entry_fields() -> None:
    registry = _minimal_registry()
    registry["primitives"][0]["extra_metadata"] = {"owner": "import"}

    out = validate_primitive_registry(registry)

    assert out["primitives"][0]["extra_metadata"] == {"owner": "import"}


def test_registry_rejects_unknown_schema_subset_key() -> None:
    registry = _minimal_registry()
    registry["primitives"][0]["inputs_schema"] = {"type": "object", "bogus": 1}

    with pytest.raises(FieldSchemaValidationError) as excinfo:
        validate_primitive_registry(registry)

    err = excinfo.value
    assert err.path == "$.primitives[0].inputs_schema.bogus"
    assert err.reason == "unknown_field"
