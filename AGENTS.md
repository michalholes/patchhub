# Codex repository guidance

This file governs Codex runs started from this repository root.

## Repository role

- This repository is both the PatchHub source tree and the home of the central artifact root.
- For patchhub-targeted execution, the target worktree is `/home/pi/patchhub`.
- `/home/pi/patchhub/patches` is an artifact store, not a documentation source. Do not browse historical patch zips or workspaces unless the issue pack explicitly requires it.

## Patch and Amp execution

- Write patch artifacts to `/home/pi/patchhub/patches` as `issue_<ISSUE>_v<N>.zip`.
- Use one concise ASCII commit message and keep it byte-identical anywhere it is repeated.
- For patchhub-targeted execution, run Amp from this repository root:
  `python3 scripts/am_patch.py ISSUE_ID "commit message" patches/issue_<ISSUE>_v<N>.zip --target-repo-name patchhub`

## Post-Amp loop

- If Amp fails, stay in the same issue, inspect the latest `patched_issue<ISSUE>_*.zip` overlay and relevant logs under `/home/pi/patchhub/patches`, diagnose the failure, produce the next patch version, and rerun Amp.
- If Amp succeeds, do not stop immediately. Perform a correctness review against the issue intent and the instructions pack. If you find a remaining logical defect, produce the next patch version in the same issue and run Amp again.
- Stop only when the issue is truly complete after Amp success and correctness review, or when you hit a hard blocker that requires an explicit user decision.

## CTA semantics

- `issue X` means inspect only. Find the latest issue pack, report readiness, and do not modify files.
- `implementuj issue X` means execute the issue.
- `daj patch issue X` means execute the issue.
- If the user explicitly says to switch executor to the implementation chat, stop and report current state instead of continuing execution as Codex.

## Issue pack lookup

- Look only in `/home/pi/patchhub/patches` for `instructions_<ISSUE>_v<N>.zip`.
- Select the highest available `N`.
- If no pack exists, or if the latest pack is ambiguous or unreadable, stop and report the blocker.
- Treat `HANDOFF.md` and `constraint_pack.json` inside the selected pack as normative for scope and constraints.

## Execution discipline

- Stay within the current repository unless the instructions pack explicitly says the issue targets a different repo. If the pack implies a multi-repo change, stop and report that the issue must be split.
- Use only the issue pack, the current repository state, the latest Amp overlay/logs, and files directly needed for implementation.
- Do not read repository-local patch manuals or unrelated historical patch artifacts unless the issue pack explicitly requires it.
- Do not mine old `issue_*.zip` files for format examples.
- Before the first Amp run, verify that the patch artifact includes every modified file, including add-file hunks for new files.

## Cleanup

- Remove scratch files, temporary extracted artifacts, ad hoc helper patches, and other non-normative debris before stopping.
- Keep only normative outputs: issue patch zips under `/home/pi/patchhub/patches`, relevant Amp logs/overlays, and the repository changes that belong to the issue.
