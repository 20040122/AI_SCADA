import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from picture.AgentI import name, ocr, opencv, semantic
from picture.AgentI.resize_image import resize_image


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def preserve_event_loop():
    try:
        previous = asyncio.get_event_loop()
    except RuntimeError:
        previous = None
    yield
    asyncio.set_event_loop(previous if previous is not None and not previous.is_closed() else None)


def prepare_reference(tmp_path, source, factor=1):
    source = ROOT / source
    if not source.is_file():
        pytest.skip("Reference image is not available")
    clean = tmp_path / "clean.png"
    resize_image(source, tmp_path / "grid.png", clean_output_path=clean)
    if factor != 1:
        image = opencv.read_image(clean)
        image = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        assert cv2.imwrite(str(clean), image)
    return clean


@pytest.mark.parametrize("source", ["image01.png", "image03.png", "test_01.png", "test_02.png", "picture/AgentI/data/input.png"])
@pytest.mark.parametrize("factor", [0.75, 1, 1.5])
def test_existing_references_keep_detection_and_associations(tmp_path, monkeypatch, source, factor):
    clean = prepare_reference(tmp_path, source, factor)
    image, items, details = opencv.run_detection(clean, tmp_path / "current", remove_grid=False)
    monkeypatch.setattr(opencv, "value_field_labels", lambda *args: {})
    previous_image, previous_items, previous_details = opencv.run_detection(clean, tmp_path / "previous", remove_grid=False)
    assert np.array_equal(image, previous_image)
    assert items == previous_items
    assert details == previous_details


@pytest.mark.parametrize("factor", [0.75, 1, 1.5])
def test_oxygen_short_labels_avoid_full_image_location_and_keep_geometry(tmp_path, monkeypatch, factor):
    clean = prepare_reference(tmp_path, "test_03.png", factor)
    image, items, details = opencv.run_detection(clean, tmp_path / "current", remove_grid=False)
    equipment = [item for item in items if item.get("control_kind") == "equipment_candidate"]
    sensors = [item for item in equipment if item.get("label_association") == "value_field_label"]
    assert len(sensors) == 22
    assert all(len(item["label_bboxes"]) == 1 for item in sensors)

    async def unexpected_location(*args):
        raise AssertionError("Unnecessary full image location")

    monkeypatch.setattr(semantic, "text_lines", lambda *args: [])
    monkeypatch.setattr(semantic, "locate_devices", unexpected_location)
    returned, _, summary = semantic.review_detection(image, items, details, tmp_path / "current", tmp_path / "db")
    assert returned is items
    assert summary["status"] == "not_needed"
    monkeypatch.setattr(opencv, "value_field_labels", lambda *args: {})
    _, previous, _ = opencv.run_detection(clean, tmp_path / "previous", remove_grid=False)
    assert [(item["id"], item["type"], item["bbox"]) for item in items] == [(item["id"], item["type"], item["bbox"]) for item in previous]


def test_value_field_label_does_not_choose_between_equally_close_devices():
    controls = [
        {"id": "field", "type": "value_field", "bbox": [100, 60, 50, 20]},
        {"id": "first", "type": "equipment_candidate", "bbox": [70, 90, 30, 35]},
        {"id": "second", "type": "equipment_candidate", "bbox": [150, 90, 30, 35]},
    ]
    texts = [{"id": "label", "bbox": [110, 35, 32, 16]}]
    opencv.assign_parents(controls, texts, 1)
    assert texts[0]["parent_id"] == "grid_1"
    assert not any(control["label_bboxes"] for control in controls)


def test_value_field_label_keeps_units_and_titles_independent():
    controls = [
        {"id": "field", "type": "value_field", "bbox": [100, 60, 50, 20]},
        {"id": "sensor", "type": "equipment_candidate", "bbox": [125, 90, 30, 35]},
    ]
    texts = [
        {"id": "label", "bbox": [110, 35, 32, 16]},
        {"id": "unit", "bbox": [155, 65, 10, 10]},
        {"id": "title", "bbox": [40, 5, 180, 20]},
    ]
    opencv.assign_parents(controls, texts, 1)
    assert texts[0]["parent_id"] == "sensor"
    assert texts[0]["association"]["method"] == "value_field_label"
    assert texts[1]["parent_id"] == texts[2]["parent_id"] == "grid_1"


def anchor_reference():
    return {
        "image_size": {"width": 400, "height": 300},
        "nodes": [{"layer": "controls", "type": "equipment_candidate", "bbox": [x, 50, 30, 30]} for x in (40, 140, 240)],
    }


def test_partial_device_counts_still_anchor_valid_devices_and_labels():
    devices = [
        {"name": "探头", "bbox": [45, 55, 30, 30], "labels": [{"text": "环境", "bbox": [45, 90, 30, 12]}]},
        {"name": "探头", "bbox": [145, 55, 30, 30], "labels": []},
    ]
    before = deepcopy(devices)
    result = semantic.anchor_devices(devices, anchor_reference())
    assert [device["bbox"] for device in result] == [[40, 50, 30, 30], [140, 50, 30, 30]]
    assert result[0]["labels"][0]["bbox"] == [40, 85, 30, 12]
    assert devices == before


