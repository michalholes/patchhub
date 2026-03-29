from __future__ import annotations

import fnmatch
import stat
import time
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_AGE_DIRECTORIES = ("logs", "successful", "unsuccessful")
_NANOSECONDS_PER_DAY = 86_400 * 1_000_000_000


@dataclass(frozen=True)
class RepoSnapshotCleanupRule:
    filename_pattern: str
    keep_count: int


@dataclass(frozen=True)
class RepoSnapshotCleanupConfig:
    rules: tuple[RepoSnapshotCleanupRule, ...] = ()
    age_max_days: int | None = None
    age_directories: tuple[str, ...] = ()

    @property
    def age_cleanup_enabled(self) -> bool:
        return self.age_max_days is not None and bool(self.age_directories)


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    basename: str
    mtime_ns: int


@dataclass(frozen=True)
class CleanupRuleSummary:
    filename_pattern: str
    keep_count: int
    matched_count: int
    deleted_count: int

    def to_json(self) -> dict[str, object]:
        return {
            "filename_pattern": self.filename_pattern,
            "keep_count": int(self.keep_count),
            "matched_count": int(self.matched_count),
            "deleted_count": int(self.deleted_count),
        }


@dataclass(frozen=True)
class CleanupSummary:
    job_id: str
    issue_id: str
    created_utc: str
    deleted_count: int
    rules: tuple[CleanupRuleSummary, ...]
    summary_text: str

    def to_json(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "issue_id": self.issue_id,
            "created_utc": self.created_utc,
            "deleted_count": int(self.deleted_count),
            "rules": [rule.to_json() for rule in self.rules],
            "summary_text": self.summary_text,
        }


@dataclass(frozen=True)
class CleanupPhaseDetail:
    label: str
    matched_count: int
    deleted_count: int
    keep_count: int | None = None
    age_max_days: int | None = None


_ALLOWED_AGE_DIRECTORY_SET = set(_ALLOWED_AGE_DIRECTORIES)


def _sorted_candidates(
    items: list[CleanupCandidate],
) -> list[CleanupCandidate]:
    return sorted(items, key=lambda item: (-item.mtime_ns, item.basename))


def _scan_direct_child_regular_files(root: Path) -> list[CleanupCandidate]:
    out: list[CleanupCandidate] = []
    try:
        entries = list(root.iterdir())
    except FileNotFoundError:
        return []
    except NotADirectoryError:
        return []

    for entry in entries:
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError:
            continue
        if not stat.S_ISREG(entry_stat.st_mode):
            continue
        out.append(
            CleanupCandidate(
                path=entry,
                basename=entry.name,
                mtime_ns=int(getattr(entry_stat, "st_mtime_ns", 0)),
            )
        )
    return out


def scan_repo_snapshot_cleanup_candidates(patches_root: Path) -> list[CleanupCandidate]:
    return _scan_direct_child_regular_files(patches_root)


def scan_age_cleanup_candidates(
    patches_root: Path,
    directory_name: str,
) -> list[CleanupCandidate]:
    name = str(directory_name or "").strip()
    if name not in _ALLOWED_AGE_DIRECTORY_SET:
        return []
    return _scan_direct_child_regular_files(patches_root / name)


def _assign_candidates(
    candidates: list[CleanupCandidate],
    config: RepoSnapshotCleanupConfig,
) -> list[list[CleanupCandidate]]:
    assigned: list[list[CleanupCandidate]] = [[] for _ in config.rules]
    for candidate in sorted(candidates, key=lambda item: item.basename):
        for idx, rule in enumerate(config.rules):
            if fnmatch.fnmatchcase(candidate.basename, rule.filename_pattern):
                assigned[idx].append(candidate)
                break
    return assigned


def _phase_details_text(phase_details: list[CleanupPhaseDetail]) -> str:
    if not phase_details:
        return "no cleanup phases configured"
    parts: list[str] = []
    for phase in phase_details:
        if phase.keep_count is not None:
            parts.append(
                f"root {phase.label}: matched {phase.matched_count}, "
                f"deleted {phase.deleted_count}, keep {phase.keep_count}"
            )
            continue
        parts.append(
            f"age {phase.label}: matched {phase.matched_count}, "
            f"deleted {phase.deleted_count}, max_age_days {int(phase.age_max_days or 0)}"
        )
    return "; ".join(parts)


def _summary_text(
    *,
    deleted_count: int,
    phase_details: list[CleanupPhaseDetail],
    failure_text: str | None,
) -> str:
    details = _phase_details_text(phase_details)
    prefix = f"PatchHub cleanup: deleted {deleted_count} file(s)"
    if failure_text:
        return prefix + f"; FAILED: {failure_text}; {details}"
    return prefix + f"; {details}"


