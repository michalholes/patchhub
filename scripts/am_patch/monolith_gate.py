from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from . import monolith_js_metrics
from .errors import RunnerError
from .log import Logger


@dataclass(frozen=True)
class MonolithAreas:
    rel_prefix: str
    area: str
    dynamic: str | None = None


@dataclass(frozen=True)
class FileMetrics:
    loc: int
    exports: int
    internal_imports: int
    distinct_areas: int
    fanin: int | None
    fanout: int | None
    parse_ok: bool


@dataclass(frozen=True)
class Violation:
    rule_id: str
    relpath: str
    message: str
    severity: str  # FAIL|WARN|REPORT


def _norm_relpath(p: str) -> str:
    s = str(p).replace("\\", "/").strip()
    if s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _norm_extensions(exts: list[str]) -> list[str]:
    out: list[str] = []
    for item in exts:
        s = str(item).strip()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        s = s.lower()
        if s not in out:
            out.append(s)
    return out


def _has_allowed_suffix(relpath: str, exts: list[str]) -> bool:
    rp = _norm_relpath(relpath).lower()
    return any(rp.endswith(ext) for ext in exts)


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
    n = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, "name", "")
            if name and not name.startswith("_"):
                n += 1
    return n


def _iter_import_modules(tree: ast.AST, *, current_module: str | None) -> list[str]:
    out: list[str] = []

    def add(mod: str) -> None:
        s = str(mod).strip().strip(".")
        if s and s not in out:
            out.append(s)

    def resolve_relative(level: int, mod: str | None) -> str | None:
        if not current_module or level <= 0:
            return None
        parts = current_module.split(".")
        # current_module includes the leaf module; treat parent as package for relative imports.
        if parts:
            parts = parts[:-1]
        up = max(0, min(level - 1, len(parts)))
        base = parts[: len(parts) - up]
        if mod:
            m = str(mod).strip(".")
            if not m:
                return ".".join(base) or None
            return ".".join([*base, m]) if base else m
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

    return out


def _areas_from_policy(
    prefixes: list[str],
    names: list[str],
    dynamic: list[str],
) -> list[MonolithAreas]:
    out: list[MonolithAreas] = []
    for i in range(len(prefixes)):
        prefix = _norm_relpath(prefixes[i])
        area = str(names[i]).strip()
        dyn_s = str(dynamic[i]).strip()
        dyn = None if dyn_s == "" else dyn_s
        if not prefix or not area:
            continue
        out.append(MonolithAreas(rel_prefix=prefix.rstrip("/") + "/", area=area, dynamic=dyn))
    return out


def area_for_relpath(relpath: str, areas: Sequence[MonolithAreas]) -> str:
    rp = _norm_relpath(relpath)
    rp2 = rp + "/" if not rp.endswith("/") else rp
    for a in areas:
        if rp2.startswith(a.rel_prefix):
            if a.dynamic == "plugins.<name>":
                # relpath: plugins/<name>/...
                parts = rp.split("/")
                if len(parts) >= 2 and parts[0] == "plugins":
                    return f"plugins.{parts[1]}"
            return a.area
    return "other"


def _module_for_relpath(relpath: str) -> str | None:
    rp = _norm_relpath(relpath)
    if rp.startswith("src/audiomason/") and rp.endswith(".py"):
        sub = rp[len("src/") : -3].replace("/", ".")
        if sub.endswith(".__init__"):
            sub = sub[: -len(".__init__")]
        return sub
    if rp.startswith("scripts/am_patch/") and rp.endswith(".py"):
        sub = rp[len("scripts/") : -3].replace("/", ".")
        if sub.endswith(".__init__"):
            sub = sub[: -len(".__init__")]
        return sub
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
        if sub.endswith(".__init__"):
            sub = sub[: -len(".__init__")]
        return sub
    return None


