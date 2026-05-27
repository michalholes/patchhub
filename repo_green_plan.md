# Repository Green Plan (Operational)

## Objective
- Bring this repository to full green on:
  - `ruff`
  - `mypy`
  - `pyright`
  - `pytest`
- Execute in small, low-risk batches with optional delegation.

## Baseline Snapshot
- `ruff check scripts/ badguys/ tests/` -> 162 errors
- `mypy scripts/` -> 5490 errors
- `pyright` -> 2231 errors
- `pytest` -> 26 failed, 579 passed

## Status Legend
- Status: `todo` | `in_progress` | `blocked` | `done`
- Priority: `P0` (highest) to `P3` (lowest)
- ETA values are planning targets, not commitments.

## Operating Rules
- Micro-batch size:
  - 1-2 files
  - up to ~120 changed lines
- Scope control:
  - prefer one ownership area per batch
  - never touch 3+ ownership areas in one batch
- Validation per batch:
  - `ruff check <changed files>`
  - `mypy <changed files>` for `scripts/`
  - `pyright <changed files>`
  - targeted `pytest` for affected modules
- Full checks run only at milestone boundaries.

## Milestone Checklist

### M0 - Baseline + Guardrails
- [ ] Capture current error snapshots to tracking note
  - Owner: Lead
  - Priority: P0
  - ETA: 0.5d
  - Status: todo
- [ ] Confirm batching and validation protocol with contributors
  - Owner: Lead
  - Priority: P1
  - ETA: 0.25d
  - Status: todo

### M1 - Stabilize `am_patch` runtime tests
- [ ] Fix `SimpleNamespace` compatibility in `initial_self_backup` paths
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.5d
  - Status: todo
- [ ] Restore CLI-attribute fallbacks in startup/patch input flow
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.5d
  - Status: todo
- [ ] Restore post-run pipeline compatibility expectations
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.75d
  - Status: todo
- [ ] Exit check: `pytest tests/test_am_patch_*`
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.25d
  - Status: todo

### M2 - Lock `scripts/am_patch`
- [ ] `ruff check scripts/am_patch`
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.1d
  - Status: todo
- [ ] `mypy scripts/am_patch`
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.1d
  - Status: todo
- [ ] `pyright scripts/am_patch`
  - Owner: Agent A
  - Priority: P0
  - ETA: 0.1d
  - Status: todo

### M3 - Ruff lane A (`badguys/`)
- [ ] Remove `Any` from `badguys` file-by-file (`TID251`, `ANN401`)
  - Owner: Agent B
  - Priority: P1
  - ETA: 1.5d
  - Status: todo
- [ ] Exit check: `ruff check badguys/`
  - Owner: Agent B
  - Priority: P1
  - ETA: 0.25d
  - Status: todo

### M4 - Ruff lane B (`scripts/patchhub`)
- [ ] Cluster 1: `app_api_*`
  - Owner: Agent C
  - Priority: P1
  - ETA: 1.0d
  - Status: todo
- [ ] Cluster 2: `asgi/*`
  - Owner: Agent C
  - Priority: P1
  - ETA: 1.5d
  - Status: todo
- [ ] Cluster 3: `editor_*`
  - Owner: Agent D
  - Priority: P1
  - ETA: 1.5d
  - Status: todo
- [ ] Cluster 4: `web_jobs_*`
  - Owner: Agent D
  - Priority: P1
  - ETA: 1.5d
  - Status: todo
- [ ] Cluster 5: `models.py`, `job_store.py`, `app_support.py`
  - Owner: Agent D
  - Priority: P1
  - ETA: 1.0d
  - Status: todo
- [ ] Exit check: `ruff check scripts/`
  - Owner: Lead
  - Priority: P1
  - ETA: 0.25d
  - Status: todo

### M5 - Mypy hardening (`scripts/`)
- [ ] Target high-impact modules (`models`, `job_store`, `web_jobs_db`, `editor_codec`)
  - Owner: Agents C/D
  - Priority: P1
  - ETA: 2.5d
  - Status: todo
- [ ] Resolve private-usage via public wrappers/aliases where required
  - Owner: Agents C/D
  - Priority: P1
  - ETA: 1.0d
  - Status: todo
- [ ] Exit check: `mypy scripts/`
  - Owner: Lead
  - Priority: P1
  - ETA: 0.25d
  - Status: todo

### M6 - Pyright hardening (repo-wide)
- [ ] Eliminate `reportUnknown*` hotspots by cluster
  - Owner: Agents C/D
  - Priority: P1
  - ETA: 2.0d
  - Status: todo
- [ ] Eliminate `reportPrivateUsage` hotspots by API cleanup
  - Owner: Agents C/D
  - Priority: P1
  - ETA: 1.0d
  - Status: todo
- [ ] Resolve missing import typing surfaces in ASGI/FastAPI paths
  - Owner: Agent C
  - Priority: P2
  - ETA: 0.5d
  - Status: todo
- [ ] Exit check: `pyright`
  - Owner: Lead
  - Priority: P1
  - ETA: 0.25d
  - Status: todo

### M7 - Final full green + closure
- [ ] `ruff check scripts/ badguys/ tests/`
  - Owner: Lead
  - Priority: P0
  - ETA: 0.1d
  - Status: todo
