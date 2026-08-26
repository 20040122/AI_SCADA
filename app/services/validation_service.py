from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft7Validator

from app.config import settings
from app.schemas import RuleCategoryMeta, RuleProperty, ValidationErrorItem

_SCHEMA_SOURCES = {
    "control": settings.control_schema_path,
    "canvas": settings.schema_path,
    "binding": settings.binding_schema_path,
}

_CONTROL_PROPERTIES = [
    RuleProperty(path="displayName", type="string", required=True, description="控件显示名称"),
    RuleProperty(path="image", type="string", required=True, description="控件资源路径（symbols/ 或 assets/ 下的 JSON 或图片文件）"),
    RuleProperty(path="width", type="number | null", required=True, description="控件宽度"),
    RuleProperty(path="height", type="number | null", required=True, description="控件高度"),
    RuleProperty(path="boundExtend", type="number", required=False, description="边界扩展像素值"),
]

_CANVAS_PROPERTIES = [
    RuleProperty(path="v", type="string", required=True, description="版本号"),
    RuleProperty(path="p", type="object", required=True, description="画布属性，含 layers、autoAdjustIndex、hierarchicalRendering"),
    RuleProperty(path="a", type="object", required=True, description="画布尺寸与行为，含 width、height、fitContent、rectSelectable、pannable、zoomable"),
    RuleProperty(path="d", type="array", required=True, description="数据元素数组"),
    RuleProperty(path="contentRect", type="object", required=True, description="内容边界，含 x、y、width、height"),
]

_BINDING_PROPERTIES = [
    RuleProperty(path="panel.list", type="array", required=True, description="绑定项数组，每个元素为 {label, bind}"),
    RuleProperty(path="label", type="string", required=True, description="绑定项显示名（属性名）"),
    RuleProperty(path="bind.type", type="string", required=True, description="绑定类型", enum=["designer"]),
    RuleProperty(path="bind.path", type="string", required=True, description="绑定路径：<projectId>#<deviceId>#<propertyId>"),
    RuleProperty(path="bind.key", type="string", required=True, description="绑定键：<deviceId>#<propertyId>"),
    RuleProperty(path="bind.label", type="string", required=True, description="展示标签：<项目名> . <设备名> . <属性名> (<单位>)"),
    RuleProperty(path="bind.proj.id", type="string", required=True, description="项目 ID"),
    RuleProperty(path="bind.proj.name", type="string", required=True, description="项目名称"),
    RuleProperty(path="bind.dev.id", type="string", required=True, description="设备 ID"),
    RuleProperty(path="bind.dev.name", type="string", required=True, description="设备名称"),
    RuleProperty(path="bind.param.id", type="string", required=True, description="属性 ID"),
    RuleProperty(path="bind.param.name", type="string", required=True, description="属性名称"),
    RuleProperty(path="bind.param.unit", type="string", required=True, description="单位（可为空）"),
    RuleProperty(path="bind.param.writable", type="boolean", required=True, description="是否可写"),
    RuleProperty(path="bind.param.dataType", type="string", required=True, description="数据类型", enum=["double", "int", "bool", "string"]),
    RuleProperty(path="bind.param.dataTypeDesc", type="string", required=True, description="数据类型描述"),
]

_LAYOUT_GROUP_PROPERTIES = [
    RuleProperty(path="layoutIntent.groups", type="array", required=True, description="布局组数组"),
    RuleProperty(path="group.id", type="string", required=True, description="组唯一标识"),
    RuleProperty(path="group.region", type="string", required=True, description="区域", enum=["left", "right", "center"]),
    RuleProperty(path="group.count", type="integer", required=True, description="组数量，>= 1"),
    RuleProperty(path="group.arrangement", type="string", required=False, description="排列方式", enum=["vertical", "horizontal", "grid"]),
    RuleProperty(path="group.unit.root.id", type="string", required=True, description="根节点 ID"),
    RuleProperty(path="group.unit.root.deviceType", type="string", required=True, description="根节点设备类型"),
    RuleProperty(path="group.unit.attachments[].id", type="string", required=True, description="附件节点 ID"),
    RuleProperty(path="group.unit.attachments[].relativeTo", type="string", required=True, description="引用本组已声明节点"),
    RuleProperty(path="group.unit.attachments[].side", type="string", required=True, description="相对侧", enum=["top", "right", "bottom", "left"]),
]

