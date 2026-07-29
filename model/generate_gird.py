import asyncio
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from openai import APITimeoutError
from pydantic import BaseModel, Field, ValidationError

from model.layout_agent import _llm_text, _parse_json_lenient
from model.llm_client import default_client

logger = logging.getLogger(__name__)

Region = Literal["left", "right", "center"]
Side = Literal["top", "right", "bottom", "left"]
Arrangement = Literal["vertical", "horizontal", "grid"]
GapHint = Literal["tight", "normal", "loose"]
GridOrder = Literal["row-major", "col-major"]
Role = Literal["root", "valve", "pipe", "meter", "sensor", "default"]
Topology = Literal["single", "series", "parallel"]
RouteStyle = Literal["direct", "orthogonal"]
Direction = Literal["horizontal", "vertical"]

_INTENT_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "layout" / "intent.json"
_GENERATE_GIRD_MODEL = "deepseek-v4-flash"
_INTENT_CACHE = OrderedDict()
_INTENT_CACHE_VERSION = 2


class DeviceNode(BaseModel):
    id: str
    deviceType: str
    role: Optional[Role] = None


class AttachmentNode(DeviceNode):
    relativeTo: str
    side: Side
    count: Optional[int] = None


class LayoutUnit(BaseModel):
    root: DeviceNode
    attachments: List[AttachmentNode] = Field(default_factory=list)


class LayoutGroup(BaseModel):
    id: str
    region: Region
    unit: LayoutUnit
    count: int
    arrangement: Optional[Arrangement] = None
    gapHint: Optional[GapHint] = None
    columns: Optional[int] = None
    rows: Optional[int] = None
    order: Optional[GridOrder] = None
    topology: Topology = "single"
    relativeTo: Optional[str] = None
    side: Optional[Side] = None


class LayoutConstraints(BaseModel):
    routeStyle: Optional[RouteStyle] = None
    allowedDirections: List[Direction] = Field(default_factory=list)
    equalSpacing: bool = False
    alignRepeated: bool = False
    consistentBranches: bool = False


class LayoutIntent(BaseModel):
    groups: List[LayoutGroup]
    constraints: LayoutConstraints = Field(default_factory=LayoutConstraints)


class LayoutFile(BaseModel):
    layoutIntent: LayoutIntent


@dataclass
class ValidationErrorItem:
    path: str
    message: str


@dataclass
class InventoryItem:
    deviceType: str
    count: int


@dataclass
class StructuredLayoutPrompt:
    inventory: List[InventoryItem]
    flow: str
    structure: str
    flowPaths: List[List[str]]
    parallelDevices: List[str]


class StructuredPromptError(ValueError):
    def __init__(self, errors: List[ValidationErrorItem]):
        self.errors = errors
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in errors))


class IntentModelUnavailableError(RuntimeError):
    pass


class IntentModelTimeoutError(RuntimeError):
    pass


class IntentModelOutputError(RuntimeError):
    def __init__(self, message: str, raw_output: Optional[str] = None):
        self.raw_output = raw_output
        super().__init__(message)


async def _call_intent_model(client, model, messages, **kwargs):
    timeout = 15
    try:
        request_client = client.with_options(max_retries=0, timeout=timeout)
        return await asyncio.wait_for(request_client.chat.completions.create(model=model, messages=messages, **kwargs), timeout=timeout)
    except (asyncio.TimeoutError, APITimeoutError) as exc:
        raise IntentModelTimeoutError("布局模型请求超时") from exc


