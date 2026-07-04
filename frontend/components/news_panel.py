"""
资讯 & 研报面板 (tab4)
从 dashboard.py 提利，包含：时间轴模式、个股相关资讯、个股公告、关联概念新闻、行业新闻、大盘快讯、机构研报评级。
"""

import math as _math
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 后端模块 -- 组件自包含导入，避免循环依赖
try:
    from news_data import (
        fetch_telegraph_em,
        fetch_telegraph_cls,
        fetch_telegraph_sina,
        fetch_research_report,
        get_stock_related_news,
        fetch_announcements_cninfo,
        fetch_announcements_em_today,
        merge_announcements,
        ANN_COLORS,
        fetch_main_business,
        fetch_industry_name,
        get_industry_news,
        fetch_stock_news_em,
        extract_business_terms,
        fetch_stock_concepts,
        get_concept_news,
        get_concept_keywords,
        build_topic_news_keywords,
        fetch_topic_news_em,
        merge_news_items,
    )

    _NEWS_AVAILABLE = True
except Exception:
    _NEWS_AVAILABLE = False


# ============== 组件内部缓存函数 ==============
# 注意：这些缓存函数与 dashboard.py 中的同名函数功能一致，
# 但因为 @st.cache_data 按函数对象做 key，所以会有独立缓存。
# 后续可统一抽取到 data_access.py 共享模块中。


@st.cache_data(ttl=180)
def _cached_telegraph_em(limit: int = 200):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_telegraph_em(limit=limit)


@st.cache_data(ttl=180)
def _cached_telegraph_cls(limit: int = 30):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_telegraph_cls(limit=limit)


@st.cache_data(ttl=180)
def _cached_telegraph_sina(limit: int = 20):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_telegraph_sina(limit=limit)


@st.cache_data(ttl=600)
def _cached_research_report(symbol: str, limit: int = 20):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_research_report(symbol, limit=limit)


@st.cache_data(ttl=600)
def _cached_announcements_cninfo(symbol: str, days: int = 30):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_announcements_cninfo(symbol, days=days)


@st.cache_data(ttl=900)
def _cached_announcements_em_today():
    if not _NEWS_AVAILABLE:
        return []
    return fetch_announcements_em_today()


@st.cache_data(ttl=3600)
def _cached_main_business(symbol: str):
    if not _NEWS_AVAILABLE:
        return {}
    return fetch_main_business(symbol)


@st.cache_data(ttl=3600)
def _cached_industry_name(symbol: str):
    if not _NEWS_AVAILABLE:
        return ""
    return fetch_industry_name(symbol)


@st.cache_data(ttl=600)
def _cached_stock_news_em(symbol: str, limit: int = 20):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_stock_news_em(symbol, limit=limit)


@st.cache_data(ttl=600)
def _cached_topic_news_em(keywords_tuple, limit_each: int = 8, total_limit: int = 30):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_topic_news_em(list(keywords_tuple or ()), limit_each=limit_each, total_limit=total_limit)


@st.cache_data(ttl=3600)
def _cached_stock_concepts(symbol: str, stock_name: str):
    if not _NEWS_AVAILABLE:
        return []
    return fetch_stock_concepts(symbol, stock_name=stock_name, max_concepts=12)


# ============== 渲染函数 ==============


