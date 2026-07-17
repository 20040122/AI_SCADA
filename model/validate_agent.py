from __future__ import annotations

import json
import logging


from model.canva_agent import _client, _MODEL, _call_llm

logger = logging.getLogger(__name__)

_CATEGORY_PROMPTS = {
    "control": (
        "你是 SCADA 控件资源校验器。校验输入的 JSON 是否符合控件索引规则。\n\n"
        "结构要求：\n"
        "- displayName: string（必填，控件显示名称）\n"
        "- image: string（必填，资源路径，应在 symbols/ 或 assets/ 下）\n"
        "- width: number | null（必填，控件宽度）\n"
        "- height: number | null（必填，控件高度）\n"
        "- boundExtend: number（可选，边界扩展像素值）\n"
        "- 不允许额外属性\n\n"
        "派生规则：\n"
        "1. image 路径应以 symbols/ 或 assets/ 开头\n"
        "2. width 和 height 为 null 时应有合理理由（如占位符）\n"
        "3. boundExtend 若存在应 >= 0\n"
        "4. displayName 不应为空字符串\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "canvas": (
        "你是 SCADA 画布校验器。校验输入的 JSON 是否符合画布结构规则。\n\n"
        "结构要求：\n"
        "- v: string（必填，版本号）\n"
        "- p: object（必填，含 layers 数组、autoAdjustIndex bool、hierarchicalRendering bool）\n"
        "  - layers[].name: string, visible: bool, selectable: bool, movable: bool, editable: bool\n"
        "- a: object（必填，含 width、height、fitContent、rectSelectable、pannable、zoomable，均为 bool 或 number）\n"
        "- d: array（必填，数据元素数组）\n"
        "- contentRect: object（必填，含 x、y、width、height number）\n\n"
        "派生规则：\n"
        "1. contentRect 应能包含所有 d 元素的坐标范围\n"
        "2. d 数组元素应至少包含 c（类型）和 p（属性）字段\n"
        "3. layers 至少有一个图层\n"
        "4. a.width 和 a.height 应 > 0\n"
        "5. contentRect.width 和 height 应 > 0\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "layout": (
        "你是 SCADA 布局校验器。校验输入的 JSON 是否符合布局拓扑规则。\n\n"
        "结构要求：\n"
        "- layoutIntent: object（必填）\n"
        "  - groups: array（必填，至少一个 LayoutGroup）\n"
        "    - id: string, region: \"left\"|\"right\"|\"center\"\n"
        "    - unit: { root: DeviceNode, attachments: AttachmentNode[] }\n"
        "    - count: number >= 1\n"
        "    - arrangement?: \"vertical\"|\"horizontal\"|\"grid\"\n"
        "    - gapHint?: \"tight\"|\"normal\"|\"loose\"\n"
        "    - columns?: number, rows?: number, order?: \"row-major\"|\"col-major\"\n"
        "  - connections?: array（可选）\n"
        "    - id: string, source: {group, node, port?}, target: {group, node, port?}\n"
        "- DeviceNode: {id: string, deviceType: string, role?: \"root\"|\"valve\"|\"pipe\"|\"meter\"|\"sensor\"|\"default\"}\n"
        "- AttachmentNode extends DeviceNode 增加 relativeTo: string, side: \"top\"|\"right\"|\"bottom\"|\"left\", count?: number\n\n"
        "派生规则：\n"
        "1. groups 不能为空\n"
        "2. group.id 必须唯一\n"
        "3. group.count >= 1\n"
        "4. 当 arrangement=grid 时，columns 或 rows 至少一个 >= 1，且 columns*rows >= count\n"
        "5. attachment.relativeTo 必须引用本组已声明的节点\n"
        "6. 各场景的角色尺寸约束：root(120-180x120-260)、pipe(80-180x20-50)、valve(40-80x40-80)、meter(50-100x50-100)、sensor(50-110x40-90)\n"
        "7. connection.id 必须唯一，source/target.group 必须存在，source/target.node 必须在该 group 内\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "binding": (
        "你是 SCADA 数据绑点校验器。校验输入的 JSON 是否符合绑点规则。\n\n"
        "结构要求：\n"
        "- controlId: string（必填，控件 ID）\n"
        "- property: string（必填，枚举值：status|value|visible|color|text|enabled）\n"
        "- variable: string（必填，PLC 变量名）\n"
        "- dataType: string（可选，枚举值：bool|int16|int32|float|string）\n"
        "- registerAddress: string（可选，寄存器地址）\n"
        "- 不允许额外属性\n\n"
        "派生规则：\n"
        "1. controlId 不应为空\n"
        "2. variable 不应为空\n"
        "3. 若属性为 visible 或 enabled，建议 dataType 为 bool\n"
        "4. 若属性为 status 或 value，建议 dataType 为数值类型（int16/int32/float）\n"
        "5. registerAddress 若存在，格式应为标准 PLC 寄存器地址（如 Q0.0、I0.1、DB1.DBX0.0）\n"
        "6. 如果有多个绑点，controlId 应唯一（每个控件只绑一次同一个属性）\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
}


class ValidateAgent:
    def __init__(self, client=None, model=None):
        self._client = client if client is not None else _client
        self._model = model if model is not None else _MODEL

    async def validate(self, category: str, json_data: dict) -> dict:
        all_errors: list[dict] = []
        all_warnings: list[dict] = []

        try:
            ai_result = await self._ai_validate(category, json_data)
        except Exception:
            logger.exception("AI validation failed")
            ai_result = {"valid": False, "summary": "AI 校验失败", "errors": [], "warnings": []}

        all_errors.extend(ai_result.get("errors", []))
        all_warnings.extend(ai_result.get("warnings", []))

        valid = len(all_errors) == 0
        return {
            "valid": valid,
            "summary": ai_result.get("summary", ""),
            "errors": all_errors,
            "warnings": all_warnings,
        }

    async def _ai_validate(self, category: str, json_data: dict) -> dict:
        system_prompt = _CATEGORY_PROMPTS.get(category)
        if not system_prompt:
            return {"valid": False, "summary": "未知类别: " + category, "errors": [], "warnings": []}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(json_data, ensure_ascii=False, indent=2)},
        ]

        response = await _call_llm(
            self._client,
            self._model,
            messages,
            response_format={"type": "json_object"},
        )

        text = response.choices[0].message.content or ""
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI 输出非 JSON: %s", text[:200])
            return {"valid": False, "summary": "AI 响应解析失败", "errors": [], "warnings": []}

        return {
            "valid": result.get("valid", False),
            "summary": result.get("summary", ""),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }