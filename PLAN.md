
  # PLAN.md — 清零 Ruff E402

  ## 目标与决策

  当前 ruff check model app tests 报告 10 个 E402：

  - model/generate_gird.py：4 个。
  - model/layout_agent.py：3 个。
  - model/llm_client.py：3 个。

  最终要求：

  - 10 个 E402 全部解决，不设置 noqa，不修改 Ruff 配置绕过检查。
  - 删除模块导入阶段的 sys.path 修改。
  - 保持 FastAPI、布局生成、微调、校验及共享 LLM 行为不变。
  - CLI 改为仅支持 python -m model.layout_agent，不再保证 python model/layout_agent.py 可用。
  - Python 3.9 兼容，新增代码不包含注释。
  - 不读取或修改 docs/，不处理无关工作区改动。

  ## 实现变更

  ### 导入结构

  在以下三个文件中移除 _project_root 和 sys.path.insert：

  - model/generate_gird.py
  - model/layout_agent.py
  - model/llm_client.py

  同时：

  - 删除不再使用的 sys 导入。
  - generate_gird.py 保留仍用于路径计算的 Path。
  - llm_client.py 若不再使用路径对象，则删除 Path 导入。
  - 所有标准库、第三方库和项目模块导入放到模块顶部，并按 Ruff 规则分组。
  - 不使用动态导入、条件导入或 Ruff 豁免来隐藏 E402。
  - 保留 layout_agent.py 在方法内部延迟导入 generate_gird 的现有循环依赖规避方式。

  ### 启动方式

  保持以下入口：

  - 服务：从仓库根目录运行现有 main.py 或 app.main:app。
  - Layout CLI：从仓库根目录运行 python -m model.layout_agent。
  - 库调用：通过 import model.layout_agent 等包导入方式使用。

  不新增包装脚本，也不恢复直接文件执行兼容。

  ## 接口与行为约束

  不得改变：

  - /api/canvas/layout、/api/canvas/refine、/api/validate 契约。
  - default_client、default_model、call_llm 的接口。
  - DeepSeek 环境变量、60 秒默认超时和 Tenacity 重试策略。
  - 布局、连接、内容边界及 Schema 校验结果。
  - model/canva_agent.py 已删除的状态。

  允许的破坏性变化仅限：

  - python model/layout_agent.py 不再是受支持入口。

  ## 测试与验收

  按顺序执行：

  1. 运行 ruff check model app tests，必须返回退出码 0 和 All checks passed；不接受任何 pre-existing E402。
  2. 使用 Python 3.9 导入 app.main、model.generate_gird、model.layout_agent、model.llm_client。
  3. 通过 runpy.run_module("model.layout_agent", run_name="not_main") 验证模块入口可解析且不会依赖 sys.path 注入。
  4. 对 _cli 使用假输入、假数据库、假 LayoutAgent 和临时输出目录进行确定性测试，证明 CLI 逻辑仍可执行且不访问真实模型。
  5. 运行全部 Python 测试，既有删除 canva_agent.py 的回归测试和三个布局场景必须继续通过。
  6. 检索三个目标文件，确认不存在 sys.path.insert、_project_root 或 E402 豁免。
  7. 检查 Git diff，确认没有 Ruff 配置、前端、docs/ 或无关模块变更。

  ## 风险与最终记录

  - 依赖直接文件执行的外部脚本会失效；这是已接受的兼容性变化。
  - 命令必须从仓库根目录执行，或项目必须以包形式安装。
  - 本任务只清理三个已知模块的路径注入，不进行全仓库打包结构重构。
  - 若移除路径注入后出现导入失败，应修正调用方式或包导入，不得重新加入路径注入。