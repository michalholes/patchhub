# AM Patch Runner (standalone repo layout)

This repository hosts the AM Patch runner under `amp/`.

## Layout

- Entrypoint: `amp/am_patch.py`
- Package: `amp/am_patch/`
- Default config: `amp/am_patch.toml`
- Default target repo root: `..`
- Default artifacts root: `..`

## Invocation

From the repository root:

```bash
python3 amp/am_patch.py ISSUE_ID "commit message" issue_123_v1.zip
```

From `amp/`:

```bash
python3 am_patch.py ISSUE_ID "commit message" patches/issue_123_v1.zip
```

## Root model

The runner lives in `amp/`, but patches the parent Git repository by default.
That behavior is driven by `target_repo_roots = [".."]` and
`active_target_repo_root = ".."` in `amp/am_patch.toml`.

## Standalone defaults

The shipped policy defaults are retargeted for this repository layout:

- Python targets default to `amp/` and `tests/`
- Namespace routing defaults to `amp/am_patch/`
- BadGuys is disabled by default in this standalone repo
- The up-to-date Git guard is disabled in the shipped config for bootstrap use

