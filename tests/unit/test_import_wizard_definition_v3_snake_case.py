"""Issue 102: WizardDefinition v3 snake_case validation."""

from __future__ import annotations

from importlib import import_module

import pytest

FieldSchemaValidationError = import_module(
    "plugins.import.field_schema_validation"
).FieldSchemaValidationError
validate_wizard_definition_v3_structure = import_module(
    "plugins.import.dsl.wizard_definition_v3_model"
).validate_wizard_definition_v3_structure


def test_wizard_definition_v3_rejects_non_snake_case_step_id() -> None:
    wd = {
        "version": 3,
        "entry_step_id": "Step1",
        "nodes": [
            {
                "step_id": "Step1",
                "op": {
                    "primitive_id": "select_authors",
                    "primitive_version": 1,
                    "inputs": {},
                    "writes": [],
                },
            }
        ],
        "edges": [],
    }

    with pytest.raises(FieldSchemaValidationError) as excinfo:
        validate_wizard_definition_v3_structure(wd)

    err = excinfo.value
    assert err.path == "$.entry_step_id"
    assert err.reason == "missing_or_invalid"
