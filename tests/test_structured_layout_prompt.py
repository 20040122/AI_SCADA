import pytest
from fastapi import HTTPException

from app.routers.canvas import canvas_layout
from app.schemas import CanvasLayoutRequest
from model.generate_gird import (
    LayoutFile,
    StructuredPromptError,
    ValidationErrorItem,
    generate_intent,
    parse_structured_prompt,
    validate_layout_file,
)


VALID_PROMPT = """控件：3台冷却塔、4台冷却泵、3台冷水机组、4台冷冻泵。
流程：冷却塔-冷却泵-冷水机组-冷冻泵；冷却塔、冷水机组和冷冻泵采用并联结构。
结构：冷却塔布置在页面左侧，3台设备纵向排列；冷却泵布置在冷却塔右侧，4台设备纵向排列；3台冷水机组布置在页面中部并纵向排列；4台冷冻泵布置在页面右侧并纵向排列。
要求：管道垂直或水平引出，并采用正交连接。相同设备和重复支路应保持等间距、上下对齐及结构一致。"""

GAS_PROMPT = """控件：1台空气罐、2台氮气罐、3个阀门、4台流量计以及3组压力传感器。
流程：空气罐上方阀门-流量计-压力传感器-流量计，氮气罐上方阀门-流量计-压力传感器；空气供气支路与氮气供气支路相互独立，2套氮气供气支路采用上下并联、独立输出的结构。
结构：多套独立系统与重复支路相结合的结构。空气罐及其出口管路布置在页面左侧，2台氮气罐布置在页面右侧，阀门、流量计和压力监测设备分别安装在各储气罐的出口管线上。2套氮气供气支路采用上下纵向排列和相同模板布局，氮气罐、阀门、流量计及压力传感器保持上下对齐；空气罐尺寸较大，作为主要气源设备单独布置在左侧，其流量监测设备沿出口管路横向排列。
要求：各储气罐出口管路采用水平正交连接，阀门靠近储气罐出口布置，流量计和压力传感器按照气体流动方向依次设置；空气和氮气管路应保持相互独立，避免交叉连接。"""

REPORTED_GAS_PROMPT = """控件：1台空气罐、2台氮气罐、3个阀门、4台流量计以及3个压力传感器
流程：空气罐上方阀门-流量计-压力传感器-流量计，氮气罐上方阀门-流量计-压力传感器
结构：2台氮气罐布置在页面右侧，阀门、流量计和压力监测设备分别安装在各储气罐的出口管线上，氮气供气支路采用上下纵向排列和相同模板布局，空气罐尺寸较大，作为主要气源设备单独布置在左侧，其流量监测设备沿出口管路横向排列
要求：各储气罐出口管路采用水平正交连接，阀门靠近储气罐出口布置，流量计和压力传感器按照气体流动方向依次设置；空气和氮气管路应保持相互独立，避免交叉连接"""


def _layout_data(cooling_pump_count=4):
    return {
        "layoutIntent": {
            "groups": [
                {
                    "id": "cooling-tower",
                    "region": "left",
                    "count": 3,
                    "arrangement": "vertical",
                    "topology": "parallel",
                    "unit": {"root": {"id": "root", "deviceType": "冷却塔"}},
                },
                {
                    "id": "cooling-pump",
                    "region": "center",
                    "relativeTo": "cooling-tower",
                    "side": "right",
                    "count": cooling_pump_count,
                    "arrangement": "vertical",
                    "unit": {"root": {"id": "root", "deviceType": "冷却泵"}},
                },
                {
                    "id": "chiller",
                    "region": "center",
                    "count": 3,
                    "arrangement": "vertical",
                    "topology": "parallel",
                    "unit": {"root": {"id": "root", "deviceType": "冷水机组"}},
                },
                {
                    "id": "chilled-pump",
                    "region": "right",
                    "count": 4,
                    "arrangement": "vertical",
                    "topology": "parallel",
                    "unit": {"root": {"id": "root", "deviceType": "冷冻泵"}},
                },
            ],
            "connections": [
                {
                    "id": "flow-1",
                    "source": {"group": "cooling-tower", "node": "root"},
                    "target": {"group": "cooling-pump", "node": "root"},
                },
                {
                    "id": "flow-2",
                    "source": {"group": "cooling-pump", "node": "root"},
                    "target": {"group": "chiller", "node": "root"},
                },
                {
                    "id": "flow-3",
                    "source": {"group": "chiller", "node": "root"},
                    "target": {"group": "chilled-pump", "node": "root"},
                },
            ],
            "constraints": {
                "routeStyle": "orthogonal",
                "allowedDirections": ["horizontal", "vertical"],
                "equalSpacing": True,
                "alignRepeated": True,
                "consistentBranches": True,
            },
        }
    }


