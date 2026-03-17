# check_patch_pm.py

`scripts/check_patch_pm.py` validates a patch zip against the
machine-verifiable PM rules before delivery.

## Canonical invocation

```bash
python3 scripts/check_patch_pm.py ISSUE_ID "commit message" PATCH
```

`PATCH` may be a basename under `patches/` or a repo-relative path under
`patches/`.

## Output contract

- Exit `0`: PASS
- Exit `1`: FAIL
- Exit `2`: usage error or validator internal error

Text mode prints a deterministic rule-by-rule report beginning with
`RESULT: PASS` or `RESULT: FAIL`.

`--json` prints the same verdict as structured JSON.

## Covered checks

The validator covers only machine-verifiable PM requirements:

- patch path under `patches/`
- patch zip basename `issue_<ISSUE>_v<N>.zip`
- `.zip` artifact shape
- `COMMIT_MESSAGE.txt`
- `ISSUE_NUMBER.txt`
- optional root-level `target.txt` (ASCII, exactly one non-empty line)
- PM per-file patch layout
- patch-member path/header consistency
- added-line length limit for `.py` and `.js` patch members only
- `git apply --check`
- `python -m compileall -q` for modified Python files
- `node --check` for modified `.js`, `.mjs`, and `.cjs` files
- Monolith gate using `scripts/am_patch/am_patch.toml`

## Explicit non-goals

PASS does not prove manual-only PM requirements such as English-only
review, inspection-proof blocks, INPUTS USED blocks, or chat-output
format obligations.


Docs gate is enforced: changes to src/, plugins/, or docs/ require a new file under docs/change_fragments/.
