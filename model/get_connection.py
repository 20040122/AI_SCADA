from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

_CONNECTION_MODEL = "deepseek-v4-flash"

_SECTION_PATTERN = re.compile(r"(?m)^\s*(管道)\s*[：:]")


class PipingSectionError(ValueError):
    pass


class ConnectionModelError(RuntimeError):
    pass


class ConnectionModelTimeoutError(ConnectionModelError):
    pass


class ConnectionModelUnavailableError(ConnectionModelError):
    pass


class ConnectionValidationError(ValueError):
    pass


class TopologyMismatchError(ValueError):
    pass


@dataclass
class ConnectionEnd:
    group: str
    node: str
    instance: int
    port: str


@dataclass
class ConnectionSpec:
    id: str
    source: ConnectionEnd
    target: ConnectionEnd


@dataclass
class TemplateEnd:
    group: str
    node: str
    port: str
    selector: Union[str, List[int]]


@dataclass
class ConnectionTemplate:
    source: TemplateEnd
    target: TemplateEnd


def _extract_piping_section(query: str) -> str:
    matches = list(_SECTION_PATTERN.finditer(query))
    for i, m in enumerate(matches):
        start = m.end()
        if i + 1 < len(matches):
            content = query[start:matches[i + 1].start()].strip()
        else:
            content = query[start:].strip()
        return content
    return ""


def _build_device_directory(ir_data: dict, pt_ir_nodes: list[dict]) -> dict:
    from collections import OrderedDict
    node_to_type = {}
    for g in ir_data["layoutIntent"]["groups"]:
        gid = g["id"]
        unit = g["unit"]
        node_to_type[(gid, unit["root"]["id"])] = unit["root"]["deviceType"]
        for att in unit.get("attachments", []):
            node_to_type[(gid, att["id"])] = att["deviceType"]
    dir = OrderedDict()
    for n in pt_ir_nodes:
        a = n.get("a", {})
        key = (a.get("layout.group"), a.get("layout.node"))
        inst = a.get("layout.instance")
        dt = node_to_type.get(key)
        if dt and key[0] is not None and key[1] is not None and inst is not None:
            dir.setdefault(dt, []).append((key[0], key[1], inst))
    return dir


def _build_llm_input(nodes: list[dict], piping_text: str) -> str:
    devices = []
    for n in nodes:
        a = n.get("a", {})
        p = n.get("p", {})
        devices.append({
            "group": a.get("layout.group"),
            "node": a.get("layout.node"),
            "instance": a.get("layout.instance"),
            "displayName": p.get("displayName", ""),
        })
    return json.dumps({"devices": devices, "piping": piping_text}, ensure_ascii=False)


_CHAIN_SPLIT = re.compile(r'[,;，；\n]+')
_CHAIN_DEVICE = re.compile(r'\s*(?:→|-)\s*')
_NAME_NUMBERED = re.compile(r'^(.+?)(\d+)$')


def _resolve_name(name: str, device_dir: dict) -> Tuple[str, str, int]:
    m = _NAME_NUMBERED.match(name)
    if m:
        dt, idx_str = m.group(1), m.group(2)
        idx = int(idx_str)
        instances = device_dir.get(dt)
        if not instances:
            raise TopologyMismatchError(f"设备类型不存在: {dt}")
        if idx < 1 or idx > len(instances):
            raise TopologyMismatchError(
                f"设备不存在: {name}。{dt} 共有 {len(instances)} 个实例"
            )
        return instances[idx - 1]
    instances = device_dir.get(name)
    if not instances:
        raise TopologyMismatchError(f"设备类型不存在: {name}")
    if len(instances) > 1:
        candidates = [f"{name}{i+1}" for i in range(len(instances))]
        raise TopologyMismatchError(
            f"设备名称 '{name}' 存在多个候选: {', '.join(candidates)}。请使用带编号名称。"
        )
    return instances[0]


