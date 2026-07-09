# 研策中枢 AlphaScope 前端适配与交互整改报告

生成日期：2026-05-24  
项目目录：`D:\研策中枢 AlphaScope\AlphaScope`  
前端目录：`D:\研策中枢 AlphaScope\AlphaScope\apps\web`  
用户前端来源：`C:\Users\admin\Desktop\alphascope-workbench (2)`  
本地前端地址：`http://127.0.0.1:3000`  
本地后端地址：`http://127.0.0.1:8000`

## 一、总体目标

本次工作目标是将主项目 `AlphaScope` 的前端替换为用户编写的 `alphascope-workbench (2)` 前端，并在保留原前端视觉、动画、排版和模块结构的基础上，把大量静态展示改造成可操作、可请求后端、可反馈状态的实用工作台。

重点整改范围包括：

- 搜索功能可用化。
- 新闻列表、新闻搜索、新闻原文跳转可用化。
- K线、技术指标、图表与后端行情接口适配。
- 工作台、证据链、研报、回测、组合、基金定投等模块接入对应后端接口。
- 保留用户前端的布局、动效、视觉风格，不做大幅重设计。

## 二、主要完成内容

### 1. 前端工程从 Next.js 切换为 Vite React

原项目 `apps/web` 是 Next.js 结构，本次已整体适配为 Vite React 前端。

主要处理：

- 新增 Vite 入口：`index.html`、`src/main.tsx`、`src/App.tsx`。
- 新增 Vite 配置：`vite.config.ts`。
- 更新 `package.json` 脚本：
  - `dev` 使用 `vite --port=3000 --host=0.0.0.0`
  - `build` 使用 `vite build`
  - `lint` 使用 `tsc --noEmit`
- 更新 `Dockerfile`、`.dockerignore`、`docker-compose.yml`，使容器启动方式适配 Vite。
- 更新本地启动/停止脚本：
  - `scripts/start_local.ps1`
  - `scripts/stop_local.ps1`
- 更新 README 和部署/架构/本地启动文档中的前端说明。

### 2. 扩展统一 API 客户端

文件：`apps/web/src/lib/api.ts`

新增和扩展了统一请求封装，前端模块不再各自拼接散乱 URL。

新增/补充的接口能力包括：

- 行情：
  - `prices`
  - `latestPrice`
  - `normalizeSymbol`
  - `priceFetch`
- 技术指标：
  - `technical`
  - `technicalSupportResistance`
- 新闻：
  - `news`
  - `announcements`
  - `newsSearch`
  - `newsDetail`
  - `newsEvents`
  - `newsImpact`
- 基本面与资金流：
  - `fundamentals`
  - `fundFlow`
  - `factors`
- 证据链：
  - `evidenceList`
  - `evidenceCreate`
  - `evidenceDelete`
  - `evidenceChain`
- 研报归档：
  - `archiveList`
  - `archiveReport`
- 量化回测：
  - `quantStatus`
  - `quantStrategies`
  - `quantRuns`
  - `quantBacktest`
  - `quantReloadStrategies`
- 基金与定投：
  - `fundSearch`
  - `fundInfo`
  - `fundNav`
  - `fundMetrics`
  - `fundDcaSimulate`
  - `fundPortfolios`
  - `fundPortfolioCreate`
  - `fundReportGenerate`
- 视觉分析：
  - `visionAnalyze`
  - `visionReport`
- 聊天流：
  - `streamChat`

### 3. 全局股票状态打通

文件：`apps/web/src/App.tsx`

新增全局 `activeStock`，默认标的为：

- 股票代码：`600519`
- 股票名称：`贵州茅台`
- 市场：`SH`

已将当前标的传递给以下模块：

- `Workbench`
- `NewsAggregator`
- `MultimodalChart`
- `ReportGenerator`
- `EvidenceChain`
- `Backtesting`
- `Portfolio`

这样用户在顶部搜索切换标的后，行情、新闻、图表、证据、研报、回测等页面都会围绕当前标的工作。

### 4. 顶部搜索栏整改

文件：`apps/web/src/components/TopBar.tsx`

原搜索框基本只是本地解析输入。现已改为：

- 支持输入股票代码或常见名称。
- 调用 `/api/prices/normalize/{symbol}` 做后端标准化。
- 调用 `/api/prices/{symbol}/fetch` 同步行情。
- 搜索后更新全局当前标的。
- 增加状态提示。
- 增加当前标的行情刷新按钮。
- 增加浏览器全屏切换按钮。

