from __future__ import annotations


def fs_junk_ignore_partition(
    paths: list[str],
    *,
    ignore_prefixes: tuple[str, ...] | list[str],
    ignore_suffixes: tuple[str, ...] | list[str],
    ignore_contains: tuple[str, ...] | list[str],
) -> tuple[list[str], list[str]]:
    """Partition paths into (kept, ignored) for workspace->live promotion hygiene."""
    prefixes = tuple(ignore_prefixes)
    suffixes = tuple(ignore_suffixes)
    contains = tuple(ignore_contains)
    kept: list[str] = []
    ignored: list[str] = []
    for p in paths:
        pp = p.strip()
        if not pp:
            continue
        is_ignored = False
        for pre in prefixes:
            if pp == pre.rstrip("/") or pp.startswith(pre):
                is_ignored = True
                break
        if not is_ignored and any(c in pp for c in contains):
            is_ignored = True
        if not is_ignored:
            for suf in suffixes:
                if pp.endswith(suf):
                    is_ignored = True
                    break
        if is_ignored:
            ignored.append(pp)
        else:
            kept.append(pp)

    # unique preserve order
    def _uniq(xs: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in xs:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    return _uniq(kept), _uniq(ignored)
