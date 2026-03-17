## Key: gates_allow_fail
Key: gates_allow_fail
Type: bool
Default: false
Meaning: If true, gate failures are reported but do not fail the runner result.
Notes:
- This changes the final exit status semantics.
Related: gates_order, gates_skip_ruff, gates_skip_pytest, gates_skip_mypy

## Key: gates_order
Key: gates_order
Type: list[str]
Default: ["compile", "js", "ruff", "pytest", "mypy", "monolith", "docs"]
Meaning: Ordered list of gate names to run when gating is enabled.
Notes:
- Unknown gate names are rejected by the runner.
Related: gates_allow_fail, run_all_tests

## Key: gates_skip_mypy
Key: gates_skip_mypy
Type: bool
Default: false
Meaning: If true, skip the mypy gate.
Related: mypy_targets, run_all_tests

## Key: gates_skip_pytest
Key: gates_skip_pytest
Type: bool
Default: false
Meaning: If true, skip the pytest gate.
Related: pytest_targets, pytest_use_venv, run_all_tests

## Key: gates_skip_ruff
Key: gates_skip_ruff
Type: bool
Default: false
Meaning: If true, skip the ruff gate.
Related: ruff_autofix, ruff_format, run_all_tests

## Key: gate_ruff_mode
Key: gate_ruff_mode
Type: str
Default: "auto"
Allowed: "auto" | "always"
Meaning: Controls when the ruff gate runs.
Notes:
- In mode "auto", the gate runs only when a file-scoped trigger matches.
- Trigger semantics are defined in scripts/am_patch_specification.md (Python gates - auto mode).
Related: gates_skip_ruff, ruff_autofix, ruff_format, ruff_targets

## Key: gate_mypy_mode
Key: gate_mypy_mode
Type: str
Default: "auto"
Allowed: "auto" | "always"
Meaning: Controls when the mypy gate runs.
Notes:
- In mode "auto", the gate runs only when a file-scoped trigger matches.
- Trigger semantics are defined in scripts/am_patch_specification.md (Python gates - auto mode).
Related: gates_skip_mypy, mypy_targets

## Key: gate_pytest_mode
Key: gate_pytest_mode
Type: str
Default: "auto"
Allowed: "auto" | "always"
Meaning: Controls when the pytest gate runs.
Notes:
- In mode "auto", the gate runs only when a file-scoped trigger matches.
- Trigger semantics are defined in scripts/am_patch_specification.md (Python gates - auto mode).
Related: gates_skip_pytest, gate_pytest_py_prefixes, pytest_targets, gate_pytest_js_prefixes

## Key: gate_pytest_py_prefixes
Key: gate_pytest_py_prefixes
Type: list[str]
Default: ["tests", "src", "plugins", "scripts"]
Meaning: In gate_pytest_mode="auto", a Python change under a listed prefix triggers pytest.
Notes:
- Prefix match is a directory-prefix match: "prefix" or "prefix/...".
- This key controls trigger timing only. It does not control the targets passed to pytest.
- Trigger semantics are defined in scripts/am_patch_specification.md (Python gates - auto mode).
Related: gate_pytest_mode, gate_pytest_js_prefixes, pytest_targets

## Key: gate_pytest_js_prefixes
Key: gate_pytest_js_prefixes
Type: list[str]
Default: []
Meaning: In gate_pytest_mode="auto", a JS change under a listed prefix triggers pytest.
Notes:
- Prefix match is a directory-prefix match: "prefix" or "prefix/...".
- Trigger semantics are defined in scripts/am_patch_specification.md (Python gates - auto mode).
Related: gate_pytest_mode, gate_pytest_py_prefixes, pytest_targets

## Key: mypy_targets
Key: mypy_targets
Type: list[str]
Default: ["src"]
Meaning: Paths passed to the mypy gate.
Notes:
- This is interpreted in the workspace repository root.
Related: gates_skip_mypy

## Key: pytest_targets
Key: pytest_targets
Type: list[str]
Default: ["tests"]
Meaning: Paths passed to the pytest gate.
Notes:
- This is interpreted in the workspace repository root.
- This key does not define the Python trigger surface for gate_pytest_mode="auto".
Related: gates_skip_pytest, gate_pytest_py_prefixes

