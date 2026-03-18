from __future__ import annotations

import sys
from pathlib import Path


def _import_runner_modules():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from am_patch import gates_policy_wiring as wiring_mod
    from am_patch.config import Policy

    return Policy, wiring_mod


def test_biome_controls_propagated(monkeypatch, tmp_path: Path) -> None:
    policy_cls, wiring_mod = _import_runner_modules()

    captured: dict[str, object] = {}

    def fake_run_gates(*_args, **kwargs):
        captured["biome_format"] = kwargs.get("biome_format")
        captured["biome_format_command"] = kwargs.get("biome_format_command")

    import am_patch.gates as gates_mod

    monkeypatch.setattr(gates_mod, "run_gates", fake_run_gates)
    monkeypatch.setattr(wiring_mod, "changed_path_entries", lambda *_a, **_k: [])
    policy = policy_cls()
    policy.biome_format = False
    policy.gate_biome_format_command = ["biome", "format", "--write"]

    wiring_mod.run_policy_gates(
        logger=None,  # type: ignore[arg-type]
        cwd=tmp_path,
        repo_root=tmp_path,
        policy=policy,
        decision_paths=[],
        progress=None,
    )

    assert captured.get("biome_format") is False
    assert captured.get("biome_format_command") == ["biome", "format", "--write"]


def test_docs_status_entries_use_cwd(monkeypatch, tmp_path: Path) -> None:
    policy_cls, wiring_mod = _import_runner_modules()

    captured: dict[str, object] = {}
    repo_root = tmp_path / "repo-root"
    cwd = tmp_path / "workspace"
    repo_root.mkdir()
    cwd.mkdir()

    def fake_changed_path_entries(_logger, root: Path):
        captured["changed_path_entries_root"] = root
        return [("??", "docs/change_fragments/test.md")]

    def fake_run_gates(*_args, **kwargs):
        captured["docs_status_entries"] = kwargs.get("docs_status_entries")

    import am_patch.gates as gates_mod

    monkeypatch.setattr(wiring_mod, "changed_path_entries", fake_changed_path_entries)
    monkeypatch.setattr(gates_mod, "run_gates", fake_run_gates)

    wiring_mod.run_policy_gates(
        logger=None,  # type: ignore[arg-type]
        cwd=cwd,
        repo_root=repo_root,
        policy=policy_cls(),
        decision_paths=[],
        progress=None,
    )

    assert captured.get("changed_path_entries_root") == cwd
    assert captured.get("docs_status_entries") == [("??", "docs/change_fragments/test.md")]
