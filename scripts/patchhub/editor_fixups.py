# ruff: noqa: E501,E701,E702,I001
from __future__ import annotations

import base64
import json
import zlib
from copy import deepcopy
from typing import Any

from .editor_codec import (
    last_error_detail,
    parse_entry_tuple,
    parse_list_head,
    recompute_meta_counts,
    scaffold_object,
)


def _sid(obj: dict[str, Any]) -> str:
    return str(obj.get("id", "")).strip()


def _by_id(items: list[dict[str, Any]], obj_id: str) -> dict[str, Any] | None:
    return next((obj for obj in items if _sid(obj) == obj_id), None)


def _obj(items: list[dict[str, Any]], obj_id: str) -> dict[str, Any]:
    obj = _by_id(items, obj_id)
    if obj is None:
        raise EditorFixupError(f"Object not found: {obj_id}")
    return obj


def _items(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [obj for obj in items if obj.get("type") == kind]


def _str_list(values: Any) -> list[str]:
    return [str(x) for x in values]


def _swap(values: Any, old: str, new: str) -> list[str]:
    return [new if str(x) == old else str(x) for x in values]


def _drop(values: Any, old: str) -> list[str]:
    return [str(x) for x in values if str(x) != old]


def _remove(items: list[dict[str, Any]], obj_id: str) -> None:
    items[:] = [obj for obj in items if _sid(obj) != obj_id]


def _replace(items: list[dict[str, Any]], obj_id: str, new_obj: dict[str, Any]) -> None:
    for idx, obj in enumerate(items):
        if _sid(obj) == obj_id:
            items[idx] = new_obj
            return
    raise EditorFixupError(f"Object not found: {obj_id}")


def _unique(items: list[dict[str, Any]], base: str) -> str:
    used = {_sid(obj) for obj in items}
    if base not in used:
        return base
    idx = 1
    while f"{base}.{idx}" in used:
        idx += 1
    return f"{base}.{idx}"


def _append(items: list[dict[str, Any]], kind: str, preferred_id: str) -> dict[str, Any]:
    obj = deepcopy(scaffold_object(kind))
    obj["id"] = _unique(items, preferred_id or str(obj.get("id", kind.upper() + ".NEW")))
    items.append(obj)
    return obj


def _first(items: list[dict[str, Any]], kind: str, *, route_ref: str = "") -> dict[str, Any]:
    matches = [obj for obj in items if obj.get("type") == kind]
    if route_ref:
        matches = [obj for obj in matches if str(obj.get("route_ref", "")) == route_ref]
    if not matches:
        raise EditorFixupError(f"No matching {kind} object found")
    return sorted(matches, key=_sid)[0]


def _first_id(items: list[dict[str, Any]], kind: str) -> str:
    return _sid(_first(items, kind))


def _set_route_ref(obj: dict[str, Any], route_id: str) -> None:
    field = {
        "surface": "route_ref",
        "implementation": "implements_route",
        "workflow_step": "route_ref",
    }.get(str(obj.get("type", "")))
    if field is None:
        raise EditorFixupError("Object does not carry a route reference")
    obj[field] = route_id


def _pairs(blob: str) -> dict[str, str]:
    return dict(item.split("|", 1) for item in blob.replace("\n", ";").split(";") if item.strip())


def _catalog_payload() -> dict[str, Any]:
    blob = "".join(
        (
            "c-qxj&5q+X41N{CX9B(J*3JS&feu<^4?PSPhGHvOcN8m?<!lFwdH3qyk}b=gO)fo6Mx-cyBt=s6_",
            "o^Y1Fn+G^_v+a7ZP%acOE(PqFBha?R8vSJJKhf!etD?|%4j2N`foSLiK`a$R6+IG5RoS$C*ljdRE",
            "?lSQqO*5ym?g{p3JJ_Lv~ejw@Q%W9{YjZXdBo+nPudbJ^vS|WGA(%)h`x<7pSzNg7ytXU4J92YpZ",
            "uqkgw#}u};1PsA60KbqdEUbG01}X<DSbpsed(>*yS_*_!BJh-f0(-9b|);lgj~IKf|OpYGNKWC@F",
            "%ks+QU`JQ1&6gH;d{f&x2VXjZ4W20DD;qUQsttAi0f8|K>1gjDt1NmV7wRFwM$RH8pq*dM;q_Wvv",
            "-hB${BCRep?rg^^>l*E<5WrNDIgSezXIgi?f)YYE;fLy3vmnhf1#rT0kLsVimZ``@e-)lHt(Duzh",
            "1Sg|)Gw(Sw2Ac^a%)JfX}!Fklt)iWoD8n=3kJ>I_iKV-?^1WUGI~*Z5Uq5$EFro(I?OSVwheqOZ5",
            "R<sfn)<zKeug&RnLPG9vge@*r=PqM+Idj;b3UU(2~nW{~0@BR37fK#BT}m_=rZ`P(jWiJrwL@)Z5",
            "Ci7GFNWS^-ghwal|TWvy_(_h*=`*ldo~!L4F(R6(n-UWjbIE@Qjlm#fxxVz!=h>qxI7w;rqUJguW",
            "3T_5VKTFL{?Ofk#cS}`qSgl89*^Ly-1&z-8Ux@wX+PtYqPjj=0=&omJ}NG@ot(`aqesLxghOG+~A",
            "hQ<+D>C46SE9tYP&lNCJcjAOO1-Vk-cU{Iz1&R}9#1ciN_9*Ff<VQtuW`@8M-=+Iw_74LyRJ^O;x",
            "2~n4_P5mE#ax=2m?y3MK9{9DOD+M#76_tdsKfr)>G!6!2>zczzf4xLM=X-|+eRz2?n9rmvmW$OmE",
            "w9!`=Si8LSwWhDru4m5+g$$(quMduxOJFqd2L{x~tO76Zy=S^IX2DZ;vtik6xV57U^1)#o2ytl>b",
            ">-^GFNz>>C%aC&s_kQ@5s!Al|NA^^1$^!YC1;X)}EFsiUmbUVqZW(7hQVa>S4JaoN7iYl<TMVgTM",
            "p4xFjvEB8HSncF_5J-`Kjd94$<QL0+#FF0dIqQvBN_vB^F*!4(f>#nfD1$kSa7&!-rEy&1_AA&jP",
            "RK{y^oi8nU)M3{k>9sy_;jUtUAEHAuAjP2cGcuKi)1`X=B9n77C1-)l=Z+5}a~t<z^UM!HH~7rB2",
            "cHzAAG*RVn;7P?I#C{Z!y>6Uy}ds|Z?Mw5n_8ZFW%7tC=BY<wA7uCYSk3N!V06aX{A5FQdPXQ)Fm",
            "j~KR`bobD&Fx{h3#e%Z#R=rsw=ouSD>8Ya5=?6;mw2#ZzkB${No+XKNQLlE|eqK?4R&v{{)38ATC",
            "S+Av^BG*>NYVJQ48969HCA99}7Lkn5pvu7`rvl!RAP5^R+oyub9ocCyDGN%oLW6*!+NU^eT-$*dE",
            "Wof%&3%wT)mh_}a$ureaSD<cxfjv4UAm;nm!O}y{D38jfQ-kx|v@o9*6JPl#b$O3PVETB}FaH%js",
            "xg_FpNrXKQTfF~a3u|8xaQO=YWG2oyGjWFX$rRq2OhNk10Ppx_0OhANE<dHA^vw#deY1kXgB7nlS",
            "l{3O1H}m*l>",
        )
    )
    raw = zlib.decompress(base64.b85decode(blob.encode("ascii")))
    return json.loads(raw.decode("utf-8"))


_PAYLOAD = _catalog_payload()
ACTION_LABELS: dict[str, str] = _PAYLOAD["labels"]
FAILURE_ACTION_CATALOG: dict[str, dict[str, Any]] = _PAYLOAD["catalog"]
CLIENT_ONLY_ACTIONS = {"jump_to_block", "jump_to_conflict"}


class EditorFixupError(Exception):
    pass


FixContext = tuple[str, str, list[dict[str, Any]]]


def _pair(detail: str, failure_class: str, primary_idx: int = 2) -> tuple[str, str, str]:
    parts = detail.split()
    return failure_class, parts[primary_idx], parts[-1]


def _entry_matches(objects: list[dict[str, Any]], scope: str, mode: str) -> list[str]:
    return sorted(
        str(obj.get("id", ""))
        for obj in objects
        if obj.get("type") == "workflow_step"
        and str(obj.get("entry_scope", "")).strip() == scope
        and str(obj.get("entry_mode", "")).strip() == mode
    )


def build_failure(
    *,
    objects: list[dict[str, Any]],
    loaded_objects: list[dict[str, Any]],
    error_text: str,
    code: str,
    primary_id: str = "",
    secondary_id: str = "",
) -> dict[str, Any]:
    detail = last_error_detail(error_text)
    failure_class = "conversion_failure"
    if "duplicate id " in detail:
        failure_class = "duplicate_id"
        primary_id = secondary_id = detail.rsplit(" ", 1)[-1]
    elif "first object must be meta" in detail:
        failure_class = "missing_meta"
    elif "exactly one binding_meta object is required" in detail:
        ids = sorted(str(obj.get("id", "")) for obj in objects if obj.get("type") == "binding_meta")
        failure_class = "duplicate_binding_meta" if len(ids) > 1 else "missing_binding_meta"
        if len(ids) > 1:
            primary_id, secondary_id = ids[-1], ids[0]
    elif detail.startswith("FAIL meta count mismatch "):
        failure_class = "meta_count_mismatch"
        primary_id = next(
            (str(obj.get("id", "")) for obj in objects if obj.get("type") == "meta"),
            "",
        )
    elif detail.startswith("FAIL orphan rule "):
        failure_class, primary_id = "orphan_rule", detail.rsplit(" ", 1)[-1]
    elif detail.startswith("FAIL capability ") and " references missing rule " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "capability_missing_rule")
    elif detail.startswith("FAIL route ") and " references missing capability " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "route_missing_capability")
    elif detail.startswith("FAIL provider coverage in route "):
        failure_class, primary_id = "provider_coverage_missing", detail.split()[5]
    elif detail.startswith("FAIL surface ") and " references missing route " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "surface_missing_route")
    elif detail.startswith("surface ") and " references missing capability " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "surface_missing_capabilities", 1)
    elif detail.startswith("FAIL implementation ") and " references missing route " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "implementation_missing_route")
    elif detail.startswith("FAIL implementation ") and " missing capabilities " in detail:
        failure_class, primary_id = "implementation_missing_capabilities", detail.split()[2]
    elif detail.startswith("FAIL binding ") and " references missing oracle " in detail:
        failure_class, primary_id, secondary_id = _pair(detail, "binding_missing_oracle")
    elif detail.startswith("FAIL duplicate workflow entrypoint "):
        scope, mode = parse_entry_tuple(detail)
        failure_class = "workflow_duplicate_entrypoint"
        matches = _entry_matches(objects, scope, mode)
        if matches:
            primary_id, secondary_id = matches[-1], matches[0]
    elif detail.startswith("FAIL dead workflow step without "):
        failure_class, primary_id = "workflow_missing_transition", detail.rsplit(" ", 1)[-1]
    elif detail.startswith("FAIL workflow_step "):
        primary_id = detail.split()[2]
        if " missing invalidation handling" in detail:
            failure_class = "workflow_missing_invalidation"
        elif " missing rollback target" in detail:
            failure_class = "workflow_missing_rollback"
        elif " surface/route mismatch " in detail:
            failure_class = "workflow_surface_route_mismatch"
            secondary_id = detail.rsplit(" ", 1)[-1].split("->", 1)[0]
    elif detail.startswith("FAIL workflow missing surface coverage "):
        failure_class, primary_id = "workflow_missing_surface_coverage", parse_list_head(detail)
    elif detail.startswith("FAIL workflow missing route coverage "):
        failure_class, primary_id = "workflow_missing_route_coverage", parse_list_head(detail)
    return {
        "failure_class": failure_class,
        "failure_code": code,
        "error_text": str(error_text),
        "primary_id": primary_id,
        "secondary_id": secondary_id,
        "title": FAILURE_ACTION_CATALOG[failure_class]["title"],
        "actions": available_actions(
            failure_class,
            primary_id=primary_id,
            secondary_id=secondary_id,
            objects=objects,
            loaded_objects=loaded_objects,
        ),
    }


