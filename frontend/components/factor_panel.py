"""量化因子面板组件

在 Agent 分析页面展示量化因子雷达图和详细数据。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def render_factor_panel(symbol: str, stock_name: str = "") -> None:
    """渲染量化因子分析面板"""
    try:
        import streamlit as st
    except ImportError:
        return

    try:
        from backend.factors import get_factor_generator

        gen = get_factor_generator()
        report = gen.generate(symbol, stock_name, days=30, include_signals=True)

        if report.news_count == 0 and report.event_count == 0 and report.report_count == 0:
            st.info("暂无足够数据生成因子分析 (需要先采集新闻/公告/研报)")
            return

        # 因子概览
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            _metric_with_color("综合因子", report.composite)
        with col2:
            _metric_with_color("新闻情绪", report.news_sentiment)
        with col3:
            _metric_with_color("事件信号", report.event_signal)
        with col4:
            _metric_with_color("分析师评级", report.analyst_rating)
        with col5:
            _metric_with_color("资金流向", report.fund_flow)
        with col6:
            _metric_with_color("价格动量", report.momentum)

        # 信号详情
        if report.signals:
            with st.expander("📋 详细信号", expanded=False):
                for sig in report.signals:
                    sig_type = sig.get("type", "")
                    if sig_type == "news":
                        st.write(f"📰 **[新闻]** {sig.get('title', '')} — 情绪: {sig.get('sentiment', 0):+.2f}")
                    elif sig_type == "event":
                        st.write(
                            f"📋 **[公告:{sig.get('category', '')}]** {sig.get('title', '')} — 得分: {sig.get('score', 0):+.2f}"
                        )
                    elif sig_type == "analyst":
                        st.write(
                            f"📊 **[研报]** {sig.get('institution', '')}: {sig.get('title', '')} — 评级: {sig.get('rating_score', 0):+.2f}"
                        )
                    elif sig_type == "fund_flow":
                        st.write(
                            f"💰 **[资金]** 主力净流入: {sig.get('last_main_yi', 0):.2f}亿, 流入{sig.get('inflow_days', 0)}天/流出{sig.get('outflow_days', 0)}天"
                        )
                    elif sig_type == "momentum":
                        st.write(
                            f"📈 **[动量]** 近期涨幅: {sig.get('short_return_pct', 0):+.1f}%, 量能变化: {sig.get('volume_change_pct', 0):+.1f}%"
                        )

        # 样本统计
        st.caption(
            f"样本: 新闻 {report.news_count} 条 | 公告 {report.event_count} 条 | 研报 {report.report_count} 条 | 计算时间: {report.computed_at[:19]}"
        )

    except Exception as e:
        logger.warning("因子面板渲染失败: %s", e)
        st.warning(f"因子分析加载失败: {e}")


def _metric_with_color(label: str, value: float) -> None:
    """带颜色的指标显示"""
    try:
        import streamlit as st
    except ImportError:
        return

    st.metric(
        label=label,
        value=f"{value:+.2f}",
        delta=None,
    )
