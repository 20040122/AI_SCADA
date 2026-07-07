import json

from model.compute_position import convert_layout_file


def _node(nodes, group, node, instance=1):
    for item in nodes:
        attrs = item.get("a") or {}
        if (
            attrs.get("layout.group") == group
            and attrs.get("layout.node") == node
            and attrs.get("layout.instance") == instance
        ):
            return item
    raise AssertionError((group, node, instance))


def _intent(groups):
    return {"layoutIntent": {"groups": groups, "connections": []}}


def test_convert_layout_file_uses_query_result_size_limits_and_relative_positions():
    data = _intent(
        [
            {
                "id": "group_left",
                "region": "left",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": [
                        {
                            "id": "valve",
                            "deviceType": "阀门",
                            "relativeTo": "root",
                            "side": "top",
                        },
                        {
                            "id": "pipe",
                            "deviceType": "管道",
                            "relativeTo": "valve",
                            "side": "right",
                        },
                    ],
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 2000, "height": 3000},
        {"displayName": "阀门", "image": "valve.json", "width": 5, "height": 5},
        {"displayName": "管道", "image": "pipe.json", "width": 400, "height": 80},
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    root = _node(nodes, "group_left", "root")
    valve = _node(nodes, "group_left", "valve")
    pipe = _node(nodes, "group_left", "pipe")

    assert root["p"]["image"] == "tank.json"
    assert root["p"]["width"] <= 180
    assert root["p"]["height"] <= 260
    assert valve["p"]["width"] >= 40
    assert valve["p"]["height"] >= 40
    assert valve["p"]["position"]["y"] < root["p"]["position"]["y"]
    assert pipe["p"]["position"]["x"] > valve["p"]["position"]["x"]


def test_convert_layout_file_arranges_repeated_group_vertically_in_right_region():
    data = _intent(
        [
            {
                "id": "group_right",
                "region": "right",
                "unit": {
                    "root": {"id": "root", "deviceType": "氮气罐"},
                    "attachments": [
                        {
                            "id": "valve",
                            "deviceType": "阀门",
                            "relativeTo": "root",
                            "side": "top",
                        }
                    ],
                },
                "count": 2,
                "arrangement": "vertical",
            }
        ]
    )
    controls = [
        {"displayName": "氮气罐", "image": "n2.json", "width": 160, "height": 240},
        {"displayName": "阀门", "image": "valve.json", "width": 60, "height": 60},
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    first = _node(nodes, "group_right", "root", 1)
    second = _node(nodes, "group_right", "root", 2)

    assert first["p"]["position"]["x"] > 960
    assert second["p"]["position"]["x"] > 960
    assert second["p"]["position"]["y"] > first["p"]["position"]["y"]
    assert second["p"]["displayName"] == "氮气罐2"


def test_convert_layout_file_scales_long_unit_to_fit_canvas():
    attachments = []
    previous = "root"
    for index in range(8):
        node_id = "pipe" if index == 0 else "pipe%s" % (index + 1)
        attachments.append(
            {
                "id": node_id,
                "deviceType": "管道",
                "relativeTo": previous,
                "side": "right",
            }
        )
        previous = node_id
    data = _intent(
        [
            {
                "id": "group_center",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": attachments,
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 160, "height": 240},
        {"displayName": "管道", "image": "pipe.json", "width": 600, "height": 80},
    ]

    nodes = convert_layout_file(data, controls=controls, width=800, height=600)
    generated = [n for n in nodes if (n.get("a") or {}).get("layout.group")]

    for item in generated:
        p = item["p"]
        x = p["position"]["x"]
        y = p["position"]["y"]
        assert x - p["width"] / 2 >= 0
        assert x + p["width"] / 2 <= 800
        assert y - p["height"] / 2 >= 0
        assert y + p["height"] / 2 <= 600


def test_convert_layout_file_keeps_dense_repeated_groups_positive_size():
    data = _intent(
        [
            {
                "id": "group_center",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": [],
                },
                "count": 30,
                "arrangement": "vertical",
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 160, "height": 240}
    ]

    nodes = convert_layout_file(data, controls=controls, width=800, height=600)
    generated = [n for n in nodes if (n.get("a") or {}).get("layout.group")]

    assert len(generated) == 30
    for item in generated:
        assert item["p"]["width"] > 0
        assert item["p"]["height"] > 0


def test_convert_layout_file_falls_back_for_extreme_material_aspect_ratio():
    data = _intent(
        [
            {
                "id": "group_center",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": [
                        {
                            "id": "valve",
                            "deviceType": "阀门",
                            "relativeTo": "root",
                            "side": "top",
                        }
                    ],
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 160, "height": 240},
        {"displayName": "阀门", "image": "valve.json", "width": 1, "height": 1000},
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    valve = _node(nodes, "group_center", "valve")

    assert valve["p"]["width"] >= 40
    assert valve["p"]["height"] >= 40
    assert valve["p"]["width"] <= 80
    assert valve["p"]["height"] <= 80


def test_convert_layout_file_expands_attachment_count_with_unique_node_ids():
    data = _intent(
        [
            {
                "id": "group_center",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": [
                        {
                            "id": "valve",
                            "deviceType": "阀门",
                            "relativeTo": "root",
                            "side": "top",
                            "count": 2,
                        }
                    ],
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 160, "height": 240},
        {"displayName": "阀门", "image": "valve.json", "width": 60, "height": 60},
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    valves = [
        item
        for item in nodes
        if (item.get("a") or {}).get("layout.node") in {"valve", "valve_2"}
    ]

    assert {item["a"]["layout.node"] for item in valves} == {"valve", "valve_2"}
    assert valves[0]["p"]["position"]["x"] != valves[1]["p"]["position"]["x"]
    assert valves[0]["p"]["displayName"] == "阀门"
    assert valves[1]["p"]["displayName"] == "阀门2"


def test_convert_layout_file_ignores_canvas_json_materials(tmp_path):
    canvas_path = tmp_path / "scene.json"
    canvas_path.write_text(
        json.dumps(
            {
                "v": "8.0.5",
                "p": {
                    "layers": [],
                    "autoAdjustIndex": True,
                    "hierarchicalRendering": True,
                },
                "a": {
                    "width": 1920,
                    "height": 1080,
                    "fitContent": True,
                    "rectSelectable": False,
                    "zoomable": False,
                    "pannable": False,
                },
                "d": [],
                "contentRect": {"x": 0, "y": 0, "width": 0, "height": 0},
            }
        ),
        encoding="utf-8",
    )
    data = _intent(
        [
            {
                "id": "group_center",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐"},
                    "attachments": [],
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {
            "displayName": "空气罐画布",
            "image": str(canvas_path),
            "width": 1920,
            "height": 1080,
        }
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    root = _node(nodes, "group_center", "root")

    assert root["p"]["image"] == "symbols/Agent/空气罐.json"


def test_convert_layout_file_role_layering_explicit_keyword_default():
    data = _intent(
        [
            {
                "id": "group_role",
                "region": "center",
                "unit": {
                    "root": {"id": "root", "deviceType": "空气罐", "role": "root"},
                    "attachments": [
                        {
                            "id": "explicit",
                            "deviceType": "阀门",
                            "role": "meter",
                            "relativeTo": "root",
                            "side": "top",
                        },
                        {
                            "id": "keyword",
                            "deviceType": "阀门",
                            "relativeTo": "root",
                            "side": "bottom",
                        },
                        {
                            "id": "fallback",
                            "deviceType": "水泵",
                            "relativeTo": "root",
                            "side": "right",
                        },
                    ],
                },
                "count": 1,
            }
        ]
    )
    controls = [
        {"displayName": "空气罐", "image": "tank.json", "width": 160, "height": 240},
        {"displayName": "阀门", "image": "valve.json", "width": 1000, "height": 1000},
        {"displayName": "水泵", "image": "pump.json", "width": 1000, "height": 1000},
    ]

    nodes = convert_layout_file(data, controls=controls, width=1920, height=1080)
    explicit = _node(nodes, "group_role", "explicit")
    keyword = _node(nodes, "group_role", "keyword")
    fallback = _node(nodes, "group_role", "fallback")

    assert explicit["p"]["width"] == 100
    assert explicit["p"]["height"] == 100
    assert keyword["p"]["width"] == 80
    assert keyword["p"]["height"] == 80
    assert fallback["p"]["width"] == 120
    assert fallback["p"]["height"] == 120
