from __future__ import annotations

from typing import Any, Optional

import pytest

from model.refine_agent import (
    RefineAgent,
    RefineInputError,
    _ControlGeometry,
    _make_label_map,
)
from tests.conftest import FakeAsyncClient, make_fake_completion


def _control(
    node_i: int,
    name: str = "泵",
    image: str = "symbols/pump.json",
    s: Any = None,
    c: Optional[str] = "ht.Node",
    with_s_key: bool = False,
) -> dict:
    item: dict = {
        "c": c,
        "i": node_i,
        "a": {
            "layout.node": True,
            "layout.sourceWidth": 200,
            "layout.sourceHeight": 100,
        },
        "p": {
            "displayName": name,
            "image": image,
            "position": {"x": 300, "y": 300},
            "width": 100,
            "height": 50,
        },
    }
    if with_s_key or s is not None:
        item["s"] = s
    return item


def _label(node_i: int, label_for: int, text: str = "泵") -> dict:
    return {
        "c": "ht.Text",
        "i": node_i,
        "a": {"layout.role": "control-label", "layout.labelFor": label_for},
        "p": {"position": {"x": 300, "y": 226}, "width": 100, "height": 32},
        "s": {"text": text},
    }


def _json(*entries: dict) -> dict:
    return {"a": {"width": 1920, "height": 1080}, "d": list(entries)}


def _geometry(node_i: int) -> _ControlGeometry:
    return _ControlGeometry(
        node_i=node_i,
        index=node_i - 1,
        x=0,
        y=0,
        width=1,
        height=1,
        original_x=0,
        original_y=0,
        original_width=1,
        original_height=1,
        has_width=True,
        has_height=True,
        node_type="ht.Node",
    )


async def _refine(actions_json: str, json_data: Optional[dict] = None):
    fake = FakeAsyncClient(
        [make_fake_completion('{"actions": ' + actions_json + ', "message": "ok"}')]
    )
    agent = RefineAgent(client=fake)
    return await agent.refine(
        "name", json_data if json_data is not None else _json(_control(1))
    )


def _ops(patch, path):
    return [op["value"] for op in patch if op.get("path") == path]


def _op_items(patch, path):
    return [op for op in patch if op.get("path") == path]


def _first_style_value(patch, key):
    for op in patch:
        if op.get("path") == "/d/0/s" and op.get("op") == "add":
            return op["value"].get(key)
    for op in patch:
        if op.get("path") == f"/d/0/s/{key}":
            return op["value"]
    return None


class TestFirstNaming:
    @pytest.mark.asyncio
    async def test_first_naming_emits_exact_three_fields(self):
        result = await _refine('[{"type":"add_label","target_ids":[1]}]')
        assert len(result.patch) == 1
        op = result.patch[0]
        assert op == {
            "op": "add",
            "path": "/d/0/s",
            "value": {
                "label": "泵",
                "label.color": "rgb(255,255,255)",
                "label.font": "18px arial, sans-serif",
            },
        }

    @pytest.mark.asyncio
    async def test_first_naming_adds_no_new_d_element(self):
        result = await _refine('[{"type":"add_label","target_ids":[1]}]')
        assert all(op.get("path") != "/d/-" for op in result.patch)
        assert all(op.get("op") != "remove" for op in result.patch)

    @pytest.mark.asyncio
    async def test_s_null_treated_as_missing(self):
        data = _json(_control(1, s=None, with_s_key=True))
        result = await _refine('[{"type":"add_label","target_ids":[1],"text":"入口阀"}]', data)
        assert _first_style_value(result.patch, "label") == "入口阀"

    @pytest.mark.asyncio
    async def test_long_name_succeeds(self):
        long_name = "长" * 300
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"' + long_name + '"}]'
        )
        assert _first_style_value(result.patch, "label") == long_name