## Key: pytest_routing_mode
Key: pytest_routing_mode
Type: str
Default: "bucketed"
Allowed: "legacy" | "bucketed"
Meaning: Controls how the pytest gate selects its effective targets after the gate has been triggered.
Notes:
- legacy passes pytest_targets directly to the pytest gate.
- bucketed uses pytest_smoke_targets, pytest_area_prefixes, pytest_area_names, pytest_area_targets,
  pytest_family_areas, pytest_family_targets, pytest_broad_repo_prefixes, and pytest_broad_repo_targets.
- This does not replace gate_pytest_mode. Trigger timing is still controlled by gate_pytest_mode.
Related: pytest_targets, gate_pytest_mode

## Key: pytest_smoke_targets
Key: pytest_smoke_targets
Type: list[str]
Default: repo default mapping
Meaning: Targets that always run in pytest_routing_mode="bucketed" whenever the pytest gate is triggered.
Notes:
- Order is preserved.
Related: pytest_routing_mode, pytest_area_targets, pytest_family_targets, pytest_broad_repo_targets

## Key: pytest_area_prefixes
Key: pytest_area_prefixes
Type: list[str]
Default: repo default mapping
Meaning: Ordered prefix list used to map decision paths to logical pytest areas.
Notes:
- Matching is first-match-wins.
- A prefix matches the whole path exactly or as prefix/.
- Must align positionally with pytest_area_names.
Related: pytest_area_names, pytest_area_targets

## Key: pytest_area_names
Key: pytest_area_names
Type: list[str]
Default: repo default mapping
Meaning: Ordered area names matched positionally with pytest_area_prefixes.
Notes:
- Length must equal pytest_area_prefixes.
- Names are later referenced by pytest_area_targets and pytest_family_areas.
Related: pytest_area_prefixes, pytest_area_targets, pytest_family_areas

## Key: pytest_area_targets
Key: pytest_area_targets
Type: dict[str, list[str]]
Default: repo default mapping
Meaning: Maps an area name to pytest targets added when that area is impacted in bucketed mode.
Notes:
- Area names are resolved from pytest_area_prefixes and pytest_area_names.
- Duplicate targets are removed deterministically, preserving first occurrence.
Related: pytest_routing_mode, pytest_area_names, pytest_family_targets

## Key: pytest_family_areas
Key: pytest_family_areas
Type: dict[str, list[str]]
Default: repo default mapping
Meaning: Maps a family name to the list of area names that activate that family in bucketed mode.
Notes:
- A family is selected when any impacted area belongs to that family.
Related: pytest_area_names, pytest_family_targets

## Key: pytest_family_targets
Key: pytest_family_targets
Type: dict[str, list[str]]
Default: repo default mapping
Meaning: Maps a family name to pytest targets added when that family is selected in bucketed mode.
Notes:
- Duplicate targets are removed deterministically, preserving first occurrence.
Related: pytest_family_areas, pytest_broad_repo_targets

## Key: pytest_broad_repo_prefixes
Key: pytest_broad_repo_prefixes
Type: list[str]
Default: repo default mapping
Meaning: Prefixes that escalate bucketed mode to an additional broad-repo pytest target set.
Notes:
- Matching uses the same exact-or-prefix/ rule as pytest_area_prefixes.
Related: pytest_broad_repo_targets, pytest_routing_mode

## Key: pytest_broad_repo_targets
Key: pytest_broad_repo_targets
Type: list[str]
Default: repo default mapping
Meaning: Extra pytest targets added in bucketed mode when any decision path matches pytest_broad_repo_prefixes.
Notes:
- Duplicate targets are removed deterministically, preserving first occurrence.
Related: pytest_broad_repo_prefixes, pytest_smoke_targets

## Key: pytest_use_venv
Key: pytest_use_venv
Type: bool
Default: true
Meaning: If true, run pytest under the configured venv python.
Related: venv_bootstrap_mode, venv_bootstrap_python

## Key: runner_subprocess_timeout_s
Key: runner_subprocess_timeout_s
Type: int
Default: 1800
Meaning: Hard timeout in seconds for runner-managed subprocesses.
Notes:
- Value 0 disables the timeout.
- Timeout is a hard failure for the owning stage, except for explicit best-effort cleanup paths.
- Repository root discovery keeps its fail-open fallback to Path.cwd().
Related: repo_root, gates_order, post_success_audit

