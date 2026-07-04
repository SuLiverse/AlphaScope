"""
资金流向面板 (tab5)
从 dashboard.py 提取，包含：个股资金流向（指标卡 + 30日趋势 + 五类资金柱图 + 明细表 + 4类细分 + 主力进出场判定）、大盘资金流向。
"""

import streamlit as st
import plotly.graph_objects as go

# 后端模块 -- 组件自包含导入
try:
    from fund_flow import (
        fetch_individual_fund_flow,
        fetch_market_fund_flow,
        summarize_fund_flow,
    )

    _FUND_AVAILABLE = True
except Exception:
    _FUND_AVAILABLE = False


# ============== 组件内部缓存函数 ==============
# 与 dashboard.py 同名缓存函数功能一致，但缓存独立。
# 后续可统一抽取到 data_access.py 共享模块中。


@st.cache_data(ttl=300)
def _cached_individual_fund_flow(symbol: str, days: int = 30):
    if not _FUND_AVAILABLE:
        return None
    return fetch_individual_fund_flow(symbol, days=days)


@st.cache_data(ttl=300)
def _cached_market_fund_flow(days: int = 30):
    if not _FUND_AVAILABLE:
        return None
    return fetch_market_fund_flow(days=days)


# ============== 渲染函数 ==============


def render(stock_name: str, symbol: str):
    """
    渲染「资金流向」面板（tab5 全部内容）。

    Args:
        stock_name: 股票名称
        symbol: 股票代码（6 位数字）
    """
    st.markdown("#### 💰 资金流向（主力 / 超大单 / 大单 / 中单 / 小单）")
    if not _FUND_AVAILABLE:
        st.error("资金流向模块加载失败，请检查 fund_flow 模块。")
        return

    # 顶部刷新栏
    col_r, col_i = st.columns([1, 5])
    with col_r:
        if st.button("🔄 刷新资金数据", use_container_width=True, key="refresh_fund"):
            st.cache_data.clear()
            st.rerun()
    with col_i:
        st.caption("数据缓存 5 分钟。资金面是 A 股最关键的同步指标，主力连续流出常领先股价。")

    sub_f1, sub_f2 = st.tabs([f"🎯 {stock_name} 个股资金", "🌐 大盘资金"])

    # ---------- 个股资金流向 ----------
    with sub_f1:
        _render_individual_fund_flow(symbol)

    # ---------- 大盘资金流向 ----------
    with sub_f2:
        _render_market_fund_flow()


# ============== 个股资金流向 ==============


