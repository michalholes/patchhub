# PM Spec Manual (pm_spec)

AUTHORITATIVE -- AudioMason2 Status: active Version: v1.0.1

This manual defines what a controller chat must produce so that an authority patch can be created, validated, and released without drift.

------------------------------------------------------------------------

## Scope (HARD)

1. pm_spec is controller-only.
2. pm_spec governs:
   - discovery resolver evidence,
   - plan negotiation authority outputs,
   - AUTHORITY FREEZE,
   - authority patch authoring,
   - authority validation,
   - final resolver evidence before implementation freeze.
3. pm_spec does NOT govern implementation patch delivery.
4. Implementation patch delivery is governed only by governance/am_patch_instructions.md.

------------------------------------------------------------------------

## Authority-first preflight (HARD)

Before any authority patch is proposed or generated, the controller chat MUST have:
1. a valid ISSUE ID,
2. an authoritative workspace snapshot,
3. a discovery resolver result for the candidate target or scope,
4. explicit evidence of the authoritative files inspected.

Without these inputs, authority patching MUST STOP.

------------------------------------------------------------------------

## Authority freeze (HARD)

Before generating any authority patch, the controller chat MUST produce an AUTHORITY FREEZE containing:
- authoritative PLAN FREEZE items P1..Pn,
- exact authority scope,
- exact files to be modified,
- exact anchors,
- exact inserted or replacement text for every authority text file,
- success criteria SCx.y for every Pi,
- explicit list of unchanged authority constraints that remain binding.

Any authority patch that changes anything outside the latest agreed AUTHORITY FREEZE is NON-COMPLIANT.

------------------------------------------------------------------------

## Authority validation (HARD)

Before delivering any authority patch, the controller chat MUST run controller-only authority validation.

Authority validation MUST confirm:
1. every P1..Pn is explicitly covered,
2. nothing outside authority freeze scope was changed,
3. exact anchors match the frozen anchors,
4. exact inserted/replacement text matches the frozen text,
5. no second truth was introduced,
6. final authority patch is coherent with Project Contract and RC.

If authority validation fails, delivery is forbidden.

------------------------------------------------------------------------

## Final resolver gate (HARD)

After a successful authority patch and before any implementation freeze, the controller chat MUST run the final resolver against the updated authority.

Without a successful final resolver run, implementation freeze is forbidden.

------------------------------------------------------------------------

## Bridge artifact contract (HARD)

The controller chat MUST generate exactly one implementation bridge artifact:

    instructions_issue<ISSUE>.zip

The bridge artifact MUST contain exactly:
- HANDOFF.md
- constraint_pack.json
- hash_pack.txt

This artifact is the only authority bridge from controller-only workflow to implementation-only workflow.

------------------------------------------------------------------------

## Controller-only tooling (HARD)

Before delivering any authority patch, the controller chat MUST run:
- governance/pm_spec_validator.py for authority patch validation
- governance/rc_resolver.py as the final resolver after successful authority patching and before implementation freeze

Delivery is forbidden unless authority validation reports PASS.

------------------------------------------------------------------------

## Truthfulness (HARD)

The chat MUST NOT claim success without evidence.
The chat MUST NOT claim full authority compliance without:
- authority freeze evidence,
- authority validation evidence,
- final resolver evidence.

------------------------------------------------------------------------

END OF PM SPEC
