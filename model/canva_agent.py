from __future__ import annotations
import asyncio
import json
import logging
import math
import os
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pathlib import Path
import jsonschema
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
from data.sqlite.material_db import MaterialDB
logger = logging.getLogger(__name__)
load_dotenv(".env.local")

_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=60.0,
)
_MODEL = os.environ.get("DEEPSEEK_MODEL")

_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    reraise=True,
)
async def _call_llm(client, model, messages, **kwargs):
    return await client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )


_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "schema" / "canvas_schema.json"
_SCHEMA_CACHE: dict | None = None



EXTRACT_CONTROLS_PROMPT = """\
SCADA 控件检索器。从用户描述中提取需要的控件名称和数量。
给定可用控件列表:
{controls_list}
要求：
1. 只能从上面的可用控件列表中选取名称，不得编造。
2. name 必须与列表中的 displayName 完全匹配。
3. count 是用户需要的数量，未明确数量时默认为1。
4. 如果用户描述中没有提到任何控件，返回空数组。
只输出 JSON,不要解释:
{{"controls": [{{"name": "", "count": 1}}]}}
"""

REFINE_PROMPT = """\
SCADA 画布布局微调器。你只能调整节点的 x 和 y 坐标。
画布尺寸：
width={canvas_width}, height={canvas_height}
输入节点 JSON:
{layout_json}
硬性约束：
1. 不得新增、删除、重命名节点。
2. 不得修改 displayName、node_id、image、width、height。
3. 所有节点必须完整位于画布内。
4. 尽量避免重叠。
5. 各控件保持在原有大致区域（左上/上/右上/左/中/右/左下/下/右下），微调时避免跨区域大幅移动。
6. x、y 必须是整数。
只输出 JSON,不要解释:
{{"nodes":[{{"node_id":"","displayName":"","image":"","width":0,"height":0,"x":0,"y":0}}]}}
"""


UNIFIED_LAYOUT_PROMPT = """\
SCADA 组态语义分析器。根据用户描述，同时完成以下三项任务：

可用控件：
{controls_info}

画布尺寸：{canvas_width}x{canvas_height}
方向选择：width>=height时推荐LR，否则推荐TB。

任务1 - placement_hints：仅当用户明确表达了位置意图时才输出（如"右上角"、"靠左"、"放在中间"等）。
  其中 target 必须使用上面列出的控件标识符（第一列的完整名称，含后缀 _1, _2 等）。
任务2 - flow_dsl：生成 Mermaid flowchart DSL 表示控件间流程/控制关系。
  - 节点格式 id[label]，id 和 label 必须是上面列出的完整控件标识符（含后缀 _1, _2 等）
  - 主流程 -->，控制/调节关系 -.->  虚线箭头
  - 用 direction LR 或 TB 声明方向
任务3 - placements：为每个控件分配一个 region，兜底布局需要。
  其中 target 必须使用上面列出的控件标识符（第一列的完整名称，含后缀 _1, _2 等）。
  可选 region 枚举：
  - left, right, top, bottom, center
  - left_top, right_top, left_bottom, right_bottom

规则：
1. 只能使用上面列出的控件标识符，不得编造
2. flow_dsl 中名称必须与可用控件列表完全一致
3. placement_hints 仅当用户明确表达了位置意图时才输出
4. 允许 flow_dsl 为空字符串（无法推导流程时）

只输出 JSON，不要解释：
{{
  "placement_hints": [{{"target": "", "region": "left"}}],
  "flow_dsl": "flowchart LR\\n    A[label1] --> B[label2]",
  "placements": [{{"target": "", "region": "left"}}]
}}
"""


VALID_REGIONS = {
    "left", "right", "top", "bottom", "center",
    "left_top", "right_top", "left_bottom", "right_bottom",
}
REGION_SYNONYMS = {
    "左": "left",
    "左边": "left",
    "左侧": "left",
    "左面": "left",
    "靠左": "left",
    "右": "right",
    "右边": "right",
    "右侧": "right",
    "右面": "right",
    "靠右": "right",
    "上": "top",
    "上面": "top",
    "上方": "top",
    "顶部": "top",
    "下": "bottom",
    "下面": "bottom",
    "下方": "bottom",
    "底部": "bottom",
    "中间": "center",
    "居中": "center",
    "左上": "left_top",
    "左上角": "left_top",
    "右上": "right_top",
    "右上角": "right_top",
    "左下": "left_bottom",
    "左下角": "left_bottom",
    "右下": "right_bottom",
    "右下角": "right_bottom",
}

REGION_ANCHORS = {
    "left_top": (0.15, 0.12),
    "top": (0.50, 0.12),
    "right_top": (0.85, 0.12),
    "left": (0.15, 0.50),
    "center": (0.50, 0.50),
    "right": (0.85, 0.50),
    "left_bottom": (0.15, 0.88),
    "bottom": (0.50, 0.88),
    "right_bottom": (0.85, 0.88),
}


@dataclass
class GraphNode:
    id: str
    label: str


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    type: str


@dataclass
class FlowGraph:
    direction: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@dataclass
class PlacementHint:
    target: str
    region: str


@dataclass
class LayoutConstraint:
    constraint_type: str
    priority: str = "soft"
    target_ids: list[str] = field(default_factory=list)
    anchor_ids: list[str] = field(default_factory=list)
    source: str = "unknown"
    source_span: str = ""
    confidence: float = 0.5
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "constraint_type": self.constraint_type,
            "priority": self.priority,
            "target_ids": self.target_ids,
            "anchor_ids": self.anchor_ids,
            "source": self.source,
            "source_span": self.source_span,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    def to_debug_line(self) -> str:
        meta_str = ", ".join(f"{k}={v}" for k, v in self.metadata.items()) if self.metadata else ""
        anchors = f" <- {self.anchor_ids}" if self.anchor_ids else ""
        return (
            f"[{self.source}:{self.confidence:.1f}] {self.constraint_type}({self.priority}) "
            f"{self.target_ids}{anchors}"
            + (f" {{{meta_str}}}" if meta_str else "")
            + (f' "{self.source_span}"' if self.source_span else "")
        )


@dataclass
class LayoutRequirement:
    canvas_width: int
    canvas_height: int
    controls: list[dict]
    placements: list[PlacementHint]
    placement_hints: list[PlacementHint]


@dataclass
class LayoutIntents:
    hints: list[PlacementHint]
    flow_dsl: str
    requirement: LayoutRequirement | None = None
    constraints: list[LayoutConstraint] = field(default_factory=list)


@dataclass
class LayoutZone:
    name: str
    x: float
    y: float
    width: float
    height: float
    controls: list[str]


@dataclass
class LayoutSkeleton:
    zones: list[LayoutZone]


@dataclass
class QualityIssue:
    severity: str
    issue_type: str
    message: str
    controls: list[str]


@dataclass
class CanvasResult:
    json_data: dict
    content_rect: dict
    quality_issues: list[QualityIssue]
    skeleton: LayoutSkeleton
    missing_controls: list[str] = field(default_factory=list)


def _normalize_region(region: str) -> str:
    if not region:
        return ""
    value = region.strip().lower()
    if value in VALID_REGIONS:
        return value
    return REGION_SYNONYMS.get(region.strip(), "")


def _extract_explicit_region_mentions(query: str, controls: list[dict]) -> list[PlacementHint]:
    """精确解析紧凑中文位置表达式，如 '水泵在左表格在右'。

    优先匹配 {控件名}在/放在/位于/靠{方位词} 等明确语法模式，
    再尝试控件名后直接跟方位词。返回的 hint 保证同一控件只选择
    离控件名最近、语法关系最明确的方位词。
    """
    hints: list[PlacementHint] = []
    position_connectors = ["放在", "在", "位于", "放", "靠"]

    for ctrl in controls:
        name = ctrl["displayName"]
        nid = ctrl["node_id"]
        idx = query.find(name)
        matched = name
        if idx < 0:
            idx = query.find(nid)
            matched = nid
        if idx < 0:
            continue

        after_name = idx + len(matched)
        remaining = query[after_name:]
        region = ""

        for conn in position_connectors:
            if remaining.startswith(conn):
                after_conn = remaining[len(conn):]
                for keyword in sorted(REGION_SYNONYMS, key=len, reverse=True):
                    if after_conn.startswith(keyword):
                        region = REGION_SYNONYMS[keyword]
                        break
                if region:
                    break

        if not region:
            for keyword in sorted(REGION_SYNONYMS, key=len, reverse=True):
                if remaining.startswith(keyword):
                    region = REGION_SYNONYMS[keyword]
                    break

        if region:
            hints.append(PlacementHint(target=matched, region=region))

    return hints


