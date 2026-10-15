import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from picture.AgentI import name
from tests.conftest import make_fake_completion


def restore_event_loop():
    try:
        asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class NameTests(unittest.TestCase):
    def setUp(self):
        restore_event_loop()
        self.addCleanup(restore_event_loop)
        os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image_path = self.root / "output.png"
        self.image = np.full((200, 300, 3), 255, np.uint8)
        self.image_path.write_bytes(cv2.imencode(".png", self.image)[1].tobytes())
        self.detections = self.root / "detections_02.json"
        self.output = self.root / "detections_03.json"
        self.db = self.root / "material.db"
        self.create_db([("冷却塔", "a.png"), ("冷却泵", "b.png"), ("按钮", "c.png"), ("冷却塔", "d.png")])
        self.items = [
            {"id": "controls_1", "type": "controls", "bbox": [0, 0, 20, 20], "value": None},
            {"id": "controls_2", "type": "controls", "bbox": [40, 0, 30, 30], "value": "previous", "extra": {"key": 1}},
            {"id": "text_1", "type": "text", "bbox": [0, 100, 50, 10], "value": "冷却水回水"},
        ]
        self.save_items()

    def create_db(self, rows):
        connection = sqlite3.connect(str(self.db))
        connection.execute(
            "CREATE TABLE IF NOT EXISTS query_results (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, "
            "displayName TEXT NOT NULL, image TEXT, width REAL, height REAL)"
        )
        connection.execute("DELETE FROM query_results")
        connection.executemany("INSERT INTO query_results (query, displayName, image) VALUES (?, ?, ?)",
                               [(row[0], row[0], row[1]) for row in rows])
        connection.commit()
        connection.close()

    def save_items(self):
        self.detections.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")

    def recognize(self, answers, failures=(), **kwargs):
        boxes = {item["id"]: item["bbox"] for item in self.items if item["type"] == "controls"}
        resolved = {
            name.encode_crop(self.image, boxes[identifier], kwargs.get("context", name.DEFAULT_CONTEXT)): reply
            for identifier, reply in answers.items()
        }

        async def fake_call_llm(client, model, messages, **options):
            url = messages[1]["content"][1]["image_url"]["url"]
            if url in failures:
                raise RuntimeError("模型调用失败")
            return make_fake_completion(resolved[url])

        with patch.object(name, "call_llm", fake_call_llm):
            return name.run(self.image_path, self.detections, self.output, self.db, "test-model", **kwargs)

    def test_updates_only_controls_and_preserves_source(self):
        original = self.detections.read_bytes()
        summary = self.recognize({"controls_1": '{"name": "冷却塔"}', "controls_2": '{"name": "冷却泵#2"}'})
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(result[0], dict(self.items[0], value="冷却塔"))
        self.assertEqual(result[1], dict(self.items[1], value="冷却泵"))
        self.assertEqual(result[2], self.items[2])
        self.assertEqual(self.detections.read_bytes(), original)
        self.assertEqual(summary["matched"], ["controls_1", "controls_2"])
        self.assertEqual(summary["unknown"], [])
        self.assertEqual(summary["failed"], [])

    def test_unknown_control_keeps_model_name(self):
        summary = self.recognize({"controls_1": '{"name": "补水箱"}', "controls_2": '{"name": "流量计"}'})
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(result[0]["value"], "补水箱(unknow)")
        self.assertEqual(result[1]["value"], "流量计(unknow)")
        self.assertEqual(summary["unknown"], ["controls_1", "controls_2"])
        self.assertEqual(summary["matched"], [])

    def test_tolerates_fenced_and_padded_response(self):
        self.recognize({"controls_1": '```json\n{"name": "按钮"}\n```',
                        "controls_2": '识别结果如下：{"name": "冷却泵"} 请核对'})
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(result[0]["value"], "按钮")
        self.assertEqual(result[1]["value"], "冷却泵")

    def test_failure_leaves_value_untouched(self):
        box = self.items[0]["bbox"]
        broken = name.encode_crop(self.image, box, 0.0)
        summary = self.recognize({"controls_2": '{"name": "冷却塔"}'}, failures=(broken,))
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertIsNone(result[0]["value"])
        self.assertEqual(result[1]["value"], "冷却塔")
        self.assertEqual(summary["failed"], ["controls_1"])

    def test_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            name.run(self.image_path, self.detections, self.image_path, self.db, "test-model")
        with self.assertRaises(ValueError):
            self.recognize({}, concurrency=0)
        with self.assertRaises(ValueError):
            self.recognize({}, context=3.0)

    def test_load_whitelist_dedupes(self):
        self.assertEqual(sorted(name.load_whitelist(self.db)), sorted(["冷却塔", "冷却泵", "按钮"]))

    def test_load_whitelist_rejects_empty_and_missing(self):
        self.create_db([])
        with self.assertRaises(ValueError):
            name.load_whitelist(self.db)
        with self.assertRaises(ValueError):
            name.load_whitelist(self.root / "missing.db")

    def test_parse_name_rejects_garbage(self):
        for content in ("", "没有对象", '{"other": "冷却塔"}', '{"name": ""}', '{"name": 3}'):
            with self.assertRaises(ValueError):
                name.parse_name(content)

    def test_normalize_prefers_whitelist_entry(self):
        whitelist = ["冷却塔", "绿相状态", "绿色状态", "状态显示"]
        self.assertEqual(name.normalize("冷却塔", whitelist), "冷却塔")
        self.assertEqual(name.normalize(" 冷却塔 ", whitelist), "冷却塔")
        self.assertEqual(name.normalize("绿色状态显示", whitelist), "绿色状态")
        self.assertEqual(name.normalize("压缩机", whitelist), "压缩机(unknow)")

    def test_expand_bbox_clips_to_image(self):
        self.assertEqual(name.expand_bbox(self.image, [0, 0, 20, 20], 1.0), [0, 0, 40, 40])
        self.assertEqual(name.expand_bbox(self.image, [280, 180, 20, 20], 1.0), [260, 160, 40, 40])
        self.assertEqual(name.expand_bbox(self.image, [10, 10, 20, 20], 0.0), [10, 10, 20, 20])

    def test_read_inputs_rejects_bad_bbox(self):
        self.items[0]["bbox"] = [0, 0, 20]
        self.save_items()
        with self.assertRaises(ValueError):
            name.read_inputs(self.image_path, self.detections)

    def test_dump_crops_writes_every_control(self):
        directory = self.root / "crops"
        self.recognize({"controls_1": '{"name": "冷却塔"}', "controls_2": '{"name": "冷却泵"}'},
                       dump_crops=directory)
        self.assertEqual(sorted(path.name for path in directory.iterdir()),
                         ["controls_1.png", "controls_2.png"])


if __name__ == "__main__":
    unittest.main()