_SECTION_PATTERN = re.compile(r"(?m)^\s*(控件|流程|结构|管道|要求)\s*[：:]")
_COUNT_PATTERN = re.compile(r"(\d+|[一二三四五六七八九十]+)\s*(?:台|个|组)")
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _parse_count(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        return _CHINESE_NUMBERS.get(left, 1) * 10 + _CHINESE_NUMBERS.get(right, 0)
    return _CHINESE_NUMBERS[value]


def _split_sections(prompt: str) -> dict:
    matches = list(_SECTION_PATTERN.finditer(prompt))
    sections = {}
    errors: List[ValidationErrorItem] = []
    for index, match in enumerate(matches):
        name = match.group(1)
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        content = prompt[match.end() : content_end].strip()
        if name in sections:
            errors.append(ValidationErrorItem(path=name, message="段落重复"))
        elif name == "管道":
            pass
        elif not content:
            errors.append(ValidationErrorItem(path=name, message="段落不能为空"))
        else:
            sections[name] = content
    if "要求" in sections:
        errors.append(ValidationErrorItem(path="要求", message="该段落已不再支持"))
    for name in ("控件", "流程", "结构"):
        if name not in sections and not any(item.path == name for item in errors):
            errors.append(ValidationErrorItem(path=name, message="缺少段落"))
    if errors:
        raise StructuredPromptError(errors)
    return sections


def _parse_inventory(text: str) -> List[InventoryItem]:
    inventory: List[InventoryItem] = []
    errors: List[ValidationErrorItem] = []
    for part in re.split(r"[、，,；;。]|以及(?=(?:\d+|[一二三四五六七八九十]+)\s*(?:台|个|组))", text):
        item = part.strip()
        if not item:
            continue
        match = re.fullmatch(r"(\d+|[一二三四五六七八九十]+)\s*(?:台|个|组)\s*(.+)", item)
        if not match:
            errors.append(ValidationErrorItem(path="控件", message=f"无法解析设备数量：{item}"))
            continue
        count = _parse_count(match.group(1))
        device_type = match.group(2).strip()
        if count < 1:
            errors.append(ValidationErrorItem(path=f"控件.{device_type}.count", message="数量必须大于等于 1"))
        elif any(existing.deviceType == device_type for existing in inventory):
            errors.append(ValidationErrorItem(path=f"控件.{device_type}", message="设备重复"))
        else:
            inventory.append(InventoryItem(deviceType=device_type, count=count))
    if not inventory:
        errors.append(ValidationErrorItem(path="控件", message="未识别到设备"))
    if errors:
        raise StructuredPromptError(errors)
    return inventory


def _structure_count(structure: str, device_type: str) -> Optional[int]:
    escaped = re.escape(device_type)
    patterns = (
        rf"(\d+|[一二三四五六七八九十]+)\s*(?:台|个|组)\s*{escaped}",
        rf"{escaped}[^；;。]*?(\d+|[一二三四五六七八九十]+)\s*(?:台|个|组)\s*设备",
    )
    for pattern in patterns:
        match = re.search(pattern, structure)
        if match:
            return _parse_count(match.group(1))
    return None


def _flow_paths(flow: str, inventory: List[InventoryItem]) -> List[List[str]]:
    names = sorted((item.deviceType for item in inventory), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(name) for name in names))
    paths: List[List[str]] = []
    for sentence in re.split(r"[；;。]", flow):
        for clause in sentence.split("，"):
            if "-" not in clause:
                continue
            path = [match.group(0) for match in pattern.finditer(clause)]
            if len(path) >= 2:
                paths.append(path)
    return paths


def _parallel_devices(flow: str, inventory: List[InventoryItem]) -> List[str]:
    if "采用并联" not in flow:
        return []
    clause = flow.split("采用并联", 1)[0]
    clause = re.split(r"[；;。]", clause)[-1]
    return [item.deviceType for item in inventory if item.deviceType in clause]


def parse_structured_prompt(prompt: str) -> StructuredLayoutPrompt:
    sections = _split_sections(prompt)
    inventory = _parse_inventory(sections["控件"])
    errors: List[ValidationErrorItem] = []
    for item in inventory:
        structure_count = _structure_count(sections["结构"], item.deviceType)
        if structure_count is not None and structure_count != item.count:
            errors.append(
                ValidationErrorItem(
                    path=f"结构.{item.deviceType}.count",
                    message=f"结构声明 {structure_count} 台，与控件声明 {item.count} 台冲突",
                )
            )
    if errors:
        raise StructuredPromptError(errors)
    flow_paths = _flow_paths(sections["流程"], inventory)
    return StructuredLayoutPrompt(
        inventory=inventory,
        flow=sections["流程"],
        structure=sections["结构"],
        flowPaths=flow_paths,
        parallelDevices=_parallel_devices(sections["流程"], inventory),
    )


