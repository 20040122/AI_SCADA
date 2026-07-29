# PLAN.md — Model 工具模块迁移

  ## 目标与最终决策

  将实现完整迁移到现有空目录：


   旧路径                          新路径
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   model/search_service.py         model/control_tools/search_service.py
  ──────────────────────────────  ───────────────────────────────────────────
   model/compute_position.py       model/layout_tools/compute_position.py
  ──────────────────────────────  ───────────────────────────────────────────
   model/get_background.py         model/layout_tools/get_background.py
  ──────────────────────────────  ───────────────────────────────────────────
   model/get_connection.py         model/layout_tools/get_connection.py
  ──────────────────────────────  ───────────────────────────────────────────
   model/get_intent.py             model/layout_tools/get_intent.py
  ──────────────────────────────  ───────────────────────────────────────────
   model/layout_intent_rules.py    model/layout_tools/layout_intent_rules.py

  最终决策：

  - 彻底迁移，不保留旧路径转发模块；六个旧导入路径必须不可用。
  - 保持函数、类型、异常、HTTP API、JSON 结构及业务行为不变。
  - 保留新路径 CLI；compute_position 支持 python3 -m model.layout_tools.compute_position，不新增原本就不支持的直接文件执行兼容。
  - get_background 保留模块和直接文件执行能力，输出仍为仓库根目录下的 data/bg_ir.json。
  - 不新增 __init__.py 或包级重导出，沿用项目现有 Python 3.9 namespace package 结构。
  - 不重构业务逻辑，不处理 refine_tools、validate_tools 或其他模块。
  - 不读取或修改 docs/，新增代码不包含注释。

  ## 实现变更

  - 使用文件移动保留当前内容和 Git 历史。当前 get_intent.py 已由 generate_gird.py 重命名而来，必须继续保留这条变更链；不得 reset、restore 或覆盖现有工作
    区修改。

  - 将所有仓库内导入改为新路径：
      - model/control_agent.py、app/deps.py 改用 model.control_tools.search_service，确保 _chunk 仍只有一个模块级状态实例。
      - model/layout_agent.py 的顶部和延迟导入改用 model.layout_tools。
      - app/routers/canvas.py、app/routers/validate.py 改用新的布局工具异常和类型路径。
      - compute_position.py 改从新路径导入 get_intent。
      - get_intent.py 的延迟导入改为新路径下的 layout_intent_rules。
      - 更新测试中的旧导入；保留 model.generate_gird 不可导入的既有约束。

  - 修复移动引起的资源根目录变化。在需要资源定位的模块内，以 Path(__file__).resolve().parents[2] 作为仓库根目录：
      - get_background.py 继续读取根目录 layout/lt*.json，CLI 继续写入根目录 data/bg_ir.json。
      - get_intent.py 继续定位根目录 layout/intent.json。
      - compute_position.py 的相对素材路径回退继续从仓库根目录解析。

  - 不改变 settings.layout_config_path、当前工作目录相对 CLI 参数、默认输出目录或数据库行为。

  ## 接口与兼容约束

  - 以下新模块路径是唯一受支持的 Python 接口：model.control_tools.search_service 与 model.layout_tools.*。
  - 六个旧模块路径均为已接受的破坏性变更，不得通过 sys.modules、转发文件或包级重导出恢复。
  - 所有既有公开函数、数据模型和异常名称保持不变，包括搜索、布局意图、坐标计算、背景生成和连接生成接口。
  - /api/canvas/layout、/api/canvas/refine、/api/validate 的状态码映射和响应契约不得改变。
  - 不触碰 PROGRESS.md 及其他无关脏文件；编辑已有改动文件时只调整本迁移所需内容。

  ## 测试与验收

  - 更新导入测试，验证六个新模块均可导入，app.main、ControlAgent、LayoutAgent 仍可导入。
  - 在独立解释器中验证六个旧模块路径均抛出 ModuleNotFoundError，避免模块缓存造成假通过。
  - 验证 app.deps 与 control_agent 引用同一个新 search_service 模块及其函数，防止 _chunk 状态分裂。
  - 从临时工作目录测试：
      - generate_layout 能读取固定尺寸模板并执行非模板尺寸缩放。
      - compute_position 仍能从仓库根目录解析相对 JSON 素材。
      - get_intent 的可选示例路径仍指向根目录 layout/intent.json。

  - 验证新 CLI：
      - python3 -m model.layout_tools.compute_position --help 返回 0。
      - 使用 mock 输入和 mock Path.write_text 执行 get_background 的模块及直接文件入口，确认目标路径和输出行为，不产生真实仓库文件。

  - 运行 codegraph sync .，检查所有调用方已指向新模块，且不存在旧导入边。
  - 使用 Python 3.9 运行 python3 -m pytest -q，现有 31 个基线测试及新增回归测试必须全部通过。
  - 修改代码后运行 ruff check model app tests，必须返回 All checks passed!。
  - 最终检查 Git diff：六个文件已移动、旧文件不存在、无兼容包装、无 docs/ 或无关改动丢失。

  ## 风险记录

  - 仓库外若仍导入旧模块将立即失败；这是已明确接受的兼容性破坏。
  - 单纯修改 import 会遗漏 __file__ 路径深度变化，必须完成资源路径测试后才能验收。
  - 当前工作区并非干净状态；移动操作必须基于现有文件内容进行，尤其不得丢失 get_intent.py、compute_position.py、路由和导入测试中的已有修改。
  - 测试与 Ruff 当前基线均通过；迁移完成后任何失败均视为本次变更引入，不接受以“既有问题”为由跳过。