def _gas_layout_data(flowmeter_count=1):
    return {
        "layoutIntent": {
            "groups": [
                {
                    "id": "air",
                    "region": "left",
                    "count": 1,
                    "unit": {
                        "root": {"id": "tank", "deviceType": "空气罐"},
                        "attachments": [
                            {"id": "valve", "deviceType": "阀门", "relativeTo": "tank", "side": "top"},
                            {"id": "meter-in", "deviceType": "流量计", "relativeTo": "valve", "side": "right"},
                            {"id": "sensor", "deviceType": "压力传感器", "relativeTo": "meter-in", "side": "right"},
                            {"id": "meter-out", "deviceType": "流量计", "relativeTo": "sensor", "side": "right"},
                        ],
                    },
                },
                {
                    "id": "nitrogen",
                    "region": "right",
                    "count": 2,
                    "arrangement": "vertical",
                    "topology": "parallel",
                    "unit": {
                        "root": {"id": "tank", "deviceType": "氮气罐"},
                        "attachments": [
                            {"id": "valve", "deviceType": "阀门", "relativeTo": "tank", "side": "top"},
                            {"id": "meter", "deviceType": "流量计", "relativeTo": "valve", "side": "right", "count": flowmeter_count},
                            {"id": "sensor", "deviceType": "压力传感器", "relativeTo": "meter", "side": "right"},
                        ],
                    },
                },
            ],
            "connections": [
                {"id": "air-1", "source": {"group": "air", "node": "tank"}, "target": {"group": "air", "node": "valve"}},
                {"id": "air-2", "source": {"group": "air", "node": "valve"}, "target": {"group": "air", "node": "meter-in"}},
                {"id": "air-3", "source": {"group": "air", "node": "meter-in"}, "target": {"group": "air", "node": "sensor"}},
                {"id": "air-4", "source": {"group": "air", "node": "sensor"}, "target": {"group": "air", "node": "meter-out"}},
                {"id": "nitrogen-1", "source": {"group": "nitrogen", "node": "tank"}, "target": {"group": "nitrogen", "node": "valve"}},
                {"id": "nitrogen-2", "source": {"group": "nitrogen", "node": "valve"}, "target": {"group": "nitrogen", "node": "meter"}},
                {"id": "nitrogen-3", "source": {"group": "nitrogen", "node": "meter"}, "target": {"group": "nitrogen", "node": "sensor"}},
            ],
        }
    }


def test_parse_structured_prompt_uses_controls_as_inventory_truth():
    source = parse_structured_prompt(VALID_PROMPT)

    assert [(item.deviceType, item.count) for item in source.inventory] == [
        ("冷却塔", 3),
        ("冷却泵", 4),
        ("冷水机组", 3),
        ("冷冻泵", 4),
    ]
    assert source.flow.startswith("冷却塔-冷却泵")


def test_parse_structured_prompt_accepts_mixed_inventory_and_independent_flow_paths():
    source = parse_structured_prompt(GAS_PROMPT)

    assert [(item.deviceType, item.count) for item in source.inventory] == [
        ("空气罐", 1),
        ("氮气罐", 2),
        ("阀门", 3),
        ("流量计", 4),
        ("压力传感器", 3),
    ]
    assert source.flowPaths == [
        ["空气罐", "阀门", "流量计", "压力传感器", "流量计"],
        ["氮气罐", "阀门", "流量计", "压力传感器"],
    ]


def test_layout_validation_accepts_repeated_branch_template_inventory_and_flow():
    layout = LayoutFile.model_validate(_gas_layout_data())

    errors, _ = validate_layout_file(layout, parse_structured_prompt(GAS_PROMPT))

    assert errors == []


