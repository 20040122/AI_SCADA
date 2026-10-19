import sys
from unittest.mock import patch

import cv2
import numpy as np
import pytest
from PIL import Image

from picture.AgentI import main as agent_main
from picture.AgentI.opencv import grid_detection
from picture.AgentI.resize_image import resize_image


def test_clean_and_grid_images_share_size_and_coordinates(tmp_path):
    source = tmp_path / "input.png"
    clean = tmp_path / "clean.png"
    grid = tmp_path / "grid.png"
    Image.new("RGB", (100, 100), "red").save(source)
    original = source.read_bytes()

    resize_image(source, grid, clean_output_path=clean)

    with Image.open(clean) as image, Image.open(grid) as reference:
        assert image.size == reference.size == (1920, 1080)
        assert image.getpixel((419, 540)) == (255, 255, 255)
        assert image.getpixel((420, 540)) == (255, 0, 0)
        assert image.getpixel((1499, 540)) == (255, 0, 0)
        assert image.getpixel((1500, 540)) == (255, 255, 255)
        assert reference.getpixel((421, 541)) == image.getpixel((421, 541))
        assert reference.getpixel((960, 540)) != image.getpixel((960, 540))
    assert source.read_bytes() == original


@pytest.mark.parametrize("conflict", ["input.png", "grid.png"])
def test_clean_output_cannot_overwrite_input_or_grid(tmp_path, conflict):
    source = tmp_path / "input.png"
    Image.new("RGB", (100, 100), "red").save(source)
    original = source.read_bytes()

    with pytest.raises(ValueError):
        resize_image(source, tmp_path / "grid.png", clean_output_path=tmp_path / conflict)

    assert source.read_bytes() == original
    assert not (tmp_path / "grid.png").exists()


def test_grid_only_resize_remains_supported(tmp_path):
    source = tmp_path / "input.png"
    output = tmp_path / "grid.png"
    Image.new("RGB", (100, 100), "white").save(source)

    resize_image(source, output)

    with Image.open(output) as image:
        assert image.size == (1920, 1080)
        assert image.getpixel((960, 540)) != (255, 255, 255)


def test_grid_removal_is_optional_and_preserves_legacy_default():
    image = np.full((100, 200, 3), 255, np.uint8)
    image[:, 40] = (190, 150, 0)

    with patch.object(cv2, "cvtColor", side_effect=AssertionError("unexpected grid detection")), patch.object(
        cv2, "inpaint", side_effect=AssertionError("unexpected grid repair"),
    ):
        info, mask, cleaned = grid_detection(image, enabled=False)

    assert not info["detected"]
    assert not np.any(mask)
    assert np.array_equal(cleaned, image)
    info, mask, cleaned = grid_detection(image)
    assert info["detected"]
    assert np.any(mask)
    assert not np.array_equal(cleaned, image)


@pytest.mark.parametrize("custom_clean_path", [False, True])
def test_run_all_uses_clean_pixels_for_detection_ocr_and_naming(tmp_path, monkeypatch, custom_clean_path):
    source = tmp_path / "input.png"
    grid = tmp_path / "grid.png"
    clean = tmp_path / "custom.png" if custom_clean_path else tmp_path / "grid_clean.png"
    detections = tmp_path / "detections.json"
    output = tmp_path / "canvas.json"
    Image.new("RGB", (100, 100), "white").save(source)
    pipeline = sys.modules[agent_main.run_pipeline.__module__]
    detector = sys.modules[pipeline.run_detection.__module__]
    received = {}
    actual_detection = pipeline.run_detection

    def detect(image_path, output_dir, **kwargs):
        assert image_path == clean
        assert kwargs["remove_grid"] is False
        return actual_detection(image_path, output_dir, **kwargs)

    def recognize(label):
        def fill(image, items, *args):
            received[label] = image.copy()
            return {}
        return fill

    monkeypatch.setattr(pipeline, "run_detection", detect)
    monkeypatch.setattr(pipeline, "fill_text_values", recognize("ocr"))
    monkeypatch.setattr(pipeline, "fill_control_names", recognize("naming"))
    monkeypatch.setattr(agent_main, "load_query_results", lambda path: [])
    with patch.object(detector, "controls_detection", wraps=detector.controls_detection) as controls, patch.object(
        cv2, "inpaint", side_effect=AssertionError("unexpected grid repair"),
    ):
        canvas, unmatched = agent_main.run_all(
            source, grid, tmp_path / "debug", detections, tmp_path / "material.db", output,
            clean_image=clean if custom_clean_path else None,
        )

    expected = cv2.imread(str(clean))
    assert np.all(expected == 255)
    assert np.array_equal(controls.call_args.args[0], expected)
    assert np.array_equal(received["ocr"], expected)
    assert np.array_equal(received["naming"], expected)
    assert grid.exists()
    assert detections.exists()
    assert output.exists()
    assert canvas["d"] == []
    assert unmatched == []
