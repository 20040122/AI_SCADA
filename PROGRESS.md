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
- 多选同类批量添加（PLAN.md）完成：
  - model/refine_agent.py：_apply_add_control 重构为分发器，拆出 _apply_single_add（单选路径行为逐字不变）与 _apply_batch_add（2～20 个锚点批量）。
  - 校验：target_ids 与当前选择按集合完全一致（顺序无关），>20 返回空 patch + 确定性中文原因；同类定义为所有锚点 p.image 非空且区分大小写完全相等，异类/缺失返回空 patch；路由层重复 selected_node_ids 422 保持不变。
  - 批量规划：50% 最小尺寸下按画布顺序（d 中出现顺序）逐锚点确定方位，单侧回退顺序固定（左→右→上→下等四组），双侧整对旋转（左右↔上下），只改失败锚点；已规划节点立即成为后续锚点障碍，锚点自身不作为障碍；方位确定后 100%→50% 搜索整批统一最大缩放，每个候选比例重新验证全部新增节点间及与原控件间距；任一锚点全部方向不可行则整批空 patch。
  - 节点：ID 从当前最大 i+1 按画布顺序×方位顺序连续分配，displayName 全画布唯一，每个节点继承对应锚点 layout.group/layout.instance（缺失沿用回退），单次 contentRect 更新。
  - 消息：批量成功含锚点数量、新增节点总数、素材名、统一缩放、换向明细（无换向时说明全部按请求方向放置）；失败说明未生成任何节点并给出失败类型，空间失败列出无法安排的锚点 ID；不输出逐节点坐标。
  - 提示词：add_control 示例加入多选，明确禁止缩减目标集合、加入未选控件或为不同锚点选择不同素材。
  - 测试：tests/test_refine_add_control.py 调整 2 个旧用例（无选择/多选异类），新增 17 个批量用例（单侧 2 节点、双侧 2N、异类/缺 image 拒绝、20 成功 21 拒绝、目标子集/超集/非选中拒绝、顺序无关按画布顺序、统一缩放、50% 不换向、单侧回退只改失败锚点、左右↔上下整对旋转、画布顺序避让 40px、全部回退失败整批空、确定性 ID/命名/元数据/单次 contentRect、消息明细）；tests/test_routes.py 新增重复 selected_node_ids 422 用例；web/scada/tests/refineStoreAddControl.test.ts 新增 3 个批量用例（多 /d/- 追加、预览/接受/撤销保留全部锚点选择与管线）。
  - 验证：ruff check . 通过；pytest 335 passed（9 个 test_canvas_upload 失败为外部 DaoSCADA 服务 daoscada.local 不可达的环境问题，与本次改动无关）；npm test 130 passed；npm run lint 通过；npm run build 通过。
