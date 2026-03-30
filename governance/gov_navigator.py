from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SEPARATOR = "-" * 80


def load_jsonl(path: Path) -> list[dict]:
    objs: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                objs.append(json.loads(line))
    return objs


def index_by_type(objs: list[dict]) -> tuple[dict | None, dict[str, list[dict]]]:
    meta = None
    groups: dict[str, list[dict]] = {}
    for obj in objs:
        obj_type = str(obj.get("type", ""))
        if obj_type == "meta":
            meta = obj
            continue
        groups.setdefault(obj_type, []).append(obj)
    return meta, groups


def _append_header(out: list[str], title: str) -> None:
    out.append(title)
    out.append(SEPARATOR)


def _fmt_list(values: list[str], *, empty: str = "-", limit: int | None = None) -> str:
    if not values:
        return empty
    unique = list(dict.fromkeys(str(value) for value in values if str(value).strip()))
    if not unique:
        return empty
    if limit is not None and len(unique) > limit:
        kept = ", ".join(unique[:limit])
        return f"{kept}, ... (+{len(unique) - limit})"
    return ", ".join(unique)


def _heading_root(section: dict) -> str:
    heading = str(section.get("heading_path", "")).strip()
    if not heading:
        return "<no heading_path>"
    return heading.split(" > ", 1)[0]


def _build_workflow_index(groups: dict[str, list[dict]]) -> dict[str, object]:
    steps = {str(obj.get("id", "")): obj for obj in groups.get("workflow_step", [])}
    transitions = groups.get("workflow_transition", [])
    gates = groups.get("workflow_gate", [])
    invalidations = groups.get("workflow_invalidation", [])
    rollbacks = groups.get("workflow_rollback", [])
    next_steps: dict[str, list[str]] = defaultdict(list)
    gates_by_step: dict[str, list[dict]] = defaultdict(list)
    invalidations_by_step: dict[str, list[str]] = defaultdict(list)
    rollbacks_by_step: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    for step_id, step in steps.items():
        if step.get("root_marker"):
            roots.append(step_id)
    for transition in transitions:
        from_step = str(transition.get("from_step", "")).strip()
        to_step = str(transition.get("to_step", "")).strip()
        if from_step and to_step:
            next_steps[from_step].append(to_step)
    for gate in gates:
        step_ref = str(gate.get("step_ref", "")).strip()
        if step_ref:
            gates_by_step[step_ref].append(gate)
    for item in invalidations:
        step_ref = str(item.get("failing_step", "")).strip()
        target = str(item.get("invalidates_step", "")).strip()
        if step_ref and target:
            invalidations_by_step[step_ref].append(target)
    for item in rollbacks:
        step_ref = str(item.get("from_step", "")).strip()
        target = str(item.get("rollback_to_step", "")).strip()
        if step_ref and target:
            rollbacks_by_step[step_ref].append(target)
    return {
        "steps": steps,
        "next_steps": next_steps,
        "gates_by_step": gates_by_step,
        "invalidations_by_step": invalidations_by_step,
        "rollbacks_by_step": rollbacks_by_step,
        "roots": sorted(roots),
    }


def _append_graph_summary(out: list[str], groups: dict[str, list[dict]]) -> None:
    _append_header(out, "GRAPH SUMMARY")
    out.append(f"surfaces: {len(groups.get('surface', []))}")
    out.append(f"routes: {len(groups.get('route', []))}")
    out.append(f"providers: {len(groups.get('provider', []))}")
    out.append(f"capabilities: {len(groups.get('capability', []))}")
    out.append(f"implementations: {len(groups.get('implementation', []))}")
    out.append(f"workflow_steps: {len(groups.get('workflow_step', []))}")
    out.append(f"workflow_transitions: {len(groups.get('workflow_transition', []))}")
    out.append(f"workflow_gates: {len(groups.get('workflow_gate', []))}")
    out.append(f"workflow_invalidations: {len(groups.get('workflow_invalidation', []))}")
    out.append(f"workflow_rollbacks: {len(groups.get('workflow_rollback', []))}")
    out.append("")


