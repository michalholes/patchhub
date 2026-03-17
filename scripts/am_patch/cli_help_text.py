from __future__ import annotations


def fmt_short_help(runner_version: str) -> str:
    return f"""am_patch.py (RUNNER_VERSION={runner_version})

Options:
  -h, --help
      Show short help with commonly used options.

  -H, --help-all
      Show full reference help with all available options and exit.

  -c, --show-config
      Print effective configuration and policy sources (defaults, config file,
      CLI overrides) and exit.

  --config PATH
      Use PATH as config file (CLI only; not a config key).
      Relative paths are resolved against runner_root.
      Default depends on detected runner layout.
      Embedded default: scripts/am_patch/am_patch.toml
      Root-layout default: am_patch.toml in runner_root

  --target-repo-name NAME
      Set target_repo_name selector input for the /home/pi/<name> target family.
      [default: audiomason2]

  --active-target-repo-root PATH
      Set explicit target repository root path selector.

  --target-repo-roots CSV
      Replace the allowed target repository roots registry.

  -q, -v, -n, -d, --verbosity {{debug, verbose, normal, warning, quiet}}
      Control screen output amount. [default: verbose]

  -a, --allow-undeclared-paths
      Allow patch scripts to touch files outside declared FILES (override default FAIL).

  -t, --allow-untouched-files
      Allow declared but untouched FILES (override default FAIL).

  -l, --rerun-latest
      Rerun the latest archived patch for ISSUE_ID (auto-select from
      patches/successful and patches/unsuccessful).

  -r, --run-all-gates
      Run all gates (ruff, pytest, mypy) even if one fails.

  -g, --allow-gates-fail
      Allow gate failures and still promote; intended for bug bounty.

  --gate-badguys-runner {{auto, on, off}}
      Runner-only extra gate: run badguys/badguys.py -q.
      auto=only when runner files changed. [default: auto]

  -f, --finalize-live MESSAGE
      Finalize live repo using MESSAGE as commit message.

  -w, --finalize-workspace ISSUE_ID
      Finalize existing workspace for ISSUE_ID; commit message is read from workspace meta.json.

  -o, --allow-no-op
      Allow no-op patches (override default FAIL).

  -u, --unified-patch
      Force unified patch mode (.patch or .zip bundle). Without -u, auto-detect:
      .patch/.zip => unified; .py => patch script.

"""