def _try_parse_chains(text: str, device_dir: dict) -> Optional[List[List[Tuple[str, str, int, str, str, int]]]]:
    lines = _CHAIN_SPLIT.split(text.strip())
    chains = []
    found_chain = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = _CHAIN_DEVICE.split(line)
        if len(parts) < 2:
            continue
        found_chain = True
        resolved = []
        for part in parts:
            part = part.strip()
            if not part:
                raise TopologyMismatchError(f"显式链中存在空名称: {line}")
            resolved.append(_resolve_name(part, device_dir))
        edges = []
        for i in range(len(resolved) - 1):
            src = resolved[i]
            tgt = resolved[i + 1]
            edges.append((src[0], src[1], src[2], tgt[0], tgt[1], tgt[2]))
        chains.append(edges)
    if not found_chain:
        return None
    return chains


def chains_to_specs(chains: List[List[Tuple[str, str, int, str, str, int]]]) -> List[ConnectionSpec]:
    result = []
    for chain in chains:
        for edge in chain:
            result.append(ConnectionSpec(
                id="",
                source=ConnectionEnd(group=edge[0], node=edge[1], instance=edge[2], port=""),
                target=ConnectionEnd(group=edge[3], node=edge[4], instance=edge[5], port=""),
            ))
    return result


def _validate_exact_edges(actual: List[ConnectionSpec], expected: List[ConnectionSpec]):
    actual_set = set()
    for s in actual:
        actual_set.add((
            s.source.group, s.source.node, s.source.instance,
            s.target.group, s.target.node, s.target.instance,
        ))
    expected_set = set()
    for s in expected:
        expected_set.add((
            s.source.group, s.source.node, s.source.instance,
            s.target.group, s.target.node, s.target.instance,
        ))
    missing = expected_set - actual_set
    extra = actual_set - expected_set
    reversed_edges = []
    for e in extra:
        rev = (e[3], e[4], e[5], e[0], e[1], e[2])
        if rev in expected_set:
            reversed_edges.append(e)
    issues = []
    if missing:
        ms = [f"({m[0]}/{m[1]} inst {m[2]})→({m[3]}/{m[4]} inst {m[5]})" for m in sorted(missing)]
        issues.append(f"缺失边: {', '.join(ms)}")
    if reversed_edges:
        rs = [f"({r[0]}/{r[1]} inst {r[2]})→({r[3]}/{r[4]} inst {r[5]}) 方向相反" for r in sorted(reversed_edges)]
        issues.append(f"反向边: {', '.join(rs)}")
    extra_clean = extra - set(reversed_edges)
    if extra_clean:
        es = [f"({e[0]}/{e[1]} inst {e[2]})→({e[3]}/{e[4]} inst {e[5]})" for e in sorted(extra_clean)]
        issues.append(f"额外边: {', '.join(es)}")
    if issues:
        raise TopologyMismatchError("; ".join(issues))


def _validate_selector(
    selector: Any,
    endpoint_key: Tuple[str, str],
    nodes: list[dict],
) -> Optional[str]:
    if isinstance(selector, str):
        if selector == "all":
            return None
        return "selector 必须是 'all' 或数组"
    if isinstance(selector, list):
        if not selector:
            return "selector 数组不能为空"
        group, node = endpoint_key
        available: set = set()
        for n in nodes:
            a = n.get("a", {})
            if a.get("layout.group") == group and a.get("layout.node") == node:
                available.add(a.get("layout.instance"))
        seen: set = set()
        for inst in selector:
            if not isinstance(inst, int):
                return f"selector 数组元素非法: {inst}"
            if inst in seen:
                return f"selector 数组包含重复实例: {inst}"
            seen.add(inst)
            if inst not in available:
                return f"selector 数组包含不存在实例: {inst}"
        return None
    return "selector 必须是 'all' 或数组"