@pytest.mark.parametrize("outlier", [[20, 180, 180, 60], [90, 50, 30, 30]])
def test_invalid_or_ambiguous_device_does_not_disable_other_anchors(outlier):
    devices = [
        {"name": "探头", "bbox": [245, 55, 30, 30], "labels": []},
        {"name": "未知", "bbox": outlier, "labels": []},
    ]
    result = semantic.anchor_devices(devices, anchor_reference())
    assert result[0]["bbox"] == [240, 50, 30, 30]
    assert result[0]["geometry_source"] == "opencv"
    assert result[1] == devices[1]


def test_vision_text_needs_no_tesseract_or_language_installation(monkeypatch):
    def unexpected_ocr(*args):
        raise AssertionError("Already transcribed text must not invoke OCR")

    monkeypatch.setattr(ocr, "check_engine", unexpected_ocr)
    monkeypatch.setattr(ocr, "recognize_crop", unexpected_ocr)
    items = [{"id": "label", "type": "text", "bbox": [0, 0, 32, 16], "vision_value": "氧气", "value": None}]
    result = ocr.fill_text_values(np.full((20, 40, 3), 255, np.uint8), items, diagnostics=True)
    assert items[0]["value"] == "氧气"
    assert items[0]["recognition_status"] == "vision_transcribed"
    assert result["recognized"] == result["skipped_vision"] == 1
    assert result["tesseract_calls"] == 0


def test_oxygen_reuses_sensor_classification_and_uncertain_label_reviews(tmp_path, monkeypatch):
    clean = prepare_reference(tmp_path, "test_03.png")
    image, items, _ = opencv.run_detection(clean, tmp_path / "detection", remove_grid=False)
    sensors = [item for item in items if item.get("label_association") == "value_field_label"]
    originals = deepcopy(sensors)
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"name":"PN探头","text":"氧气"}'))])

    monkeypatch.setattr(name, "call_llm", call)
    summary = asyncio.run(name.recognize_all(image, sensors, ["PN探头"], "", None, "test", 32, 0.5))
    assert summary["model_calls"] <= 3
    assert len(summary["reused"]) >= 19
    assert sensors == [dict(item, value="PN探头") for item in originals]
    labels = [item for item in items if item.get("parent_id") in {sensor["id"] for sensor in sensors}]
    assert len(labels) == 22
    for item in labels:
        item.update(recognition_status="needs_review", value="AA")
    result = name.refine_label_values(image, sensors + labels, model="test")
    assert result["labels"] == len(result["refined"]) == 22
    assert result["model_calls"] <= 3
    assert len(result["reused"]) >= 19
    assert all(item["value"] == "氧气" for item in labels)


def test_real_oxygen_ocr_is_corrected_without_propagating_wrong_vision_text(tmp_path, monkeypatch):
    clean = prepare_reference(tmp_path, "test_03.png")
    image, items, _ = opencv.run_detection(clean, tmp_path / "detection", remove_grid=False)
    sensors = [item for item in items if item.get("label_association") == "value_field_label"]
    parent_ids = {item["id"] for item in sensors}
    labels = [item for item in items if item.get("parent_id") in parent_ids]
    ocr.fill_text_values(image, labels, diagnostics=True)
    before = deepcopy(labels)

    async def incorrect_transcription(*args, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"text":"氩气"}'))])

    monkeypatch.setattr(name, "call_llm", incorrect_transcription)
    summary = name.refine_label_values(image, sensors + labels, model="test")
    assert len(labels) == 22
    assert all(item["value"] == "氧气" for item in labels)
    assert summary["model_calls"] == 0
    assert summary["failed"] == []
    assert summary["ocr_consensus"]
    assert [item["bbox"] for item in labels] == [item["bbox"] for item in before]
    assert all(item["ocr_candidates"] == original["ocr_candidates"] for item, original in zip(labels, before))


def test_repeated_ocr_corrects_an_isolated_high_confidence_error(tmp_path, monkeypatch):
    clean = prepare_reference(tmp_path, "test_03.png")
    image, items, _ = opencv.run_detection(clean, tmp_path / "detection", remove_grid=False)
    sensors = [item for item in items if item.get("label_association") == "value_field_label"]
    parent_ids = {item["id"] for item in sensors}
    labels = [item for item in items if item.get("parent_id") in parent_ids]
    for index, item in enumerate(labels):
        if index < 3:
            value = "氧气" if index < 2 else "氩气"
            item.update(value=value, recognition_confidence=95, recognition_status="recognized", ocr_candidates=[value])
        else:
            item.update(value="AA", recognition_confidence=40, recognition_status="needs_review", ocr_candidates=["AA", "氧气"])

    async def unexpected_call(*args, **kwargs):
        raise AssertionError("Reliable repeated OCR evidence should be used first")

    monkeypatch.setattr(name, "call_llm", unexpected_call)
    summary = name.refine_label_values(image, sensors + labels, model="test")
    assert all(item["value"] == "氧气" for item in labels)
    assert labels[2]["ocr_value"] == "氩气"
    assert labels[2]["recognition_status"] == "ocr_consensus"
    assert summary["model_calls"] == 0