def _extract_placement_hints_from_query(query: str, controls: list[dict]) -> list[PlacementHint]:
    precise_hints = _extract_explicit_region_mentions(query, controls)
    precise_targets = {h.target for h in precise_hints}

    hints: list[PlacementHint] = list(precise_hints)
    seen: set[str] = set(precise_targets)
    for ctrl in controls:
        name = ctrl["displayName"]
        nid = ctrl["node_id"]
        if name in seen or nid in seen:
            continue
        idx = query.find(name)
        matched = name
        if idx < 0:
            idx = query.find(nid)
            matched = nid
        if idx < 0:
            continue
        window_start = max(0, idx - 8)
        window_end = min(len(query), idx + len(matched) + 8)
        context = query[window_start:window_end]
        region = ""
        for keyword in sorted(REGION_SYNONYMS, key=len, reverse=True):
            if keyword in context:
                region = REGION_SYNONYMS[keyword]
                break
        if not region or matched in seen:
            continue
        hints.append(PlacementHint(target=matched, region=region))
        seen.add(matched)
    return hints


_RELATIVE_DIR_MAP = {
    "左": "left", "左边": "left", "左侧": "left", "左面": "left",
    "右": "right", "右边": "right", "右侧": "right", "右面": "right",
    "上": "above", "上方": "above", "上面": "above", "顶部": "above",
    "下": "below", "下方": "below", "下面": "below", "底部": "below",
}
_ALIGN_MAP = {
    "左对齐": "left", "右对齐": "right",
    "顶部对齐": "top", "上对齐": "top",
    "底部对齐": "bottom", "下对齐": "bottom",
    "中心对齐": "center_h", "居中对齐": "center_h",
}
_SPACING_WORDS = {"紧凑": "compact", "紧密": "compact", "均匀": "uniform", "分散": "far"}
_GROUP_WORDS = {"附着": "attached", "跟随": "attached", "贴靠": "attached",
                 "紧贴": "attached", "放在.*右上角": "attached", "放在.*左上角": "attached",
                 "放在.*右下角": "attached", "放在.*左下角": "attached"}
_ORDER_WORDS = {"从左到右": "LR", "横向": "LR", "横排": "LR", "水平": "LR",
                "从上到下": "TB", "纵向": "TB", "竖排": "TB", "垂直": "TB",
                "先后": "sequence"}


def _extract_layout_constraints_from_query(
    query: str, controls: list[dict]
) -> list[LayoutConstraint]:
    all_names = {c["displayName"] for c in controls} | {c["node_id"] for c in controls}
    constraints: list[LayoutConstraint] = []

    precise_hints = _extract_explicit_region_mentions(query, controls)
    precise_targets = {h.target for h in precise_hints}
    for h in precise_hints:
        constraints.append(LayoutConstraint(
            constraint_type="absolute_region",
            priority="soft",
            target_ids=[h.target],
            source="query",
            source_span=query.strip(),
            confidence=0.7,
            metadata={"region": h.region},
        ))

    clauses = re.split(r"[。，；、；\n]+", query)
    clauses = [c.strip() for c in clauses if c.strip()]

    for clause in clauses:
        _try_absolute_region(clause, all_names, constraints, precise_targets)
        _try_relative_position(clause, all_names, constraints)
        _try_alignment(clause, all_names, constraints)
        _try_spacing(clause, all_names, constraints)
        _try_grouping(clause, all_names, constraints)
        _try_ordering(clause, all_names, constraints)

    constraints = _dedupe_constraints(constraints)
    return constraints


def _fuzzy_resolve(name: str, all_names: set[str]) -> str | None:
    if name in all_names:
        return name
    return _fuzzy_match_label(name, all_names)


def _dedupe_constraints(constraints: list[LayoutConstraint]) -> list[LayoutConstraint]:
    seen: set[tuple] = set()
    result: list[LayoutConstraint] = []
    priority_order = {"dsl": 0, "query": 1, "llm": 2, "fallback_rule": 3}
    for c in sorted(constraints, key=lambda x: priority_order.get(x.source, 9)):
        key = (c.constraint_type, tuple(sorted(c.target_ids)), tuple(sorted(c.anchor_ids)))
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


def _try_absolute_region(clause: str, all_names: set[str], out: list[LayoutConstraint],
                         skip_names: Optional[set[str]] = None) -> None:
    if skip_names is None:
        skip_names = set()
    for name in all_names:
        if name in skip_names:
            continue
        idx = clause.find(name)
        if idx < 0:
            continue
        window_start = max(0, idx - 8)
        window_end = min(len(clause), idx + len(name) + 8)
        context = clause[window_start:window_end]
        for keyword in sorted(REGION_SYNONYMS, key=len, reverse=True):
            if keyword in context:
                region = REGION_SYNONYMS[keyword]
                out.append(LayoutConstraint(
                    constraint_type="absolute_region",
                    priority="soft",
                    target_ids=[name],
                    source="query",
                    source_span=clause.strip(),
                    confidence=0.7,
                    metadata={"region": region},
                ))
                break


def _try_relative_position(clause: str, all_names: set[str], out: list[LayoutConstraint]) -> None:
    names_list = sorted(all_names, key=len, reverse=True)
    for a_name in names_list:
        for b_name in names_list:
            if a_name == b_name:
                continue
            for kw, direction in _RELATIVE_DIR_MAP.items():
                patterns = [
                    rf"{re.escape(a_name)}[在处于放].*?{re.escape(b_name)}[的]?{re.escape(kw)}",
                    rf"{re.escape(a_name)}.*?{re.escape(kw)}[的]?.*?{re.escape(b_name)}",
                    rf"{re.escape(a_name)}(?:紧贴|贴近|紧靠|紧挨|靠近|放在){re.escape(b_name)}{re.escape(kw)}",
                ]
                for pat in patterns:
                    if re.search(pat, clause):
                        spacing = "tight" if re.search(r"紧贴|贴近|紧靠|紧挨", clause) else "normal"
                        out.append(LayoutConstraint(
                            constraint_type="relative_position",
                            priority="soft",
                            target_ids=[a_name],
                            anchor_ids=[b_name],
                            source="query",
                            source_span=clause.strip(),
                            confidence=0.6,
                            metadata={"direction": direction, "spacing": spacing},
                        ))
                        return


def _try_alignment(clause: str, all_names: set[str], out: list[LayoutConstraint]) -> None:
    for kw, align in _ALIGN_MAP.items():
        m = re.search(rf"(.+?)[和与及,.]+?\s*(.+?)\s*{re.escape(kw)}", clause)
        if not m:
            m = re.search(rf"(.+?)\s*{re.escape(kw)}\s*[于在]?\s*(.+)", clause)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            resolved_a = _fuzzy_resolve(a, all_names)
            resolved_b = _fuzzy_resolve(b, all_names)
            if resolved_a and resolved_b:
                out.append(LayoutConstraint(
                    constraint_type="alignment",
                    priority="soft",
                    target_ids=[resolved_a],
                    anchor_ids=[resolved_b],
                    source="query",
                    source_span=clause.strip(),
                    confidence=0.6,
                    metadata={"align": align},
                ))


def _try_spacing(clause: str, all_names: set[str], out: list[LayoutConstraint]) -> None:
    for kw, spacing_val in _SPACING_WORDS.items():
        if kw in clause:
            px_match = re.search(r"(\d+)\s*px", clause)
            out.append(LayoutConstraint(
                constraint_type="spacing",
                priority="soft",
                target_ids=[],
                source="query",
                source_span=clause.strip(),
                confidence=0.4,
                metadata={"spacing": int(px_match.group(1)) if px_match else spacing_val},
            ))
            return


def _try_grouping(clause: str, all_names: set[str], out: list[LayoutConstraint]) -> None:
    for pattern, group_type in _GROUP_WORDS.items():
        for a_name in sorted(all_names, key=len, reverse=True):
            for b_name in sorted(all_names, key=len, reverse=True):
                if a_name == b_name:
                    continue
                full = rf"{re.escape(a_name)}\s*{pattern}\s*{re.escape(b_name)}"
                if re.search(full, clause):
                    out.append(LayoutConstraint(
                        constraint_type="grouping",
                        priority="soft",
                        target_ids=[a_name],
                        anchor_ids=[b_name],
                        source="query",
                        source_span=clause.strip(),
                        confidence=0.5,
                        metadata={"group_type": group_type},
                    ))
                    return
    if "一组" in clause or "同组" in clause or "聚合" in clause:
        found = [n for n in all_names if n in clause]
        if len(found) >= 2:
            out.append(LayoutConstraint(
                constraint_type="grouping",
                priority="soft",
                target_ids=found,
                source="query",
                source_span=clause.strip(),
                confidence=0.5,
                metadata={"group_type": "cluster"},
            ))


