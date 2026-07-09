# 研策中枢 AlphaScope v1.7.1

发布日期：2026-06-04

v1.7.1 是一次已知问题修复与一键启动交付版本。重点修复搜索、上传、分析失败语义、股票池导出、首屏图表告警和前端类型检查问题，并重新验证 Windows portable 打包链路。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.7.1.exe`
- 便携版：`AlphaScope-portable.zip`

如果没有安装 Inno Setup，也可以使用便携版目录：

```powershell
python build.py --zip
dist\AlphaScope\AlphaScope.exe
```

## 修复

- 通用 `/api/files/upload` 不再信任客户端原始文件名，保存前会移除路径片段、规范化非法字符，并校验最终路径仍位于上传目录内。
- 顶部搜索框按 Enter 时改为解析用户实际输入内容，不再误选当前建议列表的第一项。
- `/api/analysis/run` 在所有 Agent 因模型 Provider 未配置而失败时，返回 `success=false` 和 `error_code=analysis_all_agents_failed`，同时保留诊断数据。
- 新增 `POST /api/quant/stock-pool/export`，服务端解析股票池文本并返回可测试的 CSV 下载。
- 回测页面导出股票池时优先调用服务端 CSV 端点，失败时保留本地 CSV 兜底。
- Workbench 首屏 K 线图使用稳定高度容器，修复 Recharts `width(-1) and height(-1)` 警告。
- 补齐 React 19 类型依赖与前端类型定义，恢复 `npm run lint` 通过。
- API 版本号改为从 `pyproject.toml` 读取，避免健康检查和项目版本脱节。
- CORS 默认限制为本地开发/一键启动来源，可通过环境变量显式开启更宽策略。
- 修复 Windows 一键启动包缺少 `akshare` 数据文件的问题，打包产物已包含 `akshare/file_fold/calendar.json` 等运行时资源。
- 打包产物包含 `_internal/pyproject.toml`，并通过 `ALPHASCOPE_VERSION` 提供版本兜底，启动后 `/health` 返回 `1.7.1`。

## 一键启动

面向普通用户推荐下载 release 资产后直接启动：

1. 下载 `AlphaScope-portable.zip` 并解压，或下载 `AlphaScope-Setup-1.7.1.exe` 安装。
2. 双击 `AlphaScope.exe`。
3. 程序会自动寻找可用本地端口，启动 FastAPI 后端和已构建 Web 页面，并打开浏览器。
4. 首次使用 AI 分析前，在自动创建的 `.env` 中填写至少一个模型 API Key。

源码用户可运行：

```powershell
AlphaScope-Setup.bat
```

或手动启动：

```powershell
pip install -r requirements.txt
cd apps\web
npm install
npm run dev
```

另开终端：

```powershell
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

## 验证

```bash
python -m pytest tests/test_quant_api.py tests/test_analysis_guardrails.py tests/test_file_upload_safety.py tests/test_upload_safety.py -q
```

结果：`20 passed`

```bash
python -m ruff check .
npm run lint
npm run build
```

结果：均通过。

额外验证：

- `POST /api/quant/stock-pool/export` 返回 `200`、`text/csv; charset=utf-8` 和 `attachment; filename="alphascope-stock-pool.csv"`。
- Browser-Use 打开 `http://127.0.0.1:3017/`，首页行情图可见，刷新后 fresh warn/error console logs 为 `0`。
- `python build.py --skip-web --zip --no-clean` 成功生成 `dist/AlphaScope/AlphaScope.exe` 和 `dist/AlphaScope-portable.zip`。
- 新版 `AlphaScope.exe --no-browser` 冒烟通过：`/health` 返回 `1.7.1`，`/api/prices/600519?limit=3` 返回 `success=true`、`source_status=ok`。

## 已知边界

- 本项目仍为研究和辅助分析工具，不构成投资建议。
- 外部行情、新闻、模型 Provider 可用性取决于用户网络、账号额度和第三方服务状态。
- 完整 `python -m pytest -q` 在本地长时间运行场景中可能超过交互超时，本次发布采用定向回归、前端构建和打包验证作为 release gate。
