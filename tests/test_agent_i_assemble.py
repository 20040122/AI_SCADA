from copy import deepcopy

import pytest

from picture.AgentI.assemble.compile import compile_canvas
from picture.AgentI.assemble.control import match_material


def make_detection(kind, value):
    return {
        "type": kind,
        "value": value,
        "position": {"x": 10, "y": 20},
        "width": 30,
        "height": 40,
    }


@pytest.fixture
def materials():
    return [
        {"displayName": "冷却泵", "image": "cooling.png"},
        {"displayName": "冷冻泵", "image": "chilled.png"},
    ]


@pytest.mark.parametrize("value", ["冷却泵", "  冷却泵  ", "冷却泵(unknow)"])
def test_material_matches_exact_name(value, materials):
    assert match_material(value, materials) is materials[0]


@pytest.mark.parametrize("value", ["泵(unknow)", "冷却(unknow)", "冷却泵备用(unknow)", "泵", "冷却泵#1", "", None])
def test_material_rejects_partial_and_unknown_names(value, materials):
    assert match_material(value, materials) is None


@pytest.mark.parametrize("control_start,text_start", [(16861, 16756), (1, 1), (1, 2)])
def test_canvas_ids_are_unique_across_controls_and_texts(control_start, text_start, materials):
    canvas_template = {"d": [], "a": {"width": 1920}}
    control_template = {"c": "ht.Node", "i": control_start, "p": {}}
    text_template = {"c": "ht.Text", "i": text_start, "p": {}, "s": {}}
    detections = [make_detection("controls", "泵(unknow)")]
    detections.extend(make_detection("controls", "冷却泵") for _ in range(150))
    detections.extend(make_detection("text", str(index)) for index in range(106))
    originals = deepcopy((detections, canvas_template, text_template, control_template, materials))

    canvas, unmatched = compile_canvas(detections, canvas_template, text_template, control_template, materials)

    identifiers = [node["i"] for node in canvas["d"]]
    assert identifiers == list(range(min(control_start, text_start), min(control_start, text_start) + 256))
    assert len(set(identifiers)) == 256
    assert unmatched == ["泵(unknow)"]
    assert all(node["p"]["image"] == "cooling.png" for node in canvas["d"][:150])
    assert [node["s"]["text"] for node in canvas["d"][150:]] == [str(index) for index in range(106)]
    assert (detections, canvas_template, text_template, control_template, materials) == originals


@pytest.mark.parametrize("kinds", [[], ["text"], ["controls"]])
def test_canvas_handles_empty_or_single_node_type(kinds, materials):
    detections = [make_detection(kind, "冷却泵") for kind in kinds]
    canvas, unmatched = compile_canvas(
        detections,
        {"d": []},
        {"c": "ht.Text", "i": 1, "p": {}, "s": {}},
        {"c": "ht.Node", "i": 1, "p": {}},
        materials,
    )

    assert len(canvas["d"]) == len(kinds)
    assert unmatched == []
