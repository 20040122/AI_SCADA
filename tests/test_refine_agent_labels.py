import pytest

from model.refine_agent import (
    _read_layout,
    _LabelInfo,
    _ControlGeometry,
    _validate_label_text,
    _compute_label_geometry,
    _make_label_map,
    _build_label_json,
    _compile_patch,
    _validate_patch,
    _apply_actions,
    RefineInputError,
    RefineModelError,
)


def _make_control_entry(
    i: int,
    display_name: str = "Valve",
    x: float = 100,
    y: float = 200,
    width: float = 80,
    height: float = 40,
    image: str = "valve.svg",
) -> dict:
    return {
        "c": "ht.Valve",
        "i": i,
        "p": {
            "displayName": display_name,
            "image": image,
            "position": {"x": x, "y": y},
            "width": width,
            "height": height,
        },
        "a": {"layout.node": f"n{i}", "layout.group": "g1", "layout.instance": 1},
    }


def _make_label_entry(
    i: int,
    label_for: int,
    text: str = "TestLabel",
    x: float = 100,
    y: float = 160,
    width: float = 96,
    height: float = 32,
) -> dict:
    return {
        "c": "ht.Text",
        "i": i,
        "p": {
            "position": {"x": x, "y": y},
            "width": width,
            "height": height,
            "tall": 20,
        },
        "s": {
            "text": text,
            "text.font": "bold 20px Arial",
            "text.color": "white",
            "text.align": "center",
            "opacity": 1,
            "layout.v": "top",
        },
        "a": {"layout.role": "control-label", "layout.labelFor": label_for},
    }


def _make_json(d_entries: list) -> dict:
    return {"v": "1", "p": {}, "a": {"width": 1000, "height": 800}, "d": d_entries}


# ---------------------------------------------------------------------------
# _read_layout with labels
# ---------------------------------------------------------------------------


def test_read_layout_parses_labels():
    json_data = _make_json([
        _make_control_entry(0, "Valve1", 100, 200),
        _make_label_entry(10, 0, "V1"),
    ])
    _, _, controls, _, labels, max_i = _read_layout(json_data)
    assert 0 in controls
    assert 0 in labels
    assert labels[0].label_for == 0
    assert labels[0].text == "V1"
    assert labels[0].node_i == 10
    assert max_i == 10


def test_read_layout_rejects_label_for_nonexistent_control():
    json_data = _make_json([_make_label_entry(10, 999)])
    with pytest.raises(RefineInputError, match="does not reference"):
        _read_layout(json_data)


def test_read_layout_rejects_duplicate_label():
    json_data = _make_json([
        _make_control_entry(0, "V1"),
        _make_label_entry(10, 0),
        _make_label_entry(11, 0),
    ])
    with pytest.raises(RefineInputError, match="duplicate label"):
        _read_layout(json_data)


def test_read_layout_keeps_orphan_ht_text():
    d = [
        _make_control_entry(0, "V1"),
        {
            "c": "ht.Text",
            "i": 10,
            "p": {"position": {"x": 50, "y": 50}},
            "s": {"text": "Manual text"},
        },
    ]
    _, _, controls, _, labels, max_i = _read_layout(_make_json(d))
    assert 0 in controls
    assert labels == {}
    assert max_i == 10


def test_read_layout_rejects_duplicate_node_id():
    json_data = _make_json([
        _make_control_entry(0, "V1"),
        _make_label_entry(0, 0),
    ])
    with pytest.raises(RefineInputError, match="duplicate node ID"):
        _read_layout(json_data)


def test_read_layout_max_node_i_empty():
    json_data = _make_json([])
    _, _, _, _, _, max_i = _read_layout(json_data)
    assert max_i == -1


# ---------------------------------------------------------------------------
# _validate_label_text
# ---------------------------------------------------------------------------


def test_validate_label_text_ok():
    assert _validate_label_text("Hello") == "Hello"
    assert _validate_label_text("阀门1") == "阀门1"


def test_validate_label_text_empty():
    with pytest.raises(RefineInputError, match="empty"):
        _validate_label_text("")


def test_validate_label_text_whitespace():
    with pytest.raises(RefineInputError, match="whitespace"):
        _validate_label_text("  foo  ")


def test_validate_label_text_control_chars():
    with pytest.raises(RefineInputError, match="control"):
        _validate_label_text("foo\x00bar")


