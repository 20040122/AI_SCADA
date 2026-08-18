from __future__ import annotations

import json
from pathlib import Path

import pytest

from model.layout_tools.pipe_serializer import (
    PipeConversionError,
    PipeTemplateError,
    build_edges,
    is_managed_pipe_edge,
    load_pipe_template,
    next_edge_i,
    serialize_pipes,
)

TEMPLATE = {
    "c": "ht.Edge",
    "i": 16335,
    "p": {"source": {"__i": 16295}, "target": {"__i": 16299}},
    "s": {
        "edge.width": 5,
        "edge.color": "#60acfc",
        "edge.gap": 24,
        "edge.corner.radius": 20,
        "edge.dash": True,
        "edge.dash.color": "#b8daff",
        "edge.dash.pattern": [20, 20],
        "edge.dash.width": 4,
        "note.background": "#60acfc",
        "note.border.color": "#3d3d3d",
        "edge.type": "flex2",
        "opacity": 1,
        "edge.dash.flow": True,
    },
}


@pytest.fixture
def template_path(tmp_path: Path) -> Path:
    path = tmp_path / "pipe_template.json"
    path.write_text(json.dumps(TEMPLATE), encoding="utf-8")
    return path


def _node(i: int, group: str, name: str, instance: int) -> dict:
    return {
        "c": "ht.Node",
        "i": i,
        "p": {"displayName": name, "position": {"x": 0, "y": 0}},
        "a": {"layout.group": group, "layout.node": name, "layout.instance": instance},
    }


def _conn(sg: str, sn: str, si: int, tg: str, tn: str, ti: int, port: str = "right") -> dict:
    return {
        "id": f"{sg}-{sn}-{si}-{tg}-{tn}-{ti}",
        "source": {"group": sg, "node": sn, "instance": si, "port": port},
        "target": {"group": tg, "node": tn, "instance": ti, "port": "left"},
    }


