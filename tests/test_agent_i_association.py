import copy
import json
import tempfile
import unittest
from pathlib import Path

from picture.AgentI.association import associate, extract_spatial_logic


def node(identifier, layer, bbox, parent=None, association=None):
    return {"id": identifier, "layer": layer, "bbox": bbox,
            "parent_id": parent, "association": association}


def detection(nodes):
    return {"image_size": {"width": 1920, "height": 1080},
            "bbox_format": "x_y_width_height", "nodes": nodes}


class AssociationTests(unittest.TestCase):
    def test_direction_distance_and_global_component_relations(self):
        result = extract_spatial_logic(detection([
            node("a", "component", [0, 0, 10, 10]),
            node("b", "component", [110, 0, 10, 10]),
            node("c", "text", [500, 500, 10, 10]),
        ]))
        self.assertEqual(len(result["spatial_relations"]), 1)
        pair = result["spatial_relations"][0]
        self.assertEqual(pair["relations"], ["left_of", "same_row"])
        self.assertEqual(pair["offset"], [110, 0])
        self.assertEqual(pair["edge_distance"], 100)
        self.assertEqual(pair["center_distance"], 110)

    def test_containment_overlap_touch_and_equal_boxes(self):
        cases = [
            ([2, 2, 2, 2], "contains", 0.04),
            ([5, 5, 10, 10], "overlaps", round(25 / 175, 6)),
            ([10, 0, 10, 10], "touches", 0),
            ([0, 0, 10, 10], "same_bbox", 1),
            ([-1, -1, 12, 12], "inside", round(100 / 144, 6)),
        ]
        for bbox, relation, iou in cases:
            with self.subTest(relation=relation):
                result = extract_spatial_logic(detection([
                    node("a", "control", [10, 10, 10, 10]),
                    node("b", "text", [bbox[0] + 10, bbox[1] + 10, bbox[2], bbox[3]]),
                ]))
                pair = result["spatial_relations"][0]
                self.assertIn(relation, pair["relations"])
                self.assertEqual(pair["iou"], iou)
                self.assertEqual(pair["edge_distance"], 0)

    def test_diagonal_gap_and_threshold(self):
        data = detection([node("a", "control", [0, 0, 10, 10]),
                          node("b", "text", [13, 14, 10, 10])])
        pair = extract_spatial_logic(data, near_distance=5)["spatial_relations"][0]
        self.assertEqual(pair["edge_distance"], 5)
        self.assertIn("left_of", pair["relations"])
        self.assertIn("above", pair["relations"])
        self.assertEqual(extract_spatial_logic(data, near_distance=4.9)["spatial_relations"], [])

    def test_hierarchy_preserves_inferred_ownership_without_implying_containment(self):
        inferred = {"method": "nearest_candidate", "confidence": 0.6}
        data = detection([
            node("grid", "grid", [0, 0, 1920, 1080]),
            node("equipment", "component", [100, 100, 30, 30], "grid"),
            node("control", "control", [150, 100, 30, 20], "equipment", inferred),
            node("text", "text", [155, 105, 10, 10], "control"),
            node("page_text", "text", [400, 400, 20, 10], "grid"),
        ])
        original = copy.deepcopy(data)
        result = extract_spatial_logic(data)
        self.assertEqual(data, original)
        self.assertEqual(result["component_groups"], [{"component_id": "equipment",
                         "control_ids": ["control"], "text_ids": ["text"]}])
        self.assertEqual(result["unassigned_node_ids"], ["page_text"])
        edge = next(e for e in result["hierarchy_relations"] if e["source"] == "control")
        self.assertFalse(edge["geometrically_contained"])
        self.assertEqual(edge["association"], inferred)
        self.assertFalse(any("grid" in (p["source"], p["target"]) for p in result["spatial_relations"]))

    def test_alignment_groups_do_not_chain_or_mix_layers(self):
        data = detection([
            node("a", "component", [100, 100, 10, 10]),
            node("b", "component", [50, 109, 10, 10]),
            node("c", "component", [150, 118, 10, 10]),
            node("d", "text", [160, 100, 10, 10]),
        ])
        groups = extract_spatial_logic(data)["alignment_groups"]["rows"]
        self.assertEqual(groups, [{"layer": "component", "coordinate": 109.5, "node_ids": ["b", "a"]}])

    def test_scaled_coordinates_preserve_relations(self):
        data = detection([node("a", "control", [100, 100, 20, 20]),
                          node("b", "text", [150, 106, 10, 10])])
        scaled = copy.deepcopy(data)
        scaled["image_size"] = {"width": 960, "height": 540}
        for item in scaled["nodes"]:
            item["bbox"] = [v / 2 for v in item["bbox"]]
        original, smaller = extract_spatial_logic(data), extract_spatial_logic(scaled)
        self.assertEqual(original["spatial_relations"][0]["relations"], smaller["spatial_relations"][0]["relations"])
        self.assertEqual(original["nodes"][0]["normalized_bbox"], smaller["nodes"][0]["normalized_bbox"])

    def test_invalid_input_and_cycles(self):
        invalid = [
            detection([node("a", "text", [0, 0, 0, 10])]),
            detection([node("a", "text", [0, 0, float("nan"), 10])]),
            detection([node("a", "text", [0, 0, 10, 10], "missing")]),
            detection([node("a", "text", [0, 0, 10, 10], "b"),
                       node("b", "control", [0, 0, 10, 10], "a")]),
            detection([node("a", "text", [0, 0, 10, 10]), node("a", "text", [0, 0, 10, 10])]),
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                extract_spatial_logic(data)
        for distance in (-1, float("inf"), True):
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                extract_spatial_logic(detection([]), near_distance=distance)

    def test_file_output_and_input_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detections.json"
            content = json.dumps(detection([]))
            path.write_text(content, encoding="utf-8")
            result = associate(path)
            self.assertEqual(json.loads(path.with_name("associations.json").read_text(encoding="utf-8")), result)
            with self.assertRaises(ValueError):
                associate(path, path)
            self.assertEqual(path.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
