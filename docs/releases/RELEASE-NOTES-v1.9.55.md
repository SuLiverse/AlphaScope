# 研策中枢 AlphaScope v1.9.55

发布日期：2026-08-13

相对上一份 GitHub Release **v1.9.39**，这是一次完整的可信度与工程卫生发版：回测/定投数字口径、数据湖与通知 SSRF、Docker token 卫生、检索排序，以及启动器停止逻辑。仓库 `main` 现与本地最新版对齐。

本项目用于研究、学习和辅助分析，**不构成投资建议，不荐股、不预测行情、不承诺收益**。

## 下载

源码与 CI 产物见本 Release 页面。Windows 安装包 / 便携包需用本 tag 重新执行：

```powershell
python build.py --installer --zip
```

- Windows 安装包：`AlphaScope-Setup-1.9.55.exe`
- Windows 便携版：`AlphaScope-portable.zip`

源码启动：

```bash
pip install -r requirements.txt
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
cd apps/web && npm install && npm run dev
```

需要 Python 3.11/3.12，以及 Node.js **20.19.x 或 ≥22.12**。首次启动可走 Demo，无需 API Key。

## 相对 v1.9.39 的重点

### 安全

- 已暴露密钥从仓库历史清除，并加了防再提交守卫。
- DuckDB 数据湖禁止任意文件读和 SSRF 式表名/路径绕过。
- 飞书 webhook 校验主机名；SMTP 默认不允许打到私网。
- Docker Web 容器不再下发本机 API token；远程部署需在前端入口显式填 token。
- 启动器 `--stop` 只杀带可信运行时标记的本实例，避免误杀整机 Python。
- 文档与开发默认监听 `127.0.0.1`。

### 量化（数字会变，这是刻意的）

- 策略信号与 K 线根数对齐；T 日信号在 **T+1 开盘**成交，最后一根无下一根则丢弃。
- 年化收益按自然日，不再按交易日放大。
- 定投年化改 **XIRR**；禁止用未来净值填充；回撤按单位净值。
- 全胜时 `profit_factor` 不再变成 `inf` 导致接口 500。
- 周期 K 线聚合忽略非正 OHLC。
- 为回测引擎和定投补了手算精确值回归网。

若你用旧版回测数字做对照，请以本版口径为准，不要和 v1.9.39 的年化/定投收益直接比。

### 可靠性

- Auto 模式预筛失败会降级返回，不再误升到 Deep。
- 聊天接口共享 ConversationStore，避免每次请求泄漏 SQLite 连接。
- 任务 SSE 在终态结束；自选股监控告警恢复。
- MCP `search_evidence` 接到真实混合检索；混合检索排序方向修正。
- 组合保存失败会返回错误；基本面失败结果不再被缓存成成功。

### 工程与依赖

- 去掉未使用的 `aiohttp`；升级 `requests` / `curl_cffi` / `python-dotenv`。
- 开发依赖与 CI 对齐（`httpx`、FastAPI、pytest-cov）。
- `lib-pybroker`、`ragas` 从默认 quant/mlops extra 拆出，需要时再装。
- 审查计划见仓库 `plans/`。

## 升级注意

1. **回测 / 定投数字会变。** 同一策略、同一区间，年化和定投收益率与 1.9.39 不可逐点对比。
2. **本机默认只监听 127.0.0.1。** 若你以前靠 `0.0.0.0` 从局域网访问开发服务，需要显式改启动参数。
3. **Docker 远程访问必须自己填 token。** 镜像不再自动把 token 塞进前端。
4. **前端构建需要较新的 Node。** Vite 6 要求 20.19.x 或 22.12+。
5. 仍不接实盘、不自动下单。

## 验证

本地针对本版改动面的回归：`192 passed`（launcher / DCA / 数据湖 / 检索 / 回测引擎 / 通知 / 会话存储 / runtime token / check_env / workflow）。全量套件以 CI 为准。
