"""PatchHub-safe TOML config editing for AMP.

Constraints:
- Preserve comments and ordering.
- Only modify RHS of canonical key assignments.
- Insert missing keys into the correct TOML section.
- Validate edits via the existing runner build_policy pathway.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Any

from am_patch.config import Policy, build_policy
from am_patch.config_file import _flatten_sections
from am_patch.errors import RunnerError


def validate_patchhub_update(values: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise RunnerError("CONFIG", "CONFIG", "update payload must be a dict")
    policy_schema = schema.get("policy")
    if not isinstance(policy_schema, dict):
        raise RunnerError("CONFIG", "CONFIG", "schema missing policy map")

    out: dict[str, Any] = {}
    for k, v in values.items():
        if k not in policy_schema:
            raise RunnerError("CONFIG", "CONFIG", f"unknown policy key: {k}")
        item = policy_schema[k]
        if not isinstance(item, dict):
            raise RunnerError("CONFIG", "CONFIG", f"schema entry invalid: {k}")
        if item.get("read_only") is True:
            raise RunnerError("CONFIG", "CONFIG", f"read-only policy key: {k}")

        type_name = str(item.get("type") or "")
        enum = item.get("enum")
        if enum is not None and not isinstance(enum, list):
            raise RunnerError("CONFIG", "CONFIG", f"schema enum invalid: {k}")

        if type_name == "bool":
            if not isinstance(v, bool):
                raise RunnerError("CONFIG", "CONFIG", f"expected bool for {k}")
        elif type_name == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                raise RunnerError("CONFIG", "CONFIG", f"expected int for {k}")
        elif type_name == "str":
            if not isinstance(v, str):
                raise RunnerError("CONFIG", "CONFIG", f"expected str for {k}")
        elif type_name == "optional[str]":
            if v is not None and not isinstance(v, str):
                raise RunnerError("CONFIG", "CONFIG", f"expected optional[str] for {k}")
        elif type_name == "list[str]":
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                raise RunnerError("CONFIG", "CONFIG", f"expected list[str] for {k}")
        elif type_name == "dict[str,list[str]]":
            if not isinstance(v, dict):
                raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
            for kk, vv in v.items():
                if not isinstance(kk, str) or not isinstance(vv, list):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
                if any(not isinstance(item, str) for item in vv):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
        elif type_name == "dict[str,str]":
            if not isinstance(v, dict):
                raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,str] for {k}")
            for kk, vv in v.items():
                if not isinstance(kk, str) or not isinstance(vv, str):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,str] for {k}")
        else:
            raise RunnerError("CONFIG", "CONFIG", f"unsupported schema type for {k}: {type_name}")

        if enum is not None:
            if v is None:
                raise RunnerError("CONFIG", "CONFIG", f"enum value may not be null: {k}")
            if not isinstance(v, str):
                raise RunnerError("CONFIG", "CONFIG", f"enum value must be str: {k}")
            if v not in enum:
                raise RunnerError(
                    "CONFIG",
                    "CONFIG",
                    f"invalid enum value for {k}: {v}",
                )

        out[k] = v
    return out


def validate_config_text_roundtrip(text: str) -> None:
    try:
        data = tomllib.loads(text)
    except Exception as e:  # pragma: no cover
        raise RunnerError("CONFIG", "CONFIG", f"invalid TOML: {e}") from e

    flat = _flatten_sections(data)
    defaults = Policy()
    try:
        build_policy(defaults, flat)
    except Exception as e:
        raise RunnerError("CONFIG", "CONFIG", f"policy build failed: {e}") from e


def apply_update_to_config_text(
    original_text: str,
    values: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    normalized = validate_patchhub_update(values, schema)
    policy_schema = schema.get("policy")
    if not isinstance(policy_schema, dict):
        raise RunnerError("CONFIG", "CONFIG", "schema missing policy map")

    lines = original_text.splitlines(keepends=True)
    edits = _compute_edits(lines, normalized, policy_schema)
    new_lines = _apply_edits(lines, edits)
    new_text = "".join(new_lines)
    validate_config_text_roundtrip(new_text)
    return new_text


@dataclass(frozen=True)
class _Edit:
    index: int
    new_line: str | None = None
    insert_lines: list[str] | None = None
    delete_to: int | None = None


def _render_value(v: Any, type_name: str) -> str:
    if type_name == "bool":
        return "true" if v else "false"
    if type_name == "int":
        return str(int(v))
    if type_name == "str":
        return _toml_quote(str(v))
    if type_name == "optional[str]":
        if v is None:
            return ""  # caller should remove assignment; not used in current policy
        return _toml_quote(str(v))
    if type_name == "list[str]":
        items = ", ".join(_toml_quote(str(x)) for x in v)
        return f"[{items}]"
    if type_name == "dict[str,list[str]]":
        parts: list[str] = []
        for key, values in v.items():
            rendered = ", ".join(_toml_quote(str(item)) for item in values)
            parts.append(f"{_toml_quote(str(key))} = [{rendered}]")
        return "{" + ", ".join(parts) + "}"
    if type_name == "dict[str,str]":
        parts = [f"{_toml_quote(str(key))} = {_toml_quote(str(value))}" for key, value in v.items()]
        return "{" + ", ".join(parts) + "}"
    raise RunnerError("CONFIG", "CONFIG", f"cannot render type: {type_name}")


def _render_table_lines(v: Any, type_name: str) -> list[str]:
    if type_name == "dict[str,str]":
        return [
            f"{_toml_quote(str(key))} = {_toml_quote(str(value))}\n" for key, value in v.items()
        ]
    if type_name == "dict[str,list[str]]":
        lines: list[str] = []
        for key, values in v.items():
            rendered = ", ".join(_toml_quote(str(item)) for item in values)
            lines.append(f"{_toml_quote(str(key))} = [{rendered}]\n")
        return lines
    raise RunnerError("CONFIG", "CONFIG", f"cannot render table type: {type_name}")


def _toml_quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
    return f'"{escaped}"'


def _compute_edits(
    lines: list[str],
    values: dict[str, Any],
    policy_schema: dict[str, Any],
) -> list[_Edit]:
    # Build section spans.
    spans = _scan_sections(lines)

    edits: list[_Edit] = []
    for key, value in values.items():
        item = policy_schema[key]
        section = str(item.get("section") or "")
        type_name = str(item.get("type") or "")

        span = spans.get(section)
        if span is None:
            raise RunnerError("CONFIG", "CONFIG", f"missing section in config: {section}")

        if type_name in {"dict[str,list[str]]", "dict[str,str]"} and section == key:
            edits.append(
                _Edit(
                    index=span.start + 1,
                    insert_lines=_render_table_lines(value, type_name),
                    delete_to=span.end,
                )
            )
            continue

        rhs = _render_value(value, type_name)
        found_idx = _find_assignment(lines, span, key)
        if found_idx is not None:
            edits.append(_Edit(index=found_idx, new_line=_replace_rhs(lines[found_idx], rhs)))
        else:
            insert_at = _find_insertion_index(lines, span)
            insert_line = f"{key} = {rhs}\n"
            edits.append(_Edit(index=insert_at, insert_lines=[insert_line]))

    edits.sort(key=lambda e: e.index, reverse=True)
    return edits


def _apply_edits(lines: list[str], edits: list[_Edit]) -> list[str]:
    out = list(lines)
    for e in edits:
        if e.new_line is not None:
            out[e.index] = e.new_line
        elif e.insert_lines is not None:
            delete_to = e.delete_to if e.delete_to is not None else e.index
            out[e.index : delete_to] = e.insert_lines
        else:  # pragma: no cover
            raise RunnerError("CONFIG", "CONFIG", "invalid edit")
    return out


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


def _scan_sections(lines: list[str]) -> dict[str, _Span]:
    # Root section spans from 0 to first section header.
    headers: list[tuple[str, int]] = [("", 0)]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and not stripped.startswith("[["):
            name = stripped[1:-1].strip()
            headers.append((name, i))

    spans: dict[str, _Span] = {}
    for idx, (name, start) in enumerate(headers):
        end = headers[idx + 1][1] if idx + 1 < len(headers) else len(lines)
        spans[name] = _Span(start=start, end=end)
    return spans


def _find_assignment(lines: list[str], span: _Span, key: str) -> int | None:
    start = span.start
    if start < span.end and lines[start].lstrip().startswith("["):
        start += 1
    for i in range(start, span.end):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            break
        if stripped.startswith(key) and stripped[len(key) :].lstrip().startswith("="):
            return i
    return None


def _replace_rhs(line: str, rhs: str) -> str:
    if "=" not in line:
        return line

    has_nl = line.endswith("\n")
    raw = line[:-1] if has_nl else line
    before, after = raw.split("=", 1)
    comment = ""
    if "#" in after:
        idx = after.index("#")
        comment = after[idx:]

    new = f"{before}= {rhs}"
    if comment:
        # Preserve the comment verbatim, but normalize spacing before it.
        new = new.rstrip() + " " + comment.lstrip()
    if has_nl:
        new += "\n"
    return new


def _find_insertion_index(lines: list[str], span: _Span) -> int:
    # Insert before the next section header or at EOF. Prefer after last assignment in span.
    start = span.start
    if start < span.end and lines[start].lstrip().startswith("["):
        start += 1
    last_assign = None
    for i in range(start, span.end):
        stripped = lines[i].lstrip()
        if stripped.startswith("["):
            break
        if "=" in stripped and not stripped.startswith("#"):
            last_assign = i
    if last_assign is not None:
        return last_assign + 1

    # Empty section: insert just after header line (or at start for root).
    if span.start == 0:
        for i in range(span.start, span.end):
            if lines[i].strip().startswith("["):
                return i
        return span.end
    return span.start + 1
