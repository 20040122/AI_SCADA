# PROGRESS.md — 微调 Agent 添加控件

## 计划

- [x] M1: 抽取附属控件尺寸解析复用模块
- [x] M2: 布局阶段写入素材快照
- [x] M3: 微调 Agent 支持 add_control 动作
- [x] M4: 前端补充 LayoutJsonData 快照类型
- [x] M5: 新增测试并全量验证
- [x] 修复: sides 字符串形式支持
- [x] 新增: swap 换位动作

## 进展

- M1 完成：新建 model/layout_tools/control_size.py（resolve_control_size/resolve_role/material_map/find_material/match_material/MissingMaterialError），安全区算法移入 geometry.content_rect_of_canvas，compute_position.py 改为复用新模块，保留 _fit_size 兼容别名。
- M2 完成：model/layout_agent.py generate() 在 out.a["layout.materials"] 写入素材快照（复用布局现有过滤规则，同名保留第一项）。
- M3 完成：model/refine_agent.py 支持 add_control 动作：
  - 提示词包含快照精确素材名与 add_control 规则；动作协议校验（独占字段、candidates ≤5、sides 结构）。
  - 放置：轴对齐矩形、与锚点对应边 40px、垂直中心对齐、安全区（复用 content_rect_of_canvas）、其他业务控件避障 ≥40px、1% 步长 100%→50% 缩放、成对统一比例、舍入后重验证。
  - 新节点：c=ht.Node、ID 递增、layout.node=refine_<ID>、group/instance 继承锚点（缺失回退 refine_group_<锚点ID>/1）、materialName/sourceWidth/sourceHeight、不写 panel.list；displayName 全画布唯一（名称2、名称3…）；contentRect add/replace；message 由后端生成（素材名+方位+缩放比例）。
  - 业务拒绝（未单选/多选/点名/缺方位/非法方位/歧义/素材不在快照/无快照/混用/空间不足）→ 空 patch + 中文 message；快照结构非法 → 422；模型协议错误 → 502。
- M4 完成：web/scada/src/types/layout.ts 增加 LayoutMaterial 与 a["layout.materials"]；前端 applyOpImmutable 已支持 /d/- 与 contentRect patch，无需其他改动。
- M5 完成：新增 tests/test_refine_add_control.py（33 个用例，含布局快照写入）与 web/scada/tests/refineStoreAddControl.test.ts（4 个用例）。全量验证：ruff check . 通过、pytest 303 passed、npm test 127 passed、npm run lint 通过、npm run build 通过。
- 修复：模型常以字符串形式返回 sides（如 "right" 而非 ["right"]），原协议校验直接 502。现接受字符串单方位（自动归一化为数组），非法字符串方位仍走业务拒绝（200 + 空 patch + 中文说明），其他类型仍为 502。新增 test_sides_string_accepted_as_single_side，全量 309 passed。
- 新增 swap 动作：交换两个控件位置（互换 x/y，尺寸不变，关联标签跟随，越界 clamp 到画布）。_ACTION_FIELDS/_validate_action（恰 2 目标、字段精确）/ _apply_actions / _build_prompt 均已扩展。tests/test_refine_align_swap.py 新增 7 个 swap 用例（含协议错误与越界 clamp），全量 327 passed。
