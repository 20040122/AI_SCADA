# R-01 Schema规则库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the R-01 Schema规则库 page (4-category rule display + AI validator) into web/scada, with backend AI validation via DeepSeek.

**Architecture:** Backend (FastAPI) receives `POST /api/validate {category, json_data}`, runs deterministic checks (jsonschema Draft7 + existing `validate_layout_file`) then AI semantic validation via DeepSeek, returns `{valid, summary, errors, warnings}`. Frontend (React+Zustand) displays rules in 3-column layout and calls the backend endpoint.

**Tech Stack:** Python 3.9, FastAPI, pydantic, jsonschema, openai+tenacity (DeepSeek); React 19, TypeScript, Vite, Tailwind 4, Zustand 5.

## Global Constraints

- Python 3.9 compatibility (no 3.10+ syntax like `X | Y` union types)
- Backend DeepSeek client shared via `model.canva_agent._client, _MODEL, _call_llm`
- Layout validation reuses `model.generate_gird.validate_layout_file` and `LayoutFile` pydantic model
- Frontend follows existing Zustand store pattern (`create<Store>((set)=>({...}))`)
- Frontend API uses existing `post<T>` from `web/scada/src/api/client.ts`
- No extra CSS files — use Tailwind 4 utility classes
- No new npm dependencies for routing (tab state in Zustand)

---

### Task 1: Backend — Extend schemas and config

**Files:**
- Modify: `app/schemas.py:131-143`
- Modify: `app/config.py:12-13`

**Interfaces:**
- Consumes: existing `ValidateRequest`, `ValidateResponse`, `ValidationErrorItem` (schemas.py:131-143)
- Produces: updated `ValidateRequest` with `category` field, `ValidateResponse` with `summary`+`warnings`; config with `control_schema_path`+`binding_schema_path`

- [ ] **Step 1: Modify validate schemas in app/schemas.py**

Replace `ValidateRequest` (line 131-132) and `ValidateResponse` (line 141-143):

```python
class ValidateRequest(BaseModel):
    category: Literal["control", "canvas", "layout", "binding"]
    json_data: dict[str, Any]


class ValidationErrorItem(BaseModel):
    path: str = ""
    message: str
    error_type: str = ""


class ValidateResponse(BaseModel):
    valid: bool
    summary: str = ""
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
```

- [ ] **Step 2: Add schema paths to app/config.py**

Add after line 13 (`schema_path`):

```python
    control_schema_path: str = str(Path(__file__).resolve().parent.parent / "data" / "schema" / "control_schema.json")
    binding_schema_path: str = str(Path(__file__).resolve().parent.parent / "data" / "schema" / "binding_schema.json")
```

- [ ] **Step 3: Verify**

Run: `python -c "from app.schemas import ValidateRequest, ValidateResponse; r=ValidateRequest(category='canvas',json_data={}); print(r); v=ValidateResponse(valid=True,summary='ok'); print(v)"`

Expected: no import errors, both models print successfully.

---

### Task 2: Backend — Create ValidateAgent

**Files:**
- Create: `model/validate_agent.py`

**Interfaces:**
- Consumes: `model.canva_agent._client, _MODEL, _call_llm`; `model.generate_gird.LayoutFile, validate_layout_file`
- Produces: `ValidateAgent.__init__(client, model)`; `ValidateAgent.validate(category, json_data) -> dict`

- [ ] **Step 1: Create model/validate_agent.py**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from model.canva_agent import _client, _MODEL, _call_llm

logger = logging.getLogger(__name__)

