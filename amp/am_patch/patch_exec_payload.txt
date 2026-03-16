from __future__ import annotations

import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import RunnerError
from .log import Logger


def precheck_patch_script(path: Path, *, ascii_only: bool) -> None:
    import ast

    if ascii_only:
        raw = path.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as e:
            raise RunnerError(
                "PREFLIGHT", "PATCH_ASCII", f"patch script contains non-ascii characters: {path}"
            ) from e

    # Must parse cleanly and define FILES at top-level.
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        raise RunnerError("PREFLIGHT", "PATCH_SYNTAX", f"patch syntax error: {e}") from e

    has_files = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "FILES" for t in n.targets)
        for n in tree.body
    )
    if not has_files:
        raise RunnerError(
            "PREFLIGHT", "PATCH_FILES", "patch script must define FILES=[...] at top-level"
        )


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _find_bwrap() -> str | None:
    """Resolve a usable bwrap binary.

    This must never return a non-existent / non-executable value.
    """

    env = os.environ.get("AM_PATCH_BWRAP")
    if env:
        v = str(env).strip()
        if not v:
            return None

        # If it looks like a path, require it to exist and be executable.
        if "/" in v or Path(v).is_absolute():
            p = Path(v)
            if p.exists() and p.is_file() and os.access(str(p), os.X_OK):
                return str(p)
            return None

        # Otherwise treat it as a binary name and resolve it via PATH.
        resolved = shutil.which(v)
        return resolved or None

    return shutil.which("bwrap")


def _build_bwrap_cmd(*, workspace_repo: Path, argv: list[str], unshare_net: bool) -> list[str]:
    bwrap = _find_bwrap()
    if not bwrap:
        raise RunnerError(
            "PREFLIGHT", "BWRAP", "bwrap not found (install bubblewrap or disable patch_jail)"
        )

    cmd: list[str] = [bwrap, "--die-with-parent", "--new-session"]

    if unshare_net:
        cmd.append("--unshare-net")

    # Minimal runtime filesystem. Everything is read-only except the workspace repo.
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]

    for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(p).exists():
            cmd += ["--ro-bind", p, p]

    # Provide a writable repo mount at /repo (the ONLY intended write location).
    cmd += ["--bind", str(workspace_repo), "/repo", "--chdir", "/repo"]

    cmd += ["--"] + argv
    return cmd


def run_patch(
    logger: Logger,
    patch_script: Path,
    *,
    workspace_repo: Path,
    policy: object,
) -> None:
    # Copy patch into workspace and execute the copied script so __file__ is inside the workspace.
    # This prevents accidental writes to the live repo based on Path(__file__).
    src = patch_script.resolve()
    data = src.read_bytes()
    digest = _sha256_bytes(data)

    exec_path = (workspace_repo / ".am_patch" / "patch_exec.py").resolve()
    _write_atomic(exec_path, data)

    logger.section("PATCH SOURCE")
    logger.line(f"patch_source_path={src}")
    logger.line(f"patch_source_sha256={digest}")

    logger.section("PATCH EXEC (PREP)")
    logger.line(f"patch_exec_path={exec_path}")
    logger.line(f"patch_jail={getattr(policy, 'patch_jail', False)}")

    # Build command (optionally inside a jail).
    if getattr(policy, "patch_jail", False):
        # Inside jail we intentionally run system python3, not the runner's interpreter,
        # so that the jail does not need access to any venv under the live repo.
        python_argv = ["python3", f"/repo/{exec_path.relative_to(workspace_repo)}"]
        cmd = _build_bwrap_cmd(
            workspace_repo=workspace_repo,
            argv=python_argv,
            unshare_net=getattr(policy, "patch_jail_unshare_net", True),
        )
        logger.section("PATCH EXEC (JAILED)")
        logger.line("cmd=" + " ".join(cmd))
        logger.line("patch_exec=JAILED")
        try:
            r = logger.run_logged(cmd, cwd=workspace_repo)
        except FileNotFoundError as e:
            raise RunnerError(
                "PREFLIGHT",
                "BWRAP",
                "bwrap not found (install bubblewrap or disable patch_jail)",
            ) from e
    else:
        logger.section("PATCH EXEC")
        logger.line("patch_exec=RUN")
        r = logger.run_logged([sys.executable, str(exec_path)], cwd=workspace_repo)

    if r.returncode != 0:
        raise RunnerError("PATCH", "INTERNAL", f"patch script failed (rc={r.returncode})")


