# AM Patch Runner v5 - User Manual

This manual describes how *you* use the new runner day-to-day so that runs are deterministic and issues can be safely closed.

## Concepts (minimal)

### Root model

- The runner may live in one git repository while patching a different git repository.
- The runner repository is the runner_root.
- The runner-owned config file lives under runner_root:
  - Legacy embedded layout: `scripts/am_patch/am_patch.toml`
  - Root layout: `am_patch.toml`
- Runner-owned artifacts live under artifacts_root.
- The repository being patched for the current run is active_target_repo_root.
- The configuration may list multiple candidate target repositories via target_repo_roots.
- A single run always uses exactly one active target repository.
- Multi-target execution in one run is not supported.

### Gates and COMPILE
- After the patch is applied, the runner executes gates.
- Optional diagnostics: if patch apply fails, you can still run workspace gates for diagnostics:
  - --apply-failure-partial-gates-policy {never,always,repair_only}
  - --apply-failure-zero-gates-policy {never,always,repair_only}
  - Config keys: apply_failure_partial_gates_policy / apply_failure_zero_gates_policy
  - repair_only: run gates only when workspace_attempt >= 2 (ws.attempt).
  - The run remains FAIL with PATCH_APPLY as the primary reason.
- Gate: COMPILE runs `python -m compileall -q` in the workspace repo root to catch syntax errors early.
- Default: enabled.
- Config keys:
  - `compile_check = true|false`
  - `compile_targets = ["...", ...]` (default: `["."]`)
  - `compile_exclude = ["...", ...]` (default: `[]`)
- CLI:
  - `--no-compile-check` disables it for the run.
  - `--override compile_targets=...` and `--override compile_exclude=...` use the same list format as `ruff_targets`.

## Help

- `am_patch.py --help` shows a short, workflow-focused help.
- `am_patch.py --help-all` shows a full reference (grouped by workflow).
- `am_patch.py --test-mode` runs patch + gates in the workspace, verifies the live-repo guard (after gates), then stops (no promotion, no live gates, no commit/push, no archives) and always deletes the workspace on exit.
- In --test-mode, if patch_dir is not explicitly set, the runner isolates its work paths under patches/_test_mode/issue_<ID>_pid_<PID>/ and deletes it on exit.
- `am_patch.py --show-config` prints the effective policy/config and exits.

Pytest routing:
- `--pytest-mode {auto,always}` controls when the pytest gate runs.
- `gate_pytest_py_prefixes` defines the Python trigger surface for `gate_pytest_mode=auto`.
  - The shipped default is `tests`, `src`, `plugins`, and `scripts`.
  - Configure it via the runner-owned config file (`scripts/am_patch/am_patch.toml` in legacy embedded layout, `am_patch.toml` in root layout) or `--override gate_pytest_py_prefixes=...`.
- `--pytest-routing-mode {legacy,bucketed}` controls how the pytest gate selects targets after it has been triggered.
- `legacy` passes `pytest_targets` directly.
- `bucketed` uses namespace routing plus discovery:
  - `pytest_roots` defines root namespaces. The minimal shipped roots are `amp.*`, `am2.*`, and `*`.
  - `pytest_tree` maps namespace nodes and subtrees to repo path prefixes.
  - `pytest_namespace_modules` maps each namespace to zero or more module prefixes used by discovery and validator evidence.
  - `pytest_dependencies` defines repo-documented one-way namespace dependencies.
  - `pytest_external_dependencies` defines explicit one-way routing overrides that are not presented as repo-documented dependency evidence.
  - discovery maps tests to namespaces using both tree/path signals and namespace module-prefix signals.
  - direct changed tests are always included.
  - `pytest_full_suite_prefixes` defines the explicit global full-suite escalation surface.
- Dependency semantics are one-way:
  - if `A` depends on `B`, a patch that touches `B` must also run tests owned by `A`.
  - a patch that touches `A` must not pull tests owned by `B` solely because of that dependency.
- Evidence semantics are split:
  - `pytest_dependencies` is reserved for repo-documented or repo-verifiable dependency edges.
  - `pytest_external_dependencies` is reserved for explicit routing-policy overrides that are not claimed as repo-documented evidence.
  - routing may use the union of both layers, but validator output and tests must keep the two layers separate.