_CATEGORY_PROMPTS = {
    "control": (
        "你是 SCADA 控件资源校验器。校验输入的 JSON 是否符合控件索引规则。\n\n"
        "结构要求：\n"
        "- displayName: string（必填，控件显示名称）\n"
        "- image: string（必填，资源路径，应在 symbols/ 或 assets/ 下）\n"
        "- width: number | null（必填，控件宽度）\n"
        "- height: number | null（必填，控件高度）\n"
        "- boundExtend: number（可选，边界扩展像素值）\n"
        "- 不允许额外属性\n\n"
        "派生规则：\n"
        "1. image 路径应以 symbols/ 或 assets/ 开头\n"
        "2. width 和 height 为 null 时应有合理理由（如占位符）\n"
        "3. boundExtend 若存在应 >= 0\n"
        "4. displayName 不应为空字符串\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "canvas": (
        "你是 SCADA 画布校验器。校验输入的 JSON 是否符合画布结构规则。\n\n"
        "结构要求：\n"
        "- v: string（必填，版本号）\n"
        "- p: object（必填，含 layers 数组、autoAdjustIndex bool、hierarchicalRendering bool）\n"
        "  - layers[].name: string, visible: bool, selectable: bool, movable: bool, editable: bool\n"
        "- a: object（必填，含 width、height、fitContent、rectSelectable、pannable、zoomable，均为 bool 或 number）\n"
        "- d: array（必填，数据元素数组）\n"
        "- contentRect: object（必填，含 x、y、width、height number）\n\n"
        "派生规则：\n"
        "1. contentRect 应能包含所有 d 元素的坐标范围\n"
        "2. d 数组元素应至少包含 c（类型）和 p（属性）字段\n"
        "3. layers 至少有一个图层\n"
        "4. a.width 和 a.height 应 > 0\n"
        "5. contentRect.width 和 height 应 > 0\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "layout": (
        "你是 SCADA 布局校验器。校验输入的 JSON 是否符合布局拓扑规则。\n\n"
        "结构要求：\n"
        "- layoutIntent: object（必填）\n"
        "  - groups: array（必填，至少一个 LayoutGroup）\n"
        "    - id: string, region: \"left\"|\"right\"|\"center\"\n"
        "    - unit: { root: DeviceNode, attachments: AttachmentNode[] }\n"
        "    - count: number >= 1\n"
        "    - arrangement?: \"vertical\"|\"horizontal\"|\"grid\"\n"
        "    - gapHint?: \"tight\"|\"normal\"|\"loose\"\n"
        "    - columns?: number, rows?: number, order?: \"row-major\"|\"col-major\"\n"
        "  - connections?: array（可选）\n"
        "    - id: string, source: {group, node, port?}, target: {group, node, port?}\n"
        "- DeviceNode: {id: string, deviceType: string, role?: \"root\"|\"valve\"|\"pipe\"|\"meter\"|\"sensor\"|\"default\"}\n"
        "- AttachmentNode extends DeviceNode 增加 relativeTo: string, side: \"top\"|\"right\"|\"bottom\"|\"left\", count?: number\n\n"
        "派生规则：\n"
        "1. groups 不能为空\n"
        "2. group.id 必须唯一\n"
        "3. group.count >= 1\n"
        "4. 当 arrangement=grid 时，columns 或 rows 至少一个 >= 1，且 columns*rows >= count\n"
        "5. attachment.relativeTo 必须引用本组已声明的节点\n"
        "6. 各场景的角色尺寸约束：root(120-180x120-260)、pipe(80-180x20-50)、valve(40-80x40-80)、meter(50-100x50-100)、sensor(50-110x40-90)\n"
        "7. connection.id 必须唯一，source/target.group 必须存在，source/target.node 必须在该 group 内\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
    "binding": (
        "你是 SCADA 数据绑点校验器。校验输入的 JSON 是否符合绑点规则。\n\n"
        "结构要求：\n"
        "- controlId: string（必填，控件 ID）\n"
        "- property: string（必填，枚举值：status|value|visible|color|text|enabled）\n"
        "- variable: string（必填，PLC 变量名）\n"
        "- dataType: string（可选，枚举值：bool|int16|int32|float|string）\n"
        "- registerAddress: string（可选，寄存器地址）\n"
        "- 不允许额外属性\n\n"
        "派生规则：\n"
        "1. controlId 不应为空\n"
        "2. variable 不应为空\n"
        "3. 若属性为 visible 或 enabled，建议 dataType 为 bool\n"
        "4. 若属性为 status 或 value，建议 dataType 为数值类型（int16/int32/float）\n"
        "5. registerAddress 若存在，格式应为标准的 PLC 寄存器地址（如 Q0.0、I0.1、DB1.DBX0.0）\n"
        "6. 如果有多个绑点，controlId 应唯一（每个控件只绑一次同一个属性）\n\n"
        "输出 JSON 格式：{\"valid\":bool,\"summary\":\"一句话总结\",\"errors\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}],\"warnings\":[{\"path\":\"\",\"message\":\"\",\"error_type\":\"\"}]}"
    ),
}


class ValidateAgent:
    def __init__(self, client=None, model=None):
        self._client = client if client is not None else _client
        self._model = model if model is not None else _MODEL

    async def validate(self, category: str, json_data: dict) -> dict:
        all_errors: list[dict] = []
        all_warnings: list[dict] = []

        try:
            ai_result = await self._ai_validate(category, json_data)
        except Exception as exc:
            logger.exception("AI validation failed")
            ai_result = {"valid": False, "summary": "AI 校验失败", "errors": [], "warnings": []}

        all_errors.extend(ai_result.get("errors", []))
        all_warnings.extend(ai_result.get("warnings", []))

        valid = len(all_errors) == 0
        return {
            "valid": valid,
            "summary": ai_result.get("summary", ""),
            "errors": all_errors,
            "warnings": all_warnings,
        }

    async def _ai_validate(self, category: str, json_data: dict) -> dict:
        system_prompt = _CATEGORY_PROMPTS.get(category)
        if not system_prompt:
            return {"valid": False, "summary": f"未知类别: {category}", "errors": [], "warnings": []}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(json_data, ensure_ascii=False, indent=2)},
        ]

        response = await _call_llm(
            self._client,
            self._model,
            messages,
            response_format={"type": "json_object"},
        )

        text = response.choices[0].message.content or ""
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI 输出非 JSON: %s", text[:200])
            return {"valid": False, "summary": "AI 响应解析失败", "errors": [], "warnings": []}

        return {
            "valid": result.get("valid", False),
            "summary": result.get("summary", ""),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }
```

- [ ] **Step 2: Verify import**

Run: `python -c "from model.validate_agent import ValidateAgent; print('OK')"`

Expected: no import errors.

---

### Task 3: Backend — Extend validate router + wire deps

**Files:**
- Modify: `app/routers/validate.py` (full rewrite)
- Modify: `app/deps.py:15-16,20-21,31,49-66`

**Interfaces:**
- Consumes: `ValidateRequest(category, json_data)`, `ValidateResponse(valid, summary, errors, warnings)`, `ValidateAgent`, `settings`
- Produces: `POST /api/validate` endpoint that dispatches by category, runs deterministic + AI checks

- [ ] **Step 1: Rewrite app/routers/validate.py**

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_validate_agent
from app.schemas import ApiResponse, ValidateRequest, ValidateResponse, ValidationErrorItem
from model.validate_agent import ValidateAgent

router = APIRouter(prefix="/api/validate", tags=["validate"])

_SCHEMA_CACHE: dict[str, Any] = {}
_SCHEMA_CACHE_LOCK = asyncio.Lock()

_SCHEMA_PATHS = {
    "control": settings.control_schema_path,
    "canvas": settings.schema_path,
    "binding": settings.binding_schema_path,
}


async def _load_schema(category: str) -> dict | None:
    path_str = _SCHEMA_PATHS.get(category)
    if not path_str:
        return None
    global _SCHEMA_CACHE
    if category not in _SCHEMA_CACHE:
        async with _SCHEMA_CACHE_LOCK:
            if category not in _SCHEMA_CACHE:
                schema_path = Path(path_str)
                text = await asyncio.to_thread(
                    lambda: schema_path.read_text(encoding="utf-8")
                )
                _SCHEMA_CACHE[category] = json.loads(text)
    return _SCHEMA_CACHE[category]


def _schema_validate(category: str, json_data: dict) -> list[ValidationErrorItem]:
    schema = _SCHEMA_CACHE.get(category)
    if not schema:
        return []
    errors: list[ValidationErrorItem] = []
    for err in jsonschema.Draft7Validator(schema).iter_errors(json_data):
        path = "/".join(str(p) for p in err.absolute_path) if err.absolute_path else ""
        errors.append(ValidationErrorItem(
            path=path,
            message=err.message,
            error_type=err.validator,
        ))
    return errors


def _layout_semantic_validate(json_data: dict) -> tuple[list[ValidationErrorItem], list[ValidationErrorItem]]:
    from model.generate_gird import LayoutFile, validate_layout_file
    try:
        layout_file = LayoutFile.model_validate(json_data)
        raw_errors, raw_warnings = validate_layout_file(layout_file)
        errors = [ValidationErrorItem(path=e.path, message=e.message, error_type="semantic") for e in raw_errors]
        warnings = [ValidationErrorItem(path=w, message=w, error_type="warning") for w in raw_warnings]
        return errors, warnings
    except Exception as exc:
        return [ValidationErrorItem(path="layoutIntent", message=str(exc), error_type="parse")], []


@router.post("", response_model=ApiResponse)
async def validate_json(
    req: ValidateRequest,
    agent: ValidateAgent = Depends(get_validate_agent),
):
    all_errors: list[ValidationErrorItem] = []
    all_warnings: list[ValidationErrorItem] = []

    await _load_schema(req.category)

    schema_errors = _schema_validate(req.category, req.json_data)
    all_errors.extend(schema_errors)

    if req.category == "layout":
        sem_errors, sem_warnings = _layout_semantic_validate(req.json_data)
        all_errors.extend(sem_errors)
        all_warnings.extend(sem_warnings)

    ai_result = await agent.validate(req.category, req.json_data)

    for e in ai_result.get("errors", []):
        all_errors.append(ValidationErrorItem(
            path=e.get("path", ""),
            message=e.get("message", ""),
            error_type=e.get("error_type", "ai"),
        ))
    for w in ai_result.get("warnings", []):
        all_warnings.append(ValidationErrorItem(
            path=w.get("path", ""),
            message=w.get("message", ""),
            error_type=w.get("error_type", "warning"),
        ))

    valid = len(all_errors) == 0
    return ApiResponse(data=ValidateResponse(
        valid=valid,
        summary=ai_result.get("summary", ""),
        errors=all_errors,
        warnings=all_warnings,
    ).model_dump())
```