def _try_ordering(clause: str, all_names: set[str], out: list[LayoutConstraint]) -> None:
    for kw, direction in _ORDER_WORDS.items():
        if kw in clause:
            found = [n for n in all_names if n in clause]
            out.append(LayoutConstraint(
                constraint_type="ordering",
                priority="soft",
                target_ids=found if found else [],
                source="query",
                source_span=clause.strip(),
                confidence=0.5,
                metadata={"direction": direction, "axis": "primary"},
            ))
            return


def _expand_hints_to_node_ids(hints: list[PlacementHint], controls: list[dict]) -> list[PlacementHint]:
    dn_to_ids: dict[str, list[str]] = {}
    for c in controls:
        dn = c["displayName"]
        nid = c["node_id"]
        dn_to_ids.setdefault(dn, []).append(nid)

    expanded: list[PlacementHint] = []
    for hint in hints:
        ids = dn_to_ids.get(hint.target, [hint.target])
        for nid in ids:
            expanded.append(PlacementHint(target=nid, region=hint.region))
    return expanded


def _hint_to_constraint(hint: PlacementHint, source: str, confidence: float) -> LayoutConstraint:
    return LayoutConstraint(
        constraint_type="absolute_region",
        priority="soft",
        target_ids=[hint.target],
        source=source,
        confidence=confidence,
        metadata={"region": hint.region},
    )


def _batch_hints_to_constraints(
    hints: list[PlacementHint], source: str, confidence: float
) -> list[LayoutConstraint]:
    return [_hint_to_constraint(h, source, confidence) for h in hints]


def _constraint_to_hint(c: LayoutConstraint) -> PlacementHint | None:
    if c.constraint_type == "absolute_region" and c.target_ids:
        region = c.metadata.get("region", "")
        if region:
            return PlacementHint(target=c.target_ids[0], region=region)
    return None


def _sanitize_placement_hints(hints: list[dict], controls: list[dict]) -> list[PlacementHint]:
    all_names = {c["displayName"] for c in controls}
    all_node_ids = {c["node_id"] for c in controls}
    valid_targets = all_names | all_node_ids
    clean: list[PlacementHint] = []
    seen: set[str] = set()
    for hint in hints:
        target = hint.get("target")
        region = _normalize_region(hint.get("region", ""))
        if target not in valid_targets or not region or target in seen:
            continue
        clean.append(PlacementHint(target=target, region=region))
        seen.add(target)
    return clean


def _normalize_layout_constraints(
    constraints: list[LayoutConstraint], controls: list[dict]
) -> tuple[list[LayoutConstraint], list[PlacementHint]]:
    all_names = {c["displayName"] for c in controls}
    all_node_ids = {c["node_id"] for c in controls}
    name_to_node_ids: dict[str, list[str]] = {}
    for c in controls:
        dn = c["displayName"]
        nid = c["node_id"]
        name_to_node_ids.setdefault(dn, []).append(nid)

    normalized: list[LayoutConstraint] = []
    seen_target_sets: set[tuple] = set()

    def _resolve_name(name: str) -> str | None:
        if name in all_node_ids:
            return name
        if name in all_names:
            return name
        fuzzy_node = _fuzzy_match_label(name, all_node_ids)
        if fuzzy_node:
            return fuzzy_node
        fuzzy = _fuzzy_match_label(name, all_names)
        return fuzzy

    for c in constraints:
        resolved_targets: list[str] = []
        for tid in c.target_ids:
            resolved = _resolve_name(tid)
            if resolved:
                resolved_targets.append(resolved)
            elif c.priority == "hard":
                resolved_targets.append(tid)

        resolved_anchors: list[str] = []
        for aid in c.anchor_ids:
            resolved = _resolve_name(aid)
            if resolved:
                resolved_anchors.append(resolved)
            elif c.priority == "hard":
                resolved_anchors.append(aid)

        if not resolved_targets:
            if c.constraint_type in ("ordering", "spacing"):
                normalized.append(c)
            continue

        if c.constraint_type == "absolute_region":
            region = _normalize_region(c.metadata.get("region", ""))
            if not region:
                if c.priority == "hard":
                    region = c.metadata.get("region", "")
                else:
                    continue
            c.metadata["region"] = region

        for tid in resolved_targets[:]:
            expanded_ids = name_to_node_ids.get(tid, [tid])
            if len(expanded_ids) > 1:
                resolved_targets.remove(tid)
                resolved_targets.extend(expanded_ids)

        expanded_anchors: list[str] = []
        for aid in resolved_anchors:
            expanded_anchors.extend(name_to_node_ids.get(aid, [aid]))

        c.target_ids = resolved_targets
        c.anchor_ids = expanded_anchors

        key = (c.constraint_type, tuple(sorted(c.target_ids)), tuple(sorted(c.anchor_ids)))
        if key in seen_target_sets:
            continue
        seen_target_sets.add(key)
        normalized.append(c)

    conflict_merged = _merge_conflicting_constraints(normalized)

    hints: list[PlacementHint] = []
    seen_hint_targets: set[str] = set()
    for c in conflict_merged:
        hint = _constraint_to_hint(c)
        if hint and hint.target not in seen_hint_targets:
            hints.append(hint)
            seen_hint_targets.add(hint.target)

    return conflict_merged, hints


def _merge_conflicting_constraints(
    constraints: list[LayoutConstraint],
) -> list[LayoutConstraint]:
    priority_order = {"dsl": 0, "query": 1, "llm": 2, "fallback_rule": 3}
    by_target: dict[str, list[LayoutConstraint]] = {}
    for c in constraints:
        if c.constraint_type == "absolute_region":
            for tid in c.target_ids:
                by_target.setdefault(tid, []).append(c)

    kept: list[LayoutConstraint] = []
    for c in constraints:
        if c.constraint_type != "absolute_region":
            kept.append(c)
    for tid, conflist in by_target.items():
        conflist.sort(key=lambda x: (-x.confidence, priority_order.get(x.source, 9)))
        kept.append(conflist[0])
    return kept


