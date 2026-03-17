# AM Patch Runner

# Patch Authoring Manual (PM)

AUTHORITATIVE -- AudioMason2 Status: active Version: v2.44

This manual defines what a chat must produce so that the user can run
the patch successfully and close the issue.

------------------------------------------------------------------------

## Absolute rules (HARD)

1.  The patch path MUST be under the repo patches directory (default:
    `/home/pi/audiomason2/patches/`).
2.  The patch MUST be served in a `.zip` file.
3.  The patch MUST be a unified diff in `git apply` format. Python patch
    scripts are non-compliant.

6. Always inspect the authoritative workspace snapshot before proposing or generating any patch.

------------------------------------------------------------------------

# PRE-FLIGHT GATE (HARD)

Before generating any patch, the chat MUST have:

1.  A valid ISSUE ID.
2.  An authoritative workspace snapshot (full repository or all files
    that will be modified).
3. Workspace Snapshot Format and Authority

If a single `.zip` archive is provided and it contains the full repository tree, it MUST be treated as an authoritative workspace snapshot.

No additional confirmation of authority MUST be requested from the user.

The implementing agent MUST:
- unzip the archive,
- treat its contents as the current workspace state,
- inspect the files before generating any patch.

The physical form of the snapshot (compressed archive vs. pre-unzipped directory tree) MUST NOT affect its authority.

Refusal to proceed solely on the basis that the snapshot is provided as a `.zip` archive constitutes a PRE-FLIGHT violation.

3a. Workspace Snapshot Target Derivation (HARD)

For initial patch preflight, the chat MUST deterministically derive
TARGET from the basename of the authoritative workspace snapshot zip.

The authoritative workspace snapshot basename MUST match:

    <TARGET>-main_<OPAQUE>.zip

Where:

- <TARGET> is the exact patch target value.
- <OPAQUE> is an opaque suffix and MUST be ignored for target derivation.

Examples:

- audiomason2-main_666.zip -> TARGET = audiomason2
- patchhub-main_XXX.zip -> TARGET = patchhub

The derived TARGET MUST be treated as authoritative for initial patch mode.
The chat MUST NOT guess, normalize, translate, or heuristically reinterpret
the derived TARGET.

If the authoritative workspace snapshot basename does not match this
contract, PRE-FLIGHT MUST STOP and request a compliant authoritative input.

3b. Preflight target evidence (HARD)

Before proposing, generating, or validating any patch, the chat MUST
record the authoritative TARGET and its derivation source in preflight
evidence.

In initial patch mode, the derivation source is the authoritative
workspace snapshot basename.

In repair patch mode, the derivation source is target.txt contained in
the authoritative repair overlay, as defined in Repair patch rules (HARD).

Missing authoritative TARGET evidence = PRE-FLIGHT violation.

4. If any required input is missing → STOP and request missing input.



------------------------------------------------------------------------

## Anti-monolith rule set (HARD)

A chat MUST NOT create a monolith or contribute to monolith growth.
Changes MUST preserve modular boundaries and remain localized.

This anti-monolith discipline does NOT apply to patching of
.md and .json files.

The system evaluates structural changes using metrics such as:
- growth of non-empty lines (LOC),
- total module size,
- increase in public exports,
- increase in internal imports,
- emergence of hub modules,
- violation of architectural ownership boundaries.

Growth itself is not forbidden.
Uncontrolled centralization and coupling expansion are.

Required rules:

1. Prefer small, localized changes.
2. Do not create catch-all (“god”) modules.
3. Respect ownership boundaries.
4. If a module grows significantly or is already large,
   new logic MUST be extracted into a new file.
5. If a module shows concentration signals (many exports,
   many internal imports, or hub characteristics),
   further expansion is prohibited and extraction is required.
6. File extraction is the default structural mitigation strategy.
7. Only if extraction is objectively impossible may
   architectural approval be requested.


------------------------------------------------------------------------

## Per-file patch zip format (HARD)

The patch delivered to the user MUST be a `.zip` that contains one
`.patch` file per modified repository file.

Rules:

1.  For each modified repo file `path/to/file.ext`, the zip MUST contain
    exactly one patch file named:
    `patches/per_file/path__to__file.ext.patch`
2.  Each patch file MUST contain a unified diff that changes only its
    corresponding file.
3.  The zip MUST NOT contain a combined patch.
4.  The set of patch files must be non-empty.
5.  Each patch file MUST pass: `git apply --check <that_file.patch>`.
6.  The zip MUST NOT contain any additional files except:
    - per-file patch files under patches/per_file/ as defined above,
    - the required COMMIT_MESSAGE.txt at the zip root,
    - the required ISSUE_NUMBER.txt at the zip root, and
    - the required target.txt at the zip root.
7.  The patch zip basename MUST be exactly `issue_<ISSUE>_v<N>.zip`, where:
    - `<ISSUE>` exactly matches `ISSUE_NUMBER.txt`, and
    - `<N>` is a positive integer written in ASCII digits.
------------------------------------------------------------------------

## Commit message file (HARD)

1. The patch zip MUST include exactly one commit message file at the zip root named:
   COMMIT_MESSAGE.txt
2. The file MUST be ASCII-only and use LF newlines.
3. The file content MUST be non-empty.
4. The commit message used in the canonical invocation command MUST match the file content exactly after stripping exactly one trailing LF if present (no other trimming).
5. The commit message MUST be written in English (no other language is permitted).
------------------------------------------------------------------------
## Issue number file (HARD) 
 
1. The patch zip MUST include exactly one issue file at the zip root named: 
   ISSUE_NUMBER.txt 
2. The file MUST be ASCII-only and use LF newlines. 
3. The file content MUST be non-empty. 
4. The issue number  used in the canonical invocation command MUST match the file content exactly after stripping exactly one trailing LF if present (no other trimming). 
------------------------------------------------------------------------ 
## Target file (HARD)

1. The patch zip MUST include exactly one target file at the zip root named:
   target.txt
2. target.txt MUST be ASCII-only and use LF newlines.
3. target.txt MUST contain exactly one non-empty line.
4. target.txt carries the patch target value in the same path syntax used by the runner target-root policy surface.
5. In initial patch mode, target.txt MUST exactly equal the TARGET derived in PRE-FLIGHT from the authoritative workspace snapshot basename.

6. In repair patch mode, target.txt MUST exactly equal the TARGET read from target.txt contained in the authoritative latest patched_issue{ISSUE}_*.zip overlay artifact.

7. The chat MUST NOT invent, normalize, translate, or otherwise alter the authoritative TARGET value when writing target.txt.

8. Any mismatch between target.txt and the authoritative target source is NON-COMPLIANT.
------------------------------------------------------------------------

## Patch requirements (HARD)

1.   Paths are repo-relative.
2.   Deterministic behavior only.
3.   No randomness, no time dependence, no interactive prompts during runtime, no network access.
4.   All changes MUST be expressed as unified diff patches, packaged per file.
5.   `git apply --check <patch>.patch` MUST succeed.
6.  Structural changes MUST preserve modular boundaries as defined by the Monolith gate ownership areas, except that this requirement does NOT apply to patching of .md and .json files.


## Line Length and Style Safety (HARD)

1. Any added or modified line in `.py` and `.js` files MUST respect the
   repository line-length policy - 100 chars per line.
2. Long lines in `.py` and `.js` files MUST be wrapped deterministically at
   authoring time.
3. Long string literals and f-strings in `.py` files MUST be split using
   parentheses and implicit concatenation, or equivalent deterministic
   wrapping.
4. Long function calls in `.py` and `.js` files MUST use parenthesized
   multi-line argument formatting.
5. Long collection literals in `.py` and `.js` files MUST use one element
   per line when exceeding the line-length policy.
6. Long import statements in `.py` and `.js` files MUST use parenthesized
   multi-line imports or multiple explicit imports, consistent with
   existing repository style.
