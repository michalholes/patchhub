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
}
SUPPORTED_BINDING_TYPES = {
    "resolver_contract",
    "constraint_pack",
}
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
