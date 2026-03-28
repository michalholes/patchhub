import json
import sys
from collections import Counter
from pathlib import Path


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


def fmt_source(obj: dict) -> str:
    source_span = obj.get("source_span")
    if isinstance(source_span, dict):
        file_name = source_span.get("file", "?")
        start = source_span.get("start_line", source_span.get("line", "?"))
        end = source_span.get("end_line")
        if end is None or end == start:
            return f"{file_name}#L{start}"
        return f"{file_name}#L{start}-L{end}"
    migration_source = obj.get("migration_source")
    if isinstance(migration_source, dict):
        file_name = migration_source.get("file", "?")
        line = migration_source.get("line", "?")
        return f"{file_name}#L{line}"
    if isinstance(migration_source, str) and migration_source:
        return migration_source
    return ""


def append_meta(out: list[str], meta: dict | None) -> None:
    if meta is None:
        return
    out.append("META")
    out.append("-" * 80)
    for key in sorted(meta.keys()):
        if key == "type":
            continue
        out.append(f"{key}: {meta[key]}")
    out.append("")


def append_counts(out: list[str], groups: dict[str, list[dict]]) -> None:
    out.append("OBJECT COUNTS")
    out.append("-" * 80)
    counts = Counter({name: len(items) for name, items in groups.items()})
    for name in sorted(counts):
        out.append(f"{name}: {counts[name]}")
    out.append("")


def append_bindings(out: list[str], groups: dict[str, list[dict]]) -> None:
    bindings = groups.get("obligation_binding", [])
    oracles = {obj.get("id", ""): obj for obj in groups.get("oracle", [])}
    out.append("AUTHORITY BINDINGS")
    out.append("-" * 80)
    for binding in sorted(bindings, key=lambda item: item.get("id", "")):
        binding_id = binding.get("id", "")
        match = binding.get("match", {})
        out.append(f"[{binding_id}]")
        out.append(f"  binding_type: {binding.get('binding_type', '')}")
        out.append(f"  match: {match}")
        out.append(f"  symbol_role: {binding.get('symbol_role', '')}")
        out.append(f"  conflict_policy: {binding.get('conflict_policy', '')}")
        out.append(f"  verification_mode: {binding.get('verification_mode', '')}")
        out.append(f"  verification_method: {binding.get('verification_method', '')}")
        out.append(f"  oracle_ref: {binding.get('oracle_ref', '')}")
        semantics = str(binding.get("authoritative_semantics", ""))
        out.append("  authoritative_semantics:")
        out.append(f"    {semantics}")
        peer_renderers = binding.get("peer_renderers", [])
        out.append(f"  peer_renderers ({len(peer_renderers)}):")
        for item in peer_renderers:
            out.append(f"    - {item}")
        out.append("")
    if oracles:
        out.append("ORACLES")
        out.append("-" * 80)
        for oracle_id in sorted(oracles):
            oracle = oracles[oracle_id]
            out.append(f"[{oracle_id}]")
            out.append(f"  oracle_kind: {oracle.get('oracle_kind', '')}")
            out.append(f"  description: {oracle.get('description', '')}")
            out.append("")


def append_rules(out: list[str], groups: dict[str, list[dict]]) -> None:
    rules = {str(rule.get("id", "")): rule for rule in groups.get("rule", [])}
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
        statement = str(rule.get("statement", ""))
        out.append("  statement:")
        out.append(f"    {statement}")
        out.append("")


def append_sections_and_notes(out: list[str], groups: dict[str, list[dict]]) -> None:
    sections = groups.get("section", [])
    notes = groups.get("note", [])
    source_meta = groups.get("source_meta", [])
    if sections:
        out.append("SECTIONS")
        out.append("-" * 80)
        for section in sorted(sections, key=lambda item: item.get("order", 0)):
            section_id = section.get("id", "")
            out.append(f"[{section_id}]")
            out.append(f"  heading_path: {section.get('heading_path', '')}")
            out.append(f"  level: {section.get('level', '')}")
            out.append(f"  text: {section.get('text', '')}")
            source = fmt_source(section)
            if source:
                out.append(f"  source: {source}")
            out.append("")
    if notes:
        out.append("NOTES")
        out.append("-" * 80)
        out.append(f"count: {len(notes)}")
        sample = sorted(notes, key=lambda item: item.get("order", 0))[:10]
        for note in sample:
            note_id = note.get("id", "")
            out.append(f"[{note_id}]")
            out.append(f"  kind: {note.get('kind', '')}")
            out.append(f"  heading_path: {note.get('heading_path', '')}")
            source = fmt_source(note)
            if source:
                out.append(f"  source: {source}")
            text = str(note.get("text", ""))
            preview = text if len(text) <= 120 else text[:117] + "..."
            out.append(f"  text: {preview}")
            out.append("")
    if source_meta:
        out.append("SOURCE META")
        out.append("-" * 80)
        for item in source_meta:
            out.append(f"[{item.get('id', '')}]")
            out.append(f"  source_file: {item.get('source_file', '')}")
            payload = item.get("payload", {})
            if isinstance(payload, dict):
                out.append(f"  payload_keys: {sorted(payload.keys())}")
            else:
                out.append(f"  payload_type: {type(payload).__name__}")
            out.append("")


def render(path_in: Path, path_out: Path) -> None:
    objs = load_jsonl(path_in)
    meta, groups = index_by_type(objs)
    out: list[str] = []
    out.append("MASTER_SPEC (human-readable)")
    out.append("=" * 80)
    append_meta(out, meta)
    append_counts(out, groups)
    append_bindings(out, groups)
    append_rules(out, groups)
    append_sections_and_notes(out, groups)
    path_out.write_text("\n".join(out), encoding="utf-8")


def main(argv: list[str]) -> int:
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