## Key: run_all_tests
Key: run_all_tests
Type: bool
Default: true
Meaning: If true, run the configured gate sequence after applying the patch.
Notes:
- If false, the runner may skip gates entirely depending on other policy keys.
Related: gates_order, gates_allow_fail

## Key: allow_non_main
Key: allow_non_main
Type: bool
Default: false
Meaning: If true, allow running from a non-default branch.
Notes:
- This relaxes a safety invariant around branch discipline.
Related: default_branch, enforce_main_branch

## Key: enforce_main_branch
Key: enforce_main_branch
Type: bool
Default: true
Meaning: If true, require the repository to be on default_branch before running.
Related: default_branch, allow_non_main

## Key: require_up_to_date
Key: require_up_to_date
Type: bool
Default: true
Meaning: If true, require the local branch to be up-to-date with its upstream.
Related: skip_up_to_date

## Key: skip_up_to_date
Key: skip_up_to_date
Type: bool
Default: false
Meaning: If true, skip the up-to-date check even if require_up_to_date is true.
Notes:
- This exists for controlled environments and is a safety bypass.
Related: require_up_to_date

## Key: audit_rubric_guard
Key: audit_rubric_guard
Type: bool
Default: true
Meaning: If true, require the audit rubric file(s) to be present and unchanged.
Notes:
- This is a project governance safety check.
Related: blessed_gate_outputs

## Key: default_branch
Key: default_branch
Type: str
Default: "main"
Meaning: The branch name treated as the default (main) branch for safety checks.
Related: enforce_main_branch, allow_non_main

## Key: live_repo_guard
Key: live_repo_guard
Type: bool
Default: true
Meaning: If true, protect the live repository from being modified unexpectedly.
Notes:
- This checks for local changes and enforces the live changed policy.
Related: fail_if_live_files_changed, live_repo_guard_scope

## Key: live_repo_guard_scope
Key: live_repo_guard_scope
Type: str
Default: "patch"
Meaning: Scope string controlling how the live repo guard is applied.
Notes:
- Typical values are runner-defined strings such as "patch".
Related: live_repo_guard

## Key: repo_root
Key: repo_root
Type: optional[str]
Default: null
Meaning: Legacy backward-compatibility alias for selecting the active target repository root.
Notes:
- If null, the runner uses active_target_repo_root or defaults to runner_root.
- If repo_root selects a non-runner target, it is subject to the same registry rules as active_target_repo_root.
- New configurations should prefer active_target_repo_root.
Related: active_target_repo_root, target_repo_roots

## Key: ruff_autofix
Key: ruff_autofix
Type: bool
Default: true
Meaning: If true, run ruff in autofix mode before other gates.
Notes:
- Autofix is applied only within the allowed patch scope.
Related: ruff_autofix_legalize_outside, ruff_format, gates_skip_ruff

## Key: ruff_autofix_legalize_outside
Key: ruff_autofix_legalize_outside
Type: bool
Default: true
Meaning: If true, allow ruff autofix to modify files outside the declared patch set.
Notes:
- This changes the scope safety boundary.
Related: ruff_autofix, allow_outside_files

## Key: ruff_format
Key: ruff_format
Type: bool
Default: true
Meaning: If true, run ruff format as part of the ruff gate workflow.
Related: ruff_autofix, gates_skip_ruff

## Key: ascii_only_patch
Key: ascii_only_patch
Type: bool
Default: true
Meaning: If true, enforce ASCII-only content in patches and related metadata.
Notes:
- This is a repository-wide encoding safety rule.
Related: unified_patch

## Key: unified_patch
Key: unified_patch
Type: bool
Default: false
Meaning: If true, apply a unified patch zip as a single combined patch operation.
Related: unified_patch_continue, unified_patch_strip

## Key: unified_patch_continue
Key: unified_patch_continue
Type: bool
Default: true
Meaning: If true, continue applying per-file patches after a unified patch step.
Related: unified_patch

## Key: unified_patch_strip
Key: unified_patch_strip
Type: optional[int]
Default: null
Meaning: Optional strip level override for patch application.
Notes:
- If null, the runner infers a strip value.
Related: unified_patch

