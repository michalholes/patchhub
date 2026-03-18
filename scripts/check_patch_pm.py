from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from zipfile import ZipFile

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from am_patch.config import Policy, build_policy, load_config
from am_patch.log import Logger
from am_patch.monolith_gate import run_monolith_gate
from patchhub.zip_commit_message import (
    ZipCommitConfig,
    ZipIssueConfig,
    read_commit_message_from_zip_path,
    read_issue_number_from_zip_path,
)
from patchhub.zip_patch_subset import build_zip_patch_manifest

PATCH_DIR_NAME = "patches"
TARGET_FILE_NAME = "target.txt"

PATCH_BASENAME_RE = re.compile(r"^issue_(?P<issue>\d+)_v(?P<version>[1-9]\d*)\.zip$")


COMMIT_CFG = ZipCommitConfig(True, "COMMIT_MESSAGE.txt", 4096, 200)
ISSUE_CFG = ZipIssueConfig(True, "ISSUE_NUMBER.txt", 128, 200)
MONOLITH_KEYS = [
    "gate_monolith_mode",
    "gate_monolith_scan_scope",
    "gate_monolith_extensions",
    "gate_monolith_compute_fanin",
    "gate_monolith_on_parse_error",
    "gate_monolith_areas_prefixes",
    "gate_monolith_areas_names",
    "gate_monolith_areas_dynamic",
    "gate_monolith_large_loc",
    "gate_monolith_huge_loc",
    "gate_monolith_large_allow_loc_increase",
    "gate_monolith_huge_allow_loc_increase",
    "gate_monolith_large_allow_exports_delta",
    "gate_monolith_huge_allow_exports_delta",
    "gate_monolith_large_allow_imports_delta",
    "gate_monolith_huge_allow_imports_delta",
    "gate_monolith_new_file_max_loc",
    "gate_monolith_new_file_max_exports",
    "gate_monolith_new_file_max_imports",
    "gate_monolith_hub_fanin_delta",
    "gate_monolith_hub_fanout_delta",
    "gate_monolith_hub_exports_delta_min",
    "gate_monolith_hub_loc_delta_min",
    "gate_monolith_crossarea_min_distinct_areas",
    "gate_monolith_catchall_basenames",
    "gate_monolith_catchall_dirs",
    "gate_monolith_catchall_allowlist",
]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    status: str
    detail: str


class ValidationError(Exception):
    pass


class MonolithLogger:
    def __init__(self) -> None:
        self.screen_level = "quiet"
        self.log_level = "quiet"
        self.lines: list[str] = []

    def section(self, message: str) -> None:
        self.lines.append(message)

    line = section
    warning_core = section
    error_core = section

    def emit_error_detail(self, message: str) -> None:
        self.lines.extend(message.rstrip("\n").splitlines())


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def _resolve_patch_path(repo_root: Path, patch_arg: str) -> tuple[Path, bool]:
    raw = str(patch_arg or "").strip()
    if not raw:
        raise ValidationError("missing_patch_argument")
    patch_dir = repo_root / PATCH_DIR_NAME
    p = Path(raw)
    if p.is_absolute():
        resolved = p
    elif "/" in raw or "\\" in raw:
        resolved = repo_root / raw
    else:
        resolved = patch_dir / raw
    try:
        in_patch_dir = resolved.resolve().is_relative_to(patch_dir.resolve())
    except Exception as exc:
        raise ValidationError(f"patch_path_resolution_failed:{exc}") from exc
    return resolved, in_patch_dir


def _validate_patch_basename(zpath: Path, issue_id: str) -> RuleResult:
    match = PATCH_BASENAME_RE.fullmatch(zpath.name)
    if match is None:
        return RuleResult("PATCH_BASENAME", "FAIL", f"invalid_patch_basename:{zpath.name}")
    if match.group("issue") != issue_id:
        return RuleResult(
            "PATCH_BASENAME",
            "FAIL",
            f"issue_mismatch:expected={issue_id}:actual={match.group('issue')}:name={zpath.name}",
        )
    return RuleResult("PATCH_BASENAME", "PASS", zpath.name)


def _read_zip_non_dirs(zpath: Path) -> tuple[list[str], dict[str, bytes]]:
    with ZipFile(zpath, "r") as zf:
        names = zf.namelist()
        items = {name: zf.read(name) for name in names if not name.endswith("/")}
    return names, items


