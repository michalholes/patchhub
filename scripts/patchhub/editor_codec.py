from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT_NAME = "PHB-HR-TOML v1"
FORMAT_HEADER = "# PHB-HR-TOML v1"
DOCUMENT_PATHS = {
    "specification": "governance/specification.jsonl",
    "governance": "governance/governance.jsonl",
}
OBJECT_TYPE_ORDER = [
    "meta",
    "binding_meta",
    "obligation_binding",
    "oracle",
    "rule",
    "capability",
    "provider",
    "route",
    "surface",
    "implementation",
    "section",
    "note",
    "source_meta",
    "workflow_step",
    "workflow_transition",
    "workflow_gate",
    "workflow_invalidation",
    "workflow_rollback",
]
SCAFFOLD_CATALOG = {
    "meta": (
        '[[object]]\ntype = "meta"\nid = "META.NEW"\nversion = "1.0.1"\n'
        'authoritative = true\ndraft_only = false\ndescription = ""\n[object.counts]\n'
        "records = 0\nrules = 0\nbinding_meta = 0\nobligation_bindings = 0\noracles = 0\n"
        "capabilities = 0\nproviders = 0\nroutes = 0\nsurfaces = 0\nimplementations = 0\n"
        "sections = 0\nnotes = 0\nsource_meta = 0\nworkflow_steps = 0\n"
        "workflow_transitions = 0\nworkflow_gates = 0\nworkflow_invalidations = 0\n"
        "workflow_rollbacks = 0\n"
    ),
    "binding_meta": '[[object]]\ntype = "binding_meta"\nid = "BINDING_META.NEW"\n',
    "obligation_binding": (
        '[[object]]\ntype = "obligation_binding"\nid = "BINDING.NEW"\n'
        'binding_type = "resolver_contract"\nsymbol_role = ""\n'
        'authoritative_semantics = ""\npeer_renderers = []\nshared_contract_refs = []\n'
        "downstream_consumers = []\nexception_state_refs = []\nrequired_wiring = []\n"
        'forbidden = []\nrequired_validation = []\nverification_mode = "machine"\n'
        'verification_method = ""\nsemantic_group = ""\nconflict_policy = "fail_closed"\n'
        'oracle_ref = ""\n[object.match]\nphase = ""\ntarget = ""\n'
    ),
    "oracle": '[[object]]\ntype = "oracle"\nid = "ORACLE.NEW"\noracle_kind = ""\n'
    'description = ""\n',
    "rule": (
        '[[object]]\ntype = "rule"\nid = "RULE.NEW"\nheading_path = ""\norder = 0\n'
        'kind = "paragraph"\nlayer_prefix = ""\nrule_layer = ""\nnormativity = "MUST"\n'
        'scope = ""\nstatement = ""\n'
    ),
    "capability": (
        '[[object]]\ntype = "capability"\nid = "CAP.NEW"\nheading_path = ""\nscope = ""\n'
        'family_id = ""\ncapability_kind = ""\nname = ""\ntriggers_rules = []\n'
    ),
    "provider": (
        '[[object]]\ntype = "provider"\nid = "PROVIDER.NEW"\nheading_path = ""\nscope = ""\n'
        'family_id = ""\nprovider_kind = ""\nname = ""\nprovides_capabilities = []\n'
    ),
    "route": (
        '[[object]]\ntype = "route"\nid = "ROUTE.NEW"\nheading_path = ""\nscope = ""\n'
        'family_id = ""\nroute_kind = ""\nname = ""\ncovers_capabilities = []\n'
        "provider_chain = []\n"
    ),
    "surface": (
        '[[object]]\ntype = "surface"\nid = "SURFACE.NEW"\nheading_path = ""\n'
        'route_ref = ""\nrequires_capabilities = []\n'
    ),
    "implementation": (
        '[[object]]\ntype = "implementation"\nid = "IMPLEMENTATION.NEW"\n'
        'implements_route = ""\ndeclared_capabilities = []\n'
    ),
    "section": (
        '[[object]]\ntype = "section"\nid = "SECTION.NEW"\nheading_path = ""\n'
        'level = 0\norder = 0\ntext = ""\n'
    ),
    "note": (
        '[[object]]\ntype = "note"\nid = "NOTE.NEW"\nkind = ""\nheading_path = ""\n'
        'order = 0\ntext = ""\n'
    ),
    "source_meta": (
        '[[object]]\ntype = "source_meta"\nid = "SOURCE_META.NEW"\nsource_file = ""\n'
        "[object.payload]\n"
    ),
    "workflow_step": (
        '[[object]]\ntype = "workflow_step"\nid = "WORKFLOW_STEP.NEW"\n'
        'display_name = ""\nbranch = ""\nroute_ref = ""\nsurface_ref = ""\n'
        'required_capabilities = []\nrequired_substeps = []\nentry_scope = ""\n'
        'entry_mode = ""\nroot_marker = false\nterminal_marker = false\n'
        "rollback_required = false\n"
    ),
    "workflow_transition": (
        '[[object]]\ntype = "workflow_transition"\nid = "WORKFLOW_TRANSITION.NEW"\n'
        'from_step = ""\nto_step = ""\n'
    ),
    "workflow_gate": (
        '[[object]]\ntype = "workflow_gate"\nid = "WORKFLOW_GATE.NEW"\nstep_ref = ""\n'
        'gate_kind = "entry"\ngate_capabilities = []\ngate_rule_ids = []\n'
    ),
    "workflow_invalidation": (
        '[[object]]\ntype = "workflow_invalidation"\nid = "WORKFLOW_INVALIDATION.NEW"\n'
        'failing_step = ""\ninvalidates_step = ""\n'
    ),
    "workflow_rollback": (
        '[[object]]\ntype = "workflow_rollback"\nid = "WORKFLOW_ROLLBACK.NEW"\n'
        'from_step = ""\nrollback_to_step = ""\n'
    ),
}


