import json
import sys
from collections import defaultdict
from pathlib import Path

FORBIDDEN_FIELDS = {
    "derivation",
    "generated_from",
    "generation_policy",
    "source_line",
}
SUPPORTED_TYPES = {
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
}
SUPPORTED_BINDING_TYPES = {"resolver_contract", "constraint_pack"}
BINDING_REQUIRED_FIELDS = (
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


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL {message}")


def require_count(name: str, expected: int, actual: int | None) -> None:
    if actual != expected:
        fail(f"meta count mismatch {name}: expected={expected} actual={actual}")


def ensure_unique_id(obj: dict, seen: set[str]) -> None:
    obj_id = str(obj.get("id", "")).strip()
    if not obj_id:
        fail(f"missing id in {obj.get('type')}")
    if obj_id in seen:
        fail(f"duplicate id {obj_id}")
    seen.add(obj_id)


def validate_bindings(bindings: dict[str, dict], oracles: dict[str, dict]) -> None:
    for binding_id, binding in bindings.items():
        oracle_ref = binding.get("oracle_ref")
        if oracle_ref not in oracles:
            fail(f"binding {binding_id} references missing oracle {oracle_ref}")
        if binding.get("conflict_policy") != "fail_closed":
            fail(f"binding {binding_id} conflict_policy must be fail_closed")


def validate_rule_links(rules: dict[str, dict], caps: dict[str, dict]) -> None:
    rule_refs: defaultdict[str, int] = defaultdict(int)
    for capability_id, capability in caps.items():
        for rule_id in capability.get("triggers_rules", []):
            if rule_id not in rules:
                fail(f"capability {capability_id} references missing rule {rule_id}")
            rule_refs[rule_id] += 1
    for rule_id in rules:
        if rule_refs[rule_id] == 0:
            fail(f"orphan rule {rule_id}")


def validate_routes(
    caps: dict[str, dict], providers: dict[str, dict], routes: dict[str, dict]
) -> None:
    cap_route_refs: defaultdict[str, int] = defaultdict(int)
    for route_id, route in routes.items():
        for capability_id in route.get("covers_capabilities", []):
            if capability_id not in caps:
                fail(f"route {route_id} references missing capability {capability_id}")
            cap_route_refs[capability_id] += 1
    for capability_id, capability in caps.items():
        if not capability.get("triggers_rules"):
            fail(f"capability without rules {capability_id}")
        if cap_route_refs[capability_id] == 0:
            fail(f"capability not covered by any route {capability_id}")
    for route_id, route in routes.items():
        chain = route.get("provider_chain", [])
        caps_needed = set(route.get("covers_capabilities", []))
        provided = set()
        seen = set()
        for provider_id in chain:
            if provider_id in seen:
                fail(f"route {route_id} provider_chain contains duplicate provider {provider_id}")
            seen.add(provider_id)
            if provider_id not in providers:
                fail(f"route {route_id} references missing provider {provider_id}")
            provided.update(providers[provider_id].get("provides_capabilities", []))
        missing = sorted(caps_needed - provided)
        if missing:
            fail(f"provider coverage in route {route_id} missing {missing}")


def validate_surfaces(routes: dict[str, dict], surfaces: dict[str, dict]) -> None:
    for surface_id, surface in surfaces.items():
        if not surface.get("route_ref"):
            fail(f"surface without route_ref {surface_id}")
        if not surface.get("requires_capabilities"):
            fail(f"surface without requires_capabilities {surface_id}")
        if surface["route_ref"] not in routes:
            fail(f"surface {surface_id} references missing route {surface['route_ref']}")


def validate_implementations(impls: dict[str, dict], routes: dict[str, dict]) -> None:
    for implementation_id, implementation in impls.items():
        route_id = str(implementation.get("implements_route", "")).strip()
        if not route_id or route_id not in routes:
            fail(f"implementation {implementation_id} references missing route {route_id}")
        required = set(routes[route_id].get("covers_capabilities", []))
        declared = set(implementation.get("declared_capabilities", []))
        missing = sorted(required - declared)
        if missing:
            fail(f"implementation {implementation_id} missing capabilities {missing}")


def validate_workflow(
    rules: dict[str, dict],
    caps: dict[str, dict],
    routes: dict[str, dict],
    surfaces: dict[str, dict],
    steps: dict[str, dict],
    transitions: dict[str, dict],
    gates: dict[str, dict],
    invalidations: dict[str, dict],
    rollbacks: dict[str, dict],
) -> None:
    if not steps:
        return
    if not transitions:
        fail("workflow model missing transitions")

    step_surface_refs: set[str] = set()
    step_route_refs: set[str] = set()
    entrypoint_keys: set[tuple[str, str]] = set()
    inbound: defaultdict[str, int] = defaultdict(int)
    outbound: defaultdict[str, int] = defaultdict(int)
    transitions_seen: set[tuple[str, str]] = set()
    gates_by_step: defaultdict[str, list[dict]] = defaultdict(list)
    invalidations_by_step: defaultdict[str, list[dict]] = defaultdict(list)
    rollbacks_by_step: defaultdict[str, list[dict]] = defaultdict(list)

    for step_id, step in steps.items():
        surface_ref = str(step.get("surface_ref", "")).strip()
        route_ref = str(step.get("route_ref", "")).strip()
        if not surface_ref:
            fail(f"workflow_step {step_id} missing surface_ref")
        if not route_ref:
            fail(f"workflow_step {step_id} missing route_ref")
        if surface_ref not in surfaces:
            fail(f"workflow_step {step_id} references missing surface {surface_ref}")
        if route_ref not in routes:
            fail(f"workflow_step {step_id} references missing route {route_ref}")
        if surfaces[surface_ref].get("route_ref") != route_ref:
            fail(f"workflow_step {step_id} surface/route mismatch {surface_ref}->{route_ref}")
        required_caps = step.get("required_capabilities", [])
        if not required_caps:
            fail(f"workflow_step {step_id} missing required_capabilities")
        for capability_id in required_caps:
            if capability_id not in caps:
                fail(f"workflow_step {step_id} references missing capability {capability_id}")
        for substep_id in step.get("required_substeps", []):
            if substep_id not in steps:
                fail(f"workflow_step {step_id} references missing substep {substep_id}")
        entry_scope = step.get("entry_scope")
        entry_mode = step.get("entry_mode")
        entry_scope_text = "" if entry_scope is None else str(entry_scope).strip()
        entry_mode_text = "" if entry_mode is None else str(entry_mode).strip()
        if bool(entry_scope_text) ^ bool(entry_mode_text):
            fail(f"workflow_step {step_id} entry_scope/entry_mode mismatch")
        if entry_scope_text and entry_mode_text:
            key = (entry_scope_text, entry_mode_text)
            if key in entrypoint_keys:
                fail(f"duplicate workflow entrypoint {key}")
            entrypoint_keys.add(key)
        step_surface_refs.add(surface_ref)
        step_route_refs.add(route_ref)

    for transition_id, transition in transitions.items():
        from_step = str(transition.get("from_step", "")).strip()
        to_step = str(transition.get("to_step", "")).strip()
        if from_step not in steps:
            fail(f"workflow_transition {transition_id} references missing from_step {from_step}")
        if to_step not in steps:
            fail(f"workflow_transition {transition_id} references missing to_step {to_step}")
        key = (from_step, to_step)
        if key in transitions_seen:
            fail(f"duplicate workflow transition {from_step}->{to_step}")
        transitions_seen.add(key)
        outbound[from_step] += 1
        inbound[to_step] += 1

    for gate_id, gate in gates.items():
        step_ref = str(gate.get("step_ref", "")).strip()
        if step_ref not in steps:
            fail(f"workflow_gate {gate_id} references missing step {step_ref}")
        caps_list = gate.get("gate_capabilities", [])
        rules_list = gate.get("gate_rule_ids", [])
        if not caps_list and not rules_list:
            fail(f"workflow_gate {gate_id} missing gate_capabilities/gate_rule_ids")
        for capability_id in caps_list:
            if capability_id not in caps:
                fail(f"workflow_gate {gate_id} references missing capability {capability_id}")
        for rule_id in rules_list:
            if rule_id not in rules:
                fail(f"workflow_gate {gate_id} references missing rule {rule_id}")
        gates_by_step[step_ref].append(gate)

    for invalidation_id, invalidation in invalidations.items():
        failing_step = str(invalidation.get("failing_step", "")).strip()
        invalidates_step = str(invalidation.get("invalidates_step", "")).strip()
        if failing_step not in steps:
            fail(
                f"workflow_invalidation {invalidation_id} references missing "
                f"failing_step {failing_step}"
            )
        if invalidates_step not in steps:
            fail(
                f"workflow_invalidation {invalidation_id} references missing "
                f"invalidates_step {invalidates_step}"
            )
        invalidations_by_step[failing_step].append(invalidation)

    for rollback_id, rollback in rollbacks.items():
        from_step = str(rollback.get("from_step", "")).strip()
        rollback_to = str(rollback.get("rollback_to_step", "")).strip()
        if from_step not in steps:
            fail(f"workflow_rollback {rollback_id} references missing from_step {from_step}")
        if rollback_to not in steps:
            fail(
                f"workflow_rollback {rollback_id} references missing rollback_to_step {rollback_to}"
            )
        rollbacks_by_step[from_step].append(rollback)

    if set(surfaces) != step_surface_refs:
        missing = sorted(set(surfaces) - step_surface_refs)
        fail(f"workflow missing surface coverage {missing}")
    if set(routes) != step_route_refs:
        missing = sorted(set(routes) - step_route_refs)
        fail(f"workflow missing route coverage {missing}")

    for step_id, step in steps.items():
        root = bool(step.get("root_marker"))
        terminal = bool(step.get("terminal_marker"))
        has_entry_gate = any(
            str(item.get("gate_kind", "")) == "entry" for item in gates_by_step[step_id]
        )
        if not has_entry_gate and not root:
            fail(f"workflow_step {step_id} missing entry gate/root marker")
        if inbound[step_id] == 0 and not root:
            fail(f"dead workflow step without inbound transition {step_id}")
        if outbound[step_id] == 0 and not terminal:
            fail(f"dead workflow step without outbound transition {step_id}")
        if not invalidations_by_step[step_id]:
            fail(f"workflow_step {step_id} missing invalidation handling")
        if step.get("rollback_required") and not rollbacks_by_step[step_id]:
            fail(f"workflow_step {step_id} missing rollback target")


def main(path: str) -> None:
    objs = load(Path(path))
    if not objs or objs[0].get("type") != "meta":
        fail(": first object must be meta")

    counts = objs[0].get("counts", {})
    seen_ids: set[str] = set()
    rules: dict[str, dict] = {}
    caps: dict[str, dict] = {}
    providers: dict[str, dict] = {}
    routes: dict[str, dict] = {}
    surfaces: dict[str, dict] = {}
    impls: dict[str, dict] = {}
    bindings: dict[str, dict] = {}
    oracles: dict[str, dict] = {}
    sections: dict[str, dict] = {}
    notes: dict[str, dict] = {}
    source_meta: dict[str, dict] = {}
    workflow_steps: dict[str, dict] = {}
    workflow_transitions: dict[str, dict] = {}
    workflow_gates: dict[str, dict] = {}
    workflow_invalidations: dict[str, dict] = {}
    workflow_rollbacks: dict[str, dict] = {}
    binding_meta = None

    for obj in objs:
        obj_type = obj.get("type")
        if obj_type == "source_line":
            fail(": source_line objects are not allowed in v2.0.0")
        for field in FORBIDDEN_FIELDS:
            if field in obj:
                fail(f"forbidden field '{field}' present in {obj.get('id')}")
        if obj_type not in SUPPORTED_TYPES:
            fail(f"unsupported object type {obj_type}")
        ensure_unique_id(obj, seen_ids)
        if obj_type == "rule":
            rules[obj["id"]] = obj
        elif obj_type == "capability":
            caps[obj["id"]] = obj
        elif obj_type == "provider":
            providers[obj["id"]] = obj
        elif obj_type == "route":
            routes[obj["id"]] = obj
        elif obj_type == "surface":
            surfaces[obj["id"]] = obj
        elif obj_type == "implementation":
            impls[obj["id"]] = obj
        elif obj_type == "workflow_step":
            workflow_steps[obj["id"]] = obj
        elif obj_type == "workflow_transition":
            workflow_transitions[obj["id"]] = obj
        elif obj_type == "workflow_gate":
            workflow_gates[obj["id"]] = obj
        elif obj_type == "workflow_invalidation":
            workflow_invalidations[obj["id"]] = obj
        elif obj_type == "workflow_rollback":
            workflow_rollbacks[obj["id"]] = obj
        elif obj_type == "binding_meta":
            if binding_meta is not None:
                fail(": exactly one binding_meta object is required")
            binding_meta = obj
        elif obj_type == "oracle":
            oracle_id = str(obj.get("id", "")).strip()
            if not oracle_id:
                fail("oracle missing id")
            if not str(obj.get("oracle_kind", "")).strip():
                fail(f"oracle {oracle_id} missing oracle_kind")
            oracles[oracle_id] = obj
        elif obj_type == "obligation_binding":
            binding_id = str(obj.get("id", "")).strip()
            if not binding_id:
                fail("binding missing id")
            for field in BINDING_REQUIRED_FIELDS:
                if field not in obj:
                    fail(f"binding {binding_id} missing field {field}")
            binding_type = str(obj.get("binding_type", "")).strip()
            if binding_type not in SUPPORTED_BINDING_TYPES:
                fail(f"binding {binding_id} has unsupported binding_type {binding_type}")
            for field in (
                "verification_mode",
                "verification_method",
                "semantic_group",
                "conflict_policy",
            ):
                if not str(obj.get(field, "")).strip():
                    fail(f"binding {binding_id} has empty field {field}")
            bindings[binding_id] = obj
        elif obj_type == "section":
            sections[obj["id"]] = obj
        elif obj_type == "note":
            notes[obj["id"]] = obj
        elif obj_type == "source_meta":
            source_meta[obj["id"]] = obj

    if binding_meta is None:
        fail(": exactly one binding_meta object is required")

    count_expectations = {
        "records": len(objs),
        "rules": len(rules),
        "binding_meta": 1,
        "obligation_bindings": len(bindings),
        "oracles": len(oracles),
    }
    optional_counts = {
        "capabilities": len(caps),
        "providers": len(providers),
        "routes": len(routes),
        "surfaces": len(surfaces),
        "implementations": len(impls),
        "sections": len(sections),
        "notes": len(notes),
        "source_meta": len(source_meta),
        "workflow_steps": len(workflow_steps),
        "workflow_transitions": len(workflow_transitions),
        "workflow_gates": len(workflow_gates),
        "workflow_invalidations": len(workflow_invalidations),
        "workflow_rollbacks": len(workflow_rollbacks),
    }
    for name, expected in count_expectations.items():
        require_count(name, expected, counts.get(name))
    for name, expected in optional_counts.items():
        if name in counts:
            require_count(name, expected, counts.get(name))

    validate_bindings(bindings, oracles)
    if caps:
        validate_rule_links(rules, caps)
        validate_routes(caps, providers, routes)
    if surfaces:
        validate_surfaces(routes, surfaces)
    if impls:
        validate_implementations(impls, routes)
    if workflow_steps:
        validate_workflow(
            rules,
            caps,
            routes,
            surfaces,
            workflow_steps,
            workflow_transitions,
            workflow_gates,
            workflow_invalidations,
            workflow_rollbacks,
        )

    print("V2.0.0 STRICT VALIDATION OK")
    print(
        f"records={len(objs)} rules={len(rules)} sections={len(sections)} "
        f"notes={len(notes)} source_meta={len(source_meta)} "
        f"binding_meta={1 if binding_meta else 0} "
        f"bindings={len(bindings)} oracles={len(oracles)}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_master_spec_v2.py <jsonl>")
        sys.exit(1)
    main(sys.argv[1])