def _validate_patch_headers(expected_path: str, text: str) -> str | None:
    saw_header = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4:
                return "invalid_diff_git_header"
            if parts[2] != f"a/{expected_path}" or parts[3] != f"b/{expected_path}":
                return "diff_git_path_mismatch"
            saw_header = True
        elif line.startswith("rename from ") or line.startswith("rename to "):
            return "rename_not_supported"
        elif line.startswith("--- "):
            saw_header = True
            if line[4:] not in ("/dev/null", f"a/{expected_path}"):
                return "old_path_mismatch"
        elif line.startswith("+++ "):
            saw_header = True
            if line[4:] not in ("/dev/null", f"b/{expected_path}"):
                return "new_path_mismatch"
    return None if saw_header else "missing_patch_headers"


def _check_line_lengths(text: str) -> str | None:
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.startswith("+++"):
            continue
        if line.startswith("+") and len(line[1:]) > 100:
            return f"added_line_too_long:line={idx}:len={len(line[1:])}"
    return None


def _validate_target_text(text: str) -> str | None:
    lines = text.splitlines()
    if len(lines) != 1:
        return "target_must_have_exactly_one_line"
    value = lines[0].strip()
    if not value:
        return "target_must_be_non_empty"
    return None


def _target_rule(zip_data: dict[str, bytes]) -> RuleResult:
    raw = zip_data.get(TARGET_FILE_NAME)
    if raw is None:
        return RuleResult("TARGET_FILE", "FAIL", "missing_target_file")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        return RuleResult("TARGET_FILE", "FAIL", f"ascii_decode_failed:{exc}")
    if text.endswith("\n"):
        text = text[:-1]
    err = _validate_target_text(text)
    if err is not None:
        return RuleResult("TARGET_FILE", "FAIL", err)
    return RuleResult("TARGET_FILE", "PASS", text)


def _line_length_scope_for_repo_path(repo_path: str) -> bool:
    return Path(repo_path).suffix.lower() in {".py", ".js"}


def _build_members(
    *,
    zpath: Path,
    patch_display: str,
    issue_id: str,
    commit_message: str,
) -> tuple[list[RuleResult], list[tuple[str, bytes]], list[str]]:
    results: list[RuleResult] = []
    members: list[tuple[str, bytes]] = []
    decision_paths: list[str] = []

    status = "PASS" if zpath.suffix.lower() == ".zip" else "FAIL"
    results.append(RuleResult("PATCH_EXTENSION", status, patch_display))
    if zpath.suffix.lower() != ".zip":
        return results, members, decision_paths

    zmsg, zmsg_err = read_commit_message_from_zip_path(zpath, COMMIT_CFG)
    if zmsg is None:
        results.append(RuleResult("COMMIT_MESSAGE_FILE", "FAIL", zmsg_err or "unknown"))
    else:
        status = "PASS" if zmsg == commit_message else "FAIL"
        detail = zmsg if status == "PASS" else f"mismatch:{zmsg!r}"
        results.append(RuleResult("COMMIT_MESSAGE_FILE", status, detail))

    zid, zid_err = read_issue_number_from_zip_path(zpath, ISSUE_CFG)
    if zid is None:
        results.append(RuleResult("ISSUE_NUMBER_FILE", "FAIL", zid_err or "unknown"))
    else:
        status = "PASS" if zid == issue_id else "FAIL"
        detail = zid if status == "PASS" else f"mismatch:{zid!r}"
        results.append(RuleResult("ISSUE_NUMBER_FILE", status, detail))

    manifest = build_zip_patch_manifest(patch_path=patch_display, zpath=zpath)
    reason = str(manifest.get("reason") or "unknown")
    results.append(
        RuleResult(
            "PER_FILE_LAYOUT",
            "PASS" if reason == "ok" else "FAIL",
            reason if reason != "ok" else f"entries={int(manifest.get('patch_entry_count') or 0)}",
        )
    )
    if reason != "ok":
        return results, members, decision_paths

    names, zip_data = _read_zip_non_dirs(zpath)
    if len(names) != len(set(names)):
        results.append(RuleResult("ZIP_ENTRY_SET", "FAIL", "duplicate_zip_member"))
        return results, members, decision_paths

    target_rule = _target_rule(zip_data)
    results.append(target_rule)
    if target_rule.status != "PASS":
        return results, members, decision_paths

    allowed = {"COMMIT_MESSAGE.txt", "ISSUE_NUMBER.txt", TARGET_FILE_NAME}
    allowed.update(str(item["zip_member"]) for item in manifest["entries"])
    extras = sorted(name for name in names if not name.endswith("/") and name not in allowed)
    if extras:
        results.append(RuleResult("ZIP_ENTRY_SET", "FAIL", f"extra_entries={extras}"))
        return results, members, decision_paths
    results.append(RuleResult("ZIP_ENTRY_SET", "PASS", "allowed_entries_only"))

    seen: set[str] = set()
    for item in manifest["entries"]:
        member = str(item["zip_member"])
        repo_path = str(item["repo_path"])
        if repo_path in seen:
            results.append(RuleResult("PATCH_MEMBER_PATHS", "FAIL", "duplicate_repo_path"))
            return results, members, decision_paths
        seen.add(repo_path)
        data = zip_data[member]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            results.append(RuleResult("PATCH_MEMBER_PATHS", "FAIL", f"utf8_decode_failed:{exc}"))
            return results, members, decision_paths
        header_err = _validate_patch_headers(repo_path, text)
        if header_err is not None:
            results.append(RuleResult("PATCH_MEMBER_PATHS", "FAIL", f"{member}:{header_err}"))
            return results, members, decision_paths
        if _line_length_scope_for_repo_path(repo_path):
            length_err = _check_line_lengths(text)
            if length_err is not None:
                results.append(RuleResult("LINE_LENGTH", "FAIL", f"{member}:{length_err}"))
                return results, members, decision_paths
        members.append((member, data))
        decision_paths.append(repo_path)

    results.append(RuleResult("PATCH_MEMBER_PATHS", "PASS", f"paths={len(decision_paths)}"))
    results.append(RuleResult("LINE_LENGTH", "PASS", "py_js_added_lines<=100"))
    return results, members, decision_paths


