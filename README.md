# AI-SCADA
- demo：高低温试验箱监控面板，画面左侧放置高低温试验箱设备模型，右侧显示设备名称、当前温度、运行状态、启动按钮、急停按钮和温度趋势折线图。

## QuickStart

### 后端

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
 .env.local参考 env.local.example内容
# 编辑 .env.local，填入 DEEPSEEK_API_KEY

# 3. 启动服务
python main.py
```

服务启动后访问 `http://localhost:8000`，API 文档见 `http://localhost:8000/docs`。

### 前端

```bash
cd web/scada

# 1. 安装依赖
npm install

# 2. 配置环境变量（默认已指向 localhost:8000）
cp .env .env.local

# 3. 启动开发服务器
npm run dev
```

前端启动后访问 Vite 输出的地址（默认 `http://localhost:5173`）。

```shell
sqlite3 data/material.db "SELECT * FROM query_results"
```
