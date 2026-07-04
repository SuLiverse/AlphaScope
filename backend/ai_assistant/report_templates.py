"""Report templates for structured analysis output (v1.1.4).

Provides 3 templates:
- 个股深度评级: Deep stock rating report
- 行业专题: Industry thematic report
- 黑天鹅预警: Black swan warning report
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.runtime.rating import score_to_rating


class ReportTemplate:
    """Base class for report templates."""

    name: str = ""
    description: str = ""
    sections: list[str] = []

    def generate(self, data: dict[str, Any]) -> str:
        """Generate a Markdown report from data."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "sections": self.sections,
        }


class StockDeepRatingTemplate(ReportTemplate):
    """个股深度评级报告模板."""

    name = "stock_deep_rating"
    description = "个股深度评级: 基本面+技术面+资金面+情绪面综合评估"
    sections = [
        "公司概况",
        "财务分析",
        "估值分析",
        "技术面分析",
        "资金面分析",
        "情绪面分析",
        "风险提示",
        "投资建议",
    ]

    def generate(self, data: dict[str, Any]) -> str:
        symbol = data.get("symbol", "未知")
        name = data.get("name", symbol)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        score = data.get("fundamental_score", 0)
        rating = self._score_to_rating(score)

        md = f"""# {name} ({symbol}) 深度评级报告

> 生成时间: {now} | 评级: **{rating}** | 综合评分: {score}/100

---

## 1. 公司概况

| 项目 | 数据 |
|------|------|
| 股票代码 | {symbol} |
| 所属行业 | {data.get("industry", "N/A")} |
| 总市值 | {data.get("market_cap", "N/A")} |
| 市盈率(TTM) | {data.get("pe_ttm", "N/A")} |
| 市净率 | {data.get("pb", "N/A")} |

## 2. 财务分析

{self._format_financials(data.get("financials", {}))}

## 3. 估值分析

{self._format_valuation(data.get("valuation", {}))}

## 4. 技术面分析

{self._format_technical(data.get("technical", {}))}

## 5. 资金面分析

{self._format_fund_flow(data.get("fund_flow", {}))}

## 6. 情绪面分析

{self._format_sentiment(data.get("sentiment", {}))}

## 7. 风险提示

{self._format_risks(data.get("risks", []))}

## 8. 投资建议

**评级: {rating}**

{data.get("conclusion", "暂无具体建议。请结合以上分析自行判断。")}

---

*免责声明: 本报告由 AI 自动生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。*
"""
        return md

    # 评分→五档评级已统一到 backend.runtime.rating.score_to_rating
    _score_to_rating = staticmethod(score_to_rating)

    @staticmethod
    def _format_financials(data: dict) -> str:
        if not data:
            return "暂无财务数据。"
        lines = ["| 指标 | 最新值 | 同比变化 |", "|------|--------|----------|"]
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(f"| {k} | {v.get('value', 'N/A')} | {v.get('yoy', 'N/A')} |")
            else:
                lines.append(f"| {k} | {v} | N/A |")
        return "\n".join(lines)

    @staticmethod
    def _format_valuation(data: dict) -> str:
        if not data:
            return "暂无估值数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_technical(data: dict) -> str:
        if not data:
            return "暂无技术面数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_fund_flow(data: dict) -> str:
        if not data:
            return "暂无资金面数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_sentiment(data: dict) -> str:
        if not data:
            return "暂无情绪面数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_risks(risks: list) -> str:
        if not risks:
            return "暂无特别风险提示。"
        return "\n".join(f"- {r}" for r in risks)