def _age_cutoff_ns(*, run_time_ns: int, age_max_days: int) -> int:
    return int(run_time_ns - (int(age_max_days) * _NANOSECONDS_PER_DAY))


def _run_root_cleanup(
    *,
    patches_root: Path,
    config: RepoSnapshotCleanupConfig,
    deleted_total: int,
    failure_text: str | None,
) -> tuple[list[CleanupRuleSummary], list[CleanupPhaseDetail], int, str | None]:
    try:
        candidates = scan_repo_snapshot_cleanup_candidates(patches_root)
        assigned = _assign_candidates(candidates, config)
    except Exception as exc:
        failure_text = f"{type(exc).__name__}: {exc}"
        assigned = [[] for _ in config.rules]

    rule_summaries: list[CleanupRuleSummary] = []
    phase_details: list[CleanupPhaseDetail] = []
    for index, rule in enumerate(config.rules):
        ordered = _sorted_candidates(assigned[index])
        to_delete = ordered[rule.keep_count :]
        deleted_for_rule = 0
        if failure_text is None:
            for candidate in to_delete:
                try:
                    candidate.path.unlink()
                except Exception as exc:
                    failure_text = f"{type(exc).__name__}: {exc}"
                    break
                deleted_for_rule += 1
                deleted_total += 1
        summary = CleanupRuleSummary(
            filename_pattern=rule.filename_pattern,
            keep_count=rule.keep_count,
            matched_count=len(ordered),
            deleted_count=deleted_for_rule,
        )
        rule_summaries.append(summary)
        phase_details.append(
            CleanupPhaseDetail(
                label=rule.filename_pattern,
                matched_count=len(ordered),
                deleted_count=deleted_for_rule,
                keep_count=rule.keep_count,
            )
        )
    return rule_summaries, phase_details, deleted_total, failure_text


def _run_age_cleanup(
    *,
    patches_root: Path,
    config: RepoSnapshotCleanupConfig,
    run_time_ns: int,
    deleted_total: int,
    failure_text: str | None,
) -> tuple[list[CleanupPhaseDetail], int, str | None]:
    if not config.age_cleanup_enabled:
        return [], deleted_total, failure_text

    phase_details: list[CleanupPhaseDetail] = []
    cutoff_ns = _age_cutoff_ns(
        run_time_ns=run_time_ns,
        age_max_days=int(config.age_max_days or 0),
    )
    for directory_name in config.age_directories:
        try:
            ordered = _sorted_candidates(scan_age_cleanup_candidates(patches_root, directory_name))
        except Exception as exc:
            if failure_text is None:
                failure_text = f"{type(exc).__name__}: {exc}"
            ordered = []
        to_delete = [item for item in ordered if item.mtime_ns < cutoff_ns]
        deleted_for_dir = 0
        if failure_text is None:
            for candidate in to_delete:
                try:
                    candidate.path.unlink()
                except Exception as exc:
                    failure_text = f"{type(exc).__name__}: {exc}"
                    break
                deleted_for_dir += 1
                deleted_total += 1
        phase_details.append(
            CleanupPhaseDetail(
                label=directory_name,
                matched_count=len(ordered),
                deleted_count=deleted_for_dir,
                age_max_days=int(config.age_max_days or 0),
            )
        )
    return phase_details, deleted_total, failure_text


def execute_repo_snapshot_cleanup(
    *,
    patches_root: Path,
    config: RepoSnapshotCleanupConfig,
    job_id: str,
    issue_id: str,
    created_utc: str,
    run_time_ns: int | None = None,
) -> CleanupSummary:
    deleted_total = 0
    failure_text: str | None = None
    effective_run_time_ns = int(run_time_ns) if run_time_ns is not None else time.time_ns()

    rule_summaries, root_phase_details, deleted_total, failure_text = _run_root_cleanup(
        patches_root=patches_root,
        config=config,
        deleted_total=deleted_total,
        failure_text=failure_text,
    )
    age_phase_details, deleted_total, failure_text = _run_age_cleanup(
        patches_root=patches_root,
        config=config,
        run_time_ns=effective_run_time_ns,
        deleted_total=deleted_total,
        failure_text=failure_text,
    )

    summary_text = _summary_text(
        deleted_count=deleted_total,
        phase_details=[*root_phase_details, *age_phase_details],
        failure_text=failure_text,
    )
    return CleanupSummary(
        job_id=str(job_id),
        issue_id=str(issue_id),
        created_utc=str(created_utc),
        deleted_count=deleted_total,
        rules=tuple(rule_summaries),
        summary_text=summary_text,
    )
