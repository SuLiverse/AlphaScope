# 研策中枢 AlphaScope 前端与接口检修审计文档

生成日期：2026-05-24  
项目目录：`D:\研策中枢 AlphaScope\AlphaScope`

## 一、当前结论

本轮检修已完成 P0/P1 主链路修复，并对 P2 中最容易误导用户的假数据、伪 AI、伪实盘、静默失败和无效交互做了收口。当前 Vite React 前端可以完成构建和 TypeScript 检查；后端 SSE、Settings、Agent runtime 等关键契约已补回归测试。

当前仍不建议直接发布、打 tag 或创建 release，主要原因是尚未完成系统性浏览器真实点击流手测，且文档/API 数量等 P3 漂移仍需统一收口。后续发布前应以本文档的“收尾状态”作为验收 checklist。

## 二、实际验证结果

在 `D:\研策中枢 AlphaScope\AlphaScope` 下执行验证：

| 项目 | 结果 | 说明 |
|---|---:|---|
| `npm --prefix apps/web run build` | 通过 | Vite build 成功，仍保留既有 chunk 体积警告 |
| `npm --prefix apps/web run lint` | 通过 | 当前脚本为 `tsc --noEmit` |
| `python -m ruff check backend tests` | 通过 | All checks passed |
| `python -m ruff format --check backend tests` | 通过 | 221 files already formatted |
| `python -m pytest tests/test_sse_contract.py tests/test_settings.py tests/test_runtime_orchestrator.py tests/test_agent_editor.py tests/test_api.py tests/test_quant_api.py tests/test_funds_api.py -q` | 通过 | 历史通过记录；当前量化回测已改为本地引擎，不再保留旧外部适配测试 |
| `python -m pytest tests/ -q` | 通过 | 802 passed, 2 skipped |
| `python -m pip check` | 未复跑 | 首轮检查通过，本轮未改依赖 |
| `npm audit --audit-level=moderate` | 未复跑 | 首轮检查通过，本轮未改依赖 |

## 三、收尾状态（2026-05-25）

### 已完成

- P0 SSE 契约：orchestrator 异常恢复 JSON 500，status 事件携带 `conversation_id`，隐式 mode 不再强制覆盖自动路由。
- P1 Settings：Provider 管理接入后端，保存响应不回显明文 API Key，空 key 更新保留旧密钥。
- P1 Workbench：模式选择、上传入口、分析配置、全屏、SSE 错误解析、失败提示已接入真实交互。
- P1 Portfolio：基金组合语义、空持仓状态、后端数据图表、最大单项占比等已修复。
- P1 Backtesting：策略参数、业务 `status` 失败、运行记录、未接入编译/创建流程提示已修复。
- P1 ReportGenerator：数据源失败/空状态、模板差异、报告日期/编号、全失败不生成报告等已修复。
- P1 AgentsSystem：启停写入 `/api/manage/agents`，standard/deep/auto runtime 实际读取 managed configs。
- P2 NewsAggregator：移除本地新闻 fallback，新闻/公告/详情/搜索失败可见，ticker 接当前标的最新价，宏观 ticker 与日历标演示，固定 Alpha/评级已移除。
- P2 FundDcaLab：本地模板问答明确标注未调用后端 AI，伪专家会签/AI 交易员/超额阿尔法等口吻已清理。
- P2 Backtesting 占位：实盘比对、AI 策略进化、默认随机曲线与指标均改为运行记录/本地演示/待接入说明。
- P2 Settings 未开放 tab：不再显示升级企业节点占位按钮，改为“暂未接入后端持久化接口”。

### 发布前仍需完成

- 系统性浏览器真实点击流手测：Workbench、Settings、Portfolio、Backtesting、ReportGenerator、AgentsSystem、NewsAggregator、FundDcaLab。
- 系统性浏览器真实点击流手测完成后，复跑 `npm --prefix apps/web run lint`、`npm --prefix apps/web run build` 和 `python -m pytest tests/ -q` 作为发布前最终确认。
- P3 文档漂移：README/HANDOFF/docs/release notes 中的 Next.js/Vite、测试数量、API 数量等需统一更新。