### 5. 工作台整改

文件：`apps/web/src/components/Workbench.tsx`

已接入：

- `/api/prices/{symbol}`
- `/api/prices/{symbol}/latest`
- `/api/fundamentals/{symbol}`
- `/api/news`
- `/api/fund-flow/{symbol}`
- `/api/factors/{symbol}`
- `/api/chat/stream`

完成效果：

- 行情图使用后端 K 线数据。
- 当前价格使用后端最新价格。
- 财务指标使用后端基本面数据。
- 新闻列表使用后端新闻。
- 新闻项支持打开原文链接。
- 主力资金卡片使用后端资金流数据。
- 量化因子面板显示后端因子报告。
- 聊天面板走后端 SSE 流式接口。
- 刷新按钮会重新触发行情拉取和图表刷新。

### 6. 新闻聚合页整改

文件：`apps/web/src/components/NewsAggregator.tsx`

已接入：

- `/api/news`
- `/api/news/announcements`
- `/api/news/search`
- `/api/news/{news_id}`

完成效果：

- 新闻和公告从后端加载。
- 搜索框支持后端全文检索。
- 增加刷新按钮。
- 新闻详情点击后可拉取详情。
- 若后端返回 `source_url`，可打开新闻原文。
- 右侧分析面板展示选中新闻的来源、时间、摘要和原文入口。

### 7. K线 / 多模态图表整改

文件：`apps/web/src/components/MultimodalChart.tsx`

已接入：

- `/api/prices/{symbol}`
- `/api/prices/{symbol}/fetch`
- `/api/technical/{symbol}`
- `/api/vision/report`

完成效果：

- K线数据优先使用后端真实行情。
- MA、MACD、RSI、布林线等指标根据后端行情计算/展示。
- 支撑位、压力位来自后端技术指标结果。
- 仍保留原有视觉 AI 预设图模式。
- 新增上传 K 线截图入口。
- 上传截图后可调用后端视觉报告接口。
- “保存记录”可导出当前技术诊断 Markdown。

### 8. 证据链整改

文件：`apps/web/src/components/EvidenceChain.tsx`

已接入：

- `/api/evidence`
- `/api/evidence/{id}`
- `/api/evidence/chain`

完成效果：

- 证据列表从后端加载。
- 新增证据会写入后端。
- 删除证据会调用后端删除。
- “构建证据链”调用后端证据链构建接口。
- 右侧审计面板显示后端或本地证据详情。
- 后端无数据时保留本地样例作为兜底展示。

### 9. 研报生成器整改

文件：`apps/web/src/components/ReportGenerator.tsx`

已接入：

- `/api/fundamentals/{symbol}`
- `/api/factors/{symbol}`
- `/api/news`
- `/api/fund-flow/{symbol}`
- `/api/archive`

完成效果：

- 生成报告时并行聚合基本面、因子、新闻、资金流、归档报告。
- 报告正文不再只使用固定静态文案。
- 左侧仍保留模板、评级、标的选择。
- 右侧报告目录和预览保留原动画与排版。
- 下载按钮可导出 Markdown。
- 打印按钮调用浏览器打印。

### 10. 回测模块整改

文件：`apps/web/src/components/Backtesting.tsx`

已接入：

- `/api/quant/status`
- `/api/quant/strategies`
- `/api/quant/runs`
- `/api/quant/backtest`

完成效果：

- 页面加载时检查本地量化回测引擎状态。
- 策略下拉框来自后端策略列表。
- 可以设置策略、日期区间、初始资金。
- “启动单票/组合回测”会向后端提交回测。
- 成功后更新收益曲线和指标卡。
- 后端不可用时显示真实错误，不再假装成功。
- 运行记录页展示后端同步的运行记录。

### 11. 投资组合模块整改

文件：`apps/web/src/components/Portfolio.tsx`

已接入：

- `/api/fund-portfolio`
- `/api/fund-portfolio` 创建接口

完成效果：

- 组合数据优先从后端加载。
- 后端无组合时显示演示组合，并提供一键创建当前标的研究组合。
- 组合饼图、估值、持仓数量、最近操作都可根据后端数据更新。

### 12. 基金定投模块整改

文件：`apps/web/src/components/FundDcaLab.tsx`