def test_validate_label_text_newline():
    with pytest.raises(RefineInputError, match="newline"):
        _validate_label_text("foo\nbar")


# ---------------------------------------------------------------------------
# _compute_label_geometry
# ---------------------------------------------------------------------------


def _make_control(x=100, y=200, w=80, h=40, image="valve.svg", i=0):
    return _ControlGeometry(
        node_i=i, index=0,
        x=x, y=y, width=w, height=h,
        original_x=x, original_y=y, original_width=w, original_height=h,
        has_width=True, has_height=True,
        image=image,
    )


def test_compute_label_above_control():
    ctrl = _make_control(x=100, y=200)
    lw, lh, lx, ly = _compute_label_geometry(ctrl, "Hi", 1000, 800)
    assert lw == max(80, 2 * 20 + 16)
    assert lh == 32
    assert lx == 100
    expected_ly = 200 - 40 / 2 - 8 - 32 / 2
    assert ly == expected_ly


def test_compute_label_below_when_no_space_above():
    ctrl = _make_control(x=100, y=10, h=20)
    lw, lh, lx, ly = _compute_label_geometry(ctrl, "Hi", 1000, 800)
    expected_ly = 10 + 20 / 2 + 8 + 32 / 2
    assert ly == expected_ly


def test_compute_label_no_space_above_or_below():
    ctrl = _make_control(x=100, y=400, h=790)
    with pytest.raises(RefineInputError, match="no space"):
        _compute_label_geometry(ctrl, "Hi", 1000, 800)


def test_compute_label_width_clamped_to_text():
    ctrl = _make_control(x=100, y=200, w=30, h=40)
    lw, _, _, _ = _compute_label_geometry(ctrl, "LongerText", 1000, 800)
    expected = max(30, 10 * 20 + 16)
    assert lw == expected


def test_compute_label_width_exceeds_canvas():
    ctrl = _make_control(x=100, y=200)
    with pytest.raises(RefineInputError, match="too long"):
        _compute_label_geometry(ctrl, "X" * 100, 1000, 800)


def test_compute_label_horizontal_clamp_left():
    ctrl = _make_control(x=-50, y=200, w=80)
    lw, _, lx, _ = _compute_label_geometry(ctrl, "Hi", 1000, 800)
    assert lx == lw / 2


def test_compute_label_horizontal_clamp_right():
    ctrl = _make_control(x=1020, y=200, w=80)
    lw, _, lx, _ = _compute_label_geometry(ctrl, "Hi", 1000, 800)
    assert lx == 1000 - lw / 2


# ---------------------------------------------------------------------------
# _make_label_map
# ---------------------------------------------------------------------------


def _controls_dict(**extras):
    c = _make_control()
    for k, v in extras.items():
        setattr(c, k, v)
    return {0: c, 1: _make_control(x=200, y=300)}


def test_make_label_map_names():
    ctrls = _controls_dict()
    result = _make_label_map(
        {"type": "add_label", "target_ids": [0], "names": {0: "Foo"}},
        ctrls, [],
    )
    assert result == {0: "Foo"}


def test_make_label_map_single_text():
    ctrls = _controls_dict()
    result = _make_label_map(
        {"type": "add_label", "target_ids": [0], "text": "入口"},
        ctrls, [{"i": 0, "displayName": "V1"}],
    )
    assert result == {0: "入口"}


def test_make_label_map_multi_text_numbered():
    ctrls = _controls_dict()
    result = _make_label_map(
        {"type": "add_label", "target_ids": [0, 1], "text": "阀"},
        ctrls, [],
    )
    assert result == {0: "阀1", 1: "阀2"}


def test_make_label_map_default_display_name():
    ctrls = _controls_dict()
    result = _make_label_map(
        {"type": "add_label", "target_ids": [0]},
        ctrls, [{"i": 0, "displayName": "入口阀"}],
    )
    assert result == {0: "入口阀"}


def test_make_label_map_empty_display_name_raises():
    ctrls = _controls_dict()
    with pytest.raises(RefineInputError, match="no displayName"):
        _make_label_map(
            {"type": "add_label", "target_ids": [0]},
            ctrls, [{"i": 0, "displayName": ""}],
        )


def test_make_label_map_names_missing_key():
    ctrls = _controls_dict()
    with pytest.raises(RefineInputError, match="missing entry"):
        _make_label_map(
            {"type": "add_label", "target_ids": [0], "names": {}},
            ctrls, [],
        )


