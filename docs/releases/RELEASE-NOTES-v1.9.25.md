# 研策中枢 AlphaScope v1.9.25

发布日期：2026-06-30

v1.9.25 落地战略规划 **Phase 2 的第一个真实外部项目 adapter**：vectorBT（向量化回测引擎）。这是自 v1.9.24 的 Integration Registry 骨架之后，第一个按统一 adapter 协议接入的第三方开源项目，验证了「外部能力插件」路线完全走通。同时修复 registry 首次初始化的重入死锁（潜在稳定性隐患）。纯增量，未删改既有研究 / 回测 / Agent 能力。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.9.25.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## Phase 2 首个真实 adapter：vectorBT

`backend/integrations/backtest/vectorbt_adapter.py` —— 把 [vectorBT](https://github.com/polakowo/vectorbt)（Apache-2.0，基于 NumPy 的向量化回测库）接入 Integration Registry，补齐原生引擎（精确逐 bar 迭代）所不擅长的**快速参数网格扫描**能力。

- **可选依赖 + 优雅降级**：`vectorbt` 用 import-guard 包裹，没装不影响其余功能（healthcheck 报 UNAVAILABLE）；`pip install vectorbt` 后即生效。与 DuckDB 数据湖同一种哲学。
- **不触网**：回测所需 OHLCV 由调用方通过 `bars=` 注入，本 adapter 不抓数据、不下单（延续 datalake / factor_registry 的注入测试哲学）。
- **两个能力**：
  - `run_backtest`：单次向量化回测（首批内置 ma_cross 策略），返回归一化 `NormalizedBacktestResult`。
  - `param_sweep`：vectorBT 的核心价值——参数网格扫描（如 `fast∈[3,5,10] × slow∈[10,20,30,60]`），按 sharpe / max_drawdown / total_return 排序返回 top_n。原生引擎跑这种扫描要循环几十次，vectorBT 向量化一次完成。
- **诚实假设卡（Backtest Assumption Card，想法 #4）**：vectorBT 原生**不**模拟 A 股 T+1 / 印花税 / 涨跌停 / 停牌；adapter 在 `BacktestAssumptions` 里**显式标注这些未建模项**（note 明确写「偏乐观，仅适合快速初筛，严肃验证须切回原生引擎」），防止「快速扫描的好结果」被误读为「可直接实盘」。
- **边界**：`allow_live_order=False`，Apache-2.0 → `LicenseSafety.SAFE` + `code_copy_allowed=True` + `mode=PYTHON_ADAPTER`；通过 registry 三道注册断言。
- **纯函数可单测**：`bars_to_close_series` / `build_ma_cross_signals` / `parse_param_grid` / `build_assumptions` / `map_vbt_stats_to_metrics` 不依赖 vectorbt，始终可测。

## 稳定性修复：Integration Registry 重入死锁

`get_registry()` 在持锁状态下调用 `autodiscover()`，而 autodiscover 会 import 各 `*_adapter.py`，其模块级 `@register` 装饰器会**重入** `get_registry()`。原实现用 `threading.Lock`（不可重入）→ 同线程再次抢锁 → **死锁**，首次 registry 初始化永久挂起。

- v1.9.24 只有 demo_adapter 时因 import 时序侥幸未触发，加第二个 adapter（vectorbt）后必现（表现为测试 collection 挂起 5 分钟超时）。
- 修复：`_singleton_lock` 从 `Lock` 改 `RLock`（允许同线程重入）；autodiscover 前先发布单例，重入的 `get_registry()` 直接拿到正在构建的 registry 返回，不再进入 autodiscover；autodiscover 抛错时回滚单例以便下次重试。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿：**1408 passed, 4 skipped, 1 deselected**（较 v1.9.24 +15：vectorbt 纯函数/元数据/边界 15 用例；3 个 vbt 执行路径用例在未装 vectorbt 时正确跳过）。
- `ruff check` / `ruff format --check` 通过；前端未改动（tsc / eslint / build 维持 v1.9.24 状态）。

## 合规

- vectorbt adapter 全程研究语义：不触网、不下单；假设卡诚实披露未建模的 A 股摩擦（T+1 / 印花税 / 涨跌停），明确「偏乐观、仅初筛」。回测结果是对历史数据的统计描述，不预测未来、不构成投资建议。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- vectorbt 为可选依赖：想要参数扫描能力执行 `pip install vectorbt`；不装也不影响其余功能。
- Phase 2 后续将按本协议继续接入 OpenBB（全球数据增强）、Qlib（AI 量化因子）等「必接」项目。