已接入：

- `/api/funds/{code}`
- `/api/funds/{code}/metrics`
- `/api/funds/{code}/nav`
- `/api/fund-dca/simulate`

完成效果：

- 选择基金时会尝试同步后端基金信息、指标和净值。
- 保留原本复杂的本地沙盒模拟能力。
- 新增“后端真实净值模拟”按钮。
- 后端模拟成功后，用真实净值定投结果更新图表、流水和核心指标。
- 后端不可用时保留本地模拟并显示状态。

### 13. Agent 与设置页基础接入

文件：

- `apps/web/src/components/AgentsSystem.tsx`
- `apps/web/src/components/Settings.tsx`

完成效果：

- Agent 页面读取 `/api/agents`。
- 设置页读取 `/health` 和 `/api/settings/providers`。
- API 地址在设置页可见。

### 14. 后端聊天兼容修复

文件：

- `backend/api/main.py`
- `backend/ai_assistant/orchestrator.py`

处理内容：

- 修复 `/api/chat/stream` 对 `mode` 的转换。
- 增加异常捕获，避免模型配置错误时直接 500。
- 修复 orchestrator 包导入路径，优先使用 `backend.*` 导入。

## 三、删除了哪些文件

说明：这些删除发生在主项目 `D:\研策中枢 AlphaScope\AlphaScope\apps\web` 的旧 Next.js 前端中，用于替换为用户提供的 Vite React 前端。没有删除 `docs/` 目录下的文档文件，`docs/` 下只是做了内容更新。

### 1. 删除的旧前端配置文件

- `apps/web/.eslintrc.json`
- `apps/web/next-env.d.ts`
- `apps/web/next.config.js`
- `apps/web/postcss.config.js`
- `apps/web/tailwind.config.js`

删除原因：

- 旧项目是 Next.js + 旧 Tailwind/PostCSS 配置。
- 新前端为 Vite React，使用新的 `vite.config.ts`、`index.html`、`src/main.tsx` 入口。

### 2. 删除的旧 Next.js app 目录文件

- `apps/web/src/app/error.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/app/layout.tsx`
- `apps/web/src/app/page.tsx`

删除原因：

- Vite React 不使用 Next.js `src/app` 路由结构。
- 新入口为 `apps/web/src/App.tsx` 和 `apps/web/src/main.tsx`。

### 3. 删除的旧前端组件

- `apps/web/src/components/AIAgentPanel.tsx`
- `apps/web/src/components/AgentAnalysisPanel.tsx`
- `apps/web/src/components/AnalysisPanel.tsx`
- `apps/web/src/components/ArchivePanel.tsx`
- `apps/web/src/components/ChatInput.tsx`
- `apps/web/src/components/DataDetailPanel.tsx`
- `apps/web/src/components/DataTabsPanel.tsx`
- `apps/web/src/components/ExpertPanel.tsx`
- `apps/web/src/components/FundDcaPanel.tsx`
- `apps/web/src/components/FundFlowPanel.tsx`
- `apps/web/src/components/FundamentalsPanel.tsx`
- `apps/web/src/components/HealthPanel.tsx`
- `apps/web/src/components/KLinePanel.tsx`
- `apps/web/src/components/MessageBubble.tsx`
- `apps/web/src/components/NewsPanel.tsx`
- `apps/web/src/components/PortfolioPanel.tsx`
- `apps/web/src/components/QuantLabPanel.tsx`
- `apps/web/src/components/SettingsPanel.tsx`
- `apps/web/src/components/SidebarRail.tsx`
- `apps/web/src/components/TaskCenter.tsx`

删除原因：

- 这些是旧 Next.js 前端的一组面板组件。
- 用户要求将项目整体前端换成 `alphascope-workbench (2)` 中的新前端。
- 新前端对应的新组件已经加入，例如：
  - `Workbench.tsx`
  - `NewsAggregator.tsx`
  - `MultimodalChart.tsx`
  - `Backtesting.tsx`
  - `FundDcaLab.tsx`
  - `ReportGenerator.tsx`
  - `EvidenceChain.tsx`
  - `Portfolio.tsx`
  - `Settings.tsx`
  - `AgentsSystem.tsx`

### 4. 删除的旧 Hook

- `apps/web/src/hooks/useChat.ts`

删除原因：