## 四、必须优先修复的问题（历史记录，当前多项已完成）

> 本节保留首轮审计发现的历史上下文；具体完成状态以第三节“收尾状态”为准。

### 1. SSE 错误契约被改坏，导致后端测试失败（已修复）

测试位置：

- `tests/test_sse_contract.py:186`
- `tests/test_sse_contract.py:199`

当前测试要求 orchestrator 异常时返回 JSON 500：

```python
assert resp.status_code == 500
```

当前实现位置：

- `backend/api/main.py:297`
- `backend/api/main.py:306`

修复状态：已恢复原契约，orchestrator 异常返回 JSON 500；相关 SSE contract test 已通过。

### 2. SSE status 事件没有返回 `conversation_id`（已修复）

前端依赖位置：

- `apps/web/src/components/Workbench.tsx:258`

后端当前事件位置：

- `backend/api/main.py:244`

前端等待：

```ts
if (event.type === 'status' && event.data?.conversation_id) {
  setConversationId(...)
}
```

修复状态：status 事件已携带 `data.conversation_id`，前端可保存新会话 ID；相关 SSE contract test 已通过。

### 3. Portfolio 页面错误复用基金组合接口

前端位置：

- `apps/web/src/components/Portfolio.tsx:68`
- `apps/web/src/components/Portfolio.tsx:72`

后端位置：

- `backend/api/funds.py:217`

当前前端把股票标的如 `600519 / 贵州茅台` 写入基金组合接口 `/api/fund-portfolio`，字段伪装成 `fund_code / fund_name`。这会造成业务语义错配，并可能污染基金组合数据。

后续修复方向：

- 若该页面定位为基金组合，则 UI 文案和输入必须改成基金组合；
- 若该页面定位为股票组合，则不要调用 `/api/fund-portfolio`，应新增或接入真正的股票组合接口。

### 4. Portfolio 后端数据加载后，核心图表仍使用硬编码假数据

位置：

- `apps/web/src/components/Portfolio.tsx:136`
- `apps/web/src/components/Portfolio.tsx:157`

当前 `loadPortfolios()` 会更新 `portfolioData`，但饼图和图例仍使用 `PORTFOLIO_DATA`。这会导致接口成功后用户仍看到假数据。

后续修复方向：

- 饼图和图例统一改用 `portfolioData`；
- 补齐后端字段映射，例如 `current_value`。

## 四、前端无效交互清单

### Workbench

1. `apps/web/src/components/Workbench.tsx:525`  
   `标准分析` 下拉按钮没有 `onClick`，点击无反应。

2. `apps/web/src/components/Workbench.tsx:533`  
   AI 面板最大化按钮没有 `onClick`，点击无反应。

3. `apps/web/src/components/Workbench.tsx:593`  
   “上传 K 线截图或本地研报”入口没有文件 input、没有上传逻辑、没有跳转逻辑。

4. `apps/web/src/components/Workbench.tsx:596`  
   `分析配置` 按钮没有 `onClick`，无法配置分析参数。

5. `apps/web/src/components/Workbench.tsx:278`  
   聊天接口失败后直接写入 `[本地回退]`，容易掩盖真实失败。

### AgentsSystem

6. `apps/web/src/components/AgentsSystem.tsx:93`  
   `全网拓扑` 按钮没有 `onClick`。

7. `apps/web/src/components/AgentsSystem.tsx:64`  
   Agent 启停只改本地 `idle/analyzing` 状态，没有调用后端。

8. `apps/web/src/components/AgentsSystem.tsx:161`  
   触发启停的按钮会调用本地假逻辑，不会改变后端 Agent 状态。

### Backtesting

9. `apps/web/src/components/Backtesting.tsx:216`  
   `回测参数` 按钮只是切换本地 tab，不是真正配置或提交参数。

10. `apps/web/src/components/Backtesting.tsx:335`  
    `编译为 Python 策略` 按钮没有 `onClick`。

