<p align="center">
  <img src="./assets/patchhub-logo.png" alt="PatchHub logo" width="280">
</p>

# PatchHub

PatchHub is the operator-facing control surface for the AM Patch workflow in this repository. It pairs a web UI and HTTP API with the `am_patch` runner, patch archive handling, workspace lifecycle management, live job monitoring, rollback/revert flows, governance tooling, and deterministic test infrastructure.

## What is in this repository

This repository is not just the PatchHub web app. It bundles several tightly related subsystems:

- **PatchHub web surface** in `scripts/patchhub/` and the entry script `scripts/patchhub.py`
- **AM Patch runner** in `scripts/am_patch/` and the entry script `scripts/am_patch.py`
- **Governance and validation tooling** in `governance/`
- **BadGuys deterministic test harness** in `badguys/`
- **Python and browser-facing test suites** in `tests/`

In practice, PatchHub is the browser-based operator layer on top of the runner. The default PatchHub config points its runner command at `python3 scripts/am_patch.py`, enables queued execution, uses `patches/` as the patches root, and uses `patches/incoming/` as the upload directory.

## PatchHub at a glance

PatchHub serves three main UI pages:

- `/` — the main operator console
- `/editor` — the governance/spec editor surface
- `/debug` — diagnostics and debug surface

The main UI exposes repository-facing operational areas such as:

- patch submission and queueing
- jobs and runs inspection
- workspace inspection
- AMP settings editing
- rollback guidance and revert/rollback operations

The HTTP API is broader than the UI and includes families for:

- runner and app configuration
- files and downloads
- workspaces
- patches inventory and latest patch discovery
- jobs, runs, logs, and event streams
- editor bootstrap, validation, preview, and save flows
- AMP schema and AMP config access

## Key runtime entry points

### Start PatchHub

```bash
python3 scripts/patchhub.py
```

By default, PatchHub reads `scripts/patchhub/patchhub.toml` and starts an ASGI server on `0.0.0.0:8099`.

### Start PatchHub with an explicit config path

```bash
python3 scripts/patchhub.py --config scripts/patchhub/patchhub.toml
```

### Run the AM Patch runner directly

```bash
python3 scripts/am_patch.py --help
```

### Inspect effective runner config

```bash
python3 scripts/am_patch.py --show-config
```

## Development prerequisites

At minimum, the repo expects:

- **Python 3.11+**
- **Node.js + npm** for Biome and TypeScript tooling
- **git**
- **unzip** and standard shell utilities used by repo tooling

## Suggested local setup

This repository is currently script-driven. The practical way to work with it is to run the repo entry scripts directly.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  fastapi uvicorn python-multipart websockets \
  pydantic pyyaml typer rich mutagen \
  pytest pytest-asyncio pytest-timeout pytest-forked pytest-playwright-asyncio pytest-cov \
  mypy ruff types-pyyaml httpx
npm install
```

## Configuration files that matter first

### PatchHub config

`scripts/patchhub/patchhub.toml` controls the PatchHub server, runner wiring, upload policy, UI defaults, targeting defaults, indexing, cleanup policy, and web-jobs persistence/retention.

Important defaults currently visible in that file:

- host: `0.0.0.0`
- port: `8099`
- runner command: `python3 scripts/am_patch.py`
- queue enabled: `true`
- patches root: `patches`
- upload dir: `patches/incoming`
- default target repo: `patchhub`

### Repo-local runner policy

`am_patch.repo.toml` holds repo-local AM Patch policy, including:

- Python gate mode/interpreter wiring
- Ruff, mypy, pytest, JS, Biome, BadGuys, docs, and monolith gate settings
- do-not-touch paths
- promotion policy
- pytest routing metadata

## Testing and verification

### Python tests

```bash
pytest -q
```

The repo contains an extensive pytest suite under `tests/`, including PatchHub API/UI logic, AM Patch runner behavior, validator behavior, BadGuys wiring, and E2E coverage.

### BadGuys suite

The deterministic BadGuys suite lives under `badguys/tests/` and covers runner and policy behavior through `.bdg` cases.

### JavaScript and TypeScript checks

```bash
npm run lint
npm run typecheck
```

## Governance tooling

The `governance/` directory is not decorative. It is the repo-local governance corpus and
authority data surface. The executable governance toolkit is a separate standalone runtime
selected server-side by PatchHub from the configured GitHub authority source; the repo-local
`governance/*.py` files are not the active runtime authority path for PatchHub operations.

Useful commands when you already have a standalone governance toolkit checkout or extracted
GitHub-selected toolkit bundle:

```bash
python /path/to/standalone-governance-toolkit/governance/validate_master_spec_v2.py governance/specification.jsonl
python /path/to/standalone-governance-toolkit/governance/render_master_spec_txt.py governance/specification.jsonl
python /path/to/standalone-governance-toolkit/governance/gov_navigator.py governance/specification.jsonl
```

## What PatchHub is responsible for

From the code currently in this snapshot, PatchHub is responsible for all of the following operational concerns:

- serving the web UI and static assets
- exposing HTTP APIs for jobs, runs, files, workspaces, editor flows, and AMP config flows
- orchestrating queued execution of the runner
- tracking live logs and event streams
- keeping a patch inventory and autofill metadata
- cleaning retained repo snapshot archives after successful jobs
- supporting rollback/revert-related UI and backend flows

## Current repo reality

A few points are worth stating clearly:

- The root `README.md` currently contains only `# patchhub`.
- The repository is much broader than a minimal web UI project.
- The operationally important entry points are repository scripts, not a polished installable CLI package.
- The repo contains both Python and JavaScript/TypeScript toolchains.

## Recommended first-read files

If you are new to this repository, start here:

1. `scripts/patchhub.py`
2. `scripts/patchhub/patchhub.toml`
3. `scripts/am_patch.py`
4. `am_patch.repo.toml`
5. `governance/specification.jsonl`
6. `governance/governance.jsonl`

## License

The current `pyproject.toml` declares the project license as **MIT**.
