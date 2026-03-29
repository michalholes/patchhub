from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast
from zipfile import ZipFile

PATCH_RE = re.compile(r"^issue_(?P<issue>\d+)_v(?P<version>[1-9]\d*)\.zip$")
SNAPSHOT_TARGET_RE = re.compile(r"^(?P<target>.+)-main_[^/]+\.zip$")
PATCH_PREFIX = "patches/per_file/"
PATCH_SUFFIX = ".patch"
TARGET_FILE_NAME = "target.txt"
LINE_EXTS = {".py", ".js"}
JS_EXTS = {".js", ".mjs", ".cjs"}
CATCHALL_BASENAMES = {"utils.py", "common.py", "helpers.py", "misc.py"}
CATCHALL_DIRS = {"utils", "common", "helpers", "misc"}
AREAS = {"src", "plugins", "badguys", "scripts", "tests", "docs"}
HUB_FANIN_DELTA = 5
HUB_FANOUT_DELTA = 5
HUB_EXPORTS_DELTA_MIN = 3
HUB_LOC_DELTA_MIN = 100

_RE_EXPORT_LINE = re.compile(r"^\s*export\s+", re.MULTILINE)
_RE_EXPORTS_DOT = re.compile(r"\bexports\.([A-Za-z0-9_$]+)")
_RE_IMPORT_FROM = re.compile(r"\bimport\b[^;\n]*\bfrom\s*[\"']([^\"']+)[\"']")
_RE_EXPORT_FROM = re.compile(r"\bexport\b[^;\n]*\bfrom\s*[\"']([^\"']+)[\"']")
_RE_REQUIRE = re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)")


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    status: str
    detail: str


@dataclass(frozen=True)
class MonolithMetrics:
    loc: int
    internal_imports: int
    exports: int


class ValidationError(Exception):
    pass


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def _read_zip(path: Path) -> tuple[list[str], dict[str, bytes]]:
    with ZipFile(path, "r") as zf:
        names = zf.namelist()
        items = {name: zf.read(name) for name in names if not name.endswith("/")}
    return names, items


def _decode_ascii_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return text[:-1] if text.endswith("\n") else text


def _decode_ascii_raw(raw: bytes) -> str | None:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None


def _zip_text(items: dict[str, bytes], name: str) -> str | None:
    raw = items.get(name)
    return None if raw is None else _decode_ascii_text(raw)


def _validate_target_bytes(raw: bytes) -> tuple[str | None, str | None]:
    text = _decode_ascii_raw(raw)
    if text is None:
        return None, "target_must_be_ascii"
    if "\r" in text:
        return None, "target_must_use_lf_newlines"
    value = text[:-1] if text.endswith("\n") else text
    if "\n" in value:
        return None, "target_must_have_exactly_one_line"
    if value == "":
        return None, "target_must_be_non_empty"
    return value, None


def _target_rule(items: dict[str, bytes]) -> tuple[RuleResult, str | None]:
    raw = items.get(TARGET_FILE_NAME)
    if raw is None:
        return RuleResult("TARGET_FILE", "FAIL", "missing_target_file"), None
    value, err = _validate_target_bytes(raw)
    if err is not None:
        return RuleResult("TARGET_FILE", "FAIL", err), None
    assert value is not None
    return RuleResult("TARGET_FILE", "PASS", value), value


def _is_ascii_text(text: str) -> bool:
    return text.isascii()


def _is_ascii_bytes(raw: bytes) -> bool:
    return _decode_ascii_raw(raw) is not None


def _validate_basename(path: Path, issue_id: str) -> RuleResult:
    match = PATCH_RE.fullmatch(path.name)
    if match is None:
        return RuleResult("PATCH_BASENAME", "FAIL", f"invalid_patch_basename:{path.name}")
    actual = match.group("issue")
    if actual != issue_id:
        detail = f"issue_mismatch:expected={issue_id}:actual={actual}:name={path.name}"
        return RuleResult("PATCH_BASENAME", "FAIL", detail)
    return RuleResult("PATCH_BASENAME", "PASS", path.name)


def _snapshot_target(path: Path) -> str | None:
    match = SNAPSHOT_TARGET_RE.fullmatch(path.name)
    return None if match is None else match.group("target")