def _append_surface_navigation(out: list[str], groups: dict[str, list[dict]]) -> None:
    surfaces = {str(obj.get("id", "")): obj for obj in groups.get("surface", [])}
    routes = {str(obj.get("id", "")): obj for obj in groups.get("route", [])}
    providers = {str(obj.get("id", "")): obj for obj in groups.get("provider", [])}
    implementations = groups.get("implementation", [])
    route_impls: dict[str, list[str]] = defaultdict(list)
    for impl in implementations:
        route_impls[str(impl.get("implements_route", ""))].append(str(impl.get("id", "")))
    _append_header(out, "ENTRY SURFACES")
    for surface_id in sorted(surfaces):
        surface = surfaces[surface_id]
        route_id = str(surface.get("route_ref", ""))
        route = routes.get(route_id, {})
        provider_chain = [str(item) for item in route.get("provider_chain", [])]
        out.append(f"[{surface_id}]")
        out.append(f"  route: {route_id or '-'}")
        required_caps = [str(item) for item in surface.get("requires_capabilities", [])]
        out.append("  requires_capabilities: " + _fmt_list(required_caps, limit=12))
        out.append(f"  provider_chain: {_fmt_list(provider_chain)}")
        out.append(f"  implementations: {_fmt_list(route_impls.get(route_id, []))}")
        provider_caps: list[str] = []
        for provider_id in provider_chain:
            provided_caps = providers.get(provider_id, {}).get("provides_capabilities", [])
            provider_caps.extend(str(item) for item in provided_caps)
        out.append(f"  provider_capabilities: {_fmt_list(provider_caps, limit=12)}")
        out.append("")


def _append_route_navigation(out: list[str], groups: dict[str, list[dict]]) -> None:
    routes = {str(obj.get("id", "")): obj for obj in groups.get("route", [])}
    implementations = groups.get("implementation", [])
    route_impls: dict[str, list[str]] = defaultdict(list)
    for impl in implementations:
        route_impls[str(impl.get("implements_route", ""))].append(str(impl.get("id", "")))
    _append_header(out, "ROUTE NAVIGATION")
    for route_id in sorted(routes):
        route = routes[route_id]
        out.append(f"[{route_id}]")
        covered_caps = [str(item) for item in route.get("covers_capabilities", [])]
        provider_chain = [str(item) for item in route.get("provider_chain", [])]
        out.append("  covers_capabilities: " + _fmt_list(covered_caps, limit=12))
        out.append("  provider_chain: " + _fmt_list(provider_chain))
        out.append(f"  implementations: {_fmt_list(route_impls.get(route_id, []))}")
        out.append("")


def _append_capability_navigation(out: list[str], groups: dict[str, list[dict]]) -> None:
    caps = {str(obj.get("id", "")): obj for obj in groups.get("capability", [])}
    providers = groups.get("provider", [])
    routes = groups.get("route", [])
    cap_routes: dict[str, list[str]] = defaultdict(list)
    cap_providers: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        route_id = str(route.get("id", ""))
        for cap_id in route.get("covers_capabilities", []):
            cap_routes[str(cap_id)].append(route_id)
    for provider in providers:
        provider_id = str(provider.get("id", ""))
        for cap_id in provider.get("provides_capabilities", []):
            cap_providers[str(cap_id)].append(provider_id)
    _append_header(out, "CAPABILITY NAVIGATION")
    for cap_id in sorted(caps):
        cap = caps[cap_id]
        rule_ids = [str(item) for item in cap.get("triggers_rules", [])]
        out.append(f"[{cap_id}]")
        out.append(f"  rules_count: {len(rule_ids)}")
        out.append(f"  rules: {_fmt_list(rule_ids, limit=12)}")
        out.append(f"  routes: {_fmt_list(cap_routes.get(cap_id, []))}")
        out.append(f"  providers: {_fmt_list(cap_providers.get(cap_id, []))}")
        out.append("")


def _append_implementation_navigation(out: list[str], groups: dict[str, list[dict]]) -> None:
    implementations = {str(obj.get("id", "")): obj for obj in groups.get("implementation", [])}
    _append_header(out, "IMPLEMENTATION NAVIGATION")
    for impl_id in sorted(implementations):
        impl = implementations[impl_id]
        out.append(f"[{impl_id}]")
        out.append(f"  implements_route: {impl.get('implements_route', '')}")
        declared_caps = [str(item) for item in impl.get("declared_capabilities", [])]
        out.append("  declared_capabilities: " + _fmt_list(declared_caps, limit=12))
        out.append("")


