from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepResult:
    rc: int | None
    stdout: str | None
    stderr: str | None
    value: Any


def _value_as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _value_as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return list(v)
    if isinstance(v, str):
        return [v]
    raise SystemExit("FAIL: value must be list[str] or string")


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return list(v)
    raise SystemExit("FAIL: evaluation rule must be string or list[str]")


def evaluate_step(
    *,
    rules: dict[str, Any],
    result: StepResult,
    prior: dict[int, StepResult],
    test_id: str,
    step_index: int,
) -> tuple[bool, str]:
    rc_eq = rules.get("rc_eq")
    rc_ne = rules.get("rc_ne")
    if rc_eq is not None:
        if not isinstance(rc_eq, int):
            raise SystemExit("FAIL: rc_eq must be int")
        if result.rc != rc_eq:
            return False, f"rc={result.rc} expected={rc_eq}"
    if rc_ne is not None:
        if not isinstance(rc_ne, int):
            raise SystemExit("FAIL: rc_ne must be int")
        if result.rc == rc_ne:
            return False, f"rc={result.rc} forbidden={rc_ne}"

    out_contains = _as_list(rules.get("stdout_contains"))
    for s in out_contains:
        if (result.stdout or "").find(s) < 0:
            return False, f"missing stdout token: {s}"

    out_not = _as_list(rules.get("stdout_not_contains"))
    for s in out_not:
        if (result.stdout or "").find(s) >= 0:
            return False, f"unexpected stdout token: {s}"

    out_regex = _as_list(rules.get("stdout_regex"))
    for pat in out_regex:
        if re.search(pat, result.stdout or "", flags=re.MULTILINE) is None:
            return False, f"stdout regex not matched: {pat}"

    err_contains = _as_list(rules.get("stderr_contains"))
    for s in err_contains:
        if (result.stderr or "").find(s) < 0:
            return False, f"missing stderr token: {s}"

    err_not = _as_list(rules.get("stderr_not_contains"))
    for s in err_not:
        if (result.stderr or "").find(s) >= 0:
            return False, f"unexpected stderr token: {s}"

    err_regex = _as_list(rules.get("stderr_regex"))
    for pat in err_regex:
        if re.search(pat, result.stderr or "", flags=re.MULTILINE) is None:
            return False, f"stderr regex not matched: {pat}"

    value_eq = rules.get("value_eq")
    if value_eq is not None and result.value != value_eq:
        return False, "value != value_eq"

    value_contains = _as_list(rules.get("value_contains"))
    vstr = _value_as_str(result.value)
    for s in value_contains:
        if vstr.find(s) < 0:
            return False, f"missing value token: {s}"

    value_not_contains = _as_list(rules.get("value_not_contains"))
    for s in value_not_contains:
        if vstr.find(s) >= 0:
            return False, f"unexpected value token: {s}"

    value_regex = _as_list(rules.get("value_regex"))
    for pat in value_regex:
        if re.search(pat, vstr, flags=re.MULTILINE) is None:
            return False, f"value regex not matched: {pat}"

    list_eq = rules.get("list_eq")
    if list_eq is not None:
        if not (isinstance(list_eq, list) and all(isinstance(x, str) for x in list_eq)):
            raise SystemExit("FAIL: list_eq must be list[str]")
        vlist = _value_as_list(result.value)
        if vlist != list_eq:
            return False, "list != list_eq"

    list_contains = _as_list(rules.get("list_contains"))
    if list_contains:
        vlist = _value_as_list(result.value)
        for s in list_contains:
            if s not in vlist:
                return False, f"missing list item: {s}"

    list_not_contains = _as_list(rules.get("list_not_contains"))
    if list_not_contains:
        vlist = _value_as_list(result.value)
        for s in list_not_contains:
            if s in vlist:
                return False, f"unexpected list item: {s}"

    equals_step_index = rules.get("equals_step_index")
    if equals_step_index is not None:
        if not isinstance(equals_step_index, int):
            raise SystemExit("FAIL: equals_step_index must be int")
        other = prior.get(equals_step_index)
        if other is None:
            return False, f"equals_step_index missing prior step: {equals_step_index}"
        if result.value != other.value:
            return False, "value mismatch vs prior step"

    return True, "OK"
