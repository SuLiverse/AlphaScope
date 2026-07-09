# 研策中枢 AlphaScope v1.9.29

发布日期：2026-06-30

v1.9.29 落地战略规划 **Phase 2 的第四个、也是最后一个真实外部项目 adapter**：TradingAgents（多智能体 LLM 投研团队）。这是继 vectorBT（Backtest）、OpenBB（Data）、Qlib（Factor）之后，**第一个 AgentTeamAdapter 类**的真实 adapter，补齐自研 Agent Council 的外部视角多样性（对应规划「TradingAgentsAdapter」「AgentHub 外部投研团队」，Phase 5）。

**至此 Integration Registry 的四类 adapter 协议全部被真实项目验证走通，Phase 2 完整收尾。**

## 下载

- Windows 安装包：`AlphaScope-Setup-1.9.29.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## Phase 2 收尾：TradingAgents（AgentTeamAdapter）

`backend/integrations/agent/tradingagents_adapter.py` —— 把 [TradingAgents](https://github.com/TauricResearch/TradingAgents)（TauricResearch，多智能体 LLM 金融投研框架：4 分析师 + 多空辩论 + 风控辩论 + 组合经理）接入 Integration Registry，作为「外部投研团队」输出 BUY/SELL/HOLD + 研报。

- **API 对照真实源码核对（非臆测）**：吸取 v1.9.28 Qlib adapter 的教训，本次先用 subagent 拉 TradingAgents v0.3.0 的 `trading_graph.py` / `default_config.py` / `pyproject.toml` 源码核对，确认：
  - 入口 `from tradingagents.graph.trading_graph import TradingAgentsGraph`（非臆测的 `tradingagents.tradingagents`）
  - 运行 `final_state, decision = ta.propagate(company_name, trade_date, asset_type="stock")`（返回二元组，非臆测的单值）
  - decision ∈ `{"BUY","SELL","HOLD"}` 是 LLM 抽取的字符串（需容错）
  - 配置走 `config=dict`（无 `llm_config=` 参数），API key 只能环境变量
- **可选依赖 + 优雅降级**：`tradingagents` 用 import-guard 包裹，没装不影响其余功能（healthcheck 报 UNAVAILABLE）。
- **LLM 凭证必需（与前三 adapter 不同）**：TradingAgents **无离线模式**，`.propagate()` 必须有 LLM API key；`has_llm_credentials()` 探测 `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` 等，healthcheck 在已装但缺凭证时报 DEGRADED。
- **能力**：`analyze`（对给定标的跑多 Agent 团队，返回归一化 `NormalizedAgentOpinion` 列表，BUY/SELL/HOLD → 买入/卖出/观望 + thesis）。
- **失败安全**：不可用 / 缺凭证 / `.propagate` 抛错 / 单标的失败 → 返回空列表，不抛破坏性异常；单标的失败不影响其余。
- **边界**：`allow_live_order=False`；输出观点永远 `forbidden_live_order=True`（绝不直接变成订单，须经证据+风控+人工确认）。
- **许可证**：TradingAgents 是 Apache License 2.0（已核对仓库 LICENSE 文件）→ `LicenseSafety.SAFE` + `code_copy_allowed=True`，与 vectorBT(Apache)/OpenBB(MIT)/Qlib(MIT) 同级；`requires_evidence=True`。
- **归一化纯函数可单测**：`_normalize_decision`（容错 LLM 噪声如 "buy."/"最终决策: SELL"，未知值 → HOLD）/ `map_decision_to_opinion`（把 (final_state, decision) 映射成 NormalizedAgentOpinion，thesis 优先 final_trade_decision 退到报告拼接）/ `has_llm_credentials` 不依赖 tradingagents。

## Phase 2 adapter 覆盖度（四类全部验证 ✅）

| adapter 类别 | 已接入 | 说明 |
|---|---|---|
| BacktestEngineAdapter | demo / **vectorBT** ✅ | 向量化回测 + 参数扫描 |
| DataAdapter | **OpenBB** ✅ | 全球数据路由器 |
| FactorAdapter | **Qlib** ✅ | AI 量化因子 |
| **AgentTeamAdapter** | **TradingAgents** ✅ | 外部投研团队 |

**Integration Registry 四类 adapter 协议全部被真实开源项目验证走通，Phase 2 完整收尾。** 外部项目接入从「规划文字」变成了「照模板写 adapter 文件 + 自动发现注册」的标准化流程。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿：**1440 passed, 7 skipped, 1 deselected**（较 v1.9.28 +12：tradingagents 纯函数/元数据/边界/凭证探测/失败安全 12 用例；1 个执行路径用例在未装 tradingagents 时正确跳过）。
- `ruff check` / `ruff format --check` 通过；前端未改动（维持 v1.9.24 状态）。
- registry 五个 adapter（demo/openbb/qlib/tradingagents/vectorbt）全部自动发现，`allow_live_order` 全 False，边界不变量通过。

## 合规

- TradingAgents adapter 全程研究语义：输出 BUY/SELL/HOLD 是**研究观点**，`forbidden_live_order=True`，绝不直接变成订单，须经证据 + 风控 + 人工确认；不预测、不荐股、不构成投资建议。
- 许可证：TradingAgents 为 Apache-2.0（宽松开源，可商用），与其他四个 adapter 同级，可 pip 安装使用。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- tradingagents 为可选依赖（**推荐从源码装**：`pip install git+https://github.com/TauricResearch/TradingAgents.git`），且必须配置至少一个 LLM API key（`OPENAI_API_KEY` 等）才能跑 `.propagate()`；不装也不影响其余功能。
- **Phase 2 至此收尾**。后续按规划进入 Phase 3+：把已接入的 adapter 能力透到前端「集成中心」面板、接 MCP Server、做 Plugin Marketplace 等。
