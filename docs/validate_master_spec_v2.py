import json
import sys
from collections import defaultdict

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


def load(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def fail(message):
    raise SystemExit(f"FAIL {message}")


def require_count(name, expected, actual):
    if actual != expected:
        fail(f"meta count mismatch {name}: expected={expected} actual={actual}")


def validate_bindings(bindings, oracles):
    for binding_id, binding in bindings.items():
        oracle_ref = binding.get("oracle_ref")
        if oracle_ref not in oracles:
            fail(f"binding {binding_id} references missing oracle {oracle_ref}")
        if binding.get("conflict_policy") != "fail_closed":
            fail(f"binding {binding_id} conflict_policy must be fail_closed")


def validate_rule_links(rules, caps):
    rule_refs = defaultdict(int)
    for capability_id, capability in caps.items():
        for rule_id in capability.get("triggers_rules", []):
            if rule_id not in rules:
                fail(
                    f"capability {capability_id} references missing rule {rule_id}"
                )
            rule_refs[rule_id] += 1
    for rule_id in rules:
        if rule_refs[rule_id] == 0:
            fail(f"orphan rule {rule_id}")


def validate_routes(caps, providers, routes):
    cap_route_refs = defaultdict(int)
    for route_id, route in routes.items():
        for capability_id in route.get("covers_capabilities", []):
            if capability_id not in caps:
                fail(
                    f"route {route_id} references missing capability {capability_id}"
                )
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
                fail(
                    "route "
                    f"{route_id} provider_chain contains duplicate provider "
                    f"{provider_id}"
                )
            seen.add(provider_id)
            if provider_id not in providers:
                fail(f"route {route_id} references missing provider {provider_id}")
            provided.update(providers[provider_id].get("provides_capabilities", []))
        missing = sorted(caps_needed - provided)
        if missing:
            fail(f"provider coverage in route {route_id} missing {missing}")


def validate_surfaces(routes, surfaces):
    for surface_id, surface in surfaces.items():
        if not surface.get("route_ref"):
            fail(f"surface without route_ref {surface_id}")
        if not surface.get("requires_capabilities"):
            fail(f"surface without requires_capabilities {surface_id}")
        if surface["route_ref"] not in routes:
            fail(
                f"surface {surface_id} references missing route {surface['route_ref']}"
            )


def validate_implementations(impls, routes):
    for implementation_id, implementation in impls.items():
        route_id = implementation.get("implements_route")
        if route_id not in routes:
            fail(
                f"implementation {implementation_id} references missing route {route_id}"
            )
        required = set(routes[route_id].get("covers_capabilities", []))
        declared = set(implementation.get("declared_capabilities", []))
        missing = sorted(required - declared)
        if missing:
            fail(f"implementation {implementation_id} missing capabilities {missing}")


def main(path):
    objs = load(path)
    if not objs or objs[0].get("type") != "meta":
        fail(": first object must be meta")

    counts = objs[0].get("counts", {})
    rules = {}
    caps = {}
    providers = {}
    routes = {}
    surfaces = {}
    impls = {}
    bindings = {}
    oracles = {}
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
            oracle_id = obj.get("id")
            if oracle_id in oracles:
                fail(f"duplicate oracle id {oracle_id}")
            if not str(obj.get("oracle_kind", "")).strip():
                fail(f"oracle {oracle_id} missing oracle_kind")
            oracles[oracle_id] = obj
        elif obj_type == "obligation_binding":
            binding_id = obj.get("id")
            if binding_id in bindings:
                fail(f"duplicate binding id {binding_id}")
            for field in BINDING_REQUIRED_FIELDS:
                if field not in obj:
                    fail(f"binding {binding_id} missing field {field}")
            if obj["binding_type"] not in SUPPORTED_BINDING_TYPES:
                fail(
                    "binding "
                    f"{binding_id} has unsupported binding_type "
                    f"{obj['binding_type']}"
                )
            for field in (
                "verification_mode",
                "verification_method",
                "semantic_group",
                "conflict_policy",
            ):
                if not str(obj.get(field, "")).strip():
                    fail(f"binding {binding_id} has empty field {field}")
            bindings[binding_id] = obj

    if binding_meta is None:
        fail(": exactly one binding_meta object is required")

    require_count("rules", len(rules), counts.get("rules"))
    require_count("capabilities", len(caps), counts.get("capabilities"))
    require_count("providers", len(providers), counts.get("providers"))
    require_count("routes", len(routes), counts.get("routes"))
    require_count("surfaces", len(surfaces), counts.get("surfaces"))
    require_count("implementations", len(impls), counts.get("implementations"))
    require_count("binding_meta", 1, counts.get("binding_meta"))
    require_count("obligation_bindings", len(bindings), counts.get("obligation_bindings"))
    require_count("oracles", len(oracles), counts.get("oracles"))

    validate_bindings(bindings, oracles)
    validate_rule_links(rules, caps)
    validate_routes(caps, providers, routes)
    validate_surfaces(routes, surfaces)
    validate_implementations(impls, routes)

    print("V2.0.0 STRICT VALIDATION OK")
    print(
        f"rules={len(rules)} caps={len(caps)} providers={len(providers)} "
        f"routes={len(routes)} surfaces={len(surfaces)} "
        f"impls={len(impls)} binding_meta={1 if binding_meta else 0} "
        f"bindings={len(bindings)} oracles={len(oracles)}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_master_spec_v2.py <jsonl>")
        sys.exit(1)
    main(sys.argv[1])
