import pytest
from fastapi import HTTPException

from app.routers.canvas import canvas_layout
from app.schemas import CanvasLayoutRequest
from model.compute_position import convert_layout_file
from model.generate_gird import (
    IntentModelOutputError,
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
管道：管道垂直或水平引出，并采用正交连接。相同设备和重复支路应保持等间距、上下对齐及结构一致。"""

GAS_PROMPT = """控件：1台空气罐、2台氮气罐、3个阀门、4台流量计以及3组压力传感器。
流程：空气罐上方阀门-流量计-压力传感器-流量计，氮气罐上方阀门-流量计-压力传感器；空气供气支路与氮气供气支路相互独立，2套氮气供气支路采用上下并联、独立输出的结构。
结构：多套独立系统与重复支路相结合的结构。空气罐及其出口管路布置在页面左侧，2台氮气罐布置在页面右侧，阀门、流量计和压力监测设备分别安装在各储气罐的出口管线上。2套氮气供气支路采用上下纵向排列和相同模板布局，氮气罐、阀门、流量计及压力传感器保持上下对齐；空气罐尺寸较大，作为主要气源设备单独布置在左侧，其流量监测设备沿出口管路横向排列。
管道：各储气罐出口管路采用水平正交连接，阀门靠近储气罐出口布置，流量计和压力传感器按照气体流动方向依次设置；空气和氮气管路应保持相互独立，避免交叉连接。"""

REPORTED_GAS_PROMPT = """控件：1台空气罐、2台氮气罐、3个阀门、4台流量计以及3个压力传感器
流程：空气罐上方阀门-流量计-压力传感器-流量计，氮气罐上方阀门-流量计-压力传感器
结构：2台氮气罐布置在页面右侧，阀门、流量计和压力监测设备分别安装在各储气罐的出口管线上，氮气供气支路采用上下纵向排列和相同模板布局，空气罐尺寸较大，作为主要气源设备单独布置在左侧，其流量监测设备沿出口管路横向排列
管道：各储气罐出口管路采用水平正交连接，阀门靠近储气罐出口布置，流量计和压力传感器按照气体流动方向依次设置；空气和氮气管路应保持相互独立，避免交叉连接"""


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
管道：采用正交连接。"""

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


def test_layout_validation_requires_parallel_topology():
    data = _layout_data()
    data["layoutIntent"]["groups"][0]["topology"] = "single"
    layout = LayoutFile.model_validate(data)

    errors, _ = validate_layout_file(layout, parse_structured_prompt(VALID_PROMPT))

    assert [(item.path, item.message) for item in errors] == [
        ("layoutIntent.groups[0].topology", "冷却塔必须声明为 parallel"),
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
    assert "空气罐上方阀门-流量计-压力传感器-流量计" in request["flow"]
    assert layout.layoutIntent.groups[1].count == 2


@pytest.mark.asyncio
async def test_generate_intent_raises_on_invalid_output_no_pro_fallback():
    models = []

    async def fake_call(client, model, request_messages, **kwargs):
        models.append(model)
        data = _gas_layout_data(flowmeter_count=2)
        output = __import__("json").dumps(data)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": output})()})()]},
        )()

    with pytest.raises(IntentModelOutputError, match="数量 6 与控件声明 4 不一致"):
        await generate_intent(
            GAS_PROMPT,
            [{"displayName": item} for item in ("空气罐", "氮气罐", "阀门", "流量计", "压力传感器")],
            client=object(),
            model="deepseek-v4-flash",
            model_caller=fake_call,
        )

    assert models == ["deepseek-v4-flash"]


@pytest.mark.asyncio
async def test_generate_intent_rejects_invalid_source_before_calling_llm():
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called")

    with pytest.raises(StructuredPromptError):
        await generate_intent(
            "控件：4台冷却泵。\n流程：冷却泵。\n结构：3台冷却泵纵向排列。\n管道：正交连接。",
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


HYDRAULIC_PROMPT = """控件：1台油箱、2台电机、4台液压泵、4个溢流阀、2个吸油过滤器、1个回油单向阀
流程：溢流阀-液压泵-电机-吸油过滤器-回油单向阀-油箱
结构：4个溢流阀纵向排列，每个溢流阀右侧连接对应各自的液压泵；4个液压泵纵向排列，液压泵1和液压泵2连接1号电机，液压泵3和液压泵4连接2号电机。两个电机纵向排列位于画面中央；液压泵1和液压泵2分别从上和下连接吸油过滤器1(在1号电机右侧)，液压泵3和液压泵4连接分别从上和下连接吸油过滤器2(在2号电机右侧)，俩个吸油过滤器同样纵向排布在电机的右侧；吸油过滤器1连接回油单向阀后连接油箱，吸油过滤器2直接连接油箱；油箱在画面的右下角
管道：液压管路采用水平、垂直正交连接"""

HYDRAULIC_VOCAB = [
    {"displayName": "油箱"},
    {"displayName": "电机"},
    {"displayName": "液压泵"},
    {"displayName": "溢流阀"},
    {"displayName": "吸油过滤器"},
    {"displayName": "回油单向阀"},
]

HYDRAULIC_INVENTORY = [
    ("油箱", 1),
    ("电机", 2),
    ("液压泵", 4),
    ("溢流阀", 4),
    ("吸油过滤器", 2),
    ("回油单向阀", 1),
]


def test_hydraulic_parse_structured_prompt():
    source = parse_structured_prompt(HYDRAULIC_PROMPT)

    assert [(item.deviceType, item.count) for item in source.inventory] == HYDRAULIC_INVENTORY
    assert source.flowPaths == [
        ["溢流阀", "液压泵", "电机", "吸油过滤器", "回油单向阀", "油箱"]
    ]


def _assert_hydraulic_groups_have_correct_counts(layout: LayoutFile):
    totals = {}
    for group in layout.layoutIntent.groups:
        totals[group.unit.root.deviceType] = totals.get(group.unit.root.deviceType, 0) + group.count
        for attachment in group.unit.attachments:
            totals[attachment.deviceType] = (
                totals.get(attachment.deviceType, 0)
                + group.count * (attachment.count or 1)
            )
    for device_type, expected in HYDRAULIC_INVENTORY:
        assert totals.get(device_type) == expected, (
            f"{device_type}数量 {totals.get(device_type)} 与控件声明 {expected} 不一致"
        )


def test_hydraulic_rules_path_generates_correct_groups():
    source = parse_structured_prompt(HYDRAULIC_PROMPT)
    from model.layout_intent_rules import build_rule_layout
    result = build_rule_layout(source)

    assert result.data is not None
    layout = LayoutFile.model_validate(result.data)

    device_types = [group.unit.root.deviceType for group in layout.layoutIntent.groups]
    assert device_types == ["溢流阀", "液压泵", "电机", "吸油过滤器", "回油单向阀", "油箱"]

    assert len(layout.layoutIntent.groups) == 6
    for group in layout.layoutIntent.groups:
        assert group.unit.attachments == []

    _assert_hydraulic_groups_have_correct_counts(layout)

    for i in range(1, len(layout.layoutIntent.groups)):
        assert layout.layoutIntent.groups[i].relativeTo == layout.layoutIntent.groups[i - 1].id
        assert layout.layoutIntent.groups[i].side == "right"


def test_hydraulic_validate_layout_file():
    source = parse_structured_prompt(HYDRAULIC_PROMPT)
    from model.layout_intent_rules import build_rule_layout
    result = build_rule_layout(source)

    layout = LayoutFile.model_validate(result.data)
    errors, _ = validate_layout_file(layout, source)

    assert errors == []


@pytest.mark.asyncio
async def test_hydraulic_generate_intent_uses_rules_not_llm():
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called for hydraulic prompt")

    layout = await generate_intent(
        HYDRAULIC_PROMPT,
        HYDRAULIC_VOCAB,
        client=object(),
        model="deepseek-v4-flash",
        model_caller=fail_if_called,
    )

    device_types = [group.unit.root.deviceType for group in layout.layoutIntent.groups]
    assert device_types == ["溢流阀", "液压泵", "电机", "吸油过滤器", "回油单向阀", "油箱"]
    _assert_hydraulic_groups_have_correct_counts(layout)


def test_hydraulic_convert_layout_file():
    source = parse_structured_prompt(HYDRAULIC_PROMPT)
    from model.layout_intent_rules import build_rule_layout
    result = build_rule_layout(source)

    controls = [{"displayName": name, "image": f"{name}.json", "width": 80, "height": 80} for name, _ in HYDRAULIC_INVENTORY]

    nodes = convert_layout_file(result.data, controls)

    assert len(nodes) == sum(count for _, count in HYDRAULIC_INVENTORY)
    assert all(node["c"] == "ht.Node" for node in nodes)


RULE_PROMPT = """控件：3台冷却塔、3台冷却泵、3台冷水机、4台冷冻泵。
流程：冷却塔-冷却泵-冷水机-冷冻泵；冷却塔和冷水机采用并联结构。
结构：冷却塔布置在页面左侧，3台设备纵向排列；冷却泵布置在冷却塔右侧，3台设备纵向排列；冷水机布置在冷却泵右侧，3台设备纵向排列；冷冻泵布置在冷水机右侧，4台设备纵向排列。
管道：管道垂直或水平引出，并采用正交连接。"""

RULE_VOCAB = [{"displayName": name} for name in ("冷却塔", "冷却泵", "冷水机", "冷冻泵")]


def test_rule_layout_generates_correct_groups():
    from model.layout_intent_rules import build_rule_layout
    source = parse_structured_prompt(RULE_PROMPT)
    result = build_rule_layout(source)

    assert result.data is not None
    layout = LayoutFile.model_validate(result.data)
    groups = layout.layoutIntent.groups

    assert len(groups) == 4
    device_types = [g.unit.root.deviceType for g in groups]
    assert device_types == ["冷却塔", "冷却泵", "冷水机", "冷冻泵"]

    assert groups[0].region == "left"
    assert groups[0].count == 3
    assert groups[0].arrangement == "vertical"

    assert groups[1].region == "right"
    assert groups[1].count == 3
    assert groups[1].arrangement == "vertical"
    assert groups[1].relativeTo == "group-1"
    assert groups[1].side == "right"

    assert groups[2].region == "right"
    assert groups[2].count == 3
    assert groups[2].arrangement == "vertical"
    assert groups[2].relativeTo == "group-2"
    assert groups[2].side == "right"

    assert groups[3].region == "right"
    assert groups[3].count == 4
    assert groups[3].arrangement == "vertical"
    assert groups[3].relativeTo == "group-3"
    assert groups[3].side == "right"


def test_rule_layout_validate():
    from model.layout_intent_rules import build_rule_layout
    source = parse_structured_prompt(RULE_PROMPT)
    result = build_rule_layout(source)

    layout = LayoutFile.model_validate(result.data)
    errors, _ = validate_layout_file(layout, source)
    assert errors == []


@pytest.mark.asyncio
async def test_rule_generate_intent_uses_rules_not_llm():
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called for rule prompt")

    layout = await generate_intent(
        RULE_PROMPT,
        RULE_VOCAB,
        client=object(),
        model="deepseek-v4-flash",
        model_caller=fail_if_called,
    )
    groups = layout.layoutIntent.groups
    assert len(groups) == 4
    assert [g.unit.root.deviceType for g in groups] == ["冷却塔", "冷却泵", "冷水机", "冷冻泵"]


@pytest.mark.asyncio
async def test_canvas_layout_returns_intent_unavailable_as_503():
    class Agent503:
        async def generate(self, **kwargs):
            from model.generate_gird import IntentModelUnavailableError
            raise IntentModelUnavailableError("布局模型不可用")

    request = CanvasLayoutRequest(query="测试", title="测试")

    with pytest.raises(HTTPException) as exc_info:
        await canvas_layout(request, agent=Agent503())

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_canvas_layout_returns_intent_timeout_as_504():
    class Agent504:
        async def generate(self, **kwargs):
            from model.generate_gird import IntentModelTimeoutError
            raise IntentModelTimeoutError("布局模型请求超时")

    request = CanvasLayoutRequest(query="测试", title="测试")

    with pytest.raises(HTTPException) as exc_info:
        await canvas_layout(request, agent=Agent504())

    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_canvas_layout_returns_piping_unavailable_as_503():
    class Agent503:
        async def generate(self, **kwargs):
            from model.get_connection import ConnectionModelUnavailableError
            raise ConnectionModelUnavailableError("连接模型不可用")

    request = CanvasLayoutRequest(query="测试", title="测试")

    with pytest.raises(HTTPException) as exc_info:
        await canvas_layout(request, agent=Agent503())

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_canvas_layout_returns_piping_timeout_as_504():
    class Agent504:
        async def generate(self, **kwargs):
            from model.get_connection import ConnectionModelTimeoutError
            raise ConnectionModelTimeoutError("连接模型请求超时")

    request = CanvasLayoutRequest(query="测试", title="测试")

    with pytest.raises(HTTPException) as exc_info:
        await canvas_layout(request, agent=Agent504())

    assert exc_info.value.status_code == 504
