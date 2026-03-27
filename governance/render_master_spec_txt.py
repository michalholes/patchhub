import json
import sys
from pathlib import Path


def load_jsonl(path: Path):
    objs = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                objs.append(json.loads(line))
    return objs


def index_by_type(objs):
    meta = None
    rules = {}
    caps = {}
    providers = {}
    routes = {}
    surfaces = {}
    impls = {}
    others = []

    for obj in objs:
        obj_type = obj.get("type")
        if obj_type == "meta":
            meta = obj
        elif obj_type == "rule":
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
        else:
            others.append(obj)
    return meta, rules, caps, providers, routes, surfaces, impls, others


def fmt_source(rule):
    migration_source = rule.get("migration_source")
    if isinstance(migration_source, dict):
        return (
            f"{migration_source.get('file', '?')}"
            f"#L{migration_source.get('line', '?')}"
        )
    return ""


def render(path_in: Path, path_out: Path):
    objs = load_jsonl(path_in)
    meta, rules, caps, providers, routes, surfaces, impls, others = index_by_type(objs)

    out = []
    out.append("MASTER_SPEC (human-readable)")
    out.append("=" * 80)

    if meta:
        out.append("META")
        out.append("-" * 80)
        for key in sorted(meta.keys()):
            if key == "type":
                continue
            out.append(f"{key}: {meta[key]}")
        out.append("")

    out.append("SURFACES")
    out.append("-" * 80)
    for surface_id in sorted(surfaces):
        surface = surfaces[surface_id]
        out.append(f"[{surface_id}]")
        out.append(f"  kind: {surface.get('kind', '')}")
        out.append(f"  source_file: {surface.get('source_file', '')}")
        out.append(f"  heading: {surface.get('heading', '')}")
        out.append(f"  route_ref: {surface.get('route_ref', '')}")
        required_capabilities = surface.get("requires_capabilities", [])
        out.append(f"  requires_capabilities ({len(required_capabilities)}):")
        for capability_id in sorted(required_capabilities):
            out.append(f"    - {capability_id}")
        out.append("")

    out.append("ROUTES")
    out.append("-" * 80)
    for route_id in sorted(routes):
        route = routes[route_id]
        out.append(f"[{route_id}]")
        out.append(f"  surface_id: {route.get('surface_id', '')}")
        provider_chain = route.get("provider_chain", [])
        out.append(f"  provider_chain ({len(provider_chain)}):")
        for provider_id in provider_chain:
            out.append(f"    - {provider_id}")
        covered_capabilities = route.get("covers_capabilities", [])
        out.append(f"  covers_capabilities ({len(covered_capabilities)}):")
        for capability_id in sorted(covered_capabilities):
            out.append(f"    - {capability_id}")
        out.append("")

    out.append("PROVIDERS")
    out.append("-" * 80)
    for provider_id in sorted(providers):
        provider = providers[provider_id]
        out.append(f"[{provider_id}]")
        provided_capabilities = provider.get("provides_capabilities", [])
        out.append(f"  provides_capabilities ({len(provided_capabilities)}):")
        for capability_id in sorted(provided_capabilities):
            out.append(f"    - {capability_id}")
        out.append("")

    out.append("CAPABILITIES")
    out.append("-" * 80)
    for capability_id in sorted(caps):
        capability = caps[capability_id]
        out.append(f"[{capability_id}]")
        out.append(f"  applies_to: {capability.get('applies_to', '')}")
        triggered_rules = capability.get("triggers_rules", [])
        out.append(f"  triggers_rules ({len(triggered_rules)}):")
        for rule_id in sorted(triggered_rules):
            out.append(f"    - {rule_id}")
        out.append("")

    out.append("RULES")
    out.append("-" * 80)
    for rule_id in sorted(rules):
        rule = rules[rule_id]
        out.append(f"[{rule_id}]")
        out.append(f"  rule_layer: {rule.get('rule_layer', '')}")
        out.append(f"  normativity: {rule.get('normativity', '')}")
        out.append(f"  scope: {rule.get('scope', '')}")
        source = fmt_source(rule)
        if source:
            out.append(f"  source: {source}")
        heading_path = rule.get("heading_path")
        if heading_path:
            out.append(f"  heading_path: {heading_path}")
        statement = rule.get("statement", "")
        out.append("  statement:")
        out.append(f"    {statement}")
        out.append("")

    if impls:
        out.append("IMPLEMENTATIONS")
        out.append("-" * 80)
        for implementation_id in sorted(impls):
            implementation = impls[implementation_id]
            out.append(f"[{implementation_id}]")
            out.append(
                f"  implements_route: {implementation.get('implements_route', '')}"
            )
            providers_available = implementation.get("providers_available", [])
            out.append(f"  providers_available ({len(providers_available)}):")
            for provider_id in providers_available:
                out.append(f"    - {provider_id}")
            declared_capabilities = implementation.get("declared_capabilities", [])
            out.append(
                f"  declared_capabilities ({len(declared_capabilities)}):"
            )
            for capability_id in sorted(declared_capabilities):
                out.append(f"    - {capability_id}")
            out.append("")

    if others:
        out.append("OTHER OBJECTS")
        out.append("-" * 80)
        out.append(f"count: {len(others)}")
        out.append("")

    path_out.write_text("\n".join(out), encoding="utf-8")


def main(argv):
    if len(argv) not in (2, 3):
        print("Usage: python render_master_spec_txt.py <input.jsonl> [output.txt]")
        return 2

    in_path = Path(argv[1])
    out_path = Path(argv[2]) if len(argv) == 3 else in_path.with_suffix(".txt")
    render(in_path, out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