11. `apps/web/src/components/Backtesting.tsx:360`  
    `+ 创建新策略` 按钮没有 `onClick`。

12. `apps/web/src/components/Backtesting.tsx:387`  
    策略设置齿轮按钮没有 `onClick`。

13. `apps/web/src/components/Backtesting.tsx:407`  
    “股票池解析”和“实盘比对”基本是占位内容，没有真实上传、解析或比对流程。

### Portfolio

14. `apps/web/src/components/Portfolio.tsx:42`  
    前端金额字段未读取 `current_value`，可能导致组合估值显示为 0 或权重。

15. `apps/web/src/components/Portfolio.tsx:136`  
    饼图使用硬编码 `PORTFOLIO_DATA`，不使用后端加载的 `portfolioData`。

16. `apps/web/src/components/Portfolio.tsx:157`  
    图例使用硬编码 `PORTFOLIO_DATA`，不使用后端加载的 `portfolioData`。

### Settings

17. `apps/web/src/components/Settings.tsx:167`  
    API Key `Modify` 按钮没有 `onClick`。

18. `apps/web/src/components/Settings.tsx:191`  
    `重置所有连接` 没有 `onClick`。

19. `apps/web/src/components/Settings.tsx:194`  
    `保存更改` 没有 `onClick`。

20. `apps/web/src/components/Settings.tsx:202`  
    `general/network/security/data` 等 tab 多数只是“配置项未开放”。

21. `apps/web/src/components/Settings.tsx:217`  
    `UPGRADE_REQUIRED` 按钮没有 `onClick`。

### NewsAggregator

22. `apps/web/src/components/NewsAggregator.tsx:225`  
    新闻详情拉取失败后没有错误提示、没有重试入口，基本静默。

23. `apps/web/src/components/NewsAggregator.tsx:292`  
    顶部行情 ticker 是硬编码假行情，刷新新闻不会更新该区域。

### ReportGenerator

24. `apps/web/src/components/ReportGenerator.tsx:94`  
    使用 `Promise.allSettled`，接口失败后继续用空对象拼报告。

25. `apps/web/src/components/ReportGenerator.tsx:102`  
    失败数据被吞掉，用户难以知道哪些模块生成失败。

26. `apps/web/src/components/ReportGenerator.tsx:159`  
    生成流程结束后无条件 `setReportGenerated(true)`，即使后端全失败也会显示报告已生成。

### FundDcaLab

27. `apps/web/src/components/FundDcaLab.tsx:1035`  
    智囊团问答完全本地模拟，没有调用后端 AI 或聊天接口。

28. `apps/web/src/components/FundDcaLab.tsx:1928`  
    预置问题入口触发的是本地模板回答。

29. `apps/web/src/components/FundDcaLab.tsx:1971`  
    自定义提问入口触发的是本地模板回答。

## 五、前后端 API/契约风险

### 1. `/api/agents` 与 `/api/manage/agents` 语义混杂

前端调用：

- `apps/web/src/lib/api.ts:262`

后端存在两类语义：

- `/api/agents`：默认 Agent 配置；
- `/api/manage/agents`：Agent 管理 API。

风险：用户在管理接口新增或修改 Agent 后，前端 Agent 页面不一定能反映持久化配置。

### 2. `ApiResponse` 前端类型缺少后端字段

前端位置：

- `apps/web/src/lib/api.ts:1`

后端 `ApiResponse` 包含 `error_code / trace_id / source / tool_call_id / evidence_ids` 等字段，但前端类型只声明 `success / data / error / message`。

风险：错误码和追踪信息被类型层面忽略，不利于做精确错误提示和调试。

### 3. `request()` 强依赖 JSON 响应

位置：

- `apps/web/src/lib/api.ts:178`

如果代理、502、HTML 错误页或非 JSON 响应出现，`response.json()` 会直接抛错，导致 HTTP 状态细节丢失。

### 4. 基金定投模拟返回字段需继续核对

后端位置：

- `backend/api/funds.py:164`
- `backend/api/funds.py:195`