- Fallback semantics in bucketed mode:
  - if a touched node has no explicit dependency rule, route it to its subtree suite.
  - if the touched subtree has no explicit dependency rule, route it to its root suite.
  - if a changed path matches no explicit root, route it to the catch-all `*` namespace suite.
  - full suite is reserved for `pytest_full_suite_prefixes` only; `*` is not automatic full suite.
- `pytest_targets` remains the list of targets passed to pytest after the gate has been triggered.
  It does not define the Python trigger surface.
- `--pytest-js-prefixes CSV` keeps its existing role as the JS-only trigger surface for `gate_pytest_mode=auto`.

Notes:
- Only options listed in short help have short aliases. All other options are long-only.


## Verbosity and status output



The runner supports 5 verbosity modes for console output (and the same level names for the file log filter).

Levels are inherited: each higher mode includes everything from the lower mode.

- quiet:
  - START
  - RESULT
  - On FAIL: full stdout + stderr of the failed step(s)

- normal:
  - quiet + legacy concise flow format:
    - RUN
    - LOG
    - DO
    - STATUS (elapsed format)
    - OK / FAIL
    - RESULT
    - FILES
    - COMMIT
    - PUSH
  - On FAIL: full stdout + stderr of the failed step(s)

- warning:
  - normal + warnings (if any)
  - On FAIL: full stdout + stderr

- verbose:
  - warning + diagnostic sections (config, workspace meta, gate summaries, patch summary, etc.)
  - live subprocess stdout/stderr for the screen sink
  - On FAIL: full stdout + stderr, with the final failed-step dump used only as a fallback for sinks that did not already receive live subprocess payload during the step

- debug:
  - verbose + full internal command metadata (RUN cmd=..., cwd=..., returncode=...)
  - verbose + full diagnostic dumps
  - On FAIL: full stdout + stderr, with the final failed-step dump used only as a fallback for sinks that did not already receive live subprocess payload during the step

The runner supports an independent file log filter:

- `--log-level {quiet,normal,warning,verbose,debug}`

Both `--verbosity` and `--log-level` use the same level names and meanings, but may be set to different values.

Autofix-aware failed-step rule:

- When Ruff or Biome autofix is enabled, the pre-autofix check is diagnostic only.
- The pre-autofix check must not emit `FAILED STEP OUTPUT`.
- It may emit filtered warning/detail diagnostics.
- The authoritative fail dump, if any, comes only from the post-autofix final check.

On FAIL, the runner emits a runner-owned error detail line in the form
`ERROR DETAIL: <stage>:<category>: <single-line-message>` when a `RunnerError`
produces no failed-step stdout/stderr dump. This line is error detail, not part
of the final summary.

Inheritance rule (contract):

- Verbosity modes are cumulative.
  Each higher mode MUST include all guaranteed outputs of the lower mode.

Final summary (at the end of each run):

- FILES block (only when PUSH: OK), strictly in the following format:


    FILES:

    A path1
    M path2
    D path3
  - `COMMIT: <sha>` (or `(none)` if commit/push dont runs)
  - `PUSH: OK|FAIL|UNKNOWN` (if commit/push is running)
  - `LOG: <path>`
- CANCELED:
  - `RESULT: CANCELED`
  - `STAGE: <stage-id>`
  - `REASON: cancel requested`
  - `LOG: <path>`
- FAIL:
  - `RESULT: FAIL`
  - `STAGE: <stage-id>`
  - `REASON: <one line>`
  - `LOG: <path>`

Additional `ERROR DETAIL:` records may appear before the final summary.
They are failure detail, not summary lines, and do not change the fixed
FAIL summary shape.

NDJSON terminal contract:
- `--json-out` writes NDJSON with one JSON object per line.
- The NDJSON `type="result"` event is the canonical machine terminal summary.
- Summary `type="log"` records and the human final summary remain deterministic renders of the same terminal summary.

Quiet sinks:
- If `--verbosity quiet`, the console prints only START + RESULT (plus error detail on FAIL).
- If `--log-level quiet`, the log file contains only START + RESULT (plus error detail on FAIL),
  except that the final `CANCELED` summary still logs `STAGE`, `REASON`, and `LOG`.

- **Workspace mode (default)**: runner creates/uses an issue workspace, runs patch + gates there, then promotes results to the live repo.
- **Finalize mode (-f)**: runner works directly on the live repo (no workspace). Use only when you intentionally want a direct/live operation.
- **Finalize-workspace mode (--finalize-workspace)**: runner finalizes an existing issue workspace (gates in workspace, promote to live, gates in live, commit+push). Commit message is read from workspace `meta.json`.

