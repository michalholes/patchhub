#!/usr/bin/env python3
"""Standalone helper: sync GitHub issues into deterministic markdown archives.

Hard constraints:
- NOT part of AudioMason runtime/CLI
- NO imports from audiomason
- Non-interactive
- Deterministic + idempotent

This tool writes:
- docs/issues/open_issues.md
- docs/issues/closed_issues.md
- docs/issues/all_issues.yaml


Typical location: `/home/pi/audiomason2`.
Example: `python3 /home/pi/audiomason2/scripts/sync_issues_archive.py`
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
OUT_OPEN = ROOT / "docs/issues/open_issues.md"
OUT_CLOSED = ROOT / "docs/issues/closed_issues.md"
OUT_ALL = ROOT / "docs/issues/all_issues.yaml"

COMMIT_MESSAGE = "Docs: sync GitHub issues archive (open/closed)"


def _obj_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _str_or(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _json_loads(raw: str) -> object:
    return cast(object, json.loads(raw))


def _int_like(value: object) -> int:
    if isinstance(value, (int, str)):
        return int(value)
    raise TypeError(f"Expected int-like value, got {type(value).__name__}")


def _int_or_zero(value: object) -> int:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        raise SystemExit(p.returncode)
    return p.stdout


def autodetect_repo(_run: Callable[[list[str]], str]) -> str:
    out = _run(["gh", "repo", "view", "--json", "nameWithOwner"]).strip()
    data = _obj_dict(_json_loads(out))
    if data is None:
        raise SystemExit("ERROR: gh repo view returned invalid JSON (expected object)")
    repo_any = data.get("nameWithOwner")
    if not isinstance(repo_any, str) or not repo_any:
        raise SystemExit("ERROR: gh repo view returned no nameWithOwner")
    return repo_any


def load_issues(repo: str, _run: Callable[[list[str]], str]) -> list[dict[str, object]]:
    raw = _run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,title,state,labels,assignees,milestone,createdAt,updatedAt,closedAt,body",
        ]
    )
    data_raw = _json_loads(raw)
    if not isinstance(data_raw, list):
        raise SystemExit("ERROR: gh issue list returned invalid JSON (expected list)")
    data = cast(list[object], data_raw)
    out_issues: list[dict[str, object]] = []
    for item in data:
        item_dict = _obj_dict(item)
        if item_dict is None:
            raise SystemExit(
                "ERROR: gh issue list returned invalid JSON (expected list of objects)"
            )
        out_issues.append(item_dict)
    return out_issues


def _names(items: object) -> str:
    if not isinstance(items, list):
        return "--"
    item_list = cast(list[object], items)
    names: list[str] = []
    for item in item_list:
        item_dict = _obj_dict(item)
        if item_dict is None:
            continue
        name = item_dict.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return ", ".join(names) if names else "--"


def split_and_sort(
    issues: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    def open_key(issue: dict[str, object]) -> int:
        return _int_like(issue.get("number"))

    def closed_key(issue: dict[str, object]) -> tuple[str, int]:
        return _str_or(issue.get("closedAt")), _int_like(issue.get("number"))

    open_issues: list[dict[str, object]] = [i for i in issues if i.get("state") == "OPEN"]
    closed_issues: list[dict[str, object]] = [i for i in issues if i.get("state") == "CLOSED"]
    open_issues = sorted(open_issues, key=open_key)
    closed_issues = sorted(closed_issues, key=closed_key, reverse=True)
    return open_issues, closed_issues


def render_issue(i: dict[str, object]) -> str:
    num = i["number"]
    title = _str_or(i.get("title"))
    state = _str_or(i.get("state"))
    labels = _names(i.get("labels"))
    assignees = _names(i.get("assignees"))
    milestone_obj = _obj_dict(i.get("milestone"))
    milestone = _str_or(milestone_obj.get("title")) if milestone_obj else "--"
    created = _str_or(i.get("createdAt"))
    updated = _str_or(i.get("updatedAt"))
    body = _str_or(i.get("body"))
    lines: list[str] = []
    lines.append(f"## #{num} - {title}")
    lines.append(f"- State: **{state}**")
    lines.append(f"- Labels: {labels}")
    lines.append(f"- Assignees: {assignees}")
    lines.append(f"- Milestone: {milestone}")
    lines.append(f"- Created: {created}")
    lines.append(f"- Updated: {updated}")
    if state == "CLOSED":
        lines.append(f"- Closed: {_str_or(i.get('closedAt'))}")
    lines.append("")
    lines.append(body)
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_archive(title: str, issues: list[dict[str, object]]) -> str:
    parts: list[str] = [f"# {title}", ""]
    for i in issues:
        parts.append(render_issue(i))
    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text


def ensure_clean_git(_run: Callable[[list[str]], str], allow_dirty: bool) -> None:
    if allow_dirty:
        return
    if _run(["git", "status", "--porcelain"]).strip():
        raise SystemExit("ERROR: dirty working tree")


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    p.write_text(s, encoding="utf-8")


def _gh_api_json(
    _run: Callable[[list[str]], str], path: str, *, headers: list[str] | None = None
) -> object:
    cmd = ["gh", "api"]
    if headers:
        for h in headers:
            cmd.extend(["-H", h])
    cmd.append(path)
    raw = _run(cmd)
    try:
        return _json_loads(raw)
    except json.JSONDecodeError as err:
        raise SystemExit(f"ERROR: failed to parse gh api output as JSON for {path}") from err


def _gh_api_paginated_list(
    _run: Callable[[list[str]], str],
    path: str,
    *,
    headers: list[str] | None = None,
    per_page: int = 100,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        page_path = f"{path}{sep}per_page={per_page}&page={page}"
        data = _gh_api_json(_run, page_path, headers=headers)
        if not isinstance(data, list):
            raise SystemExit(f"ERROR: expected list from gh api for {page_path}")
        if not data:
            break
        for item in cast(list[object], data):
            item_dict = _obj_dict(item)
            if item_dict is not None:
                out.append(item_dict)
        page += 1
    return out


def _user_stub(u: object) -> dict[str, object] | None:
    user = _obj_dict(u)
    if user is None:
        return None
    login = user.get("login")
    uid = user.get("id")
    if login is None and uid is None:
        return None
    d: dict[str, object] = {}
    if login is not None:
        d["login"] = login
    if uid is not None:
        d["id"] = uid
    return d


def _sort_by_created_at(items: list[dict[str, object]]) -> list[dict[str, object]]:
    def key(x: dict[str, object]) -> tuple[str, str, int]:
        created = _str_or(x.get("created_at"), _str_or(x.get("createdAt")))
        event = _str_or(x.get("event"))
        iid = _int_or_zero(x.get("id"))
        return (created, event, iid)

    return sorted(items, key=key)


def _issue_core_export(issue: dict[str, object]) -> dict[str, object]:
    ms = _obj_dict(issue.get("milestone"))
    labels: list[dict[str, object]] = []
    labels_raw = issue.get("labels")
    if isinstance(labels_raw, list):
        for label in cast(list[object], labels_raw):
            label_obj = _obj_dict(label)
            if label_obj is None:
                continue
            label_name = label_obj.get("name")
            if label_name:
                labels.append({"name": label_name})

    assignees: list[dict[str, object]] = []
    assignees_raw = issue.get("assignees")
    if isinstance(assignees_raw, list):
        for assignee in cast(list[object], assignees_raw):
            assignee_stub = _user_stub(assignee)
            if assignee_stub is not None:
                assignees.append(assignee_stub)

    out: dict[str, object] = {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "html_url": issue.get("html_url"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "user": _user_stub(issue.get("user")),
        "closed_by": _user_stub(issue.get("closed_by")),
        "labels": labels,
        "assignees": assignees,
        "milestone": None,
        "body": issue.get("body"),
    }
    if ms is not None:
        out["milestone"] = {
            "title": ms.get("title"),
            "number": ms.get("number"),
            "state": ms.get("state"),
        }
    return out


def _comment_export(c: dict[str, object]) -> dict[str, object]:
    return {
        "id": c.get("id"),
        "html_url": c.get("html_url"),
        "user": _user_stub(c.get("user")),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "body": c.get("body"),
    }


def _timeline_event_export(e: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {
        "id": e.get("id"),
        "event": e.get("event"),
        "created_at": e.get("created_at"),
        "actor": _user_stub(e.get("actor")),
    }
    # Common fields used by "referenced" events
    if "commit_id" in e:
        out["commit_id"] = e.get("commit_id")
    if "commit_url" in e:
        out["commit_url"] = e.get("commit_url")
    # Some events include nested source.commit
    src = _obj_dict(e.get("source"))
    commit = _obj_dict(src.get("commit")) if src is not None else None
    if commit is not None:
        out["source"] = {
            "commit": {
                "sha": commit.get("sha"),
                "html_url": commit.get("html_url"),
            }
        }
    return out


def _yaml_scalar(v: object) -> str:
    # YAML 1.2 JSON-subset (safe + deterministic)
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _yaml_dump(obj: object, indent: int = 0) -> str:
    sp = "  " * indent
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return sp + _yaml_scalar(obj)
    if isinstance(obj, list):
        items = cast(list[object], obj)
        if not items:
            return sp + "[]"
        lines: list[str] = []
        for item in items:
            if item is None or isinstance(item, (bool, int, float, str)):
                lines.append(sp + "- " + _yaml_scalar(item))
            else:
                lines.append(sp + "-")
                lines.append(_yaml_dump(item, indent + 1))
        return "\n".join(lines)
    if isinstance(obj, dict):
        values = cast(dict[str, object], obj)
        if not values:
            return sp + "{}"
        dict_lines: list[str] = []
        for k in sorted(values.keys()):
            v = values[k]
            if v is None or isinstance(v, (bool, int, float, str)):
                dict_lines.append(f"{sp}{k}: {_yaml_scalar(v)}")
            else:
                dict_lines.append(f"{sp}{k}:")
                dict_lines.append(_yaml_dump(v, indent + 1))
        return "\n".join(dict_lines)
    return sp + _yaml_scalar(str(obj))


def build_all_issues_yaml(
    repo: str, issues: list[dict[str, object]], _run: Callable[[list[str]], str]
) -> str:
    nums: list[int] = []
    seen: set[int] = set()
    for i in issues:
        n_any = i.get("number")
        n: int | None = None
        if isinstance(n_any, int):
            n = n_any
        elif isinstance(n_any, str):
            try:
                n = int(n_any)
            except ValueError:
                n = None
        if n is not None and n not in seen:
            seen.add(n)
            nums.append(n)
    nums.sort()

    headers_core = [
        "Accept: application/vnd.github+json",
        "X-GitHub-Api-Version: 2022-11-28",
    ]
    headers_timeline = [
        "Accept: application/vnd.github.mockingbird-preview+json",
        "X-GitHub-Api-Version: 2022-11-28",
    ]

    issues_out: list[dict[str, object]] = []
    for n in nums:
        core = _gh_api_json(_run, f"repos/{repo}/issues/{n}", headers=headers_core)
        if not isinstance(core, dict):
            raise SystemExit(f"ERROR: expected issue object from gh api for #{n}")
        core_issue = cast(dict[str, object], core)

        comments = _gh_api_paginated_list(
            _run, f"repos/{repo}/issues/{n}/comments", headers=headers_core
        )
        timeline = _gh_api_paginated_list(
            _run, f"repos/{repo}/issues/{n}/timeline", headers=headers_timeline
        )

        comments_sorted = _sort_by_created_at(comments)
        timeline_sorted = _sort_by_created_at(timeline)

        issues_out.append(
            {
                "issue": _issue_core_export(core_issue),
                "comments": [_comment_export(c) for c in comments_sorted],
                "timeline": [_timeline_event_export(e) for e in timeline_sorted],
            }
        )

    payload: dict[str, object] = {"repo": repo, "issues": issues_out}
    return _yaml_dump(payload) + "\n"


class _Args(Protocol):
    repo: str | None
    dry_run: bool
    no_commit: bool
    no_push: bool
    allow_dirty: bool


def main(
    argv: list[str] | None = None,
    *,
    _run: Callable[[list[str]], str] = run,
    _load_issues: Callable[
        [str, Callable[[list[str]], str]],
        list[dict[str, object]],
    ] = load_issues,
    _autodetect_repo: Callable[[Callable[[list[str]], str]], str] = autodetect_repo,
) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    args = cast(_Args, ap.parse_args(argv))

    ensure_clean_git(_run, args.allow_dirty)
    repo = args.repo or _autodetect_repo(_run)

    issues = _load_issues(repo, _run)
    open_issues, closed_issues = split_and_sort(issues)

    open_md = render_archive("Open Issues", open_issues)
    closed_md = render_archive("Closed Issues", closed_issues)
    all_yaml = build_all_issues_yaml(repo, issues, _run)

    if (
        OUT_OPEN.exists()
        and OUT_CLOSED.exists()
        and OUT_ALL.exists()
        and read_text(OUT_OPEN) == open_md
        and read_text(OUT_CLOSED) == closed_md
        and read_text(OUT_ALL) == all_yaml
    ):
        print("No changes.")
        return 0

    if args.dry_run:
        print("DRY RUN: changes detected")
        return 0

    write_text(OUT_OPEN, open_md)
    write_text(OUT_CLOSED, closed_md)
    write_text(OUT_ALL, all_yaml)

    if args.no_commit:
        return 0

    _run(["git", "add", str(OUT_OPEN), str(OUT_CLOSED), str(OUT_ALL)])
    _run(["git", "commit", "-m", COMMIT_MESSAGE])

    if args.no_push:
        return 0

    _run(["git", "push"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