def _append_workflow_roots(out: list[str], workflow: dict[str, object]) -> None:
    steps: dict[str, dict] = workflow["steps"]  # type: ignore[assignment]
    roots: list[str] = workflow["roots"]  # type: ignore[assignment]
    _append_header(out, "WORKFLOW ROOTS")
    for step_id in roots:
        step = steps[step_id]
        out.append(f"[{step_id}]")
        out.append(f"  branch: {step.get('branch', '')}")
        entry_scope = "" if step.get("entry_scope") is None else step.get("entry_scope", "")
        entry_mode = "" if step.get("entry_mode") is None else step.get("entry_mode", "")
        out.append(f"  entry_scope: {entry_scope}")
        out.append(f"  entry_mode: {entry_mode}")
        out.append(f"  route_ref: {step.get('route_ref', '')}")
        out.append(f"  surface_ref: {step.get('surface_ref', '')}")
        out.append("")


def _append_step_order(out: list[str], workflow: dict[str, object]) -> None:
    steps: dict[str, dict] = workflow["steps"]  # type: ignore[assignment]
    next_steps: dict[str, list[str]] = workflow["next_steps"]  # type: ignore[assignment]
    by_branch: dict[str, list[str]] = defaultdict(list)
    for step_id, step in steps.items():
        by_branch[str(step.get("branch", ""))].append(step_id)
    _append_header(out, "STEP ORDER")
    for branch in sorted(by_branch):
        roots = [step_id for step_id in by_branch[branch] if steps[step_id].get("root_marker")]
        out.append(f"[{branch}]")
        for root in sorted(roots):
            chain = [root]
            seen = {root}
            current = root
            while len(next_steps.get(current, [])) == 1:
                nxt = next_steps[current][0]
                if nxt in seen or steps.get(nxt, {}).get("branch") != branch:
                    break
                chain.append(nxt)
                seen.add(nxt)
                current = nxt
            out.append(f"  {' -> '.join(chain)}")
        out.append("")


def _append_entry_gates(out: list[str], workflow: dict[str, object]) -> None:
    steps: dict[str, dict] = workflow["steps"]  # type: ignore[assignment]
    gates_by_step: dict[str, list[dict]] = workflow["gates_by_step"]  # type: ignore[assignment]
    _append_header(out, "ENTRY GATES")
    for step_id in sorted(steps):
        entry = [
            str(item.get("id", ""))
            for item in gates_by_step.get(step_id, [])
            if str(item.get("gate_kind", "")) == "entry"
        ]
        out.append(f"[{step_id}]")
        out.append(f"  entry_gates: {_fmt_list(entry)}")
        out.append("")


def _append_invalidation_map(out: list[str], workflow: dict[str, object]) -> None:
    invalidations_by_step: dict[str, list[str]] = workflow["invalidations_by_step"]  # type: ignore[assignment]
    _append_header(out, "INVALIDATION MAP")
    for step_id in sorted(invalidations_by_step):
        out.append(f"[{step_id}] -> {_fmt_list(invalidations_by_step[step_id])}")
    out.append("")


def _append_rollback_map(out: list[str], workflow: dict[str, object]) -> None:
    rollbacks_by_step: dict[str, list[str]] = workflow["rollbacks_by_step"]  # type: ignore[assignment]
    _append_header(out, "ROLLBACK MAP")
    for step_id in sorted(rollbacks_by_step):
        out.append(f"[{step_id}] -> {_fmt_list(rollbacks_by_step[step_id])}")
    out.append("")


def _append_workflow_step_details(out: list[str], workflow: dict[str, object]) -> None:
    steps: dict[str, dict] = workflow["steps"]  # type: ignore[assignment]
    next_steps: dict[str, list[str]] = workflow["next_steps"]  # type: ignore[assignment]
    invalidations_by_step: dict[str, list[str]] = workflow["invalidations_by_step"]  # type: ignore[assignment]
    rollbacks_by_step: dict[str, list[str]] = workflow["rollbacks_by_step"]  # type: ignore[assignment]
    _append_header(out, "WORKFLOW STEP DETAILS")
    for step_id in sorted(steps):
        step = steps[step_id]
        out.append(f"[{step_id}]")
        out.append(f"  display_name: {step.get('display_name', '')}")
        out.append(f"  branch: {step.get('branch', '')}")
        out.append(f"  route_ref: {step.get('route_ref', '')}")
        out.append(f"  surface_ref: {step.get('surface_ref', '')}")
        required_caps = [str(item) for item in step.get("required_capabilities", [])]
        required_substeps = [str(item) for item in step.get("required_substeps", [])]
        out.append("  required_capabilities: " + _fmt_list(required_caps, limit=12))
        out.append("  required_substeps: " + _fmt_list(required_substeps))
        out.append(f"  next_steps: {_fmt_list(next_steps.get(step_id, []))}")
        out.append(f"  invalidates: {_fmt_list(invalidations_by_step.get(step_id, []))}")
        out.append(f"  rollback_to: {_fmt_list(rollbacks_by_step.get(step_id, []))}")
        out.append("")