Note: All modes use a single canonical Policy->gates wiring entry point.
Direct calls to run_gates outside scripts/am_patch/gates_policy_wiring.py are forbidden
and enforced.

## What "SUCCESS" means

If the runner reports **SUCCESS** (without `-o`):
- at least one real change happened,
- no file outside `FILES` was touched,
- ruff/pytest/mypy all passed,
- promotion committed and the log reports push status (e.g. `push=OK`),
- closing the issue is justified.

If you used `-o` (allow no-op), SUCCESS does **not** imply a code change.

---

## Directory layout (expected)

- Repo root: `/home/pi/audiomason2`
- Patches root: `/home/pi/audiomason2/patches`
- Runner config (persistent):
  - Legacy embedded layout: `scripts/am_patch/am_patch.toml`
  - Root layout: `am_patch.toml` in the runner root
- Workspaces (persistent until success): under `patches/workspaces/issue_<ID>/`
  - Finalize-workspace cleanup: on SUCCESS, the workspace is deleted if `delete_workspace_on_success=true`; use `-k` to keep it.
- Logs: under `patches/logs/` plus `patches/am_patch.log` symlink to latest log

---


## patched.zip (log + changed/touched subset) contents hygiene (size control)

`patched.zip (log + changed/touched subset)` is intended for reproducibility and review, not for mirroring the entire git repository internals or tool caches.
The runner excludes the following from the archived changed/touched subset when building `patched.zip (log + changed/touched subset)`:

- `.git/`
- `venv/`, `.venv/`
- `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`
- `__pycache__/`
- `*.pyc`

This reduces archive size without changing patch semantics or gates behavior.

-
Note on failure subsets:
- On `-w` / `--finalize-workspace` failure, `patched.zip` includes the log plus the
  workspace changed/touched subset, including the files that were planned for promotion.
- On `-f` / `--finalize` failure after gates start, `patched.zip` includes the log plus the
  live-repo dirty subset captured before gates, after gates,
  and again when the failure zip is built.


## Standard workflow (workspace mode)

### 1) Create / receive a patch script
A patch script is a Python file stored under:
- `/home/pi/audiomason2/patches/`

It MUST declare a `FILES = [...]` list (repo-relative paths).

### 2) Run the patch (workspace mode)
Recommended invocation:

- Legacy embedded layout: `python3 scripts/am_patch.py ISSUE_ID "message" [PATCH_SCRIPT]`
- Root layout: `python3 am_patch.py ISSUE_ID "message" [PATCH_SCRIPT]`

Patch script location rules:
- `PATCH_SCRIPT` may be `patches/<name>.py` or just `<name>.py` (resolved under `patches/`).
- Absolute paths are accepted only if they are under `patches/`.
- Any path outside `patches/` is rejected in PREFLIGHT.

You may add:
- `-r` to run all gates even if one fails (more diagnostics)

### 3) Read the log
Open `patches/am_patch.log` (symlink to newest log).

The log contains:
- effective configuration,
- full stdout+stderr of patch and all gates,
- promotion actions,
- commit SHA on success,
- runner-owned failure detail and failure fingerprint on failure.

### 4) Close the issue
Only close an issue when:
- runner returned SUCCESS **without** `-o`, and
- the success log shows a commit SHA and push succeeded.

---

## Common flags

Short-help options (have short aliases):

- `-o` / `--allow-no-op` : allow no-op (otherwise no-op fails)
- `-a` / `--allow-undeclared-paths` : allow touching files outside FILES
- `-t` / `--allow-untouched-files` : allow declared-but-untouched FILES
- `-l` / `--rerun-latest` : rerun latest archived patch (auto-select from patches/successful and patches/unsuccessful)
- `-u` / `--unified-patch` : force unified patch mode.
  - Auto-detect without `-u`:
    - input `*.patch` => unified mode
    - input `*.py` => patch script mode
    - input `*.zip` => scan zip recursively; if any `*.patch` entries exist, unified mode is used and **all** `*.patch` entries are applied (deterministic lexicographic order by zip path). If the zip also contains `*.py`, those are ignored when at least one `*.patch` exists.
- `-r` / `--run-all-gates` : run all gates (not only those affected by files in scope)
- `-g` / `--allow-gates-fail` : allow gates to fail (continue)
- `-c` / `--show-config` : print the effective config/policy and exit
- `-f` / `--finalize-live MESSAGE` : finalize live repo (gates + promotion by commit/push)

