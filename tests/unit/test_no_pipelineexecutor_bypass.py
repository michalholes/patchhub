"""Guardrail: no PipelineExecutor bypass outside core orchestration.

Baseline requires that UI layers (CLI/daemon/web) must not execute pipelines directly.
They must create Jobs via the core Orchestrator and only observe state/logs.
"""

from __future__ import annotations

from pathlib import Path

ALLOWLIST = {
    Path("src/audiomason/core/orchestration.py"),
    Path("src/audiomason/core/pipeline.py"),
}


def _iter_runtime_py_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / "src",
        repo_root / "plugins",
    ]
    out: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.py"):
            out.append(p)
    return sorted(out)


def test_no_execute_from_yaml_outside_core_allowlist() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for p in _iter_runtime_py_files(repo_root):
        rel = p.relative_to(repo_root)

        if rel in ALLOWLIST:
            continue

        text = p.read_text(encoding="utf-8")
        if "execute_from_yaml" in text:
            offenders.append(str(rel))

    assert offenders == [], f"execute_from_yaml found outside allowlist: {offenders}"
