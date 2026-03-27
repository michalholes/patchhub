from __future__ import annotations

import hashlib
import json
from pathlib import Path

import __main__ as _m

R = _m.RuleResult
VE = _m.ValidationError
_rz, _dar, _iz = _m._read_zip, _m._decode_ascii_raw, _m._iter_zip_files
AOP, IR, SBT = _m.AUTHORITY_ONLY_PATHS, _m.INSTRUCTIONS_REQUIRED, _m.SUPPORTED_BINDING_TYPES

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


def _rr(i, s, d):
    return R(i, s, d)


def _decode_utf8_text(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _normalize_single_ascii_line(raw):
    text = _dar(raw)
    if text is None:
        return None, "non_ascii"
    if "\r" in text:
        return None, "must_use_lf"
    value = text[:-1] if text.endswith("\n") else text
    if "\n" in value:
        return None, "must_have_exactly_one_line"
    return (None, "must_be_non_empty") if value == "" else (value, None)


def _su(bindings, field):
    return sorted({i for b in bindings for i in b.get(field, [])})


def _bm(bindings, key, value):
    return {binding[key]: binding[value] for binding in bindings}


def _read_instructions_zip(path):
    out = [_rr("INSTRUCTIONS_EXTENSION", "PASS" if path.suffix == ".zip" else "FAIL", str(path))]
    if path.suffix != ".zip":
        return out, None, None, None
    names, items = _rz(path)
    roots = sorted(name for name in names if not name.endswith("/"))
    ok = roots == sorted(IR)
    out.append(_rr("INSTRUCTIONS_LAYOUT", "PASS" if ok else "FAIL", f"entries={','.join(roots)}"))
    handoff = items.get("HANDOFF.md")
    pack_raw = items.get("constraint_pack.json")
    hash_raw = items.get("hash_pack.txt")
    hok = handoff is not None and _decode_utf8_text(handoff) is not None
    out.append(
        _rr(
            "INSTRUCTIONS_HANDOFF",
            "PASS" if hok else "FAIL",
            "handoff_readable" if hok else "missing_or_non_utf8_handoff",
        )
    )
    pack = None
    if pack_raw is None:
        out.append(_rr("PACK_JSON", "FAIL", "missing_pack_json"))
    else:
        try:
            pack = json.loads(pack_raw.decode("utf-8"))
            out.append(_rr("PACK_JSON", "PASS", "pack_json_readable"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            out.append(_rr("PACK_JSON", "FAIL", "invalid_pack_json"))
    hv, he = (
        (None, "missing_hash_pack") if hash_raw is None else _normalize_single_ascii_line(hash_raw)
    )
    out.append(_rr("PACK_HASH_FILE", "FAIL" if he else "PASS", he or hv or ""))
    if pack_raw is None or hv is None:
        out.append(_rr("PACK_HASH_INTEGRITY", "FAIL", "hash_integrity_prerequisite_missing"))
    else:
        actual = hashlib.sha256(pack_raw).hexdigest()
        out.append(
            _rr(
                "PACK_HASH_INTEGRITY",
                "PASS" if actual == hv else "FAIL",
                f"expected={hv}:actual={actual}",
            )
        )
    return out, pack, pack_raw, hv


def _load_jsonl_bytes(raw):
    text = _decode_utf8_text(raw)
    if text is None:
        raise VE("spec_not_utf8")
    out = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VE(f"spec_jsonl_invalid_line:{idx}:{exc.msg}") from exc
        if not isinstance(obj, dict):
            raise VE(f"spec_jsonl_non_object:{idx}")
        out.append(obj)
    return out


def _collect_binding_meta_and_bindings(objects):
    meta = None
    bindings, oracles = [], {}
    for obj in objects:
        kind = obj.get("type")
        if kind == "binding_meta":
            if meta is not None:
                raise VE("binding_meta_duplicate")
            meta = obj
            continue
        if kind == "oracle":
            oid = str(obj.get("id", "")).strip()
            if not oid:
                raise VE("oracle_missing_id")
            if oid in oracles:
                raise VE(f"oracle_duplicate:{oid}")
            oracles[oid] = obj
            continue
        if kind != "obligation_binding":
            continue
        bid = str(obj.get("id", "<missing-id>"))
        missing = [field for field in BINDING_REQUIRED_FIELDS if field not in obj]
        if missing:
            raise VE(f"binding_missing_fields:{bid}:{','.join(missing)}")
        if obj["binding_type"] not in SBT:
            raise VE(f"binding_type_unsupported:{bid}:{obj['binding_type']}")
        for field in (
            "verification_mode",
            "verification_method",
            "semantic_group",
            "conflict_policy",
        ):
            if not str(obj.get(field, "")).strip():
                raise VE(f"binding_empty_field:{bid}:{field}")
        bindings.append(obj)
    if meta is None:
        raise VE("binding_meta_missing")
    return meta, bindings, oracles


def _binding_is_active(binding, mode, target_scope):
    match = binding.get("match", {})
    return binding.get("binding_type") == "constraint_pack" or (
        match.get("phase") == mode and match.get("target") == target_scope
    )


def _ensure_binding_consistency(active_bindings, oracles):
    if not active_bindings:
        raise VE("binding_active_missing")
    symbols: dict[tuple[str, str], list[str]] = {}
    semantics: dict[str, list[str]] = {}
    roles: dict[str, set[str]] = {}
    for binding in active_bindings:
        bid = str(binding.get("id", "<missing-id>"))
        ref = str(binding.get("oracle_ref", "")).strip()
        if not ref:
            raise VE(f"binding_missing_oracle_ref:{bid}")
        if ref not in oracles:
            raise VE(f"binding_unknown_oracle_ref:{bid}:{ref}")
        if binding.get("conflict_policy") != "fail_closed":
            raise VE(f"binding_conflict_policy:{bid}")
        key = json.dumps(binding.get("match", {}), sort_keys=True)
        role = str(binding.get("symbol_role", ""))
        sem = str(binding.get("authoritative_semantics", ""))
        symbols.setdefault((key, role), []).append(bid)
        semantics.setdefault(sem, []).append(bid)
        roles.setdefault(role, set()).add(sem)
    for ids in symbols.values():
        if len(ids) > 1:
            raise VE(f"binding_ambiguous_symbol:{','.join(sorted(ids))}")
    for ids in semantics.values():
        if len(ids) > 1:
            raise VE(f"binding_duplicate_semantics:{','.join(sorted(ids))}")
    for role, vals in roles.items():
        if len(vals) > 1:
            raise VE(f"binding_conflicting_obligations:{role}")


def _build_pack_from_spec_bytes(spec_raw, mode, target_scope):
    objs = _load_jsonl_bytes(spec_raw)
    if not objs or objs[0].get("type") != "meta":
        raise VE("spec_meta_missing")
    meta, bindings, oracles = _collect_binding_meta_and_bindings(objs)
    active = [b for b in bindings if _binding_is_active(b, mode, target_scope)]
    _ensure_binding_consistency(active, oracles)
    pack = {
        "target_symbol": None,
        "target_scope": target_scope,
        "mode": mode,
        "spec_fingerprint": hashlib.sha256(spec_raw).hexdigest(),
        "binding_meta_id": meta["id"],
        "active_bindings": active,
        "active_rule_ids": [binding["id"] for binding in active],
        "full_rule_text": _bm(active, "id", "authoritative_semantics"),
        "match_basis": {binding["id"]: binding.get("match", {}) for binding in active},
        "authoritative_sources": ["governance/specification.jsonl"],
        "shared_contracts": _su(active, "shared_contract_refs"),
        "downstream_consumers": _su(active, "downstream_consumers"),
        "exception_state_refs": _su(active, "exception_state_refs"),
        "required_wiring": _su(active, "required_wiring"),
        "forbidden_strategies": _su(active, "forbidden"),
        "required_validation": _su(active, "required_validation"),
        "verification_mode_per_rule": _bm(active, "id", "verification_mode"),
        "verification_method_per_rule": _bm(active, "id", "verification_method"),
        "oracle_refs": {binding["id"]: binding.get("oracle_ref") for binding in active},
        "aggregate_scope_metadata": {
            "binding_count": len(active),
            "mode": mode,
            "target_scope": target_scope,
        },
    }
    raw = (json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest(), active


def _authority_spec_bytes(args):
    spec = "governance/specification.jsonl"
    if not args.repair_overlay:
        snap = _iz(Path(args.workspace_snapshot))
        return snap.get(spec), None if spec in snap else "missing_spec_in_workspace_snapshot"
    overlay = _iz(Path(args.repair_overlay))
    if spec in overlay:
        return overlay[spec], None
    if args.workspace_snapshot and spec in set(args.supplemental_file):
        snap = _iz(Path(args.workspace_snapshot))
        if spec in snap:
            return snap[spec], None
        return None, "supplemental_spec_missing_in_snapshot"
    return None, "missing_spec_for_recompute"


def _pack_union_rule(rule_id, pack, key, active_bindings, field):
    exp, act = _su(active_bindings, field), sorted(pack.get(key, []))
    return _rr(rule_id, "PASS" if act == exp else "FAIL", f"expected={exp}:actual={act}")


def _scope_mapping_rule(decision_paths, pack):
    scope = str(pack.get("target_scope", ""))
    if not decision_paths:
        return _rr("PACK_SCOPE_MAPPING", "FAIL", "no_patch_paths")
    if scope == "authority_scope":
        bad = [p for p in decision_paths if not (p.startswith("docs/") or p.startswith("scripts/"))]
        return _rr(
            "PACK_SCOPE_MAPPING",
            "PASS" if not bad else "FAIL",
            "authority_paths_ok" if not bad else f"out_of_scope={bad}",
        )
    if scope == "implementation_scope":
        bad = [p for p in decision_paths if p in AOP]
        return _rr(
            "PACK_SCOPE_MAPPING",
            "PASS" if not bad else "FAIL",
            "implementation_paths_ok" if not bad else f"authority_paths={bad}",
        )
    return _rr("PACK_SCOPE_MAPPING", "FAIL", f"unsupported_target_scope:{scope}")


def _forbidden_bypass_rule(patch_member_names, pack, active_bindings):
    exp, act = _su(active_bindings, "forbidden"), sorted(pack.get("forbidden_strategies", []))
    if act != exp:
        return _rr("PACK_FORBIDDEN_BYPASS", "FAIL", f"expected={exp}:actual={act}")
    blocked = {"HANDOFF.md", "constraint_pack.json", "hash_pack.txt"}
    leaked = [name for name in patch_member_names if any(item in name for item in blocked)]
    if leaked:
        return _rr(
            "PACK_FORBIDDEN_BYPASS", "FAIL", f"patch_contains_instruction_artifacts:{leaked}"
        )
    return _rr("PACK_FORBIDDEN_BYPASS", "PASS", "forbidden_bypass_checks_ok")


def _recompute_pack_rule(args, pack, pack_raw):
    spec_raw, err = _authority_spec_bytes(args)
    if err is not None or spec_raw is None:
        return _rr(
            "PACK_RECOMPUTE", "UNVERIFIED_ENVIRONMENT", err or "missing_authority_spec"
        ), None
    mode, scope = str(pack.get("mode", "")), str(pack.get("target_scope", ""))
    if not mode or not scope:
        return _rr("PACK_RECOMPUTE", "FAIL", "missing_mode_or_target_scope"), None
    try:
        rebuilt, _rebuilt_hash, active = _build_pack_from_spec_bytes(spec_raw, mode, scope)
    except VE as exc:
        return _rr("PACK_RECOMPUTE", "FAIL", str(exc)), None
    if pack_raw is None:
        return _rr("PACK_RECOMPUTE", "FAIL", "missing_pack_bytes"), active
    status = "PASS" if rebuilt == pack_raw else "FAIL"
    return _rr(
        "PACK_RECOMPUTE", status, "recompute_match" if status == "PASS" else "recompute_mismatch"
    ), active


def _pack_rule_verdicts(pack, active_bindings, support_rules):
    out = []
    bindings = active_bindings if active_bindings is not None else pack.get("active_bindings", [])
    for binding in bindings:
        bid = str(binding.get("id", "<missing-id>"))
        mode = str(binding.get("verification_mode", "")).strip()
        if not mode:
            out.append(_rr(f"PACK_RULE:{bid}", "FAIL", "missing_verification_mode"))
            continue
        if mode != "machine":
            out.append(_rr(f"PACK_RULE:{bid}", "MANUAL_REVIEW_REQUIRED", f"mode={mode}"))
            continue
        fail = [rule for rule in support_rules.values() if rule.status != "PASS"]
        if fail:
            first = fail[0]
            status = (
                first.status
                if first.status in {"UNVERIFIED_ENVIRONMENT", "MANUAL_REVIEW_REQUIRED"}
                else "FAIL"
            )
            out.append(_rr(f"PACK_RULE:{bid}", status, first.rule_id))
            continue
        detail = (
            f"mode={binding.get('verification_mode')} method={binding.get('verification_method')}"
        )
        out.append(_rr(f"PACK_RULE:{bid}", "PASS", detail))
    return out


def _verdict_coverage_rule(pack, verdicts):
    exp = sorted(str(b.get("id", "<missing-id>")) for b in pack.get("active_bindings", []))
    act = sorted(v.rule_id.split(":", 1)[1] for v in verdicts if v.rule_id.startswith("PACK_RULE:"))
    return _rr(
        "PACK_VERDICT_COVERAGE", "PASS" if act == exp else "FAIL", f"expected={exp}:actual={act}"
    )


def _pack_rules(args, instructions_path, decision_paths, patch_member_names):
    out, pack, pack_raw, _hash_value = _read_instructions_zip(instructions_path)
    if pack is None:
        return out, None
    recompute, active = _recompute_pack_rule(args, pack, pack_raw)
    out.append(recompute)
    active = pack.get("active_bindings", []) if active is None else active
    out.append(
        _pack_union_rule("PACK_REQUIRED_WIRING", pack, "required_wiring", active, "required_wiring")
    )
    out.append(_forbidden_bypass_rule(patch_member_names, pack, active))
    out.append(
        _pack_union_rule(
            "PACK_DOWNSTREAM_COVERAGE", pack, "downstream_consumers", active, "downstream_consumers"
        )
    )
    out.append(
        _pack_union_rule(
            "PACK_REQUIRED_VALIDATION", pack, "required_validation", active, "required_validation"
        )
    )
    out.append(_scope_mapping_rule(decision_paths, pack))
    watch = {
        "PACK_HASH_INTEGRITY",
        "PACK_RECOMPUTE",
        "PACK_REQUIRED_WIRING",
        "PACK_FORBIDDEN_BYPASS",
        "PACK_DOWNSTREAM_COVERAGE",
        "PACK_REQUIRED_VALIDATION",
        "PACK_SCOPE_MAPPING",
    }
    support = {rule.rule_id: rule for rule in out if rule.rule_id in watch}
    verdicts = _pack_rule_verdicts(pack, active, support)
    out.extend(verdicts)
    out.append(_verdict_coverage_rule(pack, verdicts))
    return out, pack