def _build_requirement_from_data(
    data: dict,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> LayoutRequirement:
    all_names = {c["displayName"] for c in controls} | {c["node_id"] for c in controls}
    nid_to_dn = {c["node_id"]: c["displayName"] for c in controls}

    llm_placements = data.get("placements", [])
    assigned: set[str] = set()
    placements: list[PlacementHint] = []
    for item in llm_placements:
        name = item.get("target", "")
        region = item.get("region", "")
        if name in all_names and region in VALID_REGIONS:
            placements.append(PlacementHint(target=name, region=region))
            assigned.add(nid_to_dn.get(name, name))

    LARGE_DEVICE_SIZE = 200
    for ctrl in controls:
        name = ctrl["displayName"]
        nid = ctrl["node_id"]
        if name in assigned or nid in assigned:
            continue
        w = ctrl.get("width") or 0
        h = ctrl.get("height") or 0
        if w >= LARGE_DEVICE_SIZE or h >= LARGE_DEVICE_SIZE:
            placements.append(PlacementHint(target=name, region="left"))
        else:
            placements.append(PlacementHint(target=name, region="right_top"))

    placement_hints = _sanitize_placement_hints(data.get("placement_hints", []), controls)
    if not placement_hints:
        placement_hints = _extract_placement_hints_from_query(data.get("_source_query", ""), controls)
    return LayoutRequirement(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        controls=controls,
        placements=placements,
        placement_hints=placement_hints,
    )


async def _extract_layout_intents(
    query: str, controls: list[dict], canvas_w: int, canvas_h: int, client=None, model=None
) -> LayoutIntents:
    _client_real = client or _client
    _model_real = model or _MODEL
    controls_info = "\n".join(
        f"- {c['node_id']} (原名{c['displayName']}, 宽{c.get('width',0)}x高{c.get('height',0)})"
        for c in controls
    )
    prompt = UNIFIED_LAYOUT_PROMPT.format(
        controls_info=controls_info,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
    )

    local_hints = _extract_placement_hints_from_query(query, controls)
    query_constraints = _extract_layout_constraints_from_query(query, controls)

    if not _model_real:
        logger.warning("未配置 DEEPSEEK_MODEL，使用本地规则兜底")
        normalized, compat_hints = _normalize_layout_constraints(query_constraints, controls)
        if not compat_hints:
            compat_hints = _expand_hints_to_node_ids(local_hints, controls)
        logger.info("  constraints: %d types: %s",
                    len(normalized),
                    {c.constraint_type for c in normalized})
        for c in normalized[:10]:
            logger.info("    %s", c.to_debug_line())
        if len(normalized) > 10:
            logger.info("    ... +%d more", len(normalized) - 10)
        return LayoutIntents(
            hints=compat_hints,
            flow_dsl="",
            constraints=normalized,
        )

    try:
        response = await _call_llm(
            _client_real,
            _model_real,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            stream=False,
            reasoning_effort="medium",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("统一意图抽取失败，使用本地规则兜底: %s", exc)
        normalized, compat_hints = _normalize_layout_constraints(query_constraints, controls)
        if not compat_hints:
            compat_hints = _expand_hints_to_node_ids(local_hints, controls)
        logger.info("  constraints: %d types: %s",
                    len(normalized),
                    {c.constraint_type for c in normalized})
        for c in normalized[:10]:
            logger.info("    %s", c.to_debug_line())
        if len(normalized) > 10:
            logger.info("    ... +%d more", len(normalized) - 10)
        return LayoutIntents(
            hints=compat_hints,
            flow_dsl="",
            constraints=normalized,
        )

    llm_hints = _sanitize_placement_hints(data.get("placement_hints", []), controls)
    if not llm_hints:
        llm_hints = local_hints
        llm_hints = _expand_hints_to_node_ids(llm_hints, controls)
        llm_constraints = _batch_hints_to_constraints(llm_hints, "query", 0.7)
    else:
        llm_hints = _expand_hints_to_node_ids(llm_hints, controls)
        llm_constraints = _batch_hints_to_constraints(llm_hints, "llm", 0.9)

    flow_dsl = data.get("flow_dsl") or ""

    llm_placements = data.get("placements", [])
    placement_constraints: list[LayoutConstraint] = []
    for item in llm_placements:
        name = item.get("target", "")
        region = item.get("region", "")
        if name and region:
            placement_constraints.append(LayoutConstraint(
                constraint_type="absolute_region",
                priority="soft",
                target_ids=[name],
                source="llm",
                source_span="",
                confidence=0.8,
                metadata={"region": region},
            ))

    all_constraints = query_constraints + llm_constraints + placement_constraints
    normalized, compat_hints = _normalize_layout_constraints(all_constraints, controls)

    if not compat_hints:
        compat_hints = llm_hints

    requirement = _build_requirement_from_data(
        {**data, "_source_query": query}, controls, canvas_w, canvas_h
    )

    logger.info("  constraints: %d types: %s",
                len(normalized),
                {c.constraint_type for c in normalized})
    for c in normalized[:10]:
        logger.info("    %s", c.to_debug_line())
    if len(normalized) > 10:
        logger.info("    ... +%d more", len(normalized) - 10)

    return LayoutIntents(
        hints=compat_hints,
        flow_dsl=flow_dsl,
        requirement=requirement,
        constraints=normalized,
    )


_NODE_RE = re.compile(
    r'(\w+)\s*(?:\[([^\]]+)\]|\(([^)]+)\)|\{([^}]+)\}|\(\(([^)]+)\)\)|>([^\]]+)\])'
)
_EDGE_SPLIT_RE = re.compile(r'\s*(-+\.?\.*\-+>|==+>)\s*')


def _fuzzy_match_label(label: str, name_set: set[str]) -> str | None:
    if label in name_set:
        return label
    candidates = []
    for name in name_set:
        if label in name or name in label:
            candidates.append((name, len(name)))
    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]
    return None


_BARE_ID_RE = re.compile(r'^\w+$')
_EDGE_LABEL_STRIP_RE = re.compile(r'^\|[^|]*\|\s*')


def _parse_flow_dsl(dsl: str, controls: list[dict]) -> FlowGraph | None:
    lines = dsl.strip().splitlines()
    direction = "LR"
    all_nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("%%"):
            continue

        dir_match = re.match(r'flowchart\s+(LR|TB|RL|BT)', line, re.IGNORECASE)
        if dir_match:
            direction = dir_match.group(1).upper()
            continue

        for m in _NODE_RE.finditer(line):
            nid = m.group(1)
            label = m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or ""
            label = label.strip()
            if nid not in all_nodes:
                all_nodes[nid] = GraphNode(id=nid, label=label)

        parts = _EDGE_SPLIT_RE.split(line)
        parts = [_EDGE_LABEL_STRIP_RE.sub('', p).strip() for p in parts]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            continue

        chain_ids: list[str] = []
        for part in parts:
            m = _NODE_RE.match(part)
            if m:
                chain_ids.append(m.group(1))
            elif _BARE_ID_RE.match(part) and part in all_nodes:
                chain_ids.append(part)

        for i in range(len(chain_ids) - 1):
            edge_str = parts[i * 2 + 1]
            etype = "dotted" if "." in edge_str else "solid"
            edges.append(GraphEdge(
                from_id=chain_ids[i],
                to_id=chain_ids[i + 1],
                type=etype,
            ))

    if not all_nodes:
        return None

    node_id_set = {c["node_id"] for c in controls}
    for node in list(all_nodes.values()):
        if node.label in node_id_set:
            continue
        best = _fuzzy_match_label(node.label, node_id_set)
        if best:
            node.label = best

    return FlowGraph(direction=direction, nodes=list(all_nodes.values()), edges=edges)


def _topological_layers(graph: FlowGraph) -> list[list[str]]:
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}

    for edge in graph.edges:
        if edge.from_id in adj and edge.to_id in in_degree:
            adj[edge.from_id].append(edge.to_id)
            in_degree[edge.to_id] += 1

    layers: list[list[str]] = []
    queue = [nid for nid, deg in in_degree.items() if deg == 0]

    while queue:
        layers.append(queue[:])
        next_queue: list[str] = []
        for nid in queue:
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    return layers


def _graph_to_region_map(graph: FlowGraph, hints: list[PlacementHint]) -> dict[str, str]:
    layers = _topological_layers(graph)
    num_layers = len(layers)
    region_map: dict[str, str] = {}

    for layer_idx, node_ids in enumerate(layers):
        layer_nodes = [n for n in graph.nodes if n.id in node_ids]
        n_in_layer = len(layer_nodes)

        for pos_idx, node in enumerate(layer_nodes):
            if graph.direction in ("LR", "RL"):
                if num_layers == 1:
                    h = "center"
                elif layer_idx == 0:
                    h = "left"
                elif layer_idx == num_layers - 1:
                    h = "right"
                else:
                    ratio = layer_idx / (num_layers - 1)
                    if ratio < 0.33:
                        h = "left"
                    elif ratio > 0.67:
                        h = "right"
                    else:
                        h = "center"

                if n_in_layer == 1:
                    v = ""
                elif pos_idx == 0:
                    v = "_top"
                elif pos_idx == n_in_layer - 1:
                    v = "_bottom"
                else:
                    v = ""
                candidate = f"{h}{v}"
                if h == "center" and v:
                    region = v.lstrip("_")
                elif candidate in VALID_REGIONS:
                    region = candidate
                else:
                    region = h
            else:
                if num_layers == 1:
                    v = "center"
                elif layer_idx == 0:
                    v = "top"
                elif layer_idx == num_layers - 1:
                    v = "bottom"
                else:
                    ratio = layer_idx / (num_layers - 1)
                    if ratio < 0.33:
                        v = "top"
                    elif ratio > 0.67:
                        v = "bottom"
                    else:
                        v = "center"

                if n_in_layer == 1:
                    h = ""
                elif pos_idx == 0:
                    h = "left_"
                elif pos_idx == n_in_layer - 1:
                    h = "right_"
                else:
                    h = ""
                candidate = f"{h}{v}"
                if v == "center" and h:
                    region = h.rstrip("_")
                elif candidate in VALID_REGIONS:
                    region = candidate
                else:
                    region = v

            region_map[node.label] = region

    control_ids = {e.from_id for e in graph.edges if e.type == "dotted"}
    if graph.direction in ("LR", "RL"):
        for node in graph.nodes:
            if node.id in control_ids and node.label in region_map:
                region_map[node.label] = "right_top"
    else:
        for node in graph.nodes:
            if node.id in control_ids and node.label in region_map:
                region_map[node.label] = "right_bottom"

    for hint in hints:
        region_map[hint.target] = hint.region

    for key in list(region_map):
        if region_map[key] not in VALID_REGIONS:
            normalized = _normalize_region(region_map[key])
            region_map[key] = normalized if normalized else "center"

    return region_map


