# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Governance

Two authority files govern all work in this repository:

- **`governance/governance_local.jsonl`** — cross-repo rules (anti-monolith, docs-gate, specification discipline, code quality, bug discipline). Read this before making any changes.
- **`governance/specification.jsonl`** — authoritative specification of what this repo does, must do, and must not do. The single source of truth for this codebase.

Key rules to internalize from `governance_local.jsonl`:
- Files ≥ 1300 LOC must not grow at all; files ≥ 900 LOC have restricted growth
- No catchall filenames (`utils.py`, `helpers.py`, etc.) or directories
- A single change must not touch 3+ ownership areas (`src`, `scripts`, `badguys`, `tests`, `docs`)
- Specification changes must be committed before implementation changes

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/path/to/test_file.py

# Lint
ruff check scripts/ badguys/ tests/

# Type check
mypy scripts/

# Run Amp (apply a patch)
python3 scripts/am_patch.py ISSUE_ID "commit message" patches/issue_<ISSUE>_v<N>.zip --target-repo-name <repo>
```

## Architecture

PatchHub is the home of the Amp patch runner and the central artifact workspace.

**`scripts/am_patch/`** — the Amp tool itself:
- `cli.py` — CLI entry point
- `engine.py` / `engine_run_gates.py` — patch application engine and gate execution
- `config.py` / `config_schema.py` — configuration loading and validation
- `config_monolith_areas.py` — ownership area definitions used by the monolith gate
- `artifacts.py` / `archive.py` — overlay and success archive management
- `apply_failure_gates_policy.py` — policy for handling gate failures

**`patches/`** — artifact store: patch zips (`issue_<N>_v<N>.zip`), overlays (`patched_issue<N>_*.zip`), Amp logs. Not a source directory — do not treat its contents as code.

**`badguys/`** — integration test suite runner shared with audiomason2.

**`governance/`** — authority corpus (`governance.jsonl`, `governance_local.jsonl`, `specification.jsonl`). Synced automatically from the governance repo on every push.

## Ownership areas

| Area | Path |
|---|---|
| `src` | `src/` |
| `scripts` | `scripts/` |
| `badguys` | `badguys/` |
| `tests` | `tests/` |
| `docs` | `docs/` |

A single change must not span 3+ of these areas.