7. The patch MUST NOT rely on post-processing formatters to correct
   line-length violations in `.py` and `.js` files.
------------------------------------------------------------------------


## Change log concurrency discipline (HARD)

1. Regular implementation patches MUST NOT modify docs/changes.md directly.

2. Every patch that changes src/, plugins/, or docs/ MUST create exactly one
   new change fragment under docs/change_fragments/.

3. The fragment filename MUST be unique and deterministic, using an ISO 8601
   UTC timestamp plus a short ASCII slug:
   YYYY-MM-DDTHH-MM-SSZ_<slug>.md

4. Thedfragment content MUST contain:
   - one ISO 8601 timestamp
   - human-readable description of the delivered change

5. Change log text MUST NOT contain:
   - issue numbers
   - issue references
   - patch filenames
   - chat/session metadata

6. docs/changes.md is a generated rollup artifact only.
   Direct manual editing of docs/changes.md in regular feature patches is forbidden.

7. If docs/changes.md is regenerated, that regeneration MUST be done only in a
   dedicated docs-only integration patch authored against the latest authoritative main.

8. PM validator MUST fail if:
   - a regular patch modifies docs/changes.md directly, or
   - any added change-log text contains issue references.


------------------------------------------------------------------------



# INITIAL PATCH RULES (HARD)

These rules apply when generating the first patch for an issue.

## Deliverable (MANDATORY)

The chat MUST provide:

1.  A downloadable `.zip` patch under `patches/`.
1a. The downloadable `.zip` patch basename MUST follow the same `issue_<ISSUE>_v<N>.zip`
    contract defined in Per-file patch zip format (HARD).
1b. The downloadable .zip patch MUST include COMMIT_MESSAGE.txt at the zip root (see Commit message file).
2.  A canonical invocation command in a code block.
3.  The exact PATCH argument used in invocation.
4.  A validator evidence block as defined in PM patch validator (HARD).

Canonical invocation format (NO VARIANTS):

    python3 scripts/am_patch.py ISSUE_ID "commit message" PATCH

-   `PATCH` may be `patches/<name>.zip` or `<name>.zip`
-   Absolute paths are forbidden unless under `patches/`
-   The command MUST be provided exactly once
-   No alternative forms are allowed

If invocation command is missing or malformed, the patch is
NON-COMPLIANT.

## Inspection Proof (HARD)

For every initial patch, the chat MUST include an INSPECTION PROOF block containing:

1. AUTHORITATIVE INPUTS
   - workspace snapshot identifier
   - overlay archive identifier (if applicable)
   - authoritative TARGET value
   - TARGET derivation source

2. FILES TOUCHED (MANIFEST)
   - full list of repo-relative modified files

3. ANCHORS
   - for each modified file, at least two structural anchors
     (e.g. function/class names, existing symbols, identifying section markers)

Missing INSPECTION PROOF = NON-COMPLIANT.


## Validation discipline (HARD)

Before sending:

1.  Patch MUST modify at least one file.
2.  Patch MUST apply cleanly (`git apply --check`).
3.  Modified files MUST compile (`python -m compileall` minimum).
3a. Modified JavaScript files MUST pass a syntax check. For each modified file with extension .js, .mjs, or .cjs, the chat MUST run:  node --check <file>
3b. Modified tests of pytest MUST pass.
3c. Ruff, MyPy, TypeScript, Biome on changed files must pass
4.  Patch MUST not introduce new dependencies without explicit approval.
5.  Patch MUST not introduce Monolith gate violations, except that
    this requirement does NOT apply to patching of .md and .json
    files.
    This includes:
      - uncontrolled growth of existing modules,
      - introduction of hub/catch-all files,
      - cross-area ownership violations,
      - structural coupling expansion.

For PM validator machine-verifiable checks, Monolith enforcement applies
only to repo files with extension `.py` or `.js`.
These PM Monolith rules are authoritative for PM validator workflow.

Machine-verifiable Monolith limits for PM validator purposes:

-   Existing file thresholds:
    -   if file has >= 900 LOC: allow at most +20 LOC, +2 exports, +1 imports
    -   if file has >= 1300 LOC: allow +0 LOC, +0 exports, +0 imports
-   New file thresholds:
    -   max 400 LOC
    -   max 25 exports
    -   max 15 imports
-   Catch-all basenames are forbidden:
    -   `utils.py`
    -   `common.py`
    -   `helpers.py`
    -   `misc.py`
-   Catch-all directories are forbidden:
    -   `utils/`
    -   `common/`
    -   `helpers/`
    -   `misc/`
-   Allowlist is empty.
-   Hub thresholds used by the validator:
    -   fan-in delta threshold = 5
    -   fan-out delta threshold = 5
    -   exports delta minimum = 3
    -   LOC delta minimum = 100
-   Cross-area threshold used by the validator:
    -   3 or more distinct ownership areas in one change is forbidden


The chat MUST NOT claim success without evidence.

The runner remains the authority.
6. The chat MUST provide evidence of:
   - git apply --check success per per-file patch
   - python -m compileall success (at least modified files)

7. If evidence is not shown, the chat MUST NOT claim the patch was tested.

------------------------------------------------------------------------

## PM validator (HARD)

Before delivering any initial patch or repair patch, the chat MUST run
one self-contained PM validator Python file supplied as a project file.
The validator artifact MUST NOT rely on repository-relative imports,
repository-relative config files, or an opened repository checkout.

Canonical invocation formats (NO REPO-BOUND VARIANTS):

Initial patch:

    python3 pm_validator.py ISSUE_ID "commit message" PATCH --workspace-snapshot WORKSPACE_SNAPSHOT_ZIP

Repair patch:

    python3 pm_validator.py ISSUE_ID "commit message" PATCH --repair-overlay PATCHED_ISSUE_ZIP [--workspace-snapshot WORKSPACE_SNAPSHOT_ZIP --supplemental-file REPO_PATH ...]

Where:

-   `pm_validator.py` means the filesystem path to the single-file PM validator artifact.
-   `WORKSPACE_SNAPSHOT_ZIP` means the authoritative full workspace snapshot artifact.
-   `PATCHED_ISSUE_ZIP` means the authoritative latest `patched_issue{ISSUE}_*.zip` overlay artifact.
-   `--supplemental-file REPO_PATH` is permitted only for explicit per-file supplemental authority outside the overlay as defined in Repair patch rules (HARD).

Rules:

1.  Delivery is forbidden unless the validator exits with status 0 and
    reports PASS.
2.  The chat MUST include a validator evidence block containing:
    - the exact command,
    - the exact exit status,
    - the full raw validator output without paraphrase or summarization,
    - the exact authoritative artifact paths passed to the validator,
    - for repair validation, whether the run was overlay-only or used
      supplemental authority,
    - if supplemental authority was used, the exact repo-relative file
      list supplied via `--supplemental-file`.
3.  The validator evidence block is mandatory for both initial patches
    and repair patches.
4.  PASS means only that machine-verifiable PM checks covered by the
    validator passed.
5.  Manual-only PM requirements remain mandatory even when the
    validator reports PASS.
6.  The chat MUST NOT claim "PM fully verified" unless manual-only PM
    requirements are also independently evidenced.
7.  The validator evidence block is additive. The runner remains the
    authority for apply and runtime results.
8.  pm_validator.py is in project files, or in repo folder scripts/.
9.  For initial patch validation, the validator MUST derive the expected
    target from the authoritative workspace snapshot basename using the
    contract <TARGET>-main_<OPAQUE>.zip and verify exact equality with
    target.txt in PATCH.

10. If the authoritative workspace snapshot basename does not match that
    contract, the validator MUST fail.

11. For repair patch validation, the validator MUST read target.txt from
    the authoritative latest patched_issue{ISSUE}_*.zip overlay artifact
    and verify exact equality with target.txt in PATCH.