## Key: unified_patch_touch_on_fail
Key: unified_patch_touch_on_fail
Type: bool
Default: true
Meaning: If true, touch patch output markers when unified patch apply fails.
Related: unified_patch

## Key: patch_jail
Key: patch_jail
Type: bool
Default: true
Meaning: If true, run patch application in an isolation boundary (sandbox).
Notes:
- This changes the security boundary of patch execution.
- This requires a working bwrap; if bwrap is missing or AM_PATCH_BWRAP is invalid, the runner fails
  deterministically with PREFLIGHT/BWRAP.
Related: patch_jail_unshare_net

## Key: patch_jail_unshare_net
Key: patch_jail_unshare_net
Type: bool
Default: true
Meaning: If true, disable network access inside the patch jail.
Notes:
- This is a defense-in-depth control.
Related: patch_jail

## Key: allow_declared_untouched
Key: allow_declared_untouched
Type: bool
Default: false
Meaning: If true, allow declaring files as untouched even if they were changed.
Notes:
- This weakens a scope integrity invariant.
Related: declared_untouched_fail

## Key: allow_no_op
Key: allow_no_op
Type: bool
Default: false
Meaning: If true, allow patches that result in no changes being applied.
Related: no_op_fail

## Key: allow_outside_files
Key: allow_outside_files
Type: bool
Default: false
Meaning: If true, allow patch application to modify files outside the declared set.
Notes:
- This changes the scope safety boundary.
Related: enforce_allowed_files

## Key: allow_push_fail
Key: allow_push_fail
Type: bool
Default: true
Meaning: If true, do not fail the run if git push fails after a successful commit.
Related: commit_and_push

## Key: declared_untouched_fail
Key: declared_untouched_fail
Type: bool
Default: true
Meaning: If true, fail the run when declared-untouched files are detected as changed.
Related: allow_declared_untouched

## Key: enforce_allowed_files
Key: enforce_allowed_files
Type: bool
Default: true
Meaning: If true, enforce the allowed-files list when applying patches.
Related: allow_outside_files

## Key: no_op_fail
Key: no_op_fail
Type: bool
Default: true
Meaning: If true, fail the run when the patch applies as a no-op.
Related: allow_no_op

## Key: no_rollback
Key: no_rollback
Type: bool
Default: false
Meaning: If true, disable rollback on commit/push failure.
Notes:
- This does not change workspace rollback after patch failure.
- Legacy config alias rollback_on_failure maps into this key by inversion.
Related: rollback_workspace_on_fail

## Key: rollback_workspace_on_fail
Key: rollback_workspace_on_fail
Type: enum
Default: none-applied
Meaning: Control automatic workspace rollback after patch failure.
Allowed values:
- none-applied: rollback only when applied_ok == 0
- always: rollback on any patch failure, including partial apply
- never: never rollback automatically
Notes:
- Gate, finalize-live/live-repo, audit, and promotion failures do not
  trigger rollback.
- The failed workspace state is preserved for repair after non-patch failures.
Related: no_rollback

## Key: post_success_audit
Key: post_success_audit
Type: bool
Default: true
Meaning: If true, run post-success audit checks after gates succeed.
Related: audit_rubric_guard

## Key: soft_reset_workspace
Key: soft_reset_workspace
Type: bool
Default: false
Meaning: If true, perform a soft reset of the workspace before applying the patch.
Notes:
- This is typically a git reset that preserves untracked files.
Related: update_workspace

## Key: test_mode
Key: test_mode
Type: bool
Default: false
Meaning: If true, run the runner in a test-oriented mode for local development.
Notes:
- This may change defaults for safety and cleanup behaviors.
Related: test_mode_isolate_patch_dir

## Key: test_mode_isolate_patch_dir
Key: test_mode_isolate_patch_dir
Type: bool
Default: true
Meaning: If true, isolate patch_dir during test_mode to avoid cross-run interference.
Related: test_mode

## Key: update_workspace
Key: update_workspace
Type: bool
Default: false
Meaning: If true, update the workspace repository (fetch/pull) before running.
Notes:
- This may change the base revision used for gating.
Related: soft_reset_workspace

## Key: biome_autofix
Key: biome_autofix
Type: bool
Default: true
Meaning: If true, the Biome gate may run an autofix phase when the initial check fails.
Interactions:
- When false, the Biome gate executes exactly once using gate_biome_command.
- When true, the gate may run check/apply/final phases using gate_biome_command and
  gate_biome_fix_command.
