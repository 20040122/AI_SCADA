# AI-SCADA

## 后端
```bash
# 1. 安装依赖
pip install -r requirements.txt
# 2. 配置环境变量
 创建.env.local，格式参考 env.local.example内容
# 3. 启动服务
python3 -m uvicorn app.main:app --reload --port 8000
```
## 前端
```bash
cd web/scada
rm -rf node_modules
npm ci
npm run dev
```