def validate_layout_file(
    file: LayoutFile, source: Optional[StructuredLayoutPrompt] = None
) -> Tuple[List[ValidationErrorItem], List[str]]:
    errors: List[ValidationErrorItem] = []
    warnings: List[str] = []
    groups = file.layoutIntent.groups
    if not groups:
        errors.append(
            ValidationErrorItem(path="layoutIntent.groups", message="groups 不能为空")
        )
        return errors, warnings

    group_ids: set = set()
    group_node_ids: dict = {}
    node_device_types: dict = {}
    for gi, group in enumerate(groups):
        gp = f"layoutIntent.groups[{gi}]"
        if group.id in group_ids:
            errors.append(
                ValidationErrorItem(path=f"{gp}.id", message=f"group id 重复：{group.id}")
            )
        group_ids.add(group.id)

        if (group.relativeTo is None) != (group.side is None):
            errors.append(
                ValidationErrorItem(
                    path=f"{gp}.relativeTo",
                    message="relativeTo 和 side 必须同时声明",
                )
            )

        if group.count < 1:
            errors.append(
                ValidationErrorItem(
                    path=f"{gp}.count", message="group.count 必须大于等于 1"
                )
            )

        if group.count > 1 and not group.arrangement:
            warnings.append(
                f"{gp}.arrangement: 当 group.count 大于 1 时，建议声明 arrangement"
            )

        if group.arrangement == "grid":
            if (group.columns is None or group.columns < 1) and (
                group.rows is None or group.rows < 1
            ):
                errors.append(
                    ValidationErrorItem(
                        path=f"{gp}.columns",
                        message="arrangement=grid 时，columns 或 rows 至少一个 >= 1",
                    )
                )
            if group.columns is not None and group.columns < 1:
                errors.append(
                    ValidationErrorItem(
                        path=f"{gp}.columns", message="columns 必须大于等于 1"
                    )
                )
            if group.rows is not None and group.rows < 1:
                errors.append(
                    ValidationErrorItem(
                        path=f"{gp}.rows", message="rows 必须大于等于 1"
                    )
                )
            if (
                group.columns is not None
                and group.columns >= 1
                and group.rows is not None
                and group.rows >= 1
            ):
                cap = group.columns * group.rows
                if cap < group.count:
                    errors.append(
                        ValidationErrorItem(
                            path=f"{gp}.rows",
                            message=f"grid 容量不足：rows*columns={cap} < count={group.count}",
                        )
                    )
        else:
            if group.columns is not None:
                warnings.append(f"{gp}.columns: 仅在 arrangement=grid 时有效")
            if group.rows is not None:
                warnings.append(f"{gp}.rows: 仅在 arrangement=grid 时有效")
            if group.order is not None:
                warnings.append(f"{gp}.order: 仅在 arrangement=grid 时有效")

        declared: set = {group.unit.root.id}
        node_device_types[(group.id, group.unit.root.id)] = group.unit.root.deviceType
        for ai, att in enumerate(group.unit.attachments):
            ap = f"{gp}.unit.attachments[{ai}]"
            if att.relativeTo not in declared:
                errors.append(
                    ValidationErrorItem(
                        path=f"{ap}.relativeTo",
                        message=f"relativeTo 引用了不存在或尚未声明的节点：{att.relativeTo}",
                    )
                )
            if att.count is not None and att.count < 1:
                errors.append(
                    ValidationErrorItem(
                        path=f"{ap}.count", message="attachment.count 必须大于等于 1"
                    )
                )
            declared.add(att.id)
            node_device_types[(group.id, att.id)] = att.deviceType
        group_node_ids[group.id] = declared

    for gi, group in enumerate(groups):
        if group.relativeTo is not None and group.relativeTo not in group_ids:
            errors.append(
                ValidationErrorItem(
                    path=f"layoutIntent.groups[{gi}].relativeTo",
                    message=f"引用了不存在的 group：{group.relativeTo}",
                )
            )

    if not errors and _has_group_placement_cycle(groups):
        errors.append(
            ValidationErrorItem(
                path="layoutIntent.groups", message="组级相对位置存在循环引用"
            )
        )

    if source is not None:
        groups_by_device = {}
        for gi, group in enumerate(groups):
            groups_by_device.setdefault(group.unit.root.deviceType, []).append((gi, group))
        inventory_totals = {}
        for group in groups:
            inventory_totals[group.unit.root.deviceType] = (
                inventory_totals.get(group.unit.root.deviceType, 0) + group.count
            )
            for attachment in group.unit.attachments:
                inventory_totals[attachment.deviceType] = (
                    inventory_totals.get(attachment.deviceType, 0)
                    + group.count * (attachment.count or 1)
                )
        for item in source.inventory:
            total = inventory_totals.get(item.deviceType, 0)
            if not total:
                errors.append(
                    ValidationErrorItem(
                        path="layoutIntent.groups",
                        message=f"缺少控件设备：{item.deviceType}",
                    )
                )
                continue
            if total != item.count:
                matched_roots = groups_by_device.get(item.deviceType, [])
                if len(matched_roots) == 1 and not any(
                    attachment.deviceType == item.deviceType
                    for group in groups
                    for attachment in group.unit.attachments
                ):
                    path = f"layoutIntent.groups[{matched_roots[0][0]}].count"
                else:
                    path = "layoutIntent.groups"
                errors.append(
                    ValidationErrorItem(
                        path=path,
                        message=f"{item.deviceType}数量 {total} 与控件声明 {item.count} 不一致",
                    )
                )
        inventory_types = {item.deviceType for item in source.inventory}
        for gi, group in enumerate(groups):
            for node, device_type in [(group.unit.root, group.unit.root.deviceType)] + [
                (attachment, attachment.deviceType) for attachment in group.unit.attachments
            ]:
                if device_type not in inventory_types:
                    errors.append(
                        ValidationErrorItem(
                            path=f"layoutIntent.groups[{gi}].unit.{node.id}.deviceType",
                            message=f"非控件设备：{device_type}",
                        )
                    )
        device_groups = {
            group.unit.root.deviceType: (gi, group)
            for gi, group in enumerate(groups)
            if len(groups_by_device[group.unit.root.deviceType]) == 1
        }
        for device_type in source.parallelDevices:
            group_item = device_groups.get(device_type)
            if group_item is not None and group_item[1].topology != "parallel":
                errors.append(
                    ValidationErrorItem(
                        path=f"layoutIntent.groups[{group_item[0]}].topology",
                        message=f"{device_type}必须声明为 parallel",
                    )
                )
    return errors, warnings


