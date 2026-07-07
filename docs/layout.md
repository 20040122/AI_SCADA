借鉴 NDN 的“关系图 → 粗布局 → 精修”，图是内部的布局约束图。

## 一、总体流程

```text
阶段0：控件标准化
          ↓
阶段1：布局关系图构建
          ↓
阶段2：分组级、控件级粗布局
          ↓
阶段3：确定性几何精修
          ↓
阶段4：择优与结果输出
```
NDN 三阶段：
1. 关系预测
2. 初始布局
3. 几何精修
---

## 二、统一数据模型

### 1. 布局节点

节点既可以是单个控件，也可以是控件组。

```json
{
  "id": "pressure_1",
  "node_type": "control",
  "control_type": "gauge",
  "role": "indicator",
  "width": 120,
  "height": 120,
  "priority": 70,
  "group_id": "pump_unit_1",
  "locked": false,
  "resizable": true
}
```

控件组节点：

```json
{
  "id": "pump_unit_1",
  "node_type": "group",
  "group_type": "equipment_unit",
  "members": ["pump_1", "pressure_1", "switch_1"],
  "priority": 90,
  "preferred_strategy": "anchor"
}
```

### 2. 布局关系边
明确的布局关系：
```json
{
  "source": "pressure_1",
  "target": "pump_1",
  "relation": "right_top_of",
  "priority": "hard",
  "source_type": "user",
  "confidence": 1.0,
  "params": {
    "gap": 16
  }
}
```
关系类型：
- 空间关系：`left_of`、`right_of`、`above`、`below`、`near`
- 对齐关系：`align_left`、`align_center_x`、`equal_spacing`
- 层级关系：`inside`、`belongs_to`、`attached_to`

`monitors`、`controls` 等业务关系不能直接决定坐标，应先转换成布局关系。例如：

```text
压力表 monitors 水泵
→ 压力表 attached_to 水泵
→ 优先放在水泵右上侧
```

---

## 三、阶段0：控件标准化

### 输入

- 用户描述
- 控件列表
- 画布尺寸
- 控件业务属性
- 原有位置
- 工程配置关系

### 处理

- 生成唯一实例ID。
- 补齐缺失尺寸和最小尺寸。
- 识别控件角色。
- 识别锁定控件。
- 识别重复单元。
- 将用户明确要求转换为硬约束。
- 将已有布局转换为稳定性约束。

### 输出

```text
LayoutContext
├── canvas
├── nodes
├── explicit_relations
├── groups
└── layout_policy
```

这一阶段不调用AI。

---

## 四、阶段1：布局关系图构建与补全

这是对 [layout.md](/Users/zhangchangming/Documents/Code/SCADA/layout.md:8)“关系预测阶段”的工程化落地。

### AI负责的内容

AI只处理语义层：

- 判断场景类型。
- 补充分组。
- 识别主设备与附属控件。
- 补充必要的相对位置关系。
- 选择候选布局策略。
- 识别用户描述中的软约束。

AI输出示例：

```json
{
  "scene_type": "equipment_overview",
  "groups": [
    {
      "id": "pump_units",
      "members": ["pump_unit_1", "pump_unit_2"],
      "strategy": "grid"
    }
  ],
  "inferred_relations": [
    {
      "source": "alarm_panel",
      "target": "canvas",
      "relation": "in_region",
      "value": "right_top",
      "priority": "soft",
      "confidence": 0.85
    }
  ],
  "candidate_styles": [
    "balanced",
    "compact"
  ]
}
```

### 关系补全原则

不生成全连接图，只补充必要关系：

- 每个节点一个所属分组关系。
- 每个附属控件一个锚点关系。
- 每个有顺序的集合一个排序关系。
- 每个分组少量区域、对齐关系。
- 没有依据的关系不推断。

因此关系规模维持在 `O(n+k)`，而不是 `O(n²)`。

### 约束优先级

```text
用户硬约束
> 锁定位置
> 工程配置
> 控件固有属性
> AI推断
> 默认规则
```

AI推断只能补充软约束，不能覆盖用户和工程硬约束。

---

## 五、阶段2：粗布局生成

对应 [layout.md](/Users/zhangchangming/Documents/Code/SCADA/layout.md:11) 的 Bounding Box 初生成，但不要求神经网络直接预测所有坐标。

采用两级布局。

### 1. 分组级布局

先估算每个组所需面积：

```text
组面积 ≈ Σ控件面积 ÷ 目标填充率 + 间距 + 内边距
```

