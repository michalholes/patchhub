from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .repo_snapshot_cleanup import (
    RepoSnapshotCleanupConfig,
    RepoSnapshotCleanupRule,
)


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    tail_max_bytes: int = 8_388_608
    tail_cache_max_entries: int = 32


@dataclass(frozen=True)
class MetaConfig:
    version: str


@dataclass(frozen=True)
class RunnerConfig:
    command: list[str]
    default_verbosity: str
    queue_enabled: bool
    runner_config_toml: str
    ipc_handshake_wait_s: int = 1
    post_exit_grace_s: int = 5
    terminate_grace_s: int = 3


@dataclass(frozen=True)
class PathsConfig:
    patches_root: str
    upload_dir: str
    allow_crud: bool
    crud_allowlist: list[str]


@dataclass(frozen=True)
class UploadConfig:
    max_bytes: int
    allowed_extensions: list[str]
    ascii_only_names: bool


@dataclass(frozen=True)
class IssueConfig:
    default_regex: str
    allocation_start: int
    allocation_max: int


@dataclass(frozen=True)
class IndexingConfig:
    log_filename_regex: str
    stats_windows_days: list[int]
    poll_interval_seconds: int = 2


@dataclass(frozen=True)
class UiConfig:
    base_font_px: int = 24
    drop_overlay_enabled: bool = True
    clear_output_on_autofill: bool = True
    show_autofill_clear_status: bool = True
    idle_auto_select_last_job: bool = False


@dataclass(frozen=True)
class AutofillConfig:
    enabled: bool
    poll_interval_seconds: int
    scan_dir: str
    scan_extensions: list[str]
    scan_ignore_filenames: list[str]
    scan_ignore_prefixes: list[str]
    choose_strategy: str
    tiebreaker: str
    derive_enabled: bool
    issue_regex: str
    commit_regex: str
    commit_replace_underscores: bool
    commit_replace_dashes: bool
    commit_collapse_spaces: bool
    commit_trim: bool
    commit_ascii_only: bool
    issue_default_if_no_match: str
    commit_default_if_no_match: str
    overwrite_policy: str
    fill_patch_path: bool
    fill_issue_id: bool
    fill_commit_message: bool
    zip_commit_enabled: bool
    zip_commit_filename: str
    zip_commit_max_bytes: int
    zip_commit_max_ratio: int
    zip_issue_enabled: bool
    zip_issue_filename: str
    zip_issue_max_bytes: int
    zip_issue_max_ratio: int
    scan_zip_require_patch: bool = False


@dataclass(frozen=True)
class TargetingConfig:
    default_target_repo: str = "patchhub"
    zip_target_prefill_enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    meta: MetaConfig
    runner: RunnerConfig
    paths: PathsConfig
    upload: UploadConfig
    issue: IssueConfig
    indexing: IndexingConfig
    ui: UiConfig
    autofill: AutofillConfig
    targeting: TargetingConfig = field(default_factory=TargetingConfig)
    repo_snapshot_cleanup: RepoSnapshotCleanupConfig = field(
        default_factory=RepoSnapshotCleanupConfig
    )


def _must_get(d: dict[str, Any], key: str) -> Any:
    if key not in d:
        raise KeyError(f"Missing required config key: {key}")
    return d[key]


def _must_int_at_least(value: Any, *, key: str, minimum: int) -> int:
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"Config key {key} must be >= {minimum}; got {parsed}")
    return parsed


