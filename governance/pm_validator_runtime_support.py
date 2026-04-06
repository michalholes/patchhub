from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import TypeVar

PATCH_PREFIX = "patches/per_file/"
PATCH_SUFFIX = ".patch"
TARGET_FILE_NAME = "target.txt"


@dataclass(frozen=True)
class SupportRule:
    rule_id: str
    status: str
    detail: str


@dataclass(frozen=True)
class ValidationContext:
    baseline_files: dict[str, bytes]
    runnable_paths: list[str]
    runnable_patch_members: list[tuple[str, bytes]]
    degraded_rules: list[SupportRule]
    mode: str


RuleResultT = TypeVar("RuleResultT")

RunFn = Callable[[list[str], Path], CompletedProcess[str]]


def _decode_ascii_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return text[:-1] if text.endswith("\n") else text


def _member_repo_path(member: str) -> str | None:
    if not (member.startswith(PATCH_PREFIX) and member.endswith(PATCH_SUFFIX)):
        return None
    raw = member[len(PATCH_PREFIX) : -len(PATCH_SUFFIX)]
    if not raw or "/" in raw or raw.endswith("__"):
        return None
    return raw.replace("__", "/")


def collect_patch_members(
    path: Path,
    issue_id: str,
    commit_message: str,
    *,
    read_zip: Callable[[Path], tuple[list[str], dict[str, bytes]]],
    validate_basename: Callable[[Path, str], RuleResultT],
    validate_target_bytes: Callable[[bytes], tuple[str | None, str | None]],
    validate_patch_headers: Callable[[str, str], str | None],
    check_line_lengths: Callable[[str], str | None],
    line_exts: set[str],
    rule_factory: Callable[[str, str, str], RuleResultT],
) -> tuple[list[RuleResultT], list[tuple[str, bytes]], list[str], str | None]:
    results = [validate_basename(path, issue_id)]
    if path.suffix != ".zip":
        results.insert(0, rule_factory("PATCH_EXTENSION", "FAIL", str(path)))
        return results, [], [], None
    results.insert(0, rule_factory("PATCH_EXTENSION", "PASS", str(path)))
    names, items = read_zip(path)
    zmsg = (
        _decode_ascii_text(items["COMMIT_MESSAGE.txt"]) if "COMMIT_MESSAGE.txt" in items else None
    )
    zid = _decode_ascii_text(items["ISSUE_NUMBER.txt"]) if "ISSUE_NUMBER.txt" in items else None
    results.append(
        rule_factory(
            "COMMIT_MESSAGE_FILE",
            "PASS" if zmsg == commit_message else "FAIL",
            zmsg if zmsg is not None else "missing_or_non_ascii_commit_message",
        )
    )
    results.append(
        rule_factory(
            "ISSUE_NUMBER_FILE",
            "PASS" if zid == issue_id else "FAIL",
            zid if zid is not None else "missing_or_non_ascii_issue_number",
        )
    )
    if zmsg != commit_message or zid != issue_id:
        return results, [], [], None
    raw_target = items.get(TARGET_FILE_NAME)
    if raw_target is None:
        results.append(rule_factory("TARGET_FILE", "FAIL", "missing_target_file"))
        return results, [], [], None
    target_value, target_err = validate_target_bytes(raw_target)
    results.append(
        rule_factory(
            "TARGET_FILE",
            "PASS" if target_err is None else "FAIL",
            target_err or target_value or "",
        )
    )
    if target_err is not None:
        return results, [], [], None
    non_dirs = [name for name in names if not name.endswith("/")]
    members = [
        name for name in non_dirs if name.startswith(PATCH_PREFIX) and name.endswith(PATCH_SUFFIX)
    ]
    if not members:
        results.append(rule_factory("PER_FILE_LAYOUT", "FAIL", "entries=0"))
        return results, [], [], None
    allowed = {"COMMIT_MESSAGE.txt", "ISSUE_NUMBER.txt", TARGET_FILE_NAME, *members}
    extras = sorted(name for name in non_dirs if name not in allowed)
    if extras:
        results.append(rule_factory("PER_FILE_LAYOUT", "FAIL", f"extra_entries={extras}"))
        return results, [], [], None
    results.append(rule_factory("PER_FILE_LAYOUT", "PASS", f"entries={len(members)}"))

    path_errors: list[str] = []
    ascii_errors: list[str] = []
    line_errors: list[str] = []
    patch_members: list[tuple[str, bytes]] = []
    decision_paths: list[str] = []
    seen: set[str] = set()
    for member in sorted(members):
        repo_path = _member_repo_path(member)
        if repo_path is None:
            path_errors.append(f"invalid_member:{member}")
            continue
        if not member.isascii():
            path_errors.append(f"non_ascii_member:{member}")
            continue
        if not repo_path.isascii():
            path_errors.append(f"non_ascii_repo_path:{repo_path}")
            continue
        if repo_path in seen:
            path_errors.append(f"duplicate_repo_path:{repo_path}")
            continue
        seen.add(repo_path)
        raw = items[member]
        text = _decode_ascii_text(raw)
        if text is None:
            ascii_errors.append(f"{member}:non_ascii_patch_text")
            continue
        header_err = validate_patch_headers(repo_path, text)
        if header_err is not None:
            path_errors.append(f"{member}:{header_err}")
        if Path(repo_path).suffix in line_exts:
            line_err = check_line_lengths(text)
            if line_err is not None:
                line_errors.append(f"{member}:{line_err}")
        patch_members.append((member, raw))
        decision_paths.append(repo_path)
    results.append(
        rule_factory(
            "PATCH_MEMBER_PATHS",
            "PASS" if not path_errors else "FAIL",
            f"paths={len(decision_paths)}" if not path_errors else ";".join(path_errors),
        )
    )
    results.append(
        rule_factory(
            "PATCH_ASCII",
            "PASS" if not ascii_errors else "FAIL",
            "patch_members_ascii_only" if not ascii_errors else ";".join(ascii_errors),
        )
    )
    results.append(
        rule_factory(
            "LINE_LENGTH",
            "PASS" if not line_errors else "FAIL",
            "py_js_added_lines<=100" if not line_errors else ";".join(line_errors),
        )
    )
    return results, patch_members, decision_paths, target_value