def _initial_target_source_rule(path: Path) -> tuple[RuleResult, str | None]:
    target = _snapshot_target(path)
    if target is None:
        detail = f"invalid_workspace_snapshot_basename:{path.name}"
        return RuleResult("INITIAL_TARGET_SOURCE", "FAIL", detail), None
    return RuleResult("INITIAL_TARGET_SOURCE", "PASS", target), target


def _repair_overlay_target_rule(path: Path) -> tuple[RuleResult, str | None]:
    raw = _iter_zip_files(path).get(TARGET_FILE_NAME)
    if raw is None:
        return RuleResult("REPAIR_TARGET_SOURCE", "FAIL", "missing_target_file"), None
    value, err = _validate_target_bytes(raw)
    if err is not None:
        return RuleResult("REPAIR_TARGET_SOURCE", "FAIL", err), None
    assert value is not None
    return RuleResult("REPAIR_TARGET_SOURCE", "PASS", value), value


def _target_match_rule(rule_id: str, expected: str, actual: str) -> RuleResult:
    detail = f"expected={expected}:actual={actual}"
    return RuleResult(rule_id, "PASS" if actual == expected else "FAIL", detail)


def _repair_snapshot_consistency_rule(path: Path, overlay_target: str) -> RuleResult:
    snapshot_target = _snapshot_target(path)
    if snapshot_target is None:
        detail = f"snapshot_basename_not_matching_contract:{path.name}"
        return RuleResult("REPAIR_TARGET_SNAPSHOT_CONSISTENCY", "SKIP", detail)
    detail = f"overlay={overlay_target}:snapshot={snapshot_target}"
    status = "PASS" if overlay_target == snapshot_target else "FAIL"
    return RuleResult("REPAIR_TARGET_SNAPSHOT_CONSISTENCY", status, detail)


def _member_repo_path(member: str) -> str | None:
    if not (member.startswith(PATCH_PREFIX) and member.endswith(PATCH_SUFFIX)):
        return None
    raw = member[len(PATCH_PREFIX) : -len(PATCH_SUFFIX)]
    if not raw or "/" in raw or raw.endswith("__"):
        return None
    return raw.replace("__", "/")


def _validate_patch_headers(expected_path: str, text: str) -> str | None:
    saw = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            expected_old = f"a/{expected_path}"
            expected_new = f"b/{expected_path}"
            if len(parts) != 4 or parts[2] != expected_old or parts[3] != expected_new:
                return "diff_git_path_mismatch"
            saw = True
        elif line.startswith(("rename from ", "rename to ")):
            return "rename_not_supported"
        elif line.startswith("--- "):
            saw = True
            if line[4:] not in ("/dev/null", f"a/{expected_path}"):
                return "old_path_mismatch"
        elif line.startswith("+++ "):
            saw = True
            if line[4:] not in ("/dev/null", f"b/{expected_path}"):
                return "new_path_mismatch"
    return None if saw else "missing_patch_headers"


def _check_line_lengths(text: str) -> str | None:
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.startswith("+++"):
            continue
        if line.startswith("+") and len(line[1:]) > 100:
            return f"added_line_too_long:line={idx}:len={len(line[1:])}"
    return None


