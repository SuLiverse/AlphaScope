# 研策中枢 AlphaScope v1.9.26

发布日期：2026-06-30

v1.9.26 落地战略规划 **Phase 2 的第二个真实外部项目 adapter**：OpenBB（全球金融数据路由器）。这是继 vectorBT（Backtest 类）之后，**第一个 DataAdapter 类**的真实 adapter，把 AlphaScope 从偏重 A 股扩展到**美股 / ETF / 宏观 / 加密**等全球品种（对应规划「OpenBBProvider 增强」「扩展美股、ETF、宏观」）。纯增量，未删改既有研究 / 回测 / Agent 能力。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.9.26.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## Phase 2 第二个真实 adapter：OpenBB（DataAdapter）

`backend/integrations/data/openbb_adapter.py` —— 把 [OpenBB](https://github.com/OpenBB-finance/OpenBB)（MIT，开源金融数据平台，聚合 FMP / Polygon / Alpha Vantage / Yahoo / FRED 等数十源）接入 Integration Registry，扩展 AlphaScope 的数据覆盖到全球品种。

- **可选依赖 + 优雅降级**：`openbb` 用 import-guard 包裹，没装不影响其余功能（healthcheck 报 UNAVAILABLE）；安装并配置至少一个 provider 凭证后即生效。与 vectorBT / DuckDB 数据湖同一种哲学。
- **只读数据源**：OpenBB 只取数据，无任何交易能力；`allow_live_order=False`。
- **能力**：`get_ohlcv`（取全球品种历史 OHLCV，如 `AAPL` / `SPY` / `BTC-USD`），归一化成 AlphaScope 标准 OHLCV dict，与现有 akshare provider 同构。
- **凭证探测**：`has_any_provider_credentials()` 检查 `OPENBB_FMP_API_KEY` / `POLYGON_API_KEY` 等环境变量；healthcheck 在已装但无凭证时报 DEGRADED（Yahoo 等免 key 源仍可用），有凭证时 HEALTHY。
- **失败安全**：凭证缺失 / 网络错误 / 字段不匹配 / 品种不支持 → 返回空列表 + 降级，不抛错。
- **边界**：`allow_live_order=False`，MIT → `LicenseSafety.SAFE` + `code_copy_allowed=True` + `mode=PYTHON_ADAPTER`；通过 registry 三道注册断言。
- **纯函数可单测**：`normalize_ohlcv_df`（兼容 pandas/polars，处理各 provider 字段名差异，跳过无日期行，OHLC 缺失回落 0）/ `has_any_provider_credentials` 不依赖 openbb，始终可测。

## Phase 2 adapter 覆盖度进展

| adapter 类别 | 已接入 | 说明 |
|---|---|---|
| BacktestEngineAdapter | demo / **vectorBT** ✅ | 向量化回测 + 参数扫描 |
| **DataAdapter** | **OpenBB** ✅ | 全球数据路由器（首个 DataAdapter） |
| FactorAdapter | （下一步 Qlib） | AI 量化因子 |
| AgentTeamAdapter | （后续 TradingAgents） | 外部投研团队 |

Integration Registry 的**四类 adapter 协议**现已有两类被真实项目验证走通。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿：**1417 passed, 5 skipped, 1 deselected**（较 v1.9.25 +9：openbb 纯函数/元数据/边界/凭证探测 9 用例；1 个 openbb 执行路径用例在未装 openbb 时正确跳过）。
- `ruff check` / `ruff format --check` 通过；前端未改动（维持 v1.9.24 状态）。

## 合规

- OpenBB adapter 全程研究语义：只读历史数据，不触网交易、不下单；不预测、不荐股、不构成投资建议。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- openbb 为可选依赖：想要全球数据能力执行 `pip install openbb`，并按需在 `.env` 配置 `OPENBB_FMP_API_KEY` 等；不装也不影响其余功能。
- Phase 2 后续将按本协议继续接入 Qlib（FactorAdapter，AI 量化因子）、TradingAgents（AgentTeamAdapter）等。