def build_validation_context(
    *,
    decision_paths: list[str],
    patch_members: list[tuple[str, bytes]],
    snapshot_files: dict[str, bytes] | None,
    overlay_files: dict[str, bytes] | None,
    supplemental_files: list[str],
) -> ValidationContext:
    if overlay_files is None:
        if snapshot_files is None:
            raise ValueError("workspace_snapshot_required_for_initial_mode")
        return ValidationContext(
            baseline_files=dict(snapshot_files),
            runnable_paths=list(decision_paths),
            runnable_patch_members=list(patch_members),
            degraded_rules=[],
            mode="initial",
        )
    baseline = dict(overlay_files)
    covered = [path for path in decision_paths if path in baseline]
    covered_set = set(covered)
    runnable_members = [
        (member, raw)
        for member, raw in patch_members
        if (_member_repo_path(member) or "") in covered_set
    ]
    if snapshot_files is None:
        uncovered = [path for path in decision_paths if path not in baseline]
        degraded = [
            SupportRule(
                f"REPAIR_OVERLAY_UNCOVERED:{path}",
                "SKIP",
                "missing_pre_patch_baseline_in_repair_overlay",
            )
            for path in uncovered
        ]
        if uncovered:
            degraded.append(
                SupportRule(
                    "REPAIR_SUPPLEMENTAL_HINT",
                    "SKIP",
                    f"repair_requires_supplemental_file:{uncovered}",
                )
            )
        degraded.extend(
            [
                SupportRule(
                    "REPAIR_TARGET_SNAPSHOT_CONSISTENCY",
                    "SKIP",
                    "workspace_snapshot_absent",
                ),
                SupportRule(
                    "REPAIR_SUPPLEMENTAL_AUTHORITY",
                    "SKIP",
                    "workspace_snapshot_absent",
                ),
            ]
        )
        return ValidationContext(
            baseline_files=baseline,
            runnable_paths=covered,
            runnable_patch_members=runnable_members,
            degraded_rules=degraded,
            mode="repair-overlay-only",
        )
    if not supplemental_files:
        missing = [path for path in decision_paths if path not in baseline]
        if missing:
            raise ValueError(f"repair_requires_supplemental_file:{missing}")
        return ValidationContext(
            baseline_files=baseline,
            runnable_paths=list(decision_paths),
            runnable_patch_members=list(patch_members),
            degraded_rules=[],
            mode="repair-overlay-only",
        )
    allowed = set(supplemental_files)
    undeclared = [path for path in decision_paths if path not in baseline and path not in allowed]
    if undeclared:
        raise ValueError(f"repair_requires_supplemental_file:{undeclared}")
    missing = [path for path in allowed if path not in snapshot_files]
    if missing:
        raise ValueError(f"supplemental_file_missing_in_snapshot:{sorted(missing)}")
    for path in decision_paths:
        if path in allowed and path in snapshot_files:
            baseline[path] = snapshot_files[path]
    return ValidationContext(
        baseline_files=baseline,
        runnable_paths=[path for path in decision_paths if path in baseline],
        runnable_patch_members=list(patch_members),
        degraded_rules=[],
        mode="repair-supplemental",
    )


