# Progress

## Milestone 1: 建立共享 LLM 模块 ✅
- 创建 `model/llm_client.py`
- 提供 `default_client`, `default_model`, `call_llm`
- 保留原有三次重试、指数退避、可重试异常 (APIConnectionError, APITimeoutError, RateLimitError)
- 启动即失败语义保持不变
- `requirements.txt` 添加 `tenacity>=9.1.2`

## Milestone 2: 将仅布局使用的能力收回 layout_agent.py ✅
- `_calc_content_rect` 迁入 `model/layout_agent.py`
- `_schema_validate` + Schema 缓存迁入 `model/layout_agent.py`
- 未新增 `canvas_utils.py` 或反向依赖 validate 路由

## Milestone 3: 删除遗留实现 ✅
- `model/canva_agent.py` 已删除
- `model/refine_agent.py`, `model/validate_agent.py`, `model/generate_gird.py` 改为导入 `model.llm_client`
- `model/layout_agent.py` 改为导入 `model.llm_client.default_client` + 本地 `_calc_content_rect` / `_schema_validate`
- `model/`、`app/`、`tests/` 中无 `canva_agent` 或 `CanvasAgent` 残留引用

## Milestone 4: 清零 Ruff E402 ✅
- `model/llm_client.py`：移除 `sys`、`Path` 导入，移除 `_project_root`/`sys.path.insert`，第三方 import 移至顶部
- `model/generate_gird.py`：移除 `sys` 导入，移除 `_project_root`/`sys.path.insert`，import 按 stdlib→third-party→first-party 分组
- `model/layout_agent.py`：移除 `sys` 导入，移除 `_project_root`/`sys.path.insert`，import 按标准分组，`LAYOUT_DIR`/`_SCHEMA_PATH` 路径计算内联
- `ruff check` 返回 `All checks passed!`（0 E402）
- 三个目标文件无 `sys.path.insert`、`_project_root` 或 E402 豁免残留
- 29 个测试全部通过
- 未修改 Ruff 配置、前端或 docs/