_CATEGORY_LABELS = {
    "control": "控件资源与尺寸",
    "canvas": "画布与编辑行为",
    "layout": "布局与拓扑",
    "binding": "数据绑定与通信",
}

_CATEGORY_TITLES = {
    "control": "控件索引项 (ControlIndexItem)",
    "canvas": "画布 (Canva)",
    "layout": "布局意图 (LayoutIntent)",
    "binding": "绑定面板 (Binding Panel)",
}

_CATEGORY_DESCRIPTIONS = {
    "control": "控件资源与尺寸约束",
    "canvas": "画布与编辑行为约束",
    "layout": "布局与拓扑约束 — 角色尺寸、区域排列、附件关系、连线合法性",
    "binding": "数据绑定与通信约束 — 状态面板节点 a[\"panel.list\"] 的绑定项结构（type=designer 变量映射）",
}

_LAYOUT_DERIVED_RULES = [
    "groups 不能为空",
    "group.id 必须唯一",
    "同组内节点 id 不能重复",
    "group.count >= 1",
    "当 arrangement=grid 时，columns 或 rows 至少一个 >= 1，且 columns*rows >= count",
    "attachment.relativeTo 必须引用本组已声明的节点",
    "attachment.count >= 1",
    "group.relativeTo 必须引用已存在的 group",
    "relativeTo 与 side 必须同时声明",
    "组级相对位置不能存在循环引用",
    "布局中间表示拒绝未知字段",
]

_BINDING_DERIVED_RULES = [
    "每个绑定项 bind.type 固定为 designer",
    "bind.path 格式：<projectId>#<deviceId>#<propertyId>（三者均为数字字符串）",
    "bind.key 格式：<deviceId>#<propertyId>（与 path 中后两段一致）",
    "bind.param.dataType 仅允许 double|int|bool|string",
    "展示 label 与 proj.name . dev.name . param.name (param.unit) 一致",
    "同一面板内 bind.path 不得重复",
    "完整画布下，遍历每个 d 节点的 a.panel.list 校验，错误路径包含完整节点位置",
]

_CANVAS_DERIVED_RULES = [
    "layers 至少有一个图层",
    "a.width 和 a.height 应大于 0",
    "d 数组元素应至少包含非空 c 和对象 p",
    "contentRect.x/y/width/height 不得为负",
    "空画布允许零尺寸 contentRect",
    "画布保留未声明的 DaoSCADA 扩展字段",
]

_CONTROL_DERIVED_RULES = [
    "image 路径应以 symbols/ 或 assets/ 开头",
    "displayName 不应为空",
    "width 和 height 不得为负数",
    "boundExtend 若存在应 >= 0",
    "0 或 null 尺寸产生 warning",
]


class ValidationServiceError(RuntimeError):
    pass


class SchemaLoadError(ValidationServiceError):
    pass


