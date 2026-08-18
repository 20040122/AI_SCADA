from __future__ import annotations

from model.layout_tools.compute_position import _fit_size, convert_layout_file
from model.layout_tools.geometry import (
    content_rect_of_nodes,
    fit_size,
    inscribe_ratio,
    ratio_error,
)


class TestFitSizeBranches:
    def test_original_size_when_fits(self):
        w, h = fit_size(80, 60, 50, 40, 120, 120)
        assert w == 80
        assert h == 60

    def test_enlarge_uniform_to_min(self):
        w, h = fit_size(30, 20, 50, 40, 120, 120)
        assert w == 60
        assert h == 40

    def test_shrink_uniform_to_max(self):
        w, h = fit_size(300, 200, 50, 40, 120, 120)
        assert w == 120
        assert h == 80

    def test_unsatisfiable_uses_max_scale(self):
        w, h = fit_size(500, 100, 50, 40, 120, 120)
        assert ratio_error(w, h, 500, 100) <= 0.001
        assert w <= 120
        assert h <= 120

    def test_unsatisfiable_one_side_below_min(self):
        w, h = fit_size(500, 100, 50, 40, 120, 120)
        assert w >= 120 or h >= 120
        assert ratio_error(w, h, 500, 100) <= 0.001


ROOT_MATERIALS = [
    ("冷水机", 232, 136),
    ("油箱", 316, 175),
    ("电机", 154, 80),
    ("液压泵", 154, 70),
    ("吸油过滤器", 30, 70),
    ("回油单向阀", 65, 35),
]


class TestRootMaterialRatio:
    def test_all_six_materials_keep_ratio(self):
        for name, sw, sh in ROOT_MATERIALS:
            width, height, _, _ = _fit_size(name, True, {"width": sw, "height": sh})
            assert ratio_error(width, height, sw, sh) <= 0.001, name

    def test_satisfiable_default_role_keeps_ratio(self):
        width, height, _, _ = _fit_size("阀门", False, {"width": 64, "height": 64})
        assert ratio_error(width, height, 64, 64) <= 0.001


class TestInscribeRatio:
    def test_shrink_only(self):
        w, h = inscribe_ratio(200, 100, 1.0)
        assert w <= 200
        assert h <= 100
        assert ratio_error(w, h, 1, 1) <= 0.001

    def test_never_enlarges(self):
        w, h = inscribe_ratio(50, 50, 4.0)
        assert w <= 50
        assert h <= 50
        assert ratio_error(w, h, 4, 1) <= 0.001

    def test_keeps_center(self):
        w, h = inscribe_ratio(100, 60, 1.0)
        assert w == 60
        assert h == 60

    def test_zero_ratio_returns_original(self):
        assert inscribe_ratio(100, 60, 0) == (100, 60)


class TestRatioError:
    def test_exact(self):
        assert ratio_error(200, 100, 2, 1) == 0

    def test_within_tolerance(self):
        assert ratio_error(180.0, 105.52, 232, 136) <= 0.001

    def test_zero_height(self):
        assert ratio_error(10, 0, 10, 10) == 0


class TestContentRect:
    def test_single_node(self):
        result = content_rect_of_nodes([{"x": 100, "y": 200, "width": 80, "height": 60}])
        assert result == {"x": 60.0, "y": 170.0, "width": 80.0, "height": 60.0}

    def test_empty(self):
        assert content_rect_of_nodes([]) == {"x": 0, "y": 0, "width": 0, "height": 0}


SIMPLE_LAYOUT = {
    "layoutIntent": {
        "groups": [
            {
                "id": "g1",
                "region": "center",
                "unit": {"root": {"id": "r1", "deviceType": "冷水机"}},
                "count": 1,
                "arrangement": "vertical",
            }
        ],
        "constraints": {},
    }
}


class TestMetadataEmbedding:
    def test_build_nodes_embeds_material_metadata(self):
        nodes = convert_layout_file(
            SIMPLE_LAYOUT,
            [{"displayName": "冷水机", "image": "symbols/water_chiller.json", "width": 232, "height": 136}],
            1920,
            1080,
        )
        assert len(nodes) == 1
        attrs = nodes[0]["a"]
        assert attrs["layout.materialName"] == "冷水机"
        assert attrs["layout.sourceWidth"] == 232
        assert attrs["layout.sourceHeight"] == 136
        width = nodes[0]["p"]["width"]
        height = nodes[0]["p"]["height"]
        assert ratio_error(width, height, 232, 136) <= 0.001

    def test_build_nodes_falls_back_when_material_missing_size(self):
        nodes = convert_layout_file(
            SIMPLE_LAYOUT,
            [{"displayName": "冷水机", "image": "symbols/water_chiller.json"}],
            1920,
            1080,
        )
        attrs = nodes[0]["a"]
        assert attrs["layout.sourceWidth"] == 160
        assert attrs["layout.sourceHeight"] == 240
        assert ratio_error(nodes[0]["p"]["width"], nodes[0]["p"]["height"], 160, 240) <= 0.001