Logging / output:

- `--log-level {quiet,normal,warning,verbose,debug}` : filter what is written to the log file (independent from `--verbosity`).
- `runner_subprocess_timeout_s` (config key) : hard timeout for runner subprocesses in seconds; `0` disables it.
- When `json_out` is enabled, the machine-facing NDJSON stream may also include
  periodic `HEARTBEAT` log events so listeners can detect liveness during long
  subprocess steps.
- When `json_out` is enabled, the same NDJSON stream also includes live
  subprocess stdout/stderr payload as line-framed events regardless of
  `--verbosity` or `--log-level`.
- Human-readable live subprocess payload is sink-local:
  - screen gets it only when `--verbosity` is `verbose` or `debug`
  - file log gets it only when `--log-level` is `verbose` or `debug`
- A sink that already received live subprocess payload must not receive the
  same stdout/stderr a second time in the final failed-step dump.
- The runner still buffers full stdout/stderr for `RunResult`, and the final
  failed-step dump remains the fallback for sinks that did not receive live
  payload.

IPC cancellation semantics:

- `cancel` accepted during an active runner-managed subprocess requests immediate
  termination of that subprocess tree.
- `cancel` accepted when no runner-managed subprocess is active stops at the next
  safe boundary (`OK:` or `FAIL:` step token).
- A run ended by an accepted cancel request reports `RESULT: CANCELED` and exits
  with code `130`.
- `ok=true` in the IPC reply means only that the cancel request was accepted.

Long-only options (no short alias):

- `-w` / `--finalize-workspace ISSUE_ID` : finalize an existing workspace (gates in workspace, promote changes to live, gates in live, then commit/push)
- `--require-push-success` : fail the run if push fails (overrides allow_push_fail)
- `--no-compile-check` : disable the COMPILE gate (`python -m compileall`) for this run.
- `--disable-promotion` : run gates, but do not commit or push (applies to patch mode and finalize modes)
- `--keep-workspace` : keep workspace on success (finalize-workspace and patch workspace mode)
- `--allow-live-changed` / `--overwrite-live` / `--overwrite-workspace` : control live-changed resolution during workspace promotion

Blessed gate outputs (no `-a` required):

- `audit/results/pytest_junit.xml` is treated as a gate-produced audit artifact.
- It does not trigger scope failures and is promoted/committed automatically when changed.

---

## When the runner FAILS (what to do)

### A) FAIL: origin/main is ahead
Meaning: remote main moved forward since your local main.

Fix:
1. Update your local main (pull/rebase) so it includes origin changes.
2. Re-run the runner.

If you intentionally want to proceed without updating:
- rerun with `-u` (not recommended except for controlled cases).

### B) FAIL: live FILES changed since workspace base

Meaning: the live repo changed in one of the promotable files after the workspace base was captured.

Fix options (choose explicitly):
1. Update the workspace base to current live base and retry:
   - rerun with `-W` / `--update-workspace`
2. Intentionally overwrite live with the workspace version:
   - rerun with `--overwrite-live`
   - or set `live_changed_resolution = "overwrite_live"`
3. Intentionally keep the live version and skip promoting the conflicting files:
   - rerun with `--overwrite-workspace`
   - or set `live_changed_resolution = "overwrite_workspace"`

Notes:
- `--allow-live-changed` is a legacy alias for `--overwrite-live`.

### C) FAIL: scope violation (touched file outside FILES)
Meaning: patch changed something outside its declared list.

Fix:
- correct the patch: add the missing file to `FILES` or stop touching it.
Then rerun.

### D) FAIL: no-op patch
Meaning: the patch produced no real change.

Fix:
- if the intent was to change code: patch is wrong; regenerate/fix it.
- if you intentionally want a dry/no-op run: rerun with `-o`.

---

## Finalize mode (-f)

Use finalize mode only when you intentionally want direct live repo operations.

Typical invocation:
- Legacy embedded layout: `python3 scripts/am_patch.py -r -f "message"`
- Root layout: `python3 am_patch.py -r -f "message"`

Note:
- In finalize mode, positional args (ISSUE_ID / PATCH_SCRIPT) are not accepted.

Finalize mode may be used without an issue id.
It should still obey logging and gate policies, but it does not use a workspace.

---

## Operational hygiene

- Avoid running two instances at once (runner has a lock).
- Treat SUCCESS as the only safe signal to close issues.
- Keep the runner-owned config file under version control if you want consistent behavior across machines.
  - Legacy embedded layout: `scripts/am_patch/am_patch.toml`
  - Root layout: `am_patch.toml` in the runner root