def render(stock_name: str, symbol: str):
    """
    渲染「资讯 & 研报」面板（tab4 全部内容）。

    Args:
        stock_name: 股票名称
        stock_code: 股票代码（6 位数字）
    """
    st.markdown("#### 📰 实时资讯 & 机构研报")
    if not _NEWS_AVAILABLE:
        st.error("新闻模块加载失败，资讯面板不可用。")
        return

    # 顶部操作栏 + v0.7 视图切换
    col_refresh, col_view, col_info = st.columns([1, 2, 4])
    with col_refresh:
        if st.button("🔄 刷新数据", use_container_width=True, key="news_refresh_btn"):
            st.cache_data.clear()
            st.rerun()
    with col_view:
        view_mode = st.radio(
            "视图",
            ["📅 时间轴", "📂 分类"],
            horizontal=True,
            label_visibility="collapsed",
            key="news_view_mode",
            index=1,
        )
    with col_info:
        st.caption("时间轴模式合并三源最近 10 条按时间倒序；分类模式展示原有子 Tab。")

    # ---------- v0.7 时间轴模式 ----------
    if "时间轴" in view_mode:
        with st.spinner("正在合并三源最近资讯..."):
            em_news = _cached_telegraph_em(limit=50)
            cls_news = _cached_telegraph_cls(limit=20)
            sina_news = _cached_telegraph_sina(limit=20)
            merged = (em_news or []) + (cls_news or []) + (sina_news or [])

        def _parse_dt(item):
            s = str(item.get("datetime", "")).strip()
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%m-%d %H:%M:%S",
                "%m-%d %H:%M",
                "%H:%M:%S",
                "%H:%M",
            ):
                try:
                    d = datetime.strptime(s, fmt)
                    if d.year == 1900:
                        d = d.replace(year=datetime.now().year)
                    return d
                except Exception:
                    continue
            return datetime.min

        merged_sorted = sorted(merged, key=_parse_dt, reverse=True)[:10]

        if not merged_sorted:
            st.info("暂无可用资讯")
        else:
            st.markdown(
                f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                f"合并财联社 / 东财 / 新浪，共 <b>{len(merged_sorted)}</b> 条（按时间倒序）</div>",
                unsafe_allow_html=True,
            )
            src_color_map = {
                "东财": "#1976d2",
                "财联社": "#d32f2f",
                "新浪": "#f57c00",
            }
            for n in merged_sorted:
                src = n.get("source", "")
                src_color = src_color_map.get(src, "#666")
                title = n.get("title", "")
                summary = n.get("summary", "")
                dt = n.get("datetime", "")
                url = n.get("url", "")
                title_html = (
                    f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                    if url
                    else title
                )
                st.html(f"""
                <div style='background:white; border-left:3px solid {src_color}; padding:12px 16px;
                            margin-bottom:10px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.04);'>
                    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
                        <span style='background:{src_color}; color:white; padding:2px 8px; border-radius:4px;
                                     font-size:0.72rem; font-weight:600;'>{src}</span>
                        <span style='color:#9ca3af; font-size:0.78rem;'>{dt}</span>
                    </div>
                    <div style='font-weight:600; font-size:0.98rem; margin-bottom:6px;'>{title_html}</div>
                    <div style='color:#6b7280; font-size:0.86rem; line-height:1.55;'>{summary}</div>
                </div>
                """)

    # ---------- 原有分类模式 ----------
    else:
        # v0.10: 子 Tab 拆分为 5 个，公告与行业新闻独立成区
        sub_tab1, sub_ann, sub_concept, sub_industry, sub_tab2, sub_tab3 = st.tabs(
            [
                f"🎯 {stock_name} 相关资讯",
                "📋 个股公告",
                "🧩 关联概念",
                "🏭 行业新闻",
                "🌐 大盘快讯（财联社/东财/新浪）",
                "📑 机构研报评级",
            ]
        )

        # 预加载通用数据（多个子 Tab 共用）
        with st.spinner("正在加载基础数据..."):
            em_news = _cached_telegraph_em(limit=200)
            cls_news = _cached_telegraph_cls(limit=30)
            sina_news = _cached_telegraph_sina(limit=20)
            all_news = em_news + cls_news + sina_news
            main_biz = _cached_main_business(symbol) or {}
            industry = _cached_industry_name(symbol)

        # ============ 子 Tab 1: 个股相关 ============
        with sub_tab1:
            with st.spinner("正在筛选相关资讯..."):
                stock_specific = _cached_stock_news_em(symbol, limit=20) or []
                keyword_matched = get_stock_related_news(
                    stock_name,
                    all_news,
                    limit=30,
                    symbol=symbol,
                    products=main_biz.get("products"),
                )
                seen = set()
                related = []
                for src_list in (stock_specific, keyword_matched):
                    for n in src_list:
                        key = (
                            n.get("title", "").strip(),
                            n.get("datetime", "")[:10],
                        )
                        if not key[0] or key in seen:
                            continue
                        seen.add(key)
                        related.append(n)

            if not related:
                st.info(f"近期未发现与「{stock_name}」直接相关的资讯，建议查看大盘快讯或研报。")
            else:
                from news_data import _expand_stock_keywords

                stock_kws = _expand_stock_keywords(stock_name, symbol, products=main_biz.get("products"))
                n_specific = len(stock_specific or [])
                n_total = len(related)
                n_kw = max(0, n_total - n_specific)
                kw_chip_str = " · ".join(stock_kws) if stock_kws else "(空)"
                st.markdown(
                    f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                    f"共 <b>{n_total}</b> 条：东财个股 API <b>{n_specific}</b> 条 + 大盘快讯关键词命中 <b>{n_kw}</b> 条"
                    f"<br><span style='color:#9ca3af; font-size:0.78rem;'>关键词：{kw_chip_str}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                for n in related:
                    _render_news_card(n)

        # ============ 子区: 个股公告 ============
        with sub_ann:
            with st.spinner("正在加载公告..."):
                cninfo_ann = _cached_announcements_cninfo(symbol, days=30)
                em_ann_today = _cached_announcements_em_today() or []
                em_ann_for_stock = [a for a in em_ann_today if a.get("code") == symbol]
                ann_list = merge_announcements(cninfo_ann, em_ann_for_stock)

            if not ann_list:
                st.info(f"近 30 天内未发现 {stock_name}({symbol}) 的公告。可能是接口暂时不可用，稍后刷新重试。")
            else:
                cat_counts = {}
                for a in ann_list:
                    cat_counts[a.get("category", "其他")] = cat_counts.get(a.get("category", "其他"), 0) + 1

                def _ann_chip(c, n):
                    cc = ANN_COLORS.get(c, "#6b7280")
                    return f"<span style='color:{cc};'>{c} {n}</span>"

                summary_chips = " · ".join(_ann_chip(c, n) for c, n in sorted(cat_counts.items(), key=lambda x: -x[1]))
                st.markdown(
                    f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                    f"近 30 天 <b>{len(ann_list)}</b> 条公告 · {summary_chips}</div>",
                    unsafe_allow_html=True,
                )
                for a in ann_list:
                    cat = a.get("category", "其他")
                    cc = ANN_COLORS.get(cat, "#6b7280")
                    title = a.get("title", "")
                    url = a.get("url", "")
                    date = a.get("date", "")
                    src = a.get("source", "")
                    title_html = (
                        f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                        if url
                        else title
                    )
                    st.html(f"""
                    <div style='background:white; border-left:3px solid {cc}; padding:10px 14px;
                                margin-bottom:8px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.04);'>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;'>
                            <span style='background:{cc}; color:white; padding:2px 8px; border-radius:4px;
                                         font-size:0.72rem; font-weight:600;'>{cat}</span>
                            <span style='color:#9ca3af; font-size:0.78rem;'>{date} · {src}</span>
                        </div>
                        <div style='font-weight:500; font-size:0.94rem;'>{title_html}</div>
                    </div>
                    """)

        # ============ 子区: 关联概念 ============
        with sub_concept:
            concepts = _cached_stock_concepts(symbol, stock_name) or []
            if not concepts:
                st.info("暂未识别到该股票的概念板块，或概念接口暂时不可用。")
            else:
                concept_kws = get_concept_keywords(concepts, limit=12)

                def _chip(c):
                    name = c.get("name", "")
                    precise = c.get("is_precise", False)
                    bg = "#dbeafe" if precise else "#eef2ff"
                    color = "#1e40af" if precise else "#3730a3"
                    badge = " ★" if precise else ""
                    return (
                        f"<span style='display:inline-block; padding:2px 8px; margin:2px; "
                        f"border-radius:6px; background:{bg}; color:{color}; "
                        f"font-size:0.78rem; font-weight:{'600' if precise else '400'};"
                        f"'>{name}{badge}</span>"
                    )

                chip_html = " ".join(_chip(c) for c in concepts)
                st.markdown(
                    f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                    f"识别到 <b>{len(concepts)}</b> 个关联概念<br>{chip_html}</div>",
                    unsafe_allow_html=True,
                )
                with st.spinner("正在筛选并搜索概念相关新闻..."):
                    excluded = {n.get("title", "").strip() for n in (related or [])}
                    pool_concept_news = get_concept_news(concepts, all_news, limit=30, exclude_titles=excluded)
                    topic_concept_news = _cached_topic_news_em(tuple(concept_kws[:8]), limit_each=6, total_limit=24)
                    topic_concept_news = [n for n in topic_concept_news if n.get("title", "").strip() not in excluded]
                    concept_news = merge_news_items(pool_concept_news, topic_concept_news, limit=30)
                if concept_kws:
                    st.caption("匹配词: " + " · ".join(concept_kws))
                if not concept_news:
                    st.caption("近期未在快讯池或东财主题搜索中发现这些概念的直接相关新闻。")
                else:
                    st.caption(f"快讯池命中 {len(pool_concept_news)} 条 + 主题搜索补充 {len(topic_concept_news)} 条")
                    for n in concept_news:
                        _render_concept_news_card(n)

        # ============ 子区: 行业新闻 ============
        with sub_industry:
            # v0.14: 如果行业名为空，尝试从概念板块中提取
            if not industry:
                concepts_for_industry = _cached_stock_concepts(symbol, stock_name) or []
                if concepts_for_industry:
                    industry = fetch_industry_name(symbol, concepts=concepts_for_industry)
            if not industry:
                st.info("未能识别该股票的行业，无法生成行业新闻。")
            else:
                extra_kws = []
                scope_text = (main_biz or {}).get("scope") or ""
                if scope_text:
                    extra_kws = extract_business_terms(scope_text, max_terms=8)
                concepts = _cached_stock_concepts(symbol, stock_name) or []
                extra_kws += get_concept_keywords(concepts, limit=10)
                with st.spinner("正在筛选并搜索行业新闻..."):
                    excluded = {n.get("title", "").strip() for n in (related or [])}
                    pool_ind_news = get_industry_news(
                        industry,
                        all_news,
                        limit=30,
                        exclude_titles=excluded,
                        extra_keywords=extra_kws,
                    )
                    topic_kws = build_topic_news_keywords(
                        industry=industry,
                        business_terms=extra_kws,
                        concepts=concepts,
                        limit=8,
                    )
                    topic_ind_news = _cached_topic_news_em(tuple(topic_kws), limit_each=6, total_limit=24)
                    topic_ind_news = [n for n in topic_ind_news if n.get("title", "").strip() not in excluded]
                    ind_news = merge_news_items(pool_ind_news, topic_ind_news, limit=30)
                if not ind_news:
                    st.caption(f"近期未发现「{industry}」行业的快讯或主题搜索新闻。")
                else:
                    kw_chips = " · ".join(topic_kws or [industry] + list(extra_kws))
                    st.markdown(
                        f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                        f"行业：<b>{industry}</b> · 共 <b>{len(ind_news)}</b> 条相关行业资讯"
                        f" · 快讯池 <b>{len(pool_ind_news)}</b> 条 + 主题搜索 <b>{len(topic_ind_news)}</b> 条"
                        f"<br><span style='color:#9ca3af; font-size:0.78rem;'>匹配词：{kw_chips}</span></div>",
                        unsafe_allow_html=True,
                    )
                    for n in ind_news:
                        _render_industry_news_card(n)

        # ============ 子 Tab 2: 大盘快讯 ============
        with sub_tab2:
            src_choice = st.radio(
                "选择资讯源",
                [
                    "📡 财联社（实时电报）",
                    "💹 东方财富（覆盖最广）",
                    "🔔 新浪财经（速度最快）",
                ],
                horizontal=True,
                label_visibility="collapsed",
            )
            if "财联社" in src_choice:
                items = _cached_telegraph_cls(limit=20)
                src, src_color = "财联社", "#d32f2f"
            elif "东方财富" in src_choice:
                items = _cached_telegraph_em(limit=30)
                src, src_color = "东财", "#1976d2"
            else:
                items = _cached_telegraph_sina(limit=20)
                src, src_color = "新浪", "#f57c00"

            st.markdown(
                f"<div style='color:#6b7280; font-size:0.85rem; margin-bottom:10px;'>{src} · 共 <b>{len(items)}</b> 条</div>",
                unsafe_allow_html=True,
            )
            for n in items:
                title = n.get("title", "")
                summary = n.get("summary", "")
                dt = n.get("datetime", "")
                url = n.get("url", "")
                title_html = (
                    f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                    if url
                    else title
                )
                st.html(f"""
                <div style='background:white; border-left:3px solid {src_color}; padding:10px 14px; margin-bottom:8px; border-radius:6px;'>
                    <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;'>
                        <span style='font-weight:600; font-size:0.94rem;'>{title_html}</span>
                        <span style='color:#9ca3af; font-size:0.76rem; white-space:nowrap; margin-left:10px;'>{dt}</span>
                    </div>
                    <div style='color:#6b7280; font-size:0.83rem; line-height:1.5;'>{summary}</div>
                </div>
                """)

        # ============ 子 Tab 3: 研报评级 ============
        with sub_tab3:
            with st.spinner(f"正在抓取 {stock_name} 的研报..."):
                reports = _cached_research_report(symbol, limit=20)

            if not reports:
                st.info(f"暂未抓到 {stock_name}（{symbol}）的近期研报。")
            else:
                _render_research_reports(reports)


# ============== 内部渲染辅助函数 ==============


def _render_news_card(n: dict):
    """渲染单条新闻卡片（个股相关资讯）"""
    src = n.get("source", "")
    src_color = {
        "东财": "#1976d2",
        "财联社": "#d32f2f",
        "新浪": "#f57c00",
    }.get(src, "#666")
    title = n.get("title", "")
    summary = n.get("summary", "")
    dt = n.get("datetime", "")
    url = n.get("url", "")
    title_html = (
        f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>" if url else title
    )
    st.html(f"""
    <div style='background:white; border-left:3px solid {src_color}; padding:12px 16px; margin-bottom:10px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.04);'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
            <span style='background:{src_color}; color:white; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:600;'>{src}</span>
            <span style='color:#9ca3af; font-size:0.78rem;'>{dt}</span>
        </div>
        <div style='font-weight:600; font-size:0.98rem; margin-bottom:6px;'>{title_html}</div>
        <div style='color:#6b7280; font-size:0.86rem; line-height:1.55;'>{summary}</div>
    </div>
    """)


def _render_concept_news_card(n: dict):
    """渲染概念相关新闻卡片"""
    src = n.get("source", "")
    src_color = {
        "东财": "#1976d2",
        "东财搜索": "#1976d2",
        "财联社": "#d32f2f",
        "新浪": "#f57c00",
    }.get(src, "#666")
    title = n.get("title", "")
    summary = n.get("summary", "")
    dt = n.get("datetime", "")
    url = n.get("url", "")
    topic = n.get("topic", "")
    tags = n.get("matched_keywords", [])
    if topic and topic not in tags:
        tags = [topic] + tags
    tag_html = "".join(
        f"<span style='display:inline-block; background:#e0e7ff; color:#3730a3; "
        f"padding:1px 6px; border-radius:4px; font-size:0.68rem; "
        f"margin-right:4px;'>{t}</span>"
        for t in tags[:3]
    )
    title_html = (
        f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>" if url else title
    )
    st.html(f"""
    <div style='background:white; border-left:3px solid {src_color}; padding:10px 14px;
                margin-bottom:8px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.04);'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;'>
            <span style='background:{src_color}; color:white; padding:2px 8px; border-radius:4px;
                         font-size:0.72rem; font-weight:600;'>{src}</span>
            <span style='color:#9ca3af; font-size:0.78rem;'>{dt}</span>
        </div>
        <div style='font-weight:500; font-size:0.94rem; margin-bottom:4px;'>{title_html}</div>
        {f"<div style='margin-bottom:4px;'>{tag_html}</div>" if tag_html else ""}
        <div style='color:#6b7280; font-size:0.84rem; line-height:1.5;'>{summary}</div>
    </div>
    """)


def _render_industry_news_card(n: dict):
    """渲染行业新闻卡片"""
    src = n.get("source", "")
    src_color = {
        "东财": "#1976d2",
        "东财搜索": "#1976d2",
        "财联社": "#d32f2f",
        "新浪": "#f57c00",
    }.get(src, "#666")
    title = n.get("title", "")
    summary = n.get("summary", "")
    dt = n.get("datetime", "")
    url = n.get("url", "")
    topic = n.get("topic", "")
    tags = n.get("matched_keywords", [])
    if topic and topic not in tags:
        tags = [topic] + tags
    tag_html = "".join(
        f"<span style='display:inline-block; background:#fef3c7; color:#92400e; "
        f"padding:1px 6px; border-radius:4px; font-size:0.68rem; "
        f"margin-right:4px;'>{t}</span>"
        for t in tags[:3]
    )
    title_html = (
        f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>" if url else title
    )
    st.html(f"""
    <div style='background:white; border-left:3px solid {src_color}; padding:10px 14px;
                margin-bottom:8px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.04);'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;'>
            <span style='background:{src_color}; color:white; padding:2px 8px; border-radius:4px;
                         font-size:0.72rem; font-weight:600;'>{src}</span>
            <span style='color:#9ca3af; font-size:0.78rem;'>{dt}</span>
        </div>
        <div style='font-weight:500; font-size:0.94rem; margin-bottom:4px;'>{title_html}</div>
        {f"<div style='margin-bottom:4px;'>{tag_html}</div>" if tag_html else ""}
        <div style='color:#6b7280; font-size:0.84rem; line-height:1.5;'>{summary}</div>
    </div>
    """)


def _render_research_reports(reports: list):
    """渲染机构研报评级（评级分布饼图 + 评级一览表 + 研报详情列表）"""
    # 评级分布饼图
    rating_dist = {}
    for r in reports:
        rating = (r.get("rating") or "").strip()
        if not rating or rating.lower() == "nan":
            rating = "未评级"
        rating_dist[rating] = rating_dist.get(rating, 0) + 1

    rating_colors_map = {
        "买入": "#ef5350",
        "增持": "#ff9800",
        "强烈推荐": "#d32f2f",
        "持有": "#9e9e9e",
        "观望": "#9e9e9e",
        "中性": "#9e9e9e",
        "减持": "#26a69a",
        "卖出": "#00897b",
    }

    col_pie, col_table = st.columns([1, 2])
    with col_pie:
        st.markdown("##### 评级分布")
        pie_colors = [rating_colors_map.get(k, "#bdbdbd") for k in rating_dist.keys()]
        fig_rating = go.Figure(
            data=[
                go.Pie(
                    labels=list(rating_dist.keys()),
                    values=list(rating_dist.values()),
                    hole=0.55,
                    marker=dict(
                        colors=pie_colors,
                        line=dict(color="white", width=2),
                    ),
                    textinfo="label+percent",
                    textfont=dict(size=12),
                )
            ]
        )
        fig_rating.update_layout(
            height=280,
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_rating, use_container_width=True)

    with col_table:
        st.markdown("##### 评级一览（近期）")
        rdf = pd.DataFrame(reports)
        if "pdf" in rdf.columns:
            rdf["报告"] = rdf.apply(
                lambda r: f"📄 {r['title']}" if r.get("pdf") else r["title"],
                axis=1,
            )
        show_cols = ["date", "institution", "rating", "title"]
        rename = {
            "date": "日期",
            "institution": "机构",
            "rating": "评级",
            "title": "报告",
        }
        show_df = rdf[show_cols].rename(columns=rename) if all(c in rdf.columns for c in show_cols) else rdf

        def color_rating(v):
            c = rating_colors_map.get(str(v).strip(), "#666")
            return f"color: {c}; font-weight: 600"

        styled = show_df.style.map(color_rating, subset=["评级"])
        st.dataframe(
            styled,
            height=320,
            use_container_width=True,
            hide_index=True,
        )

    # 研报列表（可点击 PDF）
    st.markdown("##### 研报详情（点击查看 PDF）")

    def _is_num(x):
        try:
            return x is not None and not _math.isnan(float(x))
        except (TypeError, ValueError):
            return False

    for r in reports[:8]:
        rating = r.get("rating") or ""
        if rating.strip().lower() == "nan":
            rating = "未评级"
        rc = rating_colors_map.get(rating, "#9e9e9e")
        pdf_link = (
            f"<a href='{r.get('pdf', '')}' target='_blank' style='color:#667eea;'>📄 PDF</a>" if r.get("pdf") else ""
        )
        eps = r.get("eps_2026")
        pe = r.get("pe_2026")
        forecast = ""
        if _is_num(eps) and _is_num(pe):
            try:
                forecast = f"<span style='color:#6b7280; font-size:0.82rem; margin-left:8px;'>EPS {float(eps):.2f} · PE {float(pe):.1f}×</span>"
            except Exception:
                forecast = ""
        st.html(f"""
        <div style='background:white; padding:10px 14px; margin-bottom:8px; border-radius:6px; border:1px solid #f0f0f0;'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div>
                    <span style='background:{rc}; color:white; padding:2px 10px; border-radius:4px; font-size:0.74rem; font-weight:600; margin-right:8px;'>{rating}</span>
                    <span style='font-weight:600; color:#1f2937;'>{r.get("institution", "")}</span>
                    {forecast}
                </div>
                <div style='color:#9ca3af; font-size:0.78rem;'>{r.get("date", "")} · {pdf_link}</div>
            </div>
            <div style='margin-top:6px; color:#374151; font-size:0.92rem;'>{r.get("title", "")}</div>
        </div>
        """)
