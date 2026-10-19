from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from picture.AgentI.name import crop_named_control
from picture.AgentI import name as naming
from picture.AgentI.ocr import parse_tsv
from picture.AgentI.opencv import assign_parents, components_detection, controls_detection, read_image, run_detection
from picture.AgentI.resize_image import resize_image


PROJECT = Path(__file__).resolve().parents[1]
DENSE_EQUIPMENT = [
    (915, 118, 178, 138), (370, 173, 38, 38), (94, 200, 114, 120),
    (230, 208, 22, 32), (490, 239, 111, 92), (850, 264, 23, 32),
    (1406, 279, 101, 94), (299, 306, 24, 32), (1104, 318, 22, 32),
    (1724, 345, 93, 72), (96, 371, 116, 121), (490, 394, 101, 93),
    (1647, 395, 22, 32), (221, 396, 22, 31), (1396, 429, 105, 97),
    (907, 455, 180, 141), (299, 477, 22, 33), (1578, 479, 39, 40),
    (850, 527, 23, 32), (488, 541, 100, 93), (223, 563, 23, 32),
    (1596, 569, 70, 71), (100, 583, 115, 121), (1402, 585, 101, 93),
    (1119, 593, 22, 32), (301, 668, 22, 33), (487, 690, 100, 93),
    (1604, 703, 70, 72), (902, 736, 181, 141), (1400, 736, 101, 93),
    (1721, 736, 101, 72), (96, 772, 37, 38), (841, 807, 22, 31),
    (1163, 852, 22, 32),
]
TANK_EQUIPMENT = [
    (1422, 62, 32, 54), (1225, 65, 57, 54), (1321, 66, 39, 51),
    (1173, 153, 161, 254), (367, 391, 57, 54), (656, 391, 40, 50),
    (567, 392, 31, 54), (463, 393, 39, 50), (315, 489, 161, 254),
    (1434, 662, 31, 54), (1225, 665, 57, 54), (1321, 667, 39, 50),
    (1173, 749, 161, 254),
]
TANK_LABELS = [
    (1229, 123, 52, 16), (1306, 123, 70, 16), (1385, 123, 105, 16),
    (1219, 412, 68, 17), (370, 449, 50, 16), (448, 449, 67, 16),
    (530, 449, 102, 16), (648, 449, 70, 16), (361, 579, 68, 21),
    (1228, 723, 52, 17), (1306, 723, 70, 17), (1398, 723, 105, 17),
    (361, 748, 68, 17), (1218, 1008, 70, 17),
]


def iou(a, b):
    x, y, w, h = a
    bx, by, bw, bh = b
    overlap = max(0, min(x + w, bx + bw) - max(x, bx)) * max(0, min(y + h, by + bh) - max(y, by))
    return overlap / max(1, w * h + bw * bh - overlap)


@pytest.mark.parametrize("source,expected", [
    ("picture/AgentI/data/input.png", DENSE_EQUIPMENT),
    ("test_01.png", TANK_EQUIPMENT),
])
@pytest.mark.parametrize("factor", [0.75, 1.0, 1.5])
def test_reference_equipment_boxes_and_labels(tmp_path, source, expected, factor):
    path = PROJECT / source
    if not path.is_file():
        pytest.skip("Reference image is not available")
    clean = tmp_path / "clean.png"
    resize_image(path, tmp_path / "grid.png", clean_output_path=clean)
    image = read_image(clean)
    if factor != 1.0:
        image = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        assert cv2.imwrite(str(clean), image)
    _, exported, result = run_detection(clean, tmp_path / "detection", remove_grid=False)
    equipment = [item for item in result["nodes"] if item["type"] == "equipment_candidate"]
    assert len(equipment) == len(expected)
    matched = set()
    for box in expected:
        scaled = [round(value * factor) for value in box]
        index = max(range(len(equipment)), key=lambda i: iou(scaled, equipment[i]["bbox"]))
        assert index not in matched
        assert iou(scaled, equipment[index]["bbox"]) >= 0.65
        assert equipment[index]["label_bboxes"]
        matched.add(index)
    if source == "test_01.png":
        texts = [item for item in result["nodes"] if item["layer"] == "text"]
        assert len(texts) == len(TANK_LABELS)
        for box in TANK_LABELS:
            scaled = [round(value * factor) for value in box]
            match = max(texts, key=lambda item: iou(scaled, item["bbox"]))
            assert iou(scaled, match["bbox"]) >= 0.7
            assert match["parent_id"] != "grid_1"
    assert not result["text_filters"]["exclude_hash_names"]
    assert all("label_bboxes" in item for item in exported if item["type"] == "controls")


