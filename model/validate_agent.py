from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from model.llm_client import call_llm, default_client, default_model

logger = logging.getLogger(__name__)

_MAX_INPUT_BYTES = 64 * 1024
_AI_TIMEOUT_SECONDS = 10.0

_CATEGORY_PROMPTS = {
    "control": (
        "你是 SCADA 控件资源校验辅助器。结构规则由确定性 Schema 校验负责，你只需给出辅助性发现。\n\n"
        "真实数据契约（单个控件记录）：\n"
        "- displayName: string（必填，控件显示名称）\n"
        "- image: string（必填，资源路径，应在 symbols/ 或 assets/ 下）\n"
        "- width: number | null（必填）\n"
        "- height: number | null（必填）\n"
        "- boundExtend: number | null（可选，>= 0）\n\n"
        "请仅返回 findings（辅助信息），例如命名合理性、资源路径可能存在性的提示。不要复述确定性规则，不要计算 valid。\n\n"
        '输出 JSON：{"errors":[],"warnings":[{"path":"","message":"","error_type":"ai"}]}'
    ),
    "canvas": (
        "你是 SCADA 画布校验辅助器。结构规则由确定性 Schema 校验负责，你只需给出辅助性发现。\n\n"
        "真实数据契约：\n"
        "- v: string, p: object（layers/autoAdjustIndex/hierarchicalRendering）, a: object（width/height/fitContent/rectSelectable/pannable/zoomable）\n"
        "- d: array（元素含 c 与 p）, contentRect: object（x/y/width/height）\n"
        "- 画布保留 DaoSCADA 未声明的扩展字段。\n\n"
        "请仅返回辅助性发现，不要复述确定性规则，不要计算 valid。\n\n"
        '输出 JSON：{"errors":[],"warnings":[{"path":"","message":"","error_type":"ai"}]}'
    ),
    "layout": (
        "你是 SCADA 布局校验辅助器。结构规则由 LayoutFile/Pydantic 与确定性语义规则负责，你只需给出辅助性发现。\n\n"
        "真实数据契约（layoutIntent）：groups 数组，每组含 id/region/unit(root+attachments)/count/arrangement/gapHint/topology/relativeTo/side 等。\n"
        "注意：不存在 connections 字段，也没有可仅凭 JSON 判断的通用尺寸规则。\n\n"
        "请仅返回辅助性发现，不要复述确定性规则，不要计算 valid。\n\n"
        '输出 JSON：{"errors":[],"warnings":[{"path":"","message":"","error_type":"ai"}]}'
    ),
    "binding": (
        "你是 SCADA 数据绑点校验辅助器。结构规则由确定性 Schema 校验负责，你只需给出辅助性发现。\n\n"
        "真实数据契约：\n"
        "- 独立对象为 {\"panel.list\":[{label, bind}]}；完整画布为 DaoSCADA canvas，遍历节点 a.panel.list。\n"
        "- bind 含 type=designer、path(projectId#deviceId#propertyId)、key(deviceId#propertyId)、label、proj/dev/param(id/name/unit/writable/dataType/dataTypeDesc)。\n\n"
        "请仅返回辅助性发现，不要复述确定性规则，不要计算 valid。\n\n"
        '输出 JSON：{"errors":[],"warnings":[{"path":"","message":"","error_type":"ai"}]}'
    ),
}


class ValidateAgent:
    def __init__(self, client=None, model=None):
        self._client = client if client is not None else default_client
        self._model = model if model is not None else default_model

    async def validate(self, category: str, json_data: dict) -> dict:
        findings_warnings: list[dict] = []

        if not self._model:
            findings_warnings.append(
                {"path": "", "message": "未配置模型，跳过 AI 辅助校验", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        try:
            raw = json.dumps(json_data, ensure_ascii=False)
        except (TypeError, ValueError):
            raw = ""
        if len(raw.encode("utf-8")) > _MAX_INPUT_BYTES:
            findings_warnings.append(
                {"path": "", "message": "JSON 超过 64 KiB，跳过 AI 辅助校验", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        system_prompt = _CATEGORY_PROMPTS.get(category)
        if not system_prompt:
            findings_warnings.append(
                {"path": "", "message": f"未知类别: {category}", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw},
        ]

        try:
            response = await asyncio.wait_for(
                call_llm(
                    self._client,
                    self._model,
                    messages,
                    response_format={"type": "json_object"},
                ),
                timeout=_AI_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("AI 辅助校验超时（10 秒）")
            return {"errors": [], "warnings": findings_warnings}
        except Exception as exc:
            logger.warning("AI 辅助校验失败: %s", exc)
            findings_warnings.append(
                {"path": "", "message": f"AI 辅助校验失败: {exc}", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        text = ""
        try:
            text = response.choices[0].message.content or ""
        except Exception:
            text = ""

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI 输出非 JSON: %s", text[:200])
            findings_warnings.append(
                {"path": "", "message": "AI 响应解析失败", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        if not isinstance(result, dict):
            findings_warnings.append(
                {"path": "", "message": "AI 响应结构无效", "error_type": "ai"}
            )
            return {"errors": [], "warnings": findings_warnings}

        findings_warnings.extend(_normalize_findings(result.get("errors")))
        findings_warnings.extend(_normalize_findings(result.get("warnings")))
        return {"errors": [], "warnings": findings_warnings}


def _normalize_findings(items: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict):
            out.append(
                {
                    "path": item.get("path", ""),
                    "message": item.get("message", ""),
                    "error_type": item.get("error_type", "ai"),
                }
            )
    return out
