from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

_REQUIRED_ENTRYPOINTS = {
    "pm_validator.py": "governance/pm_validator.py",
    "validate_master_spec_v2.py": "governance/validate_master_spec_v2.py",
}
_ALLOWED_GITHUB_HOSTS = {
    "api.github.com",
    "codeload.github.com",
    "github.com",
    "github-releases.githubusercontent.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
}
_LAST_SELECTED_FILE = "last_selected.txt"
_META_FILE = ".toolkit_meta.json"


@dataclass(frozen=True)
class GovernanceToolkitManifest:
    remote_sig: str
    archive_url: str
    archive_sha256: str
    authority_source: str


@dataclass(frozen=True)
class GovernanceToolkitSelection:
    authority_source: str
    selected_sig: str
    execution_root: Path
    pm_validator_path: Path
    validate_master_spec_v2_path: Path
    resolution: dict[str, Any]


class GovernanceToolkitRuntimeError(RuntimeError):
    def __init__(self, message: str, *, resolution: dict[str, Any]) -> None:
        super().__init__(message)
        self.resolution = resolution


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clean_ascii_token(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if not text.isascii():
        raise ValueError(f"{field} must be ASCII-only")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{field} must be single-line")
    return text


def _clean_github_url(value: str, *, field: str) -> str:
    text = _clean_ascii_token(value, field=field)
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme != "https":
        raise ValueError(f"{field} must use https")
    if parsed.netloc not in _ALLOWED_GITHUB_HOSTS:
        raise ValueError(f"{field} must use an allowed GitHub host")
    return text


def _cache_root(cfg: Any) -> Path:
    ref = str(getattr(getattr(cfg, "governance_toolkit", object()), "cache_root", "")).strip()
    if not ref:
        raise ValueError("governance_toolkit.cache_root must be configured")
    return Path(ref).expanduser().resolve()


def _github_manifest_url(cfg: Any) -> str:
    ref = str(
        getattr(getattr(cfg, "governance_toolkit", object()), "github_manifest_url", "")
    ).strip()
    if not ref:
        raise ValueError("governance_toolkit.github_manifest_url must be configured")
    return _clean_github_url(ref, field="governance_toolkit.github_manifest_url")


def _authority_key(authority_source: str) -> str:
    return hashlib.sha256(authority_source.encode("ascii")).hexdigest()


def _authority_root(cache_root: Path, authority_source: str) -> Path:
    return cache_root / "authorities" / _authority_key(authority_source)


def _allow_stale(cfg: Any) -> bool:
    return bool(getattr(getattr(cfg, "governance_toolkit", object()), "allow_stale", False))


def _request_timeout_s(cfg: Any) -> int:
    raw = int(getattr(getattr(cfg, "governance_toolkit", object()), "request_timeout_s", 3))
    return max(1, raw)


def _read_remote_bytes(url: str, *, timeout_s: int) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
        return response.read()


def load_governance_toolkit_manifest(cfg: Any) -> GovernanceToolkitManifest:
    manifest_url = _github_manifest_url(cfg)
    raw = _read_remote_bytes(manifest_url, timeout_s=_request_timeout_s(cfg))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("governance toolkit manifest must be a JSON object")
    remote_sig = _clean_ascii_token(data.get("remote_sig"), field="manifest.remote_sig")
    archive_url = _clean_github_url(
        str(data.get("archive_url") or ""),
        field="manifest.archive_url",
    )
    archive_sha256 = _clean_ascii_token(
        data.get("archive_sha256"),
        field="manifest.archive_sha256",
    ).lower()
    return GovernanceToolkitManifest(
        remote_sig=remote_sig,
        archive_url=archive_url,
        archive_sha256=archive_sha256,
        authority_source=manifest_url,
    )


def _version_root(cache_root: Path, authority_source: str, sig: str) -> Path:
    return _authority_root(cache_root, authority_source) / "versions" / sig


def _entrypoint_paths(root: Path) -> tuple[Path, Path]:
    pm_validator = (root / _REQUIRED_ENTRYPOINTS["pm_validator.py"]).resolve()
    validator = (root / _REQUIRED_ENTRYPOINTS["validate_master_spec_v2.py"]).resolve()
    return pm_validator, validator


def _write_last_selected(authority_root: Path, sig: str) -> None:
    authority_root.mkdir(parents=True, exist_ok=True)
    (authority_root / _LAST_SELECTED_FILE).write_text(sig + "\n", encoding="ascii")


def _read_last_selected(authority_root: Path) -> str:
    path = authority_root / _LAST_SELECTED_FILE
    if not path.is_file():
        return ""
    try:
        return _clean_ascii_token(path.read_text(encoding="ascii"), field="last_selected")
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


def _read_meta(root: Path) -> dict[str, Any] | None:
    path = root / _META_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _cache_state(
    root: Path,
    *,
    sig: str,
    archive_sha256: str | None,
    authority_source: str,
) -> tuple[bool, str]:
    pm_validator, validator = _entrypoint_paths(root)
    if not root.is_dir():
        return False, "missing_root"
    if not pm_validator.is_file() or not validator.is_file():
        return False, "missing_entrypoint"
    meta = _read_meta(root)
    if meta is None:
        return False, "missing_metadata"
    if str(meta.get("selected_sig", "")).strip() != sig:
        return False, "selected_sig_mismatch"
    if str(meta.get("authority_source", "")).strip() != authority_source:
        return False, "authority_source_mismatch"
    if archive_sha256 and str(meta.get("archive_sha256", "")).strip().lower() != archive_sha256:
        return False, "archive_sha256_mismatch"
    return True, "pass"


def _resolve_archive_layout_root(extracted_root: Path) -> Path:
    candidates: list[Path] = []
    for pm_validator in extracted_root.rglob(_REQUIRED_ENTRYPOINTS["pm_validator.py"]):
        candidate = pm_validator.parent.parent
        if all((candidate / relpath).is_file() for relpath in _REQUIRED_ENTRYPOINTS.values()):
            resolved = candidate.resolve()
            if resolved not in candidates:
                candidates.append(resolved)
    if not candidates:
        raise ValueError("toolkit_archive_missing_required_entrypoints")
    if len(candidates) > 1:
        raise ValueError("toolkit_archive_ambiguous_required_entrypoints")
    return candidates[0]


def _materialize_selected_toolkit(
    *,
    cache_root: Path,
    manifest: GovernanceToolkitManifest,
    timeout_s: int,
) -> tuple[Path, str]:
    raw = _read_remote_bytes(manifest.archive_url, timeout_s=timeout_s)
    actual_sha = _sha256_bytes(raw)
    if actual_sha != manifest.archive_sha256:
        raise ValueError(
            "toolkit_archive_sha256_mismatch:"
            f"expected={manifest.archive_sha256}:actual={actual_sha}"
        )
    authority_root = _authority_root(cache_root, manifest.authority_source)
    versions_root = authority_root / "versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    final_root = _version_root(cache_root, manifest.authority_source, manifest.remote_sig)
    with tempfile.TemporaryDirectory(dir=str(cache_root)) as td:
        tmp_root = Path(td) / manifest.remote_sig
        tmp_root.mkdir(parents=True, exist_ok=True)
        archive_path = Path(td) / "toolkit.zip"
        archive_path.write_bytes(raw)
        with ZipFile(archive_path, "r") as zf:
            zf.extractall(tmp_root)
        layout_root = _resolve_archive_layout_root(tmp_root)
        (layout_root / _META_FILE).write_text(
            json.dumps(
                {
                    "selected_sig": manifest.remote_sig,
                    "archive_sha256": manifest.archive_sha256,
                    "authority_source": manifest.authority_source,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if final_root.exists():
            shutil.rmtree(final_root)
        shutil.move(str(layout_root), str(final_root))
    return final_root, "pass"


def _resolution_record() -> dict[str, Any]:
    return {
        "remote_sig": "",
        "cached_sig_before": "",
        "selected_sig": "",
        "cache_hit": False,
        "download_performed": False,
        "integrity_check_result": "",
        "resolution_mode": "",
        "checked_at": _utc_now(),
        "error": "",
    }


def _selection_from_root(
    *,
    authority_source: str,
    sig: str,
    root: Path,
    resolution: dict[str, Any],
) -> GovernanceToolkitSelection:
    pm_validator_path, validate_master_spec_v2_path = _entrypoint_paths(root)
    return GovernanceToolkitSelection(
        authority_source=authority_source,
        selected_sig=sig,
        execution_root=root,
        pm_validator_path=pm_validator_path,
        validate_master_spec_v2_path=validate_master_spec_v2_path,
        resolution=dict(resolution),
    )


def resolve_governance_toolkit(cfg: Any) -> GovernanceToolkitSelection:
    cache_root = _cache_root(cfg)
    cache_root.mkdir(parents=True, exist_ok=True)
    resolution = _resolution_record()
    timeout_s = _request_timeout_s(cfg)
    manifest_url = _github_manifest_url(cfg)
    authority_root = _authority_root(cache_root, manifest_url)
    resolution["cached_sig_before"] = _read_last_selected(authority_root)
    try:
        manifest = load_governance_toolkit_manifest(cfg)
        resolution["remote_sig"] = manifest.remote_sig
        resolution["selected_sig"] = manifest.remote_sig
        selected_root = _version_root(cache_root, manifest.authority_source, manifest.remote_sig)
        cache_hit, integrity = _cache_state(
            selected_root,
            sig=manifest.remote_sig,
            archive_sha256=manifest.archive_sha256,
            authority_source=manifest.authority_source,
        )
        resolution["cache_hit"] = cache_hit
        resolution["integrity_check_result"] = integrity
        if not cache_hit:
            selected_root, integrity = _materialize_selected_toolkit(
                cache_root=cache_root,
                manifest=manifest,
                timeout_s=timeout_s,
            )
            resolution["download_performed"] = True
            resolution["integrity_check_result"] = integrity
            resolution["resolution_mode"] = "remote-download"
        else:
            resolution["resolution_mode"] = "remote-cache-hit"
        _write_last_selected(authority_root, manifest.remote_sig)
        return _selection_from_root(
            authority_source=manifest.authority_source,
            sig=manifest.remote_sig,
            root=selected_root,
            resolution=resolution,
        )
    except Exception as exc:
        resolution["error"] = str(exc)
        stale_sig = resolution["cached_sig_before"]
        if not _allow_stale(cfg) or not stale_sig:
            resolution["resolution_mode"] = "fail-closed"
            raise GovernanceToolkitRuntimeError(str(exc), resolution=resolution) from exc
        stale_root = _version_root(cache_root, manifest_url, stale_sig)
        cache_hit, integrity = _cache_state(
            stale_root,
            sig=stale_sig,
            archive_sha256=None,
            authority_source=manifest_url,
        )
        resolution["selected_sig"] = stale_sig
        resolution["cache_hit"] = cache_hit
        resolution["integrity_check_result"] = integrity
        if not cache_hit:
            resolution["resolution_mode"] = "fail-closed"
            raise GovernanceToolkitRuntimeError(str(exc), resolution=resolution) from exc
        resolution["resolution_mode"] = "stale-cache"
        return _selection_from_root(
            authority_source=manifest_url,
            sig=stale_sig,
            root=stale_root,
            resolution=resolution,
        )
