# AM Patch standalone specification

## Scope

This repository contains the standalone AM Patch runner only.
PatchHub, AudioMason2 core, plugins, and BadGuys are not part of this repo.

## File-system contract

- runner_root = `amp/`
- package_root = `amp/am_patch/`
- default_config_path = `amp/am_patch.toml`
- default_target_repo_root = parent repo root (`..`)
- default_artifacts_root = parent repo root (`..`)

## Behavioral contract

1. The runner must support a root layout where the entrypoint is not inside
   `scripts/`.
2. The runner must resolve `runner_root` independently from the active target repo.
3. The shipped config must point namespace routing, Python targets, and monolith
   areas at the standalone `amp/` layout.
4. Standalone defaults must not reference AudioMason2-only trees such as
   `src/audiomason/`, `plugins/`, or `scripts/patchhub/`.
5. The default config may disable `require_up_to_date` for bootstrap on a fresh repo.

## Validation anchors

- `amp/am_patch.py`
- `amp/am_patch/root_model.py`
- `amp/am_patch/startup_context.py`
- `amp/am_patch/runtime.py`
- `amp/am_patch/monolith_gate.py`
- `amp/am_patch/pytest_namespace_config.py`
- `amp/am_patch.toml`

