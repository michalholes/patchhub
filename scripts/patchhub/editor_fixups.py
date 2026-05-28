# ruff: noqa: E501,E701,E702,I001
from __future__ import annotations

import base64
import json
import zlib
from typing import TypedDict, cast

from .editor_codec import (
    FailurePayload,
    ObjectRecord,
    last_error_detail,
    parse_entry_tuple,
    parse_list_head,
)


class _CatalogEntry(TypedDict):
    title: str
    actions: list[tuple[str, str]]


def _sid(obj: ObjectRecord) -> str:
    return str(obj.get("id", "")).strip()


def _by_id(items: list[ObjectRecord], obj_id: str) -> ObjectRecord | None:
    return next((obj for obj in items if _sid(obj) == obj_id), None)


def _obj_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw_dict = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw_dict.items():
        if isinstance(key, str):
            out[key] = item
    return out


def _obj_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(cast(list[object], value))
    return []


def _action_pairs(value: object) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in _obj_list(value):
        pair = _obj_list(item)
        if len(pair) < 2:
            continue
        out.append((str(pair[0]), str(pair[1])))
    return out


def _catalog_payload() -> dict[str, object]:
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
    parsed: object = json.loads(raw.decode("utf-8"))
    payload = _obj_dict(parsed)
    if payload is None:
        raise ValueError("editor fixup catalog payload must decode to an object")
    return payload


def _load_catalog(payload: dict[str, object]) -> tuple[dict[str, str], dict[str, _CatalogEntry]]:
    labels_raw = _obj_dict(payload.get("labels")) or {}
    labels: dict[str, str] = {}
    for key, value in labels_raw.items():
        labels[key] = str(value)

    catalog_raw = _obj_dict(payload.get("catalog")) or {}
    catalog: dict[str, _CatalogEntry] = {}
    for failure_class, raw_entry in catalog_raw.items():
        entry = _obj_dict(raw_entry)
        if entry is None:
            continue
        catalog[failure_class] = {
            "title": str(entry.get("title", "")),
            "actions": _action_pairs(entry.get("actions")),
        }
    return labels, catalog


_PAYLOAD = _catalog_payload()
ACTION_LABELS, FAILURE_ACTION_CATALOG = _load_catalog(_PAYLOAD)
ACTION_LABELS.update(
    {
        "create_entry_gate_block": "Create entry gate block",
        "mark_workflow_step_root": "Mark workflow step as root",
    }
)
FAILURE_ACTION_CATALOG["workflow_missing_entry_gate_root"] = {
    "title": "Workflow entry gate/root marker missing",
    "actions": [
        ("create_entry_gate_block", ACTION_LABELS["create_entry_gate_block"]),
        ("mark_workflow_step_root", ACTION_LABELS["mark_workflow_step_root"]),
        ("delete_unsaved_block", ACTION_LABELS["delete_unsaved_block"]),
    ],
}


def _pair(detail: str, failure_class: str, primary_idx: int = 2) -> tuple[str, str, str]:
    parts = detail.split()
    return failure_class, parts[primary_idx], parts[-1]


def _entry_matches(objects: list[ObjectRecord], scope: str, mode: str) -> list[str]:
    return sorted(
        str(obj.get("id", ""))
        for obj in objects
        if obj.get("type") == "workflow_step"
        and str(obj.get("entry_scope", "")).strip() == scope
        and str(obj.get("entry_mode", "")).strip() == mode
    )


def build_failure(
    *,
    objects: list[ObjectRecord],
    loaded_objects: list[ObjectRecord],
    error_text: str,
    code: str,
    primary_id: str = "",
    secondary_id: str = "",
) -> FailurePayload:
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
        elif " missing entry gate/root marker" in detail:
            failure_class = "workflow_missing_entry_gate_root"
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


def empty_failure(code: str, text: str, **extra: str) -> FailurePayload:
    return build_failure(objects=[], loaded_objects=[], error_text=text, code=code, **extra)


def available_actions(
    failure_class: str,
    *,
    primary_id: str,
    secondary_id: str,
    objects: list[ObjectRecord],
    loaded_objects: list[ObjectRecord],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
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
