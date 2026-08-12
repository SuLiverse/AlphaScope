# 部署文档

## 快速启动

### 方式一：Windows 安装包（推荐给普通用户）

发布页下载 `AlphaScope-Setup-*.exe` 后双击安装即可。安装包包含后端运行时和已构建的 Web 前端，启动后会自动打开浏览器。

开发者生成安装包：

```powershell
python -m pip install -r requirements-api.txt pyinstaller
python build.py --installer
```

输出：

```text
dist/AlphaScope/AlphaScope.exe
installer/installer-output/AlphaScope-Setup-1.7.1.exe
```

如果机器没有 Inno Setup，仍可用 `python build.py --zip` 生成便携版目录和压缩包。

### 方式二：本地开发

```bash
# 1. 克隆项目
git clone https://github.com/TIANWEN-cpu/AlphaScope.git
cd AlphaScope

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，至少配置 DEEPSEEK_API_KEY

# 4. 启动 FastAPI 后端
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# 5. 启动 Vite React 前端
cd apps/web && npm install && npm run dev
```

### 方式三：Docker Compose

```bash
cp .env.example .env
# 编辑 .env，至少配置 DEEPSEEK_API_KEY

# 启动全部服务 (Streamlit + FastAPI + Vite React)
docker-compose up -d

# 仅启动 Streamlit (port 8501)
docker-compose up -d app

# 仅启动 FastAPI API (port 8000)
docker-compose up -d api

# 仅启动 Vite React 前端 (port 3000)
docker-compose up -d web

# 启动 Streamlit + FastAPI + Vite React
docker-compose up -d app api web
```

服务说明：

| 服务 | 端口 | 说明 |
|------|------|------|
| `app` | 8501 | Streamlit 界面（传统 UI） |
| `api` | 8000 | FastAPI REST / SSE API（100+ 端点） |
| `web` | 3000 | Vite React 前端（预览服务） |

API 首次启动会生成本地 Token。Web 容器通过 Compose 命名卷取得 `runtime-config.js` 时**不再包含该 token**（token 不随静态文件分发）；远程访问时首次打开 Web 界面会要求输入一次 token（仅存于当前页面会话的 sessionStorage，关页即清），token 可在 API 容器日志或根 `.env` 的 `ALPHASCOPE_LOCAL_API_TOKEN` 查看。若浏览器不在 Docker 主机上，启动前设置 `ALPHASCOPE_PUBLIC_API_BASE_URL=http://<主机地址>:8000`。API 容器已关闭 uvicorn access log，防止 `local_token` query 参数落日志。

健康检查：
```bash
docker-compose ps                    # 查看服务状态
curl http://localhost:8501/_stcore/health  # Streamlit
curl http://localhost:8000/health          # FastAPI
curl http://localhost:3000/                # Frontend
```

## 依赖分层

| 文件 | 内容 | 用途 |
|------|------|------|
| `requirements-core.txt` | 核心运行时 | Streamlit, pandas, akshare, openai |
| `requirements-api.txt` | FastAPI | fastapi, uvicorn |
| `requirements-rag.txt` | RAG | chromadb (可选) |
| `requirements-dev.txt` | 开发 | pytest, ruff |
| `requirements.txt` | 聚合 | core + api + dev |

```bash
pip install -r requirements.txt           # 默认安装
pip install -r requirements-rag.txt       # 添加 RAG 支持
```

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API Key |
| `CLAUDE_API_KEY` | 否 | Claude API Key |
| `OPENAI_API_KEY` | 否 | OpenAI API Key |
| `TAVILY_API_KEY` | 否 | 联网搜索 |
| `FINNHUB_API_KEY` | 否 | 美股数据 |
| `TUSHARE_TOKEN` | 否 | Tushare Pro Token |

## CI/CD

GitHub Actions 自动运行 3 个 job：

```yaml
jobs:
  lint-and-test:    # Python 3.11 + 3.12
    - ruff check + format check
    - pytest tests/ -v (431 tests)

  web-build:        # Node.js 20
    - npm ci
    - npm run build
    - npm run lint

  docker-build:     # 依赖 lint-and-test + web-build
    - docker build -t alphascope:test .
    - docker run --rm alphascope:test python -c "import backend"
```

## Makefile 命令

```bash
make install     # 安装依赖
make test        # 运行测试
make lint        # 代码检查
make format      # 代码格式化
make run         # 启动 Streamlit
make api         # 启动 FastAPI
make web-build   # 构建 Vite React 前端
make docker-up   # Docker 启动
make check       # lint + test
```
