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
- demo:工业供气系统组态监控界面：左侧为一台大型空气罐，顶部连接水平管道，管道连接流量计、压力传感器、流量计，空气罐顶部设有阀门。右侧上下排列两台氮气罐，每个罐顶部均安装阀门，每个的出口管道分别连接流量计和压力传感器。