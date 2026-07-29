from __future__ import annotations

from model.layout_agent import _calc_content_rect, _schema_validate


class TestCalcContentRect:
    def test_empty_nodes(self):
        assert _calc_content_rect([]) == {"x": 0, "y": 0, "width": 0, "height": 0}

    def test_single_node_center(self):
        nodes = [{"x": 100, "y": 200, "width": 80, "height": 60}]
        result = _calc_content_rect(nodes)
        assert result == {"x": 60.0, "y": 170.0, "width": 80.0, "height": 60.0}

    def test_multiple_nodes(self):
        nodes = [
            {"x": 100, "y": 100, "width": 40, "height": 40},
            {"x": 300, "y": 200, "width": 60, "height": 50},
        ]
        result = _calc_content_rect(nodes)
        assert result["x"] == 80.0
        assert result["y"] == 80.0
        assert result["width"] == 250.0
        assert result["height"] == 145.0

    def test_rounding(self):
        nodes = [{"x": 100.123456, "y": 200.654321, "width": 50.987654, "height": 30.123456}]
        result = _calc_content_rect(nodes)
        assert result["x"] == round(100.123456 - 50.987654 / 2, 5)
        assert result["y"] == round(200.654321 - 30.123456 / 2, 5)

    def test_nodes_without_width_height(self):
        nodes = [{"x": 100, "y": 200}]
        result = _calc_content_rect(nodes)
        assert result == {"x": 100.0, "y": 200.0, "width": 0.0, "height": 0.0}

    def test_all_fields_all_zero(self):
        nodes = [{"x": 0, "y": 0, "width": 0, "height": 0}]
        result = _calc_content_rect(nodes)
        assert result == {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}


class TestSchemaValidate:
    def test_empty_data_is_invalid(self):
        errors = []
        try:
            import asyncio
            errors = asyncio.run(_schema_validate({}))
        except Exception:
            pass
        assert len(errors) >= 1

    def test_minimal_valid_structure_not_schema(self):
        import asyncio
        data = {
            "v": "8.0.5",
            "p": {
                "layers": [{"name": "0", "visible": True, "selectable": True, "movable": True, "editable": True}],
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
        errors = asyncio.run(_schema_validate(data))
        assert errors == []