def _collect_patch_members(
    path: Path,
    issue_id: str,
    commit_message: str,
) -> tuple[list[RuleResult], list[tuple[str, bytes]], list[str], str | None]:
    status = "PASS" if path.suffix == ".zip" else "FAIL"
    results = [RuleResult("PATCH_EXTENSION", status, str(path))]
    if path.suffix != ".zip":
        return results, [], [], None
    names, items = _read_zip(path)
    zmsg = _zip_text(items, "COMMIT_MESSAGE.txt")
    zid = _zip_text(items, "ISSUE_NUMBER.txt")
    results.append(
        RuleResult(
            "COMMIT_MESSAGE_FILE",
            "PASS" if zmsg == commit_message else "FAIL",
            zmsg if zmsg is not None else "missing_or_non_ascii_commit_message",
        )
    )
    results.append(
        RuleResult(
            "ISSUE_NUMBER_FILE",
            "PASS" if zid == issue_id else "FAIL",
            zid if zid is not None else "missing_or_non_ascii_issue_number",
        )
    )
    if zmsg != commit_message or zid != issue_id:
        return results, [], [], None
    target_rule, patch_target = _target_rule(items)
    results.append(target_rule)
    if target_rule.status != "PASS":
        return results, [], [], None
    non_dirs = [name for name in names if not name.endswith("/")]
    members = [
        name for name in non_dirs if name.startswith(PATCH_PREFIX) and name.endswith(PATCH_SUFFIX)
    ]
    if not members:
        return results + [RuleResult("PER_FILE_LAYOUT", "FAIL", "entries=0")], [], [], None
    allowed = {"COMMIT_MESSAGE.txt", "ISSUE_NUMBER.txt", TARGET_FILE_NAME, *members}
    extras = sorted(name for name in non_dirs if name not in allowed)
    if extras:
        detail = f"extra_entries={extras}"
        return results + [RuleResult("PER_FILE_LAYOUT", "FAIL", detail)], [], [], None
    results.append(RuleResult("PER_FILE_LAYOUT", "PASS", f"entries={len(members)}"))
    patch_members: list[tuple[str, bytes]] = []
    decision_paths: list[str] = []
    seen: set[str] = set()
    for member in sorted(members):
        repo_path = _member_repo_path(member)
        if repo_path is None:
            detail = f"invalid_member:{member}"
            return results + [RuleResult("PATCH_MEMBER_PATHS", "FAIL", detail)], [], [], None
        if not _is_ascii_text(member):
            detail = f"non_ascii_member:{member}"
            return results + [RuleResult("PATCH_MEMBER_PATHS", "FAIL", detail)], [], [], None
        if not _is_ascii_text(repo_path):
            detail = f"non_ascii_repo_path:{repo_path}"
            return results + [RuleResult("PATCH_MEMBER_PATHS", "FAIL", detail)], [], [], None
        if repo_path in seen:
            detail = f"duplicate_repo_path:{repo_path}"
            return results + [RuleResult("PATCH_MEMBER_PATHS", "FAIL", detail)], [], [], None
        seen.add(repo_path)
        if not _is_ascii_bytes(items[member]):
            detail = f"{member}:non_ascii_patch_text"
            return results + [RuleResult("PATCH_ASCII", "FAIL", detail)], [], [], None
        text = items[member].decode("ascii")
        header_err = _validate_patch_headers(repo_path, text)
        if header_err is not None:
            detail = f"{member}:{header_err}"
            return results + [RuleResult("PATCH_MEMBER_PATHS", "FAIL", detail)], [], [], None
        if Path(repo_path).suffix in LINE_EXTS:
            line_err = _check_line_lengths(text)
            if line_err is not None:
                detail = f"{member}:{line_err}"
                return results + [RuleResult("LINE_LENGTH", "FAIL", detail)], [], [], None
        patch_members.append((member, items[member]))
        decision_paths.append(repo_path)
    results.append(RuleResult("PATCH_MEMBER_PATHS", "PASS", f"paths={len(decision_paths)}"))
    results.append(RuleResult("PATCH_ASCII", "PASS", "patch_members_ascii_only"))
    results.append(RuleResult("LINE_LENGTH", "PASS", "py_js_added_lines<=100"))
    return results, patch_members, decision_paths, patch_target


def _docs_gate(decision_paths: list[str]) -> RuleResult:
    if not any(path.startswith(("src/", "plugins/", "docs/")) for path in decision_paths):
        return RuleResult("DOCS_GATE", "PASS", "not_triggered")
    if any(path == "docs/changes.md" for path in decision_paths):
        return RuleResult("DOCS_GATE", "FAIL", "direct_changes_md_edit")
    has_fragment = any(path.startswith("docs/change_fragments/") for path in decision_paths)
    detail = "fragment_present" if has_fragment else "missing_change_fragment"
    return RuleResult("DOCS_GATE", "PASS" if has_fragment else "FAIL", detail)


def _iter_zip_files(path: Path) -> dict[str, bytes]:
    names, items = _read_zip(path)
    keep = {
        name: items[name]
        for name in names
        if not name.endswith("/") and not name.startswith(".am_patch/")
    }
    keep.pop("COMMIT_MESSAGE.txt", None)
    keep.pop("ISSUE_NUMBER.txt", None)
    return keep


