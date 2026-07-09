# 研策中枢 AlphaScope v1.8.0

发布日期：2026-06-19

v1.8.0 是一次能力与体验的大版本:把多源「内容深度」补齐为可用界面,并打通从分析 → 估值 → 龙虎榜 → 自选晨报 → 一键组队 → 导出 的研究闭环。全程纯增量,未删改既有功能;后端全套 **1044 测试通过**,前端 `tsc` + `vite build` 全绿。

## 下载

- Windows 便携版:`dist/AlphaScope/`(直接运行 `AlphaScope.exe`)
- Windows 安装包:`AlphaScope-Setup-1.8.0.exe`(需 Inno Setup 构建,或经 GitHub Actions `windows-installer` 工作流产出)

## 新增 · 数据与能力(融合开源 UZI-Skill,MIT)

- **龙虎榜 / 游资**:A 股「机构 vs 游资」席位拆分、24 位知名游资席位库匹配、近月活跃龙虎榜板块参考;**杀猪盘检测**(8 信号网搜扫描)。
- **机构级估值建模**:DCF(WACC + 两阶段 + 5×5 敏感性)、Comps 同业对比、Quick LBO、三表预测;支持**可调假设情景分析**(一阶段增速 / 永续增速 / Beta)。
- **投资人库**:扩充至 **59 位**投资大佬 persona(巴菲特、段永平、冯柳、张坤、游资 + Dalio/Munger/Graham/Soros…);可搜索浏览、多选**一键组建专家团**(桥接为 agent 后入「多Agent网络」)或导出团队提示词。
- **研报质量门控(确定性)**:`/api/quality/report-gate` 对报告跑机械检查(禁空话、覆盖率、矛盾呈现、免责声明等),critical 不清零即判不可发布;导出支持 `?gate`。

## 新增 · 工作台与体验

- **自选晨报**:自选股(后端持久化 + localStorage)每日聚合最新价 / 涨跌幅 / 新闻,可展开内嵌**估值 + 游资**摘要。
- **成本可见**:顶栏成本药丸展示今日 / 近 7 天 / 近 30 天 / 累计 LLM 调用花费,按模型明细(`/api/diagnostics/cost-summary`)。
- **首次引导向导**:未配置模型时引导选服务商 → 填 Key → 测连接 → 开始用。
- **研究成果一键导出**:对话研报、估值、龙虎榜结果导出 Markdown。
- **界面美化**:四个新模块统一渐变卡片 + 图标光晕 + 平滑悬停;响应式适配(`px-4 sm:px-6`、`flex-wrap`、断点栅格);克制的机构研报风格。

## 工程健康

- 新增 **10 个 API 路由** + **6 个前端模块**(估值建模 / 龙虎榜·游资 / 投资人库 / 自选晨报 + 成本药丸 + 引导)。
- CI 转绿:修复 `fastapi.testclient` 采集错误,版本断言改为从 `pyproject.toml` 单一来源派生(永不再过时)。
- 第二次全面检修:`ruff` 全后端 0 问题、全套 1044 测试通过、实跑端点冒烟(估值用真实财务数据闭环)、修复龙虎榜对未知 market 标的的稳健性。

## 验证

```bash
cd apps/web && npm run lint && npm run build
python -m pytest -q          # 1044 passed, 1 skipped
python -m ruff check backend  # All checks passed
python build.py               # 产出 dist/AlphaScope 便携版
```

> 免责声明:本项目用于研究与辅助分析,不构成投资建议。所有输出请结合真实数据与个人判断独立核验。