@pytest.mark.parametrize("word", ["氮气", "氢气", "温度"])
def test_repeated_ocr_consensus_uses_image_evidence_instead_of_a_fixed_word(word):
    group = [
        {"value": word, "recognition_confidence": 95, "recognition_status": "recognized", "ocr_candidates": [word]},
        {"value": word, "recognition_confidence": 90, "recognition_status": "recognized", "ocr_candidates": [word]},
        {"value": "AA", "recognition_confidence": 40, "recognition_status": "needs_review", "ocr_candidates": ["AA", word]},
    ]
    assert name.repeated_label_consensus(group) == word


@pytest.mark.parametrize("scenario", ["one_reliable", "conflicting_reliable", "insufficient_support"])
def test_repeated_ocr_consensus_requires_agreement_and_support(scenario):
    reliable = {"value": "氧气", "recognition_confidence": 95, "recognition_status": "recognized", "ocr_candidates": ["氧气"]}
    uncertain = {"value": "AA", "recognition_confidence": 40, "recognition_status": "needs_review", "ocr_candidates": ["AA", "氧气"]}
    if scenario == "one_reliable":
        group = [dict(reliable), dict(uncertain), dict(uncertain)]
    elif scenario == "conflicting_reliable":
        group = [dict(reliable), dict(reliable), dict(reliable, value="氮气", ocr_candidates=["氮气"]), dict(reliable, value="氮气", ocr_candidates=["氮气"])]
    else:
        group = [dict(reliable), dict(reliable)] + [dict(uncertain, ocr_candidates=["AA"]) for _ in range(3)]
    assert name.repeated_label_consensus(group) is None


@pytest.mark.parametrize("first,other", [("氧气", "氮气"), ("氧气", "氢气"), ("氧气", "氯气"), ("氧气", "温度"), ("氧气", "风机"), ("探头1", "探头2"), ("氧气1", "氧气7"), ("AP11P", "AP12P")])
def test_similar_chinese_labels_are_not_reused(first, other):
    fonts = [Path("/System/Library/Fonts/STHeiti Light.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
    font_path = next((path for path in fonts if path.is_file()), None)
    if font_path is None:
        pytest.skip("Chinese font is not available")
    font = ImageFont.truetype(str(font_path), 24)
    masks = []
    for value in (first, other):
        image = Image.new("RGB", (160, 40), "white")
        ImageDraw.Draw(image).text((3, 2), value, font=font, fill=(73, 73, 73))
        masks.append(name._glyph_appearance(np.array(image)))
    assert not name._same_glyphs(*masks)


@pytest.mark.parametrize("failure", ["exception", "unknown"])
def test_failed_repeated_label_is_not_reused(tmp_path, monkeypatch, failure):
    clean = prepare_reference(tmp_path, "test_03.png")
    image, items, _ = opencv.run_detection(clean, tmp_path / "detection", remove_grid=False)
    sensors = [item for item in items if item.get("label_association") == "value_field_label"]
    group = name.group_control_candidates(image, sensors, 0.5)[0][:3]
    sensors = [sensors[index] for index in group]
    labels = [item for item in items if item.get("parent_id") in {sensor["id"] for sensor in sensors}]
    for item in labels:
        item.update(value="uncertain", recognition_status="needs_review")
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            if failure == "exception":
                raise RuntimeError("Unavailable")
            content = '{"text":null}'
        else:
            content = '{"text":"氧气"}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(name, "call_llm", call)
    result = name.refine_label_values(image, sensors + labels, model="test")
    assert result["model_calls"] == len(calls) == 3
    assert result["reused"] == []
    assert result["failed"] == [labels[0]["id"]]
    assert labels[0]["value"] == "uncertain"
    assert all(item["value"] == "氧气" for item in labels[1:])


@pytest.mark.parametrize("difference", ["color", "label", "size"])
def test_value_field_groups_keep_distinct_equipment_separate(difference):
    image = np.full((100, 300, 3), 255, np.uint8)
    items = []
    for index, x in enumerate((30, 130)):
        color = (10, 180, 80) if difference == "color" and index else (180, 80, 10)
        label = "A2" if difference == "label" and index else "A1"
        cv2.circle(image, (x + 10, 30), 8, color, -1)
        cv2.putText(image, label, (x, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        items.append({"id": str(index), "type": "controls", "control_kind": "equipment_candidate", "bbox": [x, 20, 25 if difference == "size" and index else 20, 20], "label_bboxes": [[x, 60, 30, 20]], "label_association": "value_field_label"})
    assert name.group_control_candidates(image, items, 0.5) == [[0], [1]]


def test_agent_i_retry_configuration_does_not_change_shared_client():
    retries = name.default_client.max_retries
    client = name.create_vision_client()
    assert client.max_retries == 0
    assert name.default_client.max_retries == retries
    asyncio.run(client.close())