def _generate_skeleton(requirement: LayoutRequirement, region_map: dict[str, str]) -> LayoutSkeleton:
    zones = _apply_layout_constraints(requirement, region_map)
    return LayoutSkeleton(zones=zones)


def _sort_controls_for_region(names: list[str], hint_map: dict[str, str]) -> list[str]:
    order = {
        "left_top": 0,
        "right_top": 0,
        "top": 1,
        "left": 2,
        "center": 3,
        "right": 4,
        "bottom": 5,
        "left_bottom": 6,
        "right_bottom": 6,
    }
    return sorted(names, key=lambda name: (order.get(hint_map.get(name, ""), 3), name))


def _resolve_zone_overlaps(zones: list[LayoutZone], cw: int, ch: int, gap: float) -> None:
    for _ in range(6):
        moved = False
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                z1, z2 = zones[i], zones[j]
                ox = max(0.0, min(z1.x + z1.width, z2.x + z2.width) - max(z1.x, z2.x))
                oy = max(0.0, min(z1.y + z1.height, z2.y + z2.height) - max(z1.y, z2.y))
                if ox <= 0 or oy <= 0:
                    continue
                if ox < oy:
                    dx = (ox + gap) / 2.0
                    if z1.x < z2.x:
                        z1.x -= dx
                        z2.x += dx
                    else:
                        z1.x += dx
                        z2.x -= dx
                else:
                    dy = (oy + gap) / 2.0
                    if z1.y < z2.y:
                        z1.y -= dy
                        z2.y += dy
                    else:
                        z1.y += dy
                        z2.y -= dy
                moved = True
        if not moved:
            break

    for z in zones:
        z.x = round(max(gap, min(cw - z.width - gap, z.x)))
        z.y = round(max(gap, min(ch - z.height - gap, z.y)))


def _apply_layout_constraints(requirement: LayoutRequirement, region_map: dict[str, str]) -> list[LayoutZone]:
    cw = requirement.canvas_width
    ch = requirement.canvas_height
    ctrl_map = {c["node_id"]: c for c in requirement.controls}

    region_groups: dict[str, list[str]] = {}
    for ctrl in requirement.controls:
        nid = ctrl["node_id"]
        region = region_map.get(nid, "center")
        if region not in region_groups:
            region_groups[region] = []
        region_groups[region].append(nid)

    for region in region_groups:
        region_groups[region] = _sort_controls_for_region(region_groups[region], region_map)

    gap = 40
    padding = 20
    zones: list[LayoutZone] = []

    for region, control_names in region_groups.items():
        region_ctrls = [ctrl_map[n] for n in control_names if n in ctrl_map]
        if not region_ctrls:
            continue

        total_h = sum(c.get("height") or 0 for c in region_ctrls) + padding * (len(region_ctrls) - 1)
        max_w = max((c.get("width") or 0 for c in region_ctrls), default=0)
        zone_w = max(max_w + gap * 2, 100)
        zone_h = max(total_h + gap * 2, 100)

        anchor_x_ratio, anchor_y_ratio = REGION_ANCHORS.get(region, (0.5, 0.5))
        anchor_x = cw * anchor_x_ratio
        anchor_y = ch * anchor_y_ratio
        zone_x = round(anchor_x - zone_w / 2)
        zone_y = round(anchor_y - zone_h / 2)

        zone_x = max(gap, min(cw - zone_w - gap, zone_x))
        zone_y = max(gap, min(ch - zone_h - gap, zone_y))

        zones.append(LayoutZone(
            name=region,
            x=zone_x,
            y=zone_y,
            width=round(zone_w),
            height=round(zone_h),
            controls=control_names,
        ))

    _resolve_zone_overlaps(zones, cw, ch, gap * 0.75)
    return zones


