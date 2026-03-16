from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from .errors import RunnerError
from .gate_docs import check_docs_gate
from .gates_wiring_guard import assert_single_run_gates_callsite
from .log import Logger
from .monolith_gate import run_monolith_gate
from .pytest_bucket_routing import select_pytest_targets

_RUN_GATES_WIRING_CHECKED = False


def _norm_targets(targets: list[str], fallback: list[str]) -> list[str]:
    out: list[str] = []
    for t in targets:
        s = str(t).strip()
        if s and s not in out:
            out.append(s)
    return out or list(fallback)


def _typescript_target_to_include_glob(t: str) -> str:
    s = str(t).strip().replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    s = s.rstrip("/")
    if not s:
        return ""
    if any(ch in s for ch in ("*", "?", "[")):
        return s
    return s + "/**/*"


def _typescript_targets_to_include(targets: list[str]) -> list[str]:
    out: list[str] = []
    for t in targets:
        g = _typescript_target_to_include_glob(t)
        if g and g not in out:
            out.append(g)
    return out


def _typescript_targets_to_trigger_prefixes(targets: list[str]) -> list[str]:
    out: list[str] = []
    for t in targets:
        s = str(t).strip().replace("\\", "/")
        if s.startswith("./"):
            s = s[2:]
        for ch in ("*", "?", "["):
            if ch in s:
                s = s.split(ch, 1)[0]
                break
        s = s.rstrip("/")
        if s and s not in out:
            out.append(s)
    return out


def _write_typescript_gate_tsconfig(
    repo_root: Path,
    *,
    base_tsconfig: str,
    targets: list[str],
) -> Path:
    base_path = repo_root / base_tsconfig
    if not base_path.exists():
        raise RunnerError(
            "CONFIG",
            "TYPESCRIPT_BASE_TSCONFIG_NOT_FOUND",
            f"missing base tsconfig: {base_tsconfig!r}",
        )

    gen_dir = repo_root / ".am_patch"
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_path = gen_dir / "tsconfig.typescript_gate.json"
    rel_extends = os.path.relpath(base_path, gen_dir)
    includes = _typescript_targets_to_include(targets)
    # NOTE: TypeScript resolves `include` relative to the directory of the
    # tsconfig itself. Our generated tsconfig lives under `.am_patch/`, so we
    # must point one level up to reach repo-relative targets (scripts/, plugins/...).
    includes = [("../" + x.lstrip("./")) if not x.startswith(("../", "/")) else x for x in includes]
    includes = [x.replace("\\", "/") for x in includes]
    payload: dict[str, object] = {
        "extends": rel_extends,
        "include": includes,
    }
    gen_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return gen_path


def _venv_python(repo_root: Path) -> Path:
    # Do NOT .resolve() here: it may collapse the venv python symlink to /usr/bin/pythonX.Y
    # and lose venv site-packages.
    return repo_root / ".venv" / "bin" / "python"


def _infer_venv_root(python_exe: str) -> Path | None:
    p = Path(python_exe)
    # Detect the common layout: <repo>/.venv/bin/python
    if p.name == "python" and p.parent.name == "bin" and p.parent.parent.name == ".venv":
        return p.parent.parent
    return None


def _cmd_py(module: str, *, python: str) -> list[str]:
    return [python, "-m", module]


def _norm_exclude_paths(exclude: list[str]) -> list[str]:
    out: list[str] = []
    for x in exclude:
        s = str(x).strip().replace("\\\\", "/")
        if s.startswith("./"):
            s = s[2:]
        s = s.strip("/")
        if s and s not in out:
            out.append(s)
    return out


def _compile_exclude_regex(exclude: list[str]) -> str | None:
    ex = _norm_exclude_paths(exclude)
    if not ex:
        return None
    parts = "|".join(re.escape(p) for p in ex)
    return rf"(^|/)({parts})(/|$)"