@dataclass(frozen=True)
class UnifiedPatchFailure:
    name: str
    data: bytes
    reason: str


@dataclass(frozen=True)
class UnifiedPatchResult:
    applied_ok: int
    applied_fail: int
    declared_files: list[str]  # files referenced by any patch (repo-relative)
    touched_files: list[str]  # files referenced by any patch (best-effort resolved, repo-relative)
    failures: list[UnifiedPatchFailure]


def _ascii_check_bytes(data: bytes, *, label: str) -> None:
    try:
        data.decode("ascii")
    except UnicodeDecodeError as e:
        raise RunnerError(
            "PREFLIGHT", "PATCH_ASCII", f"patch contains non-ascii characters: {label}"
        ) from e


def _parse_unified_header_paths(patch_text: str) -> list[str]:
    out: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            out.append(line[4:].strip().split("\t", 1)[0].strip())
    return out


def _normalize_patch_path(p: str) -> str:
    p = p.strip()
    if p in ("/dev/null", "dev/null"):
        return "/dev/null"
    for pre in ("a/", "b/"):
        if p.startswith(pre):
            p = p[len(pre) :]
            break
    if p.startswith("./"):
        p = p[2:]
    return p.strip()


def _split_abs_like(p: str) -> list[str]:
    p = p.strip()
    if p.startswith("/"):
        p = p.lstrip("/")
    return [x for x in p.split("/") if x]