def _render_individual_fund_flow(symbol: str):
    """渲染个股资金流向子面板"""
    with st.spinner("正在拉取个股资金流向..."):
        df_ff = _cached_individual_fund_flow(symbol, days=30)

    if df_ff is None or len(df_ff) == 0:
        st.info("未获取到该股资金流向数据（接口可能限速，请稍后重试）。")
        return

    # 顶部 4 个核心指标卡
    s = summarize_fund_flow(df_ff, recent_days=5)
    kc1, kc2, kc3, kc4 = st.columns(4)

    with kc1:
        st.markdown(
            _fund_card(
                "近5日主力净额",
                s["main_total_yi"],
                f"流入{s['inflow_days']}天 / 流出{s['outflow_days']}天",
            ),
            unsafe_allow_html=True,
        )
    with kc2:
        st.markdown(
            _fund_card("近5日超大单", s["super_total_yi"], "机构主力"),
            unsafe_allow_html=True,
        )
    with kc3:
        st.markdown(
            _fund_card("近5日大单", s["large_total_yi"], "游资/大户"),
            unsafe_allow_html=True,
        )
    with kc4:
        st.markdown(
            _fund_card("近5日小单", s["small_total_yi"], "散户"),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # 主力净流入趋势图（30 日）
    df_ff_show = df_ff.tail(30).copy()
    df_ff_show["主力_亿"] = df_ff_show["主力净流入-净额"] / 1e8
    df_ff_show["超大_亿"] = df_ff_show["超大单净流入-净额"] / 1e8
    df_ff_show["大_亿"] = df_ff_show["大单净流入-净额"] / 1e8
    df_ff_show["中_亿"] = df_ff_show["中单净流入-净额"] / 1e8
    df_ff_show["小_亿"] = df_ff_show["小单净流入-净额"] / 1e8

    col_chart1, col_chart2 = st.columns([3, 2])

    with col_chart1:
        st.markdown("##### 主力资金 30 日流向（亿元）")
        fig_main = go.Figure()
        colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df_ff_show["主力_亿"]]
        fig_main.add_trace(
            go.Bar(
                x=df_ff_show["日期"],
                y=df_ff_show["主力_亿"],
                marker_color=colors,
                name="主力净流入",
                hovertemplate="%{x|%Y-%m-%d}<br>主力: %{y:+.2f}亿<extra></extra>",
            )
        )
        # 收盘价副轴
        fig_main.add_trace(
            go.Scatter(
                x=df_ff_show["日期"],
                y=df_ff_show["收盘价"],
                mode="lines",
                line=dict(color="#667eea", width=1.8),
                name="收盘价",
                yaxis="y2",
                hovertemplate="%{x|%Y-%m-%d}<br>收盘: ¥%{y:.2f}<extra></extra>",
            )
        )
        fig_main.update_layout(
            height=320,
            margin=dict(l=10, r=10, t=20, b=10),
            plot_bgcolor="white",
            paper_bgcolor="white",
            legend=dict(orientation="h", x=0, y=1.08),
            hovermode="x unified",
            xaxis=dict(showgrid=False),
            yaxis=dict(
                title="主力净流入 (亿)",
                gridcolor="#f3f4f6",
                zeroline=True,
                zerolinecolor="#cbd5e1",
                zerolinewidth=1,
            ),
            yaxis2=dict(title="收盘价", overlaying="y", side="right", showgrid=False),
        )
        st.plotly_chart(fig_main, use_container_width=True)

    with col_chart2:
        st.markdown("##### 五类资金近5日累计")
        cats = ["超大单", "大单", "中单", "小单"]
        vals = [
            s["super_total_yi"],
            s["large_total_yi"],
            s["medium_total_yi"],
            s["small_total_yi"],
        ]
        bar_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in vals]
        fig_cat = go.Figure(
            go.Bar(
                x=vals,
                y=cats,
                orientation="h",
                marker_color=bar_colors,
                text=[f"{v:+.2f}亿" for v in vals],
                textposition="auto",
            )
        )
        fig_cat.update_layout(
            height=320,
            margin=dict(l=10, r=10, t=20, b=10),
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
            xaxis=dict(
                title="净流入 (亿)",
                gridcolor="#f3f4f6",
                zeroline=True,
                zerolinecolor="#cbd5e1",
            ),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_cat, use_container_width=True)

    # 数据表
    st.markdown("##### 资金流向明细（近 15 日）")
    tbl = df_ff.tail(15).iloc[::-1].copy()
    tbl["日期"] = tbl["日期"].dt.strftime("%Y-%m-%d")
    tbl_show_cols = [
        "日期",
        "收盘价",
        "涨跌幅",
        "主力净流入-净额",
        "主力净流入-净占比",
        "超大单净流入-净额",
        "大单净流入-净额",
        "中单净流入-净额",
        "小单净流入-净额",
    ]
    tbl = tbl[[c for c in tbl_show_cols if c in tbl.columns]].copy()
    # 元转亿
    for col in [
        "主力净流入-净额",
        "超大单净流入-净额",
        "大单净流入-净额",
        "中单净流入-净额",
        "小单净流入-净额",
    ]:
        if col in tbl.columns:
            tbl[col] = tbl[col] / 1e8

    rename_fund = {
        "主力净流入-净额": "主力(亿)",
        "主力净流入-净占比": "主力占比%",
        "超大单净流入-净额": "超大单(亿)",
        "大单净流入-净额": "大单(亿)",
        "中单净流入-净额": "中单(亿)",
        "小单净流入-净额": "小单(亿)",
    }
    tbl = tbl.rename(columns=rename_fund)

    fmt_dict = {
        "收盘价": "{:.2f}",
        "涨跌幅": "{:+.2f}",
        "主力(亿)": "{:+.2f}",
        "主力占比%": "{:+.2f}",
        "超大单(亿)": "{:+.2f}",
        "大单(亿)": "{:+.2f}",
        "中单(亿)": "{:+.2f}",
        "小单(亿)": "{:+.2f}",
    }
    fmt_dict = {k: v for k, v in fmt_dict.items() if k in tbl.columns}
    num_cols = [c for c in fmt_dict.keys() if c != "收盘价"]

    st.dataframe(
        tbl.style.format(fmt_dict).map(_color_pos_neg, subset=num_cols),
        height=460,
        use_container_width=True,
        hide_index=True,
    )

    # ---------- v0.7 P0-4: 4 类资金细分 + 主力进出场判定 ----------
    st.markdown(
        '<hr style="margin:1.5rem 0; border:none; height:1px; '
        'background:linear-gradient(90deg,transparent,#e5e7eb,transparent);" />',
        unsafe_allow_html=True,
    )
    st.markdown("##### 🪙 4 类资金细分（超大/大/中/小单）")

    ext_c1, ext_c2 = st.columns([1, 1.4])

    cats4 = ["超大单", "大单", "中单", "小单"]
    vals4 = [
        s.get("super_total_yi", 0),
        s.get("large_total_yi", 0),
        s.get("medium_total_yi", 0),
        s.get("small_total_yi", 0),
    ]
    with ext_c1:
        abs_vals = [abs(v) for v in vals4]
        pie_colors4 = ["#ef5350" if v >= 0 else "#26a69a" for v in vals4]
        fig_pie4 = go.Figure(
            data=[
                go.Pie(
                    labels=[f"{c}({v:+.2f}亿)" for c, v in zip(cats4, vals4)],
                    values=abs_vals if sum(abs_vals) > 0 else [1, 1, 1, 1],
                    hole=0.5,
                    marker=dict(
                        colors=pie_colors4,
                        line=dict(color="white", width=2),
                    ),
                    textinfo="label+percent",
                    textfont=dict(size=11),
                )
            ]
        )
        fig_pie4.update_layout(
            title=dict(text="近 5 日 4 类资金净流向占比", x=0.5, font=dict(size=12)),
            height=320,
            margin=dict(l=10, r=10, t=40, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_pie4, use_container_width=True)

    with ext_c2:
        # 5 日按天 4 类资金趋势柱图
        df_5d = df_ff.tail(5).copy()
        df_5d["超大_亿"] = df_5d["超大单净流入-净额"] / 1e8
        df_5d["大_亿"] = df_5d["大单净流入-净额"] / 1e8
        df_5d["中_亿"] = df_5d["中单净流入-净额"] / 1e8
        df_5d["小_亿"] = df_5d["小单净流入-净额"] / 1e8
        df_5d["d_label"] = df_5d["日期"].dt.strftime("%m-%d")

        fig_5d = go.Figure()
        fig_5d.add_trace(
            go.Bar(
                name="超大单",
                x=df_5d["d_label"],
                y=df_5d["超大_亿"],
                marker_color="#ef5350",
            )
        )
        fig_5d.add_trace(
            go.Bar(
                name="大单",
                x=df_5d["d_label"],
                y=df_5d["大_亿"],
                marker_color="#fb923c",
            )
        )
        fig_5d.add_trace(
            go.Bar(
                name="中单",
                x=df_5d["d_label"],
                y=df_5d["中_亿"],
                marker_color="#9ca3af",
            )
        )
        fig_5d.add_trace(
            go.Bar(
                name="小单",
                x=df_5d["d_label"],
                y=df_5d["小_亿"],
                marker_color="#26a69a",
            )
        )
        fig_5d.update_layout(
            title=dict(
                text="近 5 日 4 类资金按日趋势（亿元）",
                x=0.5,
                font=dict(size=12),
            ),
            height=320,
            margin=dict(l=10, r=10, t=40, b=20),
            barmode="group",
            plot_bgcolor="white",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            yaxis=dict(gridcolor="#f1f5f9", zeroline=True, zerolinecolor="#cbd5e1"),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_5d, use_container_width=True)

    # 主力进出场判定
    _render_main_force_judgment(s)


# ============== 大盘资金流向 ==============


def _render_market_fund_flow():
    """渲染大盘资金流向子面板"""
    with st.spinner("正在拉取大盘资金流向..."):
        df_mf = _cached_market_fund_flow(days=30)

    if df_mf is None or len(df_mf) == 0:
        st.info("未获取到大盘资金流向数据。")
        return

    s_m = summarize_fund_flow(df_mf, recent_days=5)

    mc1, mc2, mc3, mc4 = st.columns(4)

    with mc1:
        st.markdown(
            _fund_card(
                "近5日主力净额",
                s_m["main_total_yi"],
                f"流入{s_m['inflow_days']}天 / 流出{s_m['outflow_days']}天",
                large=True,
            ),
            unsafe_allow_html=True,
        )
    with mc2:
        st.markdown(
            _fund_card("近5日超大单", s_m["super_total_yi"], "机构主力", large=True),
            unsafe_allow_html=True,
        )
    with mc3:
        st.markdown(
            _fund_card("近5日大单", s_m["large_total_yi"], "游资/大户", large=True),
            unsafe_allow_html=True,
        )
    with mc4:
        st.markdown(
            _fund_card("近5日小单", s_m["small_total_yi"], "散户", large=True),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    df_mf_show = df_mf.tail(30).copy()
    df_mf_show["主力_亿"] = df_mf_show["主力净流入-净额"] / 1e8

    st.markdown("##### 大盘主力资金 30 日趋势 vs 上证指数")
    fig_mf = go.Figure()
    colors2 = ["#ef5350" if v >= 0 else "#26a69a" for v in df_mf_show["主力_亿"]]
    fig_mf.add_trace(
        go.Bar(
            x=df_mf_show["日期"],
            y=df_mf_show["主力_亿"],
            marker_color=colors2,
            name="主力净流入（亿）",
            hovertemplate="%{x|%Y-%m-%d}<br>主力: %{y:+.0f}亿<extra></extra>",
        )
    )
    fig_mf.add_trace(
        go.Scatter(
            x=df_mf_show["日期"],
            y=df_mf_show["上证-收盘价"],
            mode="lines",
            line=dict(color="#667eea", width=2),
            name="上证指数",
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}<br>上证: %{y:.2f}<extra></extra>",
        )
    )
    fig_mf.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=20, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.08),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(
            title="主力净流入 (亿)",
            gridcolor="#f3f4f6",
            zeroline=True,
            zerolinecolor="#cbd5e1",
        ),
        yaxis2=dict(title="上证指数", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(fig_mf, use_container_width=True)


# ============== 内部辅助函数 ==============


def _fund_card(label: str, value_yi: float, sub: str = "", large: bool = False) -> str:
    """生成资金指标卡 HTML"""
    pos = value_yi >= 0
    color = "#ef5350" if pos else "#26a69a"
    sign = "+" if pos else ""
    font_size = "font-size:1.5rem;" if large else ""
    fmt = "{:+.0f}" if large else "{:+.2f}"
    return f"""
    <div class='metric-card'>
        <div class='metric-label'>{label}</div>
        <div class='metric-value' style='color:{color}; {font_size}'>{sign}{fmt.format(value_yi)}<span style='font-size:0.9rem; color:#9ca3af; margin-left:4px;'>亿</span></div>
        <div style='color:#9ca3af; font-size:0.78rem; margin-top:4px;'>{sub}</div>
    </div>"""


def _color_pos_neg(v):
    """DataFrame 样式函数：正数红、负数绿"""
    if isinstance(v, (int, float)):
        if v > 0:
            return "color: #ef5350; font-weight: 600"
        elif v < 0:
            return "color: #26a69a; font-weight: 600"
    return ""


def _render_main_force_judgment(s: dict):
    """渲染主力进出场判定"""
    super_5d_yi = float(s.get("super_total_yi", 0) or 0)
    float(s.get("large_total_yi", 0) or 0)
    small_5d_yi = float(s.get("small_total_yi", 0) or 0)

    if super_5d_yi > 0.5:  # 5000 万 = 0.5 亿
        judge_label = "🟥 主力进场"
        judge_color = "#ef5350"
        if small_5d_yi < -0.3:
            judge_detail = (
                f"超大单近 5 日净流入 {super_5d_yi:+.2f} 亿（>5000万），"
                f"散户净流出 {small_5d_yi:+.2f} 亿，典型主力底部吸筹特征。"
            )
        else:
            judge_detail = f"超大单近 5 日净流入 {super_5d_yi:+.2f} 亿（>5000万），机构主导买入。"
    elif super_5d_yi < -0.5:
        judge_label = "🟩 主力出货"
        judge_color = "#26a69a"
        if small_5d_yi > 0.3:
            judge_detail = (
                f"超大单近 5 日净流出 {super_5d_yi:+.2f} 亿，散户净流入 "
                f"{small_5d_yi:+.2f} 亿，警惕主力借利好出货 / 散户接盘。"
            )
        else:
            judge_detail = f"超大单近 5 日净流出 {super_5d_yi:+.2f} 亿，主力撤退中。"
    else:
        judge_label = "🟨 主力观望"
        judge_color = "#ff9800"
        judge_detail = f"超大单近 5 日净额 {super_5d_yi:+.2f} 亿（±5000万 内），主力暂未明确选择方向。"

    st.html(f"""
    <div style='background:#f8f9fb; border-left:5px solid {judge_color};
                border-radius:8px; padding:14px 18px; margin-top:14px;'>
        <div style='font-weight:700; font-size:1rem; color:{judge_color};'>{judge_label}</div>
        <div style='font-size:0.88rem; color:#374151; margin-top:4px;'>{judge_detail}</div>
    </div>
    """)
