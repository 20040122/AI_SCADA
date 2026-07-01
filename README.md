# AI-SCADA

## 快速开始

### 后端
```bash
# 1. 安装依赖
pip install -r requirements.txt
# 2. 配置环境变量
 创建.env.local，格式参考 env.local.example内容
# 编辑 .env.local，填入 DEEPSEEK_API_KEY
# 3. 启动服务
python main.py
```
### 前端
```bash
cd web/scada
# 1. 安装依赖
npm install
# 2. 配置环境变量
cp .env .env.local
# 3. 启动开发服务器
npm run dev
```

- 温度监控与报警控制组态画面，使用高低温试验箱作为设备主体，搭配1个启动按钮、1个急停按钮、1个运行状态指示灯、数值显示、折线图、表格。
- 高低温试验箱左侧放置启动按钮、急停按钮、运行状态指示灯及数值显示，右侧放置折线图展示温度变化趋势，底部利用表格显示记录。1600 1400