Related: gate_biome_command, gate_biome_fix_command, biome_autofix_legalize_outside

## Key: gate_biome_fix_command
Key: gate_biome_fix_command
Type: list[str] | str
Default: ["npm", "run", "lint:files:fix", "--"]
Meaning: Command argv for the BIOME_AUTOFIX (apply) phase of the Biome gate.
Interactions:
- Used only when biome_autofix=true and the BIOME (check) phase fails.
- String values are parsed using shell-like splitting (shlex), like gate_biome_command.
Related: biome_autofix, gate_biome_command

## Key: biome_autofix_legalize_outside
Key: biome_autofix_legalize_outside
Type: bool
Default: true
Meaning: If true, allow BIOME_AUTOFIX (apply) to modify additional Biome-scoped files
outside the changed paths set.
Interactions:
- Applies only when biome_autofix=true.
- Legalized files must match gate_biome_extensions (case-insensitive suffix match).
Related: biome_autofix, gate_biome_extensions

## Key: biome_format
Key: biome_format
Type: bool
Default: true
Meaning: If true, run a BIOME_FORMAT (write) phase before the BIOME (check) phase.
Notes:
- This key only controls the Biome format phase. It does not affect BIOME_AUTOFIX.
Related: gate_biome_format_command, biome_format_legalize_outside

## Key: gate_biome_format_command
Key: gate_biome_format_command
Type: list[str] | str
Default: ["npm", "exec", "--", "biome", "format", "--write"]
Meaning: Command argv for the BIOME_FORMAT (write) phase of the Biome gate.
Interactions:
- Used only when biome_format=true.
- String values are parsed using shell-like splitting (shlex), like gate_biome_command.
Related: biome_format, gate_biome_command

## Key: biome_format_legalize_outside
Key: biome_format_legalize_outside
Type: bool
Default: true
Meaning: If true, allow BIOME_FORMAT (write) to modify additional Biome-scoped files
outside the changed paths set.
Interactions:
- Applies only when biome_format=true.
- Legalized files must match gate_biome_extensions (case-insensitive suffix match).
Related: biome_format, gate_biome_extensions

## Key: artifacts_root
Key: artifacts_root
Type: str|null
Default: null
Meaning: Selects the root directory used for runner-owned artifacts.
Notes:
- If null, artifacts_root defaults to runner_root.
- Relative values are resolved against runner_root.
- This key does not select the patched git repository.
Related: patch_dir_name, patch_layout_logs_dir, patch_layout_json_dir, patch_layout_workspaces_dir, patch_layout_successful_dir, patch_layout_unsuccessful_dir, active_target_repo_root

## Key: target_repo_roots
Key: target_repo_roots
Type: list[str]
Default: []
Meaning: Optional registry of allowed git target repository roots.
Notes:
- Relative entries are resolved against runner_root.
- Entries constrain explicit path selection and name-derived target paths.
- This key does not enable multi-target execution in a single run.
- See: scripts/am_patch_specification.md section 3.1.1
Related: active_target_repo_root, target_repo_name, repo_root

## Key: active_target_repo_root
Key: active_target_repo_root
Type: str|null
Default: null
Meaning: Explicit path selector for the git repository patched by the current run.
Notes:
- Relative values are resolved against runner_root.
- If null, target selection continues via scripts/am_patch_specification.md section 3.1.1.
- The effective value must resolve either to runner_root or to one entry from target_repo_roots.
- The selected effective target root is the single authoritative runtime truth.
Related: target_repo_roots, target_repo_name, artifacts_root, repo_root

## Key: target_repo_name
Key: target_repo_name
Type: str
Default: audiomason2
Meaning: Bare repo-token selector input for the `/home/pi/<name>` target family.
Notes:
- This key is not a path.
- Valid values are ASCII-only, exactly one non-empty token, with no whitespace,
  no `/`, no `\`, and no embedded newline.
- When selected, the candidate target path is `/home/pi/<target_repo_name>`.
- After target selection resolves, the effective metadata value is derived from the selected effective target root.
- See: scripts/am_patch_specification.md section 3.1.1
Related: active_target_repo_root, target_repo_roots