模拟器内部曾存在 `fund_code` 为空字符串的风险，当前路由层尝试 `result.fund_code = body.fund_code`。后续应通过测试确认响应中的 `fund_code` 一定正确。

## 六、文档与实际状态漂移

### 1. Next.js 与 Vite 表述混杂

仍含 Next.js 表述的文件包括：

- `HANDOFF.md:17`
- `HANDOFF.md:32`
- `HANDOFF.md:83`
- `HANDOFF.md:92`
- `HANDOFF.md:114`
- `CHANGELOG.md`
- `RELEASE-NOTES-v1.0.md`
- `RELEASE-NOTES-v1.0.1.md`
- `docs/frontend-redesign-plan.md`
- `reference-frontend/SOURCE.md`

当前实际主前端已切换为 Vite React。

### 2. 测试数量表述不一致

发现的表述包括：

- `HANDOFF.md:30`：697 个通过
- `README.md:252`：793 tests
- `docs/deployment.md:112`：431 tests
- `CHANGELOG.md` 和 release notes 中仍有 697 tests

当前实际验证结果是：`792 passed, 1 failed, 2 skipped`。

### 3. API 端点数量表述不一致

发现的表述包括：

- `README.md:57`：113 endpoints
- `README.md:152`：113 endpoints across 17 router modules
- `docs/api.md:3`：27 个 REST 端点
- `docs/architecture.md:10`：27 endpoints

需要统一为当前实际 API 数量，或改成不易漂移的描述。

### 4. `FRONTEND_ADAPTATION_REPORT.md` 与依赖实际不一致

报告说移除了 `recharts / clsx / tailwind-merge`，但当前 `apps/web/package.json` 仍包含：

- `clsx`
- `recharts`
- `tailwind-merge`

而代码也仍在使用相关能力，因此报告需要修正。

## 七、检修优先级

### P0：先恢复工程可信度

1. 修复 SSE 异常契约，使 `python -m pytest tests/ -q` 全绿。
2. 给 SSE status 事件补 `conversation_id`，并增加测试。
3. 保持 `ruff check`、`ruff format --check`、`npm run build`、`npm run lint` 全部通过。

### P1：修复用户最容易点击到的无效交互

1. Settings：API Key 编辑、保存、重置必须真实可用。
2. Workbench：分析模式、上传入口、分析配置、聊天失败提示。
3. Portfolio：图表和图例使用真实后端数据；修正基金/股票组合语义。
4. Backtesting：策略创建、策略编译、参数配置、策略设置齿轮。
5. ReportGenerator：后端失败不能伪装成报告生成成功。

### P2：清理假数据和占位页

1. NewsAggregator 顶部行情 ticker 接后端或标注为演示。
2. FundDcaLab 智囊团问答接后端聊天或明确标注本地模板。
3. Backtesting 的股票池解析、实盘比对补真实流程或移除入口。
4. Settings 未开放 tab 要么实现，要么隐藏。

### P3：文档与发布前整理

1. 统一 README、HANDOFF、docs、release notes 中的前端栈描述。
2. 统一测试数量和 API 数量表述。
3. 修正 `FRONTEND_ADAPTATION_REPORT.md` 中与实际依赖不一致的内容。
4. 发布前重新跑完整验证命令。

## 八、后续每轮检修要求

每次修复一个模块后，至少执行：

```bash
python -m pytest tests/ -q
python -m ruff check backend/ frontend/ tests/
python -m ruff format --check backend/ frontend/ tests/
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

涉及前端交互的修复，还必须实际启动前后端并在浏览器验证对应交互：

```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
npm --prefix apps/web run dev
```

验证时记录：

- 点击哪个入口；
- 是否调用后端；
- 成功状态如何显示；
- 失败状态如何显示；
- 是否还有本地假数据或静默失败。

## 九、建议下一步

下一步建议从 P0 开始：

1. 修 `backend/api/main.py` 的 SSE 异常返回契约；
2. 补 `conversation_id` 到 SSE status 事件；
3. 跑完整测试；
4. 测试全绿后再进入 Settings 和 Workbench 的交互修复。
