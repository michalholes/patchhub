from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NoReturn
from zipfile import ZipFile

GOVERNANCE_SPEC_PATH = "governance/governance.jsonl"
REPO_SPEC_PATH = "governance/specification.jsonl"


def _default_spec_path(repo_path: str) -> str:
    if repo_path == REPO_SPEC_PATH:
        return REPO_SPEC_PATH
    if repo_path.startswith("governance/"):
        return GOVERNANCE_SPEC_PATH
    return REPO_SPEC_PATH


UNBOUND = "RULE RESOLVER: FAIL - unbound_target"
CONFLICT = "RULE RESOLVER: FAIL - conflicting_obligations"
REQUIRED_FIELDS = (
    "id",
    "binding_type",
    "match",
    "symbol_role",
    "authoritative_semantics",
    "peer_renderers",
    "shared_contract_refs",
    "downstream_consumers",
    "exception_state_refs",
    "required_wiring",
    "forbidden",
    "required_validation",
    "verification_mode",
    "verification_method",
    "semantic_group",
    "conflict_policy",
    "oracle_ref",
)
SUPPORTED_BINDING_TYPES = {"resolver_contract", "constraint_pack"}


def fail_unbound() -> NoReturn:
    print("RESULT: FAIL")
    print(UNBOUND)
    raise SystemExit(1)


def fail_conflict() -> NoReturn:
    print("RESULT: FAIL")
    print(CONFLICT)
    raise SystemExit(1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--workspace-snapshot", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--handoff-output", required=True)
    parser.add_argument("--pack-output", required=True)
    parser.add_argument("--hash-output", required=True)
    return parser.parse_args(argv)


def read_snapshot(path: Path) -> dict[str, bytes]:
    with ZipFile(path, "r") as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}


def split_target(raw: str) -> tuple[str, str | None]:
    repo_path, sep, symbol = raw.partition("::")
    repo_path = repo_path.strip()
    if not repo_path:
        fail_unbound()
    return repo_path, symbol.strip() if sep and symbol.strip() else None


def resolve_symbol(entries: dict[str, bytes], repo_path: str, symbol: str | None) -> None:
    raw = entries.get(repo_path)
    if raw is None:
        fail_unbound()
    if symbol is None:
        return
    text = raw.decode("utf-8", errors="ignore")
    patterns = [
        rf"^def\s+{re.escape(symbol)}\s*\(",
        rf"^async\s+def\s+{re.escape(symbol)}\s*\(",
        rf"^class\s+{re.escape(symbol)}\b",
        rf"^function\s+{re.escape(symbol)}\s*\(",
        rf"^(?:const|let|var)\s+{re.escape(symbol)}\s*=",
    ]
    hits = 0
    for line in text.splitlines():
        stripped = line.strip()
        if any(re.match(pattern, stripped) for pattern in patterns):
            hits += 1
    if hits == 0:
        fail_unbound()
    if hits > 1:
        fail_conflict()


def target_scope(repo_path: str) -> str:
    if repo_path.startswith("governance/"):
        return "authority_scope"
    return "implementation_scope"


def target_mode(scope: str) -> str:
    if scope == "authority_scope":
        return "discovery"
    return "final"


def collect_objects(objects: list[dict]) -> tuple[dict, list[dict], dict[str, dict]]:
    binding_meta = None
    bindings: list[dict] = []
    oracles: dict[str, dict] = {}
    for obj in objects:
        kind = obj.get("type")
        if kind == "binding_meta":
            if binding_meta is not None:
                fail_conflict()
            binding_meta = obj
            continue
        if kind == "oracle":
            oracle_id = str(obj.get("id", "")).strip()
            if not oracle_id:
                fail_unbound()
            oracles[oracle_id] = obj
            continue
        if kind != "obligation_binding":
            continue
        for field in REQUIRED_FIELDS:
            if field not in obj:
                fail_unbound()
        if obj.get("binding_type") not in SUPPORTED_BINDING_TYPES:
            fail_conflict()
        if obj.get("conflict_policy") != "fail_closed":
            fail_conflict()
        if not str(obj.get("oracle_ref", "")).strip():
            fail_unbound()
        bindings.append(obj)
    if binding_meta is None:
        fail_unbound()
    return binding_meta, bindings, oracles


def active_bindings(bindings: list[dict], mode: str, scope: str) -> list[dict]:
    active: list[dict] = []
    for binding in bindings:
        match = binding.get("match", {})
        if binding.get("binding_type") == "constraint_pack":
            active.append(binding)
            continue
        if match.get("phase") == mode and match.get("target") == scope:
            active.append(binding)
    return active


