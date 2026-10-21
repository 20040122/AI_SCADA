import json
from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
import pytest

from picture.AgentI import semantic
from picture.AgentI.opencv import read_image, run_detection
from picture.AgentI.resize_image import resize_image


CONNECTED_EQUIPMENT = [
    ("冷却塔", [202, 137, 180, 191], [244, 346, 101, 28], "冷却塔1"),
    ("冷却塔", [202, 409, 180, 188], [244, 615, 101, 28], "冷却塔2"),
    ("冷却塔", [202, 686, 180, 190], [244, 892, 101, 28], "冷却塔3"),
    ("冷却泵", [600, 190, 182, 131], [638, 334, 101, 28], "冷却泵1"),
    ("冷却泵", [600, 433, 182, 130], [638, 577, 101, 28], "冷却泵2"),
    ("冷却泵", [600, 693, 182, 130], [638, 838, 101, 28], "冷却泵3"),
    ("冷水机", [1020, 187, 270, 132], [1104, 334, 102, 28], "冷水机1"),
    ("冷水机", [1020, 430, 270, 132], [1104, 575, 102, 28], "冷水机2"),
    ("冷水机", [1020, 678, 270, 132], [1104, 823, 102, 28], "冷水机3"),
    ("冷冻泵", [1530, 138, 175, 126], [1565, 277, 101, 27], "冷冻泵1"),
    ("冷冻泵", [1530, 357, 175, 127], [1565, 498, 101, 28], "冷冻泵2"),
    ("冷冻泵", [1530, 588, 175, 127], [1565, 730, 101, 28], "冷冻泵3"),
    ("冷冻泵", [1530, 819, 175, 126], [1565, 960, 101, 27], "冷冻泵4"),
]


def baseline():
    return {
        "image_size": {"width": 400, "height": 300},
        "counts": {"controls": 2, "texts": 2},
        "nodes": [
            {"id": "grid_1", "layer": "grid", "type": "coordinate_grid", "bbox": [0, 0, 400, 300], "parent_id": None},
            {"id": "controls_1", "layer": "controls", "type": "button", "bbox": [10, 10, 90, 30], "parent_id": "grid_1", "label_bboxes": []},
            {"id": "controls_2", "layer": "controls", "type": "equipment_candidate", "bbox": [140, 245, 20, 20], "parent_id": "grid_1", "label_bboxes": []},
            {"id": "text_1", "layer": "text", "type": "text_region", "bbox": [10, 60, 50, 15], "parent_id": "grid_1"},
            {"id": "text_2", "layer": "text", "type": "text_region", "bbox": [160, 245, 20, 20], "parent_id": "grid_1"},
        ],
    }


def device():
    return {"name": "冷却泵", "bbox": [120, 100, 140, 130], "labels": [{"text": "冷却泵1", "bbox": [130, 240, 120, 26]}]}


def test_parse_normalized_coordinates_and_numbered_names():
    content = json.dumps({"devices": [{"name": "冷却泵", "bbox": [300, 330, 650, 770], "labels": [{"text": "冷却泵1", "bbox": [325, 800, 625, 890]}]}]})
    parsed = semantic.parse_layout(content, 400, 300)
    assert parsed[0]["bbox"] == [120, 99, 140, 132]
    assert parsed[0]["labels"] == [{"text": "冷却泵1", "bbox": [130, 240, 120, 27]}]


@pytest.mark.parametrize("box", [
    [0, 0, 1001, 100], [True, 0, 100, 100], [0, 0, float("nan"), 100],
    [200, 0, 100, 100], [0, 0, 1, 1], [0, 0, 100],
])
def test_invalid_coordinates_are_rejected(box):
    with pytest.raises(ValueError):
        semantic.pixel_box(box, 400, 300)


def test_duplicate_devices_are_rejected():
    entry = {"name": "冷却泵", "bbox": [300, 330, 650, 770], "labels": []}
    with pytest.raises(ValueError, match="重复"):
        semantic.parse_layout(json.dumps({"devices": [entry, entry]}), 400, 300)


