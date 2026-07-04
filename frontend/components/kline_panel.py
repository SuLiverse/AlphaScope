"""
K线 & 技术指标面板 (tab1)
从 dashboard.py 提取，包含：K线蜡烛图、MA均线、MACD、RSI、成交量柱图。
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render(df, show_ma: bool = True, show_macd: bool = True, show_rsi: bool = False):
    """
    渲染 K 线 & 技术指标面板。

    Args:
        df: 包含 date/open/high/low/close/volume 以及可选 MA5/MA10/MA20/MA60/DIF/DEA/MACD/RSI 列的 DataFrame
        show_ma: 是否显示均线
        show_macd: 是否显示 MACD
        show_rsi: 是否显示 RSI
    """
    # 子图行数
    rows = 1
    row_heights = [0.55]
    subplot_titles = ["K 线"]
    if show_macd:
        rows += 1
        row_heights.append(0.2)
        subplot_titles.append("MACD")
    if show_rsi:
        rows += 1
        row_heights.append(0.15)
        subplot_titles.append("RSI")
    rows += 1
    row_heights.append(0.18)
    subplot_titles.append("成交量")

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # K 线
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing=dict(line=dict(color="#ef5350", width=1), fillcolor="#ef5350"),
            decreasing=dict(line=dict(color="#26a69a", width=1), fillcolor="#26a69a"),
            name="K线",
        ),
        row=1,
        col=1,
    )

    # 均线
    if show_ma:
        ma_colors = {
            "MA5": "#ff9800",
            "MA10": "#2196f3",
            "MA20": "#9c27b0",
            "MA60": "#607d8b",
        }
        for ma, color in ma_colors.items():
            if ma in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["date"],
                        y=df[ma],
                        mode="lines",
                        line=dict(color=color, width=1.2),
                        name=ma,
                        opacity=0.85,
                    ),
                    row=1,
                    col=1,
                )

    current_row = 2
    # MACD
    if show_macd:
        macd_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df["MACD"]]
        fig.add_trace(
            go.Bar(x=df["date"], y=df["MACD"], marker_color=macd_colors, name="MACD"),
            row=current_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["DIF"],
                mode="lines",
                line=dict(color="#ff9800", width=1),
                name="DIF",
            ),
            row=current_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["DEA"],
                mode="lines",
                line=dict(color="#2196f3", width=1),
                name="DEA",
            ),
            row=current_row,
            col=1,
        )
        current_row += 1

    # RSI
    if show_rsi:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["RSI"],
                mode="lines",
                line=dict(color="#9c27b0", width=1.5),
                name="RSI",
            ),
            row=current_row,
            col=1,
        )
        fig.add_hline(
            y=70,
            line_dash="dash",
            line_color="#ef5350",
            opacity=0.4,
            row=current_row,
            col=1,
        )
        fig.add_hline(
            y=30,
            line_dash="dash",
            line_color="#26a69a",
            opacity=0.4,
            row=current_row,
            col=1,
        )
        current_row += 1

    # 成交量
    vol_colors = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["volume"],
            marker_color=vol_colors,
            name="成交量",
            opacity=0.7,
        ),
        row=current_row,
        col=1,
    )

    fig.update_layout(
        height=700,
        template="plotly_white",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")

    st.plotly_chart(fig, use_container_width=True)
