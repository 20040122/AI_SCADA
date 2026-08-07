from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

import jsonschema

from app.services.binding_config_service import BindingConfigError, load_binding_registry
from app.services.semantic import get_similarity

Validator = Callable[[dict[str, Any]], list[str]]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CANVAS_SCHEMA_PATH = _REPO_ROOT / "data" / "schema" / "canvas_schema.json"
_BINDING_SCHEMA_PATH = _REPO_ROOT / "data" / "schema" / "binding_schema.json"


class BindingHandler:
    handler_id: str = ""

    def matches(self, display_name: str) -> bool:
        raise NotImplementedError

    def canonicalize(self, display_name: str) -> str:
        raise NotImplementedError

    def validate_target(self, node: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def read_existing(self, node: dict[str, Any]) -> Any:
        raise NotImplementedError

    def render(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def validate_output(self, a_data: dict[str, Any], validator: Validator) -> list[str]:
        raise NotImplementedError


class PanelListHandler(BindingHandler):
    handler_id = "panel_list"
    _NAME_RE = re.compile(r"状态面板(?:[1-9]\d*)?")

    def matches(self, display_name: str) -> bool:
        return self._NAME_RE.fullmatch(display_name) is not None

    def canonicalize(self, display_name: str) -> str:
        return "状态面板"

    def validate_target(self, node: dict[str, Any]) -> list[str]:
        if node.get("c") != "ht.Node":
            return ["目标控件节点类型必须是 ht.Node"]
        return []

    def read_existing(self, node: dict[str, Any]) -> Any:
        return (node.get("a") or {}).get("panel.list")

    def render(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_panel_list_item(r) for r in records]

    def validate_output(self, a_data: dict[str, Any], validator: Validator) -> list[str]:
        return validator({"panel.list": a_data.get("panel.list", [])})


def _panel_list_item(rec: dict[str, Any]) -> dict[str, Any]:
    unit = rec["unit"] or ""
    if unit:
        bind_label = (
            f"{rec['projectName']} . {rec['deviceName']} . "
            f"{rec['propertyName']} ({unit})"
        )
    else:
        bind_label = (
            f"{rec['projectName']} . {rec['deviceName']} . "
            f"{rec['propertyName']}"
        )
    return {
        "label": rec["propertyName"],
        "bind": {
            "type": "designer",
            "path": f"{rec['projectId']}#{rec['deviceId']}#{rec['propertyId']}",
            "key": f"{rec['deviceId']}#{rec['propertyId']}",
            "label": bind_label,
            "proj": {"id": rec["projectId"], "name": rec["projectName"]},
            "dev": {"id": rec["deviceId"], "name": rec["deviceName"]},
            "param": {
                "id": rec["propertyId"],
                "name": rec["propertyName"],
                "unit": unit,
                "writable": rec["writable"],
                "dataType": rec["dataType"],
                "dataTypeDesc": rec["dataTypeDesc"],
            },
        },
    }


class BindingAgent:
    def __init__(
        self,
        registry_path: Optional[Path] = None,
        records: Optional[list[dict[str, Any]]] = None,
        similarity: Optional[Any] = None,
        cache_vectors: bool = True,
    ) -> None:
        if records is None:
            if registry_path is None:
                raise ValueError("registry_path 或 records 必须提供其一")
            records = load_binding_registry(Path(registry_path))
        self._records = records
        self._similarity = similarity if similarity is not None else get_similarity()
        self._handlers = self._register_handlers()
        self._record_by_id: dict[str, dict[str, Any]] = {}
        self._catalog: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._build_catalog()
        self._validate_handlers()
        self._catalog_vectors: dict[tuple[str, str], Any] = {}
        if cache_vectors:
            for key, recs in self._catalog.items():
                names = [r["propertyName"] for r in recs]
                if names:
                    self._catalog_vectors[key] = self._similarity.encode(names)
        self._canvas_schema = json.loads(_CANVAS_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._binding_schema = json.loads(_BINDING_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _register_handlers(self) -> dict[str, BindingHandler]:
        return {PanelListHandler.handler_id: PanelListHandler()}

    def _build_catalog(self) -> None:
        for rec in self._records:
            self._record_by_id[rec["id"]] = rec
            handler = self._handlers.get(rec["handler"])
            if handler is None:
                continue
            canonical = self._canonical(handler, rec["displayName"])
            key = (rec["handler"], canonical)
            self._catalog.setdefault(key, []).append(rec)

    def _canonical(self, handler: BindingHandler, display_name: str) -> str:
        if handler.matches(display_name):
            return handler.canonicalize(display_name)
        return display_name

    def _validate_handlers(self) -> None:
        errors: list[str] = []
        for rec in self._records:
            if rec["handler"] not in self._handlers:
                errors.append(f"handler 未注册: {rec['handler']} (id={rec['id']})")
        if errors:
            raise BindingConfigError(errors)

    @property
    def registry(self) -> list[dict[str, Any]]:
        return self._records

    def _find_handler(self, display_name: str) -> Optional[BindingHandler]:
        for handler in self._handlers.values():
            if handler.matches(display_name):
                return handler
        return None

    def _locate_targets(self, json_data: dict[str, Any], display_name: str) -> list[tuple[int, dict[str, Any]]]:
        found: list[tuple[int, dict[str, Any]]] = []
        for i, node in enumerate(json_data.get("d") or []):
            if node.get("c") != "ht.Node":
                continue
            if (node.get("p") or {}).get("displayName") == display_name:
                found.append((i, node))
        return found

    def match(self, json_data: dict[str, Any], requests: list[dict[str, Any]]) -> dict[str, Any]:
        errors: list[str] = []
        blocked = False
        targets: dict[int, dict[str, Any]] = {}
        items: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []

        for req in requests:
            row = int(req["row_number"])
            display_name = (req["displayName"] or "").strip()
            property_name = (req["propertyName"] or "").strip()
            item: dict[str, Any] = {
                "row_number": row,
                "target_node_i": None,
                "requested_displayName": display_name,
                "requested_propertyName": property_name,
                "candidates": [],
                "suggested_binding_id": None,
                "lead": 0.0,
                "confidence": "none",
            }
            handler = self._find_handler(display_name)
            if handler is None:
                errors.append(f"第 {row} 行: 不支持的控件 {display_name}")
                blocked = True
                items.append(item)
                continue
            found = self._locate_targets(json_data, display_name)
            if not found:
                errors.append(f"第 {row} 行: 未找到目标控件 {display_name}")
                blocked = True
                items.append(item)
                continue
            if len(found) > 1:
                errors.append(f"第 {row} 行: 目标控件 {display_name} 存在多个同名节点")
                blocked = True
                items.append(item)
                continue
            node_i, node = found[0]
            item["target_node_i"] = node_i
            type_errors = handler.validate_target(node)
            if type_errors:
                errors.extend(type_errors)
                blocked = True
                items.append(item)
                continue
            if node_i not in targets:
                targets[node_i] = {
                    "node_i": node_i,
                    "node_id": node.get("i"),
                    "displayName": display_name,
                    "handler": handler.handler_id,
                    "existing": handler.read_existing(node),
                }
            pending.append({
                "row": row,
                "query": property_name,
                "key": (handler.handler_id, handler.canonicalize(display_name)),
                "item": item,
            })

        row_candidates = self._compute_row_candidates(pending)
        for entry in pending:
            row = entry["row"]
            item = entry["item"]
            candidates, suggested, lead, confidence = row_candidates[row]
            if not candidates:
                errors.append(f"第 {row} 行: 未找到匹配属性 {entry['query']}")
                blocked = True
            item["candidates"] = candidates
            item["suggested_binding_id"] = suggested
            item["lead"] = lead
            item["confidence"] = confidence
            items.append(item)

        return {"targets": list(targets.values()), "items": items, "blocked": blocked, "errors": errors}

    def _compute_row_candidates(self, pending: list[dict[str, Any]]) -> dict[int, tuple]:
        result: dict[int, tuple] = {}
        if not pending:
            return result
        exact_groups: dict[tuple[tuple[str, str], str], list[dict[str, Any]]] = {}
        semantic_groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        for entry in pending:
            key = entry["key"]
            query = entry["query"]
            catalog = self._catalog.get(key, [])
            exact = [r for r in catalog if (r["propertyName"] or "").strip() == query]
            if exact:
                exact_groups[(key, query)] = exact
            else:
                semantic_groups.setdefault(key, []).append((query, entry))

        query_vecs: dict[tuple[tuple[str, str], str], Any] = {}
        for key, pairs in semantic_groups.items():
            queries = [q for q, _ in pairs]
            vecs = self._similarity.encode(queries)
            query_vecs.update({(key, q): v for q, v in zip(queries, vecs)})

        scored_groups: dict[tuple[tuple[str, str], str], list[tuple[dict[str, Any], float]]] = {}
        for key, pairs in semantic_groups.items():
            records = self._catalog.get(key, [])
            if not records:
                for query, _ in pairs:
                    scored_groups[(key, query)] = []
                continue
            catalog_vecs = self._catalog_vectors.get(key)
            for query, _ in pairs:
                qv = query_vecs[(key, query)]
                if catalog_vecs is not None:
                    scores = list(catalog_vecs @ qv)
                    scored_groups[(key, query)] = list(zip(records, scores))
                else:
                    scored = []
                    for rec in records:
                        cv = self._similarity.encode([rec["propertyName"]])[0]
                        scored.append((rec, float(cv @ qv)))
                    scored_groups[(key, query)] = scored

        for entry in pending:
            key = entry["key"]
            query = entry["query"]
            row = entry["row"]
            if (key, query) in exact_groups:
                result[row] = self._finalize_exact(exact_groups[(key, query)])
            elif (key, query) in scored_groups:
                result[row] = self._finalize_semantic(scored_groups[(key, query)])
            else:
                result[row] = ([], None, 0.0, "none")
        return result

    def _finalize_exact(self, records: list[dict[str, Any]]) -> tuple:
        candidates = [self._candidate(r, 1.0, exact=True) for r in records]
        candidates.sort(key=lambda c: c["binding_id"])
        if len(candidates) == 1:
            suggested: Optional[str] = candidates[0]["binding_id"]
            lead = round(candidates[0]["score"], 4)
        else:
            suggested = None
            lead = round(candidates[0]["score"] - candidates[1]["score"], 4)
        confidence = self._confidence_for(candidates[0]["score"], lead)
        return candidates, suggested, lead, confidence

    def _finalize_semantic(self, scored: list[tuple[dict[str, Any], float]]) -> tuple:
        scored.sort(key=lambda p: (-round(p[1], 4), p[0]["id"]))
        candidates: list[dict[str, Any]] = []
        for rec, score in scored:
            s = round(score, 4)
            if s < 0.55:
                break
            candidates.append(self._candidate(rec, s, exact=False))
            if len(candidates) >= 5:
                break
        if not candidates:
            return [], None, 0.0, "none"
        if len(candidates) == 1:
            lead = round(candidates[0]["score"], 4)
        else:
            lead = round(candidates[0]["score"] - candidates[1]["score"], 4)
        confidence = self._confidence_for(candidates[0]["score"], lead)
        return candidates, candidates[0]["binding_id"], lead, confidence

    def _candidate(self, rec: dict[str, Any], score: float, exact: bool) -> dict[str, Any]:
        evidence = ["属性名精确匹配"] if exact else [f"属性名相似度 {score:.4f}"]
        return {
            "binding_id": rec["id"],
            "propertyName": rec["propertyName"],
            "projectName": rec["projectName"],
            "deviceName": rec["deviceName"],
            "dataType": rec["dataType"],
            "writable": rec["writable"],
            "unit": rec["unit"],
            "score": score,
            "evidence": evidence,
        }

    def _confidence_for(self, score: float, lead: float) -> str:
        if score >= 0.85 and lead >= 0.08:
            return "high"
        if score >= 0.70 and lead >= 0.05:
            return "medium"
        if score >= 0.55:
            return "low"
        return "none"

    def build(
        self,
        json_data: dict[str, Any],
        requests: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
        canvas_validator: Optional[Validator] = None,
        binding_validator: Optional[Validator] = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        if canvas_validator is None:
            canvas_validator = self._validate_canvas
        if binding_validator is None:
            binding_validator = self._validate_binding

        match_result = self.match(json_data, requests)
        errors.extend(match_result["errors"])
        items_by_row = {int(it["row_number"]): it for it in match_result["items"]}
        targets_by_index = {t["node_i"]: t for t in match_result["targets"]}

        assigned: dict[int, str] = {}
        for a in assignments:
            row = int(a["row_number"])
            binding_id = a["binding_id"]
            if row in assigned:
                errors.append(f"第 {row} 行: 同一行存在多个 assignment")
            assigned[row] = binding_id

        for row in sorted(items_by_row.keys()):
            if row not in assigned:
                errors.append(f"第 {row} 行: 缺少 assignment")
        for row, binding_id in sorted(assigned.items()):
            if row not in items_by_row:
                errors.append(f"第 {row} 行: assignment 对应的请求不存在")
                continue
            allowed = {c["binding_id"] for c in items_by_row[row]["candidates"]}
            if binding_id not in allowed:
                errors.append(f"第 {row} 行: binding_id {binding_id} 不在允许的候选集合中")
            if binding_id not in self._record_by_id:
                errors.append(f"第 {row} 行: binding_id {binding_id} 不存在于注册表")

        used_on_target: dict[int, set[str]] = {}
        for row, binding_id in sorted(assigned.items()):
            item = items_by_row.get(row)
            if item is None or item["target_node_i"] is None:
                continue
            node_i = item["target_node_i"]
            if binding_id in used_on_target.setdefault(node_i, set()):
                errors.append(
                    f"第 {row} 行: 同一目标控件节点 {node_i} 重复选择 binding_id {binding_id}"
                )
            used_on_target[node_i].add(binding_id)

        by_node: dict[int, list[tuple[int, str]]] = {}
        for row, binding_id in assigned.items():
            item = items_by_row.get(row)
            if item is not None and item["target_node_i"] is not None:
                by_node.setdefault(item["target_node_i"], []).append((row, binding_id))

        rendered_by_node: dict[int, list[dict[str, Any]]] = {}
        for node_i, pairs in by_node.items():
            pairs.sort(key=lambda p: p[0])
            display_name = items_by_row[pairs[0][0]]["requested_displayName"]
            handler = self._find_handler(display_name)
            if handler is None:
                continue
            records = [self._record_by_id[b] for _, b in pairs if b in self._record_by_id]
            rendered_by_node[node_i] = handler.render(records)

        bound_json: Optional[dict[str, Any]] = None
        if not errors:
            bound_json = copy.deepcopy(json_data)
            for node_i, rendered in rendered_by_node.items():
                node = bound_json["d"][node_i]
                node.setdefault("a", {})["panel.list"] = rendered
            if canvas_validator is not None:
                errors.extend(f"Canvas Schema: {e}" for e in canvas_validator(bound_json))
            if binding_validator is not None:
                for node_i, pairs in by_node.items():
                    display_name = items_by_row[pairs[0][0]]["requested_displayName"]
                    handler = self._find_handler(display_name)
                    if handler is None:
                        continue
                    node_a = bound_json["d"][node_i].get("a", {})
                    errors.extend(
                        f"Binding Schema ({display_name}): {e}"
                        for e in handler.validate_output(node_a, binding_validator)
                    )
            if errors:
                bound_json = None

        previews: list[dict[str, Any]] = []
        for node_i in sorted(targets_by_index.keys()):
            target = targets_by_index[node_i]
            previews.append({
                "node_i": node_i,
                "displayName": target["displayName"],
                "handler": target["handler"],
                "before": target["existing"],
                "after": rendered_by_node.get(node_i, []),
            })

        return {
            "bound_json": bound_json,
            "previews": previews,
            "errors": errors,
            "warnings": warnings,
        }

    def _validate_canvas(self, json_data: dict[str, Any]) -> list[str]:
        validator = jsonschema.Draft7Validator(self._canvas_schema)
        return [e.message for e in validator.iter_errors(json_data)]

    def _validate_binding(self, data: dict[str, Any]) -> list[str]:
        validator = jsonschema.Draft7Validator(self._binding_schema)
        return [e.message for e in validator.iter_errors(data)]
