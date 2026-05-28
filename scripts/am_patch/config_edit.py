"""PatchHub-safe TOML config editing for AMP.

Constraints:
- Preserve comments and ordering.
- Only modify RHS of canonical key assignments.
- Insert missing keys into the correct TOML section.
- Validate edits via the existing runner build_policy pathway.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from am_patch import config_file as _config_file
from am_patch.config import Policy, build_policy
from am_patch.errors import RunnerError

_TomlLoads = Callable[[str], object]
_TOML_LOADS = cast(_TomlLoads, tomllib.loads)


def _flatten_sections(cfg: object) -> dict[str, object]:
    helper_name = "_flatten_sections"
    flatten = cast(
        Callable[[object], dict[str, object]],
        getattr(_config_file, helper_name),
    )
    return flatten(cfg)


def validate_patchhub_update(
    values: object,
    schema: object,
) -> dict[str, object]:
    if not isinstance(values, dict):
        raise RunnerError("CONFIG", "CONFIG", "update payload must be a dict")
    if not isinstance(schema, dict):
        raise RunnerError("CONFIG", "CONFIG", "schema must be a dict")
    values_map = cast(dict[object, object], values)
    schema_map = cast(dict[object, object], schema)
    policy_schema_obj = schema_map.get("policy")
    if not isinstance(policy_schema_obj, dict):
        raise RunnerError("CONFIG", "CONFIG", "schema missing policy map")
    policy_schema = cast(dict[object, object], policy_schema_obj)

    out: dict[str, object] = {}
    for raw_key, value_obj in values_map.items():
        if not isinstance(raw_key, str):
            raise RunnerError("CONFIG", "CONFIG", "policy key must be a string")
        k = raw_key
        if k not in policy_schema:
            raise RunnerError("CONFIG", "CONFIG", f"unknown policy key: {k}")
        item_obj = policy_schema[k]
        if not isinstance(item_obj, dict):
            raise RunnerError("CONFIG", "CONFIG", f"schema entry invalid: {k}")
        item = cast(dict[object, object], item_obj)
        if item.get("read_only") is True:
            raise RunnerError("CONFIG", "CONFIG", f"read-only policy key: {k}")

        type_name = str(item.get("type") or "")
        enum_obj = item.get("enum")
        if enum_obj is not None and not isinstance(enum_obj, list):
            raise RunnerError("CONFIG", "CONFIG", f"schema enum invalid: {k}")
        enum_values: list[str] | None = None
        if isinstance(enum_obj, list):
            enum_list = cast(list[object], enum_obj)
            if any(not isinstance(entry, str) for entry in enum_list):
                raise RunnerError("CONFIG", "CONFIG", f"schema enum invalid: {k}")
            enum_values = [entry for entry in enum_list if isinstance(entry, str)]

        if type_name == "bool":
            if not isinstance(value_obj, bool):
                raise RunnerError("CONFIG", "CONFIG", f"expected bool for {k}")
        elif type_name == "int":
            if not isinstance(value_obj, int) or isinstance(value_obj, bool):
                raise RunnerError("CONFIG", "CONFIG", f"expected int for {k}")
        elif type_name == "str":
            if not isinstance(value_obj, str):
                raise RunnerError("CONFIG", "CONFIG", f"expected str for {k}")
        elif type_name == "optional[str]":
            if value_obj is not None and not isinstance(value_obj, str):
                raise RunnerError("CONFIG", "CONFIG", f"expected optional[str] for {k}")
        elif type_name == "list[str]":
            if not isinstance(value_obj, list):
                raise RunnerError("CONFIG", "CONFIG", f"expected list[str] for {k}")
            list_value = cast(list[object], value_obj)
            if any(not isinstance(item, str) for item in list_value):
                raise RunnerError("CONFIG", "CONFIG", f"expected list[str] for {k}")
        elif type_name == "dict[str,list[str]]":
            if not isinstance(value_obj, dict):
                raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
            for kk, vv in cast(dict[object, object], value_obj).items():
                if not isinstance(kk, str) or not isinstance(vv, list):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
                if any(not isinstance(item, str) for item in cast(list[object], vv)):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,list[str]] for {k}")
        elif type_name == "dict[str,str]":
            if not isinstance(value_obj, dict):
                raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,str] for {k}")
            for kk, vv in cast(dict[object, object], value_obj).items():
                if not isinstance(kk, str) or not isinstance(vv, str):
                    raise RunnerError("CONFIG", "CONFIG", f"expected dict[str,str] for {k}")
        else:
            raise RunnerError("CONFIG", "CONFIG", f"unsupported schema type for {k}: {type_name}")

        enum_candidate = cast(object, value_obj)
        if enum_values is not None:
            if enum_candidate is None:
                raise RunnerError("CONFIG", "CONFIG", f"enum value may not be null: {k}")
            if not isinstance(enum_candidate, str):
                raise RunnerError("CONFIG", "CONFIG", f"enum value must be str: {k}")
            if enum_candidate not in enum_values:
                raise RunnerError(
                    "CONFIG",
                    "CONFIG",
                    f"invalid enum value for {k}: {enum_candidate}",
                )

        out[k] = cast(object, value_obj)
    return out


def validate_config_text_roundtrip(text: str) -> None:
    try:
        data_obj = _TOML_LOADS(text)
    except Exception as e:  # pragma: no cover
        raise RunnerError("CONFIG", "CONFIG", f"invalid TOML: {e}") from e

    if not isinstance(data_obj, dict):
        raise RunnerError("CONFIG", "CONFIG", "invalid TOML root: expected table")
    data_map = cast(dict[str, object], data_obj)
    flat = _flatten_sections(data_map)
    defaults = Policy()
    try:
        build_policy(defaults, flat)
    except Exception as e:
        raise RunnerError("CONFIG", "CONFIG", f"policy build failed: {e}") from e


def apply_update_to_config_text(
    original_text: str,
    values: dict[str, object],
    schema: dict[str, object],
) -> str:
    normalized = validate_patchhub_update(values, schema)
    policy_schema_obj = schema.get("policy")
    if not isinstance(policy_schema_obj, dict):
        raise RunnerError("CONFIG", "CONFIG", "schema missing policy map")
    policy_schema: dict[str, object] = {}
    for key, value in cast(dict[object, object], policy_schema_obj).items():
        if isinstance(key, str):
            policy_schema[key] = value

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


def _render_value(v: object, type_name: str) -> str:
    if type_name == "bool":
        if not isinstance(v, bool):
            raise RunnerError("CONFIG", "CONFIG", "expected bool")
        return "true" if v else "false"
    if type_name == "int":
        if not isinstance(v, int) or isinstance(v, bool):
            raise RunnerError("CONFIG", "CONFIG", "expected int")
        return str(v)
    if type_name == "str":
        return _toml_quote(str(v))
    if type_name == "optional[str]":
        if v is None:
            return ""  # caller should remove assignment; not used in current policy
        return _toml_quote(str(v))
    if type_name == "list[str]":
        if not isinstance(v, list):
            raise RunnerError("CONFIG", "CONFIG", "expected list[str]")
        list_value = cast(list[object], v)
        items = ", ".join(_toml_quote(str(item)) for item in list_value)
        return f"[{items}]"
    if type_name == "dict[str,list[str]]":
        if not isinstance(v, dict):
            raise RunnerError("CONFIG", "CONFIG", "expected dict[str,list[str]]")
        parts: list[str] = []
        for key, values in cast(dict[object, object], v).items():
            if not isinstance(values, list):
                raise RunnerError("CONFIG", "CONFIG", "expected dict[str,list[str]]")
            rendered = ", ".join(_toml_quote(str(item)) for item in cast(list[object], values))
            parts.append(f"{_toml_quote(str(key))} = [{rendered}]")
        return "{" + ", ".join(parts) + "}"
    if type_name == "dict[str,str]":
        if not isinstance(v, dict):
            raise RunnerError("CONFIG", "CONFIG", "expected dict[str,str]")
        parts = [
            f"{_toml_quote(str(key))} = {_toml_quote(str(value))}"
            for key, value in cast(dict[object, object], v).items()
        ]
        return "{" + ", ".join(parts) + "}"
    raise RunnerError("CONFIG", "CONFIG", f"cannot render type: {type_name}")


def _render_table_lines(v: object, type_name: str) -> list[str]:
    if type_name == "dict[str,str]":
        if not isinstance(v, dict):
            raise RunnerError("CONFIG", "CONFIG", "expected dict[str,str]")
        return [
            f"{_toml_quote(str(key))} = {_toml_quote(str(value))}\n"
            for key, value in cast(dict[object, object], v).items()
        ]
    if type_name == "dict[str,list[str]]":
        if not isinstance(v, dict):
            raise RunnerError("CONFIG", "CONFIG", "expected dict[str,list[str]]")
        lines: list[str] = []
        for key, values in cast(dict[object, object], v).items():
            if not isinstance(values, list):
                raise RunnerError("CONFIG", "CONFIG", "expected dict[str,list[str]]")
            rendered = ", ".join(_toml_quote(str(item)) for item in cast(list[object], values))
            lines.append(f"{_toml_quote(str(key))} = [{rendered}]\n")
        return lines
    raise RunnerError("CONFIG", "CONFIG", f"cannot render table type: {type_name}")


def _toml_quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
    return f'"{escaped}"'


def _edit_sort_index(edit: _Edit) -> int:
    return edit.index


def _compute_edits(
    lines: list[str],
    values: dict[str, object],
    policy_schema: dict[str, object],
) -> list[_Edit]:
    # Build section spans.
    spans = _scan_sections(lines)

    edits: list[_Edit] = []
    for key, value in values.items():
        item_obj = policy_schema[key]
        if not isinstance(item_obj, dict):
            raise RunnerError("CONFIG", "CONFIG", f"schema entry invalid: {key}")
        item = cast(dict[object, object], item_obj)
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
            if type_name == "list[str]":
                delete_to = _find_multiline_array_delete_to(lines, span, found_idx)
                if delete_to is not None:
                    edits.append(
                        _Edit(
                            index=found_idx,
                            insert_lines=[f"{key} = {rhs}\n"],
                            delete_to=delete_to,
                        )
                    )
                    continue
            edits.append(_Edit(index=found_idx, new_line=_replace_rhs(lines[found_idx], rhs)))
        else:
            insert_at = _find_insertion_index(lines, span)
            insert_line = f"{key} = {rhs}\n"
            edits.append(_Edit(index=insert_at, insert_lines=[insert_line]))

    edits.sort(key=_edit_sort_index, reverse=True)
    return edits


def _find_multiline_array_delete_to(lines: list[str], span: _Span, start: int) -> int | None:
    line = lines[start]
    if "=" not in line:
        return None
    rhs = line.split("=", 1)[1]
    depth = rhs.count("[") - rhs.count("]")
    if depth <= 0:
        return None
    for idx in range(start + 1, span.end):
        depth += lines[idx].count("[") - lines[idx].count("]")
        if depth <= 0:
            return idx + 1
    raise RunnerError("CONFIG", "CONFIG", "unterminated multiline array assignment")


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
    # Insert before the next section header or at EOF.
    # This avoids splitting multiline arrays such as gates_order = [ ... ].
    if span.start == 0:
        for i in range(span.start, span.end):
            if lines[i].strip().startswith("["):
                return i
        return span.end
    return span.end
