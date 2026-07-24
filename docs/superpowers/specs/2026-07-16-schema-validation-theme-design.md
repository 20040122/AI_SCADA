# Schema 校验页面主题统一设计

## 目标

统一 Schema 校验页面与现有 SCADA 深色蓝灰主题，消除未定义 CSS 变量和浅色状态块造成的色差。

## 范围

- 修改 `RuleLibraryPage.tsx` 和 `ValidatorPanel.tsx` 的主题类名。
- 不改变页面三栏布局、数据流、接口和交互行为。
- 复用 `index.css` 已定义的颜色变量。

## 视觉方案

- 基础背景使用 `--bg`、`--bg2`、`--bg3`、`--bg4`。
- 边框使用 `--border`、`--border2`。
- 文字使用 `--text`、`--text2`、`--text3`。
- 成功、警告、错误分别使用 `--success`、`--warn`、`--error`，状态背景使用对应颜色的低透明度深色叠层。
- 移除 `red-50`、`green-50`、`yellow-50`、`gray-100` 等浅色背景类。

## 验收标准

- Schema 页面不再引用未定义的 `--bg1`、`--border1`、`--text1`。
- 默认、悬停、选中、成功、警告和错误状态均保持深色 SCADA 视觉体系。
- 不改变校验请求、结果展示逻辑和现有响应式布局。
- 前端构建通过，Python 代码按项目要求通过 ruff 检查。