def _module_to_rel_hint(mod: str) -> str | None:
    s = str(mod).strip().strip(".")
    if not s:
        return None
    parts = s.split(".")
    if not parts:
        return None
    root = parts[0]
    if root == "audiomason":
        rest = "/".join(parts[1:])
        return ("src/audiomason/" + rest + ".py") if rest else "src/audiomason/__init__.py"
    if root == "am_patch":
        rest = "/".join(parts[1:])
        return ("scripts/am_patch/" + rest + ".py") if rest else "scripts/am_patch/__init__.py"
    if root == "plugins" and len(parts) >= 2:
        name = parts[1]
        rest = "/".join(parts[2:])
        return (
            ("plugins/" + name + "/" + rest + ".py")
            if rest
            else ("plugins/" + name + "/__init__.py")
        )
    if root == "tests":
        rest = "/".join(parts[1:])
        return ("tests/" + rest + ".py") if rest else "tests/__init__.py"
    return None


def _area_for_module(mod: str, areas: Sequence[MonolithAreas]) -> str:
    hint = _module_to_rel_hint(mod)
    if not hint:
        return "other"
    # Normalize to a directory hint for area prefix matching.
    area = area_for_relpath(hint, areas)
    if area != "other":
        return area
    # Also allow matching by package prefix (directory) when module points to a submodule file.
    d = _norm_relpath(str(Path(hint).parent))
    if d:
        area2 = area_for_relpath(d + "/x.py", areas)
        if area2 != "other":
            return area2
    return "other"


def _is_catchall_new_file(
    relpath: str,
    *,
    basenames: list[str],
    dirs: list[str],
    allowlist: list[str],
) -> bool:
    rp = _norm_relpath(relpath)
    if rp in set(_norm_relpath(x) for x in allowlist):
        return False
    base = Path(rp).name
    if base in set(basenames):
        return True
    parts = [p for p in rp.split("/") if p]
    dirs_set = set(dirs)
    return bool(any(seg in dirs_set for seg in parts[:-1]))


def _tier(loc: int, *, large: int, huge: int) -> str:
    if loc >= huge:
        return "huge"
    if loc >= large:
        return "large"
    return "normal"


def _scan_candidates(
    cwd: Path,
    *,
    decision_paths: list[str],
    scope: str,
    areas: Sequence[MonolithAreas],
    extensions: list[str],
) -> list[str]:
    exts = _norm_extensions(extensions)
    if scope == "patch":
        out: list[str] = []
        for p in decision_paths:
            rp = _norm_relpath(p)
            if not _has_allowed_suffix(rp, exts):
                continue
            if (cwd / rp).exists() and rp not in out:
                out.append(rp)
        out.sort()
        return out

    if scope == "workspace":
        prefixes = [a.rel_prefix for a in areas]
        out_set: set[str] = set()
        for pref in prefixes:
            root = cwd / pref.rstrip("/")
            if not root.exists():
                continue
            for ext in exts:
                for f in sorted(root.rglob(f"*{ext}")):
                    if f.is_file():
                        out_set.add(_norm_relpath(str(f.relative_to(cwd))))
        out = sorted(out_set)
        return out

    raise RunnerError("GATES", "MONOLITH", f"invalid gate_monolith_scan_scope={scope!r}")