class ValidationService:
    _instance: Optional["ValidationService"] = None

    def __init__(self) -> None:
        self._validators: dict[str, Draft7Validator] = {}
        self._load_schemas()
        self._build_meta()

    @classmethod
    def instance(cls) -> "ValidationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_schemas(self) -> None:
        for category, raw_path in _SCHEMA_SOURCES.items():
            path = Path(raw_path)
            if not path.exists():
                raise SchemaLoadError(f"{category} schema 文件缺失: {path}")
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SchemaLoadError(f"{category} schema JSON 解析失败: {exc}") from exc
            Draft7Validator.check_schema(schema)
            self._validators[category] = Draft7Validator(schema)

    def _build_meta(self) -> None:
        self._meta: dict[str, RuleCategoryMeta] = {
            "control": RuleCategoryMeta(
                category="control",
                label=_CATEGORY_LABELS["control"],
                title=_CATEGORY_TITLES["control"],
                description=_CATEGORY_DESCRIPTIONS["control"],
                properties=_CONTROL_PROPERTIES,
                derived_rules=_CONTROL_DERIVED_RULES,
                sample_valid={
                    "displayName": "电动调节阀",
                    "image": "symbols/valve_001.json",
                    "width": 60,
                    "height": 60,
                },
                sample_invalid={
                    "displayName": "",
                    "image": "unknown/valve.png",
                    "width": -1,
                    "height": "abc",
                    "boundExtend": -5,
                },
            ),
            "canvas": RuleCategoryMeta(
                category="canvas",
                label=_CATEGORY_LABELS["canvas"],
                title=_CATEGORY_TITLES["canvas"],
                description=_CATEGORY_DESCRIPTIONS["canvas"],
                properties=_CANVAS_PROPERTIES,
                derived_rules=_CANVAS_DERIVED_RULES,
                sample_valid={
                    "v": "8.0.5",
                    "p": {
                        "layers": [{"name": "0", "visible": True, "selectable": True, "movable": True, "editable": True}],
                        "autoAdjustIndex": True,
                        "hierarchicalRendering": True,
                    },
                    "a": {"width": 1920, "height": 1080, "fitContent": True, "rectSelectable": False, "pannable": False, "zoomable": False},
                    "d": [{"c": "ht.Node", "i": 17092, "p": {"displayName": "阀1", "image": "symbols/valve_001.json", "width": 60, "height": 60}}],
                    "contentRect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                },
                sample_invalid={
                    "v": 123,
                    "p": None,
                    "a": {"width": -100, "height": 0, "fitContent": True},
                    "d": "not an array",
                    "contentRect": {"x": 0, "y": 0},
                },
            ),
            "layout": RuleCategoryMeta(
                category="layout",
                label=_CATEGORY_LABELS["layout"],
                title=_CATEGORY_TITLES["layout"],
                description=_CATEGORY_DESCRIPTIONS["layout"],
                properties=_LAYOUT_GROUP_PROPERTIES,
                derived_rules=_LAYOUT_DERIVED_RULES,
                sample_valid={
                    "layoutIntent": {
                        "groups": [
                            {
                                "id": "group1",
                                "region": "center",
                                "unit": {
                                    "root": {"id": "valve_1", "deviceType": "电动调节阀", "role": "valve"},
                                    "attachments": [{"id": "sensor_1", "deviceType": "压力传感器", "role": "sensor", "relativeTo": "valve_1", "side": "right"}],
                                },
                                "count": 2,
                                "arrangement": "horizontal",
                                "gapHint": "normal",
                            }
                        ]
                    }
                },
                sample_invalid={"layoutIntent": {"groups": []}},
            ),
            "binding": RuleCategoryMeta(
                category="binding",
                label=_CATEGORY_LABELS["binding"],
                title=_CATEGORY_TITLES["binding"],
                description=_CATEGORY_DESCRIPTIONS["binding"],
                properties=_BINDING_PROPERTIES,
                derived_rules=_BINDING_DERIVED_RULES,
                sample_valid={
                    "panel.list": [
                        {
                            "label": "空气罐温度",
                            "bind": {
                                "type": "designer",
                                "path": "2084524131092914178#2084937599679848450#2084940408848506881",
                                "key": "2084937599679848450#2084940408848506881",
                                "label": "Agent . 空气罐 . 空气罐温度 (°C)",
                                "proj": {"id": "2084524131092914178", "name": "Agent"},
                                "dev": {"id": "2084937599679848450", "name": "空气罐"},
                                "param": {
                                    "id": "2084940408848506881",
                                    "name": "空气罐温度",
                                    "unit": "°C",
                                    "writable": False,
                                    "dataType": "int",
                                    "dataTypeDesc": "整型",
                                },
                            },
                        }
                    ]
                },
                sample_invalid={
                    "panel.list": [
                        {
                            "label": "",
                            "bind": {
                                "type": "unknown",
                                "path": "abc#xyz",
                                "key": "",
                                "label": "",
                                "proj": {},
                                "dev": {},
                                "param": {
                                    "id": "",
                                    "name": "",
                                    "unit": "",
                                    "writable": "yes",
                                    "dataType": "int16",
                                    "dataTypeDesc": "",
                                },
                            },
                        }
                    ]
                },
            ),
        }

    def rules_meta(self) -> list[dict]:
        return [m.model_dump() for m in self._meta.values()]

    def _schema_errors(self, category: str, json_data: Any) -> list[ValidationErrorItem]:
        total: list[str] = []
        for err in self._validators[category].iter_errors(json_data):
            elems = list(err.absolute_path)
            pointer = _pointer(elems)
            total.append("%s|%s|%s|%s" % (pointer, err.validator, str(err.message), str(list(err.schema_path))))
        dedup = _dedup(total)
        out: list[ValidationErrorItem] = []
        for line in dedup:
            pointer, validator, message, _ = line.split("|", 3)
            out.append(ValidationErrorItem(path=pointer, message=message.strip(), error_type=validator, source="schema"))
        return out

    def _errors(self, errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        for item in errors:
            if item.source == "semantic":
                item.path = _dot_to_pointer(item.path)
        for item in warnings:
            item.path = _dot_to_pointer(item.path) if item.source == "semantic" else item.path
        errs = sorted(errors, key=lambda e: (e.path, e.message))
        warms = sorted(warnings, key=lambda e: (e.path, e.message))
        return _dedup_items(errs), _dedup_items(warms)

    def validate(self, category: str, json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        if category == "binding":
            return self._validate_binding(json_data)
        if category == "layout":
            return self._validate_layout(json_data)
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        errors.extend(self._schema_errors(category, json_data))
        if category == "control":
            cerrs, cwarns = _control_semantic(json_data)
            errors.extend(cerrs)
            warnings.extend(cwarns)
        elif category == "canvas":
            cerrs, cwarns = _canvas_semantic(json_data)
            errors.extend(cerrs)
            warnings.extend(cwarns)
        return self._errors(errors, warnings)

    def _validate_layout(self, json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        from model.layout_tools.get_intent import LayoutFile, validate_layout_file

        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        unknown = _layout_unknown_fields(json_data, "layoutIntent")
        errors.extend(unknown)
        try:
            layout_file = LayoutFile.model_validate(json_data)
        except Exception as exc:
            return self._errors(
                [ValidationErrorItem(path="layoutIntent", message=str(exc), error_type="parse", source="semantic")],
                [],
            )
        if unknown:
            return self._errors(errors, [])
        raw_errors, raw_warnings = validate_layout_file(layout_file)
        for e in raw_errors:
            errors.append(ValidationErrorItem(path=e.path, message=e.message, error_type="semantic", source="semantic"))
        for w in raw_warnings:
            warnings.append(ValidationErrorItem(path="", message=w, error_type="warning", source="semantic"))
        errors.extend(_layout_duplicate_node_ids(layout_file))
        return self._errors(errors, warnings)

    def _validate_binding(self, json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        if isinstance(json_data, dict) and ("d" in json_data or "v" in json_data or "a" in json_data):
            errors: list[ValidationErrorItem] = []
            warnings: list[ValidationErrorItem] = []
            cerrs, cwarns = self._canvas_for_binding(json_data)
            errors.extend(cerrs)
            warnings.extend(cwarns)
            if not cerrs:
                perrs, pwarns = _binding_d_panels(json_data)
                errors.extend(perrs)
                warnings.extend(pwarns)
            return self._errors(errors, warnings)
        return self._binding_panel(json_data)

    def _canvas_for_binding(self, json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        errors.extend(self._schema_errors("canvas", json_data))
        cerrs, cwarns = _canvas_semantic(json_data)
        errors.extend(cerrs)
        return errors, cwarns

    def _binding_panel(self, json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        schema_errors = self._schema_errors("binding", json_data)
        errors.extend(schema_errors)
        if not schema_errors:
            perrs, pwarns = _binding_items_validate(json_data.get("panel.list") or [], "")
            errors.extend(perrs)
            warnings.extend(pwarns)
            if errors:
                return self._errors(errors, warnings)
            if not json_data.get("panel.list"):
                warnings.append(ValidationErrorItem(path="panel.list", message="绑定列表为空", error_type="warning", source="semantic"))
        return self._errors(errors, warnings)


def _pointer(elems: list[Any]) -> str:
    if not elems:
        return ""
    return "/" + "/".join(str(e) for e in elems)


def _dot_to_pointer(path: str) -> str:
    if not path:
        return ""
    if path.startswith("/"):
        return path
    result = ""
    i = 0
    n = len(path)
    while i < n:
        c = path[i]
        if c == ".":
            result += "/"
            i += 1
        elif c == "[":
            end = path.find("]", i)
            index = path[i + 1 : end] if end != -1 else ""
            result += "/" + index
            i = end + 1 if end != -1 else i + 1
        else:
            result += c
            i += 1
    if not result.startswith("/"):
        result = "/" + result
    return result


def _dedup(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _dedup_items(items: list[ValidationErrorItem]) -> list[ValidationErrorItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ValidationErrorItem] = []
    for item in items:
        key = (item.path, item.message, item.source)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _is_zero_or_null(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)


def _control_semantic(json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
    if not isinstance(json_data, dict):
        return errors, warnings
    name = json_data.get("displayName")
    if not isinstance(name, str) or not name:
        errors.append(ValidationErrorItem(path="displayName", message="displayName 非空字符串", error_type="semantic", source="semantic"))
    image = json_data.get("image")
    if isinstance(image, str):
        if not (image.startswith("symbols/") or image.startswith("assets/")):
            errors.append(ValidationErrorItem(path="image", message="image 路径应以 symbols/ 或 assets/ 开头", error_type="semantic", source="semantic"))
    for key in ("width", "height"):
        value = json_data.get(key)
        if isinstance(value, bool):
            errors.append(ValidationErrorItem(path=key, message=f"{key} 必须为数值或 null", error_type="semantic", source="semantic"))
            continue
        if isinstance(value, (int, float)):
            if value < 0:
                errors.append(ValidationErrorItem(path=key, message=f"{key} 不得为负数", error_type="semantic", source="semantic"))
            elif value == 0:
                warnings.append(ValidationErrorItem(path=key, message=f"{key} 为 0（空尺寸）", error_type="warning", source="semantic"))
        elif value is None:
            warnings.append(ValidationErrorItem(path=key, message=f"{key} 为 null（空尺寸）", error_type="warning", source="semantic"))
    bound_extend = json_data.get("boundExtend")
    if isinstance(bound_extend, (int, float)) and not isinstance(bound_extend, bool) and bound_extend < 0:
        errors.append(ValidationErrorItem(path="boundExtend", message="boundExtend 必须大于等于 0", error_type="semantic", source="semantic"))
    return errors, warnings


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number <= 0:
        return None
    return number


def _canvas_semantic(json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
    if not isinstance(json_data, dict):
        return errors, warnings
    p = json_data.get("p")
    if isinstance(p, dict):
        layers = p.get("layers")
        if not isinstance(layers, list) or not layers:
            errors.append(ValidationErrorItem(path="p.layers", message="layers 至少有一个图层", error_type="semantic", source="semantic"))
    a = json_data.get("a")
    if isinstance(a, dict):
        aw = _positive(a.get("width"))
        ah = _positive(a.get("height"))
        if aw is None:
            errors.append(ValidationErrorItem(path="a.width", message="a.width 必须为正数", error_type="semantic", source="semantic"))
        if ah is None:
            errors.append(ValidationErrorItem(path="a.height", message="a.height 必须为正数", error_type="semantic", source="semantic"))
    d = json_data.get("d") or []
    for idx, item in enumerate(d):
        if not isinstance(item, dict):
            errors.append(ValidationErrorItem(path=f"d[{idx}]", message="d 数组元素必须是对象", error_type="semantic", source="semantic"))
            continue
        c = item.get("c")
        if not isinstance(c, str) or not c:
            errors.append(ValidationErrorItem(path=f"d[{idx}].c", message="d 元素 c 必须为非空字符串", error_type="semantic", source="semantic"))
        pp = item.get("p")
        if not isinstance(pp, dict):
            errors.append(ValidationErrorItem(path=f"d[{idx}].p", message="d 元素 p 必须为对象", error_type="semantic", source="semantic"))
    content_rect = json_data.get("contentRect") or {}
    if isinstance(content_rect, dict):
        for key in ("x", "y", "width", "height"):
            value = content_rect.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
                errors.append(ValidationErrorItem(path=f"contentRect.{key}", message="contentRect 不得为负", error_type="semantic", source="semantic"))
    return errors, warnings


def _layout_unknown_fields(json_data: Any, root: str) -> list[ValidationErrorItem]:
    if not isinstance(json_data, dict):
        return []
    errors: list[ValidationErrorItem] = []
    intent = json_data.get(root)
    if not isinstance(intent, dict):
        return errors
    intent_keys = {"groups", "constraints"}
    for key in intent:
        if key not in intent_keys and not key.startswith("public"):
            errors.append(ValidationErrorItem(path=f"{root}.{key}", message=f"未知字段: {key}", error_type="semantic", source="semantic"))
    groups = intent.get("groups")
    if not isinstance(groups, list):
        return errors
    group_keys = {"id", "region", "unit", "count", "arrangement", "gapHint", "columns", "rows", "order", "topology", "relativeTo", "side"}
    unit_keys = {"root", "attachments"}
    node_keys = {"id", "deviceType", "role"}
    attachment_keys = {"id", "deviceType", "role", "relativeTo", "side", "count"}
    for gi, group in enumerate(groups):
        gp = f"{root}.groups[{gi}]"
        if not isinstance(group, dict):
            continue
        for key in group:
            if key not in group_keys:
                errors.append(ValidationErrorItem(path=f"{gp}.{key}", message=f"未知字段: {key}", error_type="semantic", source="semantic"))
        unit = group.get("unit")
        if isinstance(unit, dict):
            for key in unit:
                if key not in unit_keys:
                    errors.append(ValidationErrorItem(path=f"{gp}.unit.{key}", message=f"未知字段: {key}", error_type="semantic", source="semantic"))
            root_node = unit.get("root")
            if isinstance(root_node, dict):
                for key in root_node:
                    if key not in node_keys:
                        errors.append(ValidationErrorItem(path=f"{gp}.unit.root.{key}", message=f"未知字段: {key}", error_type="semantic", source="semantic"))
            attachments = unit.get("attachments")
            if isinstance(attachments, list):
                for ai, att in enumerate(attachments):
                    ap = f"{gp}.unit.attachments[{ai}]"
                    if not isinstance(att, dict):
                        continue
                    for key in att:
                        if key not in attachment_keys:
                            errors.append(ValidationErrorItem(path=f"{ap}.{key}", message=f"未知字段: {key}", error_type="semantic", source="semantic"))
    return errors


def _layout_duplicate_node_ids(layout_file: Any) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []
    for gi, group in enumerate(layout_file.layoutIntent.groups):
        seen: dict[str, str] = {}
        gp = f"layoutIntent.groups[{gi}]"
        nodes = [("unit.root", group.unit.root)] + [("unit.attachments[%d]" % ai, att) for ai, att in enumerate(group.unit.attachments)]
        for loc, node in nodes:
            node_id = node.id
            if node_id in seen:
                errors.append(ValidationErrorItem(path=f"{gp}.{loc}.id", message=f"同组节点 id 重复: {node_id}", error_type="semantic", source="semantic"))
            else:
                seen[node_id] = loc
    return errors


def _is_digit_str(value: Any) -> bool:
    return isinstance(value, str) and value.isdigit()


def _binding_d_panels(json_data: Any) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
    d = json_data.get("d") or []
    found = False
    for i, node in enumerate(d):
        if not isinstance(node, dict):
            continue
        a = node.get("a")
        if not isinstance(a, dict):
            continue
        if "panel.list" not in a:
            continue
        found = True
        perrs, pwarns = _binding_items_validate(a["panel.list"] or [], f"d[{i}].a")
        errors.extend(perrs)
        warnings.extend(pwarns)
        if not a["panel.list"]:
            warnings.append(ValidationErrorItem(path=f"d[{i}].a.panel.list", message="绑定列表为空", error_type="warning", source="semantic"))
    if not found:
        warnings.append(ValidationErrorItem(path="/d", message="画布中未发现绑定", error_type="warning", source="semantic"))
    return errors, warnings


def _binding_items_validate(items: list[Any], base: str) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
    seen_paths: set[str] = set()
    for idx, item in enumerate(items):
        p = f"{base}.panel.list[{idx}]"
        if not isinstance(item, dict):
            errors.append(ValidationErrorItem(path=p, message="绑定项必须是对象", error_type="semantic", source="semantic"))
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label:
            errors.append(ValidationErrorItem(path=f"{p}.label", message="label 必须为非空字符串", error_type="semantic", source="semantic"))
        bind = item.get("bind")
        if not isinstance(bind, dict):
            if "bind" not in item:
                errors.append(ValidationErrorItem(path=f"{p}.bind", message="缺少 bind", error_type="semantic", source="semantic"))
            else:
                errors.append(ValidationErrorItem(path=f"{p}.bind", message="bind 必须是对象", error_type="semantic", source="semantic"))
            continue
        _binding_bind_validate(bind, p, errors, seen_paths)
    return errors, warnings


def _binding_bind_validate(bind: dict, p: str, errors: list[ValidationErrorItem], seen_paths: set[str]) -> None:
    bind_keys = {"type", "path", "key", "label", "proj", "dev", "param"}
    for bk in bind:
        if bk not in bind_keys:
            errors.append(ValidationErrorItem(path=f"{p}.bind.{bk}", message=f"未知字段: {bk}", error_type="semantic", source="semantic"))
    btype = bind.get("type")
    if btype != "designer":
        errors.append(ValidationErrorItem(path=f"{p}.bind.type", message="bind.type 必须为 designer", error_type="semantic", source="semantic"))
    path = bind.get("path")
    if not isinstance(path, str) or not path:
        errors.append(ValidationErrorItem(path=f"{p}.bind.path", message="bind.path 必须为非空字符串", error_type="semantic", source="semantic"))
    else:
        parts = path.split("#")
        if len(parts) != 3 or not all(_is_digit_str(part) for part in parts):
            errors.append(ValidationErrorItem(path=f"{p}.bind.path", message="bind.path 格式必须为 <projectId>#<deviceId>#<propertyId>（数字字符串）", error_type="semantic", source="semantic"))
        else:
            if path in seen_paths:
                errors.append(ValidationErrorItem(path=f"{p}.bind.path", message=f"同一面板内 bind.path 重复: {path}", error_type="semantic", source="semantic"))
            seen_paths.add(path)
    key = bind.get("key")
    if not isinstance(key, str) or not key:
        errors.append(ValidationErrorItem(path=f"{p}.bind.key", message="bind.key 必须为非空字符串", error_type="semantic", source="semantic"))
    label = bind.get("label")
    if not isinstance(label, str) or not label:
        errors.append(ValidationErrorItem(path=f"{p}.bind.label", message="bind.label 必须为非空字符串", error_type="semantic", source="semantic"))
    proj_name = None
    dev_name = None
    param_name = None
    param_unit = None
    proj = bind.get("proj")
    if not isinstance(proj, dict):
        errors.append(ValidationErrorItem(path=f"{p}.bind.proj", message="bind.proj 必须是对象", error_type="semantic", source="semantic"))
    elif not set(("id", "name")) <= set(proj.keys()):
        errors.append(ValidationErrorItem(path=f"{p}.bind.proj", message="bind.proj 必须包含 id 和 name", error_type="semantic", source="semantic"))
    else:
        _id_field(proj, "id", f"{p}.bind.proj", errors)
        proj_name = _name_field(proj, "name", f"{p}.bind.proj", errors)
    dev = bind.get("dev")
    if not isinstance(dev, dict):
        errors.append(ValidationErrorItem(path=f"{p}.bind.dev", message="bind.dev 必须是对象", error_type="semantic", source="semantic"))
    elif not set(("id", "name")) <= set(dev.keys()):
        errors.append(ValidationErrorItem(path=f"{p}.bind.dev", message="bind.dev 必须包含 id 和 name", error_type="semantic", source="semantic"))
    else:
        _id_field(dev, "id", f"{p}.bind.dev", errors)
        dev_name = _name_field(dev, "name", f"{p}.bind.dev", errors)
    param = bind.get("param")
    param_keys = {"id", "name", "unit", "writable", "dataType", "dataTypeDesc"}
    if not isinstance(param, dict):
        errors.append(ValidationErrorItem(path=f"{p}.bind.param", message="bind.param 必须是对象", error_type="semantic", source="semantic"))
    elif not set(param_keys) <= set(param.keys()):
        errors.append(ValidationErrorItem(path=f"{p}.bind.param", message="bind.param 缺少字段", error_type="semantic", source="semantic"))
    else:
        for pk in param:
            if pk not in param_keys:
                errors.append(ValidationErrorItem(path=f"{p}.bind.param.{pk}", message=f"未知字段: {pk}", error_type="semantic", source="semantic"))
        _id_field(param, "id", f"{p}.bind.param", errors)
        param_name = _name_field(param, "name", f"{p}.bind.param", errors)
        unit = param.get("unit")
        if not isinstance(unit, str):
            errors.append(ValidationErrorItem(path=f"{p}.bind.param.unit", message="unit 必须为字符串", error_type="semantic", source="semantic"))
        else:
            param_unit = unit
        if not isinstance(param.get("writable"), bool):
            errors.append(ValidationErrorItem(path=f"{p}.bind.param.writable", message="writable 必须为布尔值", error_type="semantic", source="semantic"))
        if param.get("dataType") not in ("double", "int", "bool", "string"):
            errors.append(ValidationErrorItem(path=f"{p}.bind.param.dataType", message="dataType 仅允许 double|int|bool|string", error_type="semantic", source="semantic"))
    if isinstance(path, str) and len(path.split("#")) == 3:
        pid, did, ppid = path.split("#")
        if isinstance(proj, dict) and proj.get("id") is not None and str(proj.get("id")) != pid:
            errors.append(ValidationErrorItem(path=f"{p}.bind.proj.id", message="proj.id 与 path 不一致", error_type="semantic", source="semantic"))
        if isinstance(dev, dict) and dev.get("id") is not None and str(dev.get("id")) != did:
            errors.append(ValidationErrorItem(path=f"{p}.bind.dev.id", message="dev.id 与 path 不一致", error_type="semantic", source="semantic"))
        if isinstance(param, dict) and param.get("id") is not None and str(param.get("id")) != ppid:
            errors.append(ValidationErrorItem(path=f"{p}.bind.param.id", message="param.id 与 path 不一致", error_type="semantic", source="semantic"))
        if isinstance(key, str):
            expected_key = f"{did}#{ppid}"
            if key != expected_key and (did or ppid):
                errors.append(ValidationErrorItem(path=f"{p}.bind.key", message="bind.key 与 path 后两段不一致", error_type="semantic", source="semantic"))
    if label is not None and _is_str(label) and (proj_name or dev_name or param_name):
        expect_unit = f" ({param_unit})" if param_unit else ""
        expected_label = f"{proj_name} . {dev_name} . {param_name}{expect_unit}"
        if label != expected_label:
            errors.append(ValidationErrorItem(path=f"{p}.bind.label", message="bind.label 与 名称/单位 不一致", error_type="semantic", source="semantic"))


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _id_field(obj: dict, key: str, base: str, errors: list[ValidationErrorItem]) -> None:
    value = obj.get(key)
    if not _is_digit_str(value):
        errors.append(ValidationErrorItem(path=f"{base}.{key}", message=f"{key} 必须为数字字符串", error_type="semantic", source="semantic"))


def _name_field(obj: dict, key: str, base: str, errors: list[ValidationErrorItem]) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        errors.append(ValidationErrorItem(path=f"{base}.{key}", message=f"{key} 必须为非空字符串", error_type="semantic", source="semantic"))
        return ""
    return value
