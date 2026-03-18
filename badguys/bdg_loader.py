from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FORBIDDEN_EVAL_KEYS = {
    "rc_eq",
    "rc_ne",
    "stdout_contains",
    "stdout_not_contains",
    "stdout_regex",
    "stderr_contains",
    "stderr_not_contains",
    "stderr_regex",
    "value_eq",
    "value_contains",
    "value_not_contains",
    "value_regex",
    "list_eq",
    "list_contains",
    "list_not_contains",
    "equals_step_index",
}

_FORBIDDEN_PATCH_MARKERS = (
    "diff --git a/",
    "+++ b/",
    "--- a/",
    "--- /dev/null",
)

_FORBIDDEN_TOML_KEYS = {
    "runner_cmd",
    "patches_dir",
    "logs_dir",
    "central_log_pattern",
    "path",
}

_FORBIDDEN_STEP_RECIPE_KEYS = {
    "args",
    "runner_verbosity",
    "console_verbosity",
    "log_verbosity",
    "commit_limit",
}

_PATH_LITERAL_RE = re.compile(r"['\"][^'\"\n]*[\\/][^'\"\n]*['\"]")


@dataclass(frozen=True)
class BdgAssetEntry:
    name: str
    content: str
    kind: str | None = None
    subject: str | None = None
    zip_name: str | None = None
    declared_subjects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BdgAsset:
    asset_id: str
    kind: str
    content: str | None
    entries: list[BdgAssetEntry]
    subject: str | None = None
    declared_subjects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BdgStep:
    op: str
    params: dict[str, Any]


@dataclass(frozen=True)
class BdgTest:
    test_id: str
    makes_commit: bool
    is_guard: bool
    assets: dict[str, BdgAsset]
    steps: list[BdgStep]
    subjects: dict[str, str] = field(default_factory=dict)


def _as_str(d: dict[str, Any], key: str, default: str = "") -> str:
    v = d.get(key, default)
    if not isinstance(v, str):
        raise SystemExit(f"FAIL: bdg: key '{key}' must be a string")
    return v


def _as_bool(d: dict[str, Any], key: str, default: bool = False) -> bool:
    v = d.get(key, default)
    if not isinstance(v, bool):
        raise SystemExit(f"FAIL: bdg: key '{key}' must be a bool")
    return v


