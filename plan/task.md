# Canva Agent 布局语义保真改进任务

## 背景

当前 `model/canva_agent.py` 的布局链路更偏向“区域占位”，能够保证整体分布方向大体符合意图，但不能稳定保证每个控件的最终坐标严格体现细粒度语义关系。主流程的覆盖顺序是：

1. `layout()` 在 Step0 抽取 hints / DSL / placements，见 `model/canva_agent.py:1253`
2. DSL 仅被压缩为 `region_map`，见 `model/canva_agent.py:1264`
3. `_generate_skeleton()` 基于 region 生成 zone，见 `model/canva_agent.py:1303`
4. `_compute_coordinates()` 在 zone 内二次排布，见 `model/canva_agent.py:1309`
5. `_scale_to_canvas()` 与 `_clamp_nodes_to_canvas()` 再做全局缩放和回收，见 `model/canva_agent.py:1316`

这条链路里，语义信息在多个阶段被逐步“离散化”为区域、锚点和兜底几何规则，导致用户意图只能以粗粒度落地。

## 主要问题归因

### 1. 意图抽取过粗，且清洗过严

- `_extract_placement_hints_from_query()` 只在控件名附近 `±8` 字符窗口内寻找方位词，无法覆盖跨短句、并列描述、相对关系和修饰语，见 `model/canva_agent.py:229`
- `_sanitize_placement_hints()` 仅接受“目标名完全命中 + region 可标准化”的 hint，所有模糊表达、别名、相对位置都被直接丢弃，见 `model/canva_agent.py:267`
- 当前 `PlacementHint` 只有 `target` 和 `region` 两个字段，无法承载“相对谁”“距离多近”“是否必须对齐”“优先级多高”等信息

### 2. DSL 语义被压缩成 region，空间关系丢失

- `_graph_to_region_map()` 将拓扑层和层内位置映射成 `left/right/top/bottom/center`，仅保留粗区域，不保留节点之间的顺序、间距、对齐和紧凑度，见 `model/canva_agent.py:489`
- dotted edge 只会触发固定区域覆写，不能表达“附属控件贴靠主控件右上角”这类关系，见 `model/canva_agent.py:552`

### 3. 约束求解被固定锚点替代

- `_apply_layout_constraints()` 先按 region 聚类，再按 `REGION_ANCHORS` 投放到预设锚点，zone 宽高只由控件尺寸和固定 padding 估算，见 `model/canva_agent.py:623`
- 这一阶段没有使用成对约束、对齐线、最小间距、组内紧凑度、组间分离度等更细的布局语义

### 4. zone 内部再次重排，覆盖原始语义顺序

- `_apply_layout_constraints()` 会先调用 `_sort_controls_for_region()` 重排同区控件，见 `model/canva_agent.py:637`
- `_compute_coordinates()` 在 zone 内按“少量元素垂直堆叠 / 大量元素自动分列”的固定规则布局，见 `model/canva_agent.py:675`
- 这一步并不区分“用户语义顺序”“DSL 顺序”“视觉阅读顺序”，因此即使上游识别到意图，也可能被内部排版覆盖

### 5. 后处理继续弱化语义约束

- `_scale_to_canvas()` 会整体缩放并重新居中内容，见 `model/canva_agent.py:776`
- `_clamp_nodes_to_canvas()` 会把越界节点强行夹回画布，可能破坏相邻关系
- 当控件数大于 20 时，`_compute_coordinates()` 直接切换到 `_force_directed_layout()`，只保留“吸向 zone 中心”的弱约束，见 `model/canva_agent.py:684` 和 `model/canva_agent.py:829`

## 改进目标

1. 让布局链路从“区域驱动”升级为“约束驱动”，保留更多细粒度语义直到最终坐标生成。
2. 让 query 与 DSL 中的空间关系都能进入统一的中间表达，而不是过早退化为 region。
3. 让缩放、纠偏、回退布局尽量保持原有关系，而不是在后处理阶段重写结果。
4. 为语义保真建立可回归验证指标，而不是只检查是否越界或重叠。

## 非目标

