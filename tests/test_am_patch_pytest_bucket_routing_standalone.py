from __future__ import annotations

from pathlib import Path

import pytest

from am_patch.errors import RunnerError
from am_patch.pytest_bucket_routing import select_pytest_targets


def test_bucketed_routing_keeps_full_suite_prefixes() -> None:
    targets = select_pytest_targets(
        decision_paths=["pytest.ini"],
        pytest_targets=["tests"],
        routing_policy={"pytest_routing_mode": "bucketed"},
    )
    assert targets == ["tests"]


def test_bucketed_routing_selects_amp_related_tests() -> None:
    targets = select_pytest_targets(
        decision_paths=["amp/am_patch/runtime.py"],
        pytest_targets=["tests"],
        routing_policy={"pytest_routing_mode": "bucketed"},
    )
    assert "tests/test_runtime_layout.py" in targets
    assert "tests/test_root_model_layout.py" in targets
    assert "tests/integration/test_am_patch_smoke_issue666.py" in targets


def test_bucketed_routing_skips_unrelated_paths() -> None:
    targets = select_pytest_targets(
        decision_paths=["docs/readme.txt"],
        pytest_targets=["tests"],
        routing_policy={"pytest_routing_mode": "bucketed"},
    )
    assert targets == []


def test_bucketed_routing_rejects_invalid_mode() -> None:
    with pytest.raises(RunnerError, match="invalid pytest_routing_mode"):
        select_pytest_targets(
            decision_paths=["amp/am_patch/runtime.py"],
            pytest_targets=["tests"],
            routing_policy={"pytest_routing_mode": "weird"},
        )