@dataclass(frozen=True)
class EditorCodecError(Exception):
    code: str
    message: str
    primary_id: str = ""

    def __str__(self) -> str:
        return self.message


def document_relpath(document: str) -> str:
    key = str(document or "").strip()
    if key not in DOCUMENT_PATHS:
        raise EditorCodecError("document_unknown", f"Unknown document: {key}")
    return DOCUMENT_PATHS[key]


def parse_jsonl_text(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"JSONL line {idx} parse failed: {exc.msg}"
            raise EditorCodecError("jsonl_invalid", msg) from exc
        if not isinstance(obj, dict):
            raise EditorCodecError("jsonl_non_object", f"JSONL line {idx} must contain an object")
        out.append(obj)
    return out


def parse_human_text(text: str):
    first = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    if first != FORMAT_HEADER:
        msg = f"First non-empty line must be exactly {FORMAT_HEADER}"
        raise EditorCodecError("missing_header", msg)
    try:
        payload = tomllib.loads(str(text or ""))
    except tomllib.TOMLDecodeError as exc:
        raise EditorCodecError("toml_parse_failed", str(exc)) from exc
    objects = payload.get("object")
    if not isinstance(objects, list):
        raise EditorCodecError("object_table_missing", "TOML must define [[object]] blocks")
    out = [_normalize_object(item) for item in objects if isinstance(item, dict)]
    if len(out) != len(objects):
        raise EditorCodecError("object_invalid", "Each [[object]] block must decode to a table")
    for idx, obj in enumerate(out, start=1):
        if not str(obj.get("type", "")).strip():
            raise EditorCodecError("missing_type", f"[[object]] block {idx} missing type")
        if not str(obj.get("id", "")).strip():
            raise EditorCodecError("missing_id", f"[[object]] block {idx} missing id")
    return type("ParsedDocument", (), {"objects": out})()


def scaffold_text(object_type: str) -> str:
    key = str(object_type or "").strip()
    if key not in SCAFFOLD_CATALOG:
        raise EditorCodecError("unknown_scaffold", f"Unknown scaffold type: {key}")
    return SCAFFOLD_CATALOG[key]


def scaffold_object(object_type: str) -> dict[str, Any]:
    return parse_human_text(FORMAT_HEADER + "\n\n" + scaffold_text(object_type)).objects[0]


def human_text_from_jsonl_text(text: str) -> str:
    return human_text_from_objects(parse_jsonl_text(text))


def human_text_from_objects(objects: Iterable[dict[str, Any]]) -> str:
    lines = [FORMAT_HEADER, ""]
    for index, obj in enumerate(_normalize_object(o) for o in objects):
        if index:
            lines.append("")
        _emit_object(lines, obj)
    return "\n".join(lines).rstrip() + "\n"


def jsonl_text_from_objects(objects: Iterable[dict[str, Any]]) -> str:
    body = [json.dumps(_normalize_object(obj), ensure_ascii=False) for obj in objects]
    return "\n".join(body) + "\n"


def recompute_meta_counts(objects: list[dict[str, Any]]) -> None:
    meta = next((obj for obj in objects if obj.get("type") == "meta"), None)
    if meta is None:
        return
    counts = {
        "records": len(objects),
        "rules": _count(objects, "rule"),
        "binding_meta": _count(objects, "binding_meta"),
        "obligation_bindings": _count(objects, "obligation_binding"),
        "oracles": _count(objects, "oracle"),
        "capabilities": _count(objects, "capability"),
        "providers": _count(objects, "provider"),
        "routes": _count(objects, "route"),
        "surfaces": _count(objects, "surface"),
        "implementations": _count(objects, "implementation"),
        "sections": _count(objects, "section"),
        "notes": _count(objects, "note"),
        "source_meta": _count(objects, "source_meta"),
        "workflow_steps": _count(objects, "workflow_step"),
        "workflow_transitions": _count(objects, "workflow_transition"),
        "workflow_gates": _count(objects, "workflow_gate"),
        "workflow_invalidations": _count(objects, "workflow_invalidation"),
        "workflow_rollbacks": _count(objects, "workflow_rollback"),
    }
    meta["counts"] = counts


def _count(objects: list[dict[str, Any]], kind: str) -> int:
    return sum(obj.get("type") == kind for obj in objects)


def _normalize_object(obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise EditorCodecError("object_invalid", "Object must be a table")
    out = {key: obj[key] for key in ("type", "id") if key in obj}
    for key, value in obj.items():
        if key not in {"type", "id"}:
            out[str(key)] = _normalize_value(value)
    return out


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _emit_object(lines: list[str], obj: dict[str, Any]) -> None:
    lines.append("[[object]]")
    tables = []
    for key, value in sorted(obj.items(), key=lambda item: _field_sort_key(item[0])):
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            lines.append(f"{key} = {_format_toml_value(value)}")
    for key, value in tables:
        _emit_table(lines, ["object", key], value)


def _emit_table(lines: list[str], path: list[str], table: dict[str, Any]) -> None:
    lines.append(f"[{'.'.join(path)}]")
    tables = []
    for key, value in sorted(table.items(), key=lambda item: _field_sort_key(item[0])):
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            lines.append(f"{key} = {_format_toml_value(value)}")
    for key, value in tables:
        _emit_table(lines, [*path, key], value)


def _field_sort_key(key: str) -> tuple[int, str]:
    return (0 if key == "type" else 1 if key == "id" else 2, key)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    text = "" if value is None else str(value)
    if "\n" in text:
        escaped = text.replace('"""', '"""')
        return f'"""{escaped}"""'
    return json.dumps(text, ensure_ascii=False)


def surface_capability_check(objects: list[dict[str, Any]]) -> tuple[bool, str, str, str]:
    caps = {str(obj.get("id", "")) for obj in objects if obj.get("type") == "capability"}
    for obj in objects:
        if obj.get("type") != "surface":
            continue
        sid = str(obj.get("id", ""))
        for cap_id in obj.get("requires_capabilities", []):
            cap = str(cap_id)
            if cap not in caps:
                msg = f"surface {sid} references missing capability {cap}"
                return False, sid, cap, msg
    return True, "", "", ""


def parse_entry_tuple(detail: str) -> tuple[str, str]:
    if "(" not in detail or ")" not in detail:
        return "", ""
    left, _, right = detail[detail.find("(") + 1 : detail.find(")")].partition(",")
    return left.strip().strip("'\""), right.strip().strip("'\"")


def parse_list_head(detail: str) -> str:
    if "[" not in detail or "]" not in detail:
        return ""
    return detail[detail.find("[") + 1 : detail.find("]")].split(",", 1)[0].strip().strip("'\"")


def last_error_detail(error_text: str) -> str:
    lines = [line.strip() for line in str(error_text).splitlines() if line.strip()]
    return lines[-1] if lines else str(error_text)


def _run_repo_validator(validator: Path, objects: list[dict[str, Any]]) -> tuple[bool, str]:
    validator = Path(validator).resolve()
    if not validator.is_file():
        return False, f"Validator not found: {validator}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp = Path(tmp_dir) / "editor_validate.jsonl"
        temp.write_text(jsonl_text_from_objects(objects), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(validator), str(temp)],
            capture_output=True,
            text=True,
            cwd=str(validator.parent),
            check=False,
        )
    detail = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    return proc.returncode == 0, detail or "Validation failed"


def validate_human_text(
    *,
    validator_path: Path,
    human_text: str,
    loaded_objects: list[dict[str, Any]],
    failure_builder,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    try:
        objects = deepcopy(parse_human_text(human_text).objects)
    except EditorCodecError as exc:
        return (
            False,
            [],
            failure_builder(
                objects=[],
                loaded_objects=loaded_objects,
                error_text=str(exc),
                code=exc.code,
                primary_id=exc.primary_id,
            ),
        )
    ok, detail = _run_repo_validator(validator_path, objects)
    if not ok:
        return (
            False,
            objects,
            failure_builder(
                objects=objects,
                loaded_objects=loaded_objects,
                error_text=detail,
                code="validator_failure",
            ),
        )
    ok, primary, secondary, detail = surface_capability_check(objects)
    if ok:
        return True, objects, None
    return (
        False,
        objects,
        failure_builder(
            objects=objects,
            loaded_objects=loaded_objects,
            error_text=detail,
            code="surface_capability_invalid",
            primary_id=primary,
            secondary_id=secondary,
        ),
    )