def test_merge_preserves_ui_and_associates_complete_labels_without_mutating_input():
    original = baseline()
    before = deepcopy(original)
    exported, updated = semantic.merge_layout(original, [device()])
    assert original == before
    ui = [node for node in updated["nodes"] if node["type"] == "button"]
    assert len(ui) == 1
    assert ui[0]["bbox"] == [10, 10, 90, 30]
    equipment = [node for node in updated["nodes"] if node["type"] == "equipment_candidate"]
    assert len(equipment) == 1
    assert equipment[0]["bbox"] == [120, 100, 140, 130]
    assert equipment[0]["label_bboxes"] == [[130, 240, 120, 26]]
    labels = [node for node in updated["nodes"] if node.get("text") == "冷却泵1"]
    assert labels[0]["parent_id"] == equipment[0]["id"]
    assert len({node["id"] for node in updated["nodes"]}) == len(updated["nodes"])
    assert updated["counts"] == {"controls": 2, "texts": 2}
    assert all(item["type"] in ("controls", "text") for item in exported)


def test_semantic_device_cannot_replace_ui():
    proposal = device()
    proposal["bbox"] = [10, 10, 90, 30]
    with pytest.raises(ValueError, match="界面控件"):
        semantic.merge_layout(baseline(), [proposal])


def test_independent_text_lines_accept_large_fonts(monkeypatch):
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[0, 0] = 255
    words = [
        {"bbox": [100, 100, 90, 38], "text": "冷却", "confidence": 0.9, "line_key": [1, 1, 1, 1]},
        {"bbox": [180, 100, 50, 38], "text": "泵3", "confidence": 0.9, "line_key": [1, 1, 1, 1]},
    ]
    monkeypatch.setattr(semantic, "ocr_detection", lambda *args: words)
    assert semantic.text_lines(image, "chi_sim+eng") == [{"bbox": [100, 100, 130, 38], "text": "冷却泵3"}]


def test_text_fragments_trigger_review():
    details = baseline()
    details["nodes"].extend([
        {"id": "extra_1", "layer": "controls", "type": "equipment_candidate", "bbox": [165, 245, 20, 20], "label_bboxes": []},
        {"id": "extra_2", "layer": "controls", "type": "equipment_candidate", "bbox": [190, 245, 20, 20], "label_bboxes": []},
    ])
    reasons = semantic.review_reasons(details, [{"bbox": [130, 240, 120, 26], "text": "冷却泵1"}])
    assert len(reasons) == 2


@pytest.mark.parametrize("failure", [RuntimeError("unavailable"), "malformed"])
def test_failed_review_preserves_baseline_and_reports_failure(tmp_path, monkeypatch, failure):
    original = baseline()
    items = [{"id": "original"}]
    before = deepcopy(original)
    monkeypatch.setattr(semantic, "text_lines", lambda *args: [])
    monkeypatch.setattr(semantic, "load_whitelist", lambda path: ["冷却泵"])

    async def locate(*args):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(semantic, "locate_devices", locate)
    result, details, summary = semantic.review_detection(np.zeros((300, 400, 3), np.uint8), items, original, tmp_path, tmp_path / "db", mode="always")
    assert result is items
    assert details is original
    assert original == before
    assert summary["status"] == "failed"
    assert summary["error"]


def test_off_mode_does_not_run_text_or_model_detection(tmp_path, monkeypatch):
    def fail(*args):
        raise AssertionError("disabled path executed")

    monkeypatch.setattr(semantic, "text_lines", fail)
    monkeypatch.setattr(semantic, "locate_devices", fail)
    items, details = [], baseline()
    result, returned, summary = semantic.review_detection(np.zeros((300, 400, 3), np.uint8), items, details, tmp_path, tmp_path / "db", mode="off")
    assert result is items
    assert returned is details
    assert summary["status"] == "disabled"


def test_review_sends_unchanged_pixels_and_applies_valid_layout(tmp_path, monkeypatch):
    image = np.full((300, 400, 3), 255, np.uint8)
    image[90:92, 10:390] = 0
    image[80:250, 200:202] = 0
    before = image.copy()
    monkeypatch.setattr(semantic, "text_lines", lambda *args: [])
    monkeypatch.setattr(semantic, "load_whitelist", lambda path: ["冷却泵"])

    async def locate(received, *args):
        assert np.array_equal(received, before)
        return json.dumps({"devices": [{"name": "冷却泵", "bbox": [300, 330, 650, 770], "labels": [{"text": "冷却泵1", "bbox": [325, 800, 625, 890]}]}]})

    monkeypatch.setattr(semantic, "locate_devices", locate)

    def refine(received, devices):
        assert np.array_equal(received, before)
        return devices, []

    monkeypatch.setattr(semantic, "refine_boxes", refine)
    _, details, summary = semantic.review_detection(image, [], baseline(), tmp_path, tmp_path / "db", mode="always")
    assert np.array_equal(image, before)
    assert summary["status"] == "applied"
    assert summary["connection_processing"] is False
    assert details["counts"]["controls"] == 2