class IndustryThematicTemplate(ReportTemplate):
    """行业专题报告模板."""

    name = "industry_thematic"
    description = "行业专题: 行业趋势+竞争格局+投资机会+风险分析"
    sections = [
        "行业概述",
        "市场规模与趋势",
        "竞争格局",
        "政策环境",
        "投资机会",
        "风险分析",
        "重点公司",
        "投资建议",
    ]

    def generate(self, data: dict[str, Any]) -> str:
        industry = data.get("industry", "未知行业")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        md = f"""# {industry} 行业专题报告

> 生成时间: {now}

---

## 1. 行业概述

{data.get("overview", "暂无概述。")}

## 2. 市场规模与趋势

{self._format_market(data.get("market", {}))}

## 3. 竞争格局

{self._format_competition(data.get("competition", {}))}

## 4. 政策环境

{data.get("policy", "暂无政策分析。")}

## 5. 投资机会

{self._format_opportunities(data.get("opportunities", []))}

## 6. 风险分析

{self._format_risks(data.get("risks", []))}

## 7. 重点公司

{self._format_companies(data.get("companies", []))}

## 8. 投资建议

{data.get("conclusion", "暂无具体建议。")}

---

*免责声明: 本报告由 AI 自动生成，仅供参考，不构成投资建议。*
"""
        return md

    @staticmethod
    def _format_market(data: dict) -> str:
        if not data:
            return "暂无市场数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_competition(data: dict) -> str:
        if not data:
            return "暂无竞争格局数据。"
        lines = []
        for k, v in data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_opportunities(items: list) -> str:
        if not items:
            return "暂无投资机会分析。"
        return "\n".join(f"- {o}" for o in items)

    @staticmethod
    def _format_risks(items: list) -> str:
        if not items:
            return "暂无风险分析。"
        return "\n".join(f"- {r}" for r in items)

    @staticmethod
    def _format_companies(items: list) -> str:
        if not items:
            return "暂无重点公司分析。"
        if isinstance(items[0], dict):
            lines = ["| 公司 | 代码 | 评级 | 说明 |", "|------|------|------|------|"]
            for c in items:
                lines.append(
                    f"| {c.get('name', '')} | {c.get('symbol', '')} | {c.get('rating', '')} | {c.get('note', '')} |"
                )
            return "\n".join(lines)
        return "\n".join(f"- {c}" for c in items)


class BlackSwanWarningTemplate(ReportTemplate):
    """黑天鹅预警报告模板."""

    name = "black_swan_warning"
    description = "黑天鹅预警: 异常事件识别+影响评估+应对建议"
    sections = [
        "事件概述",
        "异常信号",
        "影响评估",
        "历史类比",
        "应对建议",
    ]

    def generate(self, data: dict[str, Any]) -> str:
        severity = data.get("severity", "medium")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        severity_label = {
            "low": "低",
            "medium": "中",
            "high": "高",
            "critical": "极高",
        }.get(severity, "中")

        md = f"""# 黑天鹅预警报告

> 生成时间: {now} | 严重程度: **{severity_label}**

---

## 1. 事件概述

{data.get("description", "暂无事件描述。")}

**影响范围**: {data.get("scope", "未确定")}
**影响时间**: {data.get("timeframe", "未确定")}

## 2. 异常信号

{self._format_signals(data.get("signals", []))}

## 3. 影响评估

{self._format_impact(data.get("impact", {}))}

## 4. 历史类比

{self._format_history(data.get("historical_analogies", []))}

## 5. 应对建议

{self._format_recommendations(data.get("recommendations", []))}

---

*免责声明: 本报告由 AI 自动生成，黑天鹅事件具有高度不确定性，分析仅供参考。*
"""
        return md

    @staticmethod
    def _format_signals(signals: list) -> str:
        if not signals:
            return "暂无异常信号。"
        if isinstance(signals[0], dict):
            lines = ["| 信号 | 来源 | 置信度 |", "|------|------|--------|"]
            for s in signals:
                lines.append(f"| {s.get('signal', '')} | {s.get('source', '')} | {s.get('confidence', '')} |")
            return "\n".join(lines)
        return "\n".join(f"- {s}" for s in signals)

    @staticmethod
    def _format_impact(impact: dict) -> str:
        if not impact:
            return "暂无影响评估。"
        lines = []
        for k, v in impact.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)

    @staticmethod
    def _format_history(analogies: list) -> str:
        if not analogies:
            return "暂无历史类比。"
        return "\n".join(f"- {a}" for a in analogies)

    @staticmethod
    def _format_recommendations(recs: list) -> str:
        if not recs:
            return "暂无应对建议。"
        return "\n".join(f"- {r}" for r in recs)


# Template registry
_TEMPLATES: dict[str, ReportTemplate] = {
    "stock_deep_rating": StockDeepRatingTemplate(),
    "industry_thematic": IndustryThematicTemplate(),
    "black_swan_warning": BlackSwanWarningTemplate(),
}


def list_templates() -> list[dict[str, Any]]:
    """List all available report templates."""
    return [t.to_dict() for t in _TEMPLATES.values()]


def get_template(name: str) -> ReportTemplate | None:
    """Get a template by name."""
    return _TEMPLATES.get(name)


def generate_report(template_name: str, data: dict[str, Any]) -> str | None:
    """Generate a report using the specified template."""
    template = _TEMPLATES.get(template_name)
    if not template:
        return None
    return template.generate(data)