def _parse_repo_snapshot_cleanup_rule(
    raw: Any,
    *,
    index: int,
) -> RepoSnapshotCleanupRule:
    prefix = f"repo_snapshot_cleanup.rules[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{prefix} must be a table")
    allowed = {"filename_pattern", "keep_count"}
    extra = sorted(str(key) for key in raw if str(key) not in allowed)
    if extra:
        raise ValueError(f"{prefix} contains unsupported keys: {', '.join(extra)}")

    pattern = raw.get("filename_pattern")
    if not isinstance(pattern, str):
        raise ValueError(f"{prefix}.filename_pattern must be a string")
    if not pattern:
        raise ValueError(f"{prefix}.filename_pattern must be non-empty")
    if not pattern.isascii():
        raise ValueError(f"{prefix}.filename_pattern must be ASCII-only")
    if "\n" in pattern or "\r" in pattern:
        raise ValueError(f"{prefix}.filename_pattern must be single-line")
    if "/" in pattern or "\\" in pattern:
        raise ValueError(f"{prefix}.filename_pattern must not contain separators")

    keep_count = raw.get("keep_count")
    if isinstance(keep_count, bool) or not isinstance(keep_count, int):
        raise ValueError(f"{prefix}.keep_count must be an integer")
    if keep_count < 0:
        raise ValueError(f"{prefix}.keep_count must be >= 0")
    return RepoSnapshotCleanupRule(
        filename_pattern=pattern,
        keep_count=int(keep_count),
    )


def _parse_repo_snapshot_cleanup(raw: Any) -> RepoSnapshotCleanupConfig:
    if raw is None:
        return RepoSnapshotCleanupConfig()
    if not isinstance(raw, dict):
        raise ValueError("repo_snapshot_cleanup must be a table")
    allowed = {"rules"}
    extra = sorted(str(key) for key in raw if str(key) not in allowed)
    if extra:
        raise ValueError("repo_snapshot_cleanup contains unsupported keys: " + ", ".join(extra))
    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("repo_snapshot_cleanup.rules must be an array of tables")
    rules = tuple(
        _parse_repo_snapshot_cleanup_rule(item, index=index) for index, item in enumerate(raw_rules)
    )
    return RepoSnapshotCleanupConfig(rules=rules)