def _norm_rel_path(p: str) -> str:
    s = str(p).strip().replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    s = s.strip("/")
    return s


def _norm_rel_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        s = _norm_rel_path(p)
        if s and s not in out:
            out.append(s)
    return out


def _norm_js_extensions(exts: list[str]) -> list[str]:
    out: list[str] = []
    for e in exts:
        s = str(e).strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        if s not in out:
            out.append(s)
    return out


def check_js_gate(
    decision_paths: list[str],
    *,
    extensions: list[str],
) -> tuple[bool, list[str]]:
    """Return (triggered, js_paths).

    The gate triggers only if at least one changed path ends with one of the configured extensions.
    Returned js_paths are normalized repo-relative paths (forward slashes, no leading ./).
    """
    exts = _norm_js_extensions(extensions)
    if not exts:
        return False, []

    paths = _norm_rel_paths(decision_paths)
    js_paths: list[str] = []
    for p in paths:
        pl = p.lower()
        if any(pl.endswith(e) for e in exts):
            js_paths.append(p)

    if not js_paths:
        return False, []
    js_paths.sort()
    return True, js_paths


def run_js_syntax_gate(
    logger: Logger,
    cwd: Path,
    *,
    decision_paths: list[str],
    extensions: list[str],
    command: list[str],
) -> bool:
    """Run JS syntax validation via an external command (default: node --check).

    The gate is a no-op (SKIP) when no JS files are touched.
    """
    triggered, js_paths = check_js_gate(decision_paths, extensions=extensions)
    if not triggered:
        logger.warning_core("gate_js=SKIP (no_js_touched)")
        return True

    existing_js_paths: list[str] = []
    for rel in js_paths:
        if (cwd / rel).is_file():
            existing_js_paths.append(rel)

    if not existing_js_paths:
        logger.warning_core("gate_js=SKIP (no_existing_js_files)")
        return True

    cmd0 = [str(x) for x in command if str(x).strip()]
    if not cmd0:
        raise RunnerError("GATES", "JS_CMD", "gate_js_command must be non-empty")

    logger.section("GATE: JS SYNTAX")
    logger.line("gate_js_extensions=" + ",".join(_norm_js_extensions(extensions)))
    logger.line("gate_js_cmd=" + " ".join(cmd0))

    for rel in existing_js_paths:
        logger.line("gate_js_file=" + rel)
        r = logger.run_logged([*cmd0, rel], cwd=cwd)
        if r.returncode != 0:
            return False
    return True


def check_file_scoped_gate(
    decision_paths: list[str],
    *,
    extensions: list[str],
) -> tuple[bool, list[str]]:
    """Return (triggered, matched_paths).

    The gate triggers if at least one changed path ends with one of the extensions.
    Returned paths are normalized repo-relative paths (forward slashes, no leading ./).
    """
    exts = _norm_js_extensions(extensions)
    if not exts:
        return False, []

    paths = _norm_rel_paths(decision_paths)
    matched: list[str] = []
    for p in paths:
        pl = p.lower()
        if any(pl.endswith(e) for e in exts):
            matched.append(p)

    if not matched:
        return False, []
    matched.sort()
    return True, matched


def run_file_scoped_gate(
    logger: Logger,
    cwd: Path,
    *,
    name: str,
    decision_paths: list[str],
    extensions: list[str],
    command: list[str],
) -> bool:
    triggered, paths = check_file_scoped_gate(decision_paths, extensions=extensions)
    if not triggered:
        logger.warning_core(f"gate_{name}=SKIP (no_matching_files)")
        return True

    existing: list[str] = []
    for rel in paths:
        if (cwd / rel).is_file():
            existing.append(rel)

    if not existing:
        logger.warning_core(f"gate_{name}=SKIP (no_existing_files)")
        return True

    cmd0 = [str(x) for x in command if str(x).strip()]
    if not cmd0:
        raise RunnerError("GATES", "CMD", f"gate_{name}_command must be non-empty")

    logger.section(f"GATE: {name}")
    logger.line(f"gate_{name}_extensions=" + ",".join(_norm_js_extensions(extensions)))
    logger.line(f"gate_{name}_cmd=" + " ".join(cmd0))
    for rel in existing:
        logger.line(f"gate_{name}_file=" + rel)

    r = logger.run_logged([*cmd0, *existing], cwd=cwd)
    return r.returncode == 0


