 # PLAN.md — Schema 校验模块适配方案

  ## 目标与最终决策

  将 Schema 校验改造成四类数据共用的确定性质量门禁，解决规则漏检、前后端漂移、重复加载及 AI 结果自相矛盾问题。

  已确认：

  - 以当前业务模块真实产物为权威。
  - 覆盖 control、canvas、layout、binding 的后端、前端、业务门禁和测试。
  - Schema/Python 规则决定 valid；AI 发现和故障只能产生 warning。
  - AI 仅在确定性校验通过后执行，无重试，最长 10 秒；紧凑 JSON 超过 64 KiB 时跳过并警告。
  - control/layout/binding 拒绝未知字段；canvas 保留 DaoSCADA 扩展字段。
  - binding 同时接受独立 {"panel.list":[]} 和完整 canvas。
  - 空绑定、control 的 0/null 尺寸通过但警告。
  - 不禁止不同目标面板复用同一 binding。
  - 所有生产链路发现确定性错误时阻断无效产物。
  - 不新增 CLI。
  - Python 3.9；新增 Python 代码不写注释；修改后必须执行 Ruff。

  ## 公共接口

  - 保持 POST /api/validate 的请求结构不变。
  - ValidationErrorItem 保留 path/message/error_type，新增 source，取值为 schema | semantic | ai | system。
  - 所有 path 统一为 RFC 6901 JSON Pointer；根路径为 ""。
  - valid 仅在确定性错误列表为空时为 true。
  - summary 由程序生成：通过、错误数和警告数，不使用 AI summary 覆盖。
  - 请求类别或请求类型错误仍返回 HTTP 422；业务数据不合法返回 HTTP 200，data.valid=false。
  - 新增 GET /api/validate/rules，通过 ApiResponse 返回四类规则元数据：
      - category/label/title/description
      - properties[]：path/type/required/description/enum
      - derived_rules[]
      - samples.valid 和 samples.invalid

  - 前端删除手工维护的规则镜像，完全使用该接口；加载失败时显示错误，不回退到可能过期的静态规则。

  ## 实现变更

  ### 统一校验服务

  - 建立单例校验服务，在应用启动时加载三份 Draft-07 Schema，执行 JSON 解析和 Draft7Validator.check_schema；文件缺失或无效直接阻止启动。
  - 统一输出、排序和去重结构化问题，替代路由、布局模块和 BindingAgent 各自的 Schema 缓存。
  - Schema 版本在单进程生命周期内固定，不做热更新。
  - 将结构规则、Python 语义规则、规则元数据和合法/非法示例集中管理，供校验接口、业务门禁和规则接口复用。

  ### 四类规则

  - control：
      - 校验单个 control.jsonl 记录。
      - 必填字段、类型、未知字段、非空名称、symbols/ 或 assets/ 路径、非负尺寸和非负 boundExtend 为硬规则。
      - 负尺寸报错；0/null 尺寸产生 warning。
      - 控件目录初始加载和热更新均使用同一校验器；初始错误阻止启动，热更新错误保留上一快照。

  - canvas：
      - 校验完整 DaoSCADA canvas；要求核心字段、至少一个 layer、正数画布宽高、数组元素包含非空 c 和对象 p。
      - contentRect.width/height 不得为负。
      - 空画布允许零尺寸 contentRect；存在完整几何信息的元素时，contentRect 必须为正并覆盖这些元素。
      - 不限制未声明的 DaoSCADA 扩展字段，也不臆造节点类型枚举。

  - layout：
      - 以现有 LayoutFile/Pydantic 模型为结构权威，所有层级拒绝未知字段，字符串 ID/设备名非空，数量严格为正整数。
      - 保留并统一现有分组、网格容量、附件先声明引用、组引用、循环依赖、库存和 topology 校验。
      - 补充同组节点 ID 重复校验。
      - 规则说明覆盖现有 topology/relativeTo/side/constraints；移除不存在的 connections 和无法从 LayoutFile 判断的尺寸规则。

  - binding：
      - 独立包装对象严格校验所有层级字段、枚举、非空值、数字字符串 ID 和未知字段。
      - Python 规则校验 path/key 与 proj/dev/param ID 一致、展示 label 与名称和 unit 一致、同一面板内 path 不重复。
      - 完整 canvas 先执行 canvas 校验，再遍历所有 d[*].a["panel.list"]；错误路径包含完整节点位置。
      - 未发现绑定或列表为空时只警告；不同目标面板复用 binding 合法。
      - BindingAgent 注册表仍由现有注册表模型校验，不与最终 panel.list Schema 混用。

  ### AI、业务门禁和前端

  - ValidateAgent 仅返回辅助 findings，不再计算最终 valid。
  - 确定性错误存在时不调用 AI；缺少模型配置、超时、响应无效或输入过大时生成对应 AI warning。
  - AI 返回的 errors 和 warnings 全部转换为 source=ai 的 warning；忽略模型返回的 valid。
  - 更新四类 AI 提示，使其与真实数据契约一致，特别移除旧 binding 模型和旧 layout 字段。
  - 布局中间表示校验失败继续走现有模型修正流程；最终 canvas 失败时不得写输出文件或返回结果，由布局路由映射为内部产物校验错误。
  - Binding 构建失败继续返回 bound_json=null 和错误；最终上传校验失败返回 422，并确保不会调用 DaoSCADA。
  - 前端按钮改为“开始校验”，展示 schema/semantic/ai/system 来源标识和统一路径。

  ## 测试与验收

  - Schema 自检：三份 Schema 均符合 Draft-07；损坏、缺失或非法 Schema 会使应用启动失败。
  - 合法回归：
      - data/control.jsonl 全量记录无错误，现有零宽“进度条”仅产生 warning。
      - data/canvas.json 和现有生成画布通过。
      - 当前 LayoutFile 合法样例通过。
      - binding 包装对象及包含多个面板的完整 canvas 通过。

  - 非法回归：
      - 当前前端四类非法例均在不调用 AI 的情况下失败。
      - 覆盖空名称、非法路径、负尺寸、空 layer、非正画布尺寸、越界 contentRect、重复布局 ID、非法引用、旧 binding 结构、ID/path/key 不一致和未知字段。

  - AI 回归：
      - AI 报错不改变 valid=true。
      - 无配置、异常响应、10 秒超时和超过 64 KiB 均产生明确 warning。
      - 确定性错误时断言模型客户端未被调用。

  - API/前端：
      - 校验错误路径全部为 JSON Pointer，source 正确。
      - 规则接口四类数据完整，前端不再依赖静态镜像。
      - 前端合法/非法示例与后端结果一致。

  - 生产门禁：
      - 无效布局不落盘、不返回。
      - 无效 binding 不生成 bound_json。
      - 无效上传不发生外部 HTTP 请求。

  - 修复上传测试的 mock client 注入，禁止测试访问 daoscada.local。
  - 最终验收命令全部通过：
      - python3 -m pytest -q
      - ruff check .
      - npm test
      - npm run build

  ## 风险与边界

  - 更严格的 layout/binding/control 未知字段策略可能暴露既有脏数据，这是预期阻断，不允许静默丢弃。
  - canvas 保留未知字段以兼容 DaoSCADA 扩展，但只保证已声明核心字段和可计算语义。
  - Schema 配置错误会降低服务可用性，但已明确选择启动期失败以避免带病运行。
  - 本次不修改绑定匹配算法、不禁止跨面板复用、不新增 CLI，也不扩展新的 DaoSCADA 节点类型。