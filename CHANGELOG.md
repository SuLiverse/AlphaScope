# Changelog

## v1.9.40 - 2026-07-03

> **健壮性加固**:一轮「检查并修复」驱动的批次。code-review + 自主扫描发现并修复了一批并发、崩溃、假成功、误删、数据质量盲区问题。纯修复 + 观测层增强, 未删改既有功能, 未引入新依赖。

### DB 并发安全: 全部 store 统一进程级锁(防 `database is locked`)
- **根因**: `Database` 是进程级单例(`check_same_thread=False`), 多个 store 此前直接访问 `db._conn` / `Database().conn` 绕过 `_db_lock`。后台 ingestion 线程批量写 + FastAPI 请求读写共享同一连接不加锁, 并发时 `database is locked` 或读到半写状态。
- **16 个 store 全部改为 `with Database().transaction() as conn:`**:alert / research_portfolio / notifier(此前已修) + price_store / news_store / agent_store / watchlist_store / pipeline(高频批) + datasource_config / diagnostics_store / evidence_store / file_store / factors/generator / funds/portfolio / quant/research_memory / quant/experiment_store(中频批) + settings_store(深嵌套攻坚)。
- **`_db_lock` 不可重入避坑**: 写方法内调用另一个会加锁的方法(如 `save_agent`→`get_agent`、`record_snapshot`→`_prune`、`save_provider`→`_sync_to_gateway`)会死锁; 统一改为 DB 操作在事务内 commit 后、锁外再调下游。
- **测试**: mock `_get_conn` 旧写法改 mock `Database().transaction()`; 真实临时 SQLite fixture 给 `_FakeDB` 加 transaction; price_store 补 4 写 + 1 读线程并发回归测试锁住改造成果。

### 真 bug 修复(运行时炸弹)
- **[P0] `/api/diagnostics/mcp` 一个请求打死后端**:`describe()` 经 `list_tool_names()` 在 uvicorn 请求路径 `asyncio.run(server.list_tools())` probe FastMCP, 底层 `py_mini_racer`/V8 重复初始化触发 `partition_address_space` fatal abort 整个进程。改 `describe()` 返回静态 `REGISTERED_TOOLS`, 不在请求路径 probe; 补「静态 == 运行时 probe 一致」回归测试。
- **[P1] Schema 升级从未执行**:`_upgrade_schema()` 调 `db.get_connection()` 但 `Database` 无此方法, 每次启动抛 AttributeError 被吞, 架构文档要求的 15+ 表迁移从没跑过。改 `with db.transaction() as conn:`。
- **[P1] 飞书消息体 `[:3500]` 截断失效**:f-string 内 `[:3500]` 是字面文本, 长告警原样发送且末尾泄漏 `[:3500]`。移到 f-string 外。
- **[P2] dispatch-alerts 部分渠道失败也清空全部告警**:`any(r.ok)` 即 `acknowledge_all`, 一个渠道成功就把失败渠道告警永久丢。改仅全部成功才标读。
- **[P2] 替代因子无缓存打爆外部 API**:`/api/factors/alternative` 每次直连 FRED+Finnhub。加 5 分钟 TTL 缓存。
- **Finnhub 凭证错配**:provider 只读 `FINNHUB_API_KEY` 但 UI 存 `FINNHUB_TOKEN`, 改双变量兼容。
- **`_safe_filename` 中文崩 Content-Disposition**:`isalnum()` 放过中文 → latin-1 编码崩溃, 收紧 ASCII-only。

### UI 错误处理 / 防误删(假成功治理)
- **告警铃铛 ack 假成功**(核心监控入口防失语):`ackAlert/ackAll` `.then()` 乐观更新无 catch, POST 失败 UI 标已读但服务端未读, 告警被静默消化。加 catch 回滚提示 + 防重复点击。
- **通知设置页**:清除凭证加二次确认(破坏性); 推送结果显示每渠道成败(用 `all_succeeded`); 测试前检测未保存草稿(防测旧凭证); 加载失败不再静默白屏。
- **研究组合移除持仓**:加二次确认 + 后端同步失败提示(防"刷新凭空恢复"困惑)。
- **4 处破坏性操作加二次确认**:清空数据湖 / 清空本股记忆 / 删自定义数据源 / 删回测实验。
- **K 线首帧堆叠**:`autoSize` 与 `fitContent` 时序竞争, 0 宽度拟合致蜡烛堆叠。createChart 传初始尺寸 + fitContent 延迟到 rAF。
- **主页/专家团模式菜单被遮挡**:面板 `overflow-hidden` 裁切下拉菜单; header 与卡片网格同 z-10 遮挡。改 overflow-visible + header z-30。

### 数据质量观测层(激活沉睡模块)
- **anomaly_detector 接线**(此前完全沉睡):pipeline 落库前对每条 bar 跑 `check_price`(零负价/高低倒挂)、对每条新闻跑 `check_news`(标题过短/乱码/重复时间戳), 异常 log 标记 + 计数。纯观测、失败安全、不阻断/不丢弃(尊重既有"数据进来"语义)。补接线测试。

### 验证
- 离线套件 `pytest -m "not network"`:**1677 passed, 5 skipped, 1 deselected**(0 回归)。
- `ruff check` / 前端 `tsc --noEmit` / `vite build` 全程通过。
- 每批独立 commit + push, HEAD `d63db3d` 同步 origin/main。

### 合规与边界
- 全程未碰 `.env`/密钥/凭据; 未引入新依赖; 未删改既有功能; 未弱化任何测试。
- anomaly_detector 是纯观测层, 不改变落库语义; settings_store 加锁未改写入逻辑。

## v1.9.29 - 2026-06-30