class TestExistingStyle:
    @pytest.mark.asyncio
    async def test_existing_s_preserves_keys_and_chooses_add_replace(self):
        data = _json(_control(1, s={"opacity": 1, "label.color": "white"}))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"}]', data
        )
        assert _ops(result.patch, "/d/0/s") == []
        label_ops = _op_items(result.patch, "/d/0/s/label")
        assert len(label_ops) == 1
        assert label_ops[0]["op"] == "add"
        assert label_ops[0]["value"] == "入口阀"
        color_ops = _op_items(result.patch, "/d/0/s/label.color")
        assert len(color_ops) == 1
        assert color_ops[0]["op"] == "replace"
        assert color_ops[0]["value"] == "rgb(255,255,255)"
        font_ops = _op_items(result.patch, "/d/0/s/label.font")
        assert len(font_ops) == 1
        assert font_ops[0]["op"] == "add"
        assert font_ops[0]["value"] == "18px arial, sans-serif"

    @pytest.mark.asyncio
    async def test_rename_same_value_emits_nothing(self):
        s = {
            "label": "入口阀",
            "label.color": "rgb(255,255,255)",
            "label.font": "18px arial, sans-serif",
        }
        data = _json(_control(1, s=s))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"}]', data
        )
        assert result.patch == []

    @pytest.mark.asyncio
    async def test_rename_updates_value_and_fixes_styles(self):
        data = _json(_control(1, s={"label": "旧名", "label.color": "red", "label.font": "12px Arial"}))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"新名"}]', data
        )
        assert _ops(result.patch, "/d/0/s/label") == ["新名"]
        assert _ops(result.patch, "/d/0/s/label.color") == ["rgb(255,255,255)"]
        assert _ops(result.patch, "/d/0/s/label.font") == ["18px arial, sans-serif"]


class TestNameSources:
    @pytest.mark.asyncio
    async def test_default_name_uses_display_name(self):
        data = _json(_control(1, name="液压泵"))
        result = await _refine('[{"type":"add_label","target_ids":[1]}]', data)
        assert _first_style_value(result.patch, "label") == "液压泵"

    @pytest.mark.asyncio
    async def test_single_text_used_as_is(self):
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"}]'
        )
        assert _first_style_value(result.patch, "label") == "入口阀"

    @pytest.mark.asyncio
    async def test_multi_text_numbered(self):
        data = _json(_control(1), _control(2))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1,2],"text":"阀门"}]', data
        )
        assert _first_style_value(result.patch, "label") == "阀门1"
        assert any(
            op.get("path") == "/d/1/s" and op["value"]["label"] == "阀门2"
            for op in result.patch
        )

    @pytest.mark.asyncio
    async def test_names_string_keys_normalized(self):
        data = _json(_control(1), _control(2))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1,2],"names":{"1":"入口阀","2":"出口阀"}}]',
            data,
        )
        assert _first_style_value(result.patch, "label") == "入口阀"
        assert any(
            op.get("path") == "/d/1/s" and op["value"]["label"] == "出口阀"
            for op in result.patch
        )


class TestRejectedInputs:
    async def _assert_rejected(self, actions_json, data=None, keyword=None):
        result = await _refine(actions_json, data)
        assert result.patch == []
        if keyword:
            assert keyword in result.message

    @pytest.mark.asyncio
    async def test_names_integer_keys_rejected(self):
        controls = {1: _geometry(1)}
        with pytest.raises(RefineInputError, match="JSON strings"):
            _make_label_map({"target_ids": [1], "names": {1: "b"}}, controls, [])

    @pytest.mark.asyncio
    async def test_names_unknown_id_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"names":{"99":"x"}}]',
            keyword="unknown ID 99",
        )

    @pytest.mark.asyncio
    async def test_names_missing_target_rejected(self):
        data = _json(_control(1), _control(2))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1,2],"names":{"1":"x"}}]',
            data=data,
            keyword="missing entry",
        )

    @pytest.mark.asyncio
    async def test_names_padded_key_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"names":{"01":"x"}}]',
            keyword="exactly",
        )

    @pytest.mark.asyncio
    async def test_blank_name_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"text":"  "}]',
            keyword="empty",
        )

    @pytest.mark.asyncio
    async def test_leading_trailing_space_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"text":" x "}]',
            keyword="whitespace",
        )

    @pytest.mark.asyncio
    async def test_newline_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"text":"a\\nb"}]',
            keyword="newlines",
        )

    @pytest.mark.asyncio
    async def test_control_char_rejected(self):
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1],"text":"a\\u0001b"}]',
            keyword="control characters",
        )

    @pytest.mark.asyncio
    async def test_non_node_target_rejected(self):
        data = _json(_control(1, c=None))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1]}]',
            data=data,
            keyword="not an ht.Node",
        )

    @pytest.mark.asyncio
    async def test_ht_text_target_rejected(self):
        data = _json(_control(1, c="ht.Text"))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1]}]',
            data=data,
            keyword="not an ht.Node",
        )

    @pytest.mark.asyncio
    async def test_non_object_s_rejected(self):
        data = _json(_control(1, s="bad"))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1]}]',
            data=data,
            keyword="must be an object",
        )

    @pytest.mark.asyncio
    async def test_list_s_rejected(self):
        data = _json(_control(1, s=[1, 2]))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1]}]',
            data=data,
            keyword="must be an object",
        )

    @pytest.mark.asyncio
    async def test_mixed_material_multi_rejected(self):
        data = _json(
            _control(1, image="symbols/pump.json"),
            _control(2, image="symbols/chiller.json"),
        )
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1,2],"text":"阀门"}]',
            data=data,
            keyword="same image type",
        )

    @pytest.mark.asyncio
    async def test_batch_atomic_failure(self):
        data = _json(_control(1), _control(2, c="ht.Text"))
        await self._assert_rejected(
            '[{"type":"add_label","target_ids":[1,2],"text":"阀门"}]',
            data=data,
            keyword="not an ht.Node",
        )


