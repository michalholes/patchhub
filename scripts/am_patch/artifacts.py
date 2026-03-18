from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from am_patch import git_ops
from am_patch.archive import make_failure_zip
from am_patch.errors import RunnerError
from am_patch.failure_zip import (
    cleanup_for_issue as cleanup_failure_zips_for_issue,
)
from am_patch.failure_zip import (
    effective_issue_id as effective_failure_zip_issue_id,
)
from am_patch.failure_zip import (
    render_name as render_failure_zip_name,
)
from am_patch.issue_diff import (
    collect_issue_logs,
    derive_finalize_pseudo_issue_id,
    make_issue_diff_zip,
)
from am_patch.root_model import canonical_target_repo_name_from_root


@dataclass(frozen=True)
class ArtifactSummary:
    success_zip: Path | None
    failure_zip: Path | None
    issue_diff_zip: Path | None


def build_artifacts(
    *,
    logger: Any,
    cli: Any,
    policy: Any,
    paths: Any,
    repo_root: Path,
    log_path: Path,
    exit_code: int,
    unified_mode: bool,
    patch_applied_successfully: bool,
    archived_patch: Path | None,
    failed_patch_blobs_for_zip: list[tuple[str, bytes]],
    files_for_fail_zip: list[str],
    ws_repo_for_fail_zip: Path,
    issue_diff_base_sha: str | None,
    issue_diff_paths: list[str],
    ws_attempt: int | None,
) -> ArtifactSummary:
    success_zip: Path | None = None
    failure_zip: Path | None = None
    issue_diff_zip: Path | None = None

    if exit_code == 0:
        repo_name = repo_root.name
        branch_name = git_ops.current_branch(logger, repo_root).strip()
        if branch_name == "HEAD":
            branch_name = "detached"

        issue = str(cli.issue_id) if cli.issue_id is not None else "noissue"
        epoch_s = git_ops.head_commit_epoch_s(logger, repo_root)
        ts = git_ops.format_epoch_utc_ts(epoch_s)

        template = policy.success_archive_name
        try:
            rendered = template.format(
                repo=repo_name,
                branch=branch_name,
                issue=issue,
                ts=ts,
            )
        except Exception as e:
            raise RunnerError(
                "POSTHOOK",
                "CONFIG",
                f"invalid success_archive_name template: {template!r} ({e!r})",
            ) from e

        name = Path(rendered).name
        if not name.lower().endswith(".zip"):
            name = f"{name}.zip"

        target_dir = paths.patch_dir
        if getattr(policy, "success_archive_dir", "patch_dir") == "successful_dir":
            target_dir = paths.successful_dir

        success_zip = target_dir / name
        git_ops.git_archive(logger, repo_root, success_zip, treeish="HEAD")

        keep_count = int(getattr(policy, "success_archive_keep_count", 0))
        glob_template = str(getattr(policy, "success_archive_cleanup_glob_template", "")).strip()
        if glob_template:
            candidates = [p for p in target_dir.glob(glob_template) if p.is_file()]
            candidates = sorted(candidates, key=lambda p: p.name)
            candidates = [p for p in candidates if p.resolve() != success_zip.resolve()]
            while len(candidates) > keep_count:
                doomed = candidates.pop(0)
                with contextlib.suppress(FileNotFoundError):
                    doomed.unlink()

        logger.line(f"issue_diff_base_sha={issue_diff_base_sha}")
        logger.line(f"issue_diff_paths_count={len(issue_diff_paths)}")

        if issue_diff_base_sha is None:
            raise RunnerError("POSTHOOK", "DIFF", "missing issue_diff_base_sha")

        if cli.issue_id is not None:
            issue_id = cli.issue_id
            logs = collect_issue_logs(
                logs_dir=paths.logs_dir,
                issue_id=issue_id,
                issue_template=policy.log_template_issue,
            )
        else:
            issue_id = derive_finalize_pseudo_issue_id(
                log_path=log_path,
                finalize_template=policy.log_template_finalize,
            )
            logs = [log_path]

        make_issue_diff_zip(
            logger=logger,
            repo_root=repo_root,
            artifacts_dir=paths.artifacts_dir,
            logs_dir=paths.logs_dir,
            base_sha=issue_diff_base_sha,
            issue_id=issue_id,
            files_to_promote=issue_diff_paths,
            log_paths=logs,
        )
        issue_diff_zip = None
    else:
        pseudo_issue_id: str | None = None
        if cli.issue_id is None:
            pseudo_issue_id = derive_finalize_pseudo_issue_id(
                log_path=log_path,
                finalize_template=policy.log_template_finalize,
            )

        issue = effective_failure_zip_issue_id(
            issue_id=cli.issue_id,
            pseudo_issue_id=pseudo_issue_id,
        )
        cleanup_failure_zips_for_issue(
            patch_dir=paths.patch_dir,
            policy=policy,
            issue=issue,
        )

        name = render_failure_zip_name(
            policy=policy,
            issue=issue,
            log_path=log_path,
            attempt=ws_attempt,
        )
        failure_zip = paths.patch_dir / name

        include_patch_paths: list[Path] = []
        include_patch_blobs: list[tuple[str, bytes]] = []

        if (
            not patch_applied_successfully
            and archived_patch is not None
            and archived_patch.exists()
            and not unified_mode
        ):
            include_patch_paths.append(archived_patch)

        for name, data in failed_patch_blobs_for_zip:
            include_patch_blobs.append((name, data))

        make_failure_zip(
            logger,
            failure_zip,
            workspace_repo=ws_repo_for_fail_zip,
            log_path=log_path,
            include_repo_files=files_for_fail_zip,
            include_patch_blobs=include_patch_blobs,
            include_patch_paths=include_patch_paths,
            target_repo_name=canonical_target_repo_name_from_root(repo_root),
            log_dir_name=policy.failure_zip_log_dir,
            patch_dir_name=policy.failure_zip_patch_dir,
        )

        # Enforce final retention state after writing the newest failure zip.
        cleanup_failure_zips_for_issue(
            patch_dir=paths.patch_dir,
            policy=policy,
            issue=issue,
        )

    return ArtifactSummary(
        success_zip=success_zip,
        failure_zip=failure_zip,
        issue_diff_zip=issue_diff_zip,
    )