def _git_apply_check(repo_root: Path, members: list[tuple[str, bytes]]) -> list[RuleResult]:
    out: list[RuleResult] = []
    for member, data in members:
        with tempfile.TemporaryDirectory() as td:
            patch_path = Path(td) / Path(member).name
            patch_path.write_bytes(data)
            proc = _run(["git", "apply", "--check", str(patch_path)], cwd=repo_root)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        detail = "ok" if status == "PASS" else proc.stderr.strip() or proc.stdout.strip() or "fail"
        out.append(RuleResult(f"GIT_APPLY_CHECK:{member}", status, detail))
        if status == "FAIL":
            break
    return out


def _populate_tree(
    root: Path,
    repo_root: Path,
    members: list[tuple[str, bytes]],
    decision_paths: list[str],
) -> None:
    for repo_path in decision_paths:
        src = repo_root / repo_path
        if src.exists():
            dst = root / repo_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for member, data in members:
        patch_path = root / ".pm_validator" / Path(member).name
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_bytes(data)
        proc = _run(["git", "apply", str(patch_path)], cwd=root)
        if proc.returncode != 0:
            raise ValidationError(proc.stderr.strip() or proc.stdout.strip() or member)


def _compile_python(root: Path, decision_paths: list[str]) -> RuleResult:
    targets = [root / rp for rp in decision_paths if rp.endswith(".py") and (root / rp).exists()]
    if not targets:
        return RuleResult("PY_COMPILE", "SKIP", "no_modified_python_files")
    proc = _run([sys.executable, "-m", "compileall", "-q", *map(str, targets)], cwd=root)
    if proc.returncode == 0:
        return RuleResult("PY_COMPILE", "PASS", f"files={len(targets)}")
    return RuleResult(
        "PY_COMPILE",
        "FAIL",
        proc.stderr.strip() or proc.stdout.strip() or "compileall_failed",
    )


def _check_js(root: Path, decision_paths: list[str]) -> RuleResult:
    targets = [
        root / rp
        for rp in decision_paths
        if rp.endswith((".js", ".mjs", ".cjs")) and (root / rp).exists()
    ]
    if not targets:
        return RuleResult("JS_SYNTAX", "SKIP", "no_modified_javascript_files")
    node = shutil.which("node")
    if node is None:
        raise ValidationError("node_not_found")
    for target in targets:
        proc = _run([node, "--check", str(target)], cwd=root)
        if proc.returncode != 0:
            return RuleResult(
                "JS_SYNTAX",
                "FAIL",
                proc.stderr.strip() or proc.stdout.strip() or str(target),
            )
    return RuleResult("JS_SYNTAX", "PASS", f"files={len(targets)}")