def _fan_graph(
    text_root: Path,
    *,
    cwd: Path,
    repo_root: Path,
    relpaths: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    # Build fanin/fanout based on internal imports among relpaths.
    module_to_rel: dict[str, str] = {}
    rel_to_module: dict[str, str] = {}
    for rp in relpaths:
        m = _module_for_relpath(rp)
        if m:
            module_to_rel[m] = rp
            rel_to_module[rp] = m

    def resolve_target(mod: str) -> str | None:
        s = str(mod).strip().strip(".")
        if not s:
            return None
        cur = s
        while True:
            if cur in module_to_rel:
                return module_to_rel[cur]
            if "." not in cur:
                return None
            cur = cur.rsplit(".", 1)[0]

    edges: dict[str, set[str]] = {rp: set[str]() for rp in relpaths}
    for rp in relpaths:
        path = text_root / rp
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if rp.endswith(".py"):
            tree = _parse_tree(text)
            if tree is None:
                continue
            cur_mod = rel_to_module.get(rp)
            for mod in _iter_import_modules(tree, current_module=cur_mod):
                tgt = resolve_target(mod)
                if tgt and tgt != rp:
                    edges[rp].add(tgt)
        elif rp.endswith(".js"):
            for tgt in monolith_js_metrics.js_internal_import_targets(
                relpath=rp,
                text=text,
                cwd=cwd,
                repo_root=repo_root,
            ):
                if tgt in edges and tgt != rp:
                    edges[rp].add(tgt)

    fanout: dict[str, int] = {rp: len(edges[rp]) for rp in relpaths}
    fanin: dict[str, int] = {rp: 0 for rp in relpaths}
    for _src, tgts in edges.items():
        for tgt in tgts:
            fanin[tgt] = fanin.get(tgt, 0) + 1

    return fanin, fanout


def _analyze_file(
    *,
    relpath: str,
    text: str,
    cwd: Path,
    repo_root: Path,
    areas: Sequence[MonolithAreas],
    fanin: int | None,
    fanout: int | None,
    compute_fanin: bool,
) -> FileMetrics:
    if relpath.endswith(".js"):
        from .monolith_js_metrics import js_metrics

        js_m = js_metrics(
            relpath=relpath,
            new_text=text,
            cwd=cwd,
            repo_root=repo_root,
            areas=areas,
            compute_fanin=compute_fanin,
        )
        return replace(js_m, fanin=fanin, fanout=fanout)

    tree = _parse_tree(text)
    if tree is None:
        return FileMetrics(
            loc=_count_loc(text),
            exports=0,
            internal_imports=0,
            distinct_areas=0,
            fanin=fanin,
            fanout=fanout,
            parse_ok=False,
        )

    exports = _count_exports(tree)
    cur_mod = _module_for_relpath(relpath)
    mods = _iter_import_modules(tree, current_module=cur_mod)

    internal_mods: set[str] = set()
    imported_areas: set[str] = set()
    for mod in mods:
        area = _area_for_module(mod, areas)
        if area == "other":
            continue
        internal_mods.add(mod)
        imported_areas.add(area)

    return FileMetrics(
        loc=_count_loc(text),
        exports=exports,
        internal_imports=len(internal_mods),
        distinct_areas=len(imported_areas),
        fanin=fanin,
        fanout=fanout,
        parse_ok=True,
    )


def run_monolith_gate(
    logger: Logger,
    cwd: Path,
    *,
    repo_root: Path,
    decision_paths: list[str],
    gate_monolith_mode: str,
    gate_monolith_scan_scope: str,
    gate_monolith_extensions: list[str] | None = None,
    gate_monolith_compute_fanin: bool,
    gate_monolith_on_parse_error: str,
    gate_monolith_areas_prefixes: list[str],
    gate_monolith_areas_names: list[str],
    gate_monolith_areas_dynamic: list[str],
    gate_monolith_large_loc: int,
    gate_monolith_huge_loc: int,
    gate_monolith_large_allow_loc_increase: int,
    gate_monolith_huge_allow_loc_increase: int,
    gate_monolith_large_allow_exports_delta: int,
    gate_monolith_huge_allow_exports_delta: int,
    gate_monolith_large_allow_imports_delta: int,
    gate_monolith_huge_allow_imports_delta: int,
    gate_monolith_new_file_max_loc: int,
    gate_monolith_new_file_max_exports: int,
    gate_monolith_new_file_max_imports: int,
    gate_monolith_hub_fanin_delta: int,
    gate_monolith_hub_fanout_delta: int,
    gate_monolith_hub_exports_delta_min: int,
    gate_monolith_hub_loc_delta_min: int,
    gate_monolith_crossarea_min_distinct_areas: int,
    gate_monolith_catchall_basenames: list[str],
    gate_monolith_catchall_dirs: list[str],
    gate_monolith_catchall_allowlist: list[str],
) -> bool:
    if gate_monolith_extensions is None:
        gate_monolith_extensions = [".py", ".js"]

    if gate_monolith_mode not in ("strict", "warn_only", "report_only"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            (
                "invalid gate_monolith_mode="
                f"{gate_monolith_mode!r}; allowed: strict|warn_only|report_only"
            ),
        )
    if gate_monolith_on_parse_error not in ("fail", "warn"):
        raise RunnerError(
            "CONFIG",
            "INVALID",
            (
                "invalid gate_monolith_on_parse_error="
                f"{gate_monolith_on_parse_error!r}; allowed: fail|warn"
            ),
        )

    areas = _areas_from_policy(
        gate_monolith_areas_prefixes,
        gate_monolith_areas_names,
        gate_monolith_areas_dynamic,
    )
    candidates = _scan_candidates(
        cwd,
        decision_paths=decision_paths,
        scope=gate_monolith_scan_scope,
        areas=areas,
        extensions=gate_monolith_extensions,
    )

    logger.section("GATE: MONOLITH")
    logger.line("gate_monolith_mode=" + gate_monolith_mode)
    logger.line("gate_monolith_scan_scope=" + gate_monolith_scan_scope)
    logger.line("gate_monolith_extensions=" + str(_norm_extensions(gate_monolith_extensions)))
    logger.line("gate_monolith_candidates=" + str(len(candidates)))

    files_scanned = len(candidates)
    files_new = 0
    parse_errors_new = 0
    parse_errors_old = 0
    loc_total_new = 0
    loc_total_old = 0
    imports_total_new = 0
    imports_total_old = 0
    exports_total_new = 0
    exports_total_old = 0
    fanin_delta_max: int | None = 0 if gate_monolith_compute_fanin else None
    fanout_delta_max: int | None = 0 if gate_monolith_compute_fanin else None

    fanin_map: dict[str, int] = {}
    fanout_map: dict[str, int] = {}
    fanin_map_old: dict[str, int] = {}
    fanout_map_old: dict[str, int] = {}
    if gate_monolith_compute_fanin and candidates:
        fanin_map, fanout_map = _fan_graph(
            cwd,
            cwd=cwd,
            repo_root=repo_root,
            relpaths=candidates,
        )
        fanin_map_old, fanout_map_old = _fan_graph(
            repo_root,
            cwd=cwd,
            repo_root=repo_root,
            relpaths=candidates,
        )

    violations: list[Violation] = []

    def add(rule_id: str, relpath: str, msg: str, sev: str) -> None:
        violations.append(Violation(rule_id=rule_id, relpath=relpath, message=msg, severity=sev))

    for rp in candidates:
        new_path = cwd / rp
        old_path = repo_root / rp
        is_new_file = not old_path.exists()

        if is_new_file:
            files_new += 1

        new_text = new_path.read_text(encoding="utf-8")
        old_text = old_path.read_text(encoding="utf-8") if old_path.exists() else ""

        fanin_new = fanin_map.get(rp) if gate_monolith_compute_fanin else None
        fanout_new = fanout_map.get(rp) if gate_monolith_compute_fanin else None
        fanin_old = fanin_map_old.get(rp) if gate_monolith_compute_fanin else None
        fanout_old = fanout_map_old.get(rp) if gate_monolith_compute_fanin else None

        new_m = _analyze_file(
            relpath=rp,
            text=new_text,
            cwd=cwd,
            repo_root=repo_root,
            areas=areas,
            fanin=fanin_new,
            fanout=fanout_new,
            compute_fanin=gate_monolith_compute_fanin,
        )

        old_m = _analyze_file(
            relpath=rp,
            text=old_text,
            cwd=cwd,
            repo_root=repo_root,
            areas=areas,
            fanin=None,
            fanout=None,
            compute_fanin=gate_monolith_compute_fanin,
        )

        loc_total_new += new_m.loc
        loc_total_old += old_m.loc
        imports_total_new += new_m.internal_imports
        imports_total_old += old_m.internal_imports
        exports_total_new += new_m.exports
        exports_total_old += old_m.exports

        if not new_m.parse_ok:
            parse_errors_new += 1
        if old_path.exists() and not old_m.parse_ok:
            parse_errors_old += 1

        if gate_monolith_compute_fanin:
            old_fanin = fanin_map_old.get(rp, 0)
            new_fanin = fanin_map.get(rp, 0)
            old_fanout = fanout_map_old.get(rp, 0)
            new_fanout = fanout_map.get(rp, 0)

            fanin_delta = new_fanin - old_fanin
            fanout_delta = new_fanout - old_fanout
            if fanin_delta_max is not None and fanin_delta > fanin_delta_max:
                fanin_delta_max = fanin_delta
            if fanout_delta_max is not None and fanout_delta > fanout_delta_max:
                fanout_delta_max = fanout_delta

        loc_delta = new_m.loc - old_m.loc
        exp_delta = new_m.exports - old_m.exports
        imp_delta = new_m.internal_imports - old_m.internal_imports

        metrics = (
            "loc="
            f"{old_m.loc}->{new_m.loc}(d={loc_delta}) "
            "exports="
            f"{old_m.exports}->{new_m.exports}(d={exp_delta}) "
            "imports="
            f"{old_m.internal_imports}->{new_m.internal_imports}(d={imp_delta})"
        )

        tier = _tier(new_m.loc, large=gate_monolith_large_loc, huge=gate_monolith_huge_loc)
        allow_loc = (
            gate_monolith_huge_allow_loc_increase
            if tier == "huge"
            else gate_monolith_large_allow_loc_increase
            if tier == "large"
            else None
        )
        allow_exp = (
            gate_monolith_huge_allow_exports_delta
            if tier == "huge"
            else gate_monolith_large_allow_exports_delta
            if tier == "large"
            else None
        )
        allow_imp = (
            gate_monolith_huge_allow_imports_delta
            if tier == "huge"
            else gate_monolith_large_allow_imports_delta
            if tier == "large"
            else None
        )

        # MONO.PARSE
        if not new_m.parse_ok or (old_path.exists() and not old_m.parse_ok):
            sev = "FAIL" if gate_monolith_on_parse_error == "fail" else "WARN"
            which = "new" if not new_m.parse_ok else "old"
            if rp.endswith(".js"):
                hint = "fix_js_syntax_or_encoding"
            else:
                hint = "fix_python_syntax_or_encoding"
            add(
                "MONO.PARSE",
                rp,
                f"{metrics} parse_failed on={which} hint={hint}",
                sev,
            )

        file_area = area_for_relpath(rp, areas)

        # MONO.CATCHALL
        if is_new_file and _is_catchall_new_file(
            rp,
            basenames=gate_monolith_catchall_basenames,
            dirs=gate_monolith_catchall_dirs,
            allowlist=gate_monolith_catchall_allowlist,
        ):
            add(
                "MONO.CATCHALL",
                rp,
                f"{metrics} new_catchall_file hint=rename_or_split_module",
                "FAIL",
            )

        # MONO.NEWFILE
        if is_new_file:
            if new_m.loc > gate_monolith_new_file_max_loc:
                add(
                    "MONO.NEWFILE",
                    rp,
                    (
                        f"{metrics} new_file_loc={new_m.loc} "
                        f"max={gate_monolith_new_file_max_loc} "
                        "hint=split_file_or_reduce_scope"
                    ),
                    "FAIL",
                )
            if new_m.exports > gate_monolith_new_file_max_exports:
                add(
                    "MONO.NEWFILE",
                    rp,
                    (
                        f"{metrics} new_file_exports={new_m.exports} "
                        f"max={gate_monolith_new_file_max_exports} "
                        "hint=split_public_api"
                    ),
                    "FAIL",
                )
            if new_m.internal_imports > gate_monolith_new_file_max_imports:
                add(
                    "MONO.NEWFILE",
                    rp,
                    (
                        f"{metrics} new_file_imports={new_m.internal_imports} "
                        f"max={gate_monolith_new_file_max_imports} "
                        "hint=reduce_coupling"
                    ),
                    "FAIL",
                )

        # MONO.GROWTH
        if tier in ("large", "huge") and allow_loc is not None and allow_exp is not None:
            if loc_delta > allow_loc:
                add(
                    "MONO.GROWTH",
                    rp,
                    (
                        f"{metrics} tier={tier} "
                        f"loc_delta={loc_delta} allow={allow_loc} "
                        "hint=split_or_refactor"
                    ),
                    "FAIL",
                )
            if exp_delta > allow_exp:
                add(
                    "MONO.GROWTH",
                    rp,
                    (
                        f"{metrics} tier={tier} "
                        f"exports_delta={exp_delta} allow={allow_exp} "
                        "hint=split_public_api"
                    ),
                    "FAIL",
                )
            if allow_imp is not None and imp_delta > allow_imp:
                add(
                    "MONO.GROWTH",
                    rp,
                    (
                        f"{metrics} tier={tier} "
                        f"imports_delta={imp_delta} allow={allow_imp} "
                        "hint=reduce_coupling"
                    ),
                    "FAIL",
                )

        # MONO.CORE
        if file_area == "core":
            imported_areas: set[str] = set()
            if rp.endswith(".py"):
                cur_mod = _module_for_relpath(rp)
                mods = []
                tree = _parse_tree(new_text)
                if tree is not None:
                    mods = _iter_import_modules(tree, current_module=cur_mod)
                imported_areas = {_area_for_module(m, areas) for m in mods}
            elif rp.endswith(".js"):
                for tgt in monolith_js_metrics.js_internal_import_targets(
                    relpath=rp,
                    text=new_text,
                    cwd=cwd,
                    repo_root=repo_root,
                ):
                    imported_areas.add(area_for_relpath(tgt, areas))
            if any(a.startswith("plugins.") for a in imported_areas) or "runner" in imported_areas:
                add(
                    "MONO.CORE",
                    rp,
                    f"{metrics} core_imports_plugins_or_runner hint=remove_core_dependency",
                    "FAIL",
                )

        # MONO.CROSSAREA
        if new_m.distinct_areas >= gate_monolith_crossarea_min_distinct_areas and (
            loc_delta > 0 or exp_delta > 0
        ):
            add(
                "MONO.CROSSAREA",
                rp,
                (
                    f"{metrics} distinct_areas={new_m.distinct_areas} "
                    f"delta_loc={loc_delta} delta_exports={exp_delta} "
                    "hint=split_by_area_or_add_facade"
                ),
                "FAIL",
            )

        # MONO.HUB
        if (
            gate_monolith_compute_fanin
            and fanin_new is not None
            and fanout_new is not None
            and fanin_old is not None
            and fanout_old is not None
        ):
            fanin_delta = fanin_new - fanin_old
            fanout_delta = fanout_new - fanout_old
            if (
                fanin_delta >= gate_monolith_hub_fanin_delta
                and exp_delta >= gate_monolith_hub_exports_delta_min
            ):
                add(
                    "MONO.HUB",
                    rp,
                    (
                        f"{metrics} fanin_delta={fanin_delta} "
                        f"exports_delta={exp_delta} "
                        "hint=avoid_hub_growth"
                    ),
                    "FAIL",
                )
            if (
                fanout_delta >= gate_monolith_hub_fanout_delta
                and loc_delta >= gate_monolith_hub_loc_delta_min
            ):
                add(
                    "MONO.HUB",
                    rp,
                    (
                        f"{metrics} fanout_delta={fanout_delta} "
                        f"loc_delta={loc_delta} "
                        "hint=reduce_outbound_dependencies"
                    ),
                    "FAIL",
                )

    logger.line("gate_monolith_files_scanned=" + str(files_scanned))
    logger.line("gate_monolith_files_new=" + str(files_new))
    logger.line("gate_monolith_parse_errors_new=" + str(parse_errors_new))
    logger.line("gate_monolith_parse_errors_old=" + str(parse_errors_old))

    logger.line("gate_monolith_loc_total_old=" + str(loc_total_old))
    logger.line("gate_monolith_loc_total_new=" + str(loc_total_new))
    logger.line("gate_monolith_loc_total_delta=" + str(loc_total_new - loc_total_old))

    logger.line("gate_monolith_imports_total_old=" + str(imports_total_old))
    logger.line("gate_monolith_imports_total_new=" + str(imports_total_new))
    logger.line("gate_monolith_imports_total_delta=" + str(imports_total_new - imports_total_old))

    logger.line("gate_monolith_exports_total_old=" + str(exports_total_old))
    logger.line("gate_monolith_exports_total_new=" + str(exports_total_new))
    logger.line("gate_monolith_exports_total_delta=" + str(exports_total_new - exports_total_old))

    if gate_monolith_compute_fanin:
        logger.line("gate_monolith_fanin_delta_max=" + str(fanin_delta_max or 0))
        logger.line("gate_monolith_fanout_delta_max=" + str(fanout_delta_max or 0))
    else:
        logger.line("gate_monolith_fanin_delta_max=n/a")
        logger.line("gate_monolith_fanout_delta_max=n/a")

    # Map severities by mode.
    mapped: list[Violation] = []
    for v in violations:
        sev = v.severity
        if gate_monolith_mode == "report_only":
            sev = "REPORT"
        elif gate_monolith_mode == "strict":
            sev = "FAIL"
        elif gate_monolith_mode == "warn_only":
            is_always_fail = v.rule_id in ("MONO.CORE", "MONO.CATCHALL")
            is_parse_fail = v.rule_id == "MONO.PARSE" and gate_monolith_on_parse_error == "fail"
            sev = "FAIL" if is_always_fail or is_parse_fail else "WARN"
        mapped.append(
            Violation(
                rule_id=v.rule_id,
                relpath=v.relpath,
                message=v.message,
                severity=sev,
            )
        )

    # Emit.
    fail = [v for v in mapped if v.severity == "FAIL"]
    warn = [v for v in mapped if v.severity in ("WARN", "REPORT")]

    for v in sorted(mapped, key=lambda x: (x.rule_id, x.relpath)):
        line = f"{v.rule_id} {v.relpath} {v.severity} {v.message}"
        if v.severity == "FAIL":
            logger.error_core(line)
        elif v.severity == "WARN":
            logger.warning_core(line)
        else:
            logger.line(line)

    if fail:
        quiet_enabled = (logger.screen_level == "quiet") or (logger.log_level == "quiet")
        if quiet_enabled:
            detail_lines: list[str] = [
                "MONOLITH FAIL REASONS:",
                "count=" + str(len(fail)),
            ]
            for v in sorted(fail, key=lambda x: (x.rule_id, x.relpath)):
                line = f"{v.rule_id} {v.relpath} {v.severity} {v.message}"
                detail_lines.append(line)
            logger.emit_error_detail("\n".join(detail_lines) + "\n")
        logger.error_core("MONOLITH: FAIL")
        return False
    if warn:
        logger.warning_core("MONOLITH: WARN")
        return True

    logger.line("MONOLITH: PASS")
    return True