def apply_patch_members(
    root: Path,
    patch_members: list[tuple[str, bytes]],
    *,
    run_cmd: RunFn,
    rule_factory: Callable[[str, str, str], RuleResultT],
) -> tuple[list[RuleResultT], bool]:
    results: list[RuleResultT] = []
    patch_files: list[Path] = []
    all_checked = True
    for member, data in patch_members:
        patch_file = root / ".pm_validator" / Path(member).name
        patch_file.parent.mkdir(parents=True, exist_ok=True)
        patch_file.write_bytes(data)
        patch_files.append(patch_file)
        proc = run_cmd(["git", "apply", "--check", str(patch_file)], root)
        detail = (
            "ok" if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip() or "fail")
        )
        status = "PASS" if proc.returncode == 0 else "FAIL"
        results.append(rule_factory(f"GIT_APPLY_CHECK:{member}", status, detail))
        if proc.returncode != 0:
            all_checked = False
    if not all_checked:
        return results, False
    for patch_file in patch_files:
        proc = run_cmd(["git", "apply", str(patch_file)], root)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or patch_file.name
            raise RuntimeError(detail)
    return results, True


def not_runnable_results(
    *,
    rule_factory: Callable[[str, str, str], RuleResultT],
    cli_disabled: bool,
    reason: str,
) -> list[RuleResultT]:
    rules = [
        ("PY_COMPILE", "SKIP", reason),
        ("JS_SYNTAX", "SKIP", reason),
        ("MONOLITH", "SKIP", reason),
        ("EXTERNAL_GATE:PYTEST", "SKIP", reason),
        ("EXTERNAL_GATE:RUFF", "SKIP", reason if not cli_disabled else "cli_disabled"),
        ("EXTERNAL_GATE:MYPY", "SKIP", reason if not cli_disabled else "cli_disabled"),
        ("EXTERNAL_GATE:TYPESCRIPT", "SKIP", reason if not cli_disabled else "cli_disabled"),
        ("EXTERNAL_GATE:BIOME", "SKIP", reason if not cli_disabled else "cli_disabled"),
    ]
    return [rule_factory(rule_id, status, detail) for rule_id, status, detail in rules]
