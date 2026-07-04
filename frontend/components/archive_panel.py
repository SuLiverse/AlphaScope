"""
研究存档面板 (tab8)
从 dashboard.py 提取，包含：归档自动标签、统计卡片、决策分布图、活跃度图、高频股票TOP、模型组合统计、模型组合后验表现、检索栏、报告列表与详情。
"""

import os
from collections import Counter
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 后端模块 -- 组件自包含导入
try:
    from archive import (
        list_reports,
        load_report,
        get_stats,
        delete_report,
        get_combo_stats,
        get_combo_performance,
    )

    _ARCHIVE_AVAILABLE = True
except Exception:
    _ARCHIVE_AVAILABLE = False

try:
    from archive_tagger import tag_all_reports

    _TAGGER_AVAILABLE = True
except Exception:
    _TAGGER_AVAILABLE = False


# ============== 辅助函数 ==============


def _safe_list_reports(type_filter=None, **kwargs) -> list:
    """兼容旧版 archive.list_reports：若不支持 type_filter，回退后在前端本地过滤。"""
    try:
        return list_reports(type_filter=type_filter, **kwargs)
    except TypeError as exc:
        if "type_filter" not in str(exc):
            raise
        reports = list_reports(**kwargs)
        if not type_filter:
            return reports
        return [r for r in reports if r.get("type", "agent") == type_filter]


# ============== 渲染函数 ==============


def render():
    """
    渲染「研究存档」面板（tab8 全部内容）。

    无需参数，所有数据从 archive 后端模块获取。
    """
    st.markdown("#### 📚 研究存档")
    st.caption("每次 LLM 深度分析的报告会自动归档到此处，支持检索、后验标签和模型组合统计。")

    # 自动标签区域
    if _TAGGER_AVAILABLE:
        with st.expander("🏷️ 历史归档自动标签", expanded=False):
            st.caption("为未打标签的报告计算 3/5/10 日后验涨跌幅，用于后续验证模型信号。")
            if st.button(
                "刷新行情标签",
                use_container_width=True,
                help="为未打标签的报告计算 3/5/10 日涨跌幅",
            ):
                with st.spinner("正在计算行情标签..."):
                    result = tag_all_reports()
                    st.success(
                        f"完成：新标签 {result['tagged']} 条，跳过 {result['skipped']} 条，失败 {result['errors']} 条"
                    )
                    st.rerun()
    else:
        st.caption("历史归档自动标签模块未加载。")

    if not _ARCHIVE_AVAILABLE:
        st.error("⚠️ 存档模块未加载")
        return

    stats = get_stats()

    # 顶部统计卡片
    _render_stats_cards(stats)

    # 多模型异构架构 v0.5：模型组合健康度小卡
    if stats.get("distinct_combos", 0) > 0 or stats.get("fallback_total", 0) > 0:
        _render_combo_health_cards(stats)

    st.markdown("")

    # 决策分布 & 活跃度可视化
    if stats["total"] > 0:
        _render_decision_and_activity(stats)

    # 模型组合统计
    _render_combo_stats()

    # v0.8: 模型组合后验表现
    _render_combo_performance()

    st.markdown("---")

    # 检索栏 + 报告列表
    _render_search_and_list()


# ============== 各子模块渲染函数 ==============


def _render_stats_cards(stats: dict):
    """渲染顶部 5 个统计卡片"""
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.markdown(
        """
    <div class="metric-card">
        <div class="metric-label">报告总数</div>
        <div class="metric-value">{}</div>
    </div>
    """.format(stats["total"]),
        unsafe_allow_html=True,
    )
    sc2.markdown(
        """
    <div class="metric-card">
        <div class="metric-label">覆盖股票</div>
        <div class="metric-value">{}</div>
    </div>
    """.format(stats["stocks"]),
        unsafe_allow_html=True,
    )
    sc3.markdown(
        """
    <div class="metric-card">
        <div class="metric-label">建议买入</div>
        <div class="metric-value" style='color:#ef5350;'>{}</div>
    </div>
    """.format(stats["buy"]),
        unsafe_allow_html=True,
    )
    sc4.markdown(
        """
    <div class="metric-card">
        <div class="metric-label">建议卖出</div>
        <div class="metric-value" style='color:#26a69a;'>{}</div>
    </div>
    """.format(stats["sell"]),
        unsafe_allow_html=True,
    )
    sc5.markdown(
        """
    <div class="metric-card">
        <div class="metric-label">建议观望</div>
        <div class="metric-value" style='color:#ff9800;'>{}</div>
    </div>
    """.format(stats["hold"]),
        unsafe_allow_html=True,
    )