def _compute_coordinates(
    skeleton: LayoutSkeleton,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> list[dict]:
    ctrl_map = {c["node_id"]: c for c in controls}
    total = len(controls)

    if total > 20:
        return _force_directed_layout(skeleton, controls, canvas_w, canvas_h)

    PADDING = {
        "left": 30,
        "left_top": 20,
        "left_bottom": 20,
        "center": 25,
        "right": 20,
        "right_top": 20,
        "right_bottom": 20,
        "top": 20,
        "bottom": 20,
    }

    nodes = []
    for zone in skeleton.zones:
        zone_controls = zone.controls
        if not zone_controls:
            continue

        zone_ctrls = [ctrl_map[n] for n in zone_controls if n in ctrl_map]
        if not zone_ctrls:
            continue

        padding = PADDING.get(zone.name, 20)

        sizes = [(c.get("width") or 0, c.get("height") or 0) for c in zone_ctrls]
        total_h = sum(h for _, h in sizes) + padding * (len(sizes) - 1)

        if len(zone_ctrls) <= 6:
            start_y = zone.y + (zone.height - total_h) / 2
            cx = zone.x + zone.width / 2
            cursor_y = start_y
            for ctrl, (w, h) in zip(zone_ctrls, sizes):
                nodes.append({
                    "node_id": ctrl["node_id"],
                    "displayName": ctrl["displayName"],
                    "image": ctrl.get("image", ""),
                    "width": w,
                    "height": h,
                    "x": round(cx),
                    "y": round(cursor_y + h / 2),
                })
                cursor_y += h + padding
        else:
            MARGIN = 20
            content_h = zone.height - MARGIN * 2
            cols = []
            cur_col: list[dict] = []
            cur_h = 0.0
            for ctrl, (w, h) in zip(zone_ctrls, sizes):
                space = h + (padding if cur_col else 0)
                if cur_col and cur_h + space > content_h:
                    cols.append(cur_col)
                    cur_col = [ctrl]
                    cur_h = h
                else:
                    cur_col.append(ctrl)
                    cur_h += space
            if cur_col:
                cols.append(cur_col)

            col_widths = [max(c.get("width") or 0 for c in col) for col in cols]
            content_x = zone.x + MARGIN
            content_w = zone.width - MARGIN * 2
            total_col_w = sum(col_widths) + padding * (len(cols) - 1)
            col_start_x = content_x + (content_w - total_col_w) / 2

            offset_x = col_start_x
            for col, col_w in zip(cols, col_widths):
                col_cx = offset_x + col_w / 2
                col_h = sum(c.get("height") or 0 for c in col) + padding * (len(col) - 1)
                col_start_y = zone.y + (zone.height - col_h) / 2
                cursor_y = col_start_y
                for ctrl in col:
                    h = ctrl.get("height") or 0
                    nodes.append({
                        "node_id": ctrl["node_id"],
                        "displayName": ctrl["displayName"],
                        "image": ctrl.get("image", ""),
                        "width": ctrl.get("width", 0),
                        "height": h,
                        "x": round(col_cx),
                        "y": round(cursor_y + h / 2),
                    })
                    cursor_y += h + padding
                offset_x += col_w + padding

    return nodes


def _compute_flow_graph_coordinates(
    graph: FlowGraph,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
) -> Optional[list[dict]]:
    if not graph.edges:
        return None

    ctrl_map = {c["node_id"]: c for c in controls}
    node_to_ctrl: dict[str, dict] = {}
    for graph_node in graph.nodes:
        ctrl = ctrl_map.get(graph_node.label)
        if ctrl:
            node_to_ctrl[graph_node.id] = ctrl

    if {c["node_id"] for c in node_to_ctrl.values()} != set(ctrl_map):
        return None

    raw_layers = _topological_layers(graph)
    layers: list[list[dict]] = []
    seen: set[str] = set()
    for raw_layer in raw_layers:
        layer: list[dict] = []
        for graph_node_id in raw_layer:
            ctrl = node_to_ctrl.get(graph_node_id)
            if ctrl and ctrl["node_id"] not in seen:
                layer.append(ctrl)
                seen.add(ctrl["node_id"])
        if layer:
            layers.append(layer)

    if seen != set(ctrl_map) or not layers:
        return None

    horizontal = graph.direction in ("LR", "RL")
    reverse = graph.direction in ("RL", "BT")
    nodes: list[dict] = []

    def _node_payload(ctrl: dict, x: float, y: float) -> dict:
        return {
            "node_id": ctrl["node_id"],
            "displayName": ctrl["displayName"],
            "image": ctrl.get("image", ""),
            "width": ctrl.get("width") or 0,
            "height": ctrl.get("height") or 0,
            "x": round(x),
            "y": round(y),
        }

    if horizontal:
        layer_widths = [max(c.get("width") or 0 for c in layer) for layer in layers]
        layer_gap = max(80, min(180, round(canvas_w * 0.06)))
        side_margin = max(40, min(120, round(canvas_w * 0.05)))
        if len(layers) > 1:
            available_w = max(canvas_w - side_margin * 2, 1)
            max_gap = (available_w - sum(layer_widths)) / (len(layers) - 1)
            layer_gap = max(40, min(layer_gap, round(max_gap)))

        cursor_x = side_margin
        layer_xs: list[float] = []
        for layer_w in layer_widths:
            center_x = cursor_x + layer_w / 2
            layer_xs.append(canvas_w - center_x if reverse else center_x)
            cursor_x += layer_w + layer_gap

        item_gap = max(30, min(80, round(canvas_h * 0.04)))
        for layer, center_x in zip(layers, layer_xs):
            total_h = sum(c.get("height") or 0 for c in layer) + item_gap * (len(layer) - 1)
            cursor_y = (canvas_h - total_h) / 2
            for ctrl in layer:
                h = ctrl.get("height") or 0
                nodes.append(_node_payload(ctrl, center_x, cursor_y + h / 2))
                cursor_y += h + item_gap
    else:
        layer_heights = [max(c.get("height") or 0 for c in layer) for layer in layers]
        layer_gap = max(70, min(160, round(canvas_h * 0.06)))
        side_margin = max(40, min(120, round(canvas_h * 0.05)))
        if len(layers) > 1:
            available_h = max(canvas_h - side_margin * 2, 1)
            max_gap = (available_h - sum(layer_heights)) / (len(layers) - 1)
            layer_gap = max(40, min(layer_gap, round(max_gap)))

        cursor_y = side_margin
        layer_ys: list[float] = []
        for layer_h in layer_heights:
            center_y = cursor_y + layer_h / 2
            layer_ys.append(canvas_h - center_y if reverse else center_y)
            cursor_y += layer_h + layer_gap

        item_gap = max(40, min(100, round(canvas_w * 0.04)))
        for layer, center_y in zip(layers, layer_ys):
            total_w = sum(c.get("width") or 0 for c in layer) + item_gap * (len(layer) - 1)
            cursor_x = (canvas_w - total_w) / 2
            for ctrl in layer:
                w = ctrl.get("width") or 0
                nodes.append(_node_payload(ctrl, cursor_x + w / 2, center_y))
                cursor_x += w + item_gap

    return nodes


def _scale_to_canvas(
    nodes: list[dict],
    canvas_w: int,
    canvas_h: int,
    allow_upscale: bool = True,
) -> list[dict]:
    if not nodes:
        return nodes
    margin = 20
    rect = _calc_content_rect(nodes)
    if rect["width"] <= 0 or rect["height"] <= 0:
        return nodes

    max_scale = 2.0
    needed_w = rect["width"] + margin * 2
    needed_h = rect["height"] + margin * 2
    scale_x = canvas_w / needed_w
    scale_y = canvas_h / needed_h
    if not allow_upscale and scale_x >= 1.0 and scale_y >= 1.0:
        _clamp_nodes_to_canvas(nodes, canvas_w, canvas_h)
        return nodes

    scale = min(scale_x, scale_y, max_scale if allow_upscale else 1.0)

    new_w = canvas_w - margin * 2
    new_h = canvas_h - margin * 2
    for n in nodes:
        n["x"] = round(margin + (n["x"] - rect["x"]) * scale + (new_w - rect["width"] * scale) / 2)
        n["y"] = round(margin + (n["y"] - rect["y"]) * scale + (new_h - rect["height"] * scale) / 2)

    max_w = canvas_w - margin * 2
    max_h = canvas_h - margin * 2
    for n in nodes:
        w = n.get("width") or 0
        h = n.get("height") or 0
        if w <= 0 or h <= 0:
            continue
        size_scale = 1.0
        if w > max_w:
            size_scale = min(size_scale, max_w / w)
        if h > max_h:
            size_scale = min(size_scale, max_h / h)
        if size_scale < 1.0:
            n["width"] = round(w * size_scale)
            n["height"] = round(h * size_scale)

    _clamp_nodes_to_canvas(nodes, canvas_w, canvas_h)
    return nodes


def _clamp_nodes_to_canvas(nodes: list[dict], canvas_w: int, canvas_h: int) -> None:
    for n in nodes:
        w = (n.get("width") or 0) or 60
        h = (n.get("height") or 0) or 40
        half_w = w / 2
        half_h = h / 2
        if canvas_w > 0:
            n["x"] = round(max(half_w, min(canvas_w - half_w, n.get("x", 0))))
        if canvas_h > 0:
            n["y"] = round(max(half_h, min(canvas_h - half_h, n.get("y", 0))))


def _force_directed_layout(
    skeleton: LayoutSkeleton,
    controls: list[dict],
    canvas_w: int,
    canvas_h: int,
    iterations: int = 100,
) -> list[dict]:
    all_ids = [c["node_id"] for c in controls]
    rng = random.Random(0)

    positions: dict[str, list[float]] = {}
    zone_center: dict[str, list[float]] = {}
    for zone in skeleton.zones:
        zx = zone.x + zone.width / 2
        zy = zone.y + zone.height / 2
        zone_center[zone.name] = [zx, zy]
        for nid in zone.controls:
            if nid not in positions:
                positions[nid] = [zx + rng.uniform(-30, 30), zy + rng.uniform(-30, 30)]

    for nid in all_ids:
        if nid not in positions:
            positions[nid] = [canvas_w / 2 + rng.uniform(-50, 50), canvas_h / 2 + rng.uniform(-50, 50)]

    repulsion_k = 5000.0
    zone_attract_k = 0.02
    dampening = 0.9

    velocities: dict[str, list[float]] = {n: [0.0, 0.0] for n in all_ids}

    for _ in range(iterations):
        forces: dict[str, list[float]] = {n: [0.0, 0.0] for n in all_ids}

        for i, n1 in enumerate(all_ids):
            for j, n2 in enumerate(all_ids):
                if i >= j:
                    continue
                dx = positions[n1][0] - positions[n2][0]
                dy = positions[n1][1] - positions[n2][1]
                dist = math.sqrt(dx * dx + dy * dy) + 1e-6
                f_mag = repulsion_k / (dist * dist)
                fx = f_mag * dx / dist
                fy = f_mag * dy / dist
                forces[n1][0] += fx
                forces[n1][1] += fy
                forces[n2][0] -= fx
                forces[n2][1] -= fy

        for zone in skeleton.zones:
            zx = zone_center[zone.name][0]
            zy = zone_center[zone.name][1]
            for nid in zone.controls:
                if nid in forces:
                    dx = zx - positions[nid][0]
                    dy = zy - positions[nid][1]
                    forces[nid][0] += zone_attract_k * dx
                    forces[nid][1] += zone_attract_k * dy

        for nid in all_ids:
            velocities[nid][0] = (velocities[nid][0] + forces[nid][0]) * dampening
            velocities[nid][1] = (velocities[nid][1] + forces[nid][1]) * dampening
            positions[nid][0] += velocities[nid][0]
            positions[nid][1] += velocities[nid][1]
            positions[nid][0] = max(50, min(canvas_w - 50, positions[nid][0]))
            positions[nid][1] = max(50, min(canvas_h - 50, positions[nid][1]))

    for nid in all_ids:
        positions[nid][0] = round(positions[nid][0])
        positions[nid][1] = round(positions[nid][1])

    nodes = []
    for c in controls:
        nid = c["node_id"]
        pos = positions.get(nid, [canvas_w / 2, canvas_h / 2])
        nodes.append({
            "node_id": nid,
            "displayName": c["displayName"],
            "image": c.get("image", ""),
            "width": c.get("width", 0),
            "height": c.get("height", 0),
            "x": pos[0],
            "y": pos[1],
        })

    return nodes


async def _refine_layout_with_llm(
    nodes: list[dict], canvas_w: int, canvas_h: int, client=None, model=None
) -> list[dict]:
    _model_real = model or _MODEL
    if not _model_real:
        logger.warning("未配置 DEEPSEEK_MODEL，跳过 LLM 布局微调")
        return nodes

    layout_json = json.dumps(nodes, ensure_ascii=False, indent=2)
    prompt = REFINE_PROMPT.format(
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        layout_json=layout_json,
    )
    try:
        response = await _call_llm(
            client or _client,
            _model_real,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请微调以上布局坐标，使其更合理。"},
            ],
            stream=False,
            reasoning_effort="low",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("LLM 布局微调失败，保留规则布局: %s", exc)
        return nodes

    refined = data if isinstance(data, list) else data.get("nodes", data.get("d", []))
    return _merge_refined_nodes(nodes, refined, canvas_w, canvas_h)


def _merge_refined_nodes(
    original: list[dict], refined: list[dict], canvas_w: int, canvas_h: int
) -> list[dict]:
    if not isinstance(refined, list):
        return original

    refined_by_node_id: dict[str, dict] = {}
    refined_by_dn: dict[str, list[dict]] = {}
    for n in refined:
        if isinstance(n, dict):
            nid = n.get("node_id")
            if nid:
                refined_by_node_id[nid] = n
            dn = n.get("displayName")
            if dn:
                refined_by_dn.setdefault(dn, []).append(n)

    result: list[dict] = []
    dn_idx: dict[str, int] = {}
    for node in original:
        merged = dict(node)
        nid = node.get("node_id", "")
        dn = node["displayName"]

        if nid and nid in refined_by_node_id:
            refined_node = refined_by_node_id[nid]
        else:
            idx = dn_idx.get(dn, 0)
            dn_idx[dn] = idx + 1
            refined_list = refined_by_dn.get(dn, [])
            refined_node = refined_list[idx] if idx < len(refined_list) else {}

        try:
            merged["x"] = round(float(refined_node.get("x", node["x"])))
            merged["y"] = round(float(refined_node.get("y", node["y"])))
        except (TypeError, ValueError):
            merged["x"] = node["x"]
            merged["y"] = node["y"]
        result.append(merged)

    _clamp_nodes_to_canvas(result, canvas_w, canvas_h)
    return result


def _calc_content_rect(nodes: list[dict]) -> dict:
    if not nodes:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for n in nodes:
        cx = n.get("x", 0)
        cy = n.get("y", 0)
        w = n.get("width", 0) or 0
        h = n.get("height", 0) or 0
        half_w, half_h = w / 2, h / 2
        min_x = min(min_x, cx - half_w)
        min_y = min(min_y, cy - half_h)
        max_x = max(max_x, cx + half_w)
        max_y = max(max_y, cy + half_h)
    return {
        "x": round(min_x, 5),
        "y": round(min_y, 5),
        "width": round(max_x - min_x, 5),
        "height": round(max_y - min_y, 5),
    }


def _quality_check(nodes: list[dict], canvas_w: int = 0, canvas_h: int = 0) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            n1 = nodes[i]
            n2 = nodes[j]
            overlap = _compute_overlap_ratio(n1, n2)
            if overlap > 0.10:
                issues.append(QualityIssue(
                    severity="warning",
                    issue_type="overlap",
                    message=f"控件 {n1['displayName']} 与 {n2['displayName']} 重叠率 {overlap:.1%}",
                    controls=[n1["displayName"], n2["displayName"]],
                ))

    if canvas_w > 0 and canvas_h > 0:
        for n in nodes:
            w = (n.get("width") or 0) or 60
            h = (n.get("height") or 0) or 40
            x_min = n.get("x", 0) - w / 2
            x_max = n.get("x", 0) + w / 2
            y_min = n.get("y", 0) - h / 2
            y_max = n.get("y", 0) + h / 2
            overflow_parts = []
            if x_min < 0 or x_max > canvas_w:
                overflow_parts.append(f"水平({'%.0f' % x_min},{'%.0f' % x_max})")
            if y_min < 0 or y_max > canvas_h:
                overflow_parts.append(f"垂直({'%.0f' % y_min},{'%.0f' % y_max})")
            if overflow_parts:
                issues.append(QualityIssue(
                    severity="error",
                    issue_type="overflow",
                    message=f"控件 {n['displayName']} 超出画布边界 ({canvas_w}x{canvas_h}): {'; '.join(overflow_parts)}",
                    controls=[n["displayName"]],
                ))

    return issues


def _compute_overlap_ratio(n1: dict, n2: dict) -> float:
    w1 = (n1.get("width") or 0) or 60
    h1 = (n1.get("height") or 0) or 40
    w2 = (n2.get("width") or 0) or 60
    h2 = (n2.get("height") or 0) or 40

    x1_min = n1.get("x", 0) - w1 / 2
    x1_max = n1.get("x", 0) + w1 / 2
    y1_min = n1.get("y", 0) - h1 / 2
    y1_max = n1.get("y", 0) + h1 / 2
    x2_min = n2.get("x", 0) - w2 / 2
    x2_max = n2.get("x", 0) + w2 / 2
    y2_min = n2.get("y", 0) - h2 / 2
    y2_max = n2.get("y", 0) + h2 / 2

    overlap_w = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
    overlap_h = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
    overlap_area = overlap_w * overlap_h
    area1 = w1 * h1
    area2 = w2 * h2
    smaller = min(area1, area2)
    if smaller == 0:
        return 0.0
    return overlap_area / smaller


def _get_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert _SCHEMA_CACHE is not None
    return _SCHEMA_CACHE


async def _schema_validate(json_data: dict) -> list[str]:
    schema = _get_schema()
    try:
        jsonschema.validate(instance=json_data, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e.message)]