def _has_group_placement_cycle(groups: List[LayoutGroup]) -> bool:
    parents = {
        group.id: group.relativeTo
        for group in groups
        if group.relativeTo is not None
    }
    for group_id in parents:
        seen: set = set()
        current = group_id
        while current in parents:
            if current in seen:
                return True
            seen.add(current)
            current = parents[current]
    return False


def _strip_constraints(layout_file: LayoutFile) -> LayoutFile:
    layout_file.layoutIntent.constraints = LayoutConstraints()
    return layout_file


def _load_intent_example() -> Optional[str]:
    p = _INTENT_EXAMPLE_PATH
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _build_system_prompt(vocab: List[str], example: Optional[str]) -> str:
    parts: List[str] = []
    parts.append("你是SCADA画面布局意图生成器。根据自然语言描述,生成布局意图JSON。")
    parts.append("输出格式严格为 {\"layoutIntent\":{\"groups\":[...]}}，只输出 JSON,不要解释或 markdown。")
    parts.append("数据结构：")
    parts.append("- LayoutFile: { layoutIntent: LayoutIntent }")
    parts.append("- LayoutIntent: { groups: LayoutGroup[] }")
    parts.append(
        '- LayoutGroup: { id: string, region: "left"|"right"|"center", unit: LayoutUnit, count: number, arrangement?: "vertical"|"horizontal"|"grid", gapHint?: "tight"|"normal"|"loose", columns?: number, rows?: number, order?: "row-major"|"col-major", topology?: "single"|"series"|"parallel", relativeTo?: string, side?: "top"|"right"|"bottom"|"left" }'
    )
    parts.append("- LayoutUnit: { root: DeviceNode, attachments: AttachmentNode[] }")
    parts.append('- DeviceNode: { id: string, deviceType: string, role?: "root"|"valve"|"pipe"|"meter"|"sensor"|"default" }')
    parts.append(
        '- AttachmentNode: { id: string, deviceType: string, role?: "root"|"valve"|"pipe"|"meter"|"sensor"|"default", relativeTo: string, side: "top"|"right"|"bottom"|"left", count?: number }'
    )
    parts.append("规则：")
    parts.append("1. groups 不能为空。")
    parts.append("2. 每个 group.id 必须唯一。")
    parts.append("3. group.count 必须 >= 1。")
    parts.append("4. root.id 必须存在。")
    parts.append("5. attachment.relativeTo 必须引用本组 root.id 或在它之前已声明的 attachment.id。")
    parts.append("6. attachment.count 若存在必须 >= 1。")
    parts.append("7. 当 group.count > 1 时，建议声明 arrangement。")
    parts.append("8. region 只能是 left/right/center；side 只能是 top/right/bottom/left。")
    parts.append("9. arrangement 可取 \"grid\"；当用户描述出现 M行N列/M×N/矩阵/二维 排列时，按提示词抽取到的数值填写 rows 和 columns（至少填其一且 >= 1）；若用户只说列数则只填 columns，只说行数则只填 rows。")
    parts.append("10. order 仅在 arrangement=grid 时有意义，默认 row-major。")
    parts.append("11. 同一 group 内的节点 id 必须唯一；不同 group 之间 id 可重复。")
    parts.append('12. role 可选，取值 "root"|"valve"|"pipe"|"meter"|"sensor"|"default"；root 节点可不标（自动按 root 处理）；附件节点建议标注 role 以确定尺寸约束，未标则按 deviceType 关键词推断，仍无法识别时按 default。')
    parts.append("13. user message 中 inventory 是设备和数量的唯一真值；设备可作为 root 或 attachment，所有 group.count 和 attachment.count 展开后的总数必须与 inventory 一致。")
    parts.append("14. 主流程从左到右排列时，首组作为锚点；每个后续 group 必须通过 relativeTo 引用前一组并声明 side=right，即使它们都属于 center 区域。不要让多个流程组仅因 region=center 而共用一列。")
    if vocab:
        parts.append("可用设备类型（deviceType 必须从下列选取，不要生造）：")
        parts.append("、".join(vocab))
    else:
        parts.append("未提供设备类型词表，deviceType 可根据用户描述合理命名。")
    if example:
        parts.append("示例（仅参考结构，不要照搬内容）：")
        parts.append(example)
    parts.append("只输出 JSON。")
    return "\n".join(parts)


