# Codex repository guidance

This file governs Codex runs started from this repository root.

## Repository role

- This repository is both the PatchHub source tree and the home of the central artifact root.
- For patchhub-targeted execution, the target worktree is `/home/pi/patchhub`.
- `/home/pi/patchhub/patches` is an artifact store, not a documentation source. Do not browse historical patch zips or workspaces unless the issue pack explicitly requires it.

## Local terminology

- `Amp` means the patch runner command `python3 scripts/am_patch.py ...` used for this workflow.
- `PatchHub` means the runner/artifact workspace rooted at `/home/pi/patchhub`.
- `PHB` means PatchHub.
- `AM2` means the broader AudioMason2 project context only. It does not widen repository scope beyond the current target repo.
- `issue pack` means the selected latest `instructions_<ISSUE>_v<N>.zip` under `/home/pi/patchhub/patches`.
- `overlay` means the latest `patched_issue<ISSUE>_*.zip` artifact for the same issue.
- These aliases are local execution shorthand only. Authority remains in repository governance files and the selected issue-pack normative sources.

## Patch and Amp execution

- Write patch artifacts to `/home/pi/patchhub/patches` as `issue_<ISSUE>_v<N>.zip`.
- Use one concise ASCII commit message and keep it byte-identical anywhere it is repeated.
- For patchhub-targeted execution, run Amp from this repository root:
  `python3 scripts/am_patch.py ISSUE_ID "commit message" patches/issue_<ISSUE>_v<N>.zip --target-repo-name patchhub`

## Post-Amp loop

- If Amp fails, stay in the same issue, inspect only the latest `patched_issue<ISSUE>_*.zip` overlay, the latest relevant Amp logs under `/home/pi/patchhub/patches`, and the minimal additional files strictly required to diagnose the failure, then produce the next patch version and rerun Amp.
- If Amp succeeds, do not stop immediately. Perform a bounded correctness review against:
  - the issue intent,
  - the selected instructions pack,
  - the files changed by the latest patch,
  - and any files explicitly implicated by the success log, overlay, or direct dependency inspection.
- After Amp success, broad repository re-audits are forbidden unless a concrete defect signal requires scope expansion.
- If you find a remaining logical defect, produce the next patch version in the same issue and run Amp again.
- Stop only when the issue is truly complete after Amp success and bounded correctness review, or when you hit a hard blocker that requires an explicit user decision.

## Optimization findings

- If you identify a concrete optimization that would materially reduce issue-turn count, repeated inspection, repeated Amp reruns, unnecessary patch versions, or other execution waste, you MUST report it to the user.
- Report only material optimizations. Ignore trivial style preferences and micro-optimizations.
- Use a short `OPTIMIZATION FINDINGS` block with:
  - impact
  - affected workflow step or files
  - safety class: `instruction-only` | `runtime-only` | `requires-governance`
  - whether it is inside or outside the current issue scope
- Do not implement workflow or contract changes outside the current issue scope unless the authoritative issue pack explicitly permits them.

## Issue pack lookup

- Look only in `/home/pi/patchhub/patches` for `instructions_<ISSUE>_v<N>.zip`.
- Select the highest available `N`.
- If no pack exists, or if the latest pack is ambiguous or unreadable, stop and report the blocker.
- Treat `HANDOFF.md` and `constraint_pack.json` inside the selected pack as the normative issue-pack sources.

## Working set discipline

- Before the first Amp run, derive a minimal working set from:
  - `HANDOFF.md`,
  - `constraint_pack.json`,
  - files explicitly named by the instructions pack,
  - files directly targeted for modification,
  - and only the immediate dependency anchors needed to implement the change correctly.
- Do not broad-scan directories or read unrelated files for context.
- Do not open the whole repository to orient yourself.
- If a needed file is not already in the working set, add it only when there is a concrete reason:
  - direct import or call dependency,
  - explicit symbol reference,
  - explicit handoff requirement,
  - Amp log evidence,
  - overlay evidence,
  - or a correctness-review defect signal.
- Any scope expansion must remain minimal and must be justified by inspected evidence.
- Build one concise local working summary from the selected issue pack and reuse it during the run instead of repeatedly rereading the full pack.
- The local working summary is an ephemeral aid only. `HANDOFF.md` and `constraint_pack.json` remain the sole normative issue-pack sources.
- Do not reread the full selected issue pack after the local working summary is created unless an ambiguity, blocker, overlay signal, or Amp log evidence requires reinspection of the normative source.
- Do not search the wider governance corpus merely to decode local execution aliases already defined in this file.

## Execution discipline

- Stay within the current repository unless the instructions pack explicitly says the issue targets a different repo. If the pack implies a multi-repo change, stop and report that the issue must be split.
- Use only:
  - the selected issue pack,
  - the current repository state,
  - the latest Amp overlay/logs,
  - and the files directly needed under the working-set discipline.
- Do not read repository-local patch manuals or unrelated historical patch artifacts unless the issue pack explicitly requires it.
- Do not mine old `issue_*.zip` files for format examples.
- Before the first Amp run, verify that the patch artifact includes every modified file, including add-file hunks for new files.
- Prefer the smallest correct patch over broad cleanup, opportunistic refactors, or speculative consistency passes.
- Do not widen scope for style-only cleanup, naming cleanup, incidental deduplication, or unrelated local improvements.
- During repair, prefer file-local fixes first. Only escalate beyond the minimal implicated files when logs, overlay state, or direct dependency inspection prove it is necessary.

## Cleanup

- Remove scratch files, temporary extracted artifacts, ad hoc helper patches, and other non-normative debris before stopping.
- Keep only normative outputs: issue patch zips under `/home/pi/patchhub/patches`, relevant Amp logs/overlays, and the repository changes that belong to the issue.