def _select_top_controls(rows: list[dict], keyword: str, count: int) -> list[dict]:
    best_by_name: dict[str, dict] = {}
    for row in rows:
        name = row.get("displayName")
        if not name:
            continue
        current = best_by_name.get(name)
        if current is None or row.get("similarity", 0.0) > current.get("similarity", 0.0):
            best_by_name[name] = row

    candidates = list(best_by_name.values())
    candidates.sort(
        key=lambda row: (
            0 if row.get("displayName") == keyword else 1,
            -float(row.get("similarity", 0.0)),
            row.get("displayName", ""),
        )
    )
    if not candidates:
        return []

    best = candidates[0]
    selected: list[dict] = []
    for idx in range(count):
        clone = dict(best)
        clone["_instance_index"] = idx + 1
        selected.append(clone)
    return selected


def _dedupe_controls(controls: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set = set()
    for ctrl in controls:
        name = ctrl.get("displayName")
        instance = ctrl.get("_instance_index")
        key = (name, instance) if instance is not None else name
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(ctrl)
    return result


async def _extract_control_names_from_query(query: str, material_db, client=None, model=None) -> tuple[list[dict], list[str]]:
    _client_real = client or _client
    _model_real = model or _MODEL
    all_qr = await material_db.list_query_results("")
    available_names = sorted({r["displayName"] for r in all_qr if r.get("displayName")})
    if not available_names:
        return [], []
    controls_list = "\n".join(f"- {name}" for name in available_names)
    prompt = EXTRACT_CONTROLS_PROMPT.format(controls_list=controls_list)
    if not _model_real:
        raise RuntimeError("未配置 DEEPSEEK_MODEL")
    response = await _call_llm(
        _client_real,
        _model_real,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ],
        stream=False,
        reasoning_effort="low",
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content
    data = json.loads(content) if content else {}
    if not isinstance(data, dict):
        return [], []
    items = data.get("controls", data.get("items", []))
    if not isinstance(items, list):
        return [], []
    name_set = set(available_names)
    specs: list[dict] = []
    missing_names: list[str] = []
    for item in items:
        name = item.get("name", "")
        if name in name_set:
            specs.append({"name": name, "count": max(1, int(item.get("count", 1)))})
        else:
            missing_names.append(name)
    return specs, missing_names


async def _load_controls_from_query_results(query: str, material_db, client=None, model=None) -> tuple[list[dict], list[str], list[str]]:
    specs: list[dict] | None = None
    missing_names: list[str] = []
    try:
        specs, missing_names = await _extract_control_names_from_query(query, material_db, client, model)
    except Exception as exc:
        logger.warning("LLM 控件提取失败，使用本地名称匹配: %s", exc)

    if not specs:
        specs = []

    all_qr = await material_db.list_query_results("")
    qr_names = list({r["displayName"] for r in all_qr if r.get("displayName")})
    existing_names = {s["name"] for s in specs}
    for name in sorted(qr_names, key=len, reverse=True):
        if name not in existing_names and name in query:
            specs.append({"name": name, "count": 1})
            existing_names.add(name)

    if not specs:
        return [], [], missing_names

    matched: list[dict] = []
    matched_keywords: list[str] = []
    for spec in specs:
        rows = await material_db.search_query_results_by_name(spec["name"])
        if rows:
            matched.extend(_select_top_controls(rows, spec["name"], spec.get("count", 1)))
            matched_keywords.append(spec["name"])
        else:
            if spec["name"] not in missing_names:
                missing_names.append(spec["name"])

    return matched, matched_keywords, missing_names


class CanvasAgent:
    def __init__(self, db: Optional[MaterialDB] = None, client=None, model=None):
        self._db = db
        self._client = client
        self._model = model

    async def layout(
        self,
        query: str,
        controls: Optional[list[dict]] = None,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
    ) -> CanvasResult:
        missing_controls: list[str] = []
        if controls is None:
            if self._db is None:
                raise ValueError("controls 未提供且 CanvasAgent 未注入 material_db")
            controls, _, missing_controls = await _load_controls_from_query_results(query, self._db, self._client, self._model)
        controls = _dedupe_controls(controls)
        if not controls:
            logger.info("无可用控件，早停返回")
            return CanvasResult(
                json_data={"v": "8.0.5", "p": {}, "a": {"width": canvas_width, "height": canvas_height}, "d": [], "contentRect": {}},
                content_rect={"x": 0, "y": 0, "width": 0, "height": 0},
                quality_issues=[QualityIssue(severity="warning", issue_type="empty", message="无可用控件", controls=[])],
                skeleton=LayoutSkeleton(zones=[]),
                missing_controls=missing_controls,
            )

        for ctrl in controls:
            idx = ctrl.get("_instance_index")
            ctrl["node_id"] = f"{ctrl['displayName']}_{idx}" if idx is not None else ctrl["displayName"]

        logger.info("自动布局流程")
        logger.info("━" * 40)
        logger.info("📐 画布尺寸: %dx%d", canvas_width, canvas_height)
        logger.info("📦 控件数量: %d", len(controls))

        # ── Step0: 一次性抽取全部布局意图 ──
        logger.info("━" * 40)
        logger.info("🔍 Step0: 统一抽取布局意图 (hints + DSL + placements)")
        intents = await _extract_layout_intents(query, controls, canvas_width, canvas_height, self._client, self._model)
        step1_hints = intents.hints
        logger.info("  hints: %s", [(h.target, h.region) for h in step1_hints])
        if intents.constraints:
            src_count = Counter(c.source for c in intents.constraints)
            logger.info("  constraint sources: %s", dict(src_count))

        # ── 尝试解析 DSL ──
        flow_graph: FlowGraph | None = None
        region_map: dict[str, str] = {}

        if intents.flow_dsl:
            logger.info("  DSL:\n%s", intents.flow_dsl)
            try:
                flow_graph = _parse_flow_dsl(intents.flow_dsl, controls)
                if flow_graph and flow_graph.nodes:
                    region_map = _graph_to_region_map(flow_graph, step1_hints)
                    logger.info("  DSL 解析成功: direction=%s, nodes=%d, edges=%d",
                                flow_graph.direction, len(flow_graph.nodes), len(flow_graph.edges))
                else:
                    logger.warning("  DSL 解析结果为空，降级到传统流程")
                    flow_graph = None
            except Exception as exc:
                logger.warning("  DSL 解析失败: %s，降级到传统流程", exc)
                flow_graph = None
        else:
            logger.warning("  DSL 为空，降级到传统流程")

        if flow_graph is None:
            requirement = intents.requirement or _build_requirement_from_data(
                {"_source_query": query}, controls, canvas_width, canvas_height
            )
            requirement.placements = _expand_hints_to_node_ids(requirement.placements, controls)
            requirement.placement_hints = _expand_hints_to_node_ids(requirement.placement_hints, controls)
            region_map = {p.target: p.region for p in requirement.placements}
            for h in requirement.placement_hints:
                region_map[h.target] = h.region
            logger.info("  分区配置: %s", [(k, v) for k, v in region_map.items()])
        else:
            requirement = LayoutRequirement(
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                controls=controls,
                placements=[],
                placement_hints=step1_hints,
            )
            logger.info("  分区配置(DSL): %s", [(k, v) for k, v in region_map.items()])

        logger.info("━" * 40)
        logger.info("🦴 Step2: 生成布局骨架")
        skeleton = _generate_skeleton(requirement, region_map)
        for z in skeleton.zones:
            logger.info("  %s: %d个控件 %s", z.name, len(z.controls), z.controls)

        logger.info("━" * 40)
        logger.info("📍 Step3: 计算坐标")
        total = len(controls)
        compact_flow_layout = False
        nodes: Optional[list[dict]] = None
        if flow_graph is not None and total <= 20:
            nodes = _compute_flow_graph_coordinates(flow_graph, controls, canvas_width, canvas_height)
            if nodes:
                compact_flow_layout = True
                logger.info("  使用 DSL 连接关系紧凑布局")
        if nodes is None:
            nodes = _compute_coordinates(skeleton, controls, canvas_width, canvas_height)

        if total > 20:
            logger.info("  元素数量>%d，使用力导向布局+LLM微调", 20)
            nodes = await _refine_layout_with_llm(nodes, canvas_width, canvas_height, self._client, self._model)

        nodes = _scale_to_canvas(
            nodes,
            canvas_width,
            canvas_height,
            allow_upscale=not compact_flow_layout,
        )

        for n in nodes:
            logger.info("  %s (%s) → (%d, %d)", n["displayName"], n.get("node_id", ""), n["x"], n["y"])

        logger.info("━" * 40)
        logger.info("🔍 Step4: 质量检测")
        issues = _quality_check(nodes, canvas_width, canvas_height)
        for issue in issues:
            logger.info("  [%s] %s: %s", issue.severity, issue.issue_type, issue.message)

        logger.info("━" * 40)
        logger.info("✅ Step5: 组装JSON & Schema校验")
        d_nodes = []
        for idx, n in enumerate(nodes):
            node_dict: dict = {
                "c": "ht.Node",
                "i": 17092 + idx,
            }
            p: dict = {
                "displayName": n["displayName"],
                "image": n.get("image", ""),
                "position": {"x": n["x"], "y": n["y"]},
            }
            if n.get("width") and n.get("height"):
                p["width"] = n["width"]
                p["height"] = n["height"]
            node_dict["p"] = p
            d_nodes.append(node_dict)

        content_rect = _calc_content_rect(nodes)

        json_data = {
            "v": "8.0.5",
            "p": {
                "layers": [{"name": "0", "visible": True, "selectable": True, "movable": True, "editable": True}],
                "autoAdjustIndex": True,
                "hierarchicalRendering": True,
            },
            "a": {
                "width": canvas_width,
                "height": canvas_height,
                "fitContent": True,
                "rectSelectable": False,
                "zoomable": False,
                "pannable": False,
            },
            "d": d_nodes,
            "contentRect": content_rect,
        }

        errors = await _schema_validate(json_data)
        if errors:
            logger.warning("  Schema校验问题: %s", errors)
            issues.extend(
                QualityIssue(
                    severity="error",
                    issue_type="schema",
                    message=error,
                    controls=[],
                )
                for error in errors
            )
        else:
            logger.info("  Schema校验通过 ✓")

        return CanvasResult(
            json_data=json_data,
            content_rect=json_data["contentRect"],
            quality_issues=issues,
            skeleton=skeleton,
            missing_controls=missing_controls,
        )


def _cli() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    query = input("查询描述: ").strip()
    if not query:
        print("查询描述不能为空", file=sys.stderr)
        sys.exit(1)

    w_str = input("画布宽度 (默认 800): ").strip()
    h_str = input("画布高度 (默认 800): ").strip()
    canvas_w = int(w_str) if w_str else 800
    canvas_h = int(h_str) if h_str else 800

    async def run() -> CanvasResult:
        db = MaterialDB()
        await db.init_db()
        agent = CanvasAgent(db=db)
        return await agent.layout(query=query, canvas_width=canvas_w, canvas_height=canvas_h)

    result = asyncio.run(run())
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = Path(__file__).resolve().parent.parent / "output" / f"canvas_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已保存到 %s", output_path)
    logger.info("控件数: %d, 质量问题: %d", len(result.json_data.get("d", [])), len(result.quality_issues))


if __name__ == "__main__":
    _cli()
