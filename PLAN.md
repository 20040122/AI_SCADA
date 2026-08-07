  # PLAN.md — 二列 CSV 驱动的可扩展绑定 Agent 重构

  ## 1. 目标与边界

  将绑定流程调整为：

  严格二列 CSV → 后端 BindingAgent 匹配 → 用户逐行确认 → 后端原子构建 → Schema 校验 → 手动上传

  必须完成：

  - CSV 固定为 displayName,propertyName。
  - binding.jsonl 成为完整绑定元数据的唯一真源。
  - 匹配、排序和构建编排实现在 model/binding_agent.py。
  - 建立控件绑定处理器注册机制，本次只实现状态面板处理器。
  - 保留“预览→匹配→逐行确认→生成”流程。
  - 删除旧 CSV、列映射和 normalize 兼容逻辑。

  本次不做：

  - 不实现第二种控件处理器。
  - 不兼容旧多字段 CSV 或旧绑定 API 请求。
  - 不支持 JSONL 热重载，修改后必须重启。
  - 不实现批量确认、自动确认或清空未列控件。
  - 不调用 LLM 或远端服务进行匹配。

  ## 2. 数据与 API 契约

  ### CSV

  只接受以下固定表头和顺序，不允许额外列、换序或别名：

  displayName,propertyName
  状态面板,空气罐温度
  状态面板,空气罐压力

  规则：

  - 仅接受 .csv，延续 UTF-8、UTF-8 BOM、GB18030。
  - 延续 5 MB、10,000 行限制；完全空白行忽略。
  - 表头必须精确等于 displayName,propertyName。
  - 数据值去除首尾空白，任一字段为空即整批阻断。
  - 行列数不是 2 或重复出现相同 displayName+propertyName 时整批阻断。
  - 保留物理行号和原始行序；状态面板生成的 panel.list 按 CSV 顺序排列。
  - 预览响应返回全部规范请求，前端只展示前 20 行。
  - 删除列映射 UI、/api/binding/csv/normalize 及对应类型和状态。

  POST /api/binding/csv/preview 返回：

  encoding
  total_rows
  requests[]:
    row_number
    displayName
    propertyName

  格式、编码和容量错误分别返回 422 或 413。

  ### binding.jsonl

  每行保存规范字段，由处理器派生 path/key/label，不再保存 required、property、样例 path 或样例 label。

  目标内容：

  {"id":"air_tank_temperature","handler":"panel_list","displayName":"状态面板","propertyName":"空气罐温
  度","projectId":"2084524131092914178","projectName":"Agent","deviceId":"2084937599679848450","deviceName":"空气
  罐","propertyId":"2084940408848506881","dataType":"int","dataTypeDesc":"整型","writable":false,"unit":"°C"}
  {"id":"air_tank_pressure","handler":"panel_list","displayName":"状态面板","propertyName":"空气罐压
  力","projectId":"2084524131092914178","projectName":"Agent","deviceId":"2084937599679848450","deviceName":"空气
  罐","propertyId":"2084940512418455554","dataType":"double","dataTypeDesc":"双精度","writable":false,"unit":"MPa"}

  启动时一次性加载并校验：

  - 所有字段必填，unit 可为空。
  - 三类 ID 必须为数字字符串。
  - dataType 仅允许 double/int/bool/string。
  - writable 必须是布尔值。
  - id 全局唯一。
  - 同一 handler+displayName+projectId+deviceId+propertyId 不得重复。
  - 同名 propertyName 对应不同数据源允许存在，作为人工选择候选。
  - handler 必须已注册。
  - 配置错误直接阻止应用启动。
  - 启动时缓存目录和属性向量；修改 JSONL 后重启生效。

  ### 匹配和构建 API

  保留以下端点名称，但使用破坏性的新模型：

  - POST /api/binding/match
  - POST /api/binding/build

  匹配请求：

  json_data
  requests[]:
    row_number
    displayName
    propertyName

  匹配响应：

  targets[]:
    node_i
    node_id
    displayName
    handler
    existing
  items[]:
    row_number
    target_node_i
    requested_displayName
    requested_propertyName
    candidates[]
    suggested_binding_id
    lead
    confidence
  blocked
  errors[]

  候选只由后端生成，至少包含：

  binding_id
  propertyName
  projectName
  deviceName
  dataType
  writable
  unit
  score
  evidence

  构建请求：

  json_data
  requests[]
  assignments[]:
    row_number
    binding_id

  客户端不得回传完整绑定对象、目标节点索引或自行计算的评分。后端根据原请求重新定位目标、重新验证候选资格，并从当前 JSONL 读取权威元数据。

  构建预览改为通用结构：

  node_i
  displayName
  handler
  before
  after

  请求 Schema 错误返回 422；合法请求中的目标缺失、无候选、未确认或构建冲突通过业务错误返回，bound_json 必须为 null。

  ## 3. 后端设计

  ### BindingAgent

  在 model/binding_agent.py 中实现：

  - BindingAgent 生命周期和注册表索引。
  - 属性候选计算、排序、阈值、置信度和证据生成。
  - 请求完整性复核、目标分组、处理器分发和原子构建编排。
  - 可注入相似度实现，方便测试。
  - 实际评分逻辑不得继续委托给 app/services/match_service.py。

  CSV 解析和 JSONL 校验可以保留为后端辅助模块；控件写入逻辑由处理器负责。旧 match_service.py 和 build_service.py 的业务入口应退役，路由通过依赖注入调用
  BindingAgent。

  在应用启动生命周期中初始化 _binding_agent 并提供 get_binding_agent。路由保持薄层，只负责请求模型、异常映射和响应序列化。

  ### 处理器注册表

  定义通用绑定处理器协议：

  - handler_id
  - 判断并规范化支持的 displayName
  - 校验目标节点类型
  - 读取旧绑定快照
  - 将已确认目录记录渲染为控件绑定结构
  - 应用到画布副本
  - 执行处理器专属 Schema 校验

  本次只注册 panel_list 处理器：

  - 支持 ^状态面板(?:[1-9]\d*)?$。
  - 状态面板2/3 共享规范目录名 状态面板。
  - CSV 必须写完整目标名；状态面板 不广播到编号面板。
  - 画布目标通过 p.displayName 精确定位，必须恰好找到一个 ht.Node。
  - 相同完整 displayName 存在多个节点时阻断。
  - 写入位置为节点 a["panel.list"]。
  - 对 CSV 中出现的目标整体替换旧 panel.list。
  - 未出现在 CSV 中的控件保持不变；v1 不提供清空语义。
  - 继续使用现有 Binding Schema 校验该处理器输出。
  - 新增其他控件时只需注册新处理器、Schema 和 JSONL 记录，不修改核心匹配流程或 API。

  ### 匹配算法

  每个请求行执行：

  1. 用完整 displayName 精确定位唯一画布节点。
  2. 由处理器将编号状态面板映射到规范目录 状态面板。
  3. 只在相同 handler+规范 displayName 的 JSONL 记录中查找属性。
  4. propertyName 去除首尾空白后完全相等时优先返回精确候选：
      - 唯一精确候选：score=1、高置信、预选但不确认。
      - 多个精确候选：全部返回，suggested_binding_id=null，用户必须明确选择。

  5. 无精确候选时，使用本地 BGE 比较 CSV 与 JSONL 的 propertyName：
      - score 仅为属性名相似度，不再计算设备名权重。
      - 分数四舍五入至 4 位后计算阈值和 lead。
      - 只返回 score >= 0.55 的前 5 项。
      - 排序为 score 降序，再按 binding_id 升序保证稳定。
      - lead 为第一名减第二名；只有一个候选时等于第一名分数。
      - 高置信：score >= 0.85 && lead >= 0.08。
      - 中置信：score >= 0.70 && lead >= 0.05。
      - 低置信：其余 score >= 0.55。
      - 语义候选预选第一名，但仍必须人工确认。

  6. 无候选时记录行级错误并阻断整批构建。

  批量编码未精确命中的唯一查询；目录向量在启动时缓存，避免逐候选重复调用模型。匹配全程使用本地模型，不访问网络。

  ### 构建规则

  - 每个 CSV 行必须有且只有一个 assignment。
  - 后端重新确认 binding_id 属于该行允许的候选集合。
  - 任一行缺失、无效、未确认或目标异常时整批阻断，不生成部分 JSON。
  - 同一目标控件内，同一个 binding_id 被选择多次时阻断。
  - 不同目标控件可以复用任意数据源，包括可写数据源；不因跨控件复用产生错误或警告。这是已接受的操作风险。
  - 深拷贝输入画布，原对象不得修改。
  - 同一目标的绑定项按 CSV 行顺序生成。
  - 非目标节点、布局元数据、管线和未列控件保持不变。
  - 生成后依次执行处理器 Schema 和完整 Canvas Schema；任一失败令 bound_json=null。

  状态面板输出由 JSONL 派生：

  - label = propertyName
  - bind.type = designer
  - bind.path = projectId#deviceId#propertyId
  - bind.key = deviceId#propertyId
  - bind.label = projectName . deviceName . propertyName (unit)
  - unit 为空时不得出现空括号
  - proj/dev/param 全部来自 JSONL
  - 压力输出必须是 double/双精度

  上传继续复用 /api/canvas/upload，默认文件名仍为 _bound.json；生成和上传保持两个独立人工动作。

  ## 4. 前端调整

  - 保留布局稿/已确认微调稿的来源优先级和待确认 Patch 阻断。
  - 删除列映射、规范化结果和旧 BindingProperty 状态。
  - CSV 预览显示编码、总行数、固定表头及前 20 行。
  - Store 保存后端返回的 requests、候选和逐行确认状态。
  - 候选评分、排序、置信度和 suggested 值不得在前端计算。
  - 唯一精确或语义 Top-1 可以预选，但 confirmed 初始始终为 false。
  - 删除“确认全部高置信”；每一行必须单独点击确认。
  - 更换候选时撤销该行确认，并清空已有构建和上传结果。
  - 所有行确认且无阻断错误后才启用生成按钮。
  - 构建时只发送 row_number+binding_id。
  - 来源 revision、CSV 文件或请求列表变化时清除候选、确认、构建和上传结果。
  - 构建预览使用通用 before/after 数据模型；状态面板可以继续提供友好的列表展示。
  - 上传失败保留已生成 JSON，允许原地重试。

  ## 5. 测试与验收

  ### 后端测试

  覆盖：

  - 严格表头、顺序、额外列、缺列、空值、重复行、异常行宽。
  - UTF-8、BOM、GB18030、5 MB、10,000 行和非 CSV。
  - JSONL 必填字段、ID、类型、未知处理器、重复 ID、重复物理源及启动失败。
  - 唯一精确候选、多精确候选不预选、语义 Top-5、0.55 阈值、lead 和稳定排序。
  - 完整名称定位、同名节点阻断、状态面板编号共享目录但不广播。
  - 不支持控件、目标缺失、无候选、缺少 assignment 和伪造 binding_id。
  - 目标内重复数据源阻断；跨控件读写数据源复用允许。
  - 目标绑定整体替换、未列控件保持、CSV 顺序、原画布不变。
  - 无单位标签、压力 double、Schema 失败和原子回滚。
  - 路由新请求/响应以及旧 normalize 接口不存在。

  提交固定真值集，不得再使用 skip：

  - air_tank_temperature：空气罐温度、气罐温度、空气罐温度值、空气罐测温、储气罐温度、空气容器温度、空气罐温度传感器、罐体温度、气罐热度、空气罐当前温度。
  - air_tank_pressure：空气罐压力、气罐压力、空气罐压力值、空气罐测压、储气罐压力、空气容器压力、空气罐压力传感器、罐体压力、气罐气压、空气罐当前压力。

  使用真实本地 BGE 模型验收：

  - 用例数至少 20。
  - Top-1 准确率必须不低于 75%。
  - 最高候选必须通过 0.55 阈值。
  - 当前环境只读实测结果为 20/20，但测试门槛保持 75%。

  ### 前端测试

  覆盖：

  - 新预览、匹配和构建请求体。
  - 不再调用 normalize。
  - 后端 suggested 仅预选、不自动确认。
  - 多精确候选无预选。
  - 必须逐行确认且不存在批量确认。
  - 选择变化使确认和构建失效。
  - 仅发送 binding_id，不发送完整元数据。
  - 来源变化、微调 Patch 阻断、上传失败重试及未修改布局/微调 Store。

  ### 验证命令

  实现后必须执行：

  python3 -m pytest
  cd web/scada && npm test
  cd web/scada && npm run lint
  cd web/scada && npm run build
  python3 -m ruff check .

  代码保持 Python 3.9 兼容，不新增代码注释。

  ## 6. 已接受风险与默认决策

  - API 和 CSV 契约为破坏性变更，不提供兼容层。
  - 多个控件可绑定同一可写物理点，可能造成多入口写控制；按已确认决定不阻断。
  - 编号状态面板共享同一目录，若分别选择相同 binding_id，会显示或控制同一物理点。
  - 真值集只覆盖当前两个空气罐属性；新增目录记录时必须同步扩充真值集，当前 75% 不能代表未来全目录准确率。
  - 10,000 行仍是技术上限，但逐行人工确认不适合超大文件；本次不调整上限或增加批量确认。
  - JSONL 配置错误会阻止整个应用启动，以换取确定性和失败前置。