import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pydantic import BaseModel, Field, ValidationError

from data.sqlite.material_db import MaterialDB
from model.canva_agent import _MODEL, _call_llm, _client
from model.layout_agent import _llm_text, _parse_json_lenient

logger = logging.getLogger(__name__)

Region = Literal["left", "right", "center"]
Side = Literal["top", "right", "bottom", "left"]
Arrangement = Literal["vertical", "horizontal", "grid"]
GapHint = Literal["tight", "normal", "loose"]
GridOrder = Literal["row-major", "col-major"]
Role = Literal["root", "valve", "pipe", "meter", "sensor", "default"]

_INTENT_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "layout" / "intent.json"


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


class Endpoint(BaseModel):
    group: str
    node: str
    port: Optional[str] = None


class Connection(BaseModel):
    id: str
    source: Endpoint
    target: Endpoint


class LayoutIntent(BaseModel):
    groups: List[LayoutGroup]
    connections: List[Connection] = Field(default_factory=list)


class LayoutFile(BaseModel):
    layoutIntent: LayoutIntent


@dataclass
class ValidationErrorItem:
    path: str
    message: str


def validate_layout_file(file: LayoutFile) -> Tuple[List[ValidationErrorItem], List[str]]:
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
    for gi, group in enumerate(groups):
        gp = f"layoutIntent.groups[{gi}]"
        if group.id in group_ids:
            errors.append(
                ValidationErrorItem(path=f"{gp}.id", message=f"group id 重复：{group.id}")
            )
        group_ids.add(group.id)

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
        group_node_ids[group.id] = declared

    connections = file.layoutIntent.connections
    if connections:
        conn_ids: set = set()
        for ci, conn in enumerate(connections):
            cp = f"layoutIntent.connections[{ci}]"
            if conn.id in conn_ids:
                errors.append(
                    ValidationErrorItem(
                        path=f"{cp}.id", message=f"connection id 重复：{conn.id}"
                    )
                )
            conn_ids.add(conn.id)
            for ep_name, ep in (("source", conn.source), ("target", conn.target)):
                epp = f"{cp}.{ep_name}"
                if ep.group not in group_ids:
                    errors.append(
                        ValidationErrorItem(
                            path=f"{epp}.group",
                            message=f"引用了不存在的 group：{ep.group}",
                        )
                    )
                    continue
                if ep.node not in group_node_ids.get(ep.group, set()):
                    errors.append(
                        ValidationErrorItem(
                            path=f"{epp}.node",
                            message=f"引用了 group {ep.group} 内不存在的节点：{ep.node}",
                        )
                    )

    return errors, warnings


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
    parts.append("- LayoutIntent: { groups: LayoutGroup[], connections?: Connection[] }")
    parts.append(
        '- LayoutGroup: { id: string, region: "left"|"right"|"center", unit: LayoutUnit, count: number, arrangement?: "vertical"|"horizontal"|"grid", gapHint?: "tight"|"normal"|"loose", columns?: number, rows?: number, order?: "row-major"|"col-major" }'
    )
    parts.append("- LayoutUnit: { root: DeviceNode, attachments: AttachmentNode[] }")
    parts.append('- DeviceNode: { id: string, deviceType: string, role?: "root"|"valve"|"pipe"|"meter"|"sensor"|"default" }')
    parts.append(
        '- AttachmentNode: { id: string, deviceType: string, role?: "root"|"valve"|"pipe"|"meter"|"sensor"|"default", relativeTo: string, side: "top"|"right"|"bottom"|"left", count?: number }'
    )
    parts.append("- Connection: { id: string, source: Endpoint, target: Endpoint }")
    parts.append("- Endpoint: { group: string, node: string, port?: string }")
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
    parts.append("11. connections 可选；若存在，connection.id 必须唯一，source.group/target.group 必须引用已声明的 group.id，source.node/target.node 必须是该 group 内 root.id 或 attachment.id。")
    parts.append("12. 同一 group 内的节点 id 必须唯一；不同 group 之间 id 可重复，引用时用 {group, node} 组合定位。")
    parts.append('13. role 可选，取值 "root"|"valve"|"pipe"|"meter"|"sensor"|"default"；root 节点可不标（自动按 root 处理）；附件节点建议标注 role 以确定尺寸约束，未标则按 deviceType 关键词推断，仍无法识别时按 default。')
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


async def _load_vocab() -> List[str]:
    db = MaterialDB()
    try:
        await db.init_db()
        rows = await db.list_query_results("")
    finally:
        await db.close()

    seen: set = set()
    vocab: List[str] = []
    for r in rows:
        name = r.get("displayName")
        if not name or name in seen:
            continue
        seen.add(name)
        vocab.append(name)
    return vocab


async def generate_intent(prompt: str, output_path: Path) -> int:
    if not _MODEL:
        print("错误：未设置 DEEPSEEK_MODEL 环境变量", file=sys.stderr)
        return 1

    vocab = await _load_vocab()
    if not vocab:
        logger.warning("query_results 表为空，将不约束 deviceType 词表")

    example = _load_intent_example()
    system_prompt = _build_system_prompt(vocab, example)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = await _call_llm(
            _client,
            _MODEL,
            messages,
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.exception("LLM 调用失败")
        return 1

    text = _llm_text(resp)
    data = _parse_json_lenient(text)
    if data is None:
        snippet = (text or "")[:200]
        print(f"错误：LLM 输出无法解析为 JSON。片段：{snippet}", file=sys.stderr)
        return 1

    try:
        layout_file = LayoutFile.model_validate(data)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(x) for x in e["loc"])
            print(f"{loc}: {e['msg']}", file=sys.stderr)
        return 1

    errors, warnings = validate_layout_file(layout_file)
    if errors:
        for e in errors:
            print(f"{e.path}: {e.message}", file=sys.stderr)
        return 1
    for w in warnings:
        logger.warning(w)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(layout_file.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {output_path}")
    return 0


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="generate_gird", description="根据提示词生成布局意图 intent.json"
    )
    parser.add_argument("prompt", nargs="?", help="布局需求描述；未提供时从 stdin 读取")
    parser.add_argument(
        "--output",
        default="layout/intent_ir.json",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = _parse_args(argv)
    prompt = args.prompt
    if not prompt:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("错误：未提供提示词", file=sys.stderr)
        return 1
    output_path = Path(args.output).resolve()
    return asyncio.run(generate_intent(prompt, output_path))


if __name__ == "__main__":
    sys.exit(main())