> **Phase 2 收尾 / TradingAgents 外部投研团队 (首个 AgentTeamAdapter)**:把 [TradingAgents](https://github.com/TauricResearch/TradingAgents)(多智能体 LLM 金融投研框架)接入 Integration Registry, 作为外部投研团队输出 BUY/SELL/HOLD + 研报。**至此四类 adapter 协议 (Backtest+Data+Factor+Agent) 全部被真实开源项目验证走通, Phase 2 完整收尾。** API 对照真实源码核对 (吸取 v1.9.28 Qlib 臆测错误的教训)。纯增量, 未删改既有研究/回测/Agent 能力。

### Phase 2 收尾: TradingAgents (AgentTeamAdapter)(后端)
- `backend/integrations/agent/tradingagents_adapter.py`:TradingAgents(4 分析师 + 多空辩论 + 风控辩论 + 组合经理)接入 registry, 作为外部投研团队 (对应规划「TradingAgentsAdapter」, Phase 5)。
- **API 对照真实源码核对 (非臆测)**:先拉 v0.3.0 的 trading_graph.py/default_config.py/pyproject.toml 核对, 确认入口 `from tradingagents.graph.trading_graph import TradingAgentsGraph`、运行 `final_state, decision = ta.propagate(company, date, asset_type)` 返回二元组、decision ∈ {BUY,SELL,HOLD}、config 走 dict (无 llm_config 参数)、key 只能环境变量。
- **可选依赖 + 优雅降级**:import-guard 包裹, 缺装不影响其余功能 (healthcheck 报 UNAVAILABLE)。
- **LLM 凭证必需 (与前三 adapter 不同)**:TradingAgents 无离线模式, .propagate 需 LLM key;has_llm_credentials 探测 OPENAI_API_KEY 等, healthcheck 已装但缺凭证时 DEGRADED。
- **能力 analyze**:对标的跑多 Agent 团队, 返回归一化 NormalizedAgentOpinion 列表 (BUY/SELL/HOLD → 买入/卖出/观望 + thesis)。
- **失败安全**:不可用/缺凭证/.propagate 抛错/单标的失败 → 返回空列表, 不抛;单标的失败不影响其余。
- **边界**:allow_live_order=False;观点永远 forbidden_live_order=True (绝不直接变订单, 须经证据+风控+人工确认)。
- **许可证**:TradingAgents 是 Apache License 2.0 (已核对仓库 LICENSE) → SAFE + code_copy_allowed=True, 与 vectorBT/OpenBB/Qlib 同级;requires_evidence=True。
- **归一化纯函数可单测**:_normalize_decision (容错 LLM 噪声如 "buy."/"最终决策: SELL", 未知值→HOLD)/ map_decision_to_opinion (thesis 优先 final_trade_decision 退到报告拼接)/ has_llm_credentials 不依赖 tradingagents。

### Phase 2 adapter 覆盖度 (四类全部验证)
- BacktestEngineAdapter (demo/vectorBT) + DataAdapter (OpenBB) + FactorAdapter (Qlib) + AgentTeamAdapter (TradingAgents)。**四类协议全部被真实项目验证, Phase 2 完整收尾。**

### 验证
- 离线套件 `pytest -m "not network"` 全绿:**1440 passed, 7 skipped, 1 deselected**(较 v1.9.28 +12:tradingagents 纯函数/元数据/边界/凭证/失败安全 12 用例;1 执行路径用例未装时正确跳过)。
- `ruff check`/`ruff format --check` 通过;前端未改动。registry 五个 adapter 全部自动发现, allow_live_order 全 False, 边界不变量通过。

### 合规
- TradingAgents adapter 全程研究语义:输出 BUY/SELL/HOLD 是研究观点, forbidden_live_order=True, 须经证据+风控+人工确认;不预测不荐股不构成投资建议。许可证防火墙:仅 pip/外部进程使用。

## v1.9.28 - 2026-06-30

> **Phase 2 第三个真实 adapter / Qlib AI 量化因子引擎 (首个 FactorAdapter)**:把 [Qlib](https://github.com/microsoft/qlib)(MIT, 微软 AI 量化平台)接入 Integration Registry, 补齐自研确定性因子库所不擅长的 Alpha158/Alpha360 系统化因子 + ML 衍生因子能力 (对应规划「QlibAdapter」, v2.5 蓝图核心)。四类 adapter 协议现已有三类 (Backtest+Data+Factor) 被真实项目验证走通。纯增量, 未删改既有研究/回测/Agent 能力。

### Phase 2 第三个真实 adapter: Qlib (FactorAdapter)(后端)
- `backend/integrations/factor/qlib_adapter.py`:Qlib(MIT, 微软 AI 量化平台)接入 registry, 补齐 ML 因子能力 (对应规划「QlibAdapter」「FactorLab + Qlib 深度融合」)。
- **可选依赖 + 优雅降级**:import-guard 包裹 qlib, 缺装不影响其余功能 (healthcheck 报 UNAVAILABLE), 装上 + 初始化数据即生效;与 vectorbt/openbb/DuckDB 同哲学。
- **不触网**:OHLCV 由调用方注入, 不抓数据不下单。
- **能力 compute_factors**:用 Alpha158/Alpha360 算因子向量, 归一化成 AlphaScope 因子向量结构 (与 factor_registry.compute_for_symbol 同构: {symbol,asof,factor_set,factors,source,disclaimer})。
- **数据初始化探测** has_qlib_data_initialized():检查 qlib.config 是否注册 provider;healthcheck 已装但数据未初始化时 DEGRADED (提示 qlib.init + 下载数据), 初始化后 HEALTHY。
- **失败安全**:qlib 不可用/数据未初始化/API 抛错 → 返回空因子向量 (结构与正常一致), 不抛破坏性异常。
- **边界**:allow_live_order=False;MIT → SAFE + code_copy_allowed=True + PYTHON_ADAPTER;过 registry 三道断言。
- **纯函数可单测**:normalize_qlib_factor_df (取最新行作 asof 因子向量, 过滤 NaN/inf, 跳过非数值列, 兼容 pandas)/ has_qlib_data_initialized 不依赖 qlib 始终可测。
- **诚实口径**:Qlib 因子含 ML 衍生, 与确定性技术因子口径不同;输出标 source=qlib + disclaimer 防混淆。

### adapter 覆盖度进展
- 四类 adapter 协议已有三类被真实项目验证:BacktestEngineAdapter (demo/vectorBT) + DataAdapter (OpenBB) + FactorAdapter (Qlib)。仅剩 AgentTeamAdapter (TradingAgents)。

### 验证
- 离线套件 `pytest -m "not network"` 全绿:**1427 passed, 6 skipped, 1 deselected**(较 v1.9.27 +9:qlib 纯函数/元数据/边界/失败安全 9 用例;1 个 qlib 执行路径用例未装时正确跳过)。
- `ruff check`/`ruff format --check` 通过;前端未改动(维持 v1.9.24)。

### 合规
- Qlib adapter 全程研究语义:因子是对历史量价/ML 结构的度量, direction 仅为口径标注;不据此给买卖指令、不预测、不构成选股建议;输出附 disclaimer。

## v1.9.27 - 2026-06-30

> **审查修复版**:审查 v1.9.25/26 发现三个真实缺口, 全部修复。

### 修复(后端)
- `_dispatch` 缺 data/get_ohlcv 分支 (api/integrations.py):OpenBB 是 DataAdapter, 装上后 POST /api/integrations/openbb/run 会进 ValueError。补 data/get_ohlcv 分支。
- `_dispatch` 缺 backtest/param_sweep 分支:vectorBT 核心差异化能力(参数网格扫描)通过 /run 不可达。补 param_sweep 分支。
- vectorbt_adapter benchmark 硬编码"沪深300":vectorbt/OpenBB 面向全球品种, 美股回测标沪深300误导。改为 kw.get("benchmark", "沪深300") 可配置。
- 新增 test_dispatch_supports_all_category_capability_pairs, 用 stub adapter 锁定每类能力的 dispatch 分支存在 (防以后加 adapter 又漏 dispatch)。

### 验证
- 离线套件 **1418 passed**(较 v1.9.26 +1 dispatch 覆盖用例);ruff 通过。

## v1.9.26 - 2026-06-30

> **Phase 2 第二个真实 adapter / OpenBB 全球数据路由器 (首个 DataAdapter)**:把 [OpenBB](https://github.com/OpenBB-finance/OpenBB)(MIT, 聚合 FMP/Polygon/AlphaVantage/Yahoo/FRED 等数十源)接入 Integration Registry, 扩展 AlphaScope 到美股/ETF/宏观/加密。Integration Registry 四类 adapter 协议现已有两类(Backtest + Data)被真实项目验证走通。纯增量, 未删改既有研究/回测/Agent 能力。

### Phase 2 第二个真实 adapter: OpenBB (DataAdapter)(后端)
- `backend/integrations/data/openbb_adapter.py`:OpenBB(MIT, 全球金融数据平台)接入 registry, 扩展数据覆盖到全球品种 (对应规划「OpenBBProvider 增强」)。
- **可选依赖 + 优雅降级**:import-guard 包裹 openbb, 缺装不影响其余功能 (healthcheck 报 UNAVAILABLE), 装上 + 配凭证即生效;与 vectorbt/DuckDB 同哲学。
- **只读数据源**:OpenBB 只取数据, 无任何交易能力;allow_live_order=False。
- **能力 get_ohlcv**:取全球品种历史 OHLCV (AAPL/SPY/BTC-USD), 归一化成 AlphaScope 标准 OHLCV dict (与 akshare provider 同构)。
- **凭证探测** has_any_provider_credentials():检查 OPENBB_FMP_API_KEY/POLYGON_API_KEY 等环境变量;healthcheck 已装但无凭证时 DEGRADED (Yahoo 免 key 源仍可用), 有凭证 HEALTHY。
- **失败安全**:凭证缺失/网络错误/字段不匹配/品种不支持 → 返回空 + 降级, 不抛。
- **边界**:allow_live_order=False;MIT → SAFE + code_copy_allowed=True + PYTHON_ADAPTER;过 registry 三道断言。
- **纯函数可单测**:normalize_ohlcv_df(兼容 pandas/polars, 处理各 provider 字段名差异, 跳过无日期行, OHLC 缺失回落 0)/ has_any_provider_credentials 不依赖 openbb 始终可测。

### adapter 覆盖度进展
- 四类 adapter 协议已有两类被真实项目验证:BacktestEngineAdapter (demo/vectorBT) + DataAdapter (OpenBB)。剩余 FactorAdapter (Qlib) / AgentTeamAdapter (TradingAgents) 待 Phase 2 后续。

### 验证
- 离线套件 `pytest -m "not network"` 全绿:**1417 passed, 5 skipped, 1 deselected**(较 v1.9.25 +9:openbb 纯函数/元数据/边界/凭证探测 9 用例;1 个 openbb 执行路径用例未装时正确跳过)。
- `ruff check`/`ruff format --check` 通过;前端未改动(维持 v1.9.24)。

### 合规
- OpenBB adapter 全程研究语义:只读历史数据, 不触网交易不下单;不预测不荐股不构成投资建议。

## v1.9.25 - 2026-06-30

> **Phase 2 首个真实 adapter / vectorBT 向量化回测 + 参数扫描 + registry 重入死锁修复**:把战略规划 Phase 2 第一个外部项目 vectorBT 按统一协议接入 Integration Registry,验证「外部能力插件」路线走通。同时修复 registry 首次初始化的重入死锁(v1.9.24 的潜在稳定性隐患)。纯增量,未删改既有研究/回测/Agent 能力。

### Phase 2 首个真实 adapter: vectorBT(后端)
- `backend/integrations/backtest/vectorbt_adapter.py`:把 [vectorBT](https://github.com/polakowo/vectorbt)(Apache-2.0, NumPy 向量化回测库)接入 registry,补齐原生引擎(精确逐 bar)不擅长的**快速参数网格扫描**。
- **可选依赖 + 优雅降级**:import-guard 包裹 vectorbt,缺装不影响其余功能(healthcheck 报 UNAVAILABLE),装上即生效;与 DuckDB 数据湖同哲学。
- **不触网**:OHLCV 由调用方 `bars=` 注入,不抓数据不下单。
- **两个能力**:`run_backtest`(单次向量化回测,内置 ma_cross)+ `param_sweep`(参数网格扫描,按 sharpe/max_drawdown/total_return 排序返回 top_n——vectorBT 的核心差异化)。
- **诚实假设卡**:vectorbt 原生不模拟 A 股 T+1/印花税/涨跌停/停牌;`BacktestAssumptions` 显式标注这些未建模项 + note 写明「偏乐观,仅初筛」,防误读为可实盘(想法 #4 落地)。
- **边界**:allow_live_order=False;Apache-2.0 → SAFE + code_copy_allowed=True + PYTHON_ADAPTER;过 registry 三道断言。
- **纯函数可单测**:`bars_to_close_series`/`build_ma_cross_signals`/`parse_param_grid`/`build_assumptions`/`map_vbt_stats_to_metrics` 不依赖 vectorbt,始终可测。

### 稳定性修复: Integration Registry 重入死锁(后端)
- `backend/integrations/registry.py::get_registry`:在持锁态调 `autodiscover()`,而 autodiscover import 的 `*_adapter.py` 模块级 `@register` 会**重入** `get_registry()`;原 `threading.Lock`(不可重入)→ 同线程再抢锁 → **死锁**,首次初始化永久挂起。v1.9.24 仅 demo 时侥幸未触发,加第二个 adapter 必现。
- 修复:`_singleton_lock` Lock→**RLock**(同线程可重入);autodiscover 前先发布单例,重入的 `get_registry()` 直接返回正在构建的 registry;autodiscover 抛错回滚单例下次重试。

### 验证
- 离线套件 `pytest -m "not network"` 全绿:**1408 passed, 4 skipped, 1 deselected**(较 v1.9.24 +15:vectorbt 纯函数/元数据/边界 15 用例;3 个 vbt 执行路径用例未装 vectorbt 时正确跳过)。
- `ruff check`/`ruff format --check` 通过;前端未改动(维持 v1.9.24)。

### 合规
- vectorbt adapter 全程研究语义:不触网不下单;假设卡诚实披露未建模的 A 股摩擦;回测结果是对历史数据的统计描述,不预测不荐股不构成投资建议。

## v1.9.24 - 2026-06-30

> **Phase 0 + Phase 1 落地 / 交易边界工程化 + Integration Registry 骨架 + 确定性评级层**:把战略规划里「不自动实盘下单」红线与「外部项目通过 adapter 接入」从文字变成工程约束与协议。新增四道交易边界防线(config/不变量/源码扫描/守卫)、Integration Registry(schemas + 四类 adapter 基类 + 注册表 + 自动发现 + 5 个 API + demo adapter)、确定性评级 0-100 五档(接入编排并去重 report_templates 的旧实现)、Manual Review Ticket schema;清除量化层 `LiveRunRequest/Status` 实盘残留。纯增量与加固,未删改既有研究/回测/Agent 能力。

### Phase 0 交易边界 No-Live-Order Boundary(后端)
- **配置防线** `config/legal_boundaries.yaml`:显式列出允许(paper/backtest/manual_ticket/report/watchlist)与永久禁止(live_broker_order/llm_direct_order/auto_execution/real_api_secret_for_trading)的能力标志。
- **不变量防线** `backend/security/trading_boundary.py`:启动期 `assert_invariant` 硬断言所有 `allow_live_*`/`allow_auto_*` 为 False,违例抛 `BoundaryViolation`;`live_order_blocked` 属性 + `assert_no_live_order(action)` 运行期守卫。
- **源码防线** `scan_forbidden_symbols()`:AST 扫描 `backend/` 下 .py,禁止把 `submit_order`/`place_order`/`execute_trade`/`auto_trade`/`live_gateway` 定义为函数/类/方法名。
- `describe_capabilities()` 供 UI「安全边界」面板;`backend/security/__init__.py` 导出。

### Phase 1 Integration Registry 插件中心(后端)
- **统一数据契约** `backend/integrations/schemas.py`:`IntegrationMetadata`(+ `LicenseSafety` 许可证分级 + `allow_live_order` 恒 False + `code_copy_allowed`)、`CapabilitySpec`、`IntegrationHealth`、`BacktestAssumptions`(回测假设卡)、`BacktestMetrics`、`NormalizedBacktestResult`、`NormalizedAgentOpinion`(均带研究语义自证字段)。
- **四类 adapter 基类** `backend/integrations/base.py`:`BaseAdapter` 抽象 + `DataAdapter`/`FactorAdapter`/`BacktestEngineAdapter`/`AgentTeamAdapter`;`metadata()` 双保险断言 `allow_live_order is False`。
- **注册表 + 自动发现** `backend/integrations/registry.py`:`@register` 装饰器、`autodiscover()` 扫描 `integrations/{data,factor,backtest,agent}/<name>_adapter.py`、`healthcheck_all()`、`assert_boundary_invariant()`(Phase 0 第四道防线);注册时三道断言(边界/能力黑名单/许可证防火墙:copyleft+code_copy 拒绝)。
- **demo_adapter** `backend/integrations/backtest/demo_adapter.py`:零依赖 BacktestEngineAdapter 参考实现,返回静态归一化结果。
- **5 个 API 端点** `backend/api/integrations.py`:`GET /api/integrations`、`/boundary`、`/{name}`、`/{name}/health`、`POST /{name}/run`(受边界守卫,白名单只代理研究/回测/分析能力);注册进 `main.py`。
- `backend/integrations/__init__.py` 导出全部公共符号。

### 确定性评级层 Rating(后端)
- `backend/runtime/rating.py`:`score_to_rating`(五档阈值,全项目唯一权威)+ `compute_rating(agent_results, risk_vetoed)` 纯函数——加权净方向 D → raw=50+50D → 平均置信度向中性收缩 → 风控否决压到 ≤15;空/全零置信度中性兜底;全程输出 `breakdown`(W/D/raw/avg_conf/conf_factor/n_agents/risk_vetoed)可审计。
- **接入编排** `orchestrator.run_agents_with_mode`:summary 现同时输出 `score/rating/rating_breakdown`;风控否决时重算为 vetoed 评分。
- **去重** `ai_assistant/report_templates.py`:`_score_to_rating` 改为复用 `rating.score_to_rating`(删旧实现)。
- **合规** `ai_assistant/compliance.py` 新增 `RATING_DISCLAIMER`;`schemas/agents.py::AnalysisSummary` 补 `score/rating/rating_breakdown` 字段。

### Manual Review Ticket schema + 清除实盘残留(后端)
- 新增 `backend/schemas/{manual_ticket,paper_order,research_decision}.py`(人工确认单/纸面订单/研究决策裁决,研究语义,不含订单流),`schemas/__init__.py` 导出。
- 从 `schemas/quant.py` 删除 `LiveRunRequest`/`LiveRunStatus`(无引用,干净移除)。

### 前端评级徽章接入
- `ReportGenerator.tsx`/`analysisAdapter.ts`/`types.ts`:从后端 summary 抽 `score/rating/rating_breakdown`,新增 `RatingBreakdown` 类型;研报顶部展示评级徽章 + 可审计明细;缺值优雅降级。

### 验证
- 离线套件 `pytest -m "not network"` 全绿:**1393 passed, 1 skipped, 1 deselected**(较 v1.9.23 +43:integrations 8 + security 8 + rating 27)。
- `ruff check`/`ruff format --check` 通过;前端 `tsc 0 error`·`eslint 0 problem`·`vite build ✓`(主包 index 857KB 不变)。

### 合规
- 新增 Integration Registry / Rating / Manual Ticket 全部研究语义:注册表不执行交易,评级仅为度量,人工确认单不连 broker;`allow_live_order`/`forbidden_live_order` 等字段恒 False/True 并由测试断言。不预测不荐股不构成投资建议。

## v1.9.23 - 2026-06-27

> **前端视觉协调与动画对齐**:排查发现 v1.9.0 起新增的 6 个页面(FactorRegistry / DataLakeManager / TickFlowManager / ResearchMemory / MonitoringCenter / StrategyLab)彼此字号、图标容器、间距风格不一致,且全部未接入项目既有的 `motion` 动效体系(其余 20 个老页面均在使用)。本版以 Valuation 为标杆,统一这 6 个页面的视觉语言并补齐动效,纯前端、零业务逻辑改动。

### 新页面动效与视觉对齐(前端,纯前端无后端改动)
- **页面入场**:6 页统一 `motion.div` 包裹,`opacity:0,y:8 → opacity:1,y:0 → opacity:0,y:-8`(入场/退场),与 Valuation/FundDcaLab 等既有体系一致。
- **标题/图标容器对齐**:统一 `h1 text-lg font-semibold` + `h-10 w-10` 图标容器(`bg-indigo-500/15` + `shadow-lg shadow-indigo-500/20` + `ring-1`)。修正:MonitoringCenter 原 `h3 text-xl`、StrategyLab 原 `text-xl font-bold`、新页面原 `h2 text-base` 全部统一;图标容器原各自不一(无容器 / `p-2.5` / 扁平 `border`)全部对齐。
- **列表 stagger**:因子向量行、源列表、股票列表、组件卡片、模板卡、回测指标卡、结论变化点等,按 30–50ms 错峰淡入。
- **结果块淡入**:矩阵、筛选结果、SQL 查询结果、回测结果等数据块整块淡入(`y:6 → y:0`)。
- **切换态**:`TickFlowManager` 编辑表单/空状态、`ResearchMemory` 时间线/空状态用 `AnimatePresence mode="wait"` 切换。
- 配色 token 严格复用既有体系(`white/[0.06]`、`white/[0.03]`、`transition-colors`),未引入新色值;ReportCharts 作为研报内嵌子块(非 tab 页)保持原状未动。
- 零回归:**本批无后端改动**,无业务逻辑改动,无布局结构改动;`eslint 0 problem` · `tsc 0 error` · `vite build ✓`;主包 index 维持 857 kB 不变,6 页各自独立 chunk(7.88–12.09 kB)。

## v1.9.22 - 2026-06-27

> **Phase 3 / FinRobot 式报告图表**:研报此前以文字段落为主,缺少 FinRobot 那种「一屏多图」的可视化密度。本版在「研究报告生成」页新增 **9 张图的「多维图表分析」面板**,把本次分析与历史数据可视化呈现——决策、辩论、量价、因子、形态一屏俯瞰。

### 多维报告图表 ReportCharts(前端,纯前端无后端改动)
- `ReportCharts.tsx`:9 张图(recharts),A 股配色(看多/买入红、看空/卖出绿、观望/中性琥珀):
  1. Agent 信号分布(饼)2. 各 Agent 置信度(柱)3. 多空共识度(径向仪表)4. 多空力量对比(柱)
  5. 辩论阵营分布(饼)6. K线形态信号近 60 日(柱)7. 收盘走势近 80 日(面积)8. 成交量(柱)9. 技术因子(横向柱)。
- 数据来源:1–5 取自本次分析已有数据(`agents`/`debate`,无需额外请求);6–9 **各自失败安全补抓**
  (`/api/prices/{symbol}`、`/api/factor-registry/symbol/{symbol}`、`/api/quant/patterns`)——任一失败仅该图占位,不影响其余。
- 集成进 `ReportGenerator.tsx`:`GeneratedResearchReport` 增 `symbol`/`stockName` 入参,在「多空辩论与裁决」后
  插入「多维图表分析」`ReportSection`(BarChart3 图标);随 ReportGenerator 懒加载(图表+recharts 折入其异步分块,主包不变)。
- 零回归:**本批无后端改动**,全量离线套件维持 **1222 passed, 1 skipped**;tsc 零错误;build 通过
  (ReportGenerator 块 46.7→69.4KB,主 index 857KB 不变)。
- 合规:图表基于历史与本次研究数据,描述「过去/当前」研究结构,不预测未来、不构成任何投资建议,面板顶部附免责。

## v1.9.21 - 2026-06-27

> **Phase 3 / 因子注册中心 · 研究流水线**:项目已有 5 个「软因子」(舆情/事件/评级/资金/动量,触网),但缺一个**统一因子目录**,也没把**确定性技术因子**(纯 OHLCV 算出)纳入框架,更没有「一次算一篮子标的」的批量流水线。本版对标 Qlib 的 factor/alpha 研究流程(保持本项目确定性·失败安全·不触网基线)补齐:**注册(catalog)+ 确定性技术因子 + SQLite 缓存 + 跨标的因子矩阵**。

### 因子注册中心 factor_registry(后端)
- `backend/quant/factor_registry.py`:
  - **注册目录**:`FactorDef`(id/名称/类别/方向/口径/来源)统一登记 15+ 因子——10 个确定性技术因子
    (本模块算)+ 5 个已有软因子(登记入目录,数值仍走 FactorGenerator)。`list_factors`/`get_factor`。
  - **确定性技术因子(纯函数,可单测)**:`compute_technical_factors` 从 OHLCV 算 20/60 日动量、20 日年化波动率、
    MA20/60 乖离、RSI(14)、60 日最大回撤、量比(5/20)、距 60 日高点、60 日区间位置;数据不足/脏数据 → None,失败安全。
  - **缓存**:自包含懒建表 `factor_vectors`(仿 experiment_store,不改 db 核心 schema),`cache_vector`/`get_cached_vector`/`_prune`(留 2000),全失败安全。
  - **研究流水线**:`compute_for_symbol`(单标的因子向量,`bars`/`loader` 可注入不触网)、
    `compute_matrix`(跨标的因子矩阵,逐标的失败安全)。
- `backend/api/factor_registry.py`:`GET /api/factor-registry/catalog`、`GET .../symbol/{symbol}`、
  `POST .../matrix`、`GET .../cached/{symbol}`,注册进 `main.py`。
- tests/test_factor_registry.py:16 用例(目录过滤 + 10 因子纯函数含失败安全 + 临时 SQLite 缓存 + 注入 loader 的流水线/矩阵/失败降级)。

### 因子注册中心(前端)
- `FactorRegistry.tsx` 侧栏「因子注册中心」页(量化研究引擎组):单标的因子向量(方向徽标 + 数值)+
  批量因子矩阵(多代码 → 因子矩阵表)+ 因子目录(类别/方向/来源/口径)。
- 接线:`types.ts` TabID +`factor_registry`;`App.tsx` 懒加载 + VISIBLE_TABS + 渲染分支;`Sidebar.tsx` 菜单项(Sigma 图标)。
- 零回归:全量离线套件 **1222 passed, 1 skipped**(较前 1206 增 16);tsc 零错误;build 通过(FactorRegistry 懒分块 7.6KB)。
- 合规:因子是对历史量价/舆情结构的确定性度量,方向仅为口径标注,不据此给买卖指令、不预测、不构成选股建议,附免责。

## v1.9.20 - 2026-06-27

> **Phase 3 / DuckDB·Parquet 数据湖**:三份战略报告一致点名的基础设施。把零散的逐标的行情沉淀成**列式数据湖**,用一条 SQL 跨上千标的批量扫描——批量选股、因子计算的底座。**零硬依赖、失败安全降级**:`duckdb` 用 import-guard 包裹,没装照常运行(数据湖能力报告 `available=False`,装上即生效)。

### 数据湖 datalake(后端)
- 新增依赖 `duckdb>=1.0,<2`(requirements-core.txt;**缺失时优雅降级,不影响其余功能**)。
- `backend/quant/datalake.py`:
  - 纯函数(无需 duckdb 即可单测):`normalize_bars`(统一列/去重/升序)、`build_screen_sql`
    (筛选规格 → WHERE 子句 + 参数,**字段/操作符白名单 + 占位符绑定防注入**)、`is_select_only`
    (只读守卫,拒 DDL/DML/多语句)。
  - duckdb-gated 失败安全:`ingest_prices`(规范化 → 写 `data/datalake/prices/<symbol>.parquet` 列存)、
    `ingest_from_provider`(复用价格面取数入湖,逐标的失败安全)、`query`(只读 SQL,表名 `prices`)、
    `screen`(每标的最新一根 bar 批量筛选)、`latest_snapshot`、`stats`、`list_symbols`、`clear_*`。
  - 每标的一个 parquet 文件,读取用 `read_parquet(glob)` 联合扫描;写入仅在显式入湖时发生。
- `backend/api/datalake.py`:`GET status/symbols/latest`、`POST ingest/screen/query`、
  `DELETE symbol/{id}|all`(请求体为模块级 Pydantic),注册进 `main.py`。
- tests/test_datalake.py:18 用例(规范化/选股 SQL 注入防护/只读守卫/降级纯函数组 +
  `importorskip("duckdb")` 的入湖·stats·快照·筛选·只读查询·清理往返组)。

### 数据湖(前端)
- `DataLakeManager.tsx` 侧栏「数据湖」页(量化研究引擎组):状态卡(标的数/行数/日期范围/占用)+
  **行情入湖**(批量代码输入)+ **批量筛选**(字段/操作符/阈值多条件 + 排序)+ **只读 SQL** 框 + 结果表;
  未装 duckdb 时显示友好提示(`pip install duckdb`),其余功能不受影响。
- 接线:`types.ts` TabID +`datalake`;`App.tsx` 懒加载 + VISIBLE_TABS + 渲染分支;`Sidebar.tsx` 菜单项(Database 图标)。
- 零回归:全量离线套件 **1206 passed, 1 skipped**(较前 1188 增 18);tsc 零错误;build 通过(DataLakeManager 懒分块 11.7KB)。
- 合规:数据湖为历史行情的列式副本,批量筛选描述「过去满足条件的标的」,既不预测也不构成选股建议,SQL 仅只读,均附免责。

## v1.9.19 - 2026-06-27

> **Phase 3 / TickFlow 自定义表(HTTP/JSON)**:v1.9.4 的 CSV/Excel 上传补齐了「上传文件」一路;本版补上「HTTP/JSON 接口」一路——用户配置外部 JSON 行情接口(URL + 记录路径 + 字段映射),点「拉取」即把远端 JSON 映射成标准 OHLCV **物化到本地缓存**,此后像 csv_upload 一样进入价格查询与回测面板。延续 csv 的「显式导入 → 离线可查」哲学:**网络只发生在试抓/拉取时且失败安全**,热路径只读本地缓存(离线确定性);映射/抽取是纯函数可单测。

### TickFlow HTTP/JSON 源(后端)
- `backend/providers/http_json_provider.py`:
  - 纯函数 `extract_records`(点路径 `data.klines` / 数组下标定位记录数组)、`apply_field_map`
    (字段映射 → 标准 OHLCV,支持 dict 记录按键 / list 记录按下标,时间戳秒·毫秒自动识别,失败安全)、
    `infer_field_map`(复用 csv `discover_schema` 从样本键推断映射)、`normalize_source`(配置校验)。
  - `fetch_json`(**唯一触网处**,优先 requests 回退 stdlib urllib,任何错误返回结构化失败、绝不抛出,
    可注入替身供测试)、`refresh_source`(拉取 → 映射 → **物化到 `data/uploads/tickflow/data/<symbol>.json`**;
    失败不清空既有缓存)、`preview_fetch`(试抓返回样本 + 推断映射)、`materialized_bars`(读本地缓存)。
  - `HttpJsonProvider(BaseProvider)`:priority=14(demo<http_json<csv_upload<在线源),requires_key=False,
    `get_prices` 只读物化缓存,数据标 `source=http_json` / `user_provided`,**绝不冒充在线源**,自动注册。
- `backend/api/tickflow.py`:`GET/POST /api/tickflow/sources`、`DELETE .../sources/{id}`、
  `POST .../sources/{id}/refresh`、`POST .../preview`(请求体为模块级 Pydantic 模型),注册进 `main.py`。
- tests/test_http_json_provider.py:29 用例(记录抽取/日期归一/字段映射/推断/配置校验纯函数组 +
  注入 fetcher 不触网的注册·拉取·物化·失败保留缓存·占位符·预览 + URL 守卫)。

### TickFlow(前端)
- `TickFlowManager.tsx` 侧栏「自定义数据表」页(量化研究引擎组):左源列表(状态/根数/最近拉取 + 拉取·删除),
  右配置表单(名称/代码/URL 含 `{symbol}` 占位/方法/记录路径/请求头 JSON/八字段映射)+ **「试抓并推断映射」**
  (一键填好字段映射)+ 样本记录预览。
- 接线:`types.ts` TabID +`tickflow`;`App.tsx` 懒加载 + VISIBLE_TABS + 渲染分支;`Sidebar.tsx` 菜单项(Webhook 图标)。
- 零回归:全量离线套件 **1188 passed, 1 skipped**(较前 1159 增 29);tsc 零错误;build 通过(TickFlowManager 懒分块 10KB)。
- 合规:网络仅在显式操作时发生且失败安全;数据明确标注用户来源,入库后仅供历史查询与回测,不预测不建议,附免责。

## v1.9.18 - 2026-06-27

> **Phase 3 / 研究记忆**:`1.txt` 规划的「同一股票可查看历史研究变化」。把每次 Agent 分析的**结论快照**(买入/卖出/观望 + 置信度 + 多空裁决 + 风控 + 数据核验)旁路落 SQLite,于是同一只股票可回看「上周看多、本周转观望」这类**结论随时间的变化轨迹**,辅助复盘。自包含、失败安全、纯函数可单测,仅记录与回看历史、不预测不建议。

### 研究记忆 research_memory(后端)
- `backend/quant/research_memory.py`:仿 experiment_store 风格的自包含 SQLite 模块(懒建表 `research_memory`,
  复用单例连接,**不改 `db._create_tables`**)。纯函数 `build_snapshot`(抽紧凑结论快照)/ `compute_changes`
  (检出 signal 转折点 + 转积极/转谨慎/横盘/调整方向)/ `summarize_history`(次数/最新信号/信号分布/置信度/变化数)
  皆可单测;DB 层 `record_snapshot`/`list_symbols`/`get_history`/`get_timeline`/`delete_*`/`_prune_symbol`(每股留 200)
  **全失败安全**(出错或空跑返回中性值,绝不影响分析本身)。
- `/api/analysis/run` 跑完**旁路**调用 `record_snapshot`(try/except 包裹,记不上不影响返回);空跑(无信号无计数无裁决)自动跳过,不污染记忆。
- `backend/api/research_memory.py`:`GET /api/research-memory/symbols`、`GET .../timeline/{symbol}`、
  `DELETE .../snapshot/{id}`、`DELETE .../symbol/{symbol}`,注册进 `main.py`。
- tests/test_research_memory.py:22 用例(信号归一/方向/快照映射/变化检测/历史汇总纯函数组 + 临时 SQLite 隔离的
  记录·时间线·聚合·删除·裁剪 DB 组)。

### 研究记忆(前端)
- `ResearchMemory.tsx` 侧栏「研究记忆」页(投研体系组):左股票列表(最新结论 chip + 次数),右**时间线**——
  总结卡(研究次数/最新结论/结论变化数/平均置信度)+ **结论变化轨迹**(转折点 `买入→观望` + 方向徽标)+
  **置信度趋势图**(recharts)+ 历史快照表(时间/结论/置信度/多空裁决/分歧/风控/收盘)+ 清空本股记忆。
- 接线:`types.ts` TabID +`research_memory`;`App.tsx` 懒加载 + VISIBLE_TABS + 渲染分支;`Sidebar.tsx` 菜单项(History 图标)。
- 零回归:全量离线套件 **1159 passed, 1 skipped**(较前 1137 增 22);tsc 零错误;build 通过(ResearchMemory 懒分块)。
- 合规:研究记忆仅记录与回看历史分析结论的变化,描述「过去如何判断」,不预测未来、不构成任何投资建议,附免责。

## v1.9.17 - 2026-06-27

> **形态识别(前端落地)**:把 v1.9.16 的 K 线形态在「交互K线」页可视化——形态面板 + **专业 K 线图上的形态标记**,让识别结果一眼可见、可定位到具体那根 K 线。

### 形态识别(前端 + 图上标记)
- `MultimodalChart.tsx` 交互K线页:换标的自动拉取 `/api/quant/patterns`(失败安全, 失败清空不报错),
  展示「形态识别」面板——看涨(红)/ 看跌(绿)/ 中性 chips + 三档计数 + 悬停看日期与形态说明 + 免责;
  「图上标记」开关。
- `LightweightKLine.tsx` 新增 `markers` 入参(`setMarkers`, 时间升序去重):专业 K 线上按形态打标记——
  **看涨红箭头在下、看跌绿箭头在上、中性灰圆点**, 文字为形态名, 直接定位到具体 K 线。
- tsc 零错误, build 通过(主 index 包不变;面板进 MultimodalChart 懒分包, lightweight-charts 仍是共享异步块)。

## v1.9.16 - 2026-06-27

> **Phase 3 / A 股特色**:compass 把「筹码分布 + 形态识别」并列为 A 股特色能力,筹码已于 v1.9.6 交付,本版补上**K 线形态识别**——确定性按规则检出蜡烛形态与结构信号,把"看图说话"变成可复核的标注。纯确定性、失败安全、不触网,描述历史结构、不预测涨跌。

### K 线形态识别 patterns(后端)
- `backend/quant/patterns.py`: `detect_patterns()` 从 OHLCV 按几何/比例规则检出:
  - **蜡烛形态**:十字星、锤子线/上吊线、流星/倒锤、看涨/看跌吞没、刺透/乌云盖顶、启明星/黄昏星、红三兵/三只乌鸦。
  - **结构信号**:向上/向下跳空、N 日突破/跌破、MA5-20 金叉/死叉、双顶(M 头)/双底(W 底)。
  - 每个形态规则明确、可单测,标注 看涨/看跌/中性;同形异义(锤子线 vs 上吊线)用前段趋势区分。**失败安全**(脏数据/样本不足 → 降级空形态,绝不抛出)。
- `POST /api/quant/patterns`(取本地行情 → 识别,带 provider/preview 兜底)。能力位 `pattern_recognition`
  (并顺手补回 `strategy_evolution` 在 `/api/quant/status` 能力表里的遗漏 — 此前只加到了 local_runner 未加到 API 服务的那份)。
- tests/test_patterns.py: 15 用例(吞没/锤子/十字星/红三兵/三只乌鸦/跳空/突破/金叉/双底 + 样本不足 + 失败安全 + 结构)。
- 零回归:全量离线套件 **1137 passed, 1 skipped**(较前 1122 增 15)。
- 合规:描述历史 K 线形态,其后续表现并不必然,不预测涨跌、不构成投资建议,附免责。

## v1.9.15 - 2026-06-27

> **Phase 3 差异化核心(前端落地)**:把 v1.9.14 的多空辩论裁决在「研究报告生成」页可视化——让"反方质询 + 裁决理由"对用户**可见、可审计**,完成三份报告的「报告含反方观点和裁决理由」验收闭环。

### 多空辩论裁决(前端面板)
- `ReportGenerator.tsx` 新增「多空辩论与裁决」`ReportSection`:**裁决 banner**(共识标签按多空/分歧/风控着色 +
  共识度 0-100 + 分歧度 + 多/空/中计数)+ **双栏对峙**——看多方(A 股涨红)/ 看空方·反方质询(跌绿,每条带
  `风控/数据/评审/信心` 来源徽标)+ 裁决理由 + 免责。
- `lib/analysisAdapter.ts` `normalizeDebate()` 防御式归一后端 `debate`(schema 漂移/缺字段不崩,统一为前端 `DebateResult`),
  并入 `normalizeAnalysisResult`;`types.ts` 增 `DebateResult`/`DebatePoint`。
- tsc 零错误,build 通过(主 index 包不变,面板进 ReportGenerator 懒分包)。

## v1.9.14 - 2026-06-27

> **Phase 3 差异化核心**:三份战略报告(compass/deep-research/1.txt)**一致收敛**的招牌能力——**多空辩论 + 反方质询 + 主席裁决入报**。三份都警告「证据链/结构化输出/数据治理稳定前别堆复杂 Agent」,而这些前置(v1.9.2/1.9.3/1.9.4)均已就位,故以**确定性合成器**落地:不新增任何 LLM Agent、不触网、不增成本,复用已算出的信号组成多空对峙。

### 多空辩论裁决 debate(后端 + 编排接入)
- `backend/agents/debate.py`: `synthesize_debate()` 把一次分析里**已算出**的 Agent 信号(买入/卖出/观望)+
  Critic 评审分歧 + 风控 gate 否决 + `data_verifier` 数据缺失,确定性合成「看多方 / 看空方(反方质询)/ 主席裁决」。
  - **反方质询四来源**(复用既有 skeptic 机制, 零额外模型调用):看空 Agent、看多但信心不足、风控一票否决、
    数据缺失/过期/异常、Critic 中/高分歧。
  - 裁决纯确定性(看多共识/偏看多/多空分歧/高度分歧/偏看空/看空共识/中性观望/风控否决 + 共识度 0-100),
    **合规**:描述研究分歧与置信度/共识度,绝不给买卖指令,附免责。失败安全(脏输入降级不抛)。
- `runtime/orchestrator.py`: 在风控 gate 之后**失败安全**合成 debate,附到分析结果,并把「多空辩论与裁决」小节
  (`format_debate_section`)并入研报正文 —— 满足三报告「报告含反方观点和裁决理由」的验收。两处 return 均带 `debate` 字段。
- `/api/analysis/run` 透出 `debate`。
- tests/test_debate.py: 16 用例(阵营划分/反方四来源/裁决标签/共识度/失败安全/研报小节渲染)。
- 零回归:全量离线套件 **1122 passed, 1 skipped**(较前 1106 增 16);中央编排路径改动前已跑全量验证。

## v1.9.13 - 2026-06-27

> **Phase 2 续**:把**主仪表盘(对话式研究)的 K 线**也迁到 Lightweight Charts 专业渲染,复用同一 `LightweightKLine` 组件。至此两处 K 线(交互K线 + 主仪表盘)均可专业/经典一键切换。同时把组件改**懒加载**,将 lightweight-charts 从主包拆成共享异步分块,主包体积复原。

### K 线迁 Lightweight Charts(主仪表盘 + 分包优化)
- `LightweightKLine.tsx` 扩展:新增 `ma10` 与**细粒度均线开关** `showMa5/showMa10/showMa20`(未指定时回退 `showMA`
  总开关,ma10 默认关),适配主仪表盘的三均线(MA5/MA10/MA20)独立显隐;`showMA` 向后兼容,交互K线页用法不变。
- `Workbench.tsx` 主仪表盘 K 线加「专业 / 经典」渲染切换(默认专业);经典 recharts 蜡烛 + 三均线**完整保留**为可选项,
  成交量/坐标/高低标注不动。
- **分包优化**:`LightweightKLine` 在 Workbench(默认页, 非懒加载)里改用 `React.lazy` + `Suspense`,把
  lightweight-charts(~165KB)从主 index 包拆成**共享异步分块**——主包体积复原(848KB,≈持平),MultimodalChart 分包
  也随之回落(不再各自打包一份)。首屏并行加载、不阻塞渲染,带「专业K线加载中」兜底。
- tsc 零错误,build 通过(主 index 848KB·gzip 261KB,lightweight-charts 独立分块 165KB·gzip 53KB 按需加载)。

## v1.9.12 - 2026-06-27

> **Phase 2 续**:把「交互K线」迁到 **TradingView Lightweight Charts** 专业渲染器——真·缩放/平移/十字光标/价格刻度对齐,适合密集 K 线。遵循「只增不替」:作为**专业模式**接入,与原 recharts**经典模式**并存,用户一键切换,默认专业。

### K 线迁 Lightweight Charts(Phase 2)
- 新增依赖 `lightweight-charts@^4.2.0`,**懒加载**进 MultimodalChart 分包(仅打开「K线/多模态解析」页时才加载,
  主包体积不变)。
- `components/LightweightKLine.tsx`: 自包含可复用组件,沿用既有 `KLinePoint` 形状(date/open/high/low/close +
  可选 ma5/ma20),**无需新取数**。蜡烛 + MA5/MA20 线 + 十字光标 OHLC 浮标;A 股配色(涨红/跌绿);
  `autoSize` 自适应容器;卸载时 `chart.remove()` 释放。对时间**去重 + 升序**(满足 Lightweight Charts 唯一/有序
  约束),均线只取有限正值跳过预热段 NaN —— 脏数据不崩、最多少画。
- `MultimodalChart.tsx` 交互K线页新增「专业 / 经典」渲染切换(默认专业);经典 recharts 自绘蜡烛**完整保留**为可选项,
  成交量/指标(MACD/RSI)面板不动。
- tsc 零错误,前端 build 通过(lightweight-charts 进 MultimodalChart 懒分包,主 index 包不变)。

## v1.9.11 - 2026-06-27

> **Phase 2 续**:新增**遗传算法策略参数寻优(策略进化)**——用确定性、可复现的 GA 在策略的数值参数空间里搜索更优组合,适应度=复用回测引擎跑一遍的绩效。与样本外走查天然配套(寻优找最优、走查验稳健)。纯本地、失败安全;**强免责**:样本内寻优极易过拟合,样本内最优≠未来有效。

### 遗传算法策略参数寻优 evolution(Phase 2)
- `quant/evolution.py`: 确定性 GA(全程 `random.Random(seed)` 驱动,**同 seed + 同输入 → 完全相同结果**),不触网。
  - **只进化参数、不进化代码**:遗传操作发生在数值参数空间(周期/阈值/仓位…),绝不生成或改写策略逻辑 ——
    合规等同「对历史做确定性参数搜索」。适应度=`BacktestEngine` 跑一遍取某绩效键(夏普/卡玛/索提诺/收益/胜率)。
  - 锦标赛选择 + 均匀交叉 + 高斯/整数变异 + 精英保留;初始种群含「默认参数投影」个体,故**全局最优至少不劣于默认**。
  - **失败安全**:单个个体回测异常 → 适应度沉到极小值被淘汰(绝不抛出);样本不足 → `insufficient`;
    无可寻优数值参数(tdx/custom_rule)→ `degraded`(仅评估默认);全失败 → `error`。
  - **算力有界**:种群 4-40 / 代数 1-20 自动夹紧,总评估数设预算上限,去重缓存避免重复回测。
  - `infer_param_space()` 从 `default_params` 推断合理搜索范围(正整数 [0.5d,2d]、正浮点 [0.5f,2f]),也可显式传入并校验。
- `POST /api/quant/evolve`(寻优,失败安全)+ `GET /api/quant/param-space/{strategy_name}`(供面板预填范围)。
  能力位 `strategy_evolution` 翻 True;`experiment_store._summarize` 增 `evolution` 分支落库;经 `_persist_experiment` 入实验记录。
- 前端 `Backtesting.tsx` 新增「策略进化」Tab:标的/策略/适应度/种群/代数/种子 控制 + 四指标卡(最优适应度/较默认提升/
  评估次数/搜索规模)+ 最优参数 chips + 该组合回测摘要 + **进化收敛曲线**(最优 vs 平均)+ 逐代明细表 +
  一键「去对最优参数做样本外走查验证」跨页联动 + 强过拟合免责。
- tests/test_evolution.py: 13 用例(空间推断/模板跳过/样本不足/未知策略/非法空间退化/基本寻优/**同 seed 确定性**/
  不劣于默认/显式空间被尊重/报告结构/非法指标回退夏普/实验摘要分支)。

## v1.9.10 - 2026-06-27

> **Phase 2 续**:新增**系统监控中心(Monitoring Center)**——把分散在各 observability/quant 子系统里的健康信号(数据源 / 回测引擎 / 实验记录 / 模型成本 / 工具调用 / 执行追踪)聚合成**单一快照**,前端单页总览。纯本地聚合、失败安全、不触网,仅反映系统自身运行状态。

### 系统监控中心 monitor(Phase 2)
- `observability/monitor.py`: 纯聚合 + 失败安全聚合器,**不触网**(只读各子系统进程内缓存状态与本地 SQLite)。
  - 6 个组件采集器各自独立 try/except:任一组件采集失败仅把该组件标记为 `unknown`,绝不抛出、不拖垮整体
    (沿用「诚实降级、绝不伪造正常」约定)。
  - 状态分级抽成**纯函数**(`grade_from_quality` / `tool_call_status` / `trace_status` / `compute_overall_status`),
    可脱离子系统直接单测;`unknown` 组件不参与总状态判定(未知 ≠ 异常)。
  - 复用既有 `source_health.compute_quality_score` / `local_runner.local_status_payload` /
    `experiment_store.count_experiments` / `diagnostics_store.{get_cost_summary,get_diagnostics_summary}` /
    `tracer.get_stats`,不新建数据通道。
- `GET /api/monitor/snapshot`: 返回各组件状态 + 系统总状态(good/warn/poor/unknown)+ 红黄绿计数 + 免责声明。
- 前端 `MonitoringCenter.tsx` 新模块(侧栏「量化研究引擎 · 系统监控中心」):总状态英雄卡 + 红黄绿计数 +
  组件卡片(状态徽标/摘要/指标明细可展开/`unknown` 采集异常提示)+ 20s 自动刷新(可关)+ 手动刷新。
- tests/test_monitor.py: 8 用例(质量分/工具调用/追踪三档阈值边界、总状态聚合、快照结构与 now 注入、
  包装层失败安全、依赖崩溃降级、真实采集器端到端不抛)。

## v1.9.9 - 2026-06-27

> **Phase 2 续**:把策略工坊里「TDX 公式编译(演示)/后端能力未启用」的占位做成**真能编译+回测**的通达信公式编译器——支持常用 TDX 子集,编译成防未来函数的买卖信号走现有回测引擎。纯确定性、失败安全、合规(用户自定义公式,只做确定性计算)。

### 通达信(TDX)公式编译器(A 股特色 / Phase 2)
- `quant/tdx_compiler.py`: 纯函数编译器(词法→递归下降语法→向量化序列求值),不触网。
  - 子集:数据引用 CLOSE/OPEN/HIGH/LOW/VOL;函数 MA/EMA/SMA/REF/CROSS/HHV/LLV/SUM/COUNT/
    MAX/MIN/ABS/IF/STD/AVEDEV;算术/比较/AND·OR·NOT;`:=` 赋值、`:` 输出、ENTERLONG/EXITLONG
    (或 BUY/SELL)定义买卖;`{}`、`//` 注释。
  - **防未来函数**:每条序列在 i 处只用 ≤i 数据;配合引擎 T→T+1 成交天然防前视。
  - **失败安全**:词法/语法/求值错误统一收敛成 `errors`(绝不抛出);坏公式 → 无信号 → 回测 0 交易,
    不伪造成功。周期参数须为字面量且 1-1000,函数名/参数个数编译期校验。
- `quant/strategies/tdx.py`: `TdxStrategy`(注册名 `tdx`)把公式求值成逐 bar 信号回测,复用引擎不新建。
  策略数 9→10;`tdx`/`custom_rule` 在策略榜对比中跳过(需用户公式/规则)。
- `POST /api/quant/tdx/compile`: 编译/校验(不回测),返回买卖信号、变量、引用与错误/告警,供编辑器即时反馈。
  回测复用 `/api/quant/backtest`(strategy_id="tdx", params.formula)。能力位 `tdx_compile` 翻 True。
- 前端 `Backtesting.tsx` 策略工坊:把静态演示占位换成**真编辑器**——可编辑公式 textarea + 「编译校验」
  (展示买卖信号/变量/引用/错误告警)+「直接回测」(走 tdx 策略并切到回测大厅看净值)+「恢复示例」。
- tests/test_tdx_compiler.py: 16 用例(编译/未知函数/参数数/语法失败安全/MA 金叉/REF/预热不前视/
  HHV+逻辑/坏公式无信号/注册/端到端回测)。

## v1.9.8 - 2026-06-27

> **Phase 2 续**:新增**实验记录持久化(experiment_store)**——把回测/走查/筹码/策略榜的结果落 SQLite,跨会话可查、可调阅、可横向对比。补足此前 `_local_runs` 内存态重启即丢的缺口。失败安全、只增不减(与内存态并存)。

### 实验记录持久化 experiment_store(Phase 2)
- `quant/experiment_store.py`: 自包含模块,懒创建独立表 `quant_experiments`(不改 `db._create_tables`),
  复用同一 SQLite 单例连接。`save/list/get/delete/compare/count` 全部**失败安全**(出错返回
  None/[]/False,持久化失败绝不影响运行本身——诚实降级,不假装存了)。按 mode 抽紧凑指标摘要
  供列表/对比直接用;`_prune` 保留最近 300 条防无限增长。
- 4 个运行入口(回测/走查/筹码/策略榜)统一经 `_persist_experiment()` 失败安全落库,与既有内存态
  `_local_runs` 并存(只增不减)。
- 新增端点:`GET /api/quant/experiments`(列举, 可按 mode/symbol 过滤)、
  `GET /api/quant/experiments/{run_id}`(完整载荷)、`DELETE /api/quant/experiments/{run_id}`、
  `POST /api/quant/experiments/compare`(按 run_id 列表取摘要并排)。
- 前端 `Backtesting.tsx` 新增「实验记录」Tab:类型筛选(回测/走查/筹码/策略榜)+ 记录表
  (时间/类型徽标/标的/策略/关键指标摘要/删除)+ 勾选最多 4 个一键横向对比(摘要卡并排)。
- tests/test_experiment_store.py: 11 用例(存取往返/过滤倒序/删除/对比/分模式摘要/prune/失败安全),
  用临时 SQLite 连接隔离不污染开发库。

## v1.9.7 - 2026-06-27

> **Phase 2 续**:新增**策略横向对比榜**——对同一标的一次取数、跑完全部内置策略并按指标排名,帮你快速看哪些策略在该标的历史上表现更好。复用已测回测引擎,纯本地确定性,合规(历史回测 ≠ 选股建议)。

### 策略横向对比榜 strategy leaderboard(Phase 2)
- `POST /api/quant/compare-strategies`: 一次 `_load_local_bars` 取数,所有内置策略复用同一份
  bar(各自拷贝避免污染),逐策略 `BacktestEngine.run` 回测,按 `rank_by`
  (sharpe_ratio/total_return/calmar_ratio/annual_return/win_rate)降序排名。模板策略
  `custom_rule` 无默认信号 → 跳过并在 `skipped` 标注。透出 assumptions 与免责。
- 前端 `Backtesting.tsx` 新增「策略榜」Tab(复用标的/资金状态):标的选择 + 排名指标三选
  (夏普/累计收益/Calmar) + 一键对比 → 排行榜表(累计收益/年化/最大回撤/夏普/Calmar/胜率/笔数,
  冠军行高亮 + 奖杯标),复用 AssumptionsCard 与免责声明。
- 合规: 仅历史回测对比, 不构成选股推荐;附「不代表未来、不构成投资建议」免责。
- tests/test_strategy_compare.py: 8 用例(排名形状/跳过模板/降序/非法键回退/字段/确定性/免责/路由)。

## v1.9.6 - 2026-06-27

> **Phase 2 续**:新增 A 股特色的**筹码分布(成本分布)**分析——用换手率扩散模型重建当前持仓成本结构,读出获利盘比例、平均成本、筹码集中度与上下方密集价。纯确定性、失败安全、合规(描述历史成本结构 ≠ 价格预测/荐股)。

### 筹码分布 chip distribution(A 股特色 / Phase 2)
- `quant/chip_distribution.py`: 纯函数模块(不触网)。换手率扩散——每日老筹码按 (1−t) 衰减、
  新筹码 t 份按当日价格区间三角分布铺开,逐日累积得成本分布(总量守恒)。
  - 优先用每根 K 线自带**真实换手率**;缺失时退回「量能代理」(相对成交量估算换手)并标
    `model=volume_proxy`,不冒充真实换手。
  - 输出:获利盘%、平均成本、70%/90% 筹码带与集中度、上/下方筹码密集价、逐价位占比。
  - 失败安全:K 线 <20 根返回 `insufficient` 而非抛错。
- `POST /api/quant/chip-distribution`: 优先取**原始** bar(含换手率), 不足时退回带 provider/
  preview 兜底的清洗取数(无换手 → 量能代理); 线程池执行不阻塞事件循环。
- 前端 `Backtesting.tsx` 新增「筹码分布」Tab(复用标的状态):获利盘/平均成本/集中度/建模 K 线
  四卡 + 横向筹码分布柱图(获利盘红/套牢盘绿按现价着色)+ 上/下方密集价与 70%/90% 筹码带 +
  真实换手率/量能代理建模徽标 + 免责声明。
- 合规: 「密集价」表示成本聚集而非价格目标, 附「不预测价格、不构成投资建议」免责。
- tests/test_chip_distribution.py: 17 用例(不足/分布守恒/获利盘语义/模型选择/密集价/确定性/API)。

## v1.9.5 - 2026-06-27

> **Phase 2 起步**:回测可信度继续深化——新增**样本外走查(walk-forward)稳健性分析**,回答「策略的收益是跨区间稳健,还是集中在某一段运气」这个过拟合核心问题。纯确定性、失败安全、只增不减,合规不变(描述历史 ≠ 预测/荐股)。

### 样本外走查 walk-forward(1.txt 量化严谨性 / Phase 2)
把历史切成顺序的 IS(样本内)+OOS(样本外)窗口,逐窗用**同一**固定参数策略回测,度量时间稳健性:
- `quant/walk_forward.py`: 纯函数模块(不触网),`run_walk_forward(strategy, bars, …)`。
  - 每窗只跑**一次**引擎,覆盖连续的 IS+OOS 切片 → 指标有正常预热,OOS 边界无人为信号断层;
    再按权益曲线在 IS/OOS 分界处切分,OOS 收益以分界权益重新归一 → 纯样本外度量。
  - 两种方案:`anchored`(锚定,IS 从首根增长)/ `rolling`(滚动,固定一折 IS 前移)。
  - 走查效率 WFE = OOS 年化 / IS 年化;聚合输出样本外胜率、收益均值/中位/离散、平均 WFE、
    一致性评分(0-100)与稳健性描述(稳健/一般/脆弱,警惕过拟合)。
  - 失败安全:历史不足以切分时返回 `insufficient` 报告而非抛错;窗口数据不足自动收敛并标 `degraded`。
  - 复用现有 `BacktestEngine`(T+1/印花税/滑点/防未来函数)与 `metrics`,不新建引擎;
    报告附 `assumptions` 与「样本外 ≠ 未来,不构成投资建议」免责声明。
- `POST /api/quant/walk-forward`: 复用回测取数链路(_load_local_bars),线程池执行不阻塞事件循环。
- 前端 `Backtesting.tsx` 新增「样本外走查」Tab(复用策略/标的/资金状态):锚定/滚动方案切换、
  窗口数设置、一致性评分/样本外胜率/收益均值/平均 WFE 四卡、稳健性判定 banner、
  「全样本累计 vs 样本外均值」过拟合提示、逐窗口 IS/OOS 明细表、回测假设卡与免责声明。
- tests/test_walk_forward.py: 15 用例(切分/锚定 vs 滚动/聚合区间/确定性/失败安全/未知策略/API 载荷)。

## v1.9.4 - 2026-06-27

> **里程碑**:落地 guide 四份战略报告合并去重后的 P1 全部未完成项——围绕「可复核 / 数据可信 / 上手低门槛 / 工程化」六项增强:低代码策略编辑器、数据核验 Agent、CSV/Excel 自带数据源、ProviderCapability 能力 schema、数据源质量评分、回测基准相对指标。配套 Issue/PR 模板与架构文档更新。只增不减,合规红线不变(不荐股/不预测/不实盘)。

### 低代码策略编辑器 + custom_rule 规则策略(1.txt + deep-research)
让用户用「字段+操作符+阈值」无代码组合买卖信号, 复用现有回测引擎(不新建引擎):
- `quant/strategies/custom_rule.py`: 规则驱动策略插件, 走同一套自动发现+BacktestEngine;
  compute_fields 提供 13 个按 bar 对齐的字段(rsi/macd/量比/距均线%/金叉态/回撤% 等),
  仅用 ≤i 数据(配合引擎 i→i+1 成交天然防未来函数); buy/sell 规则 and/or 组合。
- 前端 `StrategyLab.tsx`(新 tab「低代码策略编辑器」, 量化研究引擎组): 内置模板卡
  (RSI 超卖/均线金叉/放量突破/回调买入) + 可视化规则构建器 + 单次仓位 + 运行真实回测
  (透出累计/年化/回撤/夏普/胜率/笔数 + 引擎假设); localStorage 策略库, 三类标签
  builtin/custom/ai, 支持粘贴 AI 规则 JSON 导入。
- 编译产物 {strategy_id: "custom_rule", params:{buy_rules,sell_rules,logic,position_size_pct}}
  直接走 /api/quant/backtest。
- tests/test_custom_rule_strategy.py: 6 用例(字段对齐/and-or/NaN/触发/端到端回测)。

### 数据核验 Agent + CSV/Excel 数据源(compass §7.3 + §7.2)
让「数据缺失」不再被 LLM 脑补, 并让用户自带数据零 Key 入查询面:
- `agents/data_verifier.py`: 确定性预检(纯规则/不触网/失败不阻断), 逐维度核验
  行情/技术/基本面/资金流/舆情/证据是否齐全/新鲜/无异常; 缺失维度打标后由
  `brief_warning()` 生成「严禁编造」强约束注入简报, overall = complete/partial/insufficient。
- orchestrator 全路径(DEEP/STANDARD/AUTO 预筛/demo/无 Agent)透出 `data_verification`;
  `/api/analysis/run` 响应新增 data_verification 字段。
- `providers/csv_provider.py`: 上传 CSV/Excel → discover_schema 认中英文表头(含单位后缀)
  → 映射标准 OHLCV → 入价格查询面(priority=15, 高于 demo_seed 低于在线真源), 数据标注
  source=csv_upload/user_upload 绝不冒充在线行情。
- 新增 `/api/providers/csv/{datasets,upload,{filename}}` 上传/列举/删除端点。
- tests: test_data_verifier.py(9 用例) + test_csv_provider.py(9 用例)。

### ProviderCapability 能力 schema(deep-research 独有)
对标 tickflow tiers.yaml「能力驱动」, 用统一 schema 表达每个数据源能力:
- BaseProvider.capability(): 返回标准化能力字典(markets/data_types/data_class/
  freshness/latency_tier/cost_tier/rate_limit/trust_level/priority/requires_key/
  available/degradable), 纯读取类属性不触发网络。
- registry.get_all_capabilities() 聚合; 新增 /api/providers/capabilities 端点。
- 修复 BaseProvider 非数据类的 field(default_factory=) 默认值未实例化的潜在 bug
  (markets/data_types/rate_limit 在子类未覆盖时会是 Field 对象)。
- tests/test_provider_capability.py: 4 用例(schema/latency_tier/degradable/聚合)。

### 数据源质量评分 quality_score(compass §7.2 + 1.txt)
把数据源终端从"只有健康/降级/不可用"升级为可量化质量分:
- `observability/source_health.py` 新增纯函数 compute_quality_score: 成功率 × 新鲜度 × 完整度(0-100),
  带 good/warn/poor 红黄绿 grade; SourceHealthMonitor.get_quality_report() 汇总。
- `/api/providers/health` 为每个 provider 附加 quality_score/grade/success_rate/
  freshness_score/completeness_score + 顶层 quality_good/warn/poor 计数与 avg_quality。
- 前端 ProviderHealthPanel: 每个 provider 卡片显示质量分(红黄绿着色)+ 成功率/新鲜度。
- tests/test_source_quality.py: 6 用例(纯函数口径 + 聚合)。

### 统计指标补基准对比/超额收益/信息比率(compass §7.4-2)
对标 Qlib 口径, 补齐回测绩效的基准相关指标:
- `metrics.py` 新增纯函数: 超额收益(calc_excess_return)、信息比率(calc_information_ratio, 年化)、
  beta(calc_beta)、Jensen's alpha(calc_alpha)。
- `build_performance_summary` 接受可选 benchmark_curve: 有基准带 excess/IR/alpha/beta,
  无基准优雅降级为 0 并标记 has_benchmark=False(回测不依赖基准数据可得性)。
- engine.run() / local_runner / BacktestRunRequest / backtest_new API 全链路支持可选
  benchmark_symbol(如沪深300 sh000300); 取不到数据则跳过基准指标, 不阻断回测。
- 前端 Backtesting.tsx: has_benchmark 时渲染「超额收益/信息比率/Beta/Alpha」第二行指标卡。
- 前端 package.json 版本 1.8.0→1.9.0 对齐(1.txt 点出的不一致)。
- tests/test_metrics_benchmark.py: 10 用例(beta=1/超额=0/降级/有基准相对指标)。

## v1.9.3 - 2026-06-27

### 风控独立一票否决 gate(决策期)
对标金策智算「门下省」与 vn.py vnpy_riskmanager 插件式风控, 把风控从「只在回测里跑」
提升为「研报发布前也过的统一 gate」:

- 新建 `backend/quant/risk/`(`rules.py` + `engine.py`): 纯规则、确定性、可单测,
  规则配置化(`config/risk_rules.yaml`)。覆盖: ST/退市黑名单、单标的仓位、总仓位/
  行业集中度、AI 结论置信度门控。
- 与回测期 `risk_controller.py`(交易级,逐 bar)职责分离, 不耦合。
- orchestrator: 研报发布前跑 `RiskEngine.gate()`, 任一 critical 触发**一票否决**——
  研报保留(可追溯)但顶部红字写明理由, summary 不给出买入方向。
- `/api/analysis/run` 响应透出 `risk_gate` 字段(findings/vetoed/veto_reasons)。
- **合规红线**: 风控只做研究层风险提示与决策约束, 绝不输出买卖指令。
- 新增 `tests/test_risk_engine.py`(9 用例: 单规则 + gate 汇总 + orchestrator 集成)。

## v1.9.2 - 2026-06-27

### Agent 结论可溯源：绑定 evidence_id
此前证据链虽已存储, 但 Agent 结论没有反链到具体证据, "可审计"是半成品。本次补齐:

- **结构化证据池**: `context_builder.fetch_evidence_pool()` 返回带稳定 `evidence_id` 的证据条目,
  简报里的 `[n]` 编号与证据 ID 一一对应。
- **结论反链**: orchestrator 把每个 Agent reason/evidence 里的 `[n]` 引用解析成真实 `evidence_id`,
  幻觉引用(编号不存在)被静默丢弃。三种模式(STANDARD/DEEP/AUTO)响应统一带 `evidence_pool`。
- **API 透出**: `/api/analysis/run` 每个 agent 块带 `evidence_ids[]`, 顶层带 `evidence_pool[]`。
- **前端溯源**: AgentOpinionCards 渲染「结论溯源」标签, 点击跳转证据来源(新闻/研报/公告)。
- 新增 `tests/test_evidence_binding.py` 契约测试(4 用例)。

## v1.9.1 - 2026-06-26

### 回测可信度底线：真实 A 股交易摩擦
此前自研回测引擎用当天收盘价撮合、买入当日即可卖出、仅含佣金,会系统性高估收益。本次补齐量化项目可信度底线:

- **防未来函数**：T 日信号于 **T+1 开盘价成交**（不再用当天 close 既算信号又成交）。信号在最后一根 bar 时无下一 bar 可成交则丢弃,杜绝"事后成交"。
- **T+1 约束**：当日买入不得当日卖出（`backend/quant/constraints.py` `T1Constraint`）。
- **印花税**：卖出单边 0.05%（`TradingCostModel.stamp_duty_rate`）。
- **滑点**：买入 +0.1%、卖出 −0.1%（对买卖双方均不利方向偏离）。
- **佣金最低 5 元**：万三双边,小单保底 5 元。
- **涨跌停封板过滤**：涨停不可买入、跌停不可卖出（`PriceLimitFilter`,默认 ±10%,可设 ±5% 适配 ST）。
- **假设透明化**：每个回测结果新增 `assumptions` 字段(佣金/印花税/滑点/T+1/封板/成交价口径),API 响应同步透出,供研报展示"本次回测假设"。
- **向后兼容**：`BacktestEngine(initial_capital, commission_rate)` 旧调用零改动;`Portfolio.execute_buy/sell` 新增可选 `commission`/`stamp_duty` 参数,缺省走旧路径。
- **测试**：新增 `tests/test_backtest_constraints.py`(18 用例),覆盖成本模型/T+1/涨跌停/防未来函数/向后兼容。113 个量化相关测试全部通过。

## v1.8.1 - 2026-06-24

### 修复与开箱体验
- **行情涨跌幅修正**:腾讯兜底源失效时拉不到最新交易日 → 昨收取陈旧值、涨跌幅严重失真甚至恒为 0。新增**东方财富 push2his 直连**兜底,取价链路 `akshare hist → 东财直连 → 腾讯`,保证开高低收 / 昨收 / 涨跌幅准确。
- **「自定义 API 接口」开箱即用**:发布版默认 `ALLOW_LOCAL_LLM_BASE_URL=1` 放行自定义 Base URL;首次启动**自动生成持久 `AI_FINANCE_MASTER_KEY`**(每台独立、安全),保存自定义 Provider 的 Key 无需手动配置主密钥、不再依赖不安全的开发回退密钥。
- **预置常用股行情种子**:打包内置常用蓝筹 / 港股近 1 年日线,开箱即有正确价格与涨跌幅;首次启动后行情源自动补到最新交易日。

## v1.8.0 - 2026-06-19

### 多源内容能力接出为可用模块(融合 UZI-Skill,MIT)
- **龙虎榜/游资**:机构 vs 游资席位拆分 + 24 游资席位库匹配 + 近月活跃龙虎榜;杀猪盘 8 信号检测。
- **估值建模**:DCF(WACC+两阶段+5×5 敏感性)/ Comps / Quick LBO / 三表;可调假设情景分析。
- **投资人库**:59 位投资人 persona,可搜索浏览、多选一键组建专家团(桥接为 agent)或导出团队提示词。
- **研报质量门控**:确定性机械检查(禁空话/覆盖率/矛盾呈现/免责),critical 不清零拒绝发布;导出 `?gate`。

### 工作台与体验
- **自选晨报**:自选股后端持久化 + 每日聚合行情/新闻,展开内嵌估值/游资。
- **成本可见**:顶栏成本药丸(今日/7天/30天/累计 + 按模型),`/api/diagnostics/cost-summary`。
- **首次引导向导**;**研究成果一键导出 Markdown**;四个新模块统一美化 + 响应式适配。

### 工程
- 新增 10 个 API 路由 + 6 个前端模块;CI 转绿(修 `fastapi.testclient` 采集错误,版本断言改为 pyproject 单一来源)。
- 第二次全面检修:ruff 全后端 0 问题、全套 1044 测试通过、实跑端点冒烟(估值真实数据闭环)、龙虎榜未知 market 稳健性修复。

## v1.7.4 - 2026-06-05

### 年K与自定义周期
- 新增 Workbench `年K` 周期，后端支持 `frequency=1y`，从日线按自然年聚合 OHLC、成交量和成交额。
- 新增 Workbench `自定义` 周期入口，支持选择 `分时 / 日K / 周K / 月K / 年K` 粒度和对应窗口大小。
- 年K横轴显示年份，月K继续显示月份，避免把月K标签抽样误认为半年K。
- 新增年线聚合回归测试，覆盖 `normalize_frequency("年K")`、年线窗口和年度 OHLC 聚合。
- Browser-Use 实测通过：年K与自定义年K均显示年度刻度，页面 fresh `warn/error=0`。

## v1.7.3 - 2026-06-05

### K 线周期日期联动修复
- 修复 Workbench K 线周期切换后横轴日期粒度没有稳定跟随的问题。
- `分时` 兜底数据改为按分钟生成，横轴显示 `HH:mm`。
- `日K`、`周K` 横轴保持 `MM-DD`，`月K` 横轴显示 `YYYY-MM`。
- Browser-Use 实测通过：分时、日K、周K、月K 四个周期横轴均与当前选项对应，临时验证页 fresh `warn/error=0`。

## v1.7.2 - 2026-06-05

### 图表稳定与一键启动复验

- 新增 `StableChartContainer`，在容器尺寸可用后以数字宽高渲染 Recharts 图表，避免首次布局、动画切换和隐藏页签触发 `width(-1)` / `height(-1)` warning。
- 替换 Workbench、Portfolio、Backtesting、MultimodalChart、FundDcaLab 中的直接 `ResponsiveContainer` 用法。
- 修复 K 线/多模态页本地预览数据的日期生成逻辑，避免出现 `05-32`、`05-48` 等非法日期刻度。
- 版本号统一升至 `1.7.2`，覆盖 `pyproject.toml`、前端 package、桌面启动器和 Inno Setup 配置。
- 重新生成 Windows portable 目录和 `AlphaScope-portable.zip`，并确认 `_internal/pyproject.toml`、`_internal/akshare/file_fold/calendar.json`、`_internal/apps/web/dist/index.html` 均在包内。
- 打包版烟测通过：`/health` 返回 `1.7.2`，`/api/prices/600519?limit=3` 返回 `success=true`、`source_status=ok`、`degraded=false`。
- Browser-Use 打开最终打包页面后，新增 console `warning=0`、`error=0`、Recharts warning `0`。

## v1.7.1 - 2026-06-04

### 已知问题修复与一键启动交付
- 修复通用文件上传文件名安全问题，保存前规范化文件名并约束最终路径位于上传目录内。
- 修复顶部搜索框 Enter 键误选择建议列表第一项的问题。
- 修复 `/api/analysis/run` 在所有 Agent 失败时仍返回成功 envelope 的问题，新增 `analysis_all_agents_failed` 错误码。
- 新增服务端股票池 CSV 导出接口 `/api/quant/stock-pool/export`，前端导出优先使用服务端端点。
- 修复 Workbench 首屏 Recharts 容器高度警告。
- 补齐 React 类型依赖和前端类型定义，恢复 `npm run lint` 与生产构建通过。
- API 版本改为读取 `pyproject.toml`，CORS 默认限制到本地来源。
- 重新验证 Windows portable 打包链路，`python build.py --zip` 可生成 `AlphaScope.exe` 和 `AlphaScope-portable.zip`。

## v1.7.0 - 2026-06-01

### 安全与真实性修复

- 知识库上传文件名改为去除路径组件并规范化非法字符，保存路径和 metadata 不再使用客户端原始文件名。
- Workbench 材料上传改为真实调用 `/api/knowledge/upload`，仅在后端确认成功后显示上传成功，失败时显示错误。
- `/api/analysis/run` 改为读取真实行情并拒绝空行情 / 零值行情，避免后端生成未标注的正常分析成功响应。
- 新闻与技术指标接口增加 `limit`、`days`、`window`、`lookback` 上限，防止超大请求驱动过量工作。
- Provider 模型列表获取移入 worker thread 并增加超时，避免阻塞 async API 路径。
- 新增上传安全、资源限制、分析保护和设置超时回归测试；定向回归 `42 passed`。

## v1.6.0 - 2026-05-31

### 新闻研究流与可配置 Agent

- 新增新版 Windows 一键安装包构建链路，`python build.py --installer` 会构建 React Web、打包 FastAPI 桌面启动器并生成 Inno Setup 安装包。
- 打包版启动器改为自动启动本地 FastAPI 和静态 Web 前端，自动写入运行时 API 地址并打开浏览器。
- 新增 GitHub Actions `Windows Installer` 工作流，可为 tag/release 生成 `AlphaScope-Setup-*.exe` 和便携 zip。
- 新闻模块新增详情弹层，可查看正文、来源、分类、影响、情绪和 AI 摘要。
- 新闻模块新增 AI 助手，支持选中新闻咨询，也支持解析用户输入的新闻链接。
- 新闻原文跳转改为优先打开真实来源；缺失真实链接时按标题、标的和来源降级到搜索跳转。
- 新闻源概览改为可收起，避免遮挡新闻列表。
- 新增 `agentConfigs` 前端配置模块，支持 Agent 数量、启用状态、名称、角色、职责、提示词、模型、温度和图标配置。
- Agent 编排迁移到系统设置页签；专家圆桌页回归运行监控视图。
- 分析请求 `run` 与 `async` 会携带启用中的 `agent_configs`。
- 清理当前前端可见品牌残留和旧内部代号，更新前端 package 与 release 文档。
- 前端 `npm run lint` 与 `npm run build` 通过，保留既有 Vite chunk size warning。

## v1.5.0 - 2026-05-30

### AlphaScope 过渡发布

- 项目更名与工作台发布链路整理。
- 为 v1.6.0 桌面分发、模型路由和新闻/研报体验增强做准备。

## v1.4.2 - 2026-05-28

### 品牌迁移与本地体验稳定性

- 项目正式更名为「研策中枢 AlphaScope」，README、前端 README、clone 地址和 Release 链接迁移到 `https://github.com/TIANWEN-cpu/AlphaScope`。
- 修复本地回测入口在后端短暂离线或策略状态过期后卡死的问题；点击运行会自动刷新本地回测状态和策略列表。
- 回测页新增“刷新状态”，并在本地 quant 接口不可用时给出明确诊断提示。
- 新闻模块刷新失败时保留上次成功结果，不再直接清空列表；空态提供“重新同步”。
- 后端新闻出库层修复历史 UTF-8/latin1 乱码字段，新闻标题、摘要、来源和公告字段恢复正常中文展示。
- 新增 `/api/settings/preferences` GET/PUT 接口和 `app_preferences` SQLite 持久化表。
- 系统设置的基础设置、网络节点、安全组、数据管理页签接入真实表单和保存操作，不再显示“配置项暂未接入”。
- 新增设置偏好与新闻乱码修复测试；前端 `npm run lint` 通过，后端定向回归 `52 passed`。

## v1.0.1 - 2026-05-22

### Windows 前端与启动修复

- 修复 v0.85 Windows 一键包遗留问题：PowerShell UTF-8 无 BOM 脚本在 GB2312 环境下解析失败。
- 修复 `start_local.ps1` 使用 `npm` 可能误打开 Notepad，导致 Next.js 3000 端口未正确启动。
- 修复 `stop_local.ps1` 使用 `$pid` 与 PowerShell 内置变量冲突的问题。
- 增强停止脚本：递归停止进程树，清理端口 3000/8000/8501 和残留 Next.js 子进程。
- 新增 `apps/web/postcss.config.js`，修复 v1.0 主前端 Tailwind CSS 未输出、`layout.css` 404、页面呈现裸 HTML 的问题。
- 启动前清理 `apps/web/.next`，避免 `next build` 覆盖 dev server 缓存后 CSS 404。
- 重做 Next.js 主工作台 UI：左侧研究控制台、中间分析区、右侧研究监控面板。
- 修复 `/health` 版本号仍为 `0.50.0` 的问题，统一为 `1.0.1`。
- 更新前端 package 版本为 `1.0.1`，补充 v1.0.1 release notes。

## v1.0 - 2026-05-21

### 正式版发布

- 本地一键启动
- 主工作台（Next.js）
- API 配置（5 家 LLM 厂商）
- 专家团分析（10 位专家）
- K 线图分析（视觉 AI）
- 文件上传（图片/PDF/CSV/Excel）
- 报告保存和导出
- 历史记录持久化
- 本地备份恢复
- 完整用户手册
- 测试全绿（697 passed）

## v0.90 - 2026-05-21

### Release Candidate

- 功能冻结，进入稳定化阶段
- 全面测试验证（697 tests passed）
- Lint 和格式化检查通过
- Next.js 构建验证通过
- CI 全绿
- 整理 release notes
- 更新用户手册

## v0.85 - 2026-05-21

### Windows 一键包

- 新增 `AlphaScope-Setup.bat` 一键安装启动器
- 新增 `scripts/install_deps.ps1` 自动依赖安装
- 新增 `scripts/create_shortcut.ps1` 桌面快捷方式创建
- 增强 `scripts/check_env.py` 支持 `--fix` 自动修复
- 增强 `scripts/start_local.ps1` 支持首次运行检测
- 更新 `scripts/start_local.bat` 集成首次运行安装

## v0.81 - 2026-05-21

### User Manual

- 完整用户手册，包含 8 个章节
  - 安装指南 - 环境准备与安装步骤
  - 快速开始 - 5 分钟上手流程
  - 模型接入配置 - LLM API Key 配置
  - 数据源接入 - 20+ 数据源配置
  - 专家团使用 - 10 位专家协作分析
  - K 线图分析 - 视觉 AI 技术分析
  - 报告管理与导出 - 查看、搜索、导出
  - 常见问题与故障排除 - FAQ 与诊断

## v0.15 - 2026-05-20

### Provider Plugin Architecture

- Refactored `_auto_register_providers()` to use dynamic module scanning (`importlib` + `pkgutil`). All 20 providers are now auto-discovered -- no more hardcoded imports in registry.py.
- Added `custom_providers/` directory for user-created data sources. Drop a file, configure in YAML, done.
- Added `scripts/create_provider.py` -- CLI generator for provider skeletons.
- Added `BaseProvider.is_available()` classmethod for dependency checking before instantiation.
- Added `ProviderRegistry.reload()` for hot-reload during development.
- Dashboard source health panel now shows built-in vs custom provider distinction with reload button.
- All 11 previously unregistered providers (finnhub, fred, northbound, google_trends, reddit, stocktwits, wikipedia_views, choice, ifind, jy, wind) are now auto-discovered.

## v0.14 - 2026-05-19

### News Section Overhaul

**Root cause fixes for empty concept/industry news:**

- `fetch_stock_concepts` — rewrote from serial 50-board scan to East Money datacenter API (`RPT_F10_CORETHEME_BOARDTYPE`), 1 HTTP request returns all boards in <1s.
- `fetch_industry_name` — added datacenter API as primary source, uses `board_type="行业"` to reliably identify industry boards. Fixed misidentification (e.g. "权重股" for 宁德时代 → "电力设备").
- `fetch_keyword_news_em` — fixed Chinese keyword URL encoding in search cookie (`urllib.parse.quote`), which caused `curl_cffi` latin-1 encoding error returning 0 results.

### Concept Relevance Sorting

- Uses `IS_PRECISE` and `BOARD_RANK` fields from datacenter API to sort concepts by relevance.
- Precise matches (★) ranked first, then industry boards, then generic/index boards.
- Example: 贵州茅台 → ★白酒, ★超级品牌, ★电商概念 (instead of 大盘股, 标准普尔, 央视50).

### News Tags

- `get_concept_news` and `get_industry_news` now attach `matched_keywords` to each news item.
- Dashboard displays matched keywords as colored tag chips below each news title.
- Concept news tags (blue), industry news tags (amber).
- `fetch_keyword_news_em` results include `topic` field showing the search keyword.

### Cache Optimization

- Concept/industry/main-business cache TTL reduced from 86400s (24h) to 3600s (1h).
- Concept blacklist reduced from 12 to 5 entries.

### Dependencies

- Fixed `curl_cffi` import failure silently returning `[]` — added `requests` as fallback HTTP client.

## v0.13.1 - 2026-05-19

### Utility Modules
- Added `backend/utils/datetime_util.py` — datetime parsing and timezone normalization for Chinese financial data sources. Handles 10+ datetime formats, normalizes to Asia/Shanghai timezone.
- Added `backend/utils/tracer.py` — lightweight span-based tracing system with thread-safe ring buffer, context manager and decorator APIs. Can be optionally upgraded to OpenTelemetry.

### Code Review Fixes
- Fixed `frontend/dashboard.py`: removed duplicate `@st.cache_data` decorator on `get_stock_list()`, fixed undefined `logger` reference.
- Fixed `backend/utils/tracer.py`: thread-safe `_trace_counter` increment in `start_span()`.
- Fixed `backend/archive.py`: removed redundant `import re` inside function body.
- Fixed `backend/expert_panel.py`: `TypeError` in `__main__` self-test when printing evidence dicts.
- Fixed `backend/archive_tagger.py`: `_save_index()` now uses atomic write (temp file + replace).
- Fixed `backend/storage/db.py`: added `threading.Lock` around all `insert_*` + `commit` operations to prevent concurrent SQLite writes.

### Pipeline
- Pipeline `_to_news_row` / `_to_report_row` / `_to_announcement_row` now normalize datetime strings via `normalize_dt_str()`.
- Added `@st.cache_data(ttl=300)` to `get_stock_list()` in dashboard.

### Dependencies
- Pinned all dependency versions in `requirements.txt` with `==`.

### Tests
- Added `tests/test_agent_modes.py` — 27 tests for AnalysisMode enum, AgentModeEntry, AgentModeConfig, ModeResolver singleton (including thread safety), and convenience functions.
- Added `tests/test_datetime_util.py` — tests for datetime parsing across 10+ formats, timezone normalization, and display formatting.
- Added `tests/test_tracer.py` — tests for Span, Tracer ring buffer, traced context manager, traced_func decorator, and stats.

## v0.13.0 - 2026-05-19

### Agent Mode System (Highest Priority)
- Added `backend/agent_modes.py` — three-tier analysis mode system: Standard (3 agents, DeepSeek, fast/cheap), Deep (5 agents + critic + chairman, Claude/GPT, full analysis), Auto (pre-screen then escalate if ambiguous).
- Added `config/models.yaml` — declarative model configuration replacing hardcoded `AGENT_MODEL_CONFIG`, supports hot-reload.
- Added `run_agents_with_mode()` in `llm_agents.py` — mode-aware agent execution with automatic evidence/factor injection based on mode.
- Added `_run_auto_mode()` — quick pre-screen with cheap model, escalates to full DEEP analysis if confidence is between 30-70.
- Dashboard sidebar now has mode selector radio button (标准/深入/自动).
- Analysis results show mode indicator badge with escalation status.

### New Data Sources (7 Providers)
- Added `backend/providers/finnhub_provider.py` — US stock sentiment, insider trading, ESG data (free tier: 60 req/min).
- Added `backend/providers/fred_provider.py` — Federal Reserve Economic Data, 800,000+ economic time series (completely free).
- Added `backend/providers/northbound_provider.py` — 沪深港通北向资金 flow data (free via AkShare).
- Added `backend/providers/reddit_provider.py` — r/wallstreetbets sentiment via PRAW (free, 60 req/min).
- Added `backend/providers/google_trends_provider.py` — retail attention via search volume (free, 50 req/day).
- Added `backend/providers/stocktwits_provider.py` — US retail sentiment with bullish/bearish voting (free REST API).
- Added `backend/providers/wikipedia_views_provider.py` — company page views as attention indicator (free REST API).

### Evidence Aggregator
- Added `backend/quality/evidence_aggregator.py` — cross-source data validation, multi-source confidence boost, contradiction detection.
- Replaces simple "first one wins" fallback with "collect and cross-validate from N sources".

### Anomaly Detector
- Added `backend/quality/anomaly_detector.py` — detects zero/negative prices, limit-up/down violations, garbled titles, duplicate timestamps.

### Prompt Injection Protection
- Added `validate_stock_code()` in `validators.py` — whitelist validation for 6-digit A-share codes.
- Added `sanitize_prompt_input()` — removes injection patterns (ignore instructions, system prompt, jailbreak attempts).
- Added `sanitize_stock_data_for_prompt()` — validates stock code and sanitizes text fields before LLM prompts.

### Thread-Safe Singletons
- Fixed `DataPipeline`, `Database`, `VectorStore` singletons with double-checked locking via `threading.Lock()`.
- Fixed Retriever error propagation: now raises `ResourceUnavailableError` instead of returning `None`.

### BaseProvider Enhancement
- Added new fields to `BaseProvider`: `data_class`, `freshness`, `cost_tier`, `rate_limit`, `requires_key`.
- Enables intelligent routing based on data category, freshness requirements, and cost constraints.

### Engineering Hardening
- Added `.github/workflows/ci.yml` — GitHub Actions CI with ruff lint + pytest on Python 3.10/3.11/3.12.
- Added `.env.example` — complete environment variable template with all required API keys.
- Added `Makefile` — unified commands: `make test`, `make lint`, `make run`, `make docker-build`.
- Updated `docker-compose.yml` — added resource limits (CPU/memory) and health checks.
- Moved 9 stray test files from `backend/` to `tests/probes/`.

### Data Pipeline Integration
- Added `backend/pipeline.py` — `DataPipeline` class wiring Provider → Dedup → SourceRank → SQLite → ChromaDB into a unified ingestion flow.
- Pipeline supports: `ingest_news()`, `ingest_reports()`, `ingest_announcements()`, `ingest_prices()`, `ingest_fundamentals()`, `ingest_fund_flow()`, `search_evidence()`.
- All pipeline operations are logged to `source_fetch_logs` for observability.

### Ingestion Scheduler Jobs
- Added `backend/ingestion/jobs.py` — concrete fetch jobs for CN news (5min), CN reports (1hr), CN announcements (1hr), market snapshot (1hr), CN prices (daily), US SEC filings (15min).
- `create_default_scheduler()` factory creates a fully configured `DataScheduler` with all default jobs.

### Provider Fixes
- **HKEX Provider**: Implemented proper HTML parsing for HKEXnews search results with fallback link extraction.
- **SEC Provider**: Implemented ticker-to-CIK lookup using SEC's official `company_tickers.json` with in-memory caching. Fixed `_symbol_to_cik()` to return actual CIK numbers.

### Event Extraction
- Added `backend/events/extractor.py` — rule-based event extractor classifying news/announcements into 8 event types (earnings, dividend, M&A, financing, litigation, policy, supply_chain, insider) with sentiment scoring and importance rating.
- Pipeline automatically enriches news with event_type/sentiment and announcements with category during ingestion.
- Supports batch extraction via `extract_events_from_news()` and `extract_events_from_announcements()`.

### Quantitative Factor Generation
- Added `backend/factors/generator.py` — `FactorGenerator` computing 5 factor dimensions: news sentiment, event signal, analyst rating, fund flow, price momentum.
- All factors normalized to [-1.0, 1.0] with configurable weights for composite scoring.
- `fetch_factor_context()` in `llm_agents.py` injects factor analysis into agent market briefs.
- `run_all_agents()` and `run_batch_critic()` now include factor context for more informed analysis.
- Added `frontend/components/factor_panel.py` — interactive factor display in the Agent analysis tab.
- Updated `critic.md` with 7th scoring dimension: factor consistency.

### Evidence-Driven Agent Output
- Added `fetch_evidence_context()` in `llm_agents.py` — retrieves RAG evidence and formats it for agent prompts.
- `build_market_brief()` now accepts optional `evidence_context` and `factor_context` parameters.
- `run_all_agents()` automatically fetches evidence + factor context before building the market brief.
- Updated `critic.md` with 6th/7th scoring dimensions: evidence coverage rate, factor consistency.
- `build_critic_prompt()` now accepts `available_evidence` and `factor_context` parameters.

### Frontend: Source Health Dashboard
- Added Tab 10 "📊 数据源健康" to the Streamlit dashboard.
- New `frontend/components/source_health_panel.py` — displays Provider health table, fetch log statistics, RAG index status, and database record counts.
- Added `render_trust_badge()` helper for S/A/B/C/D trust level display.

### Tests
- Added `tests/test_schema_models.py` — tests for all Pydantic models (NewsItem, ResearchReport, Announcement, PriceBar, FundFlow, EvidenceItem, EvidenceBundle, AgentReport).
- Added `tests/test_dedup.py` — tests for Deduplicator fingerprint and dedup logic.
- Added `tests/test_source_rank.py` — tests for SourceRanker trust scoring and ranking.
- Added `tests/test_db.py` — tests for Database insert/upsert with temporary SQLite.
- Added `tests/test_scheduler.py` — tests for FetchJob tick/execute and DataScheduler lifecycle.
- Added `tests/test_pipeline.py` — tests for DataPipeline data conversion and status.
- Added `tests/test_sec_provider.py` — tests for SEC CIK lookup and filing parsing.
- Added `tests/test_hkex_provider.py` — tests for HKEX HTML parsing and category guessing.
- Added `tests/test_factors.py` — tests for FactorGenerator, FactorReport, rating scores, event category scores, and convenience functions.

### Integration
- Updated `news_data.py` `fetch_*_via_provider()` functions to route through `DataPipeline` first (v0.12), then Provider Registry (v0.11), then original functions (fallback).
- Updated dashboard footer to v0.12.

## v0.11.0 - 2026-05-18

### Provider Plugin Architecture
- Added `backend/providers/` with `BaseProvider` abstract class and `ProviderRegistry` for automatic source selection, priority ranking, and failover.
- Implemented 9 concrete providers: AkShare, Tushare Pro, BaoStock, OpenBB, SEC EDGAR, HKEXnews, CNInfo, CLS, EastMoney.
- Added `config/data_sources.yaml` for centralized provider configuration (enabled/disabled, priority, timeout, retry).

### Standardized Data Models
- Added `backend/schemas/` with Pydantic models: `NewsItem`, `ResearchReport`, `Announcement`, `PriceBar`, `FundFlow`, `EvidenceItem`, `EvidenceBundle`, `AgentReport`.
- All provider outputs now conform to standardized schemas for consistent downstream consumption.

### Data Quality Layer
- Added `backend/quality/dedup.py` — fingerprint-based deduplication for news, reports, and announcements.
- Added `backend/quality/source_rank.py` — source trust level scoring (S/A/B/C/D) from config.

### Storage Layer
- Added `backend/storage/db.py` — SQLite database with 6 core tables: `news_items`, `research_reports`, `announcements`, `price_bars`, `source_fetch_logs`, `evidence_items`.

### Ingestion Pipeline
- Added `backend/ingestion/scheduler.py` — `DataScheduler` with configurable fetch intervals and health tracking.

### RAG Layer
- Added `backend/rag/chunker.py` — `TextChunker` for document segmentation.
- Added `backend/rag/vector_store.py` — ChromaDB-backed vector store with collection management.
- Added `backend/rag/retriever.py` — unified retriever integrating chunking and vector search.

### Observability
- Added `backend/observability/source_health.py` — `SourceHealthMonitor` for provider status tracking and reporting.

### Docker Support
- Added `Dockerfile` with multi-stage build and health check.
- Added `docker-compose.yml` with app + Redis services.

### Integration
- Extended `news_data.py` with `fetch_news_via_provider()`, `fetch_reports_via_provider()`, `fetch_announcements_via_provider()` that route through Provider Registry with automatic fallback to existing functions.
- Updated `requirements.txt` with new dependencies: pydantic, tenacity, aiohttp, chromadb, apscheduler.

## v0.10.6 - 2026-05-18

- Isolated fallback LLM credentials so provider-specific or custom API keys are not reused when switching to the DeepSeek fallback.
- Rejected private, local, and otherwise non-public custom LLM base URLs by default unless explicitly enabled through environment configuration.
- Hardened archive file handling with safe names, archive-root path checks, and atomic index writes.
- Improved Eastmoney search handling with no-cookie first requests, validated article URLs, and an explicit `curl_cffi` dependency.
- Replaced broad JSON-object extraction with balanced-brace scanning for LLM responses.
- Made AI chat hot-reload compatibility use function signature inspection instead of TypeError string matching.
- Loaded fundamentals data sources in parallel on cache misses.
