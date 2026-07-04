"""视觉分析报告生成器 — 将 VisionAnalysisResult 转为结构化 Markdown"""

from __future__ import annotations

from typing import Any


def generate_vision_report(result: Any) -> str:
    """生成结构化 Markdown 视觉分析报告。"""
    lines = []

    # 标题
    detection = result.detection
    ticker = detection.ticker if detection else ""
    ticker_name = detection.ticker_name if detection else ""
    title = "K线视觉分析报告"
    if ticker:
        title += f" — {ticker_name}({ticker})" if ticker_name else f" — {ticker}"

    lines.append(f"# {title}")
    lines.append("")

    # 图表识别
    lines.append("## 图表识别")
    lines.append("")
    if detection:
        lines.append(f"- 图表类型: {detection.chart_type}")
        if ticker:
            lines.append(f"- 标的代码: {ticker}")
        if ticker_name:
            lines.append(f"- 标的名称: {ticker_name}")
        if detection.market:
            lines.append(f"- 市场: {detection.market}")
        if detection.period:
            lines.append(f"- 周期: {detection.period}")
        if detection.confidence > 0:
            conf_pct = detection.confidence * 100
            conf_warn = " ⚠️ 置信度较低" if conf_pct < 60 else ""
            lines.append(f"- 识别置信度: {conf_pct:.0f}%{conf_warn}")
    lines.append("")

    # K线解读
    kline = result.kline_analysis if hasattr(result, "kline_analysis") else None
    if kline:
        lines.append("## K线分析")
        lines.append("")

        if kline.trend:
            trend_icon = {"上升趋势": "📈", "下降趋势": "📉", "震荡": "↔️"}.get(kline.trend, "")
            lines.append(f"### 趋势判断: {trend_icon} {kline.trend}")
            lines.append("")

        # 支撑压力位
        support = kline.support_levels if hasattr(kline, "support_levels") else []
        resistance = kline.resistance_levels if hasattr(kline, "resistance_levels") else []
        if support or resistance:
            lines.append("### 关键价位")
            lines.append("")
            lines.append("| 类型 | 价位 |")
            lines.append("|------|------|")
            for s in support:
                lines.append(f"| 支撑位 | {s} |")
            for r in resistance:
                lines.append(f"| 压力位 | {r} |")
            lines.append("")

        # 形态识别
        patterns = kline.patterns if hasattr(kline, "patterns") else []
        if patterns:
            lines.append("### 形态识别")
            lines.append("")
            for p in patterns:
                lines.append(f"- {p}")
            lines.append("")

        # 技术指标描述
        indicators = kline.indicators if hasattr(kline, "indicators") else {}
        if indicators:
            lines.append("### 技术指标（图中读取）")
            lines.append("")
            for key, val in indicators.items():
                if val:
                    lines.append(f"- **{key.upper()}**: {val}")
            lines.append("")

        # 量能分析
        vol = kline.volume_analysis if hasattr(kline, "volume_analysis") else ""
        if vol:
            lines.append("### 量能分析")
            lines.append("")
            lines.append(vol)
            lines.append("")

        if kline.summary:
            lines.append("### 综合判断")
            lines.append("")
            lines.append(kline.summary)
            lines.append("")

    # 交叉验证
    real = result.real_data if hasattr(result, "real_data") else None
    if real and real.data_available:
        lines.append("## 交叉验证")
        lines.append("")

        if real.latest_close > 0:
            lines.append(f"- 最新收盘价: {real.latest_close:.2f}")
            lines.append(f"- 数据来源: {real.data_source}")
            lines.append("")

        if real.trend_consistent:
            lines.append("- ✅ 视觉趋势与真实行情一致")
        else:
            lines.append("- ⚠️ 视觉趋势与真实行情不一致")
        lines.append("")

        if real.conflicts:
            lines.append("### 冲突警告")
            lines.append("")
            for c in real.conflicts:
                lines.append(f"- ⚠️ {c}")
            lines.append("")
    elif real and not real.data_available:
        lines.append("## 交叉验证")
        lines.append("")
        lines.append("- ❗ 未能获取真实行情数据，仅展示视觉分析结果")
        lines.append("")

    # 缺失信息
    if result.needs_more_info and result.missing_info:
        lines.append("## 需要补充信息")
        lines.append("")
        for info in result.missing_info:
            lines.append(f"- {info}")
        lines.append("")

    # 风险提示
    lines.append("## 风险提示")
    lines.append("")
    if result.disclaimer:
        lines.append(result.disclaimer)
    else:
        lines.append(
            "以上分析仅基于K线图形观察，可能与实际行情存在偏差。请结合实时行情数据验证关键价位。本分析不构成投资建议。"
        )
    lines.append("")

    return "\n".join(lines)