def _authority_files(
    args: argparse.Namespace,
    decision_paths: list[str],
) -> tuple[dict[str, bytes], str]:
    if not args.repair_overlay:
        snapshot = _iter_zip_files(Path(args.workspace_snapshot))
        baseline = {path: snapshot[path] for path in decision_paths if path in snapshot}
        return baseline, "initial"
    overlay = _iter_zip_files(Path(args.repair_overlay))
    baseline = {path: overlay[path] for path in decision_paths if path in overlay}
    if not args.supplemental_file:
        missing = [path for path in decision_paths if path not in baseline]
        if missing:
            raise ValidationError(f"repair_requires_supplemental_file:{missing}")
        return baseline, "overlay-only"
    if not args.workspace_snapshot:
        raise ValidationError("supplemental_requires_workspace_snapshot")
    snapshot = _iter_zip_files(Path(args.workspace_snapshot))
    allowed = set(args.supplemental_file)
    undeclared = [path for path in decision_paths if path not in baseline and path not in allowed]
    if undeclared:
        raise ValidationError(f"repair_requires_supplemental_file:{undeclared}")
    missing = [path for path in allowed if path not in snapshot]
    if missing:
        raise ValidationError(f"supplemental_file_missing_in_snapshot:{sorted(missing)}")
    for path in decision_paths:
        if path in allowed and path in snapshot:
            baseline[path] = snapshot[path]
    return baseline, "overlay+supplemental"


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)


def _apply_patches(root: Path, patch_members: list[tuple[str, bytes]]) -> list[RuleResult]:
    out: list[RuleResult] = []
    for member, data in patch_members:
        patch_file = root / ".pm_validator" / Path(member).name
        patch_file.parent.mkdir(parents=True, exist_ok=True)
        patch_file.write_bytes(data)
        proc = _run(["git", "apply", "--check", str(patch_file)], cwd=root)
        detail = (
            "ok" if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip() or "fail")
        )
        status = "PASS" if proc.returncode == 0 else "FAIL"
        out.append(RuleResult(f"GIT_APPLY_CHECK:{member}", status, detail))
        if proc.returncode != 0:
            return out
        apply_proc = _run(["git", "apply", str(patch_file)], cwd=root)
        if apply_proc.returncode != 0:
            detail = apply_proc.stderr.strip() or apply_proc.stdout.strip() or member
            raise ValidationError(detail)
    return out


def _compile_python(root: Path, decision_paths: list[str]) -> RuleResult:
    targets = [
        str(root / path)
        for path in decision_paths
        if path.endswith(".py") and (root / path).exists()
    ]
    if not targets:
        return RuleResult("PY_COMPILE", "SKIP", "no_modified_python_files")
    proc = _run([sys.executable, "-m", "compileall", "-q", *targets], cwd=root)
    detail = f"files={len(targets)}"
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "compileall_failed"
    return RuleResult("PY_COMPILE", "PASS" if proc.returncode == 0 else "FAIL", detail)


def _check_js(root: Path, decision_paths: list[str]) -> RuleResult:
    targets = [
        str(root / path)
        for path in decision_paths
        if Path(path).suffix in JS_EXTS and (root / path).exists()
    ]
    if not targets:
        return RuleResult("JS_SYNTAX", "SKIP", "no_modified_javascript_files")
    node = shutil.which("node")
    if node is None:
        return RuleResult("JS_SYNTAX", "SKIP", "node_not_found")
    for target in targets:
        proc = _run([node, "--check", target], cwd=root)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or target
            return RuleResult("JS_SYNTAX", "FAIL", detail)
    return RuleResult("JS_SYNTAX", "PASS", f"files={len(targets)}")


def _count_loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _parse_tree(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _count_exports(tree: ast.AST) -> int:
    if not isinstance(tree, ast.Module):
        return 0
    total = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, "name", "")
            if name and not name.startswith("_"):
                total += 1
    return total


def _norm_relpath(path: str) -> str:
    text = str(path).replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _area(path: str) -> str:
    parts = PurePosixPath(path).parts
    first = parts[0] if parts else ""
    if first == "plugins" and len(parts) >= 2:
        return f"plugins.{parts[1]}"
    return first if first in AREAS else "other"


