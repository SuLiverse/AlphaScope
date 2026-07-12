# 证据链引擎

v0.49 新增功能。支持证据存储、来源可信度、时间衰减、多源一致性、反方证据检测。

## 功能概述

| 功能 | 说明 |
|------|------|
| 证据存储 | CRUD 操作，SQLite 持久化 |
| 结论-证据绑定 | evidence_links 表关联证据与结论 |
| 来源可信度 | S/A/B/C/D 五级，基于 data_sources.yaml |
| 时间衰减 | 按证据类型使用不同半衰期；缺失日期记为 0 |
| 多源一致性 | 同结论多源确认 → 置信度提升 |
| 反方证据 | 同组内买入/卖出信号冲突检测 |
| 证据缺失 | 关键结论无证据时警告 |
| 研究可信度 | 统一输出覆盖率、来源、日期、时效性、质量和多样性评分 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/evidence` | 证据列表 |
| GET | `/api/evidence/{id}` | 证据详情 |
| POST | `/api/evidence` | 创建证据 |
| POST | `/api/evidence/search` | 搜索证据 |
| POST | `/api/evidence/chain` | 构建证据链 |
| DELETE | `/api/evidence/{id}` | 删除证据 |
| POST | `/api/quality/research-trust` | 计算研究可信度 |
| POST | `/api/quality/research-compare` | 比较基线与候选研究输出 |

## 使用示例

### 构建证据链

```bash
curl -X POST http://localhost:8000/api/evidence/chain \
  -H "Content-Type: application/json" \
  -d '{
    "evidence": [
      {"type": "fund_flow", "claim": "主力净流入", "source": "eastmoney", "data_date": "2025-05-20"},
      {"type": "news", "claim": "主力净流入", "source": "cls", "data_date": "2025-05-20"}
    ],
    "agent_signals": [
      {"agent": "技术面分析师", "signal": "买入", "has_evidence": true}
    ]
  }'
```

### 响应结构

```json
{
  "success": true,
  "data": {
    "bundles": [
      {
        "claim": "主力净流入",
        "evidence": [...],
        "confidence": 0.82,
        "source_count": 2,
        "trust_score": 0.80,
        "decay_factor": 0.99,
        "contradictions": []
      }
    ],
    "contradictions": [],
    "missing_evidence": [],
    "coverage": 1.0,
    "overall_confidence": 0.82,
    "trust": {
      "score": 86,
      "grade": "high",
      "label": "高可信",
      "metrics": {
        "coverage": 1.0,
        "source_completeness": 1.0,
        "date_completeness": 1.0,
        "freshness": 0.96,
        "source_quality": 0.8,
        "source_diversity": 0.67
      },
      "warnings": []
    }
  }
}
```

## 置信度计算

综合置信度 = `boosted * 0.4 + trust * 0.3 + decay * 0.2 + base_conf * 0.1`

- **boosted**: 基础 0.6 + 每多一个源 +0.1（上限 0.95）
- **trust**: 来源可信度均值（SourceRanker）
- **decay**: 按类型计算时间衰减。行情 3 天、技术指标 5 天、新闻 14 天、公告 120 天、研报 180 天、基本面/宏观 365 天
- **base_conf**: 原始证据置信度均值

## 报告集成

报告生成器自动调用证据链引擎：
- 按 claim 分组显示证据
- 附置信度、来源数、可信度、时效性
- 标记矛盾证据（⚠️）
- 标记证据缺失（❗）
- 报告末尾显示覆盖率和综合置信度
- 报告显示 0-100 研究可信度、来源与日期完整度，以及明确的待复核事项
