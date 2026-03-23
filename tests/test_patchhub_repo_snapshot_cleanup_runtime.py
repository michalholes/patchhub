from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.patchhub.asgi.asgi_app import run_patch_job_success_cleanup
from scripts.patchhub.asgi.operator_info_runtime import (
    append_cleanup_recent_status,
    load_operator_info,
)
from scripts.patchhub.repo_snapshot_cleanup import (
    RepoSnapshotCleanupConfig,
    RepoSnapshotCleanupRule,
    execute_repo_snapshot_cleanup,
)


def _write_zip(path: Path, *, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"zip")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _config(*rules: tuple[str, int]) -> RepoSnapshotCleanupConfig:
    return RepoSnapshotCleanupConfig(
        rules=tuple(
            RepoSnapshotCleanupRule(filename_pattern=pattern, keep_count=keep_count)
            for pattern, keep_count in rules
        )
    )


def _summary(job_id: str, created_utc: str) -> SimpleNamespace:
    return SimpleNamespace(
        to_json=lambda: {
            "job_id": job_id,
            "issue_id": "375",
            "created_utc": created_utc,
            "deleted_count": 0,
            "rules": [],
            "summary_text": "Repo snapshot cleanup: deleted 0 file(s)",
        }
    )


def test_cleanup_retains_each_rule_family_independently(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    _write_zip(patches_root / "patchhub-main_1.zip", mtime_ns=10)
    _write_zip(patches_root / "patchhub-main_2.zip", mtime_ns=20)
    _write_zip(patches_root / "patchhub-main_3.zip", mtime_ns=30)
    _write_zip(patches_root / "audiomason2-main_1.zip", mtime_ns=40)
    _write_zip(patches_root / "audiomason2-main_2.zip", mtime_ns=50)

    summary = execute_repo_snapshot_cleanup(
        patches_root=patches_root,
        config=_config(("patchhub-main_*.zip", 2), ("audiomason2-main_*.zip", 1)),
        job_id="job-375-a",
        issue_id="375",
        created_utc="2026-03-23T10:00:00Z",
    )

    remaining = sorted(path.name for path in patches_root.iterdir())
    assert remaining == [
        "audiomason2-main_2.zip",
        "patchhub-main_2.zip",
        "patchhub-main_3.zip",
    ]
    assert summary.deleted_count == 2
    assert [rule.deleted_count for rule in summary.rules] == [1, 1]


def test_cleanup_uses_first_matching_rule_only(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    _write_zip(patches_root / "patchhub-main_1.zip", mtime_ns=10)
    _write_zip(patches_root / "patchhub-main_2.zip", mtime_ns=20)

    summary = execute_repo_snapshot_cleanup(
        patches_root=patches_root,
        config=_config(("*-main_*.zip", 1), ("patchhub-main_*.zip", 0)),
        job_id="job-375-b",
        issue_id="375",
        created_utc="2026-03-23T10:00:01Z",
    )

    remaining = sorted(path.name for path in patches_root.iterdir())
    assert remaining == ["patchhub-main_2.zip"]
    assert [rule.matched_count for rule in summary.rules] == [2, 0]
    assert [rule.deleted_count for rule in summary.rules] == [1, 0]


def test_cleanup_sorting_is_mtime_desc_then_basename_asc(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    _write_zip(patches_root / "patchhub-main_b.zip", mtime_ns=10)
    _write_zip(patches_root / "patchhub-main_a.zip", mtime_ns=10)
    _write_zip(patches_root / "patchhub-main_c.zip", mtime_ns=5)

    execute_repo_snapshot_cleanup(
        patches_root=patches_root,
        config=_config(("patchhub-main_*.zip", 1)),
        job_id="job-375-c",
        issue_id="375",
        created_utc="2026-03-23T10:00:02Z",
    )

    remaining = sorted(path.name for path in patches_root.iterdir())
    assert remaining == ["patchhub-main_a.zip"]


def test_cleanup_scans_only_top_level_patch_zip_files(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    _write_zip(patches_root / "patchhub-main_top.zip", mtime_ns=10)
    _write_zip(patches_root / "incoming" / "patchhub-main_nested.zip", mtime_ns=20)
    _write_zip(patches_root / "workspaces" / "patchhub-main_ws.zip", mtime_ns=30)

    execute_repo_snapshot_cleanup(
        patches_root=patches_root,
        config=_config(("patchhub-main_*.zip", 0)),
        job_id="job-375-d",
        issue_id="375",
        created_utc="2026-03-23T10:00:03Z",
    )

    assert not (patches_root / "patchhub-main_top.zip").exists()
    assert (patches_root / "incoming" / "patchhub-main_nested.zip").exists()
    assert (patches_root / "workspaces" / "patchhub-main_ws.zip").exists()


def test_cleanup_ignores_symlinked_zip_children(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    symlink_target = tmp_path / "linked.zip"
    _write_zip(patches_root / "patchhub-main_real.zip", mtime_ns=10)
    _write_zip(symlink_target, mtime_ns=20)
    (patches_root / "patchhub-main_link.zip").parent.mkdir(parents=True, exist_ok=True)
    (patches_root / "patchhub-main_link.zip").symlink_to(symlink_target)

    summary = execute_repo_snapshot_cleanup(
        patches_root=patches_root,
        config=_config(("patchhub-main_*.zip", 0)),
        job_id="job-375-link",
        issue_id="375",
        created_utc="2026-03-23T10:00:03Z",
    )

    remaining = sorted(path.name for path in patches_root.iterdir())
    assert remaining == ["patchhub-main_link.zip"]
    assert summary.deleted_count == 1
    assert summary.rules[0].matched_count == 1


def test_cleanup_failure_summary_is_persisted_to_operator_info(tmp_path: Path) -> None:
    patches_root = tmp_path / "patches"
    failing = patches_root / "patchhub-main_2.zip"
    _write_zip(patches_root / "patchhub-main_1.zip", mtime_ns=10)
    _write_zip(failing, mtime_ns=20)

    original_unlink = Path.unlink

    def _raise_for_target(path: Path, *args: object, **kwargs: object) -> None:
        if path == failing:
            raise RuntimeError("boom")
        original_unlink(path, *args, **kwargs)

    with patch("pathlib.Path.unlink", autospec=True, side_effect=_raise_for_target):
        summary = execute_repo_snapshot_cleanup(
            patches_root=patches_root,
            config=_config(("patchhub-main_*.zip", 0)),
            job_id="job-375-e",
            issue_id="375",
            created_utc="2026-03-23T10:00:04Z",
        )
    append_cleanup_recent_status(patches_root, summary.to_json())

    operator_info = load_operator_info(patches_root)
    assert summary.deleted_count == 0
    assert "FAILED: RuntimeError: boom" in summary.summary_text
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-e"
    assert (
        "FAILED: RuntimeError: boom" in (operator_info["cleanup_recent_status"][-1]["summary_text"])
    )


def test_patch_success_cleanup_persists_before_rescan_after_append_failure(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("rescan")
            operator_info = load_operator_info(patches_root)
            assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-f"

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-f", issue_id="375")
    summary = _summary("job-375-f", "2026-03-23T10:00:05Z")

    with (
        patch(
            "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
            return_value=summary,
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app.append_cleanup_recent_status",
            side_effect=RuntimeError("append failed"),
        ),
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    operator_info = load_operator_info(patches_root)
    assert calls == ["rescan"]
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-f"


def test_patch_success_cleanup_uses_rebuild_fail_safe_after_force_rescan_error(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("force")
            operator_info = load_operator_info(patches_root)
            assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-g"
            raise RuntimeError("wake failed")

        async def _rebuild(self, *, reason: str) -> None:
            calls.append("rebuild:" + reason)
            operator_info = load_operator_info(patches_root)
            assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-g"

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-g", issue_id="375")
    summary = _summary("job-375-g", "2026-03-23T10:00:06Z")

    with patch(
        "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
        return_value=summary,
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    assert calls == ["force", "rebuild:patch_success_cleanup"]


def test_patch_success_cleanup_uses_direct_write_after_append_and_write_failure(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("rescan")
            operator_info = load_operator_info(patches_root)
            assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-h"

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-h", issue_id="375")
    summary = _summary("job-375-h", "2026-03-23T10:00:07Z")

    with (
        patch(
            "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
            return_value=summary,
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app.append_cleanup_recent_status",
            side_effect=RuntimeError("append boom"),
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app.write_operator_info",
            side_effect=RuntimeError("write boom"),
        ),
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    operator_info = load_operator_info(patches_root)
    assert calls == ["rescan"]
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-h"


def test_patch_success_cleanup_swallows_double_refresh_failure(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("force")
            raise RuntimeError("force boom")

        async def _rebuild(self, *, reason: str) -> None:
            calls.append("rebuild:" + reason)
            raise RuntimeError("rebuild boom")

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-i", issue_id="375")
    summary = _summary("job-375-i", "2026-03-23T10:00:08Z")

    with patch(
        "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
        return_value=summary,
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    operator_info = load_operator_info(patches_root)
    assert calls == ["force", "rebuild:patch_success_cleanup"]
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-i"


def test_patch_success_cleanup_uses_runtime_summary_after_all_write_paths_fail(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("rescan")
            operator_info = load_operator_info(patches_root)
            assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-j"

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-j", issue_id="375")
    summary = _summary("job-375-j", "2026-03-23T10:00:09Z")

    with (
        patch(
            "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
            return_value=summary,
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app.append_cleanup_recent_status",
            side_effect=RuntimeError("append boom"),
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app.write_operator_info",
            side_effect=RuntimeError("write boom"),
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app._write_cleanup_summary_record_direct",
            side_effect=RuntimeError("direct boom"),
        ),
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    operator_info = load_operator_info(patches_root)
    assert calls == ["rescan"]
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-j"


def test_patch_success_cleanup_installs_fallback_snapshot_after_double_refresh_failure(
    tmp_path: Path,
) -> None:
    patches_root = tmp_path / "patches"
    calls: list[str] = []
    installed_payloads: list[dict[str, object]] = []

    class _FakeIndexer:
        async def force_rescan(self) -> None:
            calls.append("force")
            raise RuntimeError("force boom")

        async def _rebuild(self, *, reason: str) -> None:
            calls.append("rebuild:" + reason)
            raise RuntimeError("rebuild boom")

        def install_external_snapshot_payload(self, payload: dict[str, object]) -> None:
            calls.append("install")
            installed_payloads.append(payload)

    core = SimpleNamespace(
        patches_root=patches_root,
        cfg=SimpleNamespace(repo_snapshot_cleanup=_config()),
        indexer=_FakeIndexer(),
    )
    job = SimpleNamespace(job_id="job-375-k", issue_id="375")
    summary = _summary("job-375-k", "2026-03-23T10:00:10Z")

    async def _legacy_payload(_core: object) -> dict[str, object]:
        operator_info = load_operator_info(patches_root)
        assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-k"
        return {
            "ok": True,
            "seq": 0,
            "snapshot": {
                "jobs": [],
                "runs": [],
                "patches": [],
                "workspaces": [],
                "header": {},
                "operator_info": operator_info,
            },
            "sigs": {
                "jobs": "jobs:s0",
                "runs": "runs:s0",
                "patches": "patches:s0",
                "workspaces": "workspaces:s0",
                "header": "header:s0",
                "operator_info": "operator_info:s0",
                "snapshot": "snapshot:s0",
            },
        }

    with (
        patch(
            "scripts.patchhub.asgi.asgi_app.execute_repo_snapshot_cleanup",
            return_value=summary,
        ),
        patch(
            "scripts.patchhub.asgi.asgi_app._legacy_snapshot_payload",
            side_effect=_legacy_payload,
        ),
    ):
        asyncio.run(run_patch_job_success_cleanup(core, job))

    operator_info = load_operator_info(patches_root)
    assert calls == ["force", "rebuild:patch_success_cleanup", "install"]
    assert operator_info["cleanup_recent_status"][-1]["job_id"] == "job-375-k"
    assert installed_payloads[0]["snapshot"]["operator_info"] == operator_info