- [ ] **Step 2: Wire ValidateAgent in app/deps.py**

Add global variable after line 15:
```python
_validate_agent: Optional[ValidateAgent] = None
```

Add init in `init_resources` after `_refine_agent = RefineAgent()` (line 32):
```python
    _validate_agent = ValidateAgent()
```

Add getter after `get_refine_agent` (after line 61):
```python
def get_validate_agent() -> ValidateAgent:
    assert _validate_agent is not None, "ValidateAgent not initialized (call init_resources first)"
    return _validate_agent
```

- [ ] **Step 3: Verify**

Run: `python -c "from app.deps import get_validate_agent; from app.routers.validate import router; print('OK')"`

Expected: no import errors.

---

### Task 4: Frontend — Bundle rule data into src/data/

**Files:**
- Create: `web/scada/src/data/controlSchema.ts`
- Create: `web/scada/src/data/canvasSchema.ts`
- Create: `web/scada/src/data/bindingSchema.ts`
- Create: `web/scada/src/data/layoutConfig.ts`
- Create: `web/scada/src/data/rules.ts`

**Interfaces:**
- Consumes: schema JSON files from `data/schema/`, `data/layout_config.json`
- Produces: typed TS modules exporting rule metadata, schema display data, and sample data

- [ ] **Step 1: Create web/scada/src/data/controlSchema.ts**

```typescript
export const controlSchema = {
  title: "控件索引项 (ControlIndexItem)",
  description: "控件资源与尺寸约束",
  properties: [
    { name: "displayName", type: "string", required: true, description: "控件显示名称" },
    { name: "image", type: "string", required: true, description: "控件资源路径（symbols/ 或 assets/ 下的 JSON 或图片文件）" },
    { name: "width", type: "number | null", required: true, description: "控件宽度" },
    { name: "height", type: "number | null", required: true, description: "控件高度" },
    { name: "boundExtend", type: "number", required: false, description: "边界扩展像素值" },
  ],
  additionalProperties: false,
};

export const controlDerivedRules = [
  "image 路径应以 symbols/ 或 assets/ 开头",
  "width 和 height 为 null 时应有合理理由（如占位符）",
  "boundExtend 若存在应 >= 0",
  "displayName 不应为空字符串",
];

export const controlSampleOk = {
  displayName: "电动调节阀",
  image: "symbols/valve_001.json",
  width: 60,
  height: 60,
};

export const controlSampleBad = {
  displayName: "",
  image: "unknown/valve.png",
  width: -1,
  height: "abc",
  boundExtend: -5,
};
```

- [ ] **Step 2: Create web/scada/src/data/canvasSchema.ts**

```typescript
export const canvasSchema = {
  title: "画布 (Canva)",
  description: "画布与编辑行为约束",
  properties: [
    { name: "v", type: "string", required: true, description: "版本号" },
    { name: "p", type: "object", required: true, description: "画布属性，含 layers、autoAdjustIndex、hierarchicalRendering" },
    { name: "a", type: "object", required: true, description: "画布尺寸与行为，含 width、height、fitContent、rectSelectable、pannable、zoomable" },
    { name: "d", type: "array", required: true, description: "数据元素数组" },
    { name: "contentRect", type: "object", required: true, description: "内容边界，含 x、y、width、height" },
  ],
};

export const canvasDerivedRules = [
  "contentRect 应能包含所有 d 元素的坐标范围",
  "d 数组元素应至少包含 c（类型）和 p（属性）字段",
  "layers 至少有一个图层",
  "a.width 和 a.height 应大于 0",
  "contentRect.width 和 height 应大于 0",
];

export const canvasSampleOk = {
  v: "8.0.5",
  p: {
    layers: [{ name: "0", visible: true, selectable: true, movable: true, editable: true }],
    autoAdjustIndex: true,
    hierarchicalRendering: true,
  },
  a: { width: 1920, height: 1080, fitContent: true, rectSelectable: false, pannable: false, zoomable: false },
  d: [
    { c: "ht.Node", i: 17092, p: { displayName: "阀1", image: "symbols/valve_001.json", width: 60, height: 60 } },
  ],
  contentRect: { x: 0, y: 0, width: 1920, height: 1080 },
};

export const canvasSampleBad = {
  v: 123,
  p: null,
  a: { width: -100, height: 0, fitContent: true },
  d: "not an array",
  contentRect: { x: 0, y: 0 },
};
```

- [ ] **Step 3: Create web/scada/src/data/bindingSchema.ts**