def test_layout_validation_requires_each_flow_path_to_be_continuous():
    data = _gas_layout_data()
    data["layoutIntent"]["connections"].pop(5)
    layout = LayoutFile.model_validate(data)

    errors, _ = validate_layout_file(layout, parse_structured_prompt(GAS_PROMPT))

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.connections", "缺少流程连接：阀门-流量计")
    ]


def test_layout_validation_rejects_wrong_repeated_branch_attachment_total():
    layout = LayoutFile.model_validate(_gas_layout_data(flowmeter_count=2))

    errors, _ = validate_layout_file(layout, parse_structured_prompt(GAS_PROMPT))

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.groups", "流量计数量 6 与控件声明 4 不一致")
    ]


def test_parse_structured_prompt_rejects_structure_count_conflict():
    prompt = """控件：3台冷却塔、4台冷却泵。
流程：冷却塔-冷却泵。
结构：冷却塔布置在页面左侧，3台设备纵向排列；冷却泵布置在冷却塔右侧，3台设备纵向排列。
要求：采用正交连接。"""

    with pytest.raises(StructuredPromptError) as exc_info:
        parse_structured_prompt(prompt)

    assert [(item.path, item.message) for item in exc_info.value.errors] == [
        ("结构.冷却泵.count", "结构声明 3 台，与控件声明 4 台冲突")
    ]


def test_parse_structured_prompt_requires_all_sections():
    with pytest.raises(StructuredPromptError) as exc_info:
        parse_structured_prompt("控件：3台冷却塔。\n流程：冷却塔。")

    assert [(item.path, item.message) for item in exc_info.value.errors] == [
        ("结构", "缺少段落"),
        ("要求", "缺少段落"),
    ]


def test_extended_ir_keeps_topology_placement_and_constraints():
    layout = LayoutFile.model_validate(_layout_data())

    assert layout.layoutIntent.groups[0].topology == "parallel"
    assert layout.layoutIntent.groups[1].relativeTo == "cooling-tower"
    assert layout.layoutIntent.groups[1].side == "right"
    assert layout.layoutIntent.constraints.routeStyle == "orthogonal"
    assert layout.layoutIntent.constraints.allowedDirections == ["horizontal", "vertical"]


def test_layout_validation_rejects_llm_inventory_count_change():
    layout = LayoutFile.model_validate(_layout_data(cooling_pump_count=3))

    errors, _ = validate_layout_file(layout, parse_structured_prompt(VALID_PROMPT))

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.groups[1].count", "冷却泵数量 3 与控件声明 4 不一致")
    ]


def test_layout_validation_requires_source_flow_and_parallel_topology():
    data = _layout_data()
    data["layoutIntent"]["groups"][0]["topology"] = "single"
    data["layoutIntent"]["connections"].pop()
    layout = LayoutFile.model_validate(data)

    errors, _ = validate_layout_file(layout, parse_structured_prompt(VALID_PROMPT))

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.groups[0].topology", "冷却塔必须声明为 parallel"),
        ("layoutIntent.connections", "缺少流程连接：冷水机组-冷冻泵"),
    ]


def test_layout_validation_rejects_group_placement_cycle():
    data = _layout_data()
    data["layoutIntent"]["groups"][0].update({"relativeTo": "chilled-pump", "side": "right"})
    data["layoutIntent"]["groups"][3].update({"relativeTo": "cooling-tower", "side": "right"})
    layout = LayoutFile.model_validate(data)

    errors, _ = validate_layout_file(layout)

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.groups", "组级相对位置存在循环引用")
    ]


