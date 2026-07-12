# 研究质量评测

AlphaScope 分开衡量两件事：

1. **研究是否可审计**：结论有没有来源、数据日期、时效性和独立交叉验证。
2. **结论是否有效**：预测或判断在事后是否与真实结果一致。

`research_trust` 只回答第一件事。高可信不等于一定正确或盈利，它表示读者能够检查这份研究是如何得出结论的。

## 研究可信度

`backend.quality.research_trust.assess_research_trust` 使用确定性评分卡，不调用 LLM。总分为 0-100：

| 维度 | 权重 | 含义 |
|------|------|------|
| 证据覆盖率 | 25 | 有多少分析席位绑定了证据 |
| 来源完整度 | 15 | 证据是否注明来源 |
| 日期完整度 | 15 | 证据是否提供可解析的数据日期 |
| 时效性 | 15 | 按证据类型计算时间衰减 |
| 来源质量 | 15 | 使用 `data_sources.yaml` 的 S/A/B/C/D 分级 |
| 来源多样性 | 15 | 是否至少有三个独立来源交叉验证 |

尚未消解的冲突和已识别的缺证结论会额外扣分。等级为：

- `high`：80-100
- `medium`：60-79
- `low`：35-59
- `insufficient`：0-34

新闻、行情和资金流衰减较快；公告、研报、基本面和宏观数据使用更长半衰期。缺失或无法解析的日期不再获得默认时效分。

主分析接口会返回 `research_trust`；Markdown 报告会展示评分、来源数、日期完整度和待复核事项。低于 35 分时，研报机械门控会阻止发布方向性结论。
研究记忆快照同时保存 `trust_score` / `trust_grade`，时间线汇总提供最新与平均可信度，可用于观察工作流升级是否真的改善研究质量。

## 基线比较

使用同一标的、同一数据快照和同一研究问题，分别保存单模型基线与候选多 Agent 输出，然后调用：

```http
POST /api/quality/research-compare
```

```json
{
  "as_of": "2026-06-30",
  "baseline": {
    "evidence": [{"claim": "利润增长"}]
  },
  "candidate": {
    "evidence": [
      {"claim": "利润增长", "source": "cninfo", "type": "announcement", "data_date": "2026-06-30"},
      {"claim": "利润增长", "source": "tushare", "type": "fundamental", "data_date": "2026-06-30"}
    ]
  }
}
```

历史评分的时效性以 `as_of` 为参照。正式对比前应先确认两次分析返回相同的 `research_snapshot.snapshot_id`；完整截止规则见 `reproducible-research.md`。

响应包含双方评分、总分差、逐维度差异和 `candidate_better` / `baseline_better` / `tie`。建议至少固定以下实验条件：

- 相同数据截止时间，禁止候选方案看到更新数据；
- 相同研究问题与输出预算；
- 保存 Provider、模型、提示词版本和降级状态；
- 同时记录延迟、Token 成本和失败率；
- 人工盲评时隐藏模型与工作流名称。

## 其他评测

### Agent 输出质量

The Critic scores each agent on a 0-100 scale across 7 dimensions:

| Dimension | What It Measures |
|-----------|-----------------|
| Evidence quality | Are claims backed by actual data? |
| Logical consistency | Does the conclusion follow from the evidence? |
| Contradiction detection | Does the output contradict the market brief? |
| Missing evidence | Did the agent ignore relevant data? |
| Overconfidence | High conviction + weak evidence? |
| Evidence coverage | What fraction of available evidence was used? |
| Factor consistency | Does the conclusion align with quantitative factors? |

Archived decisions include these scores, enabling longitudinal analysis.

### 模型组合表现

Each archived decision stores the full model combination snapshot:

```json
{
  "agent_models": {
    "fundamentals": {"vendor": "claude", "model": "claude-sonnet-4-5", "signal": "buy", "confidence": 75},
    "technicals": {"vendor": "gpt", "model": "gpt-5.2", "signal": "hold", "confidence": 60},
    ...
  },
  "combo_signature": "claude-sonnet-4-5|gpt-5.2|deepseek-chat|...",
  "fallback_count": 0
}
```

This enables queries like: "What's the win rate when Claude + GPT agree but DeepSeek disagrees?"

### 数据链路可靠性

Tracked via `source_fetch_logs` table:

- Fetch success/failure rate per provider
- Latency per provider
- Record counts per fetch
- Error messages for failed fetches

Visible in the "Source Health" dashboard tab.

### 去重有效性

The Deduplicator uses content fingerprinting. Metrics:

- Duplicate rate across sources (expected: 15-30% for major news)
- False positive rate (legitimate distinct articles incorrectly merged)

### 事件抽取准确率

The rule-based event extractor classifies into 8 types:

- Earnings, Dividend, M&A, Financing, Litigation, Policy, Supply Chain, Insider

Each event gets a sentiment score (-1 to +1) and importance rating (1-5).

## 方法与复现

自动测试覆盖证据归一化、分类型时间衰减、评分、惩罚上限、基线比较、API、报告展示和发布门控：

```bash
python -m pytest tests/test_research_trust.py tests/test_evidence_chain.py tests/test_report_gate.py tests/test_quality_api.py -q
```

全量回归：

```bash
python -m pytest -m "not network" -q
```

## 已知边界

- 可信度评分衡量可审计性，不衡量未来收益或预测准确率。
- 来源分级仍需通过人工审计和数据许可变化持续维护。
- 尚无覆盖所有行业与市场状态的人工标注黄金集。
- RAG 检索的召回率、引用忠实度和 Critic 分数仍需与专家盲评校准。

## 案例：贵州茅台（600519）

Heterogeneous architecture produced "divergent views, suggest 30% pilot position":

- Fundamentals (Claude): bullish — product price increase
- Technicals (GPT): bullish — MA5 crossed above MA20, MACD histogram positive
- Risk Control (SenseNova): bearish — main force net outflow -4.461B over 5 days
- Retail Behavior (Mimo): caution — retail inflow + main outflow = potential bag-holding
- Sentiment (DeepSeek): identified "institutions selling into good news"

Final vote: **1 buy / 0 sell / 4 hold**. Chairman (Claude Opus) produced executive decision with:
- Position: 30% pilot
- Stop loss: MA60 or -7%
- Add signal: breakout above 1750 + main force return

This demonstrated the value of model diversity: no single model captured the full picture.

涉及真实 LLM 的效果实验需要有效 API Key；可信度评分和比较器不需要网络或模型，可以在 CI 中稳定复现。
