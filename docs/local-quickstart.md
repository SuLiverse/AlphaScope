# 本地快速启动指南

## 前置条件

- Python 3.11+
- Node.js 20.19.x 或 22.12+
- 至少一个 LLM API Key（推荐 DeepSeek）

## 一键启动（推荐）

### Windows

双击 `scripts/start_local.bat`，自动完成：

1. 环境检查（Python、Node、依赖、端口）
2. 创建必要目录
3. 启动 FastAPI 后端（端口 8000）
4. 启动 Vite React 前端（端口 3000）
5. 自动打开浏览器

### PowerShell

```powershell
# 基础启动（FastAPI + Vite React）
powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1

# 包含 Streamlit 调试台
powershell -ExecutionPolicy Bypass -File scripts/start_local.ps1 -WithStreamlit
```

### 停止服务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_local.ps1
```

## 手动启动

如果一键脚本不适用，可以手动启动各服务：

### 1. 配置环境

```bash
copy .env.example .env
# 编辑 .env，填入至少 DEEPSEEK_API_KEY
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
cd apps/web && npm install && cd ../..
```

### 3. 启动服务

```bash
# FastAPI 后端
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

# Vite React 前端（新终端）
cd apps/web && npm run dev

# Streamlit 调试台（可选，新终端）
streamlit run frontend/dashboard.py --server.port 8501
```

### 4. 访问

- 前端主界面: http://localhost:3000
- FastAPI API 文档: http://localhost:8000/docs
- Streamlit 调试台: http://localhost:8501

## 环境检查

```bash
python scripts/check_env.py
```

检查项：
- Python 版本 >= 3.11
- Node.js 版本为 20.19.x 或 >= 22.12.0
- npm 可用
- Python 依赖已安装
- .env 文件存在
- 端口 3000/8000/8501 空闲
- 数据目录齐全

## 目录结构

```
AlphaScope/
├── data/               # 运行时数据（gitignore）
│   ├── db/             # SQLite 数据库
│   ├── cache/          # 缓存、ChromaDB
│   ├── reports/        # 分析报告
│   ├── uploads/        # 上传文件
│   └── logs/           # 日志
├── apps/web/           # Vite React 前端
├── backend/            # FastAPI 后端
├── frontend/           # Streamlit 调试台
├── config/             # YAML 配置
├── scripts/            # 启动/停止/迁移脚本
└── .env                # 环境变量（从 .env.example 复制）
```

## 常见问题

### 端口被占用

```bash
# 检查端口占用
netstat -ano | findstr :8000

# 停止占用进程
taskkill /PID <进程ID> /F
```

### Python 依赖缺失

```bash
pip install -r requirements.txt
```

### npm 依赖缺失

```bash
cd apps/web && npm install
```

### .env 未配置

```bash
copy .env.example .env
# 用记事本打开 .env，填入 API Key
notepad .env
```

### ChromaDB 安装失败

ChromaDB 是可选组件。如果安装失败（需要 C++ Build Tools），可以跳过：

```bash
pip install -r requirements-core.txt -r requirements-api.txt -r requirements-dev.txt
```

无 ChromaDB 时向量检索功能不可用，其他功能正常。