@pytest.mark.asyncio
async def test_generate_intent_sends_normalized_structured_input(monkeypatch):
    messages = []
    models = []
    call_options = {}

    async def fake_call(client, model, request_messages, **kwargs):
        models.append(model)
        messages.extend(request_messages)
        call_options.update(kwargs)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": __import__("json").dumps(_layout_data())})()})()]},
        )()

    layout = await generate_intent(
        VALID_PROMPT.replace("页面中部", "页面任意位置"),
        [{"displayName": item} for item in ("冷却塔", "冷却泵", "冷水机组", "冷冻泵")],
        client=object(),
        model="deepseek-v4-flash",
        model_caller=fake_call,
    )

    assert models == ["deepseek-v4-flash"]
    assert call_options == {
        "response_format": {"type": "json_object"},
        "stream": False,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    request = __import__("json").loads(messages[1]["content"])
    assert request["inventory"] == [
        {"deviceType": "冷却塔", "count": 3},
        {"deviceType": "冷却泵", "count": 4},
        {"deviceType": "冷水机组", "count": 3},
        {"deviceType": "冷冻泵", "count": 4},
    ]
    assert layout.layoutIntent.groups[2].topology == "parallel"


@pytest.mark.asyncio
async def test_generate_intent_sends_gas_flow_paths_and_accepts_branch_templates():
    messages = []

    async def fake_call(client, model, request_messages, **kwargs):
        messages.extend(request_messages)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": __import__("json").dumps(_gas_layout_data())})()})()]},
        )()

    layout = await generate_intent(
        GAS_PROMPT,
        [{"displayName": item} for item in ("空气罐", "氮气罐", "阀门", "流量计", "压力传感器")],
        client=object(),
        model="test-model",
        model_caller=fake_call,
    )

    request = __import__("json").loads(messages[1]["content"])
    assert request["flowPaths"] == [
        ["空气罐", "阀门", "流量计", "压力传感器", "流量计"],
        ["氮气罐", "阀门", "流量计", "压力传感器"],
    ]
    assert layout.layoutIntent.groups[1].count == 2


@pytest.mark.asyncio
async def test_generate_intent_completes_reported_missing_attachment_connection():
    models = []

    async def fake_call(client, model, request_messages, **kwargs):
        models.append(model)
        data = _gas_layout_data()
        data["layoutIntent"]["connections"].pop(4)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": __import__("json").dumps(data)})()})()]},
        )()

    layout = await generate_intent(
        REPORTED_GAS_PROMPT,
        [{"displayName": item} for item in ("空气罐", "氮气罐", "阀门", "流量计", "压力传感器")],
        client=object(),
        model="deepseek-v4-flash",
        model_caller=fake_call,
    )

    assert models == ["deepseek-v4-flash"]
    assert any(
        connection.source.group == "nitrogen"
        and connection.source.node == "tank"
        and connection.target.group == "nitrogen"
        and connection.target.node == "valve"
        for connection in layout.layoutIntent.connections
    )


@pytest.mark.asyncio
async def test_generate_intent_retries_semantic_output_with_pro_model():
    models = []
    requests = []
    outputs = {}

    async def fake_call(client, model, request_messages, **kwargs):
        models.append(model)
        requests.append([dict(message) for message in request_messages])
        data = _gas_layout_data(flowmeter_count=2)
        if model == "deepseek-v4-pro":
            data = _gas_layout_data()
        output = __import__("json").dumps(data)
        outputs[model] = output
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": output})()})()]},
        )()

    layout = await generate_intent(
        GAS_PROMPT,
        [{"displayName": item} for item in ("空气罐", "氮气罐", "阀门", "流量计", "压力传感器")],
        client=object(),
        model="deepseek-v4-flash",
        model_caller=fake_call,
    )

    assert models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert [message["role"] for message in requests[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert requests[1][2]["content"] == outputs["deepseek-v4-flash"]
    assert layout.layoutIntent.groups[1].unit.root.deviceType == "氮气罐"


@pytest.mark.asyncio
async def test_generate_intent_rejects_invalid_source_before_calling_llm():
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called")

    with pytest.raises(StructuredPromptError):
        await generate_intent(
            "控件：4台冷却泵。\n流程：冷却泵。\n结构：3台冷却泵纵向排列。\n要求：正交连接。",
            [{"displayName": "冷却泵"}],
            client=object(),
            model="test-model",
            model_caller=fail_if_called,
        )


@pytest.mark.asyncio
async def test_canvas_layout_returns_structured_prompt_error_as_422():
    class Agent:
        async def generate(self, **kwargs):
            raise StructuredPromptError([
                ValidationErrorItem(path="结构.冷却泵.count", message="数量冲突")
            ])

    request = CanvasLayoutRequest(query="测试", title="测试")

    with pytest.raises(HTTPException) as exc_info:
        await canvas_layout(request, agent=Agent())

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "errors": [{"path": "结构.冷却泵.count", "message": "数量冲突"}]
    }