def _as_string_list(*, value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
        raise SystemExit(f"FAIL: bdg: {label} must be list[str]")
    return list(value)


def _validate_relpath(*, relpath: str, label: str) -> str:
    if not relpath.strip():
        raise SystemExit(f"FAIL: bdg: {label} relpath must be non-empty")
    path = Path(relpath)
    if path.is_absolute():
        raise SystemExit(f"FAIL: bdg: {label} relpath must be repo-relative")
    if any(part == ".." for part in path.parts):
        raise SystemExit(f"FAIL: bdg: {label} relpath must not contain '..'")
    return relpath


def _validate_python_payload(*, label: str, content: str) -> None:
    if any(marker in content for marker in ("FILES =", "REPO = Path", "__file__", ".parents[")):
        raise SystemExit(f"FAIL: bdg: {label} must not embed FILES or repo path machinery")
    if _PATH_LITERAL_RE.search(content):
        raise SystemExit(f"FAIL: bdg: {label} must not embed filesystem paths")


def _validate_toml_delta(*, label: str, content: str) -> None:
    raw = tomllib.loads(content) if content.strip() else {}
    if not isinstance(raw, dict):
        raise SystemExit(f"FAIL: bdg: {label} must decode to a TOML table")
    suite = raw.get("suite", {})
    lock = raw.get("lock", {})
    if not isinstance(suite, dict):
        raise SystemExit(f"FAIL: bdg: {label} [suite] must be a table")
    if not isinstance(lock, dict):
        raise SystemExit(f"FAIL: bdg: {label} [lock] must be a table")
    for key in suite:
        if key in _FORBIDDEN_TOML_KEYS:
            raise SystemExit(f"FAIL: bdg: {label} must not embed suite.{key}")
    for key in lock:
        if key in _FORBIDDEN_TOML_KEYS:
            raise SystemExit(f"FAIL: bdg: {label} must not embed lock.{key}")


def _looks_like_python_payload(content: str) -> bool:
    markers = (
        "ctx.",
        "from __future__ import annotations",
        "FILES =",
        "Path(",
        "def ",
        "class ",
    )
    return any(marker in content for marker in markers)


def _validate_zip_entry(*, asset_id: str, entry_id: str, content: str) -> None:
    label = f"asset.entry '{asset_id}.{entry_id}'"
    if any(marker in content for marker in _FORBIDDEN_PATCH_MARKERS):
        raise SystemExit(f"FAIL: bdg: {label} must not embed raw patch paths")
    if _PATH_LITERAL_RE.search(content):
        raise SystemExit(f"FAIL: bdg: {label} must not embed filesystem paths")
    if _looks_like_python_payload(content):
        _validate_python_payload(label=label, content=content)


def _validate_asset(item: dict[str, Any], *, asset_id: str, kind: str) -> None:
    content = item.get("content")
    if content is not None and not isinstance(content, str):
        raise SystemExit("FAIL: bdg: asset content must be string or omitted")
    if (
        kind == "git_patch_text"
        and isinstance(content, str)
        and any(marker in content for marker in _FORBIDDEN_PATCH_MARKERS)
    ):
        raise SystemExit(
            f"FAIL: bdg: asset '{asset_id}' git_patch_text must not embed raw patch paths"
        )
    if kind == "python_patch_script" and isinstance(content, str):
        _validate_python_payload(label=f"asset '{asset_id}'", content=content)
    if kind == "toml_text" and isinstance(content, str):
        _validate_toml_delta(label=f"asset '{asset_id}'", content=content)


def load_bdg_test(path: Path) -> BdgTest:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise SystemExit("FAIL: bdg: [meta] must be a table")

    makes_commit = _as_bool(meta, "makes_commit", False)
    is_guard = _as_bool(meta, "is_guard", False)

    raw_subjects = raw.get("subjects", {})
    if raw_subjects is None:
        raw_subjects = {}
    if not isinstance(raw_subjects, dict):
        raise SystemExit("FAIL: bdg: [subjects] must be a table")
    subjects: dict[str, str] = {}
    for subject_id, item in raw_subjects.items():
        if not isinstance(item, dict):
            raise SystemExit(f"FAIL: bdg: [subjects.{subject_id}] must be a table")
        extra = sorted(set(item) - {"relpath"})
        if extra:
            joined = ", ".join(extra)
            raise SystemExit(f"FAIL: bdg: [subjects.{subject_id}] has unknown keys: {joined}")
        relpath = item.get("relpath")
        if not isinstance(relpath, str):
            raise SystemExit(f"FAIL: bdg: [subjects.{subject_id}].relpath must be string")
        subjects[str(subject_id)] = _validate_relpath(
            relpath=relpath,
            label=f"subjects.{subject_id}",
        )

    assets: dict[str, BdgAsset] = {}
    for item in raw.get("asset", []):
        if not isinstance(item, dict):
            raise SystemExit("FAIL: bdg: [[asset]] must be a table")
        asset_id = _as_str(item, "id")
        kind = _as_str(item, "kind")
        _validate_asset(item, asset_id=asset_id, kind=kind)
        content = item.get("content")
        subject = item.get("subject")
        if subject is not None and not isinstance(subject, str):
            raise SystemExit(f"FAIL: bdg: asset '{asset_id}' subject must be string")
        declared_subjects = _as_string_list(
            value=item.get("declared_subjects", []),
            label=f"asset '{asset_id}' declared_subjects",
        )

        entries: list[BdgAssetEntry] = []
        for ent in item.get("entry", []):
            if not isinstance(ent, dict):
                raise SystemExit("FAIL: bdg: [[asset.entry]] must be a table")
            name = _as_str(ent, "name")
            if (
                "/" in name
                or "\\" in name
                or name.endswith((".patch", ".py", ".txt", ".toml", ".zip"))
            ):
                raise SystemExit(
                    f"FAIL: bdg: asset.entry '{asset_id}.{name}' must use a logical entry id"
                )
            econtent = ent.get("content")
            if not isinstance(econtent, str):
                raise SystemExit("FAIL: bdg: asset.entry content must be string")
            if kind == "patch_zip_manifest":
                _validate_zip_entry(asset_id=asset_id, entry_id=name, content=econtent)
            entry_kind = ent.get("kind")
            if entry_kind is not None and not isinstance(entry_kind, str):
                raise SystemExit(f"FAIL: bdg: asset.entry '{asset_id}.{name}' kind must be string")
            entry_subject = ent.get("subject")
            if entry_subject is not None and not isinstance(entry_subject, str):
                raise SystemExit(
                    f"FAIL: bdg: asset.entry '{asset_id}.{name}' subject must be string"
                )
            zip_name = ent.get("zip_name")
            if zip_name is not None and not isinstance(zip_name, str):
                raise SystemExit(
                    f"FAIL: bdg: asset.entry '{asset_id}.{name}' zip_name must be string"
                )
            entries.append(
                BdgAssetEntry(
                    name=name,
                    content=econtent,
                    kind=entry_kind,
                    subject=entry_subject,
                    zip_name=zip_name,
                    declared_subjects=_as_string_list(
                        value=ent.get("declared_subjects", []),
                        label=f"asset.entry '{asset_id}.{name}' declared_subjects",
                    ),
                )
            )

        if asset_id in assets:
            raise SystemExit(f"FAIL: bdg: duplicate asset id: {asset_id}")
        assets[asset_id] = BdgAsset(
            asset_id=asset_id,
            kind=kind,
            content=content,
            entries=entries,
            subject=subject,
            declared_subjects=declared_subjects,
        )

    steps: list[BdgStep] = []
    for item in raw.get("step", []):
        if not isinstance(item, dict):
            raise SystemExit("FAIL: bdg: [[step]] must be a table")
        op = _as_str(item, "op")
        params = dict(item)
        params.pop("op", None)
        bad_recipe_keys = sorted(_FORBIDDEN_STEP_RECIPE_KEYS.intersection(params))
        if bad_recipe_keys:
            joined = ", ".join(bad_recipe_keys)
            raise SystemExit(
                "FAIL: bdg: runner-start recipe stays in badguys/config.toml recipes; "
                f"remove: {joined}"
            )
        bad_keys = sorted(_FORBIDDEN_EVAL_KEYS.intersection(params))
        if bad_keys:
            joined = ", ".join(bad_keys)
            raise SystemExit(f"FAIL: bdg: expectations must be central; remove: {joined}")
        steps.append(BdgStep(op=op, params=params))

    if not steps:
        raise SystemExit("FAIL: bdg: must contain at least one [[step]]")

    test_id = path.stem
    return BdgTest(
        test_id=test_id,
        makes_commit=makes_commit,
        is_guard=is_guard,
        assets=assets,
        steps=steps,
        subjects=subjects,
    )