def _select_python_for_gate(
    *,
    repo_root: Path,
    gate: str,
    pytest_use_venv: bool,
) -> str:
    if gate == "pytest" and pytest_use_venv:
        vpy = _venv_python(repo_root)
        if not vpy.exists():
            raise RunnerError(
                "GATES", "PYTEST_VENV", f"pytest_use_venv=true but venv python not found: {vpy}"
            )
        return str(vpy)
    return sys.executable


def run_ruff(
    logger: Logger,
    cwd: Path,
    *,
    repo_root: Path,
    ruff_format: bool,
    autofix: bool,
    targets: list[str],
) -> bool:
    targets = _norm_targets(targets, ["src", "tests"])
    py = _select_python_for_gate(repo_root=repo_root, gate="ruff", pytest_use_venv=False)

    if ruff_format:
        logger.section("GATE: RUFF FORMAT")
        rfmt = logger.run_logged(
            _cmd_py("ruff", python=py) + ["format", *targets],
            cwd=cwd,
            failure_dump_mode="warn_detail",
        )
        if rfmt.returncode != 0:
            return False

    logger.section("GATE: RUFF (initial)")
    r = logger.run_logged(
        _cmd_py("ruff", python=py) + ["check", *targets],
        cwd=cwd,
        failure_dump_mode="diagnostic_detail",
    )
    if r.returncode == 0:
        return True
    if not autofix:
        return False

    logger.section("GATE: RUFF (fix)")
    _ = logger.run_logged(
        _cmd_py("ruff", python=py) + ["check", *targets, "--fix"],
        cwd=cwd,
        failure_dump_mode="warn_detail",
    )

    logger.section("GATE: RUFF (final)")
    r2 = logger.run_logged(_cmd_py("ruff", python=py) + ["check", *targets], cwd=cwd)
    return r2.returncode == 0


def run_biome(
    logger: Logger,
    cwd: Path,
    *,
    decision_paths: list[str],
    extensions: list[str],
    command: list[str],
    biome_format: bool,
    format_command: list[str],
    autofix: bool,
    fix_command: list[str],
) -> bool:
    triggered, paths = check_file_scoped_gate(decision_paths, extensions=extensions)
    if not triggered:
        logger.warning_core("gate_biome=SKIP (no_matching_files)")
        return True

    existing: list[str] = []
    for rel in paths:
        if (cwd / rel).is_file():
            existing.append(rel)
    if not existing:
        logger.warning_core("gate_biome=SKIP (no_existing_files)")
        return True

    cmd0 = [str(x) for x in command if str(x).strip()]
    if not cmd0:
        raise RunnerError("GATES", "CMD", "gate_biome_command must be non-empty")

    if biome_format:
        fmt_cmd0 = [str(x) for x in format_command if str(x).strip()]
        if not fmt_cmd0:
            # Defensive fallback: older policy overlays may omit the format command.
            # Keep deterministic behavior by using the Policy default.
            fmt_cmd0 = ["npm", "exec", "--", "biome", "format", "--write"]

        logger.section("GATE: BIOME FORMAT")
        logger.line("gate_biome_format_cmd=" + " ".join(fmt_cmd0))
        r0 = logger.run_logged([*fmt_cmd0, *existing], cwd=cwd, failure_dump_mode="warn_detail")
        if r0.returncode != 0:
            return False

    logger.section("GATE: BIOME (check)")
    logger.line("gate_biome_extensions=" + ",".join(_norm_js_extensions(extensions)))
    logger.line("gate_biome_cmd=" + " ".join(cmd0))
    for rel in existing:
        logger.line("gate_biome_file=" + rel)

    r = logger.run_logged(
        [*cmd0, *existing],
        cwd=cwd,
        failure_dump_mode="diagnostic_detail",
    )
    if r.returncode == 0:
        return True
    if not autofix:
        return False

    fix_cmd0 = [str(x) for x in fix_command if str(x).strip()]
    if not fix_cmd0:
        raise RunnerError("GATES", "CMD", "gate_biome_fix_command must be non-empty")

    logger.section("GATE: BIOME_AUTOFIX (apply)")
    logger.line("gate_biome_fix_cmd=" + " ".join(fix_cmd0))
    _ = logger.run_logged([*fix_cmd0, *existing], cwd=cwd, failure_dump_mode="warn_detail")

    logger.section("GATE: BIOME (final)")
    r2 = logger.run_logged([*cmd0, *existing], cwd=cwd)
    return r2.returncode == 0


