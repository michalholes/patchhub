from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from badguys.bdg_loader import BdgTest, load_bdg_test


@dataclass(frozen=True)
class SuitePolicy:
    commit_limit: int
    guard_test_name: str
    require_guard_test: bool
    abort_on_guard_fail: bool


@dataclass(frozen=True)
class TestDef:
    name: str
    makes_commit: bool
    is_guard: bool
    run: Callable[..., object]


class TestList(list[TestDef]):
    commit_limit: int
    abort_on_guard_fail: bool


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _policy_from_config(
    repo_root: Path,
    config_path: Path,
    cli_commit_limit: int | None,
    cli_include: list[str],
    cli_exclude: list[str],
) -> tuple[SuitePolicy, list[str], list[str]]:
    raw = _load_toml(repo_root / config_path)
    suite = raw.get("suite", {})
    guard = raw.get("guard", {})
    filters = raw.get("filters", {})

    commit_limit = int(
        cli_commit_limit if cli_commit_limit is not None else suite.get("commit_limit", 1)
    )
    require_guard_test = bool(guard.get("require_guard_test", True))
    guard_test_name = str(guard.get("guard_test_name", "test_000_test_mode_smoke"))
    abort_on_guard_fail = bool(guard.get("abort_on_guard_fail", True))

    include = list(filters.get("include", [])) + list(cli_include)
    exclude = list(filters.get("exclude", [])) + list(cli_exclude)

    return (
        SuitePolicy(
            commit_limit=commit_limit,
            guard_test_name=guard_test_name,
            require_guard_test=require_guard_test,
            abort_on_guard_fail=abort_on_guard_fail,
        ),
        include,
        exclude,
    )


def _load_test_from_bdg_file(path: Path) -> TestDef | None:
    bdg = load_bdg_test(path)

    def _run(_ctx) -> BdgTest:
        return bdg

    return TestDef(
        name=bdg.test_id,
        makes_commit=bdg.makes_commit,
        is_guard=bdg.is_guard,
        run=_run,
    )


def discover_tests(
    *,
    repo_root: Path,
    config_path: Path,
    cli_commit_limit: int | None,
    cli_include: list[str],
    cli_exclude: list[str],
) -> TestList:
    policy, include, exclude = _policy_from_config(
        repo_root, config_path, cli_commit_limit, cli_include, cli_exclude
    )

    tests_dir = repo_root / "badguys" / "tests"
    tests: list[TestDef] = []
    for p in sorted(tests_dir.glob("*.bdg")):
        t = _load_test_from_bdg_file(p)
        if t is not None:
            tests.append(t)

    all_tests = list(tests)

    if include and exclude:
        overlap = sorted(set(include).intersection(exclude))
        if overlap:
            joined = ", ".join(overlap)
            raise SystemExit(f"FAIL: include/exclude conflict: {joined}")

    if include:
        keep = set(include)
        tests = [t for t in tests if t.name in keep]

    if exclude:
        drop = set(exclude)
        tests = [t for t in tests if t.name not in drop]

    if policy.require_guard_test:
        if policy.guard_test_name in set(exclude):
            raise SystemExit(f"FAIL: guard test excluded but required: {policy.guard_test_name}")

        if policy.guard_test_name not in {t.name for t in tests}:
            injected = next((t for t in all_tests if t.name == policy.guard_test_name), None)
            if injected is None:
                raise SystemExit(f"FAIL: guard test not found: {policy.guard_test_name}")
            tests = [injected] + tests

        guard = [t for t in tests if t.name == policy.guard_test_name]
        rest = [t for t in tests if t.name != policy.guard_test_name]
        tests = guard + rest

    out = TestList(tests)
    out.commit_limit = policy.commit_limit
    out.abort_on_guard_fail = policy.abort_on_guard_fail
    return out