def _validate_connections(
    raw: list[dict], pt_ir_nodes: list[dict]
) -> Tuple[List[ConnectionTemplate], List[str]]:
    node_map: dict = {}
    for n in pt_ir_nodes:
        a = n.get("a", {})
        key = (a.get("layout.group"), a.get("layout.node"))
        if key[0] is not None and key[1] is not None:
            node_map[key] = n

    valid_ports = {"top", "right", "bottom", "left"}
    templates: List[ConnectionTemplate] = []
    errors: List[str] = []

    for i, conn in enumerate(raw):
        src = conn.get("source", {})
        tgt = conn.get("target", {})

        sk = (src.get("group"), src.get("node"))
        tk = (tgt.get("group"), tgt.get("node"))

        if sk not in node_map:
            errors.append(f"connections[{i}] source 端点不存在")
            continue
        if tk not in node_map:
            errors.append(f"connections[{i}] target 端点不存在")
            continue
        if sk == tk:
            errors.append(f"connections[{i}] 端点自连")
            continue
        if src.get("port") not in valid_ports:
            errors.append(f"connections[{i}] source 端口非法")
            continue
        if tgt.get("port") not in valid_ports:
            errors.append(f"connections[{i}] target 端口非法")
            continue

        src_sel = src.get("selector", "all")
        tgt_sel = tgt.get("selector", "all")

        src_err = _validate_selector(src_sel, sk, pt_ir_nodes)
        if src_err:
            errors.append("connections[{}] source {}".format(i, src_err))
            continue
        tgt_err = _validate_selector(tgt_sel, tk, pt_ir_nodes)
        if tgt_err:
            errors.append("connections[{}] target {}".format(i, tgt_err))
            continue

        templates.append(ConnectionTemplate(
            source=TemplateEnd(
                group=src["group"], node=src["node"],
                port=src["port"], selector=src_sel,
            ),
            target=TemplateEnd(
                group=tgt["group"], node=tgt["node"],
                port=tgt["port"], selector=tgt_sel,
            ),
        ))

    return templates, errors


def _group_instances(nodes: list[dict]) -> dict:
    instances = {}
    for n in nodes:
        a = n.get("a", {})
        key = (a.get("layout.group"), a.get("layout.node"))
        inst = a.get("layout.instance")
        if key[0] is not None and key[1] is not None and inst is not None:
            instances.setdefault(key, set()).add(inst)
    return instances


def _deduplicate_templates(
    templates: List[ConnectionTemplate],
) -> List[ConnectionTemplate]:
    seen = set()
    result = []
    for t in templates:
        key = (
            t.source.group, t.source.node, t.source.port,
            t.target.group, t.target.node, t.target.port,
        )
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def _resolve_selector(
    selector: Union[str, List[int]],
    endpoint_key: Tuple[str, str],
    node_instances: dict,
) -> List[int]:
    all_instances = sorted(node_instances.get(endpoint_key, set()))
    if selector == "all":
        return all_instances
    if isinstance(selector, list):
        return sorted(selector)
    return []