- 旧聊天 Hook 属于原 Next.js 前端。
- 新工作台聊天逻辑已在 `Workbench.tsx` 内通过统一 API 客户端 `api.streamChat` 调用 `/api/chat/stream`。

## 四、新增了哪些主要文件

### 1. 新增 Vite 前端工程文件

- `apps/web/.env.example`
- `apps/web/.gitignore`
- `apps/web/README.md`
- `apps/web/index.html`
- `apps/web/metadata.json`
- `apps/web/vite.config.ts`
- `apps/web/src/main.tsx`
- `apps/web/src/App.tsx`
- `apps/web/src/index.css`
- `apps/web/src/types.ts`
- `apps/web/src/vite-env.d.ts`

### 2. 新增用户前端组件

- `apps/web/src/components/AgentsSystem.tsx`
- `apps/web/src/components/Backtesting.tsx`
- `apps/web/src/components/EvidenceChain.tsx`
- `apps/web/src/components/FundDcaLab.tsx`
- `apps/web/src/components/MultimodalChart.tsx`
- `apps/web/src/components/NewsAggregator.tsx`
- `apps/web/src/components/PlaceholderModule.tsx`
- `apps/web/src/components/Portfolio.tsx`
- `apps/web/src/components/ReportGenerator.tsx`
- `apps/web/src/components/Settings.tsx`
- `apps/web/src/components/Workbench.tsx`

## 五、修改了哪些已有文件

### 1. 前端工程配置

- `apps/web/package.json`
- `apps/web/package-lock.json`
- `apps/web/tsconfig.json`
- `apps/web/Dockerfile`
- `apps/web/.dockerignore`

### 2. 前端核心代码

- `apps/web/src/lib/api.ts`
- `apps/web/src/components/TopBar.tsx`
- `apps/web/src/components/Sidebar.tsx`

### 3. 后端兼容修复

- `backend/api/main.py`
- `backend/ai_assistant/orchestrator.py`

### 4. 项目启动和部署

- `docker-compose.yml`
- `Makefile`
- `scripts/start_local.ps1`
- `scripts/stop_local.ps1`

### 5. 文档更新

以下文档只是更新，没有删除：

- `README.md`
- `docs/architecture.md`
- `docs/deployment.md`
- `docs/local-quickstart.md`
- `docs/user-manual/01-installation.md`

更新内容主要是把前端说明从 Next.js 改为 Vite React，并同步本地启动、部署、架构中的前端端口和命令。

## 六、验证结果

已执行并通过：

```powershell
npm run lint
npm run build
python -m pytest tests/test_smoke.py -q
```

结果：

- TypeScript 类型检查通过。
- Vite 生产构建通过。
- 后端 smoke 测试通过：`5 passed`。
- 本地前端服务可访问：`http://127.0.0.1:3000`。
- 后端基础接口可访问：
  - `/health`
  - `/api/prices/600519`
  - `/api/news`
  - `/api/technical/600519`

构建提示：

- `npm run build` 有 Vite chunk 体积超过 500 KB 的提示。
- 这是构建警告，不是错误。
- 后续如需优化，可对大页面做动态 import/code splitting。

## 七、当前限制与注意事项

1. 部分后端接口依赖本地数据源或模型供应商配置。
   - 量化回测实验室已改为本地引擎执行，不再要求额外启动回测监听服务。
   - 前端会显示真实错误，不再用假成功覆盖。

2. 视觉分析和 AI 聊天依赖模型供应商配置。
   - API Key 无效或模型不可用时，接口会返回错误文本。
   - 前端不会崩溃，但结果质量取决于后端配置。

3. 新闻数据中存在历史导入编码异常样本。
   - 前端功能已接通，但部分后端旧样本内容可能出现乱码。
   - 这是后端数据内容问题，不是前端渲染链路问题。

4. 基金、组合、证据链等模块均已接入后端。
   - 后端无数据时，前端会显示演示兜底数据或提示。
   - 新增证据、创建组合等操作会调用后端持久化接口。

## 八、结论

本次已完成主项目与用户前端的整体适配，并对大量静态模块进行了实用化改造。现在前端不再只是展示页面，而是可以围绕当前股票标的调用后端行情、新闻、技术指标、因子、资金流、证据链、研报、回测、基金和组合接口。

被删除的内容主要是旧 Next.js 前端文件和旧前端组件；`docs/` 下文档没有删除，只做了适配 Vite React 的内容更新。