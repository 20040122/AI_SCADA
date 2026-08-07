# PROGRESS

## M1-M4: 后端核心（CSV / JSONL / BindingAgent / 路由）

已完成：

- `app/services/csv_service.py` 重写为严格二列解析。仅接受 `displayName,propertyName` 表头，物理行号保留，空白行忽略，空字段/行宽≠2/重复组合整批阻断；5MB、10000 行限制延续。删除列映射、别名、suggest_mapping、normalize_csv。
- `app/services/binding_config_service.py` 重写为新 JSONL 格式（id/handler/displayName/propertyName/projectId/projectName/deviceId/deviceName/propertyId/dataType/dataTypeDesc/writable/unit），校验必填、三类 ID 数字串、dataType 枚举、writable 布尔、id 唯一、物理源不重复。
- `data/binding.jsonl` 更新为新格式，air_tank_pressure 为 double/双精度。
- `model/binding_agent.py` 实现 BindingAgent 与 handler 注册表（仅 panel_list）。匹配算法：完整名定位唯一节点、编号面板归一化、精确候选（唯一精确预选 score=1 高置信/多精确不预选）、语义候选（本地 BGE，score 仅属性名相似度，4 位舍入，>=0.55 top5，score 降序 binding_id 升序，lead 与置信度阈值）。构建：深拷贝、逐行 assignment 校验、候选集合重验、同目标重复源阻断、handler 渲染 panel.list、Binding+Canvas Schema 校验、原子失败返回 bound_json=null。
- `app/services/semantic.py` BgeSimilarity 增加 `encode()` 批量接口。
- `app/schemas.py` binding 块重写为新 API 模型（preview requests / match targets+items / build assignments）。
- `app/routers/binding.py` 重写为薄路由，经 DI 调用 BindingAgent；删除 /csv/normalize。
- `app/deps.py` 增加 `_binding_agent` 初始化与 `get_binding_agent`。
- 删除 `app/services/match_service.py`、`app/services/build_service.py`。

验证：

- 手动冒烟：match（精确+语义）与 build（替换/顺序/未列控件保留/原画布不变/压力 double）通过。
- `python3 -m ruff check` 相关文件通过。

## M5: 后端测试 + 真值集

已完成：

- `tests/test_binding.py` 全量重写为新模型：CSV 严格二列（表头/行宽/空值/重复/物理行号/空白行/引号）、编码（utf-8/BOM/gb18030/5MB/10k 行/非 CSV）、JSONL 校验（缺字段/ID 数字串/dataType 枚举/writable 布尔/unit 类型/id 重复/物理源重复/JSON 语法/未知 handler 阻断构造）、panel_list handler（名称匹配/归一化/渲染）、匹配算法（唯一精确预选高置信/多精确不预选/语义 top5/0.55 阈值/lead/稳定排序/编号面板共用目录/不同名阻断/缺目标/不支持控件/非 ht.Node）、构建（精确结构/整体替换/原画布不变/未列控件保留/CSV 顺序/缺 assignment/伪造 binding_id/注册表内非候选阻断/同目标重复源阻断/跨目标复用允许/Schema 失败原子回滚/preview 结构）。
- `tests/test_binding_routes.py` 重写：新 preview/match/build 请求体、/csv/normalize 返回 404、额外字段 422、业务错误 bound_json=null、Canvas Schema 失败。
- 新增 `tests/fixtures/binding/properties.csv`（20 行真值集）+ `ground_truth.json`（每行期望 binding_id）。
- 真值集 Top-1 测试（真实本地 BGE，无 skip）：20/20 命中，全部 top 候选 score>=0.55，准确率 100%。

验证：

- `python3 -m pytest` 全部 216 通过。
- `python3 -m ruff check` 全部通过。

## M6-M7: 前端改造

已完成：

- `web/scada/src/types/binding.ts` 重写为新 API 类型：BindingRequestRow / BindingPreviewResponse（requests）/ BindingCandidate（binding_id 而非 key，含 score/evidence）/ BindingTarget / BindingMatchItem（row_number + suggested_binding_id + lead）/ BindingAssignment（仅 row_number+binding_id）/ BindingBuildPreview（通用 before/after）。删除 BindingProperty、列映射、normalize、expectation/panel 相关类型。
- `web/scada/src/api/binding.ts` 重写：previewCsv 不变；删除 normalizeCsv；matchBinding(json_data, requests)、buildBinding(json_data, requests, assignments) 使用新请求体。
- `web/scada/src/stores/bindingStore.ts` 重写：新增 requests 状态；setPreview 存储后端 requests；runMatch 发送 requests 并预选 suggested_binding_id（confirmed 恒为 false）；selectCandidate(rowNumber, bindingId)/confirmItem(rowNumber) 按行操作，改选撤销确认并清空 build/upload；删除 setColumnMapping/applyNormalize/confirmAllHigh；runBuild 仅发送已确认行的 {row_number, binding_id}；revision/CSV/请求变化清空候选、确认、build、upload。
- `web/scada/src/components/binding-agent/LeftPanel.tsx` 重写：删除列映射/规范 UI，展示编码/总行数/固定表头与首 20 行表格。
- `web/scada/src/components/binding-agent/CenterPanel.tsx` 重写：按 targets 分组、每行独立确认按钮、删除「确认全部高置信」与期望面板、证据折叠展示、backend blocked/errors 展示。
- `web/scada/src/components/binding-agent/RightPanel.tsx` 重写：通用 before/after 新旧对比、生成按钮仅在全部行已确认且无阻断错误时可用、上传失败保留已生成 JSON 可重试。

验证：

- `npm run lint`、`npm run build` 通过。

## M8: 前端测试

已完成：

- `web/scada/tests/bindingStore.test.ts` 重写为新 store：新请求体断言（match 发送 requests；build 仅发送 {row_number,binding_id}）、suggested 仅预选不自动确认、多精确不预选、每行独立确认（无批量确认）、改选撤销确认并清空 build、source/CSV 变化清空下游、backend blocked/errors 存储、上传失败保留 boundJson 可重试、上传仅改 binding store 不动 layout/refine、pipes 深拷贝。
- `bindingApi.test.ts`、`bindingSource.test.ts` 保持通过（URL 与 resolveBindingSource 未变）。

验证：

- `npm test` 全部 96 通过。

## M9: 全量验证

已完成：

- `python3 -m pytest`：216 通过（含真值集 Top-1 20/20）。
- `cd web/scada && npm test`：96 通过。
- `cd web/scada && npm run lint`：通过。
- `cd web/scada && npm run build`：通过。
- `python3 -m ruff check .`：全部通过。

全部里程碑完成。实现与 PLAN.md 要求一致。
