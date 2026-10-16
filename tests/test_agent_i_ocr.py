import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from picture.AgentI import ocr


CHINESE_FONT = next((path for path in (
    Path('/System/Library/Fonts/STHeiti Light.ttc'),
    Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
) if path.is_file()), None)


class OCRTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image = self.root / "画面.png"
        self.detections = self.root / "detections_01.json"
        self.output = self.root / "detections_02.json"
        self.image.write_bytes(cv2.imencode(".png", np.full((80, 200, 3), 255, np.uint8))[1].tobytes())
        self.items = [
            {"id": "device_9", "type": "controls", "bbox": [0, 0, 20, 30], "value": "unchanged", "extra": {"key": 1}},
            {"id": "label_17", "type": "text", "bbox": [30, 10, 70, 16], "value": None},
            {"id": "label_2", "type": "text", "bbox": [30, 40, 90, 20], "value": "previous"},
        ]
        self.save_items()

    def save_items(self):
        self.detections.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")

    def extract(self, **kwargs):
        return ocr.extract_text(self.image, self.detections, self.output, **kwargs)

    def test_updates_only_text_and_preserves_source(self):
        original = self.detections.read_bytes()
        replies = {(68, 230): ocr.Recognition("冷却水回水", 95), (68, 236): ocr.Recognition("Pump A", 88)}

        def fake_recognize(image, *args):
            return replies[image.shape[:2]]

        with patch.object(ocr, "check_engine", return_value="tesseract"), patch.object(
            ocr, "recognize", side_effect=fake_recognize,
        ) as recognize:
            summary = self.extract(psm=6)
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(result[0], self.items[0])
        self.assertEqual(result[1], dict(self.items[1], value="冷却水回水"))
        self.assertEqual(result[2], dict(self.items[2], value="Pump A"))
        self.assertEqual(self.detections.read_bytes(), original)
        self.assertEqual(recognize.call_count, 2)
        self.assertEqual(summary["text_count"], 2)
        self.assertEqual(summary["recognized"], 2)

    def test_empty_and_low_confidence_candidates(self):
        queues = {
            (68, 230): [ocr.Recognition("", 0), ocr.Recognition("1.5米", 40), ocr.Recognition("1.5米", 30)],
            (68, 236): [ocr.Recognition("", 0), ocr.Recognition("", 0), ocr.Recognition("", 0)],
        }

        def fake_recognize(image, *args):
            return queues[image.shape[:2]].pop(0)

        with patch.object(ocr, "check_engine", return_value="tesseract"), patch.object(
            ocr, "recognize", side_effect=fake_recognize,
        ):
            summary = self.extract(psm=6)
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(result[1]["value"], "1.5米")
        self.assertIsNone(result[2]["value"])
        self.assertEqual(summary["unrecognized"], ["label_2"])
        self.assertEqual(summary["low_confidence"], [{"id": "label_17", "confidence": 40}])
        self.assertEqual(summary["tesseract_calls"], 6)

    def test_fallback_selects_higher_confidence_without_overwriting_good_result(self):
        queues = {
            (68, 230): [ocr.Recognition("AC6", 55), ocr.Recognition("ACG", 30), ocr.Recognition("ACG", 40)],
            (68, 236): [ocr.Recognition("R相", 42), ocr.Recognition("R相", 91)],
        }

        def fake_recognize(image, *args):
            return queues[image.shape[:2]].pop(0)

        with patch.object(ocr, "check_engine", return_value="tesseract"), patch.object(
            ocr, "recognize", side_effect=fake_recognize,
        ):
            self.extract(psm=6)
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual([item["value"] for item in result[1:]], ["AC6", "R相"])

    def test_runtime_errors_leave_input_and_existing_output_intact(self):
        original = self.detections.read_bytes()
        self.output.write_bytes(b"previous output")
        for error in (RuntimeError("failed"), subprocess.TimeoutExpired("tesseract", 1)):
            def fake_recognize(image, *args, error=error):
                if image.shape[:2] == (68, 236):
                    raise error
                return ocr.Recognition("first", 95)
            with self.subTest(error=type(error).__name__), patch.object(ocr, "check_engine", return_value="tesseract"), patch.object(
                ocr, "recognize", side_effect=fake_recognize,
            ):
                with self.assertRaisesRegex(RuntimeError, "label_2"):
                    self.extract(psm=6)
            self.assertEqual(self.output.read_bytes(), b"previous output")
            self.assertEqual(self.detections.read_bytes(), original)

    def test_invalid_boxes_fail_before_recognition(self):
        for box in ([0, 0, 0, 10], [-1, 0, 20, 10], [190, 0, 20, 10], [0, 75, 10, 10], [True, 0, 20, 10], [0.5, 0, 20, 10], [1, 2, 3]):
            with self.subTest(box=box):
                self.items[1]["bbox"] = box
                self.save_items()
                with patch.object(ocr, "check_engine") as engine, self.assertRaises(ValueError):
                    self.extract()
                engine.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_duplicate_text_ids_are_rejected(self):
        self.items[2]["id"] = self.items[1]["id"]
        self.save_items()
        with self.assertRaises(ValueError):
            self.extract()

    def test_invalid_json_and_image_are_rejected(self):
        for value in ({"nodes": self.items}, [None], "not an array"):
            with self.subTest(value=value):
                self.detections.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.extract()
                self.assertFalse(self.output.exists())
        self.save_items()
        self.image.write_bytes(b"invalid image bytes")
        with self.assertRaises(ValueError):
            self.extract()

    def test_invalid_parameters_do_not_create_output(self):
        for parameters in ({"target_height": 0}, {"timeout": -1}, {"timeout": float("nan")}, {"min_confidence": 101}, {"psm": 0}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.extract(**parameters)
            self.assertFalse(self.output.exists())

    def test_empty_text_list_needs_no_engine(self):
        self.items = self.items[:1]
        self.save_items()
        with patch.object(ocr, "check_engine") as engine:
            summary = self.extract()
        engine.assert_not_called()
        self.assertEqual(summary["text_count"], 0)
        self.assertEqual(json.loads(self.output.read_text()), self.items)

    def test_cannot_overwrite_inputs(self):
        for output in (self.image, self.detections):
            with self.subTest(output=output), self.assertRaises(ValueError):
                ocr.extract_text(self.image, self.detections, output)

    def test_missing_engine_and_language(self):
        with patch.object(ocr.shutil, "which", return_value=None), self.assertRaisesRegex(RuntimeError, "Tesseract"):
            ocr.check_engine("chi_sim+eng", 30)
        process = subprocess.CompletedProcess([], 0, stdout=b"List of available languages (1):\neng\n", stderr=b"")
        with patch.object(ocr.shutil, "which", return_value="tesseract"), patch.object(ocr.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "chi_sim"):
                ocr.check_engine("chi_sim+eng", 30)

    def test_process_failure_is_not_an_empty_recognition(self):
        process = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"bad engine")
        with patch.object(ocr.subprocess, "run", return_value=process), self.assertRaisesRegex(RuntimeError, "bad engine"):
            ocr.recognize(np.full((30, 80, 3), 255, np.uint8), "tesseract", "eng", 7, 30)

    def test_failed_atomic_replace_preserves_previous_output_and_removes_temporary(self):
        self.output.write_bytes(b"previous output")
        before = set(self.root.iterdir())
        with patch.object(ocr.os, "replace", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            ocr.write_atomic(self.output, self.items)
        self.assertEqual(self.output.read_bytes(), b"previous output")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_normalization_preserves_english_spacing_and_punctuation(self):
        self.assertEqual(ocr.normalize_text("  冷 却 水  Pump   A  1.5米 AC6  "), "冷却水 Pump A 1.5米 AC6")
        self.assertEqual(ocr.normalize_text("状态 : Pump A ;"), "状态: Pump A;")

    def test_default_compares_raw_line_even_when_primary_confidence_is_high(self):
        results = [ocr.Recognition("wig", 91), ocr.Recognition("W相", 90), ocr.Recognition("W相", 92)]
        with patch.object(ocr, "recognize", side_effect=results) as recognize:
            result = ocr.recognize_crop(np.full((16, 50, 3), 255, np.uint8), "tesseract", "chi_sim+eng", 7, 48, 60, 30)
        self.assertEqual(result.value, "W相")
        self.assertEqual([call.args[3] for call in recognize.call_args_list], [7, 13, 13])

    def test_tsv_handles_compact_mixed_labels_and_multiline(self):
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        rows = [
            "5\t1\t1\t1\t1\t1\t0\t0\t20\t30\t90\tR",
            "5\t1\t1\t1\t1\t2\t22\t0\t30\t30\t80\t相",
            "5\t1\t1\t1\t2\t1\t0\t40\t60\t30\t95\tPump",
            "5\t1\t1\t1\t2\t2\t75\t40\t20\t30\t95\tA",
        ]
        result = ocr.parse_tsv(header + "\n".join(rows))
        self.assertEqual(result.value, "R相\nPump A")
        self.assertEqual(result.confidence, 90)

    def test_adaptive_size_and_background_polarity(self):
        for height, expected_height in ((8, 52), (16, 68), (80, 100)):
            for background in (0, 255):
                with self.subTest(height=height, background=background):
                    crop = np.full((height, 100, 3), background, np.uint8)
                    for binary, conservative in ((False, False), (True, False), (False, True)):
                        result = ocr.prepare_crop(crop, 48, binary, conservative)
                        self.assertEqual(result.shape[0], expected_height)
                        self.assertTrue(np.all(result == 255))

    @unittest.skipUnless(shutil.which("tesseract"), "需要 Tesseract")
    def test_real_ocr_varied_sizes_colors_and_grid(self):
        executable = ocr.check_engine("eng", 30)
        palettes = [((255, 255, 255), (0, 0, 0)), ((20, 20, 20), (255, 255, 255)), ((255, 255, 255), (180, 50, 20)), ((100, 30, 10), (0, 255, 255))]
        for scale in (0.6, 1.0, 2.0):
            for background, foreground in palettes:
                with self.subTest(scale=scale, background=background, foreground=foreground):
                    size, baseline = cv2.getTextSize("Pump A 1.5m", cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, round(scale * 2)))
                    crop = np.full((size[1] + baseline + 8, size[0] + 12, 3), background, np.uint8)
                    if background == (255, 255, 255):
                        cv2.line(crop, (0, crop.shape[0] // 2), (crop.shape[1] - 1, crop.shape[0] // 2), (235, 220, 210), 1)
                    cv2.putText(crop, "Pump A 1.5m", (6, size[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, scale, foreground, max(1, round(scale * 2)), cv2.LINE_AA)
                    best = ocr.recognize_crop(crop, executable, "eng", 7, 48, 60, 30)
                    self.assertEqual(best.value, "Pump A 1.5m")

    @unittest.skipUnless(shutil.which("tesseract") and CHINESE_FONT, "需要 Tesseract 和中文字体")
    def test_real_ocr_chinese_and_mixed_labels_with_other_fonts_and_colors(self):
        try:
            executable = ocr.check_engine("chi_sim+eng", 30)
        except RuntimeError as error:
            self.skipTest(str(error))
        for size in (24, 40):
            font = ImageFont.truetype(str(CHINESE_FONT), size)
            for label in ("冷却水", "2.5MPa", "U相"):
                for background, foreground in (((255, 255, 255), (30, 70, 180)), ((20, 30, 80), (255, 255, 210))):
                    with self.subTest(size=size, label=label, background=background):
                        left, top, right, bottom = font.getbbox(label)
                        image = Image.new("RGB", (right - left + 8, bottom - top + 8), background)
                        ImageDraw.Draw(image).text((4 - left, 4 - top), label, font=font, fill=foreground)
                        crop = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                        result = ocr.recognize_crop(crop, executable, "chi_sim+eng", 7, 48, 60, 30)
                        self.assertEqual(result.value, label)

    @unittest.skipUnless(shutil.which("tesseract"), "需要 Tesseract")
    def test_real_multiline_mode_preserves_lines(self):
        crop = np.full((100, 220, 3), 255, np.uint8)
        for y, text in ((35, "Pump A"), (80, "Flow 12.5")):
            cv2.putText(crop, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
        executable = ocr.check_engine("eng", 30)
        result = ocr.recognize_crop(crop, executable, "eng", 6, 48, 60, 30)
        self.assertEqual(result.value, "Pump A\nFlow 12.5")


if __name__ == "__main__":
    unittest.main()