放置顺序：

1. 锁定区域
2. 标题、报警等固定功能区
3. 大型主设备组
4. 高频监控区
5. 操作区
6. 次要指标和辅助控件

组级策略：

| 场景 | 策略 |
|---|---|
| 仪表盘 | Grid/Flex |
| 大小混合区域 | MaxRects |
| 重复设备单元 | Matrix |
| 主设备总览 | 主区域＋侧栏 |
| 报警中心 | 固定顶部或右侧区域 |

### 2. 组内布局

根据 `group_type` 路由：

- `equipment_unit`：锚点模板
- `metric_group`：自适应网格
- `operation_group`：横排或竖排
- `chart_group`：卡片布局
- `repeated_unit`：模板生成后复制
- `mixed`：大控件优先装箱

例如泵组：

```text
压力表 → 锚定在水泵右上
开关   → 锚定在水泵右侧
状态灯 → 锚定在水泵顶部
名称   → 锚定在水泵下方
```

这种关系图表达的是布局拓扑，不是业务流程。

### 3. 多候选方案

借鉴 [layout.md](/Users/zhangchangming/Documents/Code/SCADA/layout.md:14) 的多样性思想，初期不必直接引入CVAE，可以生成少量确定性候选：

- `compact`：空间利用率优先
- `balanced`：留白和对称优先
- `operation_focused`：操作控件优先
- `monitoring_focused`：指标和报警优先

每个候选使用不同模板、方向或间距参数。

---

## 六、阶段3：确定性几何精修

对应 [layout.md](/Users/zhangchangming/Documents/Code/SCADA/layout.md:18) 的“语义与几何解耦”。

AI不再负责逐像素微调，改由约束求解器完成。

### 精修顺序

1. 强制满足锁定和区域硬约束。
2. 修复越界。
3. 修复控件重叠。
4. 修复组间重叠。
5. 执行对齐和等间距。
6. 执行像素网格吸附。
7. 平衡画布留白。
8. 尽量靠近原有位置。

### 目标函数

```text
硬约束违反 → 方案直接失败

软约束成本 =
    相对位置违反
  + 对齐误差
  + 间距误差
  + 分组离散度
  + 留白不均衡
  + 与原布局的位移
```

碰撞检测应使用空间哈希或R-tree，只检查邻近节点。

修复时优先移动：

```text
未锁定节点
→ 低优先级节点
→ 附属节点
→ 整个低优先级分组
```

如果仍无法满足：

1. 降低软约束。
2. 缩小可缩放控件。
3. 调整组排列。
4. 扩展画布。
5. 返回不可满足约束。

---

## 七、阶段4：评分与择优

每个候选计算：

- 硬约束满足率
- 重叠面积
- 越界数量
- 用户约束满足率
- 对齐程度
- 间距一致性
- 分组紧凑度
- 画布利用率
- 布局稳定性

建议先排除所有硬约束失败方案，再从剩余方案选择总分最高者。

质量检测由当前“只报告问题”升级为：

```text
检测 → 局部修复 → 重新检测 → 评分
```

---

## 八、与当前 `canva_agent.py` 的概念映射

| 当前设计 | 新设计 |
|---|---|
| `FlowGraph` | `LayoutRelationGraph` |
| `GraphEdge solid/dotted` | 具体空间、对齐、层级关系 |
| `LayoutIntents.flow_dsl` | 删除 |
| `placement_hints` | 转换成 `in_region` 约束 |
| `LayoutConstraint` | 保留并扩展，成为核心输入 |
| `LayoutSkeleton` | 保留，表示组级粗布局 |
| `_compute_coordinates` | 改为策略路由器 |
| `_refine_layout_with_llm` | 改为确定性几何精修 |
| `_quality_check` | 改为检测、修复、复检闭环 |

当前的 `LayoutConstraint` 已经具备类型、目标、锚点、来源和置信度等基础字段，[canva_agent.py](/Users/zhangchangming/Documents/Code/SCADA/model/canva_agent.py:197) 可以直接作为关系图边模型的基础。

## 最终职责边界

```text
AI：
场景识别、语义分组、关系补全、候选策略

布局引擎：
面积计算、粗坐标、约束求解、碰撞修复、质量评分

输出层：
转换为HT Canvas JSON
```

这套设计保留了 `layout.md` 的“先定关系、再定几何、最后精修”，同时避免重新引入任何流程图DSL。未改动代码。