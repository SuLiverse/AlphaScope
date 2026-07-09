# 研策中枢 AlphaScope v1.9.28

发布日期：2026-06-30

v1.9.28 落地战略规划 **Phase 2 的第三个真实外部项目 adapter**：Qlib（AI 量化因子引擎，微软出品）。这是继 vectorBT（Backtest 类）、OpenBB（Data 类）之后，**第一个 FactorAdapter 类**的真实 adapter，补齐自研确定性因子库所不擅长的「Alpha158/Alpha360 系统化因子 + ML 衍生因子」能力（对应规划「QlibAdapter」「FactorLab + Qlib 深度融合」，v2.5 蓝图核心）。纯增量，未删改既有研究 / 回测 / Agent 能力。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.9.28.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## Phase 2 第三个真实 adapter：Qlib（FactorAdapter）

`backend/integrations/factor/qlib_adapter.py` —— 把 [Qlib](https://github.com/microsoft/qlib)（MIT，微软 AI 量化平台）接入 Integration Registry，补齐自研 `factor_registry`（确定性技术因子）所不擅长的机器学习因子能力。

- **可选依赖 + 优雅降级**：`qlib` 用 import-guard 包裹，没装不影响其余功能（healthcheck 报 UNAVAILABLE）；安装并初始化数据目录后即生效。与 vectorBT / OpenBB / DuckDB 同一种哲学。
- **不触网**：因子计算所需 OHLCV 由调用方注入，不抓数据、不下单。
- **能力**：`compute_factors`（用 Alpha158/Alpha360 算因子向量），归一化成 AlphaScope 因子向量结构，与现有 `factor_registry.compute_for_symbol` 同构（`{symbol, asof, factor_set, factors, source, disclaimer}`）。
- **数据初始化探测**：`has_qlib_data_initialized()` 检查 `qlib.config` 是否注册了 provider；healthcheck 在已装但数据未初始化时报 DEGRADED（提示 `qlib.init(provider_uri=...)` + 下载数据），初始化后 HEALTHY。
- **失败安全**：qlib 不可用 / 数据未初始化 / API 抛错 → 返回空因子向量（结构与正常输出一致），不抛破坏性异常。
- **边界**：`allow_live_order=False`，MIT → `LicenseSafety.SAFE` + `code_copy_allowed=True` + `mode=PYTHON_ADAPTER`；通过 registry 三道注册断言。
- **纯函数可单测**：`normalize_qlib_factor_df`（取最新行作为 asof 因子向量，过滤 NaN/inf，跳过非数值列，兼容 pandas）/ `has_qlib_data_initialized` 不依赖 qlib，始终可测。
- **诚实口径标注**：Qlib 因子含 ML 衍生，与确定性技术因子口径不同；输出标 `source=qlib` + disclaimer 防混淆。

## Phase 2 adapter 覆盖度进展

| adapter 类别 | 已接入 | 说明 |
|---|---|---|
| BacktestEngineAdapter | demo / **vectorBT** ✅ | 向量化回测 + 参数扫描 |
| DataAdapter | **OpenBB** ✅ | 全球数据路由器 |
| **FactorAdapter** | **Qlib** ✅ | AI 量化因子（首个 FactorAdapter） |
| AgentTeamAdapter | （下一步 TradingAgents） | 外部投研团队 |

Integration Registry 的**四类 adapter 协议现已有三类**被真实项目验证走通（仅剩 AgentTeamAdapter）。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿：**1427 passed, 6 skipped, 1 deselected**（较 v1.9.27 +9：qlib 纯函数/元数据/边界/失败安全 9 用例；1 个 qlib 执行路径用例在未装 qlib 时正确跳过）。
- `ruff check` / `ruff format --check` 通过；前端未改动（维持 v1.9.24 状态）。

## 合规

- Qlib adapter 全程研究语义：因子是对历史量价 / ML 结构的度量，`direction` 仅为口径标注；不据此给买卖指令、不预测、不构成选股建议；输出附 disclaimer。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- qlib 为可选依赖：想要 ML 因子能力执行 `pip install pyqlib`，并按 [Qlib 文档](https://github.com/microsoft/qlib#data-preparation) 用 `qlib.init(provider_uri=...)` + `python -m qlib.run.get_data` 下载数据；不装也不影响其余功能。
- Phase 2 后续将按本协议接入 TradingAgents（AgentTeamAdapter，外部投研团队），完成后四类 adapter 协议全部被真实项目验证。