def ensure_consistency(bindings: list[dict], oracles: dict[str, dict]) -> None:
    if not bindings:
        fail_unbound()
    symbol_map: dict[tuple[str, str], list[str]] = {}
    semantic_map: dict[str, list[str]] = {}
    role_map: dict[str, set[str]] = {}
    for binding in bindings:
        binding_id = str(binding.get("id", "<missing-id>"))
        oracle_ref = str(binding.get("oracle_ref", "")).strip()
        if oracle_ref not in oracles:
            fail_unbound()
        match_key = json.dumps(binding.get("match", {}), sort_keys=True)
        role = str(binding.get("symbol_role", ""))
        semantics = str(binding.get("authoritative_semantics", ""))
        symbol_map.setdefault((match_key, role), []).append(binding_id)
        semantic_map.setdefault(semantics, []).append(binding_id)
        role_map.setdefault(role, set()).add(semantics)
        if not str(binding.get("verification_mode", "")).strip():
            fail_unbound()
        if not str(binding.get("verification_method", "")).strip():
            fail_unbound()
    if any(len(ids) > 1 for ids in symbol_map.values()):
        fail_conflict()
    if any(len(ids) > 1 for ids in semantic_map.values()):
        fail_conflict()
    if any(len(values) > 1 for values in role_map.values()):
        fail_conflict()


def union_values(bindings: list[dict], field: str) -> list:
    values = {item for binding in bindings for item in binding.get(field, [])}
    return sorted(values)


def binding_map(bindings: list[dict], key: str, value: str) -> dict[str, str]:
    return {binding[key]: binding[value] for binding in bindings}


def _resolve_workflow_contract(objects: list[dict], scope: str, mode: str) -> dict:
    steps = [obj for obj in objects if obj.get("type") == "workflow_step"]
    transitions = [obj for obj in objects if obj.get("type") == "workflow_transition"]
    gates = [obj for obj in objects if obj.get("type") == "workflow_gate"]
    rollbacks = [obj for obj in objects if obj.get("type") == "workflow_rollback"]
    candidates = [
        step
        for step in steps
        if ("" if step.get("entry_scope") is None else str(step.get("entry_scope", "")).strip())
        == scope
        and ("" if step.get("entry_mode") is None else str(step.get("entry_mode", "")).strip())
        == mode
    ]
    if not candidates:
        fail_unbound()
    if len(candidates) > 1:
        fail_conflict()
    step = candidates[0]
    step_id = str(step.get("id", "")).strip()
    next_steps = [
        str(item.get("to_step", "")).strip()
        for item in transitions
        if str(item.get("from_step", "")).strip() == step_id
    ]
    required_gates = [
        str(item.get("id", "")).strip()
        for item in gates
        if str(item.get("step_ref", "")).strip() == step_id
        and str(item.get("gate_kind", "")).strip() == "entry"
    ]
    rollback_contract = [
        {
            "id": str(item.get("id", "")).strip(),
            "rollback_to_step": str(item.get("rollback_to_step", "")).strip(),
        }
        for item in rollbacks
        if str(item.get("from_step", "")).strip() == step_id
    ]
    title = str(step.get("display_name", step_id)).strip() or step_id
    surface_ref = str(step.get("surface_ref", "")).strip()
    route_ref = str(step.get("route_ref", "")).strip()
    required_capabilities = [str(item) for item in step.get("required_capabilities", [])]
    summary = (
        f"entry_step={title}; surface={surface_ref}; route={route_ref}; "
        f"required_gates={required_gates}; next_steps={next_steps}"
    )
    return {
        "workflow_entry_step_id": step_id,
        "workflow_entry_title": title,
        "workflow_entry_surface": surface_ref,
        "workflow_entry_route": route_ref,
        "workflow_entry_required_capabilities": required_capabilities,
        "allowed_next_steps": next_steps,
        "required_gates": required_gates,
        "rollback_contract": rollback_contract,
        "workflow_human_summary": summary,
    }