def _module_for_relpath(relpath: str) -> str | None:
    rp = _norm_relpath(relpath)
    if rp.startswith("src/audiomason/") and rp.endswith(".py"):
        sub = rp[len("src/") : -3].replace("/", ".")
        return sub[: -len(".__init__")] if sub.endswith(".__init__") else sub
    if rp.startswith("scripts/am_patch/") and rp.endswith(".py"):
        sub = rp[len("scripts/") : -3].replace("/", ".")
        return sub[: -len(".__init__")] if sub.endswith(".__init__") else sub
    if rp.startswith("plugins/") and rp.endswith(".py"):
        parts = rp.split("/")
        if len(parts) >= 2:
            name = parts[1]
            rest = "/".join(parts[2:])
            if rest == "__init__.py":
                return f"plugins.{name}"
            if rest.endswith(".py"):
                rest = rest[:-3]
            rest = rest.replace("/", ".")
            return f"plugins.{name}.{rest}" if rest else f"plugins.{name}"
    if rp.startswith("tests/") and rp.endswith(".py"):
        sub = rp[:-3].replace("/", ".")
        return sub[: -len(".__init__")] if sub.endswith(".__init__") else sub
    return None


def _module_to_rel_hint(mod: str) -> str | None:
    text = str(mod).strip().strip(".")
    if not text:
        return None
    parts = text.split(".")
    root = parts[0]
    if root == "audiomason":
        rest = "/".join(parts[1:])
        return f"src/audiomason/{rest}.py" if rest else "src/audiomason/__init__.py"
    if root == "am_patch":
        rest = "/".join(parts[1:])
        return f"scripts/am_patch/{rest}.py" if rest else "scripts/am_patch/__init__.py"
    if root == "plugins" and len(parts) >= 2:
        name = parts[1]
        rest = "/".join(parts[2:])
        return f"plugins/{name}/{rest}.py" if rest else f"plugins/{name}/__init__.py"
    if root == "tests":
        rest = "/".join(parts[1:])
        return f"tests/{rest}.py" if rest else "tests/__init__.py"
    return None


def _area_for_module(mod: str) -> str:
    hint = _module_to_rel_hint(mod)
    return "other" if hint is None else _area(hint)


def _iter_import_modules(tree: ast.AST, *, current_module: str | None) -> list[str]:
    modules: list[str] = []

    def add(mod: str) -> None:
        text = str(mod).strip().strip(".")
        if text and text not in modules:
            modules.append(text)

    def resolve_relative(level: int, mod: str | None) -> str | None:
        if not current_module or level <= 0:
            return None
        parts = current_module.split(".")
        if parts:
            parts = parts[:-1]
        up = max(0, min(level - 1, len(parts)))
        base = parts[: len(parts) - up]
        if mod:
            text = str(mod).strip(".")
            if not text:
                return ".".join(base) or None
            return ".".join([*base, text]) if base else text
        return ".".join(base) or None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                resolved = resolve_relative(node.level, node.module)
                if resolved:
                    add(resolved)
                continue
            if node.module:
                add(node.module)

    return modules


def _count_js_exports(text: str) -> int:
    export_lines = len(_RE_EXPORT_LINE.findall(text))
    module_exports = text.count("module.exports")
    dotted = {match.group(1) for match in _RE_EXPORTS_DOT.finditer(text)}
    return export_lines + module_exports + len(dotted)


def _iter_js_specs(text: str) -> list[str]:
    specs: list[str] = []

    def add(spec: str) -> None:
        value = str(spec).strip()
        if value and value not in specs:
            specs.append(value)

    for rx in (_RE_IMPORT_FROM, _RE_EXPORT_FROM, _RE_REQUIRE):
        for match in rx.finditer(text):
            add(match.group(1))
    return specs


def _resolve_js_spec(relpath: str, spec: str, known_paths: set[str]) -> str | None:
    value = str(spec).strip()
    if not (value.startswith("./") or value.startswith("../")):
        return None
    for sep in ("?", "#"):
        if sep in value:
            value = value.split(sep, 1)[0]
    base = PurePosixPath(_norm_relpath(relpath)).parent
    candidate = _norm_relpath(str(base / value))
    options = [candidate]
    if not any(candidate.endswith(ext) for ext in JS_EXTS):
        options.append(candidate + ".js")
        options.append(_norm_relpath(candidate + "/index.js"))
    for option in options:
        if option in known_paths:
            return option
    return options[0] if options else None