```typescript
export const bindingSchema = {
  title: "绑点项 (BindingItem)",
  description: "数据绑定与通信约束 — 控件属性与 PLC 变量的映射关系",
  properties: [
    { name: "controlId", type: "string", required: true, description: "控件 ID" },
    { name: "property", type: "enum", required: true, description: "控件绑定属性", enum: ["status", "value", "visible", "color", "text", "enabled"] },
    { name: "variable", type: "string", required: true, description: "PLC 变量名" },
    { name: "dataType", type: "enum", required: false, description: "变量数据类型", enum: ["bool", "int16", "int32", "float", "string"] },
    { name: "registerAddress", type: "string", required: false, description: "寄存器地址" },
  ],
  additionalProperties: false,
};

export const bindingDerivedRules = [
  "controlId 不应为空",
  "variable 不应为空",
  "若属性为 visible 或 enabled，建议 dataType 为 bool",
  "若属性为 status 或 value，建议 dataType 为数值类型（int16/int32/float）",
  "registerAddress 格式应为标准 PLC 寄存器地址（如 Q0.0、I0.1、DB1.DBX0.0）",
  "若有多个绑点，controlId 应唯一（每个控件只绑一次同一个属性）",
];

export const bindingSampleOk = {
  controlId: "valve_001",
  property: "status",
  variable: "DB1.DBX0.0",
  dataType: "bool",
  registerAddress: "DB1.DBX0.0",
};

export const bindingSampleBad = {
  controlId: "",
  property: "invalid_prop",
  variable: "",
  dataType: "complex",
};
```

- [ ] **Step 4: Create web/scada/src/data/layoutConfig.ts**

```typescript
export interface RoleLimit {
  keywords: string[];
  limits: {
    min_w: number;
    min_h: number;
    max_w: number;
    max_h: number;
    preferred_w: number;
    preferred_h: number;
  };
}

export const layoutConfig: {
  root_role_name: string;
  roles: Record<string, RoleLimit>;
} = {
  root_role_name: "root",
  roles: {
    root: {
      keywords: [],
      limits: { min_w: 120, min_h: 120, max_w: 180, max_h: 260, preferred_w: 160, preferred_h: 240 },
    },
    pipe: {
      keywords: ["管"],
      limits: { min_w: 80, min_h: 20, max_w: 180, max_h: 50, preferred_w: 120, preferred_h: 30 },
    },
    valve: {
      keywords: ["阀"],
      limits: { min_w: 40, min_h: 40, max_w: 80, max_h: 80, preferred_w: 60, preferred_h: 60 },
    },
    meter: {
      keywords: ["流量", "表"],
      limits: { min_w: 50, min_h: 50, max_w: 100, max_h: 100, preferred_w: 80, preferred_h: 80 },
    },
    sensor: {
      keywords: ["传感", "压力"],
      limits: { min_w: 50, min_h: 40, max_w: 110, max_h: 90, preferred_w: 80, preferred_h: 60 },
    },
    default: {
      keywords: [],
      limits: { min_w: 50, min_h: 40, max_w: 120, max_h: 120, preferred_w: 80, preferred_h: 80 },
    },
  },
};

export const layoutDerivedRules = [
  "groups 不能为空",
  "group.id 必须唯一",
  "group.count >= 1",
  "当 arrangement=grid 时，columns 或 rows 至少一个 >= 1，且 columns*rows >= count",
  "attachment.relativeTo 必须引用本组已声明的节点",
  "connection.id 必须唯一，source/target.group 必须存在",
  "角色尺寸约束：root(120-180x120-260)、pipe(80-180x20-50)、valve(40-80x40-80)、meter(50-100x50-100)、sensor(50-110x40-90)",
];

export const layoutSampleOk = {
  layoutIntent: {
    groups: [
      {
        id: "group1",
        region: "center",
        unit: {
          root: { id: "valve_1", deviceType: "电动调节阀", role: "valve" },
          attachments: [{ id: "sensor_1", deviceType: "压力传感器", role: "sensor", relativeTo: "valve_1", side: "right" }],
        },
        count: 2,
        arrangement: "horizontal",
        gapHint: "normal",
      },
    ],
    connections: [{ id: "conn1", source: { group: "group1", node: "valve_1" }, target: { group: "group1", node: "sensor_1" } }],
  },
};

export const layoutSampleBad = {
  layoutIntent: {
    groups: [],
  },
};
```

- [ ] **Step 5: Create web/scada/src/data/rules.ts**