def test_make_label_map_text_and_names_mutual():
    with pytest.raises(RefineModelError, match="cannot have both"):
        from model.refine_agent import _validate_action
        _validate_action(
            {"type": "add_label", "target_ids": [0], "text": "X", "names": {0: "Y"}},
            {0},
        )


def test_make_label_map_rejects_mixed_image_multi_select():
    ctrls = {
        0: _make_control(image="valve.svg"),
        1: _make_control(x=200, y=300, image="pump.svg"),
    }
    with pytest.raises(RefineInputError, match="same image"):
        _make_label_map(
            {"type": "add_label", "target_ids": [0, 1], "text": "设备"},
            ctrls, [],
        )


# ---------------------------------------------------------------------------
# _build_label_json
# ---------------------------------------------------------------------------


def test_build_label_json():
    label = _LabelInfo(
        node_i=42, index=-1, label_for=0,
        x=100, y=150, width=96, height=32,
        text="Test", touched=True,
    )
    obj = _build_label_json(label)
    assert obj["c"] == "ht.Text"
    assert obj["i"] == 42
    assert obj["p"]["position"] == {"x": 100, "y": 150}
    assert obj["p"]["width"] == 96
    assert obj["p"]["height"] == 32
    assert obj["p"]["tall"] == 20
    assert obj["s"]["text"] == "Test"
    assert obj["s"]["text.font"] == "bold 20px Arial"
    assert obj["s"]["text.color"] == "white"
    assert obj["a"]["layout.role"] == "control-label"
    assert obj["a"]["layout.labelFor"] == 0


# ---------------------------------------------------------------------------
# _apply_actions add_label
# ---------------------------------------------------------------------------


def test_apply_add_label_creates_new_label():
    ctrl = _make_control(i=0, x=100, y=200)
    controls = {0: ctrl}
    labels: dict = {}
    new_labels: list = []

    max_i = _apply_actions(
        [{"type": "add_label", "target_ids": [0], "text": "入口"}],
        controls, labels, new_labels, 5, 1000, 800,
        [{"i": 0, "displayName": "V1"}],
    )

    assert max_i == 7
    assert 0 in labels
    assert len(new_labels) == 1
    assert labels[0].text == "入口"
    assert labels[0].node_i == 6


def test_apply_add_label_updates_existing():
    ctrl = _make_control(i=0, x=100, y=200)
    existing = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=50, y=50, width=60, height=32,
        text="Old", touched=False,
    )
    controls = {0: ctrl}
    labels = {0: existing}
    new_labels: list = []

    _apply_actions(
        [{"type": "add_label", "target_ids": [0], "text": "NewName"}],
        controls, labels, new_labels, 5, 1000, 800,
        [{"i": 0, "displayName": "V1"}],
    )

    assert existing.text == "NewName"
    assert existing.touched
    assert len(new_labels) == 0


def test_apply_add_label_multi_text_numbered():
    ctrl0 = _make_control(i=0, x=100, y=200, image="valve.svg")
    ctrl1 = _make_control(i=1, x=300, y=200, image="valve.svg")
    controls = {0: ctrl0, 1: ctrl1}
    labels: dict = {}
    new_labels: list = []

    _apply_actions(
        [{"type": "add_label", "target_ids": [0, 1], "text": "V"}],
        controls, labels, new_labels, 5, 1000, 800,
        [{"i": 0, "displayName": "V1"}, {"i": 1, "displayName": "V2"}],
    )

    assert labels[0].text == "V1"
    assert labels[1].text == "V2"
    assert len(new_labels) == 2
    assert labels[0].node_i == 6
    assert labels[1].node_i == 7


def test_apply_add_label_multi_mixed_image_rejected():
    ctrl0 = _make_control(i=0, x=100, y=200, image="valve.svg")
    ctrl1 = _make_control(i=1, x=300, y=200, image="pump.svg")
    controls = {0: ctrl0, 1: ctrl1}
    labels: dict = {}
    new_labels: list = []

    with pytest.raises(RefineInputError, match="same image"):
        _apply_actions(
            [{"type": "add_label", "target_ids": [0, 1], "text": "V"}],
            controls, labels, new_labels, 5, 1000, 800,
            [],
        )
    assert len(new_labels) == 0