def fmt_full_help(runner_version: str) -> str:
    return f"""am_patch.py (RUNNER_VERSION={runner_version})

Full reference of all available options.
All options are shown in long form.
Short aliases are shown in parentheses only for options that also appear in short help.

CORE / INFO
  --help (-h)
      Show short help with commonly used options.

  --help-all (-H)
      Show full reference help with all available options and exit.

  --show-config (-c)
      Print effective configuration and policy sources (defaults, config file,
      CLI overrides) and exit.

  --config PATH
      Use PATH as config file (CLI only; not a config key).
      Relative paths are resolved against runner_root.
      Default depends on detected runner layout.
      Embedded default: scripts/am_patch/am_patch.toml
      Root-layout default: am_patch.toml in runner_root

  --target-repo-name NAME
      Set target_repo_name selector input for the /home/pi/<name> target family.
      [default: audiomason2]

  --active-target-repo-root PATH
      Set explicit target repository root path selector.

  --target-repo-roots CSV
      Replace the allowed target repository roots registry.

  --version
      Print runner version and exit.

  -q, -v, -n, -d, --verbosity {{debug, verbose, normal, warning, quiet}}
      Control screen output amount.
      [default: verbose]

  --log-level {{debug, verbose, normal, warning, quiet}}
      Control what is written to the file log (independent from screen output).
      [default: verbose]

WORKFLOW / MODES
  --finalize-live MESSAGE (-f)
      Finalize live repository using MESSAGE as commit message.
      Enables finalize mode and performs promotion, commit, and push.

  -w, --finalize-workspace ISSUE_ID
      Finalize an existing workspace for ISSUE_ID, including promotion, gates, commit, and push.
      Commit message is read from workspace meta.json.

  --rerun-latest (-l)
      Rerun the latest archived patch for the given ISSUE_ID.
      Patch is auto-selected from successful or unsuccessful archives.

  --update-workspace
      Update the existing workspace to match the current live repository state.

  --test-mode
      Badguys test mode: run patch + gates in workspace, then stop.
      Skips promotion/live gates/commit/push and does not create any archives.
      Workspace is deleted on exit (success or failure).

GATES / EXECUTION
  --skip-ruff
      Skip ruff gate.
      [default: OFF]

  --skip-pytest
      Skip pytest gate.
      [default: OFF]

  --skip-mypy
      Skip mypy gate.
      [default: OFF]

  --skip-js
      Skip JS gate.
      [default: OFF]

  --skip-biome
      Skip biome gate (Variant B, file-scoped).
      [default: ON]

  --skip-typescript
      Skip typescript gate (Variant B, file-scoped).
      [default: ON]

  --gate-biome-extensions EXT[,EXT...]
      Override biome file extensions (comma-separated).

  --gate-biome-command TOK[,TOK...]
      Override biome command tokens (comma-separated).

  --gate-typescript-extensions EXT[,EXT...]
      Override typescript file extensions (comma-separated).

  --gate-typescript-command TOK[,TOK...]
      Override typescript command tokens (comma-separated).

  --skip-docs
      Skip docs gate.
      [default: OFF]

  --skip-monolith
      Skip monolith gate.
      [default: OFF]

  --run-all-gates (-r)
      Continue running all gates even after failures.

  --allow-gates-fail (-g)
      Allow gate failures and still promote.

  --gate-compile
      Enable compile gate (python -m compileall).

PATCH INPUT / APPLY
  --allow-no-op (-o)
      Allow no-op patches.

  --unified-patch (-u)
      Force unified patch mode.

  --patch-strip N
      Patch strip level passed to git apply -pN.

  --skip-up-to-date
      Skip patch apply if the workspace already contains the exact patch hash.

  --allow-non-main
      Allow patching on non-main branches.

WORKSPACE
  --update-workspace
      Update the existing workspace to match live repo.

  --soft-reset-workspace
      Reset workspace to live repo without deleting history.

  --keep-workspace
      Keep workspace even on success.

  --rollback-workspace-on-fail {{none-applied, never, always}}
      Whether to rollback workspace to pre-apply state on patch failure.

  --no-rollback-workspace-on-fail
      Shortcut for --rollback-workspace-on-fail never.

  --no-rollback-on-commit-push-failure
      Disable rollback on commit/push failure.

SECURITY / GUARDS
  --live-repo-guard
      Protect live repo from patch mistakes.

  --live-repo-guard-scope {{none, scripts, all}}
      Guard scope for live repo.

  --patch-jail
      Run gates in a jailed environment.

  --patch-jail-unshare-net
      Unshare network namespace for jailed gates.

FORMAT / TOOLS
  --ruff-format
      Run ruff format gate.

  --ruff-mode auto|always
      Control ruff gate trigger mode (auto=file-scoped; always=force run).

  --mypy-mode auto|always
      Control mypy gate trigger mode (auto=file-scoped; always=force run).

  --pytest-mode auto|always
      Control pytest gate trigger mode (auto=file-scoped; always=force run).

  --pytest-routing-mode legacy|bucketed
      Control pytest target selection after the gate has been triggered.

  --pytest-js-prefixes CSV
      JS triggers for pytest (CSV prefixes; e.g. scripts/patchhub/static,
      plugins/import/ui/web/assets).

  --pytest-use-venv
      Run pytest using venv python.

BADGUYS
  --gate-badguys-runner {{auto, on, off}}
      Control badguys runner gate.

  --gate-badguys-command CMD
      Override badguys command.

  --gate-badguys-cwd PATH
      Override badguys cwd.

OVERRIDES
  --override KEY=VALUE (repeatable)
      Apply a single CLI override.

  --allow-undeclared-paths (-a)
      Allow patch scripts to touch files outside declared FILES.

  --allow-untouched-files (-t)
      Allow declared but untouched FILES.

ADVANCED / INTERNAL
  --require-push-success
  --allow-outside-files
  --allow-declared-untouched
  --disable-promotion
  --allow-live-changed
  --gates-on-partial-apply
  --gates-on-zero-apply
  --docs-include REGEX
  --docs-exclude REGEX
  --gates-order CSV
  --ruff-autofix-legalize-outside
  --post-success-audit
  --load-latest-patch

WORKSPACE PATHS
  --workspace-base-dir PATH
  --workspace-issue-dir-template TEMPLATE
  --workspace-repo-dir-name NAME
  --workspace-meta-filename NAME
  --workspace-history-logs-dir NAME
  --workspace-history-oldlogs-dir NAME
  --workspace-history-patches-dir NAME
  --workspace-history-oldpatches-dir NAME
  --blessed-gate-output PATH (repeatable)
  --scope-ignore-prefix STR (repeatable)
  --scope-ignore-suffix STR (repeatable)
  --scope-ignore-contains STR (repeatable)
  --venv-bootstrap-mode {{auto, always, never}}
  --venv-bootstrap-python PATH

"""