def _render_combo_health_cards(stats: dict):
    """渲染模型组合健康度小卡"""
    mc1, mc2 = st.columns(2)
    with mc1:
        st.html(f"""
        <div class="metric-card">
            <div class="metric-label">出现过的模型组合</div>
            <div class="metric-value" style='color:#6366f1;'>{stats.get("distinct_combos", 0)}</div>
        </div>
        """)
    with mc2:
        fb = stats.get("fallback_total", 0)
        fb_color = "#9ca3af" if fb == 0 else "#ef4444"
        st.html(f"""
        <div class="metric-card">
            <div class="metric-label">主模型→兜底次数</div>
            <div class="metric-value" style='color:{fb_color};'>{fb}</div>
        </div>
        """)


def _render_decision_and_activity(stats: dict):
    """渲染决策分布饼图 + 近 14 日活跃度柱图 + 高频研究股票TOP"""
    all_reports = _safe_list_reports(limit=500)
    viz_col1, viz_col2 = st.columns([1, 1.3])

    with viz_col1:
        # 决策分布 donut
        pie_fig = go.Figure(
            data=[
                go.Pie(
                    labels=["建议买入", "建议卖出", "建议观望"],
                    values=[stats["buy"], stats["sell"], stats["hold"]],
                    hole=0.55,
                    marker=dict(colors=["#ef5350", "#26a69a", "#ff9800"]),
                    textinfo="label+percent",
                    textposition="outside",
                )
            ]
        )
        pie_fig.update_layout(
            title=dict(text="决策分布", x=0.5, font=dict(size=14)),
            height=280,
            margin=dict(l=20, r=20, t=50, b=20),
            showlegend=False,
            annotations=[
                dict(
                    text=f"<b>{stats['total']}</b><br>报告",
                    x=0.5,
                    y=0.5,
                    font=dict(size=18),
                    showarrow=False,
                )
            ],
        )
        st.plotly_chart(pie_fig, use_container_width=True)

    with viz_col2:
        # 近 14 日活跃度
        date_counter = Counter()
        for r in all_reports:
            date_counter[r.get("date", "")] += 1

        today = datetime.now().date()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
        counts = [date_counter.get(d, 0) for d in dates]
        date_labels = [(today - timedelta(days=i)).strftime("%m-%d") for i in range(13, -1, -1)]

        act_fig = go.Figure()
        act_fig.add_trace(
            go.Bar(
                x=date_labels,
                y=counts,
                marker=dict(color=["#3b82f6" if c > 0 else "#e5e7eb" for c in counts]),
                text=[c if c > 0 else "" for c in counts],
                textposition="outside",
            )
        )
        act_fig.update_layout(
            title=dict(text="近 14 日研究活跃度", x=0.5, font=dict(size=14)),
            height=280,
            margin=dict(l=20, r=20, t=50, b=40),
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor="#f1f5f9", title=""),
            plot_bgcolor="white",
        )
        st.plotly_chart(act_fig, use_container_width=True)

    # 高频研究股票 Top 10
    stock_counter = Counter()
    for r in all_reports:
        stock_counter[f"{r.get('stock_name', '')}({r.get('symbol', '')})"] += 1
    top_stocks = stock_counter.most_common(10)
    if len(top_stocks) > 1:
        with st.expander("📊 高频研究股票 TOP", expanded=False):
            rank_fig = go.Figure(
                go.Bar(
                    x=[c for _, c in top_stocks][::-1],
                    y=[s for s, _ in top_stocks][::-1],
                    orientation="h",
                    marker=dict(color="#6366f1"),
                    text=[c for _, c in top_stocks][::-1],
                    textposition="outside",
                )
            )
            rank_fig.update_layout(
                height=max(220, 32 * len(top_stocks)),
                margin=dict(l=20, r=40, t=20, b=20),
                xaxis=dict(showgrid=False, title="报告数"),
                yaxis=dict(showgrid=False),
                plot_bgcolor="white",
            )
            st.plotly_chart(rank_fig, use_container_width=True)