def empty_failure(code: str, text: str, **extra: str) -> dict[str, Any]:
    return build_failure(objects=[], loaded_objects=[], error_text=text, code=code, **extra)


def available_actions(
    failure_class: str,
    *,
    primary_id: str,
    secondary_id: str,
    objects: list[dict[str, Any]],
    loaded_objects: list[dict[str, Any]],
) -> list[dict[str, str]]:
    out = []
    for action_id, label in FAILURE_ACTION_CATALOG[failure_class]["actions"]:
        ok = action_id not in {"revert_block", "delete_unsaved_block"}
        if action_id == "revert_block":
            ok = bool(primary_id) and _by_id(loaded_objects, primary_id) is not None
        if action_id == "delete_unsaved_block":
            ok = bool(primary_id) and _by_id(loaded_objects, primary_id) is None
            ok = ok and _by_id(objects, primary_id) is not None
        if ok:
            out.append({"action_id": action_id, "label": label})
    return out


def apply_fix_action(
    *,
    action_id: str,
    objects: list[dict[str, Any]],
    primary_id: str,
    secondary_id: str,
    loaded_objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if action_id in CLIENT_ONLY_ACTIONS:
        raise EditorFixupError(f"Action {action_id} is client-side only")
    items = deepcopy(objects)
    ctx = (primary_id.strip(), secondary_id.strip(), deepcopy(loaded_objects))
    _apply(items, ctx, action_id)
    recompute_meta_counts(items)
    return items


def _providers(items: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        obj
        for pid in map(str, route.get("provider_chain", []))
        if (obj := _by_id(items, pid)) is not None
    ]


def _missing_cap_id(items: list[dict[str, Any]], primary_id: str) -> str:
    primary = _by_id(items, primary_id)
    if primary and primary.get("type") == "surface":
        field = "requires_capabilities"
    else:
        field = "covers_capabilities"
    for cap_id in (primary or {}).get(field, []):
        if _by_id(items, str(cap_id)) is None:
            return str(cap_id)
    return "CAP.FIX"


def _apply(items: list[dict[str, Any]], ctx: FixContext, action_id: str) -> None:
    primary_id, secondary_id, loaded_objects = ctx
    if action_id == "delete_unsaved_block":
        _remove(items, primary_id)
    elif action_id == "rename_current_id":
        _obj(items, primary_id)["id"] = _unique(items, primary_id + ".RENAMED")
    elif action_id == "revert_block":
        _replace(items, primary_id, deepcopy(_obj(loaded_objects, primary_id)))
    elif action_id in {"recreate_meta_block", "restore_last_loaded_meta"}:
        meta = next((obj for obj in loaded_objects if obj.get("type") == "meta"), None)
        items[:] = [obj for obj in items if obj.get("type") != "meta"]
        replacement = scaffold_object("meta") if action_id == "recreate_meta_block" else meta
        items.insert(0, deepcopy(replacement or scaffold_object("meta")))
    elif action_id == "merge_into_existing_binding_meta":
        keep_id = secondary_id or _first_id(items, "binding_meta")
        kept, seen = [], False
        for obj in items:
            if obj.get("type") != "binding_meta":
                kept.append(obj)
            elif not seen and str(obj.get("id", "")) == keep_id:
                kept.append(obj)
                seen = True
        items[:] = kept
    elif action_id == "create_binding_meta_block":
        _append(items, "binding_meta", "BINDING_META.NEW")
        items.insert(1 if items and items[0].get("type") == "meta" else 0, items.pop())
    elif action_id == "recompute_meta_counts":
        return
    elif action_id == "relink_rule_to_existing_capability":
        cap = _first(items, "capability")
        refs = [str(x) for x in cap.get("triggers_rules", [])]
        if primary_id not in refs:
            refs.append(primary_id)
        cap["triggers_rules"] = refs
    elif action_id == "create_companion_capability_block":
        cap = _append(items, "capability", "CAP.FIX")
        cap["triggers_rules"] = [primary_id]
        cap["name"] = primary_id
    elif action_id == "create_missing_rule_block":
        rule = _append(items, "rule", secondary_id or "RULE.FIX")
        rule["statement"] = f"Auto-created rule for {primary_id or rule['id']}"
    elif action_id == "relink_capability_rule_ref":
        cap = _obj(items, primary_id)
        rid = _first_id(items, "rule")
        cap["triggers_rules"] = _swap(cap.get("triggers_rules", []), secondary_id, rid)
    elif action_id == "remove_broken_rule_ref":
        cap = _obj(items, primary_id)
        cap["triggers_rules"] = _drop(cap.get("triggers_rules", []), secondary_id)
    elif action_id == "create_missing_capability_block":
        cap = _append(items, "capability", secondary_id or _missing_cap_id(items, primary_id))
        cap["name"] = cap["id"]
    elif action_id == "relink_route_capability_ref":
        route = _obj(items, primary_id)
        cid = _first_id(items, "capability")
        route["covers_capabilities"] = _swap(
            route.get("covers_capabilities", []), secondary_id, cid
        )
    elif action_id == "remove_broken_route_capability_ref":
        route = _obj(items, primary_id)
        route["covers_capabilities"] = _drop(route.get("covers_capabilities", []), secondary_id)
    elif action_id == "add_provider_capability_coverage":
        route = _obj(items, primary_id)
        chain = _str_list(route.get("provider_chain", []))
        if not chain:
            raise EditorFixupError("Route has no provider_chain")
        provider = _obj(items, chain[-1])
        provided_caps = _str_list(provider.get("provides_capabilities", []))
        for cap_id in route.get("covers_capabilities", []):
            if str(cap_id) not in provided_caps:
                provided_caps.append(str(cap_id))
        provider["provides_capabilities"] = provided_caps
    elif action_id == "create_provider_block":
        route = _obj(items, primary_id)
        provider = _append(items, "provider", "PROVIDER.FIX")
        provider["provides_capabilities"] = [str(x) for x in route.get("covers_capabilities", [])]
        route["provider_chain"] = [*map(str, route.get("provider_chain", [])), provider["id"]]
    elif action_id == "reduce_route_capabilities":
        route = _obj(items, primary_id)
        provided_ids = {
            str(x) for obj in _providers(items, route) for x in obj.get("provides_capabilities", [])
        }
        route["covers_capabilities"] = [
            cap for cap in map(str, route.get("covers_capabilities", [])) if cap in provided_ids
        ]
    elif action_id in {"select_existing_route_ref", "create_route_block"}:
        if action_id == "create_route_block":
            route = _append(items, "route", secondary_id or primary_id or "ROUTE.FIX")
            _set_route_ref(_obj(items, primary_id), route["id"])
        else:
            _set_route_ref(_obj(items, primary_id), _first_id(items, "route"))
    elif action_id == "select_existing_capabilities":
        surface = _obj(items, primary_id)
        route_obj = _by_id(items, str(surface.get("route_ref", "")))
        cap_ids = [
            str(x)
            for x in (route_obj or {}).get("covers_capabilities", [])
            if _by_id(items, str(x))
        ]
        if cap_ids:
            surface["requires_capabilities"] = cap_ids
        else:
            surface["requires_capabilities"] = sorted(
                str(obj.get("id", "")) for obj in _items(items, "capability")
            )
    elif action_id == "add_missing_declared_capabilities":
        impl = _obj(items, primary_id)
        route = _obj(items, str(impl.get("implements_route", "")))
        declared = _str_list(impl.get("declared_capabilities", []))
        for cap_id in route.get("covers_capabilities", []):
            if str(cap_id) not in declared:
                declared.append(str(cap_id))
        impl["declared_capabilities"] = declared
    elif action_id in {"select_existing_oracle_ref", "create_oracle_block"}:
        if action_id == "create_oracle_block":
            oracle = _append(items, "oracle", secondary_id or "ORACLE.FIX")
            _obj(items, primary_id)["oracle_ref"] = oracle["id"]
        else:
            _obj(items, primary_id)["oracle_ref"] = _first_id(items, "oracle")
    elif action_id == "clear_current_entry_fields":
        step = _obj(items, primary_id)
        step["entry_scope"] = ""
        step["entry_mode"] = ""
    elif action_id == "create_transition_block":
        sid = str(_obj(items, primary_id).get("id", ""))
        steps = sorted(_items(items, "workflow_step"), key=lambda obj: str(obj.get("id", "")))
        other = next((obj for obj in steps if str(obj.get("id", "")) != sid), None)
        if other is None:
            raise EditorFixupError("At least two workflow steps are required")
        inbound = any(
            str(obj.get("to_step", "")) == sid for obj in _items(items, "workflow_transition")
        )
        trans = _append(items, "workflow_transition", "WORKFLOW_TRANSITION.FIX")
        other_id = str(other.get("id", ""))
        trans["from_step"], trans["to_step"] = (sid, other_id) if inbound else (other_id, sid)
    elif action_id == "create_invalidation_block":
        steps = sorted(_items(items, "workflow_step"), key=lambda obj: str(obj.get("id", "")))
        target = next(
            (
                obj
                for obj in steps
                if str(obj.get("id", "")) != primary_id and obj.get("root_marker")
            ),
            None,
        )
        target = target or next(
            (obj for obj in steps if str(obj.get("id", "")) != primary_id), None
        )
        if target is None:
            raise EditorFixupError("No invalidation target available")
        inv = _append(items, "workflow_invalidation", "WORKFLOW_INVALIDATION.FIX")
        inv["failing_step"] = primary_id
        inv["invalidates_step"] = str(target.get("id", ""))
    elif action_id == "create_rollback_block":
        target = next(
            (obj for obj in _items(items, "workflow_step") if obj.get("root_marker")),
            None,
        )
        if target is None:
            raise EditorFixupError("No rollback target available")
        rb = _append(items, "workflow_rollback", "WORKFLOW_ROLLBACK.FIX")
        rb["from_step"] = primary_id
        rb["rollback_to_step"] = str(target.get("id", ""))
    elif action_id == "clear_rollback_required_flag":
        _obj(items, primary_id)["rollback_required"] = False
    elif action_id in {"create_workflow_step_for_surface", "create_workflow_step_for_route"}:
        source = _obj(items, primary_id)
        step = _append(items, "workflow_step", "WORKFLOW_STEP.FIX")
        if action_id.endswith("surface"):
            surface_id, route_id = primary_id, str(source.get("route_ref", ""))
            req_caps = [str(x) for x in source.get("requires_capabilities", [])]
        else:
            surface_id = str(_first(items, "surface", route_ref=primary_id).get("id", ""))
            route_id = primary_id
            req_caps = _str_list(source.get("covers_capabilities", []))
        step.update(
            {
                "display_name": primary_id,
                "branch": "editor_fix",
                "route_ref": route_id,
                "surface_ref": surface_id,
                "required_capabilities": req_caps,
            }
        )
    elif action_id == "relink_workflow_step_surface":
        step = _obj(items, primary_id)
        step["surface_ref"] = str(
            _first(items, "surface", route_ref=str(step.get("route_ref", ""))).get("id", "")
        )
    elif action_id == "relink_workflow_step_route":
        step = _obj(items, primary_id)
        step["route_ref"] = str(_obj(items, str(step.get("surface_ref", ""))).get("route_ref", ""))
    else:
        raise EditorFixupError(f"Unknown action_id: {action_id}")
