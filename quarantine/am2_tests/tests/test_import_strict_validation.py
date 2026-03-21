"""Issue 270: strict validators for FlowConfig and WizardDefinition."""

from __future__ import annotations

from importlib import import_module

import pytest

normalize_flow_config = import_module("plugins.import.flow_config_validation").normalize_flow_config
validate_flow_config_editor_boundary = import_module(
    "plugins.import.flow_config_validation"
).validate_flow_config_editor_boundary
FinalizeError = import_module("plugins.import.errors").FinalizeError
validate_wizard_definition_structure = import_module(
    "plugins.import.wizard_definition_model"
).validate_wizard_definition_structure


def test_flow_config_rejects_ui() -> None:
    with pytest.raises(ValueError):
        normalize_flow_config({"version": 1, "steps": {}, "defaults": {}, "ui": {}})


def test_flow_config_editor_boundary_does_not_read_projection_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step_catalog = import_module("plugins.import.step_catalog")

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("projection helper should not be consulted")

    monkeypatch.setattr(step_catalog, "get_step_details", _boom)
    monkeypatch.setattr(step_catalog, "build_default_step_catalog_projection", _boom)

    out = validate_flow_config_editor_boundary(
        {
            "version": 1,
            "steps": {"publish_policy": {"enabled": True}},
            "defaults": {"publish_policy": {"custom": {"mode": "copy"}}},
        }
    )

    assert out["defaults"] == {"publish_policy": {"custom": {"mode": "copy"}}}


def test_wizard_definition_v2_rejects_wizard_id() -> None:
    with pytest.raises(FinalizeError):
        validate_wizard_definition_structure(
            {
                "version": 2,
                "wizard_id": "import",
                "graph": {
                    "entry_step_id": "select_authors",
                    "nodes": [{"step_id": "select_authors"}],
                    "edges": [],
                },
            }
        )


def test_wizard_definition_v2_rejects_unknown_keys() -> None:
    with pytest.raises(FinalizeError):
        validate_wizard_definition_structure(
            {
                "version": 2,
                "graph": {
                    "entry_step_id": "select_authors",
                    "nodes": [{"step_id": "select_authors", "extra": 1}],
                    "edges": [],
                },
            }
        )

    with pytest.raises(FinalizeError):
        validate_wizard_definition_structure(
            {
                "version": 2,
                "graph": {
                    "entry_step_id": "select_authors",
                    "nodes": [{"step_id": "select_authors"}],
                    "edges": [
                        {
                            "from_step_id": "select_authors",
                            "to_step_id": "select_authors",
                            "priority": 1,
                            "when": None,
                            "x": 1,
                        }
                    ],
                },
            }
        )


def test_wizard_definition_v2_rejects_editor_metadata() -> None:
    with pytest.raises(FinalizeError):
        validate_wizard_definition_structure(
            {
                "version": 2,
                "graph": {
                    "entry_step_id": "select_authors",
                    "nodes": [{"step_id": "select_authors"}],
                    "edges": [],
                },
                "_am2_ui": {"showOptional": True},
            }
        )
