from __future__ import annotations


def evaluate_apply_failure_gates_policy(
    *,
    patch_applied_any: bool,
    workspace_attempt: int,
    partial_policy: str,
    zero_policy: str,
) -> bool:
    repair_attempt = workspace_attempt >= 2
    policy_value = partial_policy if patch_applied_any else zero_policy

    if policy_value == "never":
        return False
    if policy_value == "always":
        return True
    if policy_value == "repair_only":
        return repair_attempt

    raise ValueError(f"unknown apply-failure gates policy: {policy_value!r}")


def evaluate_apply_failure_gates_policy_audited(
    *,
    patch_applied_any: bool,
    workspace_attempt: int,
    partial_policy: str,
    zero_policy: str,
) -> tuple[bool, str]:
    """Evaluate apply-failure gate policy and emit a stable audit line."""

    repair_attempt = workspace_attempt >= 2
    policy_key_used = (
        "apply_failure_partial_gates_policy"
        if patch_applied_any
        else "apply_failure_zero_gates_policy"
    )
    policy_value_used = partial_policy if patch_applied_any else zero_policy
    should_run_gates = evaluate_apply_failure_gates_policy(
        patch_applied_any=patch_applied_any,
        workspace_attempt=workspace_attempt,
        partial_policy=partial_policy,
        zero_policy=zero_policy,
    )
    audit_line = (
        f"patch_apply_failure_policy_eval workspace_attempt={workspace_attempt} "
        f"repair_attempt={str(repair_attempt).lower()} "
        f"patch_applied_any={str(patch_applied_any).lower()} "
        f"policy_key_used={policy_key_used} "
        f"policy_value_used={policy_value_used} "
        f"should_run_gates={str(should_run_gates).lower()}"
    )
    return should_run_gates, audit_line
