import json
import asyncio
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from picture.AgentI import name as naming
from picture.AgentI import ocr, semantic
from picture.AgentI.assemble.text import convert_text_nodes
from picture.AgentI.opencv import read_image, run_detection
from picture.AgentI.resize_image import resize_image


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = Path(__file__).parent / "fixtures" / "agent_i_oxygen_layout.json"


@pytest.mark.parametrize("factor", [0.75, 1.0, 1.5])
@pytest.mark.parametrize("layout", [LAYOUT, LAYOUT.with_name("agent_i_oxygen_drift_layout.json"), LAYOUT.with_name("agent_i_oxygen_side_layout.json")])
def test_oxygen_reference_keeps_text_out_of_controls_and_aligns_labels(tmp_path, factor, layout):
    source = ROOT / "test_03.png"
    if not source.is_file():
        pytest.skip("Reference image is not available")
    clean = tmp_path / "clean.png"
    resize_image(source, tmp_path / "grid.png", clean_output_path=clean)
    image = read_image(clean)
    if factor != 1:
        image = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        assert cv2.imwrite(str(clean), image)
    image, _, baseline = run_detection(clean, tmp_path / "baseline", remove_grid=False)
    assert sum(n["type"] == "value_field" for n in baseline["nodes"]) == 22
    assert sum(n["type"] == "button" for n in baseline["nodes"]) == 3
    devices = semantic.anchor_devices(semantic.parse_layout(layout.read_text(), image.shape[1], image.shape[0]), baseline)
    devices, _ = semantic.refine_boxes(image, devices)
    regions = [n for n in baseline["nodes"] if n["layer"] == "text"]
    devices = semantic.align_labels(image, devices, regions)
    exported, result = semantic.merge_layout(baseline, devices)
    assert result["counts"]["controls"] == 62
    label_count = sum(len(device["labels"]) for device in devices)
    assert result["counts"]["texts"] == 31 + label_count + (6 if factor == 1.5 else 0)
    assert len(devices) == 28
    assert sum(item.get("vision_value") == "氧气" for item in exported) == 22
    assert {"\n".join(label["text"] for label in device["labels"]) for device in devices[-6:]} == {
        "风机\nAP12P", "风机\nAP21S", "风机\nAP12SG#1", "风机\nAP11P", "风机\nAP12SG#2", "风机\nAP11SG",
    }
    for device in devices[-6:]:
        assert device["labels"][0]["bbox"][3] < 45 * factor


@pytest.mark.parametrize("source,counts", [
    ("image01.png", {"controls": 8, "texts": 8}),
    ("test_02.png", {"controls": 14, "texts": 14}),
])
def test_additional_previous_reference_counts(tmp_path, source, counts):
    path = ROOT / source
    if not path.is_file():
        pytest.skip("Reference image is not available")
    clean = tmp_path / "clean.png"
    resize_image(path, tmp_path / "grid.png", clean_output_path=clean)
    _, _, detection = run_detection(clean, tmp_path / "detection", remove_grid=False)
    assert detection["counts"] == counts


def test_saved_side_labels_are_valid_and_distant_labels_still_fail():
    devices = semantic.parse_layout(LAYOUT.read_text(), 1920, 1080)
    assert len(devices) == 28
    invalid = {"devices": [{"name": "传感器", "bbox": [10, 10, 30, 40], "labels": [{"text": "名称", "bbox": [800, 800, 830, 820]}]}]}
    with pytest.raises(ValueError, match="距离异常"):
        semantic.parse_layout(json.dumps(invalid), 1920, 1080)
    side = {"devices": [{"name": "探头", "bbox": [846, 451, 862, 483], "labels": [{"text": "环境", "bbox": [893, 451, 910, 467]}]}]}
    assert semantic.parse_layout(json.dumps(side), 1920, 1080)[0]["labels"][0]["text"] == "环境"


def test_ocr_conflicts_are_reviewed_and_existing_vision_text_survives(monkeypatch):
    image = np.full((60, 100, 3), 255, np.uint8)
    items = [
        {"id": "text_1", "type": "text", "bbox": [0, 0, 32, 16], "value": None},
        {"id": "text_2", "type": "text", "bbox": [0, 30, 32, 16], "value": None, "vision_value": "氧气"},
    ]
    monkeypatch.setattr(ocr, "check_engine", lambda *args: "tesseract")
    monkeypatch.setattr(ocr, "recognize_crop", lambda *args: ocr.Recognition("AA", 90, 3, ("AA", "氧气")))
    summary = ocr.fill_text_values(image, items, workers=1, diagnostics=True)
    assert items[0]["recognition_status"] == "needs_review"
    assert items[1]["value"] == "氧气"
    assert items[1]["recognition_status"] == "vision_transcribed"
    assert "ocr_value" not in items[1]
    assert summary["tesseract_calls"] == 3
    assert summary["skipped_vision"] == 1


@pytest.mark.parametrize("content,expected,status", [
    ('{"text":"地下管廊"}', "地下管廊", "vision_transcribed"),
    ('{"text":null}', "地下管底", "needs_review"),
])
def test_unassociated_uncertain_text_gets_visual_review(monkeypatch, content, expected, status):
    async def call(*args, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(naming, "call_llm", call)
    items = [{"id": "title", "type": "text", "bbox": [0, 0, 80, 19], "value": "地下管底", "recognition_status": "needs_review"}]
    summary = naming.refine_label_values(np.full((30, 100, 3), 255, np.uint8), items, model="test")
    assert summary["labels"] == 1
    assert items[0]["value"] == expected
    assert items[0]["recognition_status"] == status


def test_text_style_keeps_blue_small_labels_and_multiline_content():
    image = np.full((100, 200, 3), 255, np.uint8)
    cv2.putText(image, "AP11P", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 40, 20), 1)
    item = {"bbox": [8, 10, 60, 20], "value": "AP11P"}
    style = ocr.infer_text_style(image, item)
    assert style["text.color"] == "rgb(20,40,150)"
    detection = {"type": "text", "position": {"x": 40, "y": 20}, "width": 60, "height": 30, "value": "风机\nAP11P", "text_style": style}
    nodes = convert_text_nodes([detection], {"i": 1, "p": {}, "s": {"text.font": "16px arial"}})
    assert nodes[0]["s"]["text"] == "风机\nAP11P"
    assert nodes[0]["s"]["text.color"] == "rgb(20,40,150)"
    assert nodes[0]["s"]["text.font"] == style["text.font"]


@pytest.mark.parametrize("different_labels", [False, True])
def test_same_appearance_and_label_use_majority_without_merging_different_labels(monkeypatch, different_labels):
    image = np.full((100, 200, 3), 255, np.uint8)
    items = [{"id": str(index), "type": "controls", "bbox": [index * 40, 0, 30, 40], "semantic_name": "传感器", "semantic_labels": [str(index) if different_labels else "环境"]} for index in range(3)]

    async def recognize(client, model, semaphore, item, *args):
        return ("PN探头" if item["id"] != "2" else "压力传感器"), True

    monkeypatch.setattr(naming, "recognize_control", recognize)
    asyncio.run(naming.recognize_all(image, items, ["PN探头", "压力传感器"], "", None, "test", 3, 0))
    assert items[2]["value"] == ("压力传感器" if different_labels else "PN探头")