def _render_combo_stats():
    """渲染模型组合信号统计"""
    combo_stats = get_combo_stats()
    if not combo_stats:
        return

    with st.expander("🧬 模型组合信号统计 / 待收益回测", expanded=False):
        st.caption(
            "当前展示的是不同模型组合的历史信号分布和平均置信度，不伪造真实胜率；收益命中率需要结合自动标签后的 3/5/10 日表现继续计算。"
        )

        combo_df = pd.DataFrame(combo_stats)
        combo_df["combo_display"] = combo_df["combo"].apply(lambda x: x[:50] + "..." if len(x) > 50 else x)
        st.dataframe(
            combo_df[
                [
                    "combo_display",
                    "count",
                    "buy",
                    "sell",
                    "hold",
                    "avg_confidence",
                ]
            ],
            column_config={
                "combo_display": st.column_config.TextColumn("组合签名", help="完整签名可在 tooltip 中查看"),
                "count": "出现次数",
                "buy": "买入",
                "sell": "卖出",
                "hold": "观望",
                "avg_confidence": st.column_config.NumberColumn("平均置信度", format="%.1f%%"),
            },
            hide_index=True,
            use_container_width=True,
        )

        viz_c1, viz_c2 = st.columns(2)
        with viz_c1:
            bar_labels = [c["combo"][:40] + "..." if len(c["combo"]) > 40 else c["combo"] for c in combo_stats]
            bar_fig = go.Figure(
                go.Bar(
                    x=bar_labels,
                    y=[c["count"] for c in combo_stats],
                    marker=dict(color="#6366f1"),
                    text=[c["count"] for c in combo_stats],
                    textposition="outside",
                )
            )
            bar_fig.update_layout(
                title=dict(text="各组合出现次数", x=0.5, font=dict(size=13)),
                height=300,
                margin=dict(l=20, r=20, t=40, b=80),
                xaxis=dict(tickangle=-30, showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
                plot_bgcolor="white",
            )
            st.plotly_chart(bar_fig, use_container_width=True)

        with viz_c2:
            total_buy = sum(c["buy"] for c in combo_stats)
            total_sell = sum(c["sell"] for c in combo_stats)
            total_hold = sum(c["hold"] for c in combo_stats)
            sig_fig = go.Figure(
                data=[
                    go.Pie(
                        labels=["买入", "卖出", "观望"],
                        values=[total_buy, total_sell, total_hold],
                        hole=0.5,
                        marker=dict(colors=["#ef5350", "#26a69a", "#ff9800"]),
                        textinfo="label+percent",
                        textposition="outside",
                    )
                ]
            )
            sig_fig.update_layout(
                title=dict(text="信号分布（全组合汇总）", x=0.5, font=dict(size=13)),
                height=300,
                margin=dict(l=20, r=20, t=40, b=20),
                showlegend=False,
                annotations=[
                    dict(
                        text=f"<b>{total_buy + total_sell + total_hold}</b><br>信号",
                        x=0.5,
                        y=0.5,
                        font=dict(size=16),
                        showarrow=False,
                    )
                ],
            )
            st.plotly_chart(sig_fig, use_container_width=True)


def _render_combo_performance():
    """渲染模型组合后验表现"""
    try:
        combo_perf = get_combo_performance(min_samples=0)
    except Exception as _perf_e:
        combo_perf = []
        st.caption(f"模型组合后验表现暂不可用: {_perf_e}")

    if not combo_perf:
        return

    labeled_total = sum(c.get("samples_with_label", 0) for c in combo_perf)
    with st.expander(
        f"⚖️ 模型组合后验表现（{labeled_total} 条已回填）",
        expanded=False,
    ):
        st.caption(
            "聚合 3/5/10/20 日真实涨跌幅、10 日最大回撤，以及按方向拆分的 5 日命中率。"
            " 命中口径：买入信号区间内上涨 / 卖出信号区间内下跌 / 观望信号 |涨跌幅| ≤ 2%。"
            " 排序按 5 日总命中率降序，样本量过小的组合请审慎参考。"
        )

        perf_df = pd.DataFrame(combo_perf)
        perf_df["combo_display"] = perf_df["combo"].apply(
            lambda x: x[:50] + "..." if isinstance(x, str) and len(x) > 50 else x
        )
        show_cols = [
            "combo_display",
            "count",
            "samples_with_label",
            "avg_5d_return",
            "avg_10d_return",
            "avg_20d_return",
            "avg_drawdown_10d",
            "hit_rate_5d",
            "buy_hit_rate_5d",
            "hold_hit_rate_5d",
        ]
        show_cols = [c for c in show_cols if c in perf_df.columns]
        st.dataframe(
            perf_df[show_cols],
            column_config={
                "combo_display": st.column_config.TextColumn("组合签名"),
                "count": st.column_config.NumberColumn("总样本"),
                "samples_with_label": st.column_config.NumberColumn("已回填(5日)"),
                "avg_5d_return": st.column_config.NumberColumn("5日均收益", format="%.2f%%"),
                "avg_10d_return": st.column_config.NumberColumn("10日均收益", format="%.2f%%"),
                "avg_20d_return": st.column_config.NumberColumn("20日均收益", format="%.2f%%"),
                "avg_drawdown_10d": st.column_config.NumberColumn("10日均回撤", format="%.2f%%"),
                "hit_rate_5d": st.column_config.NumberColumn("5日命中率", format="%.0f%%"),
                "buy_hit_rate_5d": st.column_config.NumberColumn("买入5日命中率", format="%.0f%%"),
                "hold_hit_rate_5d": st.column_config.NumberColumn("观望5日命中率", format="%.0f%%"),
            },
            hide_index=True,
            use_container_width=True,
        )

        if labeled_total == 0:
            st.info(
                "尚未有已回填的后验数据。请等待 T+3 / T+5 交易日，然后在上方"
                "「🏷️ 历史归档自动标签」中点击「刷新行情标签」重新计算。"
            )
        else:
            top_perf = [c for c in combo_perf if c.get("avg_5d_return") is not None][:5]
            if top_perf:
                ret_fig = go.Figure(
                    go.Bar(
                        x=[c["avg_5d_return"] for c in top_perf][::-1],
                        y=[(c["combo"][:40] + "...") if len(c["combo"]) > 40 else c["combo"] for c in top_perf][::-1],
                        orientation="h",
                        marker=dict(color=["#ef5350" if c["avg_5d_return"] > 0 else "#26a69a" for c in top_perf][::-1]),
                        text=[f"{c['avg_5d_return']:+.2f}%" for c in top_perf][::-1],
                        textposition="outside",
                    )
                )
                ret_fig.update_layout(
                    title=dict(
                        text="Top 5 组合 · 5 日平均收益",
                        x=0.5,
                        font=dict(size=13),
                    ),
                    height=max(220, 36 * len(top_perf) + 80),
                    margin=dict(l=20, r=80, t=40, b=20),
                    xaxis=dict(showgrid=True, gridcolor="#f1f5f9", title="%"),
                    yaxis=dict(showgrid=False),
                    plot_bgcolor="white",
                )
                st.plotly_chart(ret_fig, use_container_width=True)


def _render_search_and_list():
    """渲染检索栏 + 报告列表/详情"""
    fc0, fc1, fc2, fc3, fc4 = st.columns([1.5, 2, 2, 2, 2])
    with fc0:
        f_type = st.selectbox("类型", ["全部", "Agent 报告", "圆桌纪要"], key="arc_type")
    with fc1:
        f_stock = st.text_input(
            "🔍 股票名称/代码",
            placeholder="如：贵州茅台 或 600519",
            key="arc_stock",
        )
    with fc2:
        f_decision = st.selectbox(
            "决策类型",
            ["全部", "建议买入", "建议卖出", "建议观望"],
            key="arc_decision",
        )
    with fc3:
        f_date_from = st.date_input("起始日期", value=None, key="arc_from")
    with fc4:
        f_date_to = st.date_input("结束日期", value=None, key="arc_to")

    type_filter_map = {
        "全部": None,
        "Agent 报告": "agent",
        "圆桌纪要": "roundtable",
    }
    reports = _safe_list_reports(
        stock_filter=f_stock or None,
        decision_filter=None if f_decision == "全部" else f_decision,
        date_from=f_date_from.strftime("%Y-%m-%d") if f_date_from else None,
        date_to=f_date_to.strftime("%Y-%m-%d") if f_date_to else None,
        type_filter=type_filter_map.get(f_type),
        limit=200,
    )

    st.markdown(f"**命中 {len(reports)} 条报告**")

    if not reports:
        st.caption("暂无符合条件的存档报告。请先在「Agent 协作分析」Tab 启动深度分析，报告会自动归档。")
        return

    # 列表 + 详情切换
    view_key = "arc_view_path"
    if view_key not in st.session_state:
        st.session_state[view_key] = None

    if st.session_state[view_key] is None:
        _render_report_list(reports, view_key)
    else:
        _render_report_detail(view_key)


def _render_report_list(reports: list, view_key: str):
    """渲染报告列表视图"""
    for r in reports:
        decision_color = {
            "建议买入": "#ef5350",
            "建议卖出": "#26a69a",
            "建议观望": "#ff9800",
        }.get(r.get("decision", ""), "#6b7280")

        main_flow = r.get("main_5d_yi")
        flow_html = ""
        if main_flow is not None:
            fc = "#ef5350" if main_flow > 0 else "#26a69a"
            flow_html = f"<span style='color:{fc}; margin-left:12px;'>主力5日 {main_flow:+.2f}亿</span>"

        # 行情标签：3/5/10/20 日涨跌幅
        ret_html = ""
        for dkey, dlabel in [
            ("3d_return", "3日"),
            ("5d_return", "5日"),
            ("10d_return", "10日"),
            ("20d_return", "20日"),
        ]:
            dval = r.get(dkey)
            if dval is not None:
                dcolor = "#ef5350" if dval > 0 else "#26a69a" if dval < 0 else "#6b7280"
                demoji = "🔴" if dval > 0 else "🟢" if dval < 0 else "⚪"
                ret_html += f"<span style='color:{dcolor}; margin-left:10px;'>{demoji} {dlabel} {dval:+.2f}%</span>"

        # v0.8: 10 日窗口最大回撤
        dd_val = r.get("max_drawdown_10d")
        if dd_val is not None:
            dd_color = "#26a69a" if dd_val < 0 else "#9ca3af"
            ret_html += (
                f"<span style='color:{dd_color}; margin-left:10px;' "
                f"title='报告日起 10 日内最大回撤'>📉 回撤 {dd_val:+.2f}%</span>"
            )

        # v0.8: 5 日命中徽标
        hit_5 = r.get("hit_5d")
        if hit_5 in (0, 1):
            hit_color = "#16a34a" if hit_5 == 1 else "#dc2626"
            hit_text = "5日命中" if hit_5 == 1 else "5日未中"
            ret_html += (
                f"<span style='color:{hit_color}; margin-left:10px;'>✓ {hit_text}</span>"
                if hit_5 == 1
                else f"<span style='color:{hit_color}; margin-left:10px;'>✗ {hit_text}</span>"
            )

        day_chg = r.get("day_change", 0) or 0
        chg_color = "#ef5350" if day_chg > 0 else "#26a69a" if day_chg < 0 else "#6b7280"

        # v0.9: 审稿质量徽标
        critic_meta = r.get("critic") or {}
        critic_html = ""
        if critic_meta.get("ok"):
            avg_q = critic_meta.get("avg_quality")
            if isinstance(avg_q, (int, float)):
                if avg_q >= 80:
                    qc = "#16a34a"
                elif avg_q >= 60:
                    qc = "#0ea5e9"
                elif avg_q >= 40:
                    qc = "#f59e0b"
                else:
                    qc = "#dc2626"
                critic_html += (
                    f"<span title='审稿员对本次决策的平均评分' "
                    f"style='margin-left:10px; color:{qc};'>🧐 审 {avg_q:.0f}</span>"
                )
            oc = critic_meta.get("overconfident_count", 0)
            if oc:
                critic_html += (
                    f"<span style='margin-left:8px; color:#dc2626;' "
                    f"title='被审稿人标记为过度自信的 Agent 数'>⚠ 自信 {oc}</span>"
                )
            level = critic_meta.get("divergence_level")
            if level and level != "无":
                lc = {
                    "高": "#dc2626",
                    "中": "#f59e0b",
                    "低": "#16a34a",
                }.get(level, "#9ca3af")
                critic_html += (
                    f"<span style='margin-left:8px; color:{lc};' "
                    f"title='审稿人判定的 Agent 之间分歧度'>分歧 {level}</span>"
                )

        col_meta, col_btn = st.columns([10, 2])
        with col_meta:
            st.html(f"""
            <div style='padding:14px 18px; background:#f8f9fb; border-radius:10px; margin-bottom:10px;
                        border-left:4px solid {decision_color};'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <div>
                        <strong style='font-size:1.05rem;'>{r["stock_name"]}</strong>
                        <span style='color:#9ca3af; margin-left:8px; font-size:0.85rem;'>{r["symbol"]}</span>
                        <span style='color:{decision_color}; margin-left:14px; font-weight:600;'>{r["decision"]}</span>
                        <span style='color:#6b7280; margin-left:10px; font-size:0.85rem;'>置信度 {r["avg_confidence"]}%</span>
                    </div>
                    <div style='color:#9ca3af; font-size:0.82rem;'>
                        {r["date"]} {r["time"]}
                    </div>
                </div>
                <div style='margin-top:8px; color:#4b5563; font-size:0.88rem;'>
                    收盘 ¥{r.get("close", 0) or 0:.2f}
                    <span style='color:{chg_color}; margin-left:6px;'>({day_chg:+.2f}%)</span>
                    <span style='color:#9ca3af; margin-left:12px;'>买{r["buy"]}/卖{r["sell"]}/观{r["hold"]}</span>
                    {flow_html}
                    {ret_html}
                    {critic_html}
                </div>
                <div style='margin-top:6px; color:#6b7280; font-size:0.82rem; font-style:italic;'>
                    💬 {r.get("chairman_excerpt", "")}…
                </div>
            </div>
            """)
        with col_btn:
            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            if st.button("查看", key=f"view_{r['path']}", use_container_width=True):
                st.session_state[view_key] = r["path"]
                st.rerun()
            if st.button(
                "🗑",
                key=f"del_{r['path']}",
                use_container_width=True,
                help="删除此报告",
            ):
                delete_report(r["path"])
                st.rerun()


def _render_report_detail(view_key: str):
    """渲染报告详情视图"""
    report_text = load_report(st.session_state[view_key])
    cb1, cb2 = st.columns([1, 5])
    with cb1:
        if st.button("← 返回列表", use_container_width=True):
            st.session_state[view_key] = None
            st.rerun()
    with cb2:
        fname = os.path.basename(st.session_state[view_key])
        st.download_button(
            label=f"📥 下载 {fname}",
            data=report_text.encode("utf-8"),
            file_name=fname,
            mime="text/markdown",
            key="download_archived",
        )
    st.markdown("---")
    st.markdown(report_text)