def _candidate_strips(parts: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i in range(0, len(parts)):
        rel = "/".join(parts[i:])
        if rel:
            out.append((i, rel))
    return out


def _infer_strip_depth(repo: Path, paths: list[str]) -> int | None:
    scored: dict[int, int] = {}
    for raw in paths:
        n = _normalize_patch_path(raw)
        if n in ("/dev/null", ""):
            continue
        parts = _split_abs_like(n)
        for i, rel in _candidate_strips(parts):
            if (repo / rel).exists():
                scored[i] = scored.get(i, 0) + 1

    if not scored:
        return 0
    best = max(scored.values())
    best_ns = sorted([n for n, s in scored.items() if s == best])
    if len(best_ns) == 1:
        return best_ns[0]
    return None


def _rewrite_patch_paths(patch_text: str, *, strip: int) -> tuple[str, list[str]]:
    # Rewrite patch header paths deterministically and consistently.
    # For git-style patches, git apply expects:
    #   diff --git a/P b/P
    #   --- a/P (or /dev/null)
    #   +++ b/P (or /dev/null)
    # This function enforces that consistency while applying strip depth.
    rewritten_touched: list[str] = []
    out_lines: list[str] = []
    for line in patch_text.splitlines(True):
        if line.startswith("diff --git "):
            parts = line.rstrip("\n").split()
            # Expected: diff --git a/PATH b/PATH
            if len(parts) >= 4:
                a_norm = _normalize_patch_path(parts[2])
                b_norm = _normalize_patch_path(parts[3])
                if a_norm in ("/dev/null", "") or b_norm in ("/dev/null", ""):
                    out_lines.append(line)
                    continue
                a_parts = _split_abs_like(a_norm)
                b_parts = _split_abs_like(b_norm)
                a_rel = "/".join(a_parts[strip:]) if strip < len(a_parts) else "/".join(a_parts)
                b_rel = "/".join(b_parts[strip:]) if strip < len(b_parts) else "/".join(b_parts)
                if a_rel.startswith("/") or ".." in a_rel.split("/"):
                    a_rel = "/dev/null"
                if b_rel.startswith("/") or ".." in b_rel.split("/"):
                    b_rel = "/dev/null"
                if a_rel == "/dev/null" or b_rel == "/dev/null":
                    out_lines.append(line)
                    continue
                out_lines.append("diff --git a/" + a_rel + " b/" + b_rel + "\n")
                continue
        if line.startswith("--- ") or line.startswith("+++ "):
            prefix = line[:4]
            rest = line[4:].rstrip("\n")
            path_part = rest.split("\t", 1)[0].strip()
            norm = _normalize_patch_path(path_part)
            if norm in ("/dev/null", ""):
                out_lines.append(prefix + "/dev/null\n")
                continue
            parts = _split_abs_like(norm)
            rel_str = "/".join(parts[strip:]) if strip < len(parts) else "/".join(parts)
            if rel_str.startswith("/") or ".." in rel_str.split("/"):
                out_lines.append(prefix + "/dev/null\n")
                continue
            # Keep git-style a/ and b/ prefixes so headers stay consistent.
            if prefix == "--- ":
                out_lines.append(prefix + "a/" + rel_str + "\n")
            else:
                out_lines.append(prefix + "b/" + rel_str + "\n")
            rewritten_touched.append(rel_str)
            continue
        out_lines.append(line)
    uniq: list[str] = []
    seen: set[str] = set()
    for p in rewritten_touched:
        if p in ("/dev/null", ""):
            continue
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return ("".join(out_lines), uniq)


def _resolve_touched_best_effort(
    repo: Path, raw_paths: list[str], *, strip: int | None
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    repo = repo.resolve()

    all_files: list[str] = []
    for p in repo.rglob("*"):
        if p.is_file():
            try:
                rel_path = p.relative_to(repo)
            except Exception:
                continue
            all_files.append(str(rel_path))

    for raw in raw_paths:
        n = _normalize_patch_path(raw)
        if n in ("/dev/null", ""):
            continue
        parts = _split_abs_like(n)
        if strip is not None:
            rel_str = "/".join(parts[strip:]) if strip < len(parts) else "/".join(parts)
            if rel_str and rel_str not in seen:
                seen.add(rel_str)
                out.append(rel_str)
            continue

        tail = "/".join(parts[-min(len(parts), 6) :])
        cands = [f for f in all_files if f.endswith("/" + tail) or f == tail]
        if len(cands) == 1:
            rel_str = cands[0]
            if rel_str not in seen:
                seen.add(rel_str)
                out.append(rel_str)
    out.sort()
    return out


def run_unified_patch_bundle(
    logger: Logger,
    patch_input: Path,
    *,
    workspace_repo: Path,
    policy: object,
) -> UnifiedPatchResult:
    src = patch_input.resolve()
    if not src.exists():
        raise RunnerError("PREFLIGHT", "PATCH_PATH", f"patch input not found: {src}")

    if src.suffix not in (".patch", ".zip"):
        raise RunnerError(
            "PREFLIGHT", "PATCH_PATH", f"unified patch input must be .patch or .zip: {src}"
        )

    logger.line(f"UNIFIED_PATCH bundle_start input={src.name}")

    patch_entries: list[tuple[str, bytes]] = []
    if src.suffix == ".patch":
        data = src.read_bytes()
        if getattr(policy, "ascii_only_patch", False):
            _ascii_check_bytes(data, label=str(src))
        patch_entries.append((src.name, data))
    else:
        import zipfile

        with zipfile.ZipFile(src, "r") as z:
            names = [n for n in z.namelist() if n.endswith(".patch")]
            names = sorted(names)
            for n in names:
                pn = Path(n)
                if pn.is_absolute() or ".." in pn.parts:
                    continue
                data = z.read(n)
                if getattr(policy, "ascii_only_patch", False):
                    _ascii_check_bytes(data, label=f"{src.name}:{n}")
                safe_name = pn.as_posix().replace("/", "__")
                patch_entries.append((safe_name, data))

    applied_ok = 0
    applied_fail = 0
    failures: list[UnifiedPatchFailure] = []
    declared_all: set[str] = set()
    touched_all: set[str] = set()

    strip_cfg = getattr(policy, "unified_patch_strip", None)
    for name, data in patch_entries:
        text = data.decode("utf-8", errors="replace")
        raw_paths = _parse_unified_header_paths(text)

        logger.section("UNIFIED PATCH (attempt)")
        logger.line(f"patch_name={name}")
        logger.line(f"UNIFIED_PATCH attempt_start name={name}")
        if strip_cfg is not None:
            strip: int | None = int(strip_cfg)
            logger.line(f"patch_strip={strip} (config)")
        else:
            strip = _infer_strip_depth(workspace_repo, raw_paths)
            if strip is None:
                logger.line("patch_strip=AMBIGUOUS")
            else:
                logger.line(f"patch_strip={strip} (inferred)")

        if strip is None:
            logger.error_core(f"UNIFIED_PATCH strip=AMBIGUOUS name={name}")
        else:
            logger.line(f"UNIFIED_PATCH strip={strip} name={name}")
        touched_resolved = _resolve_touched_best_effort(
            workspace_repo, raw_paths, strip=(strip if isinstance(strip, int) else None)
        )
        for p in touched_resolved:
            touched_all.add(p)
        for p in touched_resolved:
            declared_all.add(p)

        if strip is None:
            applied_fail += 1
            reason = (
                "ambiguous strip depth; set unified_patch_strip (or --patch-strip) to disambiguate"
            )
            logger.line(f"result=FAIL reason={reason}")
            logger.error_core(f"UNIFIED_PATCH result=FAIL name={name} reason={reason}")
            failures.append(UnifiedPatchFailure(name=name, data=data, reason=reason))
            continue

        rewritten_text, rewritten_touched = _rewrite_patch_paths(text, strip=strip)
        for p in rewritten_touched:
            touched_all.add(p)
            declared_all.add(p)

        patch_path = (workspace_repo / ".am_patch" / "inputs" / name).resolve()
        _write_atomic(patch_path, rewritten_text.encode("utf-8"))

        patch_rel = patch_path.relative_to(workspace_repo)
        git_argv = ["git", "apply", "--whitespace=nowarn", str(patch_rel)]
        if getattr(policy, "patch_jail", False):
            cmd = _build_bwrap_cmd(
                workspace_repo=workspace_repo,
                argv=git_argv,
                unshare_net=getattr(policy, "patch_jail_unshare_net", True),
            )
            try:
                r = logger.run_logged(cmd, cwd=workspace_repo)
            except FileNotFoundError as e:
                raise RunnerError(
                    "PREFLIGHT",
                    "BWRAP",
                    "bwrap not found (install bubblewrap or disable patch_jail)",
                ) from e
        else:
            r = logger.run_logged(git_argv, cwd=workspace_repo)
        if r.returncode != 0:
            applied_fail += 1
            reason = f"git apply failed (rc={r.returncode})"
            logger.line(f"result=FAIL reason={reason}")
            logger.error_core(f"UNIFIED_PATCH result=FAIL name={name} reason={reason}")
            failures.append(UnifiedPatchFailure(name=name, data=data, reason=reason))
            continue

        applied_ok += 1
        logger.line("result=OK")
        logger.line(f"UNIFIED_PATCH result=OK name={name}")

    declared_files = sorted({p for p in declared_all if p and p != "/dev/null"})
    touched_files = sorted({p for p in touched_all if p and p != "/dev/null"})

    logger.section("UNIFIED PATCH (summary)")
    logger.line(f"UNIFIED_PATCH summary applied_ok={applied_ok} applied_fail={applied_fail}")
    logger.line(f"applied_ok={applied_ok}")
    logger.line(f"applied_fail={applied_fail}")
    logger.line("declared_files=" + ",".join(declared_files))
    logger.line("touched_files=" + ",".join(touched_files))
    if failures:
        logger.warning_core(f"UNIFIED_PATCH failures_exist count={len(failures)}")
        logger.line("failed_patches=" + ",".join([f.name for f in failures]))

    return UnifiedPatchResult(
        applied_ok=applied_ok,
        applied_fail=applied_fail,
        declared_files=declared_files,
        touched_files=touched_files,
        failures=failures,
    )