def load_config(path: Path) -> AppConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    server = raw.get("server", {})
    meta = raw.get("meta", {})
    runner = raw.get("runner", {})
    paths = raw.get("paths", {})
    upload = raw.get("upload", {})
    issue = raw.get("issue", {})
    indexing = raw.get("indexing", {})
    ui = raw.get("ui", {})
    autofill = raw.get("autofill", {})
    targeting = raw.get("targeting", {})
    repo_snapshot_cleanup = _parse_repo_snapshot_cleanup(raw.get("repo_snapshot_cleanup"))

    return AppConfig(
        server=ServerConfig(
            host=str(_must_get(server, "host")),
            port=int(_must_get(server, "port")),
            tail_max_bytes=int(server.get("tail_max_bytes", 8_388_608)),
            tail_cache_max_entries=int(server.get("tail_cache_max_entries", 32)),
        ),
        meta=MetaConfig(
            version=str(meta.get("version", "0.0.0")),
        ),
        runner=RunnerConfig(
            command=list(_must_get(runner, "command")),
            default_verbosity=str(_must_get(runner, "default_verbosity")),
            queue_enabled=bool(_must_get(runner, "queue_enabled")),
            runner_config_toml=str(_must_get(runner, "runner_config_toml")),
            ipc_handshake_wait_s=_must_int_at_least(
                runner.get("ipc_handshake_wait_s", 1),
                key="runner.ipc_handshake_wait_s",
                minimum=1,
            ),
            post_exit_grace_s=_must_int_at_least(
                runner.get("post_exit_grace_s", 5),
                key="runner.post_exit_grace_s",
                minimum=1,
            ),
            terminate_grace_s=_must_int_at_least(
                runner.get("terminate_grace_s", 3),
                key="runner.terminate_grace_s",
                minimum=1,
            ),
        ),
        paths=PathsConfig(
            patches_root=str(_must_get(paths, "patches_root")),
            upload_dir=str(_must_get(paths, "upload_dir")),
            allow_crud=bool(_must_get(paths, "allow_crud")),
            crud_allowlist=list(_must_get(paths, "crud_allowlist")),
        ),
        upload=UploadConfig(
            max_bytes=int(_must_get(upload, "max_bytes")),
            allowed_extensions=list(_must_get(upload, "allowed_extensions")),
            ascii_only_names=bool(_must_get(upload, "ascii_only_names")),
        ),
        issue=IssueConfig(
            default_regex=str(_must_get(issue, "default_regex")),
            allocation_start=int(_must_get(issue, "allocation_start")),
            allocation_max=int(_must_get(issue, "allocation_max")),
        ),
        indexing=IndexingConfig(
            log_filename_regex=str(_must_get(indexing, "log_filename_regex")),
            stats_windows_days=list(_must_get(indexing, "stats_windows_days")),
            poll_interval_seconds=int(indexing.get("poll_interval_seconds", 2)),
        ),
        ui=UiConfig(
            base_font_px=int(ui.get("base_font_px", 24)),
            drop_overlay_enabled=bool(ui.get("drop_overlay_enabled", True)),
            clear_output_on_autofill=bool(ui.get("clear_output_on_autofill", True)),
            show_autofill_clear_status=bool(ui.get("show_autofill_clear_status", True)),
            idle_auto_select_last_job=bool(ui.get("idle_auto_select_last_job", False)),
        ),
        autofill=AutofillConfig(
            enabled=bool(autofill.get("enabled", True)),
            poll_interval_seconds=int(autofill.get("poll_interval_seconds", 10)),
            scan_dir=str(autofill.get("scan_dir", "patches")),
            scan_extensions=list(autofill.get("scan_extensions", [".zip", ".patch"])),
            scan_ignore_filenames=list(autofill.get("scan_ignore_filenames", [])),
            scan_ignore_prefixes=list(autofill.get("scan_ignore_prefixes", [])),
            choose_strategy=str(autofill.get("choose_strategy", "mtime_ns")),
            tiebreaker=str(autofill.get("tiebreaker", "lex_name")),
            derive_enabled=bool(autofill.get("derive_enabled", True)),
            issue_regex=str(autofill.get("issue_regex", "^issue_(\\d+)_")),
            commit_regex=str(
                autofill.get(
                    "commit_regex",
                    "^issue_\\d+_(.+)\\.(zip|patch|diff|py)$",
                )
            ),
            commit_replace_underscores=bool(autofill.get("commit_replace_underscores", True)),
            commit_replace_dashes=bool(autofill.get("commit_replace_dashes", True)),
            commit_collapse_spaces=bool(autofill.get("commit_collapse_spaces", True)),
            commit_trim=bool(autofill.get("commit_trim", True)),
            commit_ascii_only=bool(autofill.get("commit_ascii_only", True)),
            issue_default_if_no_match=str(autofill.get("issue_default_if_no_match", "")),
            commit_default_if_no_match=str(autofill.get("commit_default_if_no_match", "")),
            overwrite_policy=str(autofill.get("overwrite_policy", "if_not_dirty")),
            fill_patch_path=bool(autofill.get("fill_patch_path", True)),
            fill_issue_id=bool(autofill.get("fill_issue_id", True)),
            fill_commit_message=bool(autofill.get("fill_commit_message", True)),
            zip_commit_enabled=bool(autofill.get("zip_commit_enabled", True)),
            zip_commit_filename=str(autofill.get("zip_commit_filename", "COMMIT_MESSAGE.txt")),
            zip_commit_max_bytes=int(autofill.get("zip_commit_max_bytes", 4096)),
            zip_commit_max_ratio=int(autofill.get("zip_commit_max_ratio", 200)),
            zip_issue_enabled=bool(autofill.get("zip_issue_enabled", True)),
            zip_issue_filename=str(autofill.get("zip_issue_filename", "ISSUE_NUMBER.txt")),
            zip_issue_max_bytes=int(autofill.get("zip_issue_max_bytes", 128)),
            zip_issue_max_ratio=int(autofill.get("zip_issue_max_ratio", 200)),
            scan_zip_require_patch=bool(autofill.get("scan_zip_require_patch", False)),
        ),
        targeting=TargetingConfig(
            default_target_repo=str(targeting.get("default_target_repo", "patchhub")),
            zip_target_prefill_enabled=bool(targeting.get("zip_target_prefill_enabled", True)),
        ),
        repo_snapshot_cleanup=repo_snapshot_cleanup,
    )