def build_pack(
    spec_raw: bytes,
    mode: str,
    scope: str,
    spec_path: str = REPO_SPEC_PATH,
) -> bytes:
    objects = []
    for line in spec_raw.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            objects.append(json.loads(line))
    if not objects or objects[0].get("type") != "meta":
        fail_unbound()
    binding_meta, bindings, oracles = collect_objects(objects)
    active = active_bindings(bindings, mode, scope)
    ensure_consistency(active, oracles)
    workflow_contract = _resolve_workflow_contract(objects, scope, mode)
    pack = {
        "target_symbol": None,
        "target_scope": scope,
        "mode": mode,
        "spec_fingerprint": hashlib.sha256(spec_raw).hexdigest(),
        "binding_meta_id": binding_meta["id"],
        "active_bindings": active,
        "active_rule_ids": [binding["id"] for binding in active],
        "full_rule_text": binding_map(active, "id", "authoritative_semantics"),
        "match_basis": {binding["id"]: binding.get("match", {}) for binding in active},
        "authoritative_sources": [spec_path],
        "shared_contracts": union_values(active, "shared_contract_refs"),
        "downstream_consumers": union_values(active, "downstream_consumers"),
        "exception_state_refs": union_values(active, "exception_state_refs"),
        "required_wiring": union_values(active, "required_wiring"),
        "forbidden_strategies": union_values(active, "forbidden"),
        "required_validation": union_values(active, "required_validation"),
        "verification_mode_per_rule": binding_map(active, "id", "verification_mode"),
        "verification_method_per_rule": binding_map(
            active,
            "id",
            "verification_method",
        ),
        "oracle_refs": {binding["id"]: binding.get("oracle_ref") for binding in active},
        "aggregate_scope_metadata": {
            "binding_count": len(active),
            "mode": mode,
            "target_scope": scope,
        },
        **workflow_contract,
    }
    payload = json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True)
    return (payload + "\n").encode("utf-8")


def handoff_text(target: str, scope: str, mode: str, workflow_contract: dict) -> str:
    lines = [
        "SPEC CONTEXT",
        "RC version used: resolver-generated",
        "PM version used: resolver-generated",
        "",
        f"TARGET: {target}",
        f"TARGET_SCOPE: {scope}",
        f"MODE: {mode}",
        f"WORKFLOW_ENTRY_STEP_ID: {workflow_contract['workflow_entry_step_id']}",
        f"WORKFLOW_ENTRY_TITLE: {workflow_contract['workflow_entry_title']}",
        f"WORKFLOW_ENTRY_SURFACE: {workflow_contract['workflow_entry_surface']}",
        f"WORKFLOW_ENTRY_ROUTE: {workflow_contract['workflow_entry_route']}",
        f"ALLOWED_NEXT_STEPS: {workflow_contract['allowed_next_steps']}",
        f"REQUIRED_GATES: {workflow_contract['required_gates']}",
        f"ROLLBACK_CONTRACT: {workflow_contract['rollback_contract']}",
        f"WORKFLOW_HUMAN_SUMMARY: {workflow_contract['workflow_human_summary']}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    repo_path, symbol = split_target(args.target)
    entries = read_snapshot(Path(args.workspace_snapshot))
    resolve_symbol(entries, repo_path, symbol)
    scope = target_scope(repo_path)
    mode = target_mode(scope)
    expected_spec = _default_spec_path(repo_path)
    if args.spec != expected_spec:
        print("RESULT: FAIL")
        print(f"RULE RESOLVER: FAIL - spec_mismatch expected={expected_spec}:actual={args.spec}")
        raise SystemExit(1)
    spec_raw = Path(args.spec).read_bytes()
    pack_bytes = build_pack(spec_raw, mode, scope, spec_path=args.spec)
    pack = json.loads(pack_bytes.decode("utf-8"))
    workflow_contract = {
        "workflow_entry_step_id": pack["workflow_entry_step_id"],
        "workflow_entry_title": pack["workflow_entry_title"],
        "workflow_entry_surface": pack["workflow_entry_surface"],
        "workflow_entry_route": pack["workflow_entry_route"],
        "allowed_next_steps": pack["allowed_next_steps"],
        "required_gates": pack["required_gates"],
        "rollback_contract": pack["rollback_contract"],
        "workflow_human_summary": pack["workflow_human_summary"],
    }
    Path(args.handoff_output).write_text(
        handoff_text(args.target, scope, mode, workflow_contract),
        encoding="utf-8",
    )
    Path(args.pack_output).write_bytes(pack_bytes)
    digest = hashlib.sha256(pack_bytes).hexdigest()
    Path(args.hash_output).write_text(digest + "\n", encoding="utf-8")
    print("RESULT: PASS")


if __name__ == "__main__":
    main(sys.argv[1:])
