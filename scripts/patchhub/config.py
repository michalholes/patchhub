from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

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
class GovernanceToolkitConfig:
    github_manifest_url: str = ""
    cache_root: str = "patches/governance_toolkit_cache"
    allow_stale: bool = False
    request_timeout_s: int = 3


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
    governance_toolkit: GovernanceToolkitConfig = field(default_factory=GovernanceToolkitConfig)
    repo_snapshot_cleanup: RepoSnapshotCleanupConfig = field(
        default_factory=RepoSnapshotCleanupConfig
    )


TomlTable = dict[str, object]


def _as_toml_table(raw: object, *, key: str) -> TomlTable:
    if not isinstance(raw, dict):
        raise ValueError(f"{key} must be a table")
    raw_dict = cast(dict[object, object], raw)
    out: TomlTable = {}
    for raw_key, raw_value in raw_dict.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"{key} has non-string key")
        out[raw_key] = raw_value
    return out


def _list_of_objects(value: object, *, key: str) -> list[object]:
    if isinstance(value, list):
        return [item for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return [item for item in cast(tuple[object, ...], value)]
    raise ValueError(f"{key} must be an array")


def _list_of_strings(value: object, *, key: str) -> list[str]:
    out: list[str] = []
    for index, item in enumerate(_list_of_objects(value, key=key)):
        if not isinstance(item, str):
            raise ValueError(f"{key}[{index}] must be a string")
        out.append(item)
    return out


def _list_of_ints(value: object, *, key: str) -> list[int]:
    out: list[int] = []
    for index, item in enumerate(_list_of_objects(value, key=key)):
        out.append(_must_int_at_least(item, key=f"{key}[{index}]", minimum=0))
    return out


def _must_get(d: Mapping[str, object], key: str) -> object:
    if key not in d:
        raise KeyError(f"Missing required config key: {key}")
    return d[key]


def _must_int_at_least(value: object, *, key: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Config key {key} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, (float, str)):
        parsed = int(value)
    else:
        raise ValueError(f"Config key {key} must be an integer")
    if parsed < minimum:
        raise ValueError(f"Config key {key} must be >= {minimum}; got {parsed}")
    return parsed


def _parse_repo_snapshot_cleanup_rule(
    raw: object,
    *,
    index: int,
) -> RepoSnapshotCleanupRule:
    prefix = f"repo_snapshot_cleanup.rules[{index}]"
    rule = _as_toml_table(raw, key=prefix)
    allowed = {"filename_pattern", "keep_count"}
    extra = sorted(key for key in rule if key not in allowed)
    if extra:
        raise ValueError(f"{prefix} contains unsupported keys: {', '.join(extra)}")

    pattern = rule.get("filename_pattern")
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

    keep_count = rule.get("keep_count")
    if isinstance(keep_count, bool) or not isinstance(keep_count, int):
        raise ValueError(f"{prefix}.keep_count must be an integer")
    if keep_count < 0:
        raise ValueError(f"{prefix}.keep_count must be >= 0")
    return RepoSnapshotCleanupRule(
        filename_pattern=pattern,
        keep_count=int(keep_count),
    )


def _parse_repo_snapshot_cleanup(raw: object) -> RepoSnapshotCleanupConfig:
    if raw is None:
        return RepoSnapshotCleanupConfig()
    config = _as_toml_table(raw, key="repo_snapshot_cleanup")
    allowed = {"rules", "age_max_days", "age_directories"}
    extra = sorted(key for key in config if key not in allowed)
    if extra:
        raise ValueError("repo_snapshot_cleanup contains unsupported keys: " + ", ".join(extra))

    raw_rules = _list_of_objects(config.get("rules", []), key="repo_snapshot_cleanup.rules")
    rules = tuple(
        _parse_repo_snapshot_cleanup_rule(item, index=index) for index, item in enumerate(raw_rules)
    )

    has_age_max_days = "age_max_days" in config
    has_age_directories = "age_directories" in config
    if has_age_max_days != has_age_directories:
        raise ValueError(
            "repo_snapshot_cleanup.age_max_days and "
            "repo_snapshot_cleanup.age_directories must be provided together"
        )

    if not has_age_max_days:
        return RepoSnapshotCleanupConfig(rules=rules)

    age_max_days = config.get("age_max_days")
    if isinstance(age_max_days, bool) or not isinstance(age_max_days, int):
        raise ValueError("repo_snapshot_cleanup.age_max_days must be an integer")
    if age_max_days < 1:
        raise ValueError("repo_snapshot_cleanup.age_max_days must be >= 1")

    raw_age_directories = _list_of_objects(
        config.get("age_directories"),
        key="repo_snapshot_cleanup.age_directories",
    )
    if not raw_age_directories:
        raise ValueError("repo_snapshot_cleanup.age_directories must be non-empty")

    allowed_directories = {"logs", "successful", "unsuccessful"}
    age_directories: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_age_directories):
        if not isinstance(item, str):
            raise ValueError(f"repo_snapshot_cleanup.age_directories[{index}] must be a string")
        value = item.strip()
        if value not in allowed_directories:
            raise ValueError(
                "repo_snapshot_cleanup.age_directories contains unsupported value: " + value
            )
        if value in seen:
            raise ValueError(
                "repo_snapshot_cleanup.age_directories contains duplicate entry: " + value
            )
        seen.add(value)
        age_directories.append(value)

    return RepoSnapshotCleanupConfig(
        rules=rules,
        age_max_days=int(age_max_days),
        age_directories=tuple(age_directories),
    )


