"""Issue 103: ExprRef evaluator behavior."""

from __future__ import annotations

from importlib import import_module

import pytest

eval_expr_ref = import_module("plugins.import.dsl").eval_expr_ref


@pytest.mark.parametrize(
    ("expr_ref", "expected"),
    [
        ({"expr": "$.state.count < 5"}, True),
        ({"expr": '"oh" in $.inputs.name'}, True),
        ({"expr": 'lower($.inputs.name) == "john"'}, True),
        ({"expr": 'upper($.inputs.name) == "JOHN"'}, True),
        ({"expr": 'replace($.inputs.name, "J", "P") == "Pohn"'}, True),
    ],
)
def test_eval_expr_ref_baseline_cases(
    expr_ref: dict[str, str],
    expected: bool | None,
) -> None:
    state = {
        "count": 3,
        "flags": [True, False, True],
    }
    inputs = {
        "name": "John",
        "csv": "a,b",
        "items": [1, 2],
        "flags": [True, True],
    }

    ok, value, error = eval_expr_ref(expr_ref, state=state, inputs=inputs)

    if expected is None:
        assert ok is False
        assert value is None
        assert error is not None
        return

    assert ok is True
    assert error is None
    assert value is expected


def test_eval_expr_ref_supports_split() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": 'len(split($.inputs.csv, ",")) == 2'},
        state={},
        inputs={"csv": "a,b"},
    )

    assert ok is True
    assert value is True
    assert error is None


def test_eval_expr_ref_supports_any_all_and_len() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "any($.inputs.flags) and all($.inputs.flags) and len($.inputs.flags) == 2"},
        state={},
        inputs={"flags": [True, True]},
    )

    assert ok is True
    assert value is True
    assert error is None


def test_eval_expr_ref_reports_missing_key() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "$.state.missing == 1"},
        state={},
        inputs={},
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "missing_path"
    assert error["reason"] == "missing_key"


def test_eval_expr_ref_reports_type_mismatch() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "not $.inputs.name"},
        state={},
        inputs={"name": "John"},
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "type_mismatch"
    assert error["reason"] == "not_requires_bool"


def test_eval_expr_ref_reports_unknown_function() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "mystery($.inputs.name)"},
        state={},
        inputs={"name": "John"},
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "unknown_function"


def test_eval_expr_ref_rejects_forbidden_root() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "$.env.secret"},
        state={},
        inputs={},
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "forbidden_root"


def test_eval_expr_ref_allows_op_outputs_only_with_gate() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": "$.op.outputs.answer == 7"},
        state={},
        inputs={},
        op_outputs={"answer": 7},
        allow_op_outputs=False,
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "forbidden_root"

    ok, value, error = eval_expr_ref(
        {"expr": "$.op.outputs.answer == 7"},
        state={},
        inputs={},
        op_outputs={"answer": 7},
        allow_op_outputs=True,
    )

    assert ok is True
    assert value is True
    assert error is None


def test_eval_expr_ref_is_total_for_invalid_input_shape() -> None:
    ok, value, error = eval_expr_ref(
        {"expr": 123},  # type: ignore[arg-type]
        state={},
        inputs={},
    )

    assert ok is False
    assert value is None
    assert error is not None
    assert error["code"] == "invalid_expr_ref"