def test_large_neutral_equipment_at_page_edges():
    image = np.full((1080, 1920, 3), 255, np.uint8)
    cv2.rectangle(image, (2, 2), (152, 352), (155, 155, 155), -1)
    cv2.circle(image, (1870, 1025), 40, (170, 170, 170), -1)
    _, occupied = controls_detection(image, 1.0)
    equipment, _ = components_detection(image, occupied, 1.0)
    assert len(equipment) == 2
    assert max(item["bbox"][3] for item in equipment) >= 350
    assert any(item["bbox"][1] > 900 for item in equipment)


def test_label_association_uses_alignment_and_preserves_bottom_labels():
    controls = [
        {"id": "left", "type": "equipment_candidate", "bbox": [100, 900, 50, 60]},
        {"id": "right", "type": "equipment_candidate", "bbox": [200, 900, 50, 60]},
    ]
    texts = [
        {"id": "label", "bbox": [85, 970, 80, 16]},
        {"id": "ambiguous", "bbox": [135, 970, 80, 16]},
    ]
    assign_parents(controls, texts, 1.0)
    assert texts[0]["parent_id"] == "left"
    assert texts[1]["parent_id"] == "grid_1"
    assert controls[0]["label_bboxes"] == [[85, 970, 80, 16]]


def test_named_crop_includes_entire_wide_label():
    image = np.full((200, 300, 3), 255, np.uint8)
    image[120:140, 20:180] = 0
    crop = crop_named_control(image, {"bbox": [90, 60, 20, 40], "label_bboxes": [[20, 120, 160, 20]]}, 0.5)
    assert crop.shape == (103, 166, 3)
    assert np.count_nonzero(np.all(crop == 0, axis=2)) == 3200


def test_literal_quote_in_tesseract_tsv_does_not_swallow_following_rows():
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    rows = '5\t1\t1\t1\t1\t1\t0\t0\t5\t10\t90\t"\n5\t1\t1\t1\t1\t2\t10\t0\t20\t10\t90\t阀门#1\n'
    result = parse_tsv(header + rows)
    assert "阀门#1" in result.value
    assert "\t" not in result.value


@pytest.mark.parametrize("response,expected,status", [
    ('{"text":"阀门#3"}', "阀门#3", "vision_transcribed"),
    ('{"text":null}', "阀门起", "needs_review"),
])
def test_label_refinement_preserves_ocr_and_handles_uncertainty(monkeypatch, response, expected, status):
    image = np.full((100, 200, 3), 255, np.uint8)
    items = [
        {"id": "control", "type": "controls", "bbox": [20, 10, 30, 40], "value": "阀门", "label_bboxes": [[10, 60, 60, 16]]},
        {"id": "label", "type": "text", "bbox": [10, 60, 60, 16], "parent_id": "control", "value": "阀门起"},
        {"id": "unrelated", "type": "text", "bbox": [100, 60, 30, 16], "value": "环境"},
    ]

    async def fake_call(client, model, messages, **kwargs):
        assert "阀门" in messages[1]["content"][0]["text"]
        assert "阀门起" not in str(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))])

    monkeypatch.setattr(naming, "call_llm", fake_call)
    summary = naming.refine_label_values(image, items, model="test-model")
    assert summary["labels"] == 1
    assert items[1]["value"] == expected
    assert items[1]["recognition_status"] == status
    assert items[2]["value"] == "环境"
    if status == "vision_transcribed":
        assert items[1]["ocr_value"] == "阀门起"
        assert summary["failed"] == []
    else:
        assert summary["failed"] == ["label"]
