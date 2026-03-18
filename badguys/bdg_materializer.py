from __future__ import annotations

import io
import json
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from badguys.bdg_loader import BdgAsset, BdgAssetEntry, BdgTest
from badguys.bdg_recipe import base_cfg_sections, validate_test_config_boundary
from badguys.bdg_subst import SubstCtx, subst_text


@dataclass(frozen=True)
class MaterializedAssets:
    root: Path
    files: dict[str, Path]
    subjects: dict[str, str] = field(default_factory=dict)


def _safe_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum() or ch in {"_", "-", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _build_git_add_file_patch(*, rel_path: str, text: str) -> str:
    if not text.endswith("\n"):
        text += "\n"
    lines = text.splitlines(True)
    body = "".join(["+" + line for line in lines])
    return (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{rel_path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}"
    )


def _subject_relpath(
    *,
    subjects: dict[str, str],
    subject_name: object,
    test_id: str,
    asset_id: str,
    field_name: str,
) -> str:
    if not isinstance(subject_name, str) or not subject_name:
        raise SystemExit(f"FAIL: bdg: {test_id}.{asset_id}.{field_name} must be a string")
    rel_path = subjects.get(subject_name)
    if rel_path is None:
        raise SystemExit(f"FAIL: bdg: missing subject '{subject_name}' for {test_id}.{asset_id}")
    return rel_path


def _string_list(
    *,
    value: object,
    test_id: str,
    asset_id: str,
    field_name: str,
) -> list[str]:
    if not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
        raise SystemExit(f"FAIL: bdg: {test_id}.{asset_id}.{field_name} must be list[str]")
    return list(value)


def _build_python_patch_script(
    *,
    body: str,
    issue_id: str,
    subjects: dict[str, str],
    declared_subjects: list[str],
    test_id: str,
    asset_id: str,
) -> str:
    declared_relpaths = [
        _subject_relpath(
            subjects=subjects,
            subject_name=name,
            test_id=test_id,
            asset_id=asset_id,
            field_name="declared_subjects",
        )
        for name in declared_subjects
    ]
    subjects_json = json.dumps(subjects, sort_keys=True)
    files_json = json.dumps(declared_relpaths)
    issue_json = json.dumps(issue_id)
    script_json = json.dumps(body)
    return (
        "from __future__ import annotations\n\n"
        f"FILES = {files_json}\n\n"
        "from pathlib import Path\n\n"
        "REPO = Path(__file__).resolve().parents[1]\n"
        f"_SUBJECTS = {subjects_json}\n"
        f"_ISSUE_ID = {issue_json}\n"
        f"_SCRIPT = {script_json}\n\n"
        "class _Ctx:\n"
        "    def path(self, name: str) -> Path:\n"
        "        rel = _SUBJECTS.get(name)\n"
        "        if rel is None:\n"
        "            raise KeyError(f'unknown subject: {name}')\n"
        "        return REPO / rel\n\n"
        "    def write_text(self, name: str, text: str) -> None:\n"
        "        path = self.path(name)\n"
        "        path.parent.mkdir(parents=True, exist_ok=True)\n"
        "        path.write_text(text, encoding='utf-8')\n\n"
        "    def unlink(self, name: str) -> None:\n"
        "        try:\n"
        "            self.path(name).unlink()\n"
        "        except FileNotFoundError:\n"
        "            pass\n\n"
        "    def write_outside_repo(self, text: str) -> None:\n"
        "        outside = (REPO / '..' / f'badguys_sentinel_issue_{_ISSUE_ID}.txt').resolve()\n"
        "        outside.write_text(text, encoding='utf-8')\n\n"
        "ctx = _Ctx()\n"
        "_GLOBALS = {\n"
        "    '__builtins__': __builtins__,\n"
        "    '__file__': str(__file__),\n"
        "    'FILES': FILES,\n"
        "    'Path': Path,\n"
        "    'REPO': REPO,\n"
        "    '_ISSUE_ID': _ISSUE_ID,\n"
        "    '_SUBJECTS': _SUBJECTS,\n"
        "    'ctx': ctx,\n"
        "}\n"
        "exec(compile(_SCRIPT, str(__file__), 'exec'), _GLOBALS, _GLOBALS)\n"
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


def _format_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    raise SystemExit(f"FAIL: bdg materializer: unsupported TOML value: {type(value).__name__}")


def _dump_toml_sections(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for section in ("suite", "lock", "guard", "filters", "runner"):
        table = data.get(section, {})
        if not isinstance(table, dict):
            raise SystemExit(f"FAIL: bdg materializer: section '{section}' must be a table")
        parts.append(f"[{section}]")
        for key in sorted(table.keys()):
            parts.append(f"{key} = {_format_toml_value(table[key])}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def materialize_assets(
    *,
    repo_root: Path,
    config_path: Path,
    subst: SubstCtx,
    bdg: BdgTest,
) -> MaterializedAssets:
    validate_test_config_boundary(repo_root=repo_root, config_path=config_path, bdg=bdg)
    root = repo_root / "patches" / "badguys_artifacts" / f"issue_{subst.issue_id}" / bdg.test_id
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    subjects = dict(bdg.subjects)
    for asset_id, asset in bdg.assets.items():
        files[asset_id] = _materialize_one(
            root=root,
            repo_root=repo_root,
            config_path=config_path,
            subst=subst,
            test_id=bdg.test_id,
            asset=asset,
            subjects=subjects,
        )
    return MaterializedAssets(root=root, files=files, subjects=subjects)


def _materialize_python_asset(
    *,
    repo_root: Path,
    subst: SubstCtx,
    test_id: str,
    asset: BdgAsset,
    subjects: dict[str, str],
) -> Path:
    declared_subjects = _string_list(
        value=asset.declared_subjects,
        test_id=test_id,
        asset_id=asset.asset_id,
        field_name="declared_subjects",
    )
    patches_dir = repo_root / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    safe_test = _safe_name(test_id)
    safe_id = _safe_name(asset.asset_id)
    path = patches_dir / f"issue_{subst.issue_id}__bdg__{safe_test}__{safe_id}.py"
    body = subst_text(asset.content or "", ctx=subst)
    script = _build_python_patch_script(
        body=body,
        issue_id=subst.issue_id,
        subjects=subjects,
        declared_subjects=declared_subjects,
        test_id=test_id,
        asset_id=asset.asset_id,
    )
    path.write_text(script, encoding="utf-8")
    return path


def _materialize_patch_asset(
    *,
    repo_root: Path,
    subst: SubstCtx,
    test_id: str,
    asset: BdgAsset,
    subjects: dict[str, str],
) -> Path:
    rel_path = _subject_relpath(
        subjects=subjects,
        subject_name=asset.subject,
        test_id=test_id,
        asset_id=asset.asset_id,
        field_name="subject",
    )
    patches_dir = repo_root / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    safe_test = _safe_name(test_id)
    safe_id = _safe_name(asset.asset_id)
    path = patches_dir / f"issue_{subst.issue_id}__bdg__{safe_test}__{safe_id}.patch"
    content = subst_text(asset.content or "", ctx=subst)
    path.write_text(_build_git_add_file_patch(rel_path=rel_path, text=content), encoding="utf-8")
    return path


def _zip_entry_bytes(
    *,
    entry: BdgAssetEntry,
    subst: SubstCtx,
    subjects: dict[str, str],
    test_id: str,
    asset_id: str,
) -> tuple[str, bytes]:
    zip_name = entry.zip_name
    if not isinstance(zip_name, str) or not zip_name:
        raise SystemExit(f"FAIL: bdg: missing zip_name for {test_id}.{asset_id}.{entry.name}")
    if entry.kind == "git_patch_text":
        rel_path = _subject_relpath(
            subjects=subjects,
            subject_name=entry.subject,
            test_id=test_id,
            asset_id=f"{asset_id}.{entry.name}",
            field_name="subject",
        )
        data = _build_git_add_file_patch(
            rel_path=rel_path,
            text=subst_text(entry.content, ctx=subst),
        ).encode("utf-8")
        return zip_name, data
    if entry.kind == "python_patch_script":
        declared_subjects = _string_list(
            value=entry.declared_subjects,
            test_id=test_id,
            asset_id=f"{asset_id}.{entry.name}",
            field_name="declared_subjects",
        )
        data = _build_python_patch_script(
            body=subst_text(entry.content, ctx=subst),
            issue_id=subst.issue_id,
            subjects=subjects,
            declared_subjects=declared_subjects,
            test_id=test_id,
            asset_id=f"{asset_id}.{entry.name}",
        ).encode("utf-8")
        return zip_name, data
    raise SystemExit(f"FAIL: bdg: unsupported zip entry kind for {test_id}.{asset_id}.{entry.name}")


def _materialize_zip_asset(
    *,
    repo_root: Path,
    subst: SubstCtx,
    test_id: str,
    asset: BdgAsset,
    subjects: dict[str, str],
) -> Path:
    patches_dir = repo_root / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    safe_test = _safe_name(test_id)
    safe_id = _safe_name(asset.asset_id)
    path = patches_dir / f"issue_{subst.issue_id}__bdg__{safe_test}__{safe_id}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in asset.entries:
            zip_name, data = _zip_entry_bytes(
                entry=entry,
                subst=subst,
                subjects=subjects,
                test_id=test_id,
                asset_id=asset.asset_id,
            )
            info = zipfile.ZipInfo(zip_name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    path.write_bytes(buf.getvalue())
    return path


def _materialize_one(
    *,
    root: Path,
    repo_root: Path,
    config_path: Path,
    subst: SubstCtx,
    test_id: str,
    asset: BdgAsset,
    subjects: dict[str, str],
) -> Path:
    safe_id = _safe_name(asset.asset_id)
    if asset.kind == "text":
        path = root / f"{safe_id}.txt"
        path.write_text(subst_text(asset.content or "", ctx=subst), encoding="utf-8")
        return path

    if asset.kind == "toml_text":
        path = root / f"{safe_id}.toml"
        base = base_cfg_sections(repo_root=repo_root, config_path=config_path)
        delta_raw = subst_text(asset.content or "", ctx=subst)
        delta = tomllib.loads(delta_raw) if delta_raw.strip() else {}
        if not isinstance(delta, dict):
            raise SystemExit("FAIL: bdg materializer: toml_text delta must decode to a table")
        merged = _deep_merge(base, delta)
        path.write_text(_dump_toml_sections(merged), encoding="utf-8")
        return path

    if asset.kind == "python_patch_script":
        return _materialize_python_asset(
            repo_root=repo_root,
            subst=subst,
            test_id=test_id,
            asset=asset,
            subjects=subjects,
        )

    if asset.kind == "git_patch_text":
        return _materialize_patch_asset(
            repo_root=repo_root,
            subst=subst,
            test_id=test_id,
            asset=asset,
            subjects=subjects,
        )

    if asset.kind == "patch_zip_manifest":
        return _materialize_zip_asset(
            repo_root=repo_root,
            subst=subst,
            test_id=test_id,
            asset=asset,
            subjects=subjects,
        )

    raise SystemExit(f"FAIL: bdg materializer: unsupported asset kind: {asset.kind}")