```typescript
import { controlSchema, controlDerivedRules, controlSampleOk, controlSampleBad } from "./controlSchema";
import { canvasSchema, canvasDerivedRules, canvasSampleOk, canvasSampleBad } from "./canvasSchema";
import { bindingSchema, bindingDerivedRules, bindingSampleOk, bindingSampleBad } from "./bindingSchema";
import { layoutConfig, layoutDerivedRules, layoutSampleOk, layoutSampleBad } from "./layoutConfig";

export interface RuleCategory {
  id: string;
  label: string;
  icon: string;
  schema: { title: string; description: string; properties: { name: string; type: string; required: boolean; description: string; enum?: string[] }[] };
  derivedRules: string[];
  sampleOk: Record<string, unknown>;
  sampleBad: Record<string, unknown>;
}

export const ruleCategories: RuleCategory[] = [
  {
    id: "control",
    label: "控件资源与尺寸",
    icon: "🧩",
    schema: controlSchema,
    derivedRules: controlDerivedRules,
    sampleOk: controlSampleOk as Record<string, unknown>,
    sampleBad: controlSampleBad as Record<string, unknown>,
  },
  {
    id: "canvas",
    label: "画布与编辑行为",
    icon: "🖼️",
    schema: canvasSchema,
    derivedRules: canvasDerivedRules,
    sampleOk: canvasSampleOk as Record<string, unknown>,
    sampleBad: canvasSampleBad as Record<string, unknown>,
  },
  {
    id: "layout",
    label: "布局与拓扑",
    icon: "🔗",
    schema: { title: "布局意图 (LayoutIntent)", description: "布局与拓扑约束 — 角色尺寸、区域排列、附件关系、连线合法性", properties: [] },
    derivedRules: layoutDerivedRules,
    sampleOk: layoutSampleOk as Record<string, unknown>,
    sampleBad: layoutSampleBad as Record<string, unknown>,
  },
  {
    id: "binding",
    label: "数据绑定与通信",
    icon: "📡",
    schema: bindingSchema,
    derivedRules: bindingDerivedRules,
    sampleOk: bindingSampleOk as Record<string, unknown>,
    sampleBad: bindingSampleBad as Record<string, unknown>,
  },
];
```

---

### Task 5: Frontend — API + Store

**Files:**
- Create: `web/scada/src/api/validate.ts`
- Create: `web/scada/src/stores/ruleStore.ts`

**Interfaces:**
- Consumes: `post<T>` from `api/client.ts`; `ruleCategories` from `data/rules.ts`
- Produces: `validateRequest(category, jsonData) -> Promise<ValidateResponse>`; `useRuleStore()` with `activeCategory`, `validatorInput`, `result`, `loading`, `runValidate()`

- [ ] **Step 1: Create web/scada/src/api/validate.ts**

```typescript
import { post } from "./client";

export interface ValidationErrorItem {
  path: string;
  message: string;
  error_type: string;
}

export interface ValidateResponse {
  valid: boolean;
  summary: string;
  errors: ValidationErrorItem[];
  warnings: ValidationErrorItem[];
}

export function validateRequest(category: string, jsonData: Record<string, unknown>): Promise<ValidateResponse> {
  return post<ValidateResponse>("/api/validate", { category, json_data: jsonData });
}
```

- [ ] **Step 2: Create web/scada/src/stores/ruleStore.ts**

```typescript
import { create } from "zustand";
import type { ValidateResponse, ValidationErrorItem } from "../api/validate";
import { validateRequest } from "../api/validate";

interface RuleStore {
  activeCategory: string;
  validatorInput: string;
  result: ValidateResponse | null;
  loading: boolean;
  error: string | null;
  setActiveCategory: (id: string) => void;
  setValidatorInput: (input: string) => void;
  runValidate: (category: string) => Promise<void>;
}

export const useRuleStore = create<RuleStore>((set) => ({
  activeCategory: "control",
  validatorInput: "",
  result: null,
  loading: false,
  error: null,

  setActiveCategory: (id: string) => set({ activeCategory: id }),

  setValidatorInput: (input: string) => set({ validatorInput: input }),

  runValidate: async (category: string) => {
    set({ loading: true, error: null, result: null });
    try {
      let jsonData: Record<string, unknown>;
      try {
        jsonData = JSON.parse(useRuleStore.getState().validatorInput);
      } catch {
        set({ loading: false, error: "JSON 格式错误，请检查输入" });
        return;
      }
      const result = await validateRequest(category, jsonData);
      set({ result, loading: false });
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : "校验请求失败" });
    }
  },
}));
```

---

### Task 6: Frontend — RuleLibraryPage + ValidatorPanel

**Files:**
- Create: `web/scada/src/components/schema/RuleLibraryPage.tsx`
- Create: `web/scada/src/components/schema/ValidatorPanel.tsx`

**Interfaces:**
- Consumes: `useRuleStore()`; `ruleCategories` from `data/rules.ts`
- Produces: Full R-01 page with 3-column layout (left nav, center content, right validator panel)

- [ ] **Step 1: Create web/scada/src/components/schema/ValidatorPanel.tsx**

