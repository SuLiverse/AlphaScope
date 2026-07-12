# 可复现研究快照

AlphaScope 的研究报告支持显式指定 `as_of` 数据截止日和 `research_question`。目标是让单模型、多 Agent 或不同版本之间的比较使用同一信息集，避免未来数据穿越和证据编号漂移。

## 截止规则

启用 `as_of` 后：

- 行情查询使用 `end_date=as_of`，报告中的最新价和技术指标只来自截止日前数据；
- RAG 证据必须具有可解析日期且 `published_at/data_date/date <= as_of`；无日期材料被排除；
- 证据池只检索一次，同一份列表同时用于 Prompt 中的 `[n]` 编号、`evidence_id` 反链和可信度评分；
- 未支持历史版本的实时量化因子会被排除，而不是悄悄混入当前值；
- 证据时效性以截止日为参照计算，不以运行当天为参照；
- 未来截止日返回 HTTP 422。

不传 `as_of` 时仍可正常运行，但 `research_snapshot.warnings` 会提示该结果属于动态快照，后续重跑可能看到更新数据。

## API 示例

同步和异步分析使用相同字段：

```json
{
  "stock_symbol": "600519",
  "stock_name": "贵州茅台",
  "mode": "deep",
  "as_of": "2026-06-30",
  "research_question": "未来两个季度的利润增长是否可持续？"
}
```

可调用：

- `POST /api/analysis/run`
- `POST /api/analysis/async`

分析响应新增 `research_snapshot`：

```json
{
  "snapshot_id": "85b7ca94568248a1",
  "requested_as_of": "2026-06-30",
  "effective_as_of": "2026-06-30",
  "cutoff_enforced": true,
  "price_data_date": "2026-06-30",
  "latest_evidence_date": "2026-06-29",
  "evidence_count": 6,
  "undated_evidence_count": 0,
  "factor_data_policy": "excluded_unversioned",
  "research_question": "未来两个季度的利润增长是否可持续？",
  "warnings": []
}
```

## 快照哈希

`snapshot_id` 是以下内容的稳定 SHA-256 短哈希：

- 标的、截止日和研究问题；
- 行情日期及核心价格/均线值；
- 因子数据策略；
- 排序后的证据 ID、来源、日期和正文摘要。

相同输入与相同数据会得到相同 ID；价格被修订、证据正文变化、研究问题或截止日变化都会生成新 ID。研究记忆会保存该 ID、截止日和研究问题。

## 已知边界

- 快照哈希用于识别输入数据版本，不代表数据来源本身不可篡改。
- 历史截止模式宁可排除无日期材料，也不推测发布日期。
- 尚未支持历史版本的因子不会参与历史报告；后续只有在因子存储具备明确 `data_date` 后才应开放。
- 同一截止日比较模型时，还应固定 Provider、模型版本、Prompt、Token 预算和降级状态。
