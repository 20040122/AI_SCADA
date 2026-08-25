# PROGRESS

按 PLAN.md 的 milestone 顺序实施。本文件随每个 milestone 完成后更新。

通用约束：Python 3.9，新增 Python 代码不写注释，改动后运行 ruff。

## M1 统一校验服务 ✔
- 新增 `app/services/validation_service.py`：
  - 启动时加载 control/canvas/binding 三份 Draft-07 Schema，执行 `Draft7Validator.check_schema`；文件缺失/JSON 非法直接抛 `SchemaLoadError` 阻止启动。
  - 单例 `ValidationService.instance()`；`init_resources()` 启动时加载。
  - 集中管理四类规则的元数据（label/title/description/properties/derived_rules/sample_valid/sample_invalid）供规则接口复用。
  - 统一输出、按路径+消息排序、去重；semantic 路径统一转为 RFC6901 JSON Pointer。
  - 语义规则：
    - control：非空名称、image 前缀 symbols/assets、非负尺寸、非负 boundExtend；0/null 尺寸产生 warning。
    - canvas：至少一个 layer、正数画布尺寸、元素含非空 c 与对象 p、contentRect 非负、有几何元素时必须正并覆盖。
    - layout：复用 LayoutFile/`validate_layout_file`，补充同组节点 ID 重复、未知字段拒绝。
    - binding：独立包装对象 + 完整 canvas 两种形态；严格层级字段、枚举、数字字符串 ID、未知字段拒绝；path/key 与 proj/dev/param ID 一致、label 与名称/单位一致、同面板 path 不重复；错误路径含完整节点位置。
- `app/schemas.py`：`ValidationErrorItem` 新增 `source`（schema|semantic|ai|system）；新增规则接口模型。

## M2 校验 API 路由 ✔
- `app/routers/validate.py` 改造：
  - POST /api/validate 使用统一服务；`valid` 仅在确定性错误列表为空时为 true。
  - summary 由程序生成（通过 / 错误数 / 警告数）；不使用 AI summary。
  - 确定性错误存在时不调用 AI；AI findings 统一转为 source=ai 的 warning。
  - 新增 GET /api/validate/rules，通过 `ApiResponse` 返回四类规则元数据。
- 请求类别/类型非法仍由 FastAPI 返回 422；业务不合法返回 200 且 valid=false。

## M3 ValidateAgent 改造 ✔
- `model/validate_agent.py` 重写：
  - 仅返回辅助 findings（errors 恒空、AI 的 errors/warnings 全部转为 warning），不再计算 valid。
  - 无模型配置、响应非 JSON/结构无效、异常、10 秒超时、超过 64 KiB 输入均生成明确 ai warning。
  - 每个类别 10 秒超时（`asyncio.wait_for`）。
  - 更新四类 AI 提示，与真实数据契约一致（移除旧 binding 字段与 layout connections/尺寸规则）。

## M4 控件目录统一校验器 ✔
- `model/control_tools/catalog.py` 的 `load_canonical_controls` 用统一服务的 control 校验逐条记录；非法记录抛 `CatalogConfigError`。
- 初始加载（`load_initial`）失败向上抛，阻止启动；热更新（`_maybe_reload`）失败被捕获，保留上一快照。

## M5 layout 语义规则补全 ✔
- 由 M1 统一服务承载：同组节点 ID 重复校验、未知字段拒绝、derived_rules 元数据覆盖 topology/relativeTo/side/constraints；移除不存在的 connections 与无法判断的尺寸规则。

## M6 binding 校验与生产门禁 ✔
- `model/binding_agent.py` 默认 validator 改用统一服务（移除 jsonschema 缓存），支持独立包装对象与完整 canvas。
- `app/routers/binding.py`：最终上传校验失败（error 含 Canvas/Binding Schema）返回 422；构建逻辑错误继续返回 200 + bound_json=null。

## M7 canvas 生产门禁 ✔
- `model/layout_agent.py` generate 在落盘前用统一 canvas 校验，输出无效抛 `LayoutOutputError`，不写文件不返回。
- `app/routers/canvas.py` 捕获 `LayoutOutputError` 映射为 422。

## M8 AI 提示更新 ✔
- 见 M3，四类提示已与真实数据契约一致。

## M9 前端改造 ✔
- 删除静态规则镜像 `data/rules.ts`、`controlSchema.ts`、`canvasSchema.ts`、`bindingSchema.ts`；`layoutConfig.ts` 移除规则/样本导出。
- `api/validate.ts`：新增 `source` 字段、`RuleCategoryMeta`/`getRules()`。
- `stores/ruleStore.ts`：从 GET /api/validate/rules 加载四类元数据；加载失败设置 error 不回退静态规则。
- `ValidatorPanel.tsx`：按钮改“开始校验”，展示 schema/semantic/ai/system 来源标识与统一路径，样本来自后端接口。
- `RuleLibraryPage.tsx`：schema/derived_rules/samples 全部来自接口。

## M10 测试 ✔
- 新增 `tests/test_validation.py`：Schema 自检（Draft-07/缺失/非法阻止启动）、rules 接口四类、合法回归（control.jsonl 全量、data/canvas.json、layout、binding 独立+完整 canvas）、非法回归（四类前端样例、布局 ID/未知字段）、JSON Pointer、确定性错误不调 AI、AI findings→warning、AI 回归（无配置/过大/非 JSON/异常）。
- 更新 `tests/test_agents.py`、`tests/test_binding.py`、`tests/test_binding_routes.py`、`tests/test_control_generation.py`、`tests/test_refine_add_control.py`、`tests/test_canvas_upload.py`（mock client 默认注入，禁止访问 daoscada.local）。

## M11 全量验收 ✔
- `python3 -m pytest -q`：464 passed
- `ruff check .`：All checks passed
- `npm test`：143 passed
- `npm run build`：成功
- 更新本文件。

## 风险与说明
- layout 未知字段拒绝与 binding/control 未知字段策略更严格，符合 PLAN 预期阻断；canvas 保留扩展字段。
- 前端规则加载的自动化测试因 node:test 对 ESM 扩展名解析限制未新增（`node --test` 无法解析源文件内无扩展名的 import）；行为已实现且经 tsc/build 保障。
- 「contentRect 必须覆盖所有元素」校验已按需求移除（该规则会因元素越出画布对合法布局产生误报，影响布局落盘/返回）。保留 contentRect 各维非负检查与空画布允许零尺寸；同步更新 canvas 派生规则元数据并清理 `_content_span` 等无引用代码。
