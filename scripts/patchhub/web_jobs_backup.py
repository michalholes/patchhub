from __future__ import annotations

import re
import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import WebJobsDbConfig

_VALID_TRIGGER_POLICIES = (
    "manual",
    "startup_always",
    "startup_after_recovery",
    "interval_hours",
)

_REQUIRED_TABLES = (
    "web_jobs",
    "web_job_log_lines",
    "web_job_event_lines",
    "web_jobs_meta",
)


@dataclass(frozen=True)
class WebJobsBackupSettings:
    enabled: bool
    destination_template: str
    retain_count: int
    verify_after_backup: bool
    trigger_policy: str
    restore_source_preference: tuple[str, ...]
    interval_hours: int = 4
    check_interval_minutes: int = 5


@dataclass(frozen=True)
class VerifiedBackupResult:
    path: Path
    verified: bool


def _resolve_under_patches(patches_root: Path, rel_or_abs: str) -> Path:
    raw = str(rel_or_abs or "").strip()
    if not raw:
        return patches_root / "artifacts" / "web_jobs_backup_{timestamp}.sqlite3"
    path = Path(raw)
    if path.is_absolute():
        return path
    return (patches_root / path).resolve()


def _tuple_of_strings(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return default
    items = tuple(str(item).strip() for item in raw if str(item).strip())
    return items or default


def _normalize_trigger_policy(raw: Any) -> str:
    policy = str(raw or "manual").strip() or "manual"
    if policy not in _VALID_TRIGGER_POLICIES:
        raise ValueError(f"invalid_web_jobs_backup_trigger_policy:{policy}")
    return policy


def _normalize_positive_int(raw: Any, *, name: str, default: int) -> int:
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_{name}:{raw}") from exc
    if value < 1:
        raise ValueError(f"invalid_{name}:{value}")
    return value


def startup_backup_required(
    settings: WebJobsBackupSettings,
    recovery: dict[str, Any],
) -> bool:
    policy = _normalize_trigger_policy(settings.trigger_policy)
    if policy in {"manual", "interval_hours"}:
        return False
    if policy == "startup_always":
        return True
    action = str(recovery.get("recovery_action", "none") or "none")
    return action not in {
        "none",
        "initialized_new_main_db",
        "clean_start_db_primary",
        "validated_after_unclean_shutdown",
    }


def load_web_jobs_backup_settings(
    repo_root: Path,
    patches_root: Path,
    db_cfg: WebJobsDbConfig,
) -> WebJobsBackupSettings:
    cfg_path = repo_root / "scripts" / "patchhub" / "patchhub.toml"
    raw: dict[str, Any] = {}
    if cfg_path.is_file():
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    backup_raw = raw.get("web_jobs_backup", {})
    return WebJobsBackupSettings(
        enabled=bool(backup_raw.get("enabled", True)),
        destination_template=str(
            backup_raw.get("destination_template", db_cfg.backup_destination_template)
        ),
        retain_count=max(0, int(backup_raw.get("retain_count", db_cfg.backup_retain_count))),
        verify_after_backup=bool(
            backup_raw.get("verify_after_write", db_cfg.backup_verify_after_write)
        ),
        trigger_policy=_normalize_trigger_policy(backup_raw.get("trigger_policy", "manual")),
        restore_source_preference=_tuple_of_strings(
            backup_raw.get("restore_source_preference"),
            db_cfg.backup_restore_source_preference,
        ),
        interval_hours=_normalize_positive_int(
            backup_raw.get("interval_hours"),
            name="web_jobs_backup_interval_hours",
            default=4,
        ),
        check_interval_minutes=_normalize_positive_int(
            backup_raw.get("check_interval_minutes"),
            name="web_jobs_backup_check_interval_minutes",
            default=5,
        ),
    )


def _template_name_parts(template: str) -> tuple[str, str]:
    name = Path(template).name
    if "{timestamp}" not in name:
        return name, ""
    prefix, suffix = name.split("{timestamp}", 1)
    return prefix, suffix


def _template_regex(template: str) -> re.Pattern[str]:
    prefix, suffix = _template_name_parts(template)
    body = r"\d{8}T\d{6}Z(?:_\d{2})?"
    return re.compile(rf"^{re.escape(prefix)}{body}{re.escape(suffix)}$")


def _candidate_destination(template_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    raw = str(template_path)
    if "{timestamp}" in raw:
        return Path(raw.format(timestamp=timestamp))
    if template_path.suffix:
        return template_path.with_name(f"{template_path.stem}_{timestamp}{template_path.suffix}")
    return template_path.with_name(f"{template_path.name}_{timestamp}")


def _collision_safe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(1, 100):
        cand = path.with_name(f"{stem}_{idx:02d}{suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("Cannot allocate collision-safe backup path")


def verify_sqlite_backup(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute("PRAGMA quick_check").fetchall()
        if not rows or any(str(row[0]) != "ok" for row in rows):
            raise RuntimeError("quick_check_failed")
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    missing = [name for name in _REQUIRED_TABLES if name not in tables]
    if missing:
        raise RuntimeError("missing_required_tables:" + ",".join(missing))


def list_verified_backups(
    *,
    patches_root: Path,
    settings: WebJobsBackupSettings,
) -> list[Path]:
    template_path = _resolve_under_patches(patches_root, settings.destination_template)
    regex = _template_regex(settings.destination_template)
    if not template_path.parent.is_dir():
        return []
    items = [
        path for path in template_path.parent.iterdir() if path.is_file() and regex.match(path.name)
    ]
    items.sort(key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    return items


def latest_verified_backup(
    *,
    patches_root: Path,
    settings: WebJobsBackupSettings,
) -> Path | None:
    items = list_verified_backups(patches_root=patches_root, settings=settings)
    return items[0] if items else None


def _prune_verified_backups(*, patches_root: Path, settings: WebJobsBackupSettings) -> None:
    keep = int(settings.retain_count)
    if keep <= 0:
        return
    for path in list_verified_backups(patches_root=patches_root, settings=settings)[keep:]:
        path.unlink(missing_ok=True)


def create_verified_backup(
    *,
    db_path: Path,
    patches_root: Path,
    settings: WebJobsBackupSettings,
) -> VerifiedBackupResult:
    if not settings.enabled:
        raise RuntimeError("web_jobs_backup_disabled")
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    template_path = _resolve_under_patches(patches_root, settings.destination_template)
    destination = _collision_safe_path(_candidate_destination(template_path))
    tmp_path = destination.with_name(destination.name + ".tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.unlink(missing_ok=True)
    try:
        with sqlite3.connect(str(db_path)) as src_conn:
            src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            with sqlite3.connect(str(tmp_path)) as dst_conn:
                src_conn.backup(dst_conn)
        if settings.verify_after_backup:
            verify_sqlite_backup(tmp_path)
        tmp_path.replace(destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    _prune_verified_backups(patches_root=patches_root, settings=settings)
    return VerifiedBackupResult(path=destination, verified=True)
