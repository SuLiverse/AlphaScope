# 研策中枢 AlphaScope v1.9.24

发布日期：2026-06-30

v1.9.24 落地战略规划的 **Phase 0（边界 / 协议先行）+ Phase 1（Integration Registry 插件中心骨架）**：把「不自动实盘下单」从 README 文字变成**可加载、可断言、可扫描、可守卫**的工程约束；把外部项目（OpenBB / Qlib / vectorBT / TradingAgents / …）接入方式从「口头规划」变成**统一 adapter 协议 + 注册表 + 自动发现 + 5 个 API 端点**。同时新增**确定性评级层（0-100 评分 + 五档评级 + 可审计明细）**，并把实盘残留 schema（`LiveRunRequest/Status`）从量化层清除。纯增量与加固，未删改既有研究 / 回测 / Agent 能力。

## 下载

- Windows 安装包：`AlphaScope-Setup-1.9.24.exe`（双击安装）
- Windows 便携版：`AlphaScope-portable.zip`（解压后运行 `AlphaScope.exe`）

## Phase 0：交易边界工程化（No-Live-Order Boundary）

把核心合规红线（不连接真实券商、不自动下单）变成四道可执行防线，任何 PR 若引入实盘下单能力都会被测试拦截：

- **配置防线** `config/legal_boundaries.yaml`：显式列出允许（paper / backtest / manual_ticket / report / watchlist）与永久禁止（live_broker_order / llm_direct_order / auto_execution / real_api_secret_for_trading）的能力标志。
- **不变量防线** `backend/security/trading_boundary.py::TradingBoundary.assert_invariant`：启动期硬断言所有 `allow_live_*` / `allow_auto_*` 为 False，违例抛 `BoundaryViolation` 拒绝启动。
- **源码防线** `scan_forbidden_symbols()`：AST 扫描 `backend/` 下 .py，禁止把 `submit_order` / `place_order` / `execute_trade` / `auto_trade` / `live_gateway` 定义为函数 / 类 / 方法名（接近交易的能力必须用 `create_paper_order` / `create_research_ticket` 等研究语义命名）。
- **守卫防线** `assert_no_live_order(action)`：任何「接近交易」的代码路径可在入口处自证，双保险。

## Phase 1：Integration Registry 插件中心

外部项目接入的统一地基（规划「10 个最优先融合功能」#1）：

- **统一数据契约** `backend/integrations/schemas.py`：`IntegrationMetadata`（含许可证防火墙分级 `LicenseSafety` + `allow_live_order` 恒 False + `code_copy_allowed`）+ 归一化输出 `NormalizedBacktestResult` / `NormalizedAgentOpinion` + `BacktestAssumptions`（回测假设卡）。
- **四类 adapter 协议** `backend/integrations/base.py`：`DataAdapter` / `FactorAdapter` / `BacktestEngineAdapter` / `AgentTeamAdapter`，统一 `metadata()` / `healthcheck()` / `is_available()`。
- **注册表 + 自动发现** `backend/integrations/registry.py`：`@register` 装饰器 + `autodiscover()` 扫描 `integrations/{data,factor,backtest,agent}/<name>_adapter.py`；注册时执行三道断言（边界 / 能力黑名单 / 许可证防火墙）。
- **demo_adapter** `backend/integrations/backtest/demo_adapter.py`：零依赖参考实现，证明注册表走通（Phase 2 起会被 vectorbt / backtrader 等真实 adapter 取代 / 补充）。
- **5 个 API 端点** `backend/api/integrations.py`：`GET /api/integrations`（列表 + 健康）、`/boundary`（边界概览）、`/{name}`（详情）、`/{name}/health`、`POST /{name}/run`（受边界守卫）。
- **许可证防火墙**：AGPL / 非商业 / BSL 的 adapter 必须 `mode=external_process` + `code_copy_allowed=False`，禁止拷码进主仓（与 §12 License Firewall 一致）。

## 确定性评级层（Agent Scorecard）

`backend/runtime/rating.py`：从多 Agent 投票 × 置信度算出 0-100 评分 + 五档评级（强烈推荐 / 推荐 / 中性 / 谨慎 / 回避），全项目唯一权威实现。

- **纯函数 `compute_rating(agent_results, risk_vetoed)`**：加权净方向 D ∈ [-1,+1] → raw = 50+50D → 用平均置信度向中性收缩 → 风控否决压到 ≤15（回避档）；空输入 / 全零置信度 → 50（中性）。全程输出 `breakdown`（W/D/raw/avg_conf/conf_factor/n_agents/risk_vetoed）可审计。
- **接入编排**：`orchestrator.run_agents_with_mode` 现在在 summary 里同时输出 `score` / `rating` / `rating_breakdown`；风控否决时重算为 vetoed 评分。`AnalysisSummary` schema 补 `score/rating/rating_breakdown` 字段。
- **去重**：`ai_assistant/report_templates.py` 原 `_score_to_rating` 改为复用 `rating.score_to_rating`（删除重复实现）。
- **合规**：评级是「多 Agent 投票结构」的确定性度量，`compliance.RATING_DISCLAIMER` 明确不构成投资建议。

## Manual Review Ticket 数据模型（Phase 0）

- `backend/schemas/{manual_ticket,paper_order,research_decision}.py`：把「人工确认单 / 纸面订单 / 研究决策裁决」的研究语义 schema 落地（规划「10 个最优先融合功能」#8）。仅数据模型，不含实盘订单流。
- **清除实盘残留**：从 `schemas/quant.py` 删除 `LiveRunRequest` / `LiveRunStatus`（无任何引用，干净移除），消除命名上的合规隐患。

## 前端：评级徽章接入

- `ReportGenerator.tsx` / `analysisAdapter.ts` / `types.ts`：从后端 `summary` 抽取 `score` / `rating` / `rating_breakdown`，新增 `RatingBreakdown` 类型；研报顶部展示确定性评级徽章 + 可审计明细（W/D/raw/conf_factor）。
- 失败安全：缺 score / rating 时优雅降级，不破坏既有研报渲染。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿：**1393 passed, 1 skipped, 1 deselected**（较 v1.9.23 增 43：integrations 8 + security 8 + rating 27）。
- `ruff check` / `ruff format --check` 通过；前端 `tsc --noEmit` 0 error、`eslint` 0 problem、`vite build` 通过（主包 index 857 kB 不变）。

## 合规

- 本版新增的 Integration Registry / Rating / Manual Ticket 全部为**研究语义**：注册表不执行交易，评级仅为度量，人工确认单不连 broker；`allow_live_order` / `forbidden_live_order` 等字段恒为 False / True，并由测试断言。
- 不预测行情、不荐股、不构成投资建议；评级与回测均附免责。

## 升级说明

- 直接安装覆盖即可；本地 `data/` 与 `.env` 保留。
- Phase 1 仅落地骨架 + demo adapter；真实外部项目（Qlib / vectorBT / OpenBB / TradingAgents）的 adapter 将在 Phase 2 起按本协议逐一接入。