def load_config(path: Path) -> AppConfig:
    parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    raw = _as_toml_table(parsed, key="config")

    server = _as_toml_table(raw.get("server", {}), key="server")
    meta = _as_toml_table(raw.get("meta", {}), key="meta")
    runner = _as_toml_table(raw.get("runner", {}), key="runner")
    paths = _as_toml_table(raw.get("paths", {}), key="paths")
    upload = _as_toml_table(raw.get("upload", {}), key="upload")
    issue = _as_toml_table(raw.get("issue", {}), key="issue")
    indexing = _as_toml_table(raw.get("indexing", {}), key="indexing")
    ui = _as_toml_table(raw.get("ui", {}), key="ui")
    autofill = _as_toml_table(raw.get("autofill", {}), key="autofill")
    targeting = _as_toml_table(raw.get("targeting", {}), key="targeting")
    governance_toolkit = _as_toml_table(
        raw.get("governance_toolkit", {}),
        key="governance_toolkit",
    )
    repo_snapshot_cleanup = _parse_repo_snapshot_cleanup(raw.get("repo_snapshot_cleanup"))

    return AppConfig(
        server=ServerConfig(
            host=str(_must_get(server, "host")),
            port=_must_int_at_least(_must_get(server, "port"), key="server.port", minimum=1),
            tail_max_bytes=_must_int_at_least(
                server.get("tail_max_bytes", 8_388_608),
                key="server.tail_max_bytes",
                minimum=1,
            ),
            tail_cache_max_entries=_must_int_at_least(
                server.get("tail_cache_max_entries", 32),
                key="server.tail_cache_max_entries",
                minimum=1,
            ),
        ),
        meta=MetaConfig(
            version=str(meta.get("version", "0.0.0")),
        ),
        runner=RunnerConfig(
            command=_list_of_strings(_must_get(runner, "command"), key="runner.command"),
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
            crud_allowlist=_list_of_strings(
                _must_get(paths, "crud_allowlist"),
                key="paths.crud_allowlist",
            ),
        ),
        upload=UploadConfig(
            max_bytes=_must_int_at_least(
                _must_get(upload, "max_bytes"),
                key="upload.max_bytes",
                minimum=1,
            ),
            allowed_extensions=_list_of_strings(
                _must_get(upload, "allowed_extensions"),
                key="upload.allowed_extensions",
            ),
            ascii_only_names=bool(_must_get(upload, "ascii_only_names")),
        ),
        issue=IssueConfig(
            default_regex=str(_must_get(issue, "default_regex")),
            allocation_start=_must_int_at_least(
                _must_get(issue, "allocation_start"),
                key="issue.allocation_start",
                minimum=0,
            ),
            allocation_max=_must_int_at_least(
                _must_get(issue, "allocation_max"),
                key="issue.allocation_max",
                minimum=1,
            ),
        ),
        indexing=IndexingConfig(
            log_filename_regex=str(_must_get(indexing, "log_filename_regex")),
            stats_windows_days=_list_of_ints(
                _must_get(indexing, "stats_windows_days"),
                key="indexing.stats_windows_days",
            ),
            poll_interval_seconds=_must_int_at_least(
                indexing.get("poll_interval_seconds", 2),
                key="indexing.poll_interval_seconds",
                minimum=1,
            ),
        ),
        ui=UiConfig(
            base_font_px=_must_int_at_least(
                ui.get("base_font_px", 24),
                key="ui.base_font_px",
                minimum=1,
            ),
            drop_overlay_enabled=bool(ui.get("drop_overlay_enabled", True)),
            clear_output_on_autofill=bool(ui.get("clear_output_on_autofill", True)),
            show_autofill_clear_status=bool(ui.get("show_autofill_clear_status", True)),
            idle_auto_select_last_job=bool(ui.get("idle_auto_select_last_job", False)),
        ),
        autofill=AutofillConfig(
            enabled=bool(autofill.get("enabled", True)),
            poll_interval_seconds=_must_int_at_least(
                autofill.get("poll_interval_seconds", 10),
                key="autofill.poll_interval_seconds",
                minimum=1,
            ),
            scan_dir=str(autofill.get("scan_dir", "patches")),
            scan_extensions=_list_of_strings(
                autofill.get("scan_extensions", [".zip", ".patch"]),
                key="autofill.scan_extensions",
            ),
            scan_ignore_filenames=_list_of_strings(
                autofill.get("scan_ignore_filenames", []),
                key="autofill.scan_ignore_filenames",
            ),
            scan_ignore_prefixes=_list_of_strings(
                autofill.get("scan_ignore_prefixes", []),
                key="autofill.scan_ignore_prefixes",
            ),
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
            zip_commit_max_bytes=_must_int_at_least(
                autofill.get("zip_commit_max_bytes", 4096),
                key="autofill.zip_commit_max_bytes",
                minimum=1,
            ),
            zip_commit_max_ratio=_must_int_at_least(
                autofill.get("zip_commit_max_ratio", 200),
                key="autofill.zip_commit_max_ratio",
                minimum=1,
            ),
            zip_issue_enabled=bool(autofill.get("zip_issue_enabled", True)),
            zip_issue_filename=str(autofill.get("zip_issue_filename", "ISSUE_NUMBER.txt")),
            zip_issue_max_bytes=_must_int_at_least(
                autofill.get("zip_issue_max_bytes", 128),
                key="autofill.zip_issue_max_bytes",
                minimum=1,
            ),
            zip_issue_max_ratio=_must_int_at_least(
                autofill.get("zip_issue_max_ratio", 200),
                key="autofill.zip_issue_max_ratio",
                minimum=1,
            ),
            scan_zip_require_patch=bool(autofill.get("scan_zip_require_patch", False)),
        ),
        targeting=TargetingConfig(
            default_target_repo=str(targeting.get("default_target_repo", "patchhub")),
            zip_target_prefill_enabled=bool(targeting.get("zip_target_prefill_enabled", True)),
        ),
        governance_toolkit=GovernanceToolkitConfig(
            github_manifest_url=str(governance_toolkit.get("github_manifest_url", "")),
            cache_root=str(
                governance_toolkit.get(
                    "cache_root",
                    "patches/governance_toolkit_cache",
                )
            ),
            allow_stale=bool(governance_toolkit.get("allow_stale", False)),
            request_timeout_s=_must_int_at_least(
                governance_toolkit.get("request_timeout_s", 3),
                key="governance_toolkit.request_timeout_s",
                minimum=1,
            ),
        ),
        repo_snapshot_cleanup=repo_snapshot_cleanup,
    )