## Patch execution safety (v4.1.38+)

- Patch scripts are copied into the workspace and executed only from there.
- Patch execution is isolated via a filesystem jail (bubblewrap) by default.
- Only the workspace is writable; live repo access is denied.

### Rollback behavior

- On patch failure, the workspace is rolled back to the exact state before patch execution.
- Gate failures do not trigger rollback and leave the failed workspace state intact for repair.
- This rollback is transactional and includes tracked and untracked files.

### Ruff formatting

- `ruff format` runs before `ruff check` by default.
- Formatting is logged and included in rollback semantics.

## Post-success Audit (automatic)

When a run completes successfully **and the commit+push succeeds**, the runner automatically
executes an **AUDIT** step:

```
python3 -u audit/audit_report.py
```

What this means:
- You immediately see how the audit status changed due to the patch you just pushed.
- The audit runs on the **live repository**, not the workspace.
- In `workspace` mode and `--finalize-workspace`, the audit runs **after** workspace deletion (when enabled).
- In `--finalize-live`, there is no workspace; the audit runs after `SUCCESS`.

If the audit step fails:
- The runner reports FAILURE with stage `AUDIT`.
- The commit remains (no rollback), but the failure is visible in the log and must be addressed.

---

## Success archive (SUCCESS: clean repo snapshot)

On SUCCESS (in `workspace`, `finalize`, and `finalize_workspace` modes; excluding `--test-mode`), the runner
creates a git-archive success zip as a clean `git archive HEAD` snapshot of the final live repository state.

Naming:
- The filename is controlled by `success_archive_name` / `--success-archive-name`
  (default `{repo}-{branch}.zip`, e.g. `audiomason2-main.zip`).
- Placeholders:
  - {repo}: repository directory name
  - {branch}: current branch name (or "detached")
  - {issue}: CLI issue id, or "noissue" when ISSUE_ID is not provided
  - {ts}: HEAD committer time in UTC (YYYYMMDD_%H%M%S), not runtime time
- Example: `{repo}-{branch}-issue{issue}-{ts}.zip`

Destination directory:
- Controlled by `success_archive_dir` / `--success-archive-dir`:
  - patch_dir: `patches/` (default)
  - successful_dir: `patches/successful/`

Deterministic retention (optional):
- Enable by setting BOTH:
  - `success_archive_cleanup_glob_template` / `--success-archive-cleanup-glob`
  - `success_archive_keep_count` / `--success-archive-keep-count` (> 0)
- After writing the new archive, the runner deletes old archives selected by the glob template,
  sorted lexicographically by filename. It never deletes the newly created archive.

It contains only git-tracked files and does not include logs, workspaces, caches, or patch inputs.

---

## Issue diff bundle (SUCCESS: per-file unified diffs + logs)

On SUCCESS (in `workspace`, `finalize`, and `finalize_workspace` modes; excluding `--test-mode`), the runner also creates an issue diff bundle zip under `patches/artifacts/`.

Naming:
- `issue_<ISSUE>_diff.zip`
- If a file already exists, the runner creates `issue_<ISSUE>_diff_v2.zip`, `issue_<ISSUE>_diff_v3.zip`, etc.
- In `finalize` mode (no issue id), the runner uses a pseudo issue id derived from the finalize log filename: `FINALIZE_<ts>`.

Contents:
- `manifest.txt` (issue id, base sha, files list, diff entries list, logs list)
- `diff/` (per-file unified diffs: `diff/<repo-path>.patch`)
- `files/` (full file snapshots: `files/<repo-path>`)
- `logs/` (all logs for the issue id; for `finalize`, only the current finalize log)

Diff scope rules:
- In workspace modes, the diff set is limited to `files_to_promote` (the promotion plan), and it includes any gate modifications of those files (for example ruff autofix/format).
- In `finalize`, the diff set is limited to the union of decision paths before gates and changed paths after gates (so ruff changes are included without pulling in unrelated tracked files).


- --gate-badguys-runner {auto,on,off}: runner-only badguys gate (default auto)

## Console color output

The runner can colorize only the OK/FAIL/SUCCESS tokens on stdout.

Configuration:
- Config file key: console_color = "auto"|"always"|"never"
- CLI: --color {auto,always,never} or --no-color
- Env: NO_COLOR disables color regardless of config/CLI
