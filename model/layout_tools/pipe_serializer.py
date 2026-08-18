from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

PIPE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "pipe_template.json"
PIPE_ROLE = "pipe"


class PipeTemplateError(ValueError):
    pass


class PipeConversionError(ValueError):
    pass


def load_pipe_template(path: Optional[Path] = None) -> dict:
    template_path = path or PIPE_TEMPLATE_PATH
    try:
        raw = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PipeTemplateError(f"pipe template missing or unreadable: {template_path}") from exc
    try:
        template = json.loads(raw)
    except ValueError as exc:
        raise PipeTemplateError(f"pipe template unparseable: {template_path}") from exc
    if not isinstance(template, dict):
        raise PipeTemplateError("pipe template must be an object")
    if template.get("c") != "ht.Edge":
        raise PipeTemplateError("pipe template c must be ht.Edge")
    if not isinstance(template.get("s"), dict):
        raise PipeTemplateError("pipe template s must be an object")
    return copy.deepcopy(template)


def is_managed_pipe_edge(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("c") != "ht.Edge":
        return False
    attrs = item.get("a")
    return isinstance(attrs, dict) and attrs.get("layout.role") == PIPE_ROLE


def _max_integer_i(items: list) -> int:
    maximum = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        i = item.get("i")
        if isinstance(i, int) and not isinstance(i, bool) and i > maximum:
            maximum = i
    return maximum


def next_edge_i(items: list) -> int:
    return _max_integer_i(items) + 1


def build_node_index(nodes: list) -> dict:
    index: dict[tuple, int] = {}
    seen_i: dict[int, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attrs = node.get("a")
        if not isinstance(attrs, dict):
            continue
        group = attrs.get("layout.group")
        node_name = attrs.get("layout.node")
        instance = attrs.get("layout.instance")
        if group is None or node_name is None or instance is None:
            continue
        i = node.get("i")
        if not isinstance(i, int) or isinstance(i, bool):
            raise PipeConversionError(
                f"node {group}/{node_name}/{instance}: i missing or not an integer"
            )
        key = (str(group), str(node_name), instance)
        if key in index:
            raise PipeConversionError(
                f"duplicate node key {group}/{node_name}/{instance}: endpoint keys must be unique"
            )
        if i in seen_i:
            raise PipeConversionError(
                f"node i {i} duplicated between {seen_i[i]} and {group}/{node_name}/{instance}"
            )
        index[key] = i
        seen_i[i] = f"{group}/{node_name}/{instance}"
    return index


def _resolve_endpoint(endpoint: Any, conn_index: int, side: str, index: dict) -> int:
    if not isinstance(endpoint, dict):
        raise PipeConversionError(f"connections[{conn_index}] {side} 端点不存在")
    group = endpoint.get("group")
    node_name = endpoint.get("node")
    instance = endpoint.get("instance")
    key = (str(group), str(node_name), instance)
    i = index.get(key)
    if i is None:
        raise PipeConversionError(
            f"connections[{conn_index}] {side} 端点不存在: {group}/{node_name}/{instance}"
        )
    return i


def build_edges(
    pipe_data: Any,
    node_index: dict,
    first_edge_i: int,
    template: Optional[dict] = None,
) -> list[dict]:
    if template is None:
        template = load_pipe_template()
    if not isinstance(pipe_data, dict):
        raise PipeConversionError("pipe_data must be an object")
    connections = pipe_data.get("connections")
    if not isinstance(connections, list):
        raise PipeConversionError("pipe_data.connections must be an array")
    seen: set[tuple[int, int]] = set()
    edges: list[dict] = []
    for idx, conn in enumerate(connections):
        if not isinstance(conn, dict):
            raise PipeConversionError(f"connections[{idx}] must be an object")
        source_i = _resolve_endpoint(conn.get("source"), idx, "source", node_index)
        target_i = _resolve_endpoint(conn.get("target"), idx, "target", node_index)
        pair = (source_i, target_i)
        if pair in seen:
            continue
        seen.add(pair)
        edge = copy.deepcopy(template)
        edge["i"] = first_edge_i + len(edges)
        p = edge.get("p")
        if not isinstance(p, dict):
            p = {}
            edge["p"] = p
        p["source"] = {"__i": source_i}
        p["target"] = {"__i": target_i}
        attrs = edge.get("a")
        if not isinstance(attrs, dict):
            attrs = {}
            edge["a"] = attrs
        attrs["layout.role"] = PIPE_ROLE
        edges.append(edge)
    return edges


def serialize_pipes(
    pipe_data: Any,
    nodes: list,
    first_edge_i: int,
    template: Optional[dict] = None,
) -> list[dict]:
    node_index = build_node_index(nodes)
    return build_edges(pipe_data, node_index, first_edge_i, template)