- 本任务不追求一次性引入复杂通用 CAD/自动排版引擎。
- 不要求彻底移除 region 概念；region 可以保留为初始化信号，但不能再是唯一语义载体。
- 不要求第一阶段就依赖 LLM 微调解决所有布局问题；核心约束需要可解释、可回归。

## 方案设计

### 一、升级意图中间表达

新增统一的 `LayoutConstraint` / `SpatialIntent` 结构，替代当前仅有 `PlacementHint(target, region)` 的表达。建议至少支持以下类型：

- `absolute_region`: 绝对区域偏好，如左上、底部中间
- `relative_position`: 相对位置，如 A 在 B 左侧、C 贴近 D 下方
- `alignment`: 左对齐、中心对齐、顶部对齐、基线对齐
- `spacing`: 紧凑、均匀、保持固定间距、避免过远
- `grouping`: 同组聚合、主从绑定、控制按钮附着主设备
- `ordering`: 从左到右、从上到下、先后顺序
- `priority`: hard / soft 约束和权重

同时为每条约束保留：

- `source`: `query` / `dsl` / `fallback_rule`
- `source_span` 或原始片段，便于调试
- `confidence`
- `target_ids` / `anchor_ids`

### 二、重写意图抽取与清洗逻辑

#### 2.1 `_extract_placement_hints_from_query()` 升级为多关系抽取

- 从“控件名附近小窗口匹配”改为“基于短句/分句的关系解析”
- 支持从整句中提取“目标 + 参照物 + 关系 + 程度词”
- 支持控件别名、重复控件实例、同义表达和省略主语
- 对无法直接标准化为 region 的表达，保留为 soft constraint，而不是直接丢弃

#### 2.2 `_sanitize_placement_hints()` 升级为约束归一化

- 从“过滤器”改成“归一化器”
- 目标不完全命中时，尝试做别名映射、模糊匹配、节点实例展开
- region 无法标准化时，不丢弃整个 hint，而是降级成待求解的相对约束
- 对重复约束做冲突合并和优先级裁决，而不是简单去重

### 三、让 DSL 保留空间关系而不是只产出 region

#### 3.1 `_graph_to_region_map()` 拆分职责

将其重构为两层：

1. `graph -> initial_order / grouping / pairwise_constraints`
2. `constraints -> coarse_seed_regions`

保留以下 DSL 语义：

- 层间先后顺序
- 层内相对顺序
- dotted / attached 边的主从依附关系
- 同层节点的紧凑排列需求
- 图方向对布局主轴的约束

`region_map` 可以继续存在，但只能作为初始化，不再是 DSL 的最终投影。

### 四、用约束求解替代固定锚点 zone 投放

#### 4.1 `_apply_layout_constraints()` 重构为“初始化 + 求解”

建议输出从 `list[LayoutZone]` 升级为：

- `seed_zones`: 粗区域初始化结果
- `constraint_graph`: 布局约束图
- `placement_state`: 当前求解状态

第一阶段可以采用“启发式 + 局部优化”的轻量方案：

- 用 region 生成初始位置
- 用组约束和相对位置约束做迭代修正
- 用对齐/间距规则做二次优化
- 用最小位移原则解决冲突

后续如果需要，再替换为更系统的约束求解器。

#### 4.2 zone 不再是语义终点

- zone 应仅代表布局簇或初始边界
- zone 内节点位置应由约束决定，而不是统一套用垂直堆叠/自动分列
- zone 的宽高应根据组内相对结构反推，而不是仅根据总高和最大宽估算

### 五、重构 `_compute_coordinates()`，保留语义顺序

重点改动：

- 输入改为“骨架 + 约束 + 顺序信息”，而不只是 skeleton zone
- 禁止无条件按 region 规则重排控件
- 将“阅读顺序”“DSL 顺序”“语义附着顺序”显式区分
- 引入主轴和副轴布局
- 支持组内横排、纵排、网格、附着、环绕等基本模式

建议在节点输出前增加一次“语义一致性检查”，例如：

- A 是否仍在 B 左侧
- 从属按钮是否仍贴近主控件
- 同组元素是否被异常拉开

