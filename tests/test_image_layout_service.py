import io
import json
import sqlite3

import pytest
from PIL import Image

from app.services.image_layout_service import generate_image_layout
from picture.AgentI import pipeline


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("width,height,scale,offset_y", [(1920, 1080, 1, 0), (960, 960, 0.5, 210)])
def test_image_layout_preserves_detected_geometry_text_and_materials(monkeypatch, width, height, scale, offset_y):
    workspaces = []
    materials = [{"displayName": "泵", "image": "symbols/pump.json", "width": 80, "height": 100}]

    def detect(image, output_dir, output_path, db_path, **kwargs):
        workspaces.append(output_dir.parent)
        assert kwargs == {"remove_grid": False}
        with Image.open(image) as source:
            assert source.size == (1920, 1080)
        with sqlite3.connect(str(db_path)) as connection:
            assert connection.execute("SELECT displayName FROM query_results").fetchall() == [("泵",)]
        output_path.write_text(json.dumps([
            {"id": "controls_1", "type": "controls", "bbox": [100, 200, 60, 80], "value": "泵"},
            {"id": "text_1", "type": "text", "bbox": [100, 300, 70, 20], "value": "泵1\n运行", "text_style": {"text.font": "17px arial, sans-serif", "text.color": "rgb(20,40,60)"}},
            {"id": "controls_2", "type": "controls", "bbox": [500, 100, 50, 50], "value": "未知阀"},
        ]), encoding="utf-8")
        return {"detection": {"semantic": {"status": "failed"}}}

    monkeypatch.setattr(pipeline, "run_pipeline", detect)
    result = generate_image_layout(image_bytes(), materials, width, height, "系统")
    control, text = result.json_data["d"]
    assert control["p"]["position"] == {"x": 130 * scale, "y": 240 * scale + offset_y}
    assert control["p"]["width"] == 60 * scale
    assert control["p"]["height"] == 80 * scale
    assert control["p"]["image"] == "symbols/pump.json"
    assert control["a"]["layout.node"]
    assert text["s"]["text"] == "泵1\n运行"
    assert text["s"]["text.font"] == "{:g}px arial, sans-serif".format(17 * scale)
    assert text["s"]["text.color"] == "rgb(20,40,60)"
    assert result.json_data["a"]["width"] == width
    assert result.json_data["a"]["height"] == height
    assert result.missing_controls == ["未知阀"]
    assert result.quality_issues[0]["severity"] == "warning"
    assert result.pipe_data is None
    assert all(not directory.exists() for directory in workspaces)


@pytest.mark.parametrize("image,width,height", [(b"", 1920, 1080), (b"not-an-image", 1920, 1080), (b"x", 0, 1080)])
def test_image_layout_rejects_invalid_input(image, width, height):
    with pytest.raises((ValueError, OSError)):
        generate_image_layout(image, [{"displayName": "泵"}], width, height, "")