def _append_legacy_navigation(out: list[str], groups: dict[str, list[dict]]) -> None:
    sections = groups.get("section", [])
    rules = groups.get("rule", [])
    roots: dict[str, int] = defaultdict(int)
    for section in sections:
        roots[_heading_root(section)] += 1
    _append_header(out, "NAVIGATION")
    out.append("graph_status: legacy authority corpus (no execution graph objects present)")
    out.append(f"section_roots: {len(roots)}")
    out.append(f"rules: {len(rules)}")
    out.append("")
    _append_header(out, "LEGACY SECTION ROOTS")
    for root_name in sorted(roots):
        out.append(f"- {root_name}: {roots[root_name]} sections")
    out.append("")


def build_navigation_lines(objs: list[dict]) -> list[str]:
    _meta, groups = index_by_type(objs)
    graph_counts = [
        len(groups.get("surface", [])),
        len(groups.get("route", [])),
        len(groups.get("provider", [])),
        len(groups.get("capability", [])),
        len(groups.get("implementation", [])),
    ]
    out: list[str] = []
    if any(graph_counts):
        _append_graph_summary(out, groups)
        _append_surface_navigation(out, groups)
        _append_route_navigation(out, groups)
        _append_capability_navigation(out, groups)
        _append_implementation_navigation(out, groups)
        if groups.get("workflow_step"):
            workflow = _build_workflow_index(groups)
            _append_workflow_roots(out, workflow)
            _append_step_order(out, workflow)
            _append_entry_gates(out, workflow)
            _append_invalidation_map(out, workflow)
            _append_rollback_map(out, workflow)
            _append_workflow_step_details(out, workflow)
        return out
    _append_legacy_navigation(out, groups)
    return out


def build_navigation_json(objs: list[dict]) -> dict:
    _meta, groups = index_by_type(objs)
    workflow = _build_workflow_index(groups)
    steps: dict[str, dict] = workflow["steps"]  # type: ignore[assignment]
    next_steps: dict[str, list[str]] = workflow["next_steps"]  # type: ignore[assignment]
    invalidations_by_step: dict[str, list[str]] = workflow["invalidations_by_step"]  # type: ignore[assignment]
    rollbacks_by_step: dict[str, list[str]] = workflow["rollbacks_by_step"]  # type: ignore[assignment]
    return {
        "graph_counts": {
            "surfaces": len(groups.get("surface", [])),
            "routes": len(groups.get("route", [])),
            "providers": len(groups.get("provider", [])),
            "capabilities": len(groups.get("capability", [])),
            "implementations": len(groups.get("implementation", [])),
            "workflow_steps": len(groups.get("workflow_step", [])),
        },
        "workflow_roots": workflow["roots"],
        "steps": {
            step_id: {
                "display_name": step.get("display_name", ""),
                "branch": step.get("branch", ""),
                "route_ref": step.get("route_ref", ""),
                "surface_ref": step.get("surface_ref", ""),
                "required_capabilities": step.get("required_capabilities", []),
                "required_substeps": step.get("required_substeps", []),
                "next_steps": next_steps.get(step_id, []),
                "invalidates": invalidations_by_step.get(step_id, []),
                "rollback_to": rollbacks_by_step.get(step_id, []),
                "entry_scope": (
                    "" if step.get("entry_scope") is None else step.get("entry_scope", "")
                ),
                "entry_mode": (
                    "" if step.get("entry_mode") is None else step.get("entry_mode", "")
                ),
            }
            for step_id, step in sorted(steps.items())
        },
    }


def render(path_in: Path, path_out: Path, *, as_json: bool = False) -> None:
    objs = load_jsonl(path_in)
    if as_json:
        payload = json.dumps(
            build_navigation_json(objs),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        path_out.write_text(payload + "\n", encoding="utf-8")
        return
    path_out.write_text("\n".join(build_navigation_lines(objs)), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_jsonl")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv[1:])
    in_path = Path(args.input_jsonl)
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = in_path.with_suffix(".nav.json" if args.json else ".nav.txt")
    render(in_path, out_path, as_json=args.json)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