def _run_monolith(
    root: Path, repo_root: Path, config_path: Path, decision_paths: list[str]
) -> RuleResult:
    targets = [rp for rp in decision_paths if rp.endswith((".py", ".js")) and (root / rp).exists()]
    if not targets:
        return RuleResult("MONOLITH", "SKIP", "no_modified_python_or_javascript_files")
    cfg, _used = load_config(config_path)
    policy = build_policy(Policy(), cfg)
    logger = MonolithLogger()
    kwargs = {key: getattr(policy, key) for key in MONOLITH_KEYS}
    ok = run_monolith_gate(
        cast(Logger, logger),
        root,
        repo_root=repo_root,
        decision_paths=targets,
        **kwargs,
    )
    detail = "gate_passed" if ok else (logger.lines[-1] if logger.lines else "gate_failed")
    return RuleResult("MONOLITH", "PASS" if ok else "FAIL", detail)


def _format_text(results: list[RuleResult]) -> str:
    overall = "FAIL" if any(r.status == "FAIL" for r in results) else "PASS"
    lines = [f"RESULT: {overall}"]
    lines.extend(f"RULE {r.rule_id}: {r.status} - {r.detail}" for r in results)
    return "\n".join(lines) + "\n"


def _docs_gate(decision_paths: list[str]) -> RuleResult:
    trigger_prefixes = ("src/", "plugins/", "docs/")
    triggered = any(p.startswith(trigger_prefixes) for p in decision_paths)
    if not triggered:
        return RuleResult("DOCS_GATE", "PASS", "not_triggered")
    has_fragment = any(p.startswith("docs/change_fragments/") for p in decision_paths)
    if not has_fragment:
        return RuleResult("DOCS_GATE", "FAIL", "missing_change_fragment")
    if any(p == "docs/changes.md" for p in decision_paths):
        return RuleResult("DOCS_GATE", "FAIL", "direct_changes_md_edit")
    return RuleResult("DOCS_GATE", "PASS", "fragment_present")


def run_validation(args: argparse.Namespace) -> tuple[int, list[RuleResult]]:
    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config).resolve()
    zpath, in_patch_dir = _resolve_patch_path(repo_root, args.patch)
    if zpath.is_relative_to(repo_root):
        patch_display = zpath.relative_to(repo_root).as_posix()
    else:
        patch_display = str(zpath)
    results = [
        RuleResult("PATCH_LOCATION_SCOPE", "PASS" if in_patch_dir else "FAIL", patch_display)
    ]
    if not zpath.exists() or not zpath.is_file():
        results.append(RuleResult("PATCH_LOCATION", "FAIL", "patch_not_found"))
        return 1, results

    results.append(_validate_patch_basename(zpath, str(args.issue_id)))

    member_results, members, decision_paths = _build_members(
        zpath=zpath,
        patch_display=patch_display,
        issue_id=str(args.issue_id),
        commit_message=str(args.commit_message),
    )
    results.extend(member_results)
    results.append(_docs_gate(decision_paths))
    if any(r.status == "FAIL" for r in results):
        return 1, results

    results.extend(_git_apply_check(repo_root, members))
    if any(r.status == "FAIL" for r in results):
        return 1, results

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _populate_tree(root, repo_root, members, decision_paths)
        results.append(_compile_python(root, decision_paths))
        results.append(_check_js(root, decision_paths))
        results.append(_run_monolith(root, repo_root, config_path, decision_paths))

    return (1 if any(r.status == "FAIL" for r in results) else 0), results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a patch zip against machine-verifiable PM rules."
    )
    parser.add_argument("issue_id", help="Issue number expected in ISSUE_NUMBER.txt")
    parser.add_argument("commit_message", help="Expected COMMIT_MESSAGE.txt content")
    parser.add_argument("patch", help="Patch zip path or patch basename under patches/")
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        help="Authoritative repo root used for git apply and materialization checks.",
    )
    parser.add_argument(
        "--config",
        default=str(_REPO_ROOT / "scripts" / "am_patch" / "am_patch.toml"),
        help="am_patch TOML used for monolith policy.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code, results = run_validation(args)
    except ValidationError as exc:
        payload = {"result": "ERROR", "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=True, indent=2))
        else:
            print(f"RESULT: ERROR\nERROR: {exc}")
        return 2
    except Exception as exc:
        payload = {"result": "ERROR", "error": f"internal_error:{exc}"}
        msg = json.dumps(payload, ensure_ascii=True, indent=2)
        print(msg if args.json else f"RESULT: ERROR\nERROR: internal_error:{exc}")
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "result": "PASS" if exit_code == 0 else "FAIL",
                    "rules": [r.__dict__ for r in results],
                },
                ensure_ascii=True,
                indent=2,
            )
        )
    else:
        print(_format_text(results), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
