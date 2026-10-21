import asyncio
from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from picture.AgentI import name


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def repeated_controls():
    image = np.full((100, 300, 3), 255, np.uint8)
    items = []
    for index, x in enumerate((30, 130, 230)):
        cv2.circle(image, (x + 10, 30), 8, (180, 80, 10), -1)
        items.append({"id": str(index), "type": "controls", "bbox": [x, 20, 20, 20], "control_kind": "equipment_candidate"})
    return image, items


def test_repeated_controls_share_one_request_and_keep_each_geometry(monkeypatch):
    image, items = repeated_controls()
    originals = deepcopy(items)
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        return completion('{"name":"氧气传感器"}')

    monkeypatch.setattr(name, "call_llm", call)
    summary = asyncio.run(name.recognize_all(image, items, ["氧气传感器"], "", None, "test", 32, 0.5))
    assert len(calls) == summary["model_calls"] == 1
    assert summary["reused"] == ["1", "2"]
    assert items == [dict(item, value="氧气传感器") for item in originals]


@pytest.mark.parametrize("difference", ["color", "label", "context", "size"])
def test_different_controls_are_classified_separately(monkeypatch, difference):
    image, items = repeated_controls()
    items = items[:2]
    if difference == "color":
        cv2.circle(image, (140, 30), 8, (10, 180, 80), -1)
    elif difference == "label":
        items[0]["semantic_labels"] = ["氧气"]
        items[1]["semantic_labels"] = ["氮气"]
    elif difference == "context":
        image[10:20, 120:150] = 0
    else:
        items[1]["bbox"][2] = 25
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        return completion('{"name":"传感器"}')

    monkeypatch.setattr(name, "call_llm", call)
    summary = asyncio.run(name.recognize_all(image, items, ["传感器"], "", None, "test", 32, 0.5))
    assert len(calls) == 2
    assert summary["reused"] == []


@pytest.mark.parametrize("first", ["unknown", "failed"])
def test_unknown_or_failed_representative_does_not_propagate(monkeypatch, first):
    image, items = repeated_controls()
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            if first == "failed":
                raise RuntimeError("模型异常")
            return completion('{"name":"其他传感器"}')
        return completion('{"name":"氧气传感器"}')

    monkeypatch.setattr(name, "call_llm", call)
    summary = asyncio.run(name.recognize_all(image, items, ["氧气传感器"], "", None, "test", 32, 0.5))
    assert len(calls) == 3
    assert summary["reused"] == []
    assert [item["value"] for item in items[1:]] == ["氧气传感器", "氧气传感器"]
    assert summary["failed"] == (["0"] if first == "failed" else [])


def test_reliable_labels_skip_review_but_uncertain_texts_are_reviewed(monkeypatch):
    reliable = {"type": "text", "bbox": [0, 0, 40, 20], "value": "氧气", "recognition_status": "recognized", "recognition_confidence": 95, "ocr_candidates": ["氧气"]}
    cases = [
        {},
        {"vision_value": "氧气", "recognition_status": "needs_review"},
        {"recognition_status": "vision_transcribed"},
        {"recognition_confidence": 59},
        {"ocr_candidates": ["氧气", "氮气"]},
        {"value": "", "ocr_candidates": []},
        {"recognition_status": "needs_review"},
    ]
    texts = [dict(reliable, id=str(index), **changes) for index, changes in enumerate(cases)]
    original = deepcopy(texts)
    items = [{"id": "control", "type": "controls", "label_bboxes": [[0, 0, 40, 20]]}] + texts
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        return completion('{"text":"氧气"}')

    monkeypatch.setattr(name, "call_llm", call)
    summary = name.refine_label_values(np.full((30, 50, 3), 255, np.uint8), items, model="test")
    assert len(calls) == summary["labels"] == 4
    assert summary["skipped"] == 3
    assert summary["refined"] == ["3", "4", "5", "6"]
    assert texts[:3] == original[:3]


def test_precise_label_pixels_prevent_reuse_with_different_names():
    image, items = repeated_controls()
    items = items[:2]
    for item, label in zip(items, ("A", "B")):
        x = item["bbox"][0]
        item["label_bboxes"] = [[x, 60, 25, 20]]
        cv2.putText(image, label, (x, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    assert name.group_control_candidates(image, items, 0.5) == [[0], [1]]