class TestLoadTemplate:
    def test_loads_valid_template(self, template_path: Path):
        template = load_pipe_template(template_path)
        assert template == TEMPLATE

    def test_template_not_mutated_by_edges(self, template_path: Path):
        template = load_pipe_template(template_path)
        nodes = [_node(100, "g", "a", 1), _node(101, "g", "b", 1)]
        serialize_pipes({"connections": [_conn("g", "a", 1, "g", "b", 1)]}, nodes, 200, template)
        assert template == TEMPLATE

    def test_missing_template_fails(self, tmp_path: Path):
        with pytest.raises(PipeTemplateError) as exc_info:
            load_pipe_template(tmp_path / "nope.json")
        assert "missing" in str(exc_info.value)

    def test_unparseable_template_fails(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(PipeTemplateError) as exc_info:
            load_pipe_template(path)
        assert "unparseable" in str(exc_info.value)

    def test_non_object_template_fails(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([]), encoding="utf-8")
        with pytest.raises(PipeTemplateError) as exc_info:
            load_pipe_template(path)
        assert "object" in str(exc_info.value)

    def test_wrong_c_fails(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({**TEMPLATE, "c": "ht.Node"}), encoding="utf-8")
        with pytest.raises(PipeTemplateError) as exc_info:
            load_pipe_template(path)
        assert "ht.Edge" in str(exc_info.value)

    def test_non_object_s_fails(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({**TEMPLATE, "s": "oops"}), encoding="utf-8")
        with pytest.raises(PipeTemplateError) as exc_info:
            load_pipe_template(path)
        assert "s must be an object" in str(exc_info.value)


class TestSerializePipes:
    def test_maps_known_nodes_to_i(self, template_path: Path):
        nodes = [
            _node(20399, "coolingTowers", "CT1", 1),
            _node(20402, "coolingPumps", "CP1", 1),
        ]
        edges = serialize_pipes(
            {"connections": [_conn("coolingTowers", "CT1", 1, "coolingPumps", "CP1", 1)]},
            nodes,
            next_edge_i(nodes),
            load_pipe_template(template_path),
        )
        assert len(edges) == 1
        assert edges[0]["p"] == {
            "source": {"__i": 20399},
            "target": {"__i": 20402},
        }
        assert edges[0]["i"] == 20403

    def test_edge_inherits_template_style_and_marks_role(self, template_path: Path):
        nodes = [_node(100, "g", "a", 1), _node(101, "g", "b", 1)]
        edges = serialize_pipes(
            {"connections": [_conn("g", "a", 1, "g", "b", 1)]},
            nodes,
            next_edge_i(nodes),
            load_pipe_template(template_path),
        )
        edge = edges[0]
        assert edge["c"] == "ht.Edge"
        assert edge["s"] == TEMPLATE["s"]
        assert edge["a"] == {"layout.role": "pipe"}
        assert edge["i"] != TEMPLATE["i"]
        assert edge["p"]["source"] != TEMPLATE["p"]["source"]
        assert edge["p"]["target"] != TEMPLATE["p"]["target"]

    def test_output_has_no_port_or_endpoint_fields(self, template_path: Path):
        nodes = [
            _node(10, "g", "a", 1),
            _node(11, "g", "b", 1),
            _node(12, "g", "c", 1),
        ]
        edges = serialize_pipes(
            {"connections": [_conn("g", "a", 1, "g", "b", 1), _conn("g", "b", 1, "g", "c", 1)]},
            nodes,
            next_edge_i(nodes),
            load_pipe_template(template_path),
        )
        raw = json.dumps(edges)
        for forbidden in ("port", "group", "node", "instance"):
            assert forbidden not in raw
        assert "__i" in raw

    def test_dedupe_keeps_first_reverse_kept_order_stable(self, template_path: Path):
        nodes = [
            _node(10, "g", "a", 1),
            _node(11, "g", "b", 1),
            _node(12, "g", "c", 1),
        ]
        pipe_data = {
            "connections": [
                _conn("g", "a", 1, "g", "b", 1, port="right"),
                _conn("g", "b", 1, "g", "a", 1, port="left"),
                _conn("g", "a", 1, "g", "b", 1, port="bottom"),
                _conn("g", "a", 1, "g", "c", 1),
            ]
        }
        template = load_pipe_template(template_path)
        first = serialize_pipes(pipe_data, nodes, next_edge_i(nodes), template)
        second = serialize_pipes(pipe_data, nodes, next_edge_i(nodes), template)
        assert first == second
        assert len(first) == 3
        assert [(e["p"]["source"]["__i"], e["p"]["target"]["__i"]) for e in first] == [
            (10, 11),
            (11, 10),
            (10, 12),
        ]
        assert [e["i"] for e in first] == [13, 14, 15]

    def test_empty_connections_produce_empty_edges(self, template_path: Path):
        nodes = [_node(10, "g", "a", 1)]
        edges = serialize_pipes(
            {"connections": []},
            nodes,
            next_edge_i(nodes),
            load_pipe_template(template_path),
        )
        assert edges == []

    def test_next_edge_i_skips_non_integer(self):
        assert next_edge_i([]) == 1
        assert next_edge_i([{"i": "5"}, {"i": 3}, {"i": 10}, {"c": "ht.Edge"}]) == 11


class TestSerializePipesErrors:
    def test_missing_endpoint_fails_with_connection_and_side(self, template_path: Path):
        nodes = [_node(10, "g", "a", 1)]
        with pytest.raises(PipeConversionError) as exc_info:
            serialize_pipes(
                {"connections": [_conn("g", "a", 1, "g", "ghost", 1)]},
                nodes,
                20,
                load_pipe_template(template_path),
            )
        message = str(exc_info.value)
        assert "connections[0]" in message
        assert "target" in message
        assert "g/ghost/1" in message

    def test_duplicate_endpoint_key_fails(self, template_path: Path):
        nodes = [_node(10, "g", "a", 1), _node(11, "g", "a", 1)]
        with pytest.raises(PipeConversionError) as exc_info:
            serialize_pipes({"connections": []}, nodes, 20, load_pipe_template(template_path))
        assert "duplicate node key" in str(exc_info.value)

    def test_missing_node_i_fails(self, template_path: Path):
        node = _node(10, "g", "a", 1)
        del node["i"]
        with pytest.raises(PipeConversionError) as exc_info:
            serialize_pipes({"connections": []}, [node], 20, load_pipe_template(template_path))
        assert "i missing" in str(exc_info.value)

    def test_non_integer_node_i_fails(self, template_path: Path):
        node = _node(10, "g", "a", 1)
        node["i"] = "10"
        with pytest.raises(PipeConversionError) as exc_info:
            serialize_pipes({"connections": []}, [node], 20, load_pipe_template(template_path))
        assert "not an integer" in str(exc_info.value)

    def test_duplicate_node_i_fails(self, template_path: Path):
        nodes = [_node(10, "g", "a", 1), _node(10, "g", "b", 1)]
        with pytest.raises(PipeConversionError) as exc_info:
            serialize_pipes({"connections": []}, nodes, 20, load_pipe_template(template_path))
        assert "node i 10 duplicated" in str(exc_info.value)

    def test_invalid_template_blocks_edge_generation(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"c": "ht.Node", "s": {}}), encoding="utf-8")
        with pytest.raises(PipeTemplateError):
            build_edges({"connections": []}, {}, 1, load_pipe_template(path))

    def test_pipe_data_not_object_fails(self, template_path: Path):
        with pytest.raises(PipeConversionError) as exc_info:
            build_edges("nope", {}, 1, load_pipe_template(template_path))
        assert "must be an object" in str(exc_info.value)

    def test_connections_not_array_fails(self, template_path: Path):
        with pytest.raises(PipeConversionError) as exc_info:
            build_edges({"connections": "nope"}, {}, 1, load_pipe_template(template_path))
        assert "must be an array" in str(exc_info.value)


class TestManagedEdgeDetection:
    def test_managed_edge_detected(self):
        edge = {"c": "ht.Edge", "i": 1, "p": {}, "s": {}, "a": {"layout.role": "pipe"}}
        assert is_managed_pipe_edge(edge)

    def test_other_edges_not_detected(self):
        assert not is_managed_pipe_edge({"c": "ht.Edge", "i": 1, "p": {}, "s": {}})
        assert not is_managed_pipe_edge({"c": "ht.Node", "i": 1, "a": {"layout.role": "pipe"}})
        assert not is_managed_pipe_edge({"c": "ht.Edge", "a": {"layout.role": "other"}})
        assert not is_managed_pipe_edge(None)
        assert not is_managed_pipe_edge("x")
