"""
基本面 Tab 渲染组件(v0.7 新增)
- 接管原 Tab6 全部内容
- 按 PRD US-1/US-2: 财务摘要 → 股东结构 → 同业对比
- 数据从 backend.fundamentals.load_fundamentals() 获取
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from fundamentals import load_fundamentals, FundamentalsData  # noqa: E402


# ============== 缓存包装(Streamlit 层 24h) ==============
@st.cache_data(ttl=86400, show_spinner=False)
def _cached_load(symbol: str, stock_name: str) -> dict:
    """缓存返回 dict(避免 dataclass 序列化坑)"""
    data = load_fundamentals(symbol, stock_name)
    return data.to_dict()


def _from_dict(d: dict) -> FundamentalsData:
    from fundamentals import (
        FundamentalsData as FD,
        FinancialPeriod,
        ShareholderRow,
        PeerRow,
    )

    out = FD(
        symbol=d.get("symbol", ""),
        stock_name=d.get("stock_name", ""),
        data_date=d.get("data_date", ""),
        industry_name=d.get("industry_name", ""),
        has_error=d.get("has_error", False),
        error_msg=d.get("error_msg", ""),
    )
    for f in d.get("financials", []) or []:
        out.financials.append(FinancialPeriod(**f))
    for f in d.get("top_holders", []) or []:
        out.top_holders.append(ShareholderRow(**f))
    for f in d.get("circulate_holders", []) or []:
        out.circulate_holders.append(ShareholderRow(**f))
    for f in d.get("inst_changes", []) or []:
        out.inst_changes.append(ShareholderRow(**f))
    for f in d.get("peers", []) or []:
        out.peers.append(PeerRow(**f))
    return out


# ============== 子区:核心信息卡片(沿用 v0.6 行为) ==============
def _render_basic_info_cards(info: dict):
    """保留原 Tab6 上半部分:基础信息卡片"""
    st.markdown("##### 📌 核心指标")
    if not info:
        st.info("基本面数据暂未获取到")
        return
    info_items = list(info.items())
    cols = st.columns(2)
    for idx, (k, v) in enumerate(info_items):
        with cols[idx % 2]:
            st.html(f"""
            <div style='padding:10px 14px; background:#f8f9fb; border-radius:8px; margin-bottom:8px;'>
                <span style='color:#6b7280; font-size:0.85rem;'>{k}</span>
                <span style='float:right; color:#1f2937; font-weight:600;'>{v}</span>
            </div>
            """)


# ============== 子区:财务摘要 ==============
def _render_financial_summary(data: FundamentalsData):
    st.markdown("##### 📊 财务摘要(近 4 期)")
    if not data.financials:
        st.info("该股暂无完整财报数据")
        return

    # 反转:接口返回新到旧,我们图表按时间从左到右展示
    fins = list(reversed(data.financials))
    periods = [f.period for f in fins]
    revenue = [f.revenue_yi for f in fins]
    net_profit = [f.net_profit_yi for f in fins]
    gross = [f.gross_margin_pct for f in fins]
    roe = [f.roe_pct for f in fins]
    debt = [f.debt_ratio_pct for f in fins]
    yoy_rev = [f.yoy_revenue for f in fins]
    yoy_np = [f.yoy_net_profit for f in fins]

    # ---- 第一行:营收 / 净利润 折线 ----
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=periods,
                y=revenue,
                mode="lines+markers+text",
                text=[f"{v:.1f}" for v in revenue],
                textposition="top center",
                line=dict(color="#ef5350", width=2.5),
                marker=dict(size=10),
                name="营业收入(亿)",
            )
        )
        fig.update_layout(
            title=dict(text="营业收入(亿元)", x=0.5, font=dict(size=13)),
            height=260,
            margin=dict(l=10, r=10, t=40, b=20),
            plot_bgcolor="white",
            showlegend=False,
            yaxis=dict(gridcolor="#f1f5f9"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=periods,
                y=net_profit,
                mode="lines+markers+text",
                text=[f"{v:.1f}" for v in net_profit],
                textposition="top center",
                line=dict(color="#ff9800", width=2.5),
                marker=dict(size=10),
                name="归母净利润(亿)",
            )
        )
        fig.update_layout(
            title=dict(text="归母净利润(亿元)", x=0.5, font=dict(size=13)),
            height=260,
            margin=dict(l=10, r=10, t=40, b=20),
            plot_bgcolor="white",
            showlegend=False,
            yaxis=dict(gridcolor="#f1f5f9"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---- 第二行:毛利率 / ROE / 负债率 ----
    c3, c4, c5 = st.columns(3)
    with c3:
        fig = go.Figure(
            go.Bar(
                x=periods,
                y=gross,
                marker_color="#26a69a",
                text=[f"{v:.1f}%" for v in gross],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=dict(text="毛利率(%)", x=0.5, font=dict(size=13)),
            height=260,
            margin=dict(l=10, r=10, t=40, b=20),
            plot_bgcolor="white",
            showlegend=False,
            yaxis=dict(gridcolor="#f1f5f9"),
        )
        st.plotly_chart(fig, use_container_width=True)
    with c4:
        fig = go.Figure(
            go.Bar(
                x=periods,
                y=roe,
                marker_color="#6366f1",
                text=[f"{v:.1f}%" for v in roe],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=dict(text="ROE(%)", x=0.5, font=dict(size=13)),
            height=260,
            margin=dict(l=10, r=10, t=40, b=20),
            plot_bgcolor="white",
            showlegend=False,
            yaxis=dict(gridcolor="#f1f5f9"),
        )
        st.plotly_chart(fig, use_container_width=True)
    with c5:
        fig = go.Figure(
            go.Bar(
                x=periods,
                y=debt,
                marker_color="#9ca3af",
                text=[f"{v:.1f}%" for v in debt],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=dict(text="资产负债率(%)", x=0.5, font=dict(size=13)),
            height=260,
            margin=dict(l=10, r=10, t=40, b=20),
            plot_bgcolor="white",
            showlegend=False,
            yaxis=dict(gridcolor="#f1f5f9"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---- 同比柱图 ----
    if any(abs(v) > 0.01 for v in yoy_rev + yoy_np):
        c6, c7 = st.columns(2)
        with c6:
            colors_r = ["#ef5350" if v >= 0 else "#26a69a" for v in yoy_rev]
            fig = go.Figure(
                go.Bar(
                    x=periods,
                    y=yoy_rev,
                    marker_color=colors_r,
                    text=[f"{v:+.1f}%" for v in yoy_rev],
                    textposition="outside",
                )
            )
            fig.update_layout(
                title=dict(text="营收同比增速(%)", x=0.5, font=dict(size=13)),
                height=240,
                margin=dict(l=10, r=10, t=40, b=20),
                plot_bgcolor="white",
                showlegend=False,
                yaxis=dict(gridcolor="#f1f5f9", zeroline=True, zerolinecolor="#cbd5e1"),
            )
            st.plotly_chart(fig, use_container_width=True)
        with c7:
            colors_n = ["#ef5350" if v >= 0 else "#26a69a" for v in yoy_np]
            fig = go.Figure(
                go.Bar(
                    x=periods,
                    y=yoy_np,
                    marker_color=colors_n,
                    text=[f"{v:+.1f}%" for v in yoy_np],
                    textposition="outside",
                )
            )
            fig.update_layout(
                title=dict(text="净利同比增速(%)", x=0.5, font=dict(size=13)),
                height=240,
                margin=dict(l=10, r=10, t=40, b=20),
                plot_bgcolor="white",
                showlegend=False,
                yaxis=dict(gridcolor="#f1f5f9", zeroline=True, zerolinecolor="#cbd5e1"),
            )
            st.plotly_chart(fig, use_container_width=True)


# ============== 子区:股东结构 ==============
def _shareholder_to_df(rows, with_change: bool = False) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    cols = {
        "rank": "序号",
        "name": "名称",
        "shares_yi": "持股(亿股)",
        "ratio_pct": "占比(%)",
    }
    if with_change:
        cols["change_type"] = "变动"
    df = pd.DataFrame([{cols[k]: getattr(r, k) for k in cols} for r in rows])
    return df


def _render_shareholders(data: FundamentalsData):
    st.markdown("##### 👥 股东结构")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**十大股东**")
        df = _shareholder_to_df(data.top_holders, with_change=True)
        if df.empty:
            st.info("该股暂无完整十大股东数据")
        else:
            st.dataframe(
                df.style.format({"持股(亿股)": "{:.4f}", "占比(%)": "{:.2f}"}),
                hide_index=True,
                use_container_width=True,
                height=380,
            )

    with c2:
        st.markdown("**十大流通股东**")
        df = _shareholder_to_df(data.circulate_holders, with_change=True)
        if df.empty:
            st.info("该股暂无完整流通股东数据")
        else:
            st.dataframe(
                df.style.format({"持股(亿股)": "{:.4f}", "占比(%)": "{:.2f}"}),
                hide_index=True,
                use_container_width=True,
                height=380,
            )

    st.markdown("**机构持仓变动**")
    df = _shareholder_to_df(data.inst_changes, with_change=True)
    if df.empty:
        st.info("该股暂无完整机构持仓变动数据")
    else:
        st.dataframe(
            df.style.format({"持股(亿股)": "{:.4f}", "占比(%)": "{:.2f}"}),
            hide_index=True,
            use_container_width=True,
            height=320,
        )


# ============== 子区:同业对比 ==============
def _render_peers(data: FundamentalsData):
    st.markdown("##### 🏢 同业对比")
    if not data.peers:
        st.info("该股暂无完整同业对比数据")
        return

    industry = data.industry_name or "未识别行业"
    st.markdown(f"**所属行业**: {industry}  · **对比口径**: 行业总市值前 8 + 本股(最多 9 行)")

    rows = []
    for p in data.peers:
        rows.append(
            {
                "代码": p.symbol,
                "股票": (p.name + "(当前股票)") if p.is_self else p.name,
                "总市值(亿)": p.total_mcap_yi,
                "PE": p.pe,
                "PB": p.pb,
                "ROE(%)": p.roe_pct,
                "营收同比(%)": p.yoy_revenue_pct,
                "净利同比(%)": p.yoy_net_profit_pct,
                "_self": p.is_self,
            }
        )
    df = pd.DataFrame(rows)

    def _highlight(row):
        if row.get("_self"):
            return ["background-color: #fff3cd; font-weight: 700; color: #92400e"] * len(row)
        return [""] * len(row)

    show_df = df.drop(columns=["_self"])
    styled = show_df.style.apply(_highlight, axis=1).format(
        {
            "总市值(亿)": "{:.1f}",
            "PE": "{:.2f}",
            "PB": "{:.2f}",
            "ROE(%)": "{:.2f}",
            "营收同比(%)": "{:+.2f}",
            "净利同比(%)": "{:+.2f}",
        }
    )
    st.dataframe(styled, hide_index=True, use_container_width=True, height=42 * (len(df) + 1) + 4)


# ============== 主入口 ==============
def render(symbol: str, stock_name: str, info: dict | None = None):
    """
    Tab6 完整渲染入口。
    - symbol: 6 位股票代码
    - stock_name: 股票简称
    - info: get_stock_info 的字典(沿用 v0.6 上半部分卡片)
    """
    st.markdown("#### 💡 基本面")

    # 顶部刷新
    cr1, cr2 = st.columns([1, 5])
    with cr1:
        if st.button("🔄 刷新基本面", use_container_width=True, key=f"refresh_fd_{symbol}"):
            _cached_load.clear()
            st.rerun()
    with cr2:
        st.caption("数据缓存 24 小时(财务/股东/同业)。点击刷新强制重新拉取。")

    # 上半部分:核心信息卡片(沿用 v0.6)
    _render_basic_info_cards(info or {})

    st.markdown("---")

    # 下半部分:加载完整基本面
    with st.spinner(f"正在拉取 {stock_name} 基本面数据..."):
        try:
            d_dict = _cached_load(symbol, stock_name)
            data = _from_dict(d_dict)
        except Exception as e:
            st.error(f"基本面数据加载失败: {e}")
            return

    if data.has_error and not data.financials and not data.peers:
        st.warning(f"⚠️ 该股暂无完整基本面数据。{data.error_msg}")
        return

    _render_financial_summary(data)
    st.markdown("---")
    _render_shareholders(data)
    st.markdown("---")
    _render_peers(data)