class TestLegacyLabels:
    @pytest.mark.asyncio
    async def test_rename_migrates_and_deletes_legacy_label(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"}]', data
        )
        paths = [op["path"] for op in result.patch]
        assert "/d/0/s" in paths
        assert "/d/1" in paths
        remove_index = next(
            i for i, op in enumerate(result.patch) if op.get("path") == "/d/1"
        )
        style_index = next(
            i for i, op in enumerate(result.patch) if op.get("path") == "/d/0/s"
        )
        assert remove_index > style_index
        assert all(op.get("path") != "/d/1/s/text" for op in result.patch)

    @pytest.mark.asyncio
    async def test_other_labels_and_titles_unaffected(self):
        title = {
            "c": "ht.Text",
            "i": 3,
            "a": {"layout.role": "title"},
            "p": {"position": {"x": 100, "y": 100}, "width": 200, "height": 40},
            "s": {"text": "背景标题"},
        }
        data = _json(_control(1), _control(2), _label(4, 1), _label(5, 2), title)
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"}]', data
        )
        removed = [op["path"] for op in result.patch if op.get("op") == "remove"]
        assert removed == ["/d/2"]
        assert all(op.get("path") != "/d/1/s/text" for op in result.patch)
        assert all(op.get("path") != "/d/3/s/text" for op in result.patch)

    @pytest.mark.asyncio
    async def test_legacy_label_follows_move(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine(
            '[{"type":"move","target_ids":[1],"dx":10,"dy":0}]', data
        )
        assert _ops(result.patch, "/d/0/p/position/x") == [310]
        assert _ops(result.patch, "/d/1/p/position/x") == [310]

    @pytest.mark.asyncio
    async def test_legacy_label_follows_resize(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine(
            '[{"type":"resize","target_ids":[1],"width":200}]', data
        )
        assert _ops(result.patch, "/d/1/p/position/y") != []
        assert _ops(result.patch, "/d/1/p/width") == [200]

    @pytest.mark.asyncio
    async def test_delete_removes_legacy_label(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine('[{"type":"delete","target_ids":[1]}]', data)
        removed = [op["path"] for op in result.patch if op.get("op") == "remove"]
        assert removed == ["/d/1", "/d/0"]

    @pytest.mark.asyncio
    async def test_naming_then_delete_no_orphan_style(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine(
            '[{"type":"add_label","target_ids":[1],"text":"入口阀"},{"type":"delete","target_ids":[1]}]',
            data,
        )
        assert all(not op.get("path", "").startswith("/d/0/s") for op in result.patch)
        removed = [op["path"] for op in result.patch if op.get("op") == "remove"]
        assert removed == ["/d/1", "/d/0"]

    @pytest.mark.asyncio
    async def test_delete_then_naming_no_orphan_style(self):
        data = _json(_control(1), _label(2, 1))
        result = await _refine(
            '[{"type":"delete","target_ids":[1]},{"type":"add_label","target_ids":[1],"text":"入口阀"}]',
            data,
        )
        assert all(not op.get("path", "").startswith("/d/0/s") for op in result.patch)
        removed = [op["path"] for op in result.patch if op.get("op") == "remove"]
        assert removed == ["/d/1", "/d/0"]