def _deduplicate_specs(
    specs: List[ConnectionSpec],
) -> List[ConnectionSpec]:
    seen = set()
    result = []
    for s in specs:
        key = (
            s.source.group, s.source.node, s.source.instance, s.source.port,
            s.target.group, s.target.node, s.target.instance, s.target.port,
        )
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def _normalize_ports(
    specs: List[ConnectionSpec],
    pt_ir_nodes: list[dict],
) -> List[ConnectionSpec]:
    center_map = {}
    for n in pt_ir_nodes:
        a = n.get("a", {})
        p = n.get("p", {})
        pos = p.get("position", {})
        w = p.get("width", 0) or 0
        h = p.get("height", 0) or 0
        key = (a.get("layout.group"), a.get("layout.node"), a.get("layout.instance"))
        if key[0] is not None and key[1] is not None and key[2] is not None:
            center_map[key] = (pos.get("x", 0) + w / 2, pos.get("y", 0) + h / 2)

    result = []
    for spec in specs:
        src_key = (spec.source.group, spec.source.node, spec.source.instance)
        tgt_key = (spec.target.group, spec.target.node, spec.target.instance)
        src_c = center_map.get(src_key)
        tgt_c = center_map.get(tgt_key)
        if src_c is None or tgt_c is None:
            result.append(spec)
            continue
        if src_c == tgt_c:
            raise TopologyMismatchError(
                f"节点中心重合: ({src_key[0]}/{src_key[1]} inst {src_key[2]}) "
                f"与 ({tgt_key[0]}/{tgt_key[1]} inst {tgt_key[2]})"
            )
        dx = tgt_c[0] - src_c[0]
        dy = tgt_c[1] - src_c[1]
        if abs(dx) >= abs(dy):
            if dx >= 0:
                src_port, tgt_port = "right", "left"
            else:
                src_port, tgt_port = "left", "right"
        else:
            if dy >= 0:
                src_port, tgt_port = "bottom", "top"
            else:
                src_port, tgt_port = "top", "bottom"
        result.append(ConnectionSpec(
            id=spec.id,
            source=ConnectionEnd(
                group=spec.source.group, node=spec.source.node,
                instance=spec.source.instance, port=src_port,
            ),
            target=ConnectionEnd(
                group=spec.target.group, node=spec.target.node,
                instance=spec.target.instance, port=tgt_port,
            ),
        ))
    return result


def _expand_templates(
    templates: List[ConnectionTemplate],
    node_instances: dict,
) -> List[ConnectionSpec]:
    result = []
    for tmpl in templates:
        src_key = (tmpl.source.group, tmpl.source.node)
        tgt_key = (tmpl.target.group, tmpl.target.node)

        src_instances = _resolve_selector(tmpl.source.selector, src_key, node_instances)
        tgt_instances = _resolve_selector(tmpl.target.selector, tgt_key, node_instances)

        for src_inst in sorted(src_instances):
            for tgt_inst in sorted(tgt_instances):
                result.append(ConnectionSpec(
                    id="",
                    source=ConnectionEnd(
                        group=tmpl.source.group,
                        node=tmpl.source.node,
                        instance=src_inst,
                        port=tmpl.source.port,
                    ),
                    target=ConnectionEnd(
                        group=tmpl.target.group,
                        node=tmpl.target.node,
                        instance=tgt_inst,
                        port=tmpl.target.port,
                    ),
                ))

    for i, spec in enumerate(result, 1):
        spec.id = f"pipe-{i}"

    return result


async def _call_connection_model(client, model, messages, **kwargs):
    timeout = 15
    from openai import APITimeoutError
    try:
        request_client = client.with_options(max_retries=0, timeout=timeout)
        return await asyncio.wait_for(
            request_client.chat.completions.create(
                model=model, messages=messages, **kwargs
            ),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, APITimeoutError) as exc:
        raise ConnectionModelTimeoutError("连接模型请求超时") from exc