def _load_vocab(rows: List[dict]) -> List[str]:
    seen: set = set()
    vocab: List[str] = []
    for r in rows:
        name = r.get("displayName")
        if not name or name in seen:
            continue
        seen.add(name)
        vocab.append(name)
    return vocab


def _build_user_prompt(source: StructuredLayoutPrompt) -> str:
    return json.dumps(
        {
            "inventory": [
                {"deviceType": item.deviceType, "count": item.count}
                for item in source.inventory
            ],
            "flow": source.flow,
            "structure": source.structure,
        },
        ensure_ascii=False,
    )


async def generate_intent(
    prompt: str,
    materials: List[dict],
    client=None,
    model=None,
    model_caller=None,
) -> LayoutFile:
    source = parse_structured_prompt(prompt)
    client = client or default_client
    model = model or _GENERATE_GIRD_MODEL
    model_caller = model_caller or _call_intent_model

    vocab = _load_vocab(materials)
    if not vocab:
        raise ValueError("query_results 表为空")
    errors = [
        ValidationErrorItem(path=f"控件.{item.deviceType}", message="query_results 缺少控件素材")
        for item in source.inventory
        if item.deviceType not in vocab
    ]
    if errors:
        raise StructuredPromptError(errors)
    section_text = "控件：" + "、".join(f"{item.count}台{item.deviceType}" for item in source.inventory) + "\n流程：" + source.flow + "\n结构：" + source.structure
    cache_key = (_INTENT_CACHE_VERSION, section_text, tuple(sorted(vocab)), model)
    cached = _INTENT_CACHE.get(cache_key)
    if cached is not None:
        return cached.model_copy(deep=True)
    from model.layout_intent_rules import build_rule_layout
    rule = build_rule_layout(source)
    if rule.data is not None:
        layout_file = LayoutFile.model_validate(rule.data)
        errors, _ = validate_layout_file(layout_file, source)
        if not errors:
            _strip_constraints(layout_file)
            _INTENT_CACHE[cache_key] = layout_file.model_copy(deep=True)
            return layout_file

    example = _load_intent_example()
    system_prompt = _build_system_prompt(vocab, example)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_prompt(source)},
    ]

    async def call_and_validate(selected_model, **kwargs):
        try:
            resp = await model_caller(client, selected_model, messages, **kwargs)
        except IntentModelTimeoutError:
            raise
        except Exception as exc:
            logger.exception("LLM 调用失败")
            raise IntentModelUnavailableError("布局模型不可用") from exc

        text = _llm_text(resp)
        data = _parse_json_lenient(text)
        if data is None:
            raise IntentModelOutputError(
                f"LLM 输出无法解析为 JSON：{(text or '')[:200]}", text
            )
        try:
            layout_file = LayoutFile.model_validate(data)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in exc.errors()
            )
            raise IntentModelOutputError(
                f"布局模型输出不符合格式：{details}", text
            ) from exc

        errors, warnings = validate_layout_file(layout_file, source)
        if errors:
            details = "; ".join(f"{item.path}: {item.message}" for item in errors)
            raise IntentModelOutputError(
                f"布局模型输出未通过语义校验：{details}", text
            )
        for warning in warnings:
            logger.warning(warning)
        _strip_constraints(layout_file)
        return layout_file

    layout_file = await call_and_validate(
        model,
        response_format={"type": "json_object"},
        stream=False,
        extra_body={"thinking": {"type": "disabled"}},
    )
    _INTENT_CACHE[cache_key] = layout_file.model_copy(deep=True)
    return layout_file