def run_pytest(
    logger: Logger, cwd: Path, *, repo_root: Path, pytest_use_venv: bool, targets: list[str]
) -> bool:
    targets = _norm_targets(targets, [])
    if not targets:
        raise RunnerError(
            "CONFIG",
            "PYTEST_TARGETS_EMPTY",
            "effective pytest target list is empty",
        )

    # IMPORTANT: pytest may need dependencies that exist only inside a venv.
    # Preferred: use repo_root/.venv/bin/python when it exists.
    # Fallback: if the workspace/clone repo has no .venv, but this runner itself is
    # already executing from a venv (sys.executable), use sys.executable.
    venv_root: Path | None = None
    if pytest_use_venv:
        vpy = _venv_python(repo_root)
        if vpy.exists():
            py = str(vpy)
            venv_root = repo_root / ".venv"
        else:
            venv_root = _infer_venv_root(sys.executable)
            if venv_root is None or not Path(sys.executable).exists():
                msg = (
                    f"pytest_use_venv=true but venv python not found: {vpy} "
                    "(and no usable venv in sys.executable)"
                )
                raise RunnerError(
                    "GATES",
                    "PYTEST_VENV",
                    msg,
                )
            py = sys.executable
    else:
        py = sys.executable

    logger.section("GATE: PYTEST")
    logger.line(f"pytest_use_venv={pytest_use_venv}")
    logger.line(f"sys_executable={sys.executable}")
    logger.line(f"pytest_python={py}")
    env = dict(os.environ)
    env["AM_PATCH_PYTEST_GATE"] = "1"
    if pytest_use_venv and venv_root is not None:
        # Ensure subprocesses spawned by tests can resolve `audiomason`.
        # This is done by prefixing PATH with the venv bin dir.
        venv_bin = venv_root / "bin"
        old_path = env.get("PATH", "")
        env["PATH"] = f"{venv_bin}:{old_path}" if old_path else str(venv_bin)
        env["VIRTUAL_ENV"] = str(venv_root)
    r = logger.run_logged(_cmd_py("pytest", python=py) + ["-q", *targets], cwd=cwd, env=env)
    return r.returncode == 0


def run_badguys(
    logger: Logger,
    cwd: Path,
    *,
    repo_root: Path,
    command: list[str],
) -> bool:
    logger.section("GATE: BADGUYS")
    logger.line(f"badguys_python={sys.executable}")
    env = dict(os.environ)
    env["AM_PATCH_BADGUYS_GATE"] = "1"
    # Ensure BadGuys uses the same Python as the runner for nested am_patch invocations.
    env["AM_PATCH_BADGUYS_RUNNER_PYTHON"] = sys.executable
    # If we are running from a venv, propagate PATH/VIRTUAL_ENV so nested processes
    # can find the same toolchain even inside workspace/clone repos.
    venv_root = _infer_venv_root(sys.executable)
    if venv_root is not None:
        venv_bin = venv_root / "bin"
        old_path = env.get("PATH", "")
        env["PATH"] = f"{venv_bin}:{old_path}" if old_path else str(venv_bin)
        env["VIRTUAL_ENV"] = str(venv_root)
    logger.line(f"badguys_cmd={command}")
    cmd = [sys.executable, "-u", *command]
    r = logger.run_logged(cmd, cwd=cwd, env=env)
    return r.returncode == 0


