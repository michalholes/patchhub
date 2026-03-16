from __future__ import annotations


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


def _path_has_prefix(path: str, prefix: str) -> bool:
    if not prefix:
        return False
    if path == prefix:
        return True
    return path.startswith(prefix + "/")


def _docs_gate_is_watched(
    decision_paths: list[str],
    *,
    include: list[str],
    exclude: list[str],
) -> tuple[bool, str | None]:
    inc = _norm_rel_paths(include)
    exc = _norm_rel_paths(exclude)
    paths = _norm_rel_paths(decision_paths)

    for path in paths:
        if any(_path_has_prefix(path, item) for item in exc):
            continue
        if any(_path_has_prefix(path, item) for item in inc):
            return True, path
    return False, None


def _norm_docs_required_prefixes(required_files: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in required_files:
        display = str(raw).strip().replace("\\", "/")
        if display.startswith("./"):
            display = display[2:]
        display = display.lstrip("/")
        prefix = _norm_rel_path(raw)
        if not display or not prefix or prefix in seen:
            continue
        seen.add(prefix)
        out.append((display, prefix))
    return out


def _norm_changed_entries(
    changed_entries: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for status, path in changed_entries or []:
        norm_status = str(status).strip()
        norm_path = _norm_rel_path(path)
        item = (norm_status, norm_path)
        if not norm_status or not norm_path or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _docs_gate_has_added_fragment(
    changed_entries: list[tuple[str, str]],
    *,
    required_prefix: str,
    decision_path_set: set[str],
) -> bool:
    for status, path in changed_entries:
        if path not in decision_path_set:
            continue
        if status != "??" and not status.startswith("A"):
            continue
        if _path_has_prefix(path, required_prefix):
            return True
    return False


def check_docs_gate(
    decision_paths: list[str],
    *,
    include: list[str],
    exclude: list[str],
    required_files: list[str],
    changed_entries: list[tuple[str, str]] | None = None,
) -> tuple[bool, list[str], str | None]:
    """Return (ok, missing_required, trigger_path).

    The gate triggers only if at least one changed path matches include and does not match
    exclude. If triggered, each required docs prefix must contain an added or untracked
    changed path from this run.
    """
    triggered, trigger_path = _docs_gate_is_watched(
        decision_paths, include=include, exclude=exclude
    )
    if not triggered:
        return True, [], None

    decision_path_set = set(_norm_rel_paths(decision_paths))
    required = _norm_docs_required_prefixes(required_files)
    entries = _norm_changed_entries(changed_entries)
    missing = [
        display
        for display, prefix in required
        if not _docs_gate_has_added_fragment(
            entries, required_prefix=prefix, decision_path_set=decision_path_set
        )
    ]
    return len(missing) == 0, missing, trigger_path
