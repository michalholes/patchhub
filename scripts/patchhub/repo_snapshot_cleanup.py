from __future__ import annotations

import fnmatch
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepoSnapshotCleanupRule:
    filename_pattern: str
    keep_count: int


@dataclass(frozen=True)
class RepoSnapshotCleanupConfig:
    rules: tuple[RepoSnapshotCleanupRule, ...] = ()


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


def _sorted_candidates(
    items: list[CleanupCandidate],
) -> list[CleanupCandidate]:
    return sorted(items, key=lambda item: (-item.mtime_ns, item.basename))


def scan_repo_snapshot_cleanup_candidates(patches_root: Path) -> list[CleanupCandidate]:
    out: list[CleanupCandidate] = []
    try:
        entries = list(patches_root.iterdir())
    except FileNotFoundError:
        return []
    except NotADirectoryError:
        return []

    for entry in entries:
        if entry.suffix != ".zip":
            continue
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


def _summary_text(
    *,
    deleted_count: int,
    rule_summaries: list[CleanupRuleSummary],
    failure_text: str | None,
) -> str:
    details = "; ".join(
        (
            f"{rule.filename_pattern}: matched {rule.matched_count}, "
            f"deleted {rule.deleted_count}, keep {rule.keep_count}"
        )
        for rule in rule_summaries
    )
    if not details:
        details = "no cleanup rules configured"
    prefix = f"Repo snapshot cleanup: deleted {deleted_count} file(s)"
    if failure_text:
        return prefix + f"; FAILED: {failure_text}; {details}"
    return prefix + f"; {details}"


def execute_repo_snapshot_cleanup(
    *,
    patches_root: Path,
    config: RepoSnapshotCleanupConfig,
    job_id: str,
    issue_id: str,
    created_utc: str,
) -> CleanupSummary:
    deleted_total = 0
    failure_text: str | None = None

    try:
        candidates = scan_repo_snapshot_cleanup_candidates(patches_root)
        assigned = _assign_candidates(candidates, config)
    except Exception as exc:
        failure_text = f"{type(exc).__name__}: {exc}"
        assigned = [[] for _ in config.rules]

    rule_summaries: list[CleanupRuleSummary] = []
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
        rule_summaries.append(
            CleanupRuleSummary(
                filename_pattern=rule.filename_pattern,
                keep_count=rule.keep_count,
                matched_count=len(ordered),
                deleted_count=deleted_for_rule,
            )
        )

    summary_text = _summary_text(
        deleted_count=deleted_total,
        rule_summaries=rule_summaries,
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