def test_local_refinement_uses_device_pixels_without_mutating_image():
    image = np.full((300, 400, 3), 255, np.uint8)
    image[100:200, 100:250] = (150, 100, 30)
    image[149:152, :] = 0
    before = image.copy()
    proposal = {"name": "泵", "bbox": [110, 110, 150, 100], "labels": []}
    refined, failed = semantic.refine_boxes(image, [proposal])
    assert failed == []
    assert refined[0]["bbox"] == [91, 94, 168, 112]
    assert proposal["bbox"] == [110, 110, 150, 100]
    assert np.array_equal(image, before)


def test_label_alignment_uses_original_glyphs_and_preserves_pixels():
    image = np.full((300, 400, 3), 255, np.uint8)
    cv2.putText(image, "PUMP1", (100, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    expected = list(cv2.boundingRect(np.where(image[:, :, 0] < 150, 255, 0).astype(np.uint8)))
    image[30:32, :] = 0
    before = image.copy()
    devices = [{"name": "泵", "bbox": [100, 40, 100, 60], "labels": [{"text": "PUMP1", "bbox": [90, 100, 150, 40]}]}]
    aligned = semantic.align_labels(image, devices)
    assert aligned[0]["labels"][0]["bbox"] == expected
    assert devices[0]["labels"][0]["bbox"] == [90, 100, 150, 40]
    assert np.array_equal(image, before)


def test_connected_reference_boxes_and_text_are_separated_without_changing_pixels(tmp_path):
    source = Path(__file__).resolve().parents[1] / "image03.png"
    if not source.is_file():
        pytest.skip("Reference image is not available")
    clean = tmp_path / "clean.png"
    resize_image(source, tmp_path / "grid.png", clean_output_path=clean)
    image, _, original = run_detection(clean, tmp_path / "baseline", remove_grid=False)
    before = read_image(clean)
    assert semantic.review_reasons(original, [])
    proposals = [{"name": name, "bbox": [box[0] + 8, box[1] - 12, box[2], box[3]], "labels": [{"text": text, "bbox": [label[0] + 5, label[1] - 10, label[2], label[3] + 8]}]} for name, box, label, text in CONNECTED_EQUIPMENT]
    proposals, failed = semantic.refine_boxes(image, proposals)
    assert failed == []
    proposals = semantic.align_labels(image, proposals)
    _, result = semantic.merge_layout(original, proposals)
    assert result["counts"] == {"controls": 13, "texts": 13}
    for proposal, (name, box, label, text) in zip(proposals, CONNECTED_EQUIPMENT):
        actual = proposal["bbox"]
        intersection = semantic.overlap(actual, box)
        assert intersection / (actual[2] * actual[3] + box[2] * box[3] - intersection) >= 0.7
        actual_label = proposal["labels"][0]["bbox"]
        assert semantic.overlap(actual_label, label) / (label[2] * label[3]) >= 0.9
        assert proposal["labels"][0]["text"] == text
    assert np.array_equal(image, before)


def test_multiple_uncovered_instance_names_reject_partial_semantic_result(tmp_path, monkeypatch):
    lines = [{"bbox": [300, y, 50, 15], "text": "冷却泵{}".format(index)} for index, y in enumerate([10, 50, 90], 1)]
    monkeypatch.setattr(semantic, "text_lines", lambda *args: lines)
    monkeypatch.setattr(semantic, "load_whitelist", lambda path: ["冷却泵"])

    async def locate(*args):
        return json.dumps({"devices": [{"name": "冷却泵", "bbox": [300, 330, 650, 770], "labels": []}]})

    monkeypatch.setattr(semantic, "locate_devices", locate)
    items, original = [], baseline()
    result, returned, summary = semantic.review_detection(np.full((300, 400, 3), 255, np.uint8), items, original, tmp_path, tmp_path / "db", mode="always")
    assert result is items
    assert returned is original
    assert summary["status"] == "failed"
    assert summary["uncovered_instance_labels"] == 3


def test_independent_text_failure_preserves_normal_legacy_path(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("OCR unavailable")

    monkeypatch.setattr(semantic, "text_lines", fail)
    items, original = [], baseline()
    result, returned, summary = semantic.review_detection(np.zeros((300, 400, 3), np.uint8), items, original, tmp_path, tmp_path / "db")
    assert result is items
    assert returned is original
    assert summary["status"] == "not_needed"
    assert summary["text_detection_error"] == "OCR unavailable"