```tsx
import { useRuleStore } from "../../stores/ruleStore";
import { ruleCategories } from "../../data/rules";

export default function ValidatorPanel() {
  const { activeCategory, validatorInput, result, loading, error, setValidatorInput, runValidate, setActiveCategory } = useRuleStore();

  const cat = ruleCategories.find((c) => c.id === activeCategory);

  const handleSample = (type: "ok" | "bad") => {
    if (!cat) return;
    const sample = type === "ok" ? cat.sampleOk : cat.sampleBad;
    setValidatorInput(JSON.stringify(sample, null, 2));
  };

  return (
    <div className="w-[300px] border-l border-[var(--border1)] flex flex-col bg-[var(--bg1)]">
      <div className="px-3 py-2 text-[12px] font-semibold text-[var(--text2)] border-b border-[var(--border1)]">
        校验器
      </div>

      <div className="p-2 border-b border-[var(--border1)]">
        <select
          className="w-full text-[12px] px-2 py-1 rounded border border-[var(--border1)] bg-[var(--bg2)] text-[var(--text1)] outline-none"
          value={activeCategory}
          onChange={(e) => setActiveCategory(e.target.value)}
        >
          {ruleCategories.map((c) => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 flex flex-col p-2 gap-2">
        <textarea
          className="flex-1 w-full text-[11px] font-mono p-2 rounded border border-[var(--border1)] bg-[var(--bg2)] text-[var(--text1)] resize-none outline-none"
          placeholder="在此粘贴 JSON 进行校验..."
          value={validatorInput}
          onChange={(e) => setValidatorInput(e.target.value)}
        />

        <div className="flex gap-1">
          <button
            className="flex-1 px-2 py-1 text-[11px] rounded bg-[var(--accent)] text-white font-medium disabled:opacity-40"
            disabled={loading || !validatorInput.trim()}
            onClick={() => runValidate(activeCategory)}
          >
            {loading ? "校验中..." : "AI 校验"}
          </button>
          <button
            className="px-2 py-1 text-[11px] rounded border border-[var(--border1)] text-[var(--text2)] hover:bg-[var(--bg2)]"
            onClick={() => handleSample("ok")}
          >
            合法例
          </button>
          <button
            className="px-2 py-1 text-[11px] rounded border border-[var(--border1)] text-[var(--text2)] hover:bg-[var(--bg2)]"
            onClick={() => handleSample("bad")}
          >
            非法例
          </button>
        </div>

        {error && (
          <div className="text-[11px] p-2 rounded bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800">
            {error}
          </div>
        )}

        {result && (
          <div className="text-[11px] border border-[var(--border1)] rounded overflow-hidden">
            <div className={`px-2 py-1 font-medium text-white ${result.valid ? "bg-green-500" : "bg-red-500"}`}>
              {result.valid ? "✓ 校验通过" : "✗ 校验未通过"}
              {result.summary && ` — ${result.summary}`}
            </div>
            {result.errors.length > 0 && (
              <div className="p-2 bg-red-50 dark:bg-red-900/10">
                <div className="font-medium text-red-600 dark:text-red-400 mb-1">错误 ({result.errors.length})</div>
                {result.errors.map((e, i) => (
                  <div key={i} className="mb-1 last:mb-0">
                    <span className="text-red-500">[err]</span>{" "}
                    {e.path && <span className="text-[var(--text3)]">{e.path}: </span>}
                    {e.message}
                  </div>
                ))}
              </div>
            )}
            {result.warnings.length > 0 && (
              <div className="p-2 bg-yellow-50 dark:bg-yellow-900/10">
                <div className="font-medium text-yellow-600 dark:text-yellow-400 mb-1">警告 ({result.warnings.length})</div>
                {result.warnings.map((w, i) => (
                  <div key={i} className="mb-1 last:mb-0">
                    <span className="text-yellow-500">[warn]</span>{" "}
                    {w.path && <span className="text-[var(--text3)]">{w.path}: </span>}
                    {w.message}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create web/scada/src/components/schema/RuleLibraryPage.tsx**

```tsx
import { useRuleStore } from "../../stores/ruleStore";
import { ruleCategories } from "../../data/rules";
import { layoutConfig } from "../../data/layoutConfig";
import ValidatorPanel from "./ValidatorPanel";

