# 研策中枢 AlphaScope v1.4.1

> 2026-05-27

v1.4.1 是 v1.4 前端工作台的稳定性补丁，重点修复真实运行中发现的主力资金为空、量化因子资金维度缺失、研报目录交互不稳定以及 README 展示不足的问题。

## Highlights

- 主力资金流改为带超时的 Eastmoney 直连源，避免 AkShare 无超时请求导致页面等待或资金卡片为空。
- 成功资金流数据会写入本地缓存；上游波动时返回缓存数据并明确标记 `degraded/source_status/cached_at`。
- 量化因子能正确使用资金流数据，缓存可用时不再把 `fund_flow` 标记为缺失维度。
- Workbench 资金卡片区分真实数据、缓存数据和降级空态。
- 研报目录改为显式滚动正文容器，修正文案和下载按钮显示。
- README 增加工作台、数据源终端、研报生成截图。
- 脱敏历史计划文档中的测试 API Key 字符串。

## Fixed

### Fund Flow

- 新增 `backend.fund_flow._fetch_individual_fund_flow_eastmoney()`，直接调用东方财富资金流接口。
- 请求使用独立 session 并关闭环境代理继承，避免本地代理导致 HTTP 源不稳定。
- 请求设置连接/读取超时，避免外部源阻塞 FastAPI 请求线程。
- 标准化字段解析为现有 `summarize_fund_flow()` 可消费的 DataFrame schema。
- 新增本地 JSON cache：`data/cache/fund_flow/`。

### API Degradation

- `/api/fund-flow/{symbol}` 返回真实来源元数据：
  - `source`
  - `source_status`
  - `degraded`
  - `error`
  - `cached_at`
- 缓存命中时 API 仍返回 records 和 summary，同时 `error_code=FUND_FLOW_DEGRADED`。
- 大盘资金流缓存保留 `akshare` 来源标记，个股资金流缓存保留 `eastmoney` 来源标记。

### Factor Generator

- 缓存资金流数据会进入 `degraded_inputs`，但不会进入 `missing_dimensions`。
- 实测 `/api/factors/600519` 可返回非零 `fund_flow`，并且 `missing_dimensions=[]`。

### Frontend

- Workbench 资金卡片在缓存可用时显示数值并标注“缓存”，不再显示为全空。
- 因子面板对资金流降级来源给出更准确说明。
- 研报目录滚动改为定位到报告正文滚动容器。
- 研报生成页修正“研究对象”等文案，下载按钮改为“下载 Markdown”。

## Screenshots

### Workbench

![Workbench](docs/assets/v1.4.1/workbench.png)

### News Terminal

![News Terminal](docs/assets/v1.4.1/news-terminal.png)

### Report Generator

![Report Generator](docs/assets/v1.4.1/report-generator.png)

## Verification

Backend targeted regression:

```text
52 passed
```

Frontend:

```text
npm run lint   passed
npm run build  passed
```

Runtime probes:

```text
/api/fund-flow/600519?days=30
  records=30
  source=eastmoney
  source_status=ok
  degraded=false

/api/factors/600519
  fund_flow=0.369
  degraded_inputs=[]
  missing_dimensions=[]

/api/news?symbol=600519&limit=8
  count=8
```

## Known Notes

- Vite build still reports the existing large chunk warning.
- External data source availability depends on local network and third-party service stability.
- This release does not contain the user-provided test API keys and does not require committing local runtime artifacts.