def _py_metrics(relpath: str, text: str) -> MonolithMetrics:
    tree = _parse_tree(text)
    if tree is None:
        return MonolithMetrics(loc=_count_loc(text), internal_imports=0, exports=0)
    current_module = _module_for_relpath(relpath)
    internal_mods = {
        mod
        for mod in _iter_import_modules(tree, current_module=current_module)
        if _area_for_module(mod) != "other"
    }
    return MonolithMetrics(
        loc=_count_loc(text),
        internal_imports=len(internal_mods),
        exports=_count_exports(tree),
    )


def _js_metrics(relpath: str, text: str, known_paths: set[str]) -> MonolithMetrics:
    internal_targets = {
        target
        for spec in _iter_js_specs(text)
        if (target := _resolve_js_spec(relpath, spec, known_paths)) is not None
        and _area(target) != "other"
    }
    return MonolithMetrics(
        loc=_count_loc(text),
        internal_imports=len(internal_targets),
        exports=_count_js_exports(text),
    )


def _metrics_for_path(relpath: str, text: str, known_paths: set[str]) -> MonolithMetrics:
    suffix = Path(relpath).suffix
    if suffix == ".py":
        return _py_metrics(relpath, text)
    if suffix in JS_EXTS:
        return _js_metrics(relpath, text, known_paths)
    return MonolithMetrics(loc=_count_loc(text), internal_imports=0, exports=0)


def _resolve_fan_target(mod: str, module_to_rel: dict[str, str]) -> str | None:
    current = str(mod).strip().strip(".")
    if not current:
        return None
    while True:
        if current in module_to_rel:
            return module_to_rel[current]
        if "." not in current:
            return None
        current = current.rsplit(".", 1)[0]