export default function RuleLibraryPage() {
  const { activeCategory, setActiveCategory } = useRuleStore();

  const cat = ruleCategories.find((c) => c.id === activeCategory);
  if (!cat) return null;

  return (
    <div className="flex flex-1 h-full">
      {/* Left nav */}
      <nav className="w-[180px] border-r border-[var(--border1)] bg-[var(--bg1)] flex flex-col shrink-0">
        <div className="px-3 py-2 text-[11px] font-semibold text-[var(--text3)] uppercase tracking-wider border-b border-[var(--border1)]">
          规则分类
        </div>
        {ruleCategories.map((c) => (
          <button
            key={c.id}
            className={`flex items-center gap-2 px-3 py-2 text-[12px] text-left transition-colors ${
              activeCategory === c.id
                ? "bg-[var(--accent)]/10 text-[var(--accent)] font-medium border-r-2 border-[var(--accent)]"
                : "text-[var(--text2)] hover:bg-[var(--bg2)]"
            }`}
            onClick={() => setActiveCategory(c.id)}
          >
            <span className="text-[14px]">{c.icon}</span>
            <span>{c.label}</span>
          </button>
        ))}
      </nav>

      {/* Center content */}
      <div className="flex-1 overflow-y-auto p-4 bg-[var(--bg2)]">
        <div className="max-w-[800px] mx-auto">
          <h1 className="text-[18px] font-bold text-[var(--text1)] mb-1">{cat.schema.title}</h1>
          <p className="text-[12px] text-[var(--text3)] mb-4">{cat.schema.description}</p>

          {/* Schema fields */}
          {cat.schema.properties.length > 0 && (
            <section className="mb-6">
              <h2 className="text-[13px] font-semibold text-[var(--text1)] mb-2">字段定义</h2>
              <div className="border border-[var(--border1)] rounded overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[var(--bg1)]">
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">字段名</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">类型</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">必填</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cat.schema.properties.map((p) => (
                      <tr key={p.name} className="border-t border-[var(--border1)]">
                        <td className="px-3 py-1.5 font-mono text-[var(--accent)]">{p.name}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{p.type}</td>
                        <td className="px-3 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${p.required ? "bg-red-100 dark:bg-red-900/20 text-red-600" : "bg-gray-100 dark:bg-gray-800 text-[var(--text3)]"}`}>
                            {p.required ? "必填" : "可选"}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">
                          {p.description}
                          {p.enum && <span className="block text-[var(--text3)] mt-0.5">枚举值: {p.enum.join(", ")}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Layout role limits (only for layout category) */}
          {activeCategory === "layout" && (
            <section className="mb-6">
              <h2 className="text-[13px] font-semibold text-[var(--text1)] mb-2">角色尺寸约束</h2>
              <div className="border border-[var(--border1)] rounded overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[var(--bg1)]">
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">角色</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">关键词</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">最小尺寸</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">最大尺寸</th>
                      <th className="px-3 py-1.5 text-left text-[var(--text3)] font-medium">推荐尺寸</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(layoutConfig.roles).map(([role, cfg]) => (
                      <tr key={role} className="border-t border-[var(--border1)]">
                        <td className="px-3 py-1.5 font-mono text-[var(--accent)]">{role}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.keywords.join(", ") || "-"}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.min_w}×{cfg.limits.min_h}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.max_w}×{cfg.limits.max_h}</td>
                        <td className="px-3 py-1.5 text-[var(--text2)]">{cfg.limits.preferred_w}×{cfg.limits.preferred_h}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Derived rules */}
          <section className="mb-6">
            <h2 className="text-[13px] font-semibold text-[var(--text1)] mb-2">派生规则</h2>
            <div className="border border-[var(--border1)] rounded divide-y divide-[var(--border1)]">
              {cat.derivedRules.map((rule, i) => (
                <div key={i} className="px-3 py-1.5 text-[11px] text-[var(--text2)]">
                  {i + 1}. {rule}
                </div>
              ))}
            </div>
          </section>

          {/* Samples */}
          <section className="mb-6">
            <h2 className="text-[13px] font-semibold text-[var(--text1)] mb-2">示例</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] font-medium text-green-600 dark:text-green-400 mb-1">✓ 合法示例</div>
                <pre className="text-[10px] p-2 rounded border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/10 text-[var(--text1)] overflow-x-auto max-h-[160px]">
                  {JSON.stringify(cat.sampleOk, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-[11px] font-medium text-red-600 dark:text-red-400 mb-1">✗ 非法示例</div>
                <pre className="text-[10px] p-2 rounded border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 text-[var(--text1)] overflow-x-auto max-h-[160px]">
                  {JSON.stringify(cat.sampleBad, null, 2)}
                </pre>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Right validator panel */}
      <ValidatorPanel />
    </div>
  );
}
```

---

### Task 7: Frontend — Wire into App.tsx

**Files:**
- Modify: `web/scada/src/App.tsx:5,33`

**Interfaces:**
- Consumes: `RuleLibraryPage` component
- Produces: `activeTab === "schema"` renders `RuleLibraryPage` instead of `PlaceholderPage`

- [ ] **Step 1: Add import and replace placeholder**

Add import at line 6 (after RefineAgentPage import):
```typescript
import RuleLibraryPage from "./components/schema/RuleLibraryPage";
```

Replace line 33:
```tsx
        {activeTab === "schema" && <RuleLibraryPage />}
```