- [ ] `mypy scripts/`
  - Owner: Lead
  - Priority: P0
  - ETA: 0.1d
  - Status: todo
- [ ] `pyright`
  - Owner: Lead
  - Priority: P0
  - ETA: 0.1d
  - Status: todo
- [ ] `pytest`
  - Owner: Lead
  - Priority: P0
  - ETA: 0.25d
  - Status: todo
- [ ] Run Amp completion workflow after all checks are green
  - Owner: Lead
  - Priority: P0
  - ETA: 0.1d
  - Status: todo

## Delegation Map
- Agent A: `scripts/am_patch` stabilization and lock (`M1`, `M2`)
- Agent B: `badguys/` strict typing (`M3`)
- Agent C: `scripts/patchhub` API + ASGI lanes (`M4`, `M6` subset)
- Agent D: `scripts/patchhub` data/editor/web-jobs lanes (`M4`, `M5`, `M6` subset)
- Lead: integration, conflict resolution, final full validations (`M0`, `M7`)

## Integration Cadence
- Every 3-5 micro-batches per lane:
  - integrate/rebase
  - run lane-level sanity checks
- At each milestone end:
  - run milestone exit checks
  - update this file status fields

## First 10 Micro-Batches (Suggested Start Queue)
- [ ] MB-01: `scripts/am_patch/initial_self_backup.py` - compatibility defaults for policy attrs
  - Owner: Agent A | Priority: P0 | ETA: 0.25d | Status: todo
- [ ] MB-02: `scripts/am_patch/startup_context.py` - safe CLI attribute fallback reads
  - Owner: Agent A | Priority: P0 | ETA: 0.25d | Status: todo
- [ ] MB-03: `scripts/am_patch/patch_input.py` - patch-script fallback compatibility
  - Owner: Agent A | Priority: P0 | ETA: 0.25d | Status: todo
- [ ] MB-04: `scripts/am_patch/post_run_pipeline.py` - expected side-effect ordering restore
  - Owner: Agent A | Priority: P0 | ETA: 0.5d | Status: todo
- [ ] MB-05: `scripts/am_patch/engine.py` - finalize/report compatibility field defaults
  - Owner: Agent A | Priority: P0 | ETA: 0.25d | Status: todo
- [ ] MB-06: `badguys/bdg_evaluator.py` - remove `Any`, add typed coercion helpers
  - Owner: Agent B | Priority: P1 | ETA: 0.25d | Status: todo
- [ ] MB-07: `badguys/bdg_loader.py` - remove `Any`, normalize typed maps
  - Owner: Agent B | Priority: P1 | ETA: 0.25d | Status: todo
- [ ] MB-08: `scripts/patchhub/app_api_amp.py` - replace `Any` interfaces with protocols
  - Owner: Agent C | Priority: P1 | ETA: 0.25d | Status: todo
- [ ] MB-09: `scripts/patchhub/asgi/json_contract.py` - remove `Any` response typing
  - Owner: Agent C | Priority: P1 | ETA: 0.25d | Status: todo
- [ ] MB-10: `scripts/patchhub/models.py` - start unknown-type reduction on core coercers
  - Owner: Agent D | Priority: P1 | ETA: 0.5d | Status: todo

## Definition of Done
- `ruff` reports zero errors.
- `mypy` reports zero errors.
- `pyright` reports zero errors.
- `pytest` reports zero failures.
- Governance constraints remain satisfied throughout execution.

## Daily Update Template

Use this template for each contributor/agent update.

```
Date: YYYY-MM-DD
Owner: <name or agent id>

1) Progress Today
- Completed:
  - <task id / file / short outcome>
- In progress:
  - <task id / current status>

2) Validation Run
- Commands run:
  - <exact command>
  - <exact command>
- Result summary:
  - ruff: <pass/fail + count>
  - mypy: <pass/fail + count>
  - pyright: <pass/fail + count>
  - pytest: <pass/fail + count>

3) Issues / Blockers
- <none OR blocker description>
- Needed input:
  - <decision/dependency required>

4) Next Micro-Batches
- MB-xx: <planned file(s) + intent>
- MB-yy: <planned file(s) + intent>

5) Risk Notes
- Behavior risk: <low/medium/high + short reason>
- Scope risk: <low/medium/high + short reason>
```

### Lead Daily Rollup Template

```
Date: YYYY-MM-DD
Lead: <name>

Lane Status
- Agent A: <green/yellow/red> - <one line>
- Agent B: <green/yellow/red> - <one line>
- Agent C: <green/yellow/red> - <one line>
- Agent D: <green/yellow/red> - <one line>

Milestone Tracking
- M0: <todo/in_progress/blocked/done>
- M1: <todo/in_progress/blocked/done>
- M2: <todo/in_progress/blocked/done>
- M3: <todo/in_progress/blocked/done>
- M4: <todo/in_progress/blocked/done>
- M5: <todo/in_progress/blocked/done>
- M6: <todo/in_progress/blocked/done>
- M7: <todo/in_progress/blocked/done>

Delta Since Yesterday
- Error counts:
  - ruff: <old -> new>
  - mypy: <old -> new>
  - pyright: <old -> new>
  - pytest fails: <old -> new>
- Notable merges/conflicts:
  - <one line each>

Plan For Next Day
- Top 3 priorities:
  1. <item>
  2. <item>
  3. <item>
```
