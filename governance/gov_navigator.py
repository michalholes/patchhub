from __future__ import annotations

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


def _append_graph_summary(out: list[str], groups: dict[str, list[dict]]) -> None:
    _append_header(out, "GRAPH SUMMARY")
    out.append(f"surfaces: {len(groups.get('surface', []))}")
    out.append(f"routes: {len(groups.get('route', []))}")
    out.append(f"providers: {len(groups.get('provider', []))}")
    out.append(f"capabilities: {len(groups.get('capability', []))}")
    out.append(f"implementations: {len(groups.get('implementation', []))}")
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
        out.append(
            "  requires_capabilities: "
            + _fmt_list([str(item) for item in surface.get("requires_capabilities", [])])
        )
        out.append(f"  provider_chain: {_fmt_list(provider_chain)}")
        out.append(f"  implementations: {_fmt_list(route_impls.get(route_id, []))}")
        provider_caps: list[str] = []
        for provider_id in provider_chain:
            provider_caps.extend(
                str(item)
                for item in providers.get(provider_id, {}).get("provides_capabilities", [])
            )
        out.append(f"  provider_capabilities: {_fmt_list(provider_caps, limit=10)}")
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
        out.append(
            "  covers_capabilities: "
            + _fmt_list([str(item) for item in route.get("covers_capabilities", [])], limit=12)
        )
        out.append(
            "  provider_chain: "
            + _fmt_list([str(item) for item in route.get("provider_chain", [])])
        )
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
        out.append(
            "  declared_capabilities: "
            + _fmt_list([str(item) for item in impl.get("declared_capabilities", [])], limit=12)
        )
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
        return out
    _append_legacy_navigation(out, groups)
    return out


def render(path_in: Path, path_out: Path) -> None:
    objs = load_jsonl(path_in)
    path_out.write_text("\n".join(build_navigation_lines(objs)), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("Usage: python gov_navigator.py <input.jsonl> [output.txt]")
        return 2
    in_path = Path(argv[1])
    out_path = Path(argv[2]) if len(argv) == 3 else in_path.with_suffix(".nav.txt")
    render(in_path, out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