async def generate_connections(
    query: str,
    pt_ir_nodes: list[dict],
    client,
    model: Optional[str] = None,
    ir_data: Optional[dict] = None,
) -> Optional[dict]:
    piping_text = _extract_piping_section(query)
    if not piping_text:
        logger.info("管道段缺失或为空，跳过连接生成")
        return None

    if not pt_ir_nodes:
        logger.warning("pt_ir 节点为空，跳过连接生成")
        return None

    device_dir = _build_device_directory(ir_data, pt_ir_nodes) if ir_data else None
    chains = _try_parse_chains(piping_text, device_dir) if device_dir else None

    model = model or _CONNECTION_MODEL
    llm_input = _build_llm_input(pt_ir_nodes, piping_text)

    from model.layout_agent import _llm_text, _parse_json_lenient

    system_prompt = (
        "你是SCADA管线拓扑识别器。根据设备列表和用户管道描述，识别管道连接模板。\n"
        "设备由 group/node 标识，每个设备有若干实例(instance)。\n"
        "输出连接模板，每个连接由 source 和 target 构成，每个端点使用 selector 表示实例选择：\n"
        '  - 数组如 [1] 表示仅连接 1 号实例，[2] 表示仅连接 2 号实例\n'
        '  - "all" 表示连接该端点的所有实例（只用于明确的全连接关系）\n'
        "输出格式：\n"
        "{\n"
        '  "connections": [\n'
        "    {\n"
        '      "source": {"group": "...", "node": "...", "selector": [1], "port": "right"},\n'
        '      "target": {"group": "...", "node": "...", "selector": [1], "port": "left"}\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "端口可为 top/right/bottom/left 之一。\n"
        "一一对应支路必须输出 [1]→[1]、[2]→[2] 等单实例模板。\n"
        "禁止将全矩阵关系缩减为同编号一一对应。用 selector [1],[2] 表达一一对应。\n"
        "只输出 JSON，不要解释或 markdown。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": llm_input},
    ]

    try:
        resp = await _call_connection_model(
            client, model, messages,
            response_format={"type": "json_object"},
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except ConnectionModelTimeoutError:
        raise
    except ConnectionModelError:
        raise
    except Exception as exc:
        logger.exception("连接模型调用失败")
        raise ConnectionModelUnavailableError("连接模型不可用") from exc

    text = _llm_text(resp)
    data = _parse_json_lenient(text)
    if data is None:
        raise ConnectionModelError(
            f"连接模型输出无法解析为 JSON：{(text or '')[:200]}"
        )

    raw_connections = data.get("connections", []) if isinstance(data, dict) else []
    if not isinstance(raw_connections, list):
        raise ConnectionModelError("连接模型输出格式无效：connections 非数组")

    templates, errors = _validate_connections(raw_connections, pt_ir_nodes)
    if errors:
        details = "; ".join(errors)
        raise ConnectionValidationError(details)

    if not templates:
        raise ConnectionValidationError("无法明确至少一条 source-target 连接")

    node_instances = _group_instances(pt_ir_nodes)
    expanded = _expand_templates(templates, node_instances)
    expanded = _deduplicate_specs(expanded)
    expanded = _normalize_ports(expanded, pt_ir_nodes)

    if chains is not None:
        expected = chains_to_specs(chains)
        _validate_exact_edges(expanded, expected)
        spec_map = {}
        for s in expanded:
            fwd = (s.source.group, s.source.node, s.source.instance,
                   s.target.group, s.target.node, s.target.instance)
            rev = (s.target.group, s.target.node, s.target.instance,
                   s.source.group, s.source.node, s.source.instance)
            spec_map[fwd] = (s.source.port, s.target.port)
            spec_map[rev] = (s.target.port, s.source.port)
        ordered = []
        idx = 1
        for chain in chains:
            for edge in chain:
                ports = spec_map.get(edge)
                if ports is None:
                    continue
                ordered.append(ConnectionSpec(
                    id=f"pipe-{idx}",
                    source=ConnectionEnd(group=edge[0], node=edge[1], instance=edge[2], port=ports[0]),
                    target=ConnectionEnd(group=edge[3], node=edge[4], instance=edge[5], port=ports[1]),
                ))
                idx += 1
        expanded = ordered
    else:
        if not expanded:
            raise ConnectionValidationError("展开结果为空，无有效连接")

    for i, spec in enumerate(expanded, 1):
        spec.id = f"pipe-{i}"

    connections_out = []
    for spec in expanded:
        connections_out.append({
            "id": spec.id,
            "source": {
                "group": spec.source.group,
                "node": spec.source.node,
                "instance": spec.source.instance,
                "port": spec.source.port,
            },
            "target": {
                "group": spec.target.group,
                "node": spec.target.node,
                "instance": spec.target.instance,
                "port": spec.target.port,
            },
        })

    return {"connections": connections_out}