def run_mypy(logger: Logger, cwd: Path, *, repo_root: Path, targets: list[str]) -> bool:
    targets = _norm_targets(targets, ["src"])
    py = _select_python_for_gate(repo_root=repo_root, gate="mypy", pytest_use_venv=False)
    logger.section("GATE: MYPY")
    r = logger.run_logged(_cmd_py("mypy", python=py) + [*targets], cwd=cwd)
    return r.returncode == 0


def run_compile_check(
    logger: Logger,
    cwd: Path,
    *,
    repo_root: Path,
    targets: list[str],
    exclude: list[str],
) -> bool:
    """Compile Python sources to catch syntax errors early."""
    logger.section("GATE: compile")
    py = sys.executable
    logger.line(f"compile_python={py}")
    targets = _norm_targets(targets, ["."])
    exclude = _norm_exclude_paths(exclude)
    logger.line(f"compile_targets={targets}")
    logger.line(f"compile_exclude={exclude}")
    cmd: list[str] = [py, "-m", "compileall", "-q"]
    rx = _compile_exclude_regex(exclude)
    if rx:
        logger.line(f"compile_exclude_regex={rx}")
        cmd += ["-x", rx]
    cmd += targets
    r = logger.run_logged(cmd, cwd=cwd)
    return r.returncode == 0


def _norm_gate_name(s: str) -> str:
    return str(s).strip().lower()


def _norm_gates_order(order: list[str] | None) -> list[str]:
    if not order:
        return []
    allowed = {
        "dont-touch",
        "compile",
        "js",
        "biome",
        "typescript",
        "ruff",
        "pytest",
        "mypy",
        "docs",
        "monolith",
    }
    out: list[str] = []
    for item in order:
        name = _norm_gate_name(item)
        if name in allowed and name not in out:
            out.append(name)
    return out