12. If repair validation also uses a workspace snapshot and its basename
    matches the initial snapshot naming contract, the validator MUST
    verify that the basename-derived target exactly equals the overlay
    target.txt value.

13. Any target mismatch detected by the validator is a FAIL. 
------------------------------------------------------------------------

# REPAIR PATCH RULES (HARD)

These rules apply when user provides .zip file with filename beginning with patched_issue{ISSUE}_.

Repair patches MUST also include COMMIT_MESSAGE.txt and obey the same matching rule defined in Commit message file (HARD).

Repair patches MUST also satisfy PM patch validator (HARD) before delivery.

## Authoritative overlay model

Default repair authority is overlay-only.

Authoritative artifacts for repair validator workflow:

1.  Most recent `patched_issue{ISSUE}_*.zip`.
2.  Optional full workspace snapshot, but only as per-file supplemental
    authority for files outside the overlay when escalation is allowed
    by these rules.

Repair target authority:

-   For repair patch preflight, TARGET MUST be read from target.txt
    contained in the most recent patched_issue{ISSUE}_*.zip.
-   Overlay target.txt is authoritative for repair mode.
-   If overlay target.txt is missing, empty, multi-line, or non-ASCII,
    PRE-FLIGHT MUST STOP.
-   If a full workspace snapshot is also provided and its basename
    matches <TARGET>-main_<OPAQUE>.zip, the basename-derived TARGET
    MUST exactly equal the overlay target.txt value.
-   Any mismatch is NON-COMPLIANT.

Per-file authority:

-   If file exists in latest `patched_issue{ISSUE}_*.zip`, that version
    is authoritative by default.
-   A file not present in the overlay MUST NOT be sourced from the full
    workspace snapshot unless it is explicitly declared as a
    supplemental authority file.
-   Supplemental authority is per-file only. Bulk or implicit full-tree
    fallback is FORBIDDEN.
-   Logs are diagnostic only.

Generating repair patch against outdated overlay is FORBIDDEN.

Repair patches MUST follow a file-local default workflow.
The agent MUST NOT reconstruct, overwrite, or mechanically rebuild the
entire repository tree unless strictly required for correctness.

The default behavior is minimal-scope modification based on failing gate logs.

------------------------------------------------------------------------

## Repair workflow optimization (HARD)

### Core principle: minimal scope

-   The agent MUST modify only the minimal set of files required to fix
    the failing gate(s).
-   The agent MUST justify any widening of scope using log evidence and
    file inspection.
-   Automatic full-tree restoration or overlay merging is prohibited.


## Ruff / Mypy /Biome / Typescript failures (default-minimal workflow)

If the failing gates include `ruff` and/or `mypy`, the agent MUST:

1.  Use the provided logs to identify exact failing file paths.
2.  Restrict modifications to only the implicated files.
3.  Prefer files present in patched_issue{ISSUE}_*.zip when applicable.
4.  Avoid unpacking or reconstructing the full workspace unless the log
    explicitly references files outside `patched_issue{ISSUE}_*.zip`.

Fixing pure ruff/mypy/biome/typescript failures MUST NOT trigger full repository rebuild.


## Pytest failures (triage workflow)

If the failing gates include `pytest`, the agent MUST perform triage
before escalating scope.

Minimal path (preferred):

-   If the failure can plausibly be fixed within files present in
    `patched_issue{ISSUE}_*.zip`, modifications MUST be restricted to those files.

Escalation (only when required):

-   The agent MAY inspect the full workspace snapshot ONLY if the log
    references files not included in `patched_issue{ISSUE}_*.zip`, or the failure
    depends on configuration, fixtures, test resources, packaging,
    entrypoints, or other files outside the authoritative overlay.
-   Any such escalation MUST stay per-file. Only the minimal explicit
    supplemental authority file list is allowed; full-tree fallback is
    prohibited.

Even after escalation, only the minimal required files may be modified.

Mechanical replacement of the entire repository tree is prohibited.

## Monolith gate repair instructions (HARD)

This section does NOT apply to patching of .md and .json
files.

