# 研策中枢 AlphaScope v1.9.22

发布日期：2026-06-27

v1.9.22 是自 v1.9.0 以来的一次**大幅功能扩展 + 工程加固**汇总版本:量化研究链路(Phase 2/3)全面补齐,Agent 编排新增风控否决/结论溯源/多空辩论,前端 K 线迁移到 Lightweight Charts 并新增监控、研究记忆、多维报告图表;同时完成 CI 全绿、前端 `strict` + ESLint 接入等工程基线加固。纯增量与修复,未删改既有功能。

## 下载

- Windows 安装包:`AlphaScope-Setup-1.9.22.exe`(双击安装)
- Windows 便携版:`AlphaScope-portable.zip`(解压后运行 `AlphaScope.exe`)

## 量化研究(Phase 2 / Phase 3 全集)

- **数据湖 DuckDB/Parquet**:列式物化 + 跨标的批量选股 / 因子扫描(`/api/datalake/*`)。
- **因子注册中心 / 研究流水线**:统一因子目录 + 确定性技术因子 + 缓存 + 因子矩阵。
- **样本外走查 walk-forward**、**筹码分布**、**策略横向对比榜**、**实验记录持久化**。
- **遗传算法策略参数寻优**、**通达信(TDX)公式编译器**、**低代码策略编辑器 + custom_rule 规则策略**。
- **K 线形态识别**(图上标记)。
- 回测可信度底线:真实 A 股交易摩擦。

## Agent 与编排

- **风控独立一票否决 gate**(决策期)。
- **Agent 结论可溯源**:绑定 `evidence_id`,结论可反查证据。
- **多空辩论裁决 debate**(后端 + 编排接入 + 前端面板)。
- **数据核验 Agent**(CSV/Excel 数据源接入)。

## 数据源与数据质量

- **TickFlow HTTP/JSON 自定义数据表**:接口拉取 + 字段映射入查询面。
- **ProviderCapability 能力 schema** + **数据源质量评分** + 统计指标基准对比/超额收益/信息比率。

## 前端与可视化

- **K 线迁移到 Lightweight Charts**(主仪表盘 + 分包优化)。
- **系统监控中心**、**研究记忆**(同一股票结论随时间变化追踪)。
- **FinRobot 式多维报告图表**:9 图一屏俯瞰。

## 工程与稳定性(本次基线加固)

- **CI 全绿**:修复 ruff lint(9 项)、统一 ruff 格式、测试网络门禁(`-m "not network"`)、CI 增装 API 依赖;编排/证据/风控测试与环境密钥解耦,无 key 也确定性通过。
- **前端类型基线**:开启 `tsconfig strict`,接入 **ESLint**(typescript-eslint + react-hooks)到 lint 门禁,清零全部 warning;修复一个 `useMemo` 条件调用的 hooks 真 bug。
- 版本号三处对齐(1.9.22)、ReportGenerator mock 定时器卸载清理、文档与实现对齐。

## 升级说明

- 直接安装覆盖即可;本地 `data/` 与 `.env` 保留。
- 桌面包启动会自动生成本地 API token 并注入前端(CSRF 纵深防御);命令行 dev 模式(`make api` + `make web-dev`)不强制 token。

## 验证

- 离线测试套件 `pytest -m "not network"` 全绿(1350 passed);`ruff check` / `ruff format --check` 通过。
- 前端 `tsc --noEmit` 0 error、`eslint` 0 problem、`vite build` 通过。
- CI 四个 job(lint-and-test 3.11/3.12、web-build、docker-build)全部通过。