### 六、弱化破坏性后处理

#### 6.1 `_scale_to_canvas()` 改为保关系缩放

- 缩放时同时考虑节点尺寸和节点间距
- 避免“先居中再夹紧”导致边界节点关系改变
- 优先整体平移，其次等比缩放，最后才局部修正

#### 6.2 `_clamp_nodes_to_canvas()` 改为最小扰动修正

- 记录每次修正的位移量
- 如果某次修正破坏 hard constraint，触发局部重算而不是直接夹回
- 输出 debug 信息，便于定位哪些规则导致布局失真

### 七、收敛大规模场景回退策略

当前 `>20` 直接切到 `_force_directed_layout()` 过于激进。建议改成分层退化：

1. 优先使用“约束驱动布局 + 稀疏求解”
2. 仅对局部簇使用力导向分散，保留簇间主关系
3. LLM 微调只做最终微调，不负责恢复核心拓扑语义

`_force_directed_layout()` 如果保留，至少需要增加：

- 组内吸引力
- 关键相对边约束
- 对齐与最小间距项
- 可重复、可解释的代价函数

## 实施拆分

### Phase 1：语义表达升级

- 新增约束数据结构与序列化调试输出
- 保留 `PlacementHint` 兼容层，但内部统一转换到新约束模型
- 重写 query hint 提取与 sanitize 流程

### Phase 2：DSL 保真

- 重构 `_graph_to_region_map()`，拆出 pairwise / grouping / ordering 约束
- 调整 `layout()` 主流程，让 DSL 与 query 意图汇合到同一约束集

### Phase 3：坐标求解重构

- 重构 `_apply_layout_constraints()` 与 `_compute_coordinates()`
- 用“初始化 + 迭代修正 + 最小扰动冲突消解”替换固定锚点和硬编码堆叠

### Phase 4：后处理与回退收敛

- 重写 `_scale_to_canvas()` / `_clamp_nodes_to_canvas()` 的修正策略
- 调整 `>20` 的回退路径，避免直接进入弱语义力导向布局

### Phase 5：验证与观测

- 为每一步输出可调试中间结果
- 建立回归样例和语义评分指标

## 验收标准

### 功能验收

- 细粒度描述不会因为目标名不完全匹配或 region 无法标准化而直接丢失
- DSL 中的层次、顺序、依附关系在最终坐标上可观察
- zone 内部布局不再无条件覆盖语义顺序
- 大于 20 个控件时仍能保留核心拓扑关系

### 指标验收

- 相对位置命中率：例如 “A 在 B 左侧” 的满足率
- 对齐命中率：例如同组左对齐/中心对齐满足率
- 组内紧凑度：组内平均距离 / 组间平均距离
- 约束破坏率：后处理阶段新增的违规数量
- 回退一致性：普通布局与大规模布局在核心关系上的一致度

## 测试建议

- 为 `_extract_layout_intents()`、`_sanitize_placement_hints()`、`_graph_to_region_map()`、`_compute_coordinates()` 增加单测
- 增加 query -> constraints -> coordinates 的端到端 golden case
- 覆盖以下典型表达：
  - “A 放左上，B 紧贴 A 右侧，C 在 B 下方”
  - “主设备居中，控制按钮放在其右上角”
  - “左侧一列展示传感器，右侧一列展示执行器”
  - “底部横向排布告警相关控件，间距紧凑”
  - “超过 20 个控件但仍要求按区域分组”

## 风险与注意事项

- 新旧数据结构并存期间，注意兼容 `layout()` 输出和前端消费格式
- 约束过多时，求解耗时可能上升，需要控制迭代次数和退化策略
- 若缺少调试输出，后续会很难定位“语义丢失发生在哪一步”
- 当前 `model/canva_agent.py` 已有未提交改动，实施时需避免与现有变更冲突

## 建议落地顺序

优先做“中间表达 + 主流程串联 + 可观测性”，再做求解器重构。原因是如果没有统一约束模型和中间态输出，即使替换布局算法，也无法稳定判断语义到底丢失在抽取、映射、求解还是后处理阶段。