If the Monolith gate fails, the chat MUST correct the structural
violation before attempting any other modification.

### Scope discipline (MANDATORY)

Monolith repair is file-local by default.

If the Monolith gate identifies specific modified files as the source
of the violation, the repair MUST be restricted strictly to those files.

Full repository unpacking, workspace-wide inspection, or refactoring of
unrelated modules is prohibited unless the gate log explicitly indicates
cross-file structural impact that cannot be repaired within the flagged
files.

Scope expansion requires explicit log-backed justification.

### Repair procedure (MANDATORY)

1. Identify the violated signal from the Monolith output:
   - excessive LOC growth,
   - large total module size,
   - increased public exports,
   - increased internal imports,
   - hub characteristics,
   - ownership boundary violation,
   - parse/syntax error introduced.

2. Apply structural mitigation (default strategy: extraction):
   - extract newly added or expanded logic into a new, appropriately
     scoped file,
   - split responsibility clusters into separate modules,
   - move cross-area logic into an area-owned module,
   - reduce internal imports by introducing clearer boundaries.

3. Verify the repair does not re-introduce concentration:
   - the original module must not continue to grow as a catch-all,
   - the extraction must not create a new hub or cross-area dependency
     magnet.

### Forbidden repairs (HARD)

The chat MUST NOT:
- suppress, bypass, or “silence” the violation,
- centralize additional logic into the failing module,
- merge unrelated responsibilities to “make it pass”,
- perform broad refactors not justified by the Monolith output.

### Escalation rule (HARD)

Only if structural repair within the flagged files is objectively
impossible may architectural approval be requested.

## Scope Expansion Justification (HARD)

If the chat modifies files outside the minimal set directly implicated
by failing gate logs or outside the authoritative overlay,
it MUST include a SCOPE EXPANSION JUSTIFICATION block containing:

- Gate name
- Log reference
- Why the issue cannot be fixed within minimal scope
- Minimal additional files list

Missing justification when scope expands = NON-COMPLIANT.
------------------------------------------------------------------------

## FILE AUTHORITY MANIFEST (HARD)

Before generating repair patch, the chat MUST output:

1.  Full list of repo files to be modified.
2.  Authority source per file:
    -   source = patched_issue{ISSUE}_*.zip (default repair authority)
    -   or source = full workspace snapshot (supplemental authority,
        permitted only for explicitly listed files outside overlay)
3.  At least one structural anchor per file proving inspection.
4.  If any file uses supplemental authority, the manifest MUST also list
    the exact log-backed reason that required each such file.

5.  The manifest MUST include the authoritative TARGET value used for
    repair mode.
6.  The manifest MUST state whether TARGET was established from:
    - overlay target.txt only, or
    - overlay target.txt plus matching workspace snapshot basename
      consistency check.

Missing manifest = NON-COMPLIANT.

------------------------------------------------------------------------

## Repair validation evidence (HARD)

For repair patches, the chat MUST provide evidence of:

1.  `git apply --check` success per file
2.  `python -m compileall` success (at least modified files)
2.  all pytest tests
3.  validator evidence as defined in PM patch validator (HARD)

If evidence is not shown, the chat MUST NOT claim patch was tested.

------------------------------------------------------------------------

## Issue closing rule

An issue may be closed only if:

-   Runner returns SUCCESS
-   Success log shows commit SHA
-   Push status line exists (e.g., `push=OK`)
-   User confirms correctness

Chats must never instruct closing based on reasoning alone.

------------------------------------------------------------------------

# Single Source of Truth (HARD)

1.  Always base patch on latest authoritative workspace.
2.  Open and inspect workspace before writing patch.
3.  No guessing or reconstruction.
4.  Workspace overrides chat history.
5.  No cross-chat memory as source of truth.
6. Every patch (initial or repair) MUST include an INPUTS USED list
   enumerating:
   - workspace snapshot identifiers
   - overlay archive identifiers (if any)
   - exact repo files inspected for decision-making

   Inputs not listed MUST NOT be relied upon.