def _fan_graph(texts: dict[str, str], relpaths: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    module_to_rel = {
        module: relpath
        for relpath in relpaths
        if (module := _module_for_relpath(relpath)) is not None
    }
    known_paths = set(relpaths)
    edges: dict[str, set[str]] = {relpath: set() for relpath in relpaths}
    for relpath in relpaths:
        text = texts.get(relpath)
        if text is None:
            continue
        if relpath.endswith(".py"):
            tree = _parse_tree(text)
            if tree is None:
                continue
            current_module = _module_for_relpath(relpath)
            for mod in _iter_import_modules(tree, current_module=current_module):
                target = _resolve_fan_target(mod, module_to_rel)
                if target and target != relpath:
                    edges[relpath].add(target)
        elif Path(relpath).suffix in JS_EXTS:
            for spec in _iter_js_specs(text):
                target = _resolve_js_spec(relpath, spec, known_paths)
                if target in edges and target != relpath:
                    edges[relpath].add(target)
    fanout = {relpath: len(edges[relpath]) for relpath in relpaths}
    fanin = {relpath: 0 for relpath in relpaths}
    for targets in edges.values():
        for target in targets:
            fanin[target] = fanin.get(target, 0) + 1
    return fanin, fanout


def _hub_failure(
    *,
    path: str,
    fanin_delta: int,
    fanout_delta: int,
    loc_delta: int,
    exports_delta: int,
) -> RuleResult | None:
    if fanin_delta >= HUB_FANIN_DELTA and exports_delta >= HUB_EXPORTS_DELTA_MIN:
        detail = f"hub_signal_fanin:{path}:fanin_delta={fanin_delta}:exports_delta={exports_delta}"
        return RuleResult("MONOLITH", "FAIL", detail)
    if fanout_delta >= HUB_FANOUT_DELTA and loc_delta >= HUB_LOC_DELTA_MIN:
        detail = f"hub_signal_fanout:{path}:fanout_delta={fanout_delta}:loc_delta={loc_delta}"
        return RuleResult("MONOLITH", "FAIL", detail)
    return None


def _monolith(root: Path, baseline: dict[str, bytes], decision_paths: list[str]) -> RuleResult:
    targets = [
        path for path in decision_paths if Path(path).suffix in LINE_EXTS and (root / path).exists()
    ]
    if not targets:
        return RuleResult("MONOLITH", "SKIP", "no_modified_python_or_javascript_files")
    areas = {_area(path) for path in targets}
    if len(areas) >= 3:
        return RuleResult("MONOLITH", "FAIL", f"cross_area_threshold:areas={sorted(areas)}")

    new_texts = {path: (root / path).read_text(encoding="utf-8") for path in targets}
    old_texts = {path: baseline[path].decode("utf-8") for path in targets if path in baseline}
    known_paths = set(targets)
    new_fanin, new_fanout = _fan_graph(new_texts, targets)
    old_fanin, old_fanout = _fan_graph(old_texts, targets)

    for path in targets:
        posix = PurePosixPath(path)
        has_bad_dir = any(part in CATCHALL_DIRS for part in posix.parts[:-1])
        if posix.name in CATCHALL_BASENAMES or has_bad_dir:
            return RuleResult("MONOLITH", "FAIL", f"catchall_forbidden:{path}")

        new_metrics = _metrics_for_path(path, new_texts[path], known_paths)
        fanin_delta = new_fanin.get(path, 0) - old_fanin.get(path, 0)
        fanout_delta = new_fanout.get(path, 0) - old_fanout.get(path, 0)
        old_text = old_texts.get(path)
        if old_text is None:
            if (
                new_metrics.loc > 400
                or new_metrics.exports > 25
                or new_metrics.internal_imports > 15
            ):
                return RuleResult("MONOLITH", "FAIL", f"new_file_limits:{path}")
            hub_failure = _hub_failure(
                path=path,
                fanin_delta=fanin_delta,
                fanout_delta=fanout_delta,
                loc_delta=new_metrics.loc,
                exports_delta=new_metrics.exports,
            )
            if hub_failure is not None:
                return hub_failure
            continue

        old_metrics = _metrics_for_path(path, old_text, known_paths)
        loc_delta = new_metrics.loc - old_metrics.loc
        imports_delta = new_metrics.internal_imports - old_metrics.internal_imports
        exports_delta = new_metrics.exports - old_metrics.exports
        grew = any(value > 0 for value in (loc_delta, imports_delta, exports_delta))
        tier = None
        if new_metrics.loc >= 1300:
            tier = "huge"
        elif new_metrics.loc >= 900:
            tier = "large"
        if tier == "huge" and grew:
            return RuleResult("MONOLITH", "FAIL", f"huge_file_growth:{path}")
        if tier == "large" and (loc_delta > 20 or exports_delta > 2 or imports_delta > 1):
            return RuleResult("MONOLITH", "FAIL", f"large_file_growth:{path}")
        hub_failure = _hub_failure(
            path=path,
            fanin_delta=fanin_delta,
            fanout_delta=fanout_delta,
            loc_delta=loc_delta,
            exports_delta=exports_delta,
        )
        if hub_failure is not None:
            return hub_failure
    return RuleResult("MONOLITH", "PASS", "gate_passed")


INSTRUCTIONS_REQUIRED = {"HANDOFF.md", "constraint_pack.json", "hash_pack.txt"}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_BINDING_TYPES = {"resolver_contract", "constraint_pack"}
BINDING_REQUIRED_FIELDS = (
    "id",
    "binding_type",
    "match",
    "symbol_role",
    "authoritative_semantics",
    "peer_renderers",
    "shared_contract_refs",
    "downstream_consumers",
    "exception_state_refs",
    "required_wiring",
    "forbidden",
    "required_validation",
    "verification_mode",
    "verification_method",
    "semantic_group",
    "conflict_policy",
)
AUTHORITY_ONLY_PATHS = {
    "governance/AUDIOMASON2_PROJECT_CONTRACT.md",
    "governance/instructions_project_chats.txt",
    "governance/instructions_implementation_chats.txt",
    "governance/am_patch_instructions.md",
    "governance/pm_spec.md",
    "governance/governance.jsonl",
    "governance/specification.jsonl",
}

if TYPE_CHECKING:
    PackRulesFn = Callable[
        [argparse.Namespace, Path, list[str], list[str]],
        tuple[list[RuleResult], object | None],
    ]
else:
    PackRulesFn = object


def _load_pack_rules() -> PackRulesFn:
    module_name = "pm_validator_pack_contract"
    if __package__:
        module_name = f"{__package__}.pm_validator_pack_contract"
    module = import_module(module_name)
    return cast(PackRulesFn, module._pack_rules)


def _run_pack_rules(
    args: argparse.Namespace,
    instructions_path: Path,
    decision_paths: list[str],
    patch_member_names: list[str],
) -> tuple[list[RuleResult], object | None]:
    return _load_pack_rules()(args, instructions_path, decision_paths, patch_member_names)


def _format(results: list[RuleResult]) -> str:
    hard_fail_statuses = {"FAIL", "UNVERIFIED_ENVIRONMENT", "MANUAL_REVIEW_REQUIRED"}
    overall = "FAIL" if any(item.status in hard_fail_statuses for item in results) else "PASS"
    lines = [f"RESULT: {overall}"]
    lines.extend(f"RULE {item.rule_id}: {item.status} - {item.detail}" for item in results)
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-file PM validator for patch artifacts.")
    parser.add_argument("issue_id")
    parser.add_argument("commit_message")
    parser.add_argument("patch")
    parser.add_argument("instructions_zip")
    parser.add_argument(
        "--workspace-snapshot",
        help="Workspace snapshot zip for initial mode or supplemental files.",
    )
    parser.add_argument(
        "--repair-overlay",
        help="patched_issue*.zip overlay for repair mode.",
    )
    parser.add_argument(
        "--supplemental-file",
        action="append",
        default=[],
        help="Repeat per repo-relative file path allowed during repair escalation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        if not Path(args.patch).is_file():
            raise ValidationError("patch_not_found")
        if not Path(args.instructions_zip).is_file():
            raise ValidationError("instructions_zip_not_found")
        if args.repair_overlay:
            if not Path(args.repair_overlay).is_file():
                raise ValidationError("repair_overlay_not_found")
        elif not args.workspace_snapshot:
            raise ValidationError("workspace_snapshot_required_for_initial_mode")
        if args.workspace_snapshot and not Path(args.workspace_snapshot).is_file():
            raise ValidationError("workspace_snapshot_not_found")
        if args.supplemental_file and not args.repair_overlay:
            raise ValidationError("supplemental_file_requires_repair_mode")
        patch_path = Path(args.patch).resolve()
        instructions_path = Path(args.instructions_zip).resolve()
        results = [_validate_basename(patch_path, args.issue_id)]
        more, patch_members, decision_paths, patch_target = _collect_patch_members(
            patch_path,
            args.issue_id,
            args.commit_message,
        )
        results.extend(more)
        if any(item.status == "FAIL" for item in results):
            sys.stdout.write(_format(results))
            return 1
        if patch_target is None:
            raise ValidationError("patch_target_missing_after_validation")
        if args.repair_overlay:
            repair_rule, overlay_target = _repair_overlay_target_rule(Path(args.repair_overlay))
            results.append(repair_rule)
            if overlay_target is not None:
                results.append(
                    _target_match_rule("REPAIR_TARGET_MATCH", overlay_target, patch_target)
                )
                if args.workspace_snapshot:
                    results.append(
                        _repair_snapshot_consistency_rule(
                            Path(args.workspace_snapshot), overlay_target
                        )
                    )
        else:
            initial_rule, initial_target = _initial_target_source_rule(
                Path(args.workspace_snapshot)
            )
            results.append(initial_rule)
            if initial_target is not None:
                results.append(
                    _target_match_rule("INITIAL_TARGET_MATCH", initial_target, patch_target)
                )
        if any(item.status == "FAIL" for item in results):
            sys.stdout.write(_format(results))
            return 1
        results.append(_docs_gate(decision_paths))
        patch_member_names = [member for member, _data in patch_members]
        pack_results, _pack = _run_pack_rules(
            args, instructions_path, decision_paths, patch_member_names
        )
        results.extend(pack_results)
        if any(
            item.status in {"FAIL", "UNVERIFIED_ENVIRONMENT", "MANUAL_REVIEW_REQUIRED"}
            for item in results
        ):
            sys.stdout.write(_format(results))
            return 1
        baseline, _mode = _authority_files(args, decision_paths)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_tree(root, baseline)
            results.extend(_apply_patches(root, patch_members))
            if any(item.status == "FAIL" for item in results):
                sys.stdout.write(_format(results))
                return 1
            results.extend(
                [
                    _compile_python(root, decision_paths),
                    _check_js(root, decision_paths),
                    _monolith(root, baseline, decision_paths),
                ]
            )
        sys.stdout.write(_format(results))
        return (
            0
            if all(
                item.status not in {"FAIL", "UNVERIFIED_ENVIRONMENT", "MANUAL_REVIEW_REQUIRED"}
                for item in results
            )
            else 1
        )
    except ValidationError as exc:
        sys.stdout.write(_format([RuleResult("VALIDATION_ERROR", "FAIL", str(exc))]))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