def run_gates(
    logger: Logger,
    cwd: Path,
    *,
    repo_root: Path,
    run_all: bool,
    compile_check: bool,
    compile_targets: list[str],
    compile_exclude: list[str],
    allow_fail: bool,
    skip_dont_touch: bool = False,
    dont_touch_paths: list[str] | None = None,
    skip_ruff: bool,
    skip_js: bool,
    skip_biome: bool = True,
    skip_typescript: bool = True,
    skip_pytest: bool,
    skip_mypy: bool,
    skip_docs: bool,
    skip_monolith: bool,
    gate_monolith_enabled: bool,
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
    docs_include: list[str],
    docs_exclude: list[str],
    docs_required_files: list[str],
    docs_status_entries: list[tuple[str, str]] | None = None,
    js_extensions: list[str],
    js_command: list[str],
    biome_extensions: list[str] | None = None,
    biome_command: list[str] | None = None,
    biome_format: bool = True,
    biome_format_command: list[str] | None = None,
    biome_autofix: bool = True,
    biome_fix_command: list[str] | None = None,
    typescript_extensions: list[str] | None = None,
    typescript_command: list[str] | None = None,
    gate_typescript_mode: str = "auto",
    typescript_targets: list[str] | None = None,
    gate_typescript_base_tsconfig: str = "tsconfig.json",
    ruff_format: bool,
    ruff_autofix: bool,
    ruff_targets: list[str],
    pytest_targets: list[str],
    mypy_targets: list[str],
    gate_ruff_mode: str = "auto",
    gate_mypy_mode: str = "auto",
    gate_pytest_mode: str = "auto",
    gate_pytest_py_prefixes: list[str] | None = None,
    gate_pytest_js_prefixes: list[str] | None = None,
    pytest_routing_policy: dict[str, object] | None = None,
    gates_order: list[str] | None,
    pytest_use_venv: bool,
    decision_paths: list[str],
    progress: Callable[[str], None] | None = None,
) -> None:
    global _RUN_GATES_WIRING_CHECKED
    if not _RUN_GATES_WIRING_CHECKED:
        assert_single_run_gates_callsite()
        _RUN_GATES_WIRING_CHECKED = True

    failures: list[str] = []
    skipped: list[str] = []

    order = _norm_gates_order(gates_order)
    biome_exts = biome_extensions or []
    biome_cmd = biome_command or []
    biome_fmt_cmd = biome_format_command or []
    biome_fix_cmd = biome_fix_command or []
    ts_exts = typescript_extensions or []
    ts_cmd = typescript_command or []
    ts_mode = str(gate_typescript_mode).strip()
    if ts_mode not in ("auto", "always"):
        raise RunnerError(
            "CONFIG",
            "INVALID_GATE_TYPESCRIPT_MODE",
            f"invalid gate_typescript_mode: {ts_mode!r}",
        )
    ts_targets = _norm_targets(typescript_targets or [], fallback=[])
    ts_base = str(gate_typescript_base_tsconfig).strip() or "tsconfig.json"
    if not order:
        logger.section("GATES: SKIPPED (gates_order empty)")
        logger.warning_core("GATES: SKIPPED (gates_order empty)")
        return

    _norm_decision_paths = [p.replace("\\", "/").lstrip("./") for p in decision_paths]
    gate_pytest_py_prefixes = gate_pytest_py_prefixes or []
    gate_pytest_js_prefixes = gate_pytest_js_prefixes or []

    def _has_changed_basename(names: tuple[str, ...]) -> bool:
        return any(pth in names for pth in _norm_decision_paths)

    def _has_changed_file(exts: tuple[str, ...], prefixes: list[str]) -> bool:
        norm_prefixes = [x.rstrip("/").lstrip("./") for x in prefixes if x]
        for pth in _norm_decision_paths:
            if not pth.endswith(exts):
                continue
            for pfx in norm_prefixes:
                if pth == pfx or pth.startswith(pfx + "/"):
                    return True
        return False

    def _run_gate(name: str) -> bool:
        if name == "dont-touch":
            if skip_dont_touch:
                skipped.append("dont-touch")
                logger.warning_core("gate_dont_touch=SKIP (skipped_by_user)")
                return True
            from .gate_dont_touch import run_dont_touch_gate

            logger.section("GATE: dont-touch")
            ok, reason = run_dont_touch_gate(
                decision_paths=decision_paths,
                protected_paths=list(dont_touch_paths or []),
            )
            if ok:
                logger.line("gate_dont_touch=OK")
                return True
            logger.error_core("gate_dont_touch=FAIL")
            if reason:
                logger.error_core(reason)
            return False

        if name == "compile":
            if not compile_check:
                skipped.append("compile")
                logger.warning_core("gate_compile=SKIP (disabled_by_policy)")
                return True
            return run_compile_check(
                logger,
                cwd=cwd,
                repo_root=repo_root,
                targets=compile_targets,
                exclude=compile_exclude,
            )

        if name == "js":
            if skip_js:
                skipped.append("js")
                logger.warning_core("gate_js=SKIP (skipped_by_user)")
                return True
            return run_js_syntax_gate(
                logger,
                cwd=cwd,
                decision_paths=decision_paths,
                extensions=js_extensions,
                command=js_command,
            )

        if name == "biome":
            if skip_biome:
                skipped.append("biome")
                logger.warning_core("gate_biome=SKIP (skipped_by_user)")
                return True
            return run_biome(
                logger,
                cwd=cwd,
                decision_paths=decision_paths,
                extensions=biome_exts,
                command=biome_cmd,
                biome_format=biome_format,
                format_command=biome_fmt_cmd,
                autofix=biome_autofix,
                fix_command=biome_fix_cmd,
            )

        if name == "typescript":
            if skip_typescript:
                skipped.append("typescript")
                logger.warning_core("gate_typescript=SKIP (skipped_by_user)")
                return True
            if ts_mode != "always":
                trigger_prefixes = _typescript_targets_to_trigger_prefixes(ts_targets)
                trigger = _has_changed_basename((ts_base,)) or _has_changed_file(
                    tuple(ts_exts), trigger_prefixes
                )
                if not trigger:
                    skipped.append("typescript")
                    logger.warning_core("gate_typescript=SKIP (no_matching_files)")
                    return True
            gen_path = _write_typescript_gate_tsconfig(
                cwd, base_tsconfig=ts_base, targets=ts_targets
            )
            argv = list(ts_cmd) + ["--project", str(gen_path)]
            r = logger.run_logged(argv, cwd=cwd)
            return r.returncode == 0

        if name == "ruff":
            if skip_ruff:
                skipped.append("ruff")
                logger.warning_core("gate_ruff=SKIP (skipped_by_user)")
                return True
            if gate_ruff_mode != "always":
                trigger = _has_changed_basename(("pyproject.toml",)) or _has_changed_file(
                    (".py",), ruff_targets
                )
                if not trigger:
                    skipped.append("ruff")
                    logger.warning_core("gate_ruff=SKIP (no_matching_files)")
                    return True
            return run_ruff(
                logger,
                cwd,
                repo_root=repo_root,
                ruff_format=ruff_format,
                autofix=ruff_autofix,
                targets=ruff_targets,
            )

        if name == "pytest":
            if skip_pytest:
                skipped.append("pytest")
                logger.warning_core("gate_pytest=SKIP (skipped_by_user)")
                return True
            if gate_pytest_mode != "always":
                trigger_py = _has_changed_basename(
                    ("pyproject.toml", "pytest.ini")
                ) or _has_changed_file((".py",), gate_pytest_py_prefixes)
                trigger_js = bool(gate_pytest_js_prefixes) and _has_changed_file(
                    (".js", ".mjs", ".cjs"), gate_pytest_js_prefixes
                )
                if not trigger_py and not trigger_js:
                    skipped.append("pytest")
                    logger.warning_core("gate_pytest=SKIP (no_matching_files)")
                    return True
            return run_pytest(
                logger,
                cwd,
                repo_root=repo_root,
                pytest_use_venv=pytest_use_venv,
                targets=select_pytest_targets(
                    decision_paths=decision_paths,
                    pytest_targets=pytest_targets,
                    routing_policy=pytest_routing_policy,
                ),
            )

        if name == "mypy":
            if skip_mypy:
                skipped.append("mypy")
                logger.warning_core("gate_mypy=SKIP (skipped_by_user)")
                return True
            if gate_mypy_mode != "always":
                trigger = _has_changed_basename(("pyproject.toml",)) or _has_changed_file(
                    (".py",), mypy_targets
                )
                if not trigger:
                    skipped.append("mypy")
                    logger.warning_core("gate_mypy=SKIP (no_matching_files)")
                    return True
            return run_mypy(logger, cwd, repo_root=repo_root, targets=mypy_targets)

        if name == "monolith":
            if skip_monolith:
                skipped.append("monolith")
                logger.warning_core("gate_monolith=SKIP (skipped_by_user)")
                return True
            if not gate_monolith_enabled:
                skipped.append("monolith")
                logger.warning_core("gate_monolith=SKIP (disabled_by_policy)")
                return True
            return run_monolith_gate(
                logger,
                cwd,
                repo_root=repo_root,
                decision_paths=decision_paths,
                gate_monolith_mode=gate_monolith_mode,
                gate_monolith_scan_scope=gate_monolith_scan_scope,
                gate_monolith_extensions=gate_monolith_extensions,
                gate_monolith_compute_fanin=gate_monolith_compute_fanin,
                gate_monolith_on_parse_error=gate_monolith_on_parse_error,
                gate_monolith_areas_prefixes=gate_monolith_areas_prefixes,
                gate_monolith_areas_names=gate_monolith_areas_names,
                gate_monolith_areas_dynamic=gate_monolith_areas_dynamic,
                gate_monolith_large_loc=gate_monolith_large_loc,
                gate_monolith_huge_loc=gate_monolith_huge_loc,
                gate_monolith_large_allow_loc_increase=gate_monolith_large_allow_loc_increase,
                gate_monolith_huge_allow_loc_increase=gate_monolith_huge_allow_loc_increase,
                gate_monolith_large_allow_exports_delta=gate_monolith_large_allow_exports_delta,
                gate_monolith_huge_allow_exports_delta=gate_monolith_huge_allow_exports_delta,
                gate_monolith_large_allow_imports_delta=gate_monolith_large_allow_imports_delta,
                gate_monolith_huge_allow_imports_delta=gate_monolith_huge_allow_imports_delta,
                gate_monolith_new_file_max_loc=gate_monolith_new_file_max_loc,
                gate_monolith_new_file_max_exports=gate_monolith_new_file_max_exports,
                gate_monolith_new_file_max_imports=gate_monolith_new_file_max_imports,
                gate_monolith_hub_fanin_delta=gate_monolith_hub_fanin_delta,
                gate_monolith_hub_fanout_delta=gate_monolith_hub_fanout_delta,
                gate_monolith_hub_exports_delta_min=gate_monolith_hub_exports_delta_min,
                gate_monolith_hub_loc_delta_min=gate_monolith_hub_loc_delta_min,
                gate_monolith_crossarea_min_distinct_areas=(
                    gate_monolith_crossarea_min_distinct_areas
                ),
                gate_monolith_catchall_basenames=gate_monolith_catchall_basenames,
                gate_monolith_catchall_dirs=gate_monolith_catchall_dirs,
                gate_monolith_catchall_allowlist=gate_monolith_catchall_allowlist,
            )

        if name == "docs":
            if skip_docs:
                skipped.append("docs")
                logger.warning_core("gate_docs=SKIP (skipped_by_user)")
                return True
            ok, missing, trigger_reason = check_docs_gate(
                decision_paths,
                include=docs_include,
                exclude=docs_exclude,
                required_files=docs_required_files,
                changed_entries=docs_status_entries,
            )
            if ok:
                logger.line("gate_docs=OK")
                return True
            trig = trigger_reason or "unknown"
            logger.error_core("gate_docs=FAIL")
            logger.error_core("gate_docs_trigger=" + trig)
            logger.error_core("gate_docs_missing=" + ",".join(missing))
            return False

        return True

    for gate in (
        "dont-touch",
        "compile",
        "js",
        "biome",
        "typescript",
        "ruff",
        "pytest",
        "mypy",
        "docs",
        "monolith",
    ):
        if gate not in order:
            skipped.append(gate)
            logger.warning_core(f"gate_{gate}=SKIP (not in gates_order)")

    for gate in order:
        stage = f"GATE_{gate.upper()}"
        if progress is not None:
            progress(f"DO:{stage}")
        ok = _run_gate(gate)
        if progress is not None:
            progress(f"OK:{stage}" if ok else f"FAIL:{stage}")
        if not ok:
            failures.append(gate)
            if not run_all:
                if allow_fail:
                    break
                raise RunnerError("GATES", "GATES", f"gate failed: {gate}")

    if failures and not allow_fail:
        raise RunnerError("GATES", "GATES", "gates failed: " + ", ".join(failures))

    if failures and allow_fail:
        logger.warning_core("gates_failed_allowed=true")
        logger.warning_core("gates_failed=" + ",".join(failures))