def test_apply_move_updates_label_position():
    ctrl = _make_control(i=0, x=100, y=200)
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=100, y=160, width=96, height=32,
        text="V1", touched=False,
    )
    controls = {0: ctrl}
    labels = {0: label}
    new_labels: list = []

    _apply_actions(
        [{"type": "move", "target_ids": [0], "dx": 50, "dy": 0}],
        controls, labels, new_labels, 5, 1000, 800,
        [],
    )

    assert ctrl.x == 150
    assert label.touched
    assert label.x == 150


def test_apply_delete_removes_label():
    ctrl = _make_control(i=0, x=100, y=200)
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=100, y=160, width=96, height=32,
        text="V1", touched=False,
    )
    controls = {0: ctrl}
    labels = {0: label}
    new_labels: list = []

    _apply_actions(
        [{"type": "delete", "target_ids": [0]}],
        controls, labels, new_labels, 5, 1000, 800,
        [],
    )

    assert ctrl.deleted
    assert label.deleted


# ---------------------------------------------------------------------------
# _compile_patch with labels
# ---------------------------------------------------------------------------


def test_compile_patch_label_update():
    ctrl = _make_control(i=0, x=100, y=200)
    ctrl.touched = True
    ctrl.x = 150
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=120, y=150, width=100, height=32,
        text="Updated", touched=True,
    )
    controls = {0: ctrl}
    new_labels: list = []

    patch = _compile_patch(controls, {0: label}, new_labels)
    paths = [op["path"] for op in patch]
    assert "/d/3/s/text" in paths
    assert "/d/3/p/position/x" in paths
    assert "/d/3/p/position/y" in paths
    assert "/d/3/p/width" in paths
    assert "/d/3/p/height" in paths


def test_compile_patch_label_append():
    ctrl = _make_control(i=0, x=100, y=200)
    controls = {0: ctrl}
    new_label = _LabelInfo(
        node_i=11, index=-1, label_for=0,
        x=100, y=150, width=96, height=32,
        text="New", touched=True,
    )
    patch = _compile_patch(controls, {}, [new_label])
    assert any(op["op"] == "add" and op["path"] == "/d/-" for op in patch)


def test_compile_patch_label_delete():
    ctrl = _make_control(i=0, x=100, y=200)
    ctrl.deleted = True
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=100, y=160, width=96, height=32,
        text="V1", deleted=True,
    )
    patch = _compile_patch({0: ctrl}, {0: label}, [])
    removes = [op for op in patch if op["op"] == "remove"]
    assert any(op["path"] == "/d/3" for op in removes)
    assert any(op["path"] == "/d/0" for op in removes)


def test_compile_patch_label_append_only():
    new_label = _LabelInfo(
        node_i=42, index=-1, label_for=0,
        x=100, y=150, width=96, height=32,
        text="New", touched=True,
    )
    patch = _compile_patch({}, {}, [new_label])
    adds = [op for op in patch if op["op"] == "add"]
    assert len(adds) == 1
    assert adds[0]["path"] == "/d/-"
    assert adds[0]["value"]["i"] == 42
    assert adds[0]["value"]["c"] == "ht.Text"


# ---------------------------------------------------------------------------
# _validate_patch with labels
# ---------------------------------------------------------------------------


def test_validate_patch_label_update_accepts():
    ctrl = _make_control(i=0, x=100, y=200)
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=100, y=160, width=96, height=32,
        text="V1",
    )
    patch = [
        {"op": "replace", "path": "/d/3/s/text", "value": "Updated"},
        {"op": "replace", "path": "/d/3/p/position/x", "value": 120},
        {"op": "remove", "path": "/d/3"},
    ]
    _validate_patch(patch, {0: ctrl}, {0: label})


def test_validate_patch_d_append_accepts():
    ctrl = _make_control(i=0, x=100, y=200)
    patch = [
        {"op": "add", "path": "/d/-", "value": {"c": "ht.Text", "i": 42, "p": {}, "s": {}, "a": {}}},
    ]
    _validate_patch(patch, {0: ctrl}, {})


def test_validate_patch_rejects_invalid_label_path():
    ctrl = _make_control(i=0, x=100, y=200)
    label = _LabelInfo(
        node_i=10, index=3, label_for=0,
        x=100, y=160, width=96, height=32,
        text="V1",
    )
    patch = [
        {"op": "replace", "path": "/d/3/invalid", "value": 1},
    ]
    with pytest.raises(RefineModelError, match="invalid"):
        _validate_patch(patch, {0: ctrl}, {0: label})
