# PROGRESS

## M1 后端统一几何模块与生成期宽高比修复 — 完成

- 新增 `model/layout_tools/geometry.py`：`fit_size`（新尺寸规则：可满足时沿用原策略，不可满足时用 maxScale 兜底）、`inscribe_ratio`（保持中心、只缩不放）、`ratio_error`、`round2`、`content_rect_of_nodes`（自 layout_agent 迁移）。
- `compute_position._fit_size` 委托 `geometry.fit_size`，原 min_scale>max_scale 时返回 preferred 的缺陷已修复；返回 (width, height, source_w, source_h)。
- `_PlacedNode` 增加 `material_name/source_width/source_height`，随 `_fit_unit_to_slot`、`compute_unit_layout` 透传。
- `build_nodes` 在 `a` 中写入 `layout.materialName`、`layout.sourceWidth`、`layout.sourceHeight`（取 preferred 兜底后的实际原始值）。
- `model/layout_agent.py` 的 `_calc_content_rect` 改为委托 `geometry.content_rect_of_nodes`。
- 新增 `tests/test_geometry.py`（18 个用例）：fit_size 各分支、6 个可复现素材根角色宽高比误差 ≤0.1%、inscribe 只缩不放、元数据嵌入与缺失尺寸兜底。
- 验证：`python3 -m pytest tests/` 57 passed；`ruff check model/ tests/` 通过。

## M2 微调 Agent 宽高比强制 — 完成

- `_ControlGeometry` 增加 `aspect`（来自节点 `a.layout.sourceWidth/sourceHeight`，新增 `_aspect_from_attributes` 解析；非正/缺失 → None）。
- resize 分支：scale 等比缩放；仅 width → h=w/ratio；仅 height → w=h*ratio；width+height 视为上界框 → `geometry.inscribe_ratio` 内接。
- 目标无 ratio 元数据 → `RefineInputError`（refine 返回空 patch + 说明消息，不进入 pending-accept）。
- 新增 `_clamp_ratio_geometry`：画布边界只做等比缩放（先等比放大到 ≥1，再等比缩小到画布内），不再分别钳制 w/h。
- `_compile_patch`：被 resize 的控件始终同时输出 width 与 height 两个 op。
- 新增 `tests/test_refine_ratio.py`（10 个用例）：scale/单边/失配框内接、画布等比裁剪、缺元数据阻止、双 op 输出、标签按新边界重定位。
- 验证：`python3 -m pytest tests/` 67 passed；ruff 通过。

## M3 上传网关 POST /api/canvas/upload — 完成

- `app/config.py` 新增 `daoscada_upload_url`（http://daoscada.local/hmi-ui/upload/）、`daoscada_target_dir`（displays/dutzcm）、`daoscada_upload_timeout`，上传地址不再由前端硬编码。
- 新增 `app/services/canvas_upload_service.py`：文件名校验（无路径分隔、.json）；ratio 判定顺序 元数据(a.layout.sourceWidth/sourceHeight) → 素材库 name+image 唯一匹配 → 剥离实例编号后缀(液压泵2→液压泵)且唯一 → 否则 422 并列出 node_i/displayName/image；非正尺寸同样 422。修正 = `inscribe_ratio` 保持中心只缩不放；标签按新边界重定位（上/下、gap 8）；contentRect 重算；碰撞前后比对（新增/扩大 → 422，既有 → warnings）；`_schema_validate` 校验；`httpx` multipart 上传 path=displays/dutzcm/{file_name}、content=规范化 JSON。异常映射：输入/素材/JSON → 422（UploadBlockedError），上游拒绝/连接失败 → 502（UploadUpstreamError），超时 → 504（UploadTimeoutError）。
- `app/schemas.py` 新增 `UploadCanvasRequest/CorrectionSize/CorrectionItem/UploadCanvasResponse`（corrections 含 node_i、display_name、image、before/after 尺寸）。
- `app/routers/canvas.py` 新增 POST /upload 路由，依赖 `get_material_db` 取素材库。
- 新增 `tests/test_canvas_upload.py`（24 个用例，httpx.MockTransport）：历史 JSON 内接修正（保中心、不放大 bbox）、元数据优先、name+image 匹配、后缀剥离、重复图片路径歧义阻止、缺尺寸阻止、文件名校验、schema 阻止、输入不被篡改、既有重叠转 warnings、multipart 路径与规范化内容、502/504 映射、路由 200/422/502/504 映射。
- 验证：`python3 -m pytest tests/` 91 passed；ruff 通过。

## M4 前端等比缩放与严格预览 — 完成

- `utils/dragGeometry.ts` 新增 `computeRatioResize`（handle 支持 4 角 + 4 边）：用户拖出的矩形作为上界，取矩形内最大的等比尺寸，对角/对边锚定；画布边界只做等比缩放；非正/非有限 aspect 回退为 1；结果四舍五入到 2 位小数。
- `components/canvas/AgentCanvas.tsx`：
  - 删除旧的自由变形 `computeResize`，改为 `computeRatioResize`，aspect 取 `node.a.layout.sourceWidth/sourceHeight`（缺失时回退当前 w/h）。
  - 新增 n/s/e/w 四边手柄（`EDGE_CURSORS` ns-resize/ew-resize），共 8 个手柄。
  - 控件图与装饰图移除 `objectFit: contain` 与 padding，改为按节点尺寸全拉伸，严格模拟 DaoSCADA 远端拉伸语义（错误 JSON 在插入前即可暴露）。
- 新增 8 个用例（tests/dragGeometry.test.ts）：对角拖拽保比+对边锚定、边拖拽（收缩/失配节点向素材比回归）、上界框内接、超大拖拽等比裁剪、非法 aspect 回退。
- 验证：`npm test` 63 passed；`npm run build` 通过。`npm run lint` 仅剩基线既有的 client.ts:23 preserve-caught-error 一处（本分支未改该文件）。

## M5 前端上传网关与回写 — 完成

- `api/layout.ts`：删除前端硬编码的 `uploadToSystem`（直连 http://daoscada.local/hmi-ui/upload/），新增 `uploadCanvas(fileName, jsonData)` 调用 `POST /api/canvas/upload`。
- `types/layout.ts` 新增 `UploadCanvasResponse/UploadCorrection/UploadCorrectionSize`。
- `stores/layoutStore.ts`：新增 `corrections/uploadWarnings` 状态与 `applyUploadResult(res)`（写入规范化 jsonData、重提取 nodes+decorations 使画布显示远端几何；setLayoutResult/clearCanvas 清空修正信息）。
- `stores/refineStore.ts`：新增 `applyUploadResult(res)`（更新 workingJson/workingNodes/decorations；保留 workingPipes；不清除 pendingPatch，保持插入阻塞）。
- 两个插入按钮（布局 Agent / 微调 Agent 面板）均改为调用 `uploadCanvas`：成功才显示"已插入系统"（含修正数量），失败显示后端错误；成功后面板展示逐控件修正详情（before→after）与警告列表。
- 新增 `tests/layoutStoreUpload.test.ts`（4 个用例）与 `tests/refineStoreUpload.test.ts`（3 个用例）：规范化 JSON 回写、节点重提取、修正信息保存/清理、pendingPatch 阻塞保持、pipes 保留。
- 验证：`npm test` 70 passed；`npm run build` 通过；`npm run lint` 仅剩基线既有的 client.ts:23 一处。
