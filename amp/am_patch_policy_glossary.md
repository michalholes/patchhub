# AM Patch policy glossary (standalone repo)

## target_repo_roots

Allowed patch targets. In this repo the shipped config registers the parent repo:

```toml
target_repo_roots = [".."]
```

## active_target_repo_root

The currently selected patch target. The shipped config points to the parent repo:

```toml
active_target_repo_root = ".."
```

## artifacts_root

Where patches, workspaces, logs, and archives are stored. The shipped config uses
`..` so artifacts live at the parent repo root.

## gate_pytest_py_prefixes

Python-trigger prefixes for the standalone repo. The shipped config uses:

```toml
gate_pytest_py_prefixes = ["amp", "tests"]
```

## gate_badguys_runner

Disabled by default in the standalone repo because BadGuys is not transferred here.

