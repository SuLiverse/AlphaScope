"""
金融 Agent 工作台 - 专业版 Dashboard
数据源: akshare (A股) / OpenBB (美股/全球)
LLM: 5 厂商异构（Claude · GPT · DeepSeek · Mimo · SenseNova）
v0.7 新增: 基本面增强 / AI 咨询悬浮 / 专家团圆桌 / 资金流细分 / 资讯时间轴
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import akshare as ak
from datetime import datetime, timedelta

# LLM Agent 模块
try:
    from llm_agents import (
        summarize_with_chairman,
        AGENT_MODEL_CONFIG,
        VENDORS,
        build_market_brief,
        get_default_agent_configs,
        run_custom_agents,
        get_custom_agent_model_table,
        run_agents_with_mode,
    )

    LLM_AVAILABLE = True
except Exception as e:
    LLM_AVAILABLE = False
    LLM_ERROR = str(e)

# 新闻 & 研报模块
try:
    from news_data import (
        fetch_telegraph_em,
        fetch_telegraph_cls,
        fetch_telegraph_sina,
        fetch_research_report,
        get_stock_related_news,
        build_news_brief_for_llm,
        build_research_brief_for_llm,
        # v0.10: 公告 + 行业 + 主营业务
        fetch_announcements_cninfo,
        fetch_announcements_em_today,
        merge_announcements,
        build_announcements_brief_for_llm,
        ANN_COLORS,
        fetch_main_business,
        fetch_industry_name,
        get_industry_news,
        # v0.10.2: 个股专属新闻
        fetch_stock_news_em,
        # v0.10.3: 经营范围 -> 行业关键词
        extract_business_terms,
        # v0.10.4: 概念板块归属与概念新闻
        fetch_stock_concepts,
        get_concept_news,
        get_concept_keywords,
        build_concepts_brief_for_llm,
        # v0.10.5: 行业/概念主题主动搜索
        build_topic_news_keywords,
        fetch_topic_news_em,
        merge_news_items,
    )

    NEWS_AVAILABLE = True
except Exception:
    NEWS_AVAILABLE = False

# 研究存档模块
try:
    from archive import (
        save_report,
        list_reports,
        load_report,
        get_stats,
        delete_report,
        get_combo_stats,
        get_combo_performance,
    )

    ARCHIVE_AVAILABLE = True
except Exception as e:
    ARCHIVE_AVAILABLE = False
    NEWS_ERROR = str(e)

# 归档自动标签模块
try:
    from archive_tagger import tag_all_reports

    TAGGER_AVAILABLE = True
except Exception as e:
    TAGGER_AVAILABLE = False
    TAGGER_ERROR = str(e)

# 资金流向模块
try:
    from fund_flow import (
        fetch_individual_fund_flow,
        fetch_market_fund_flow,
        summarize_fund_flow,
        build_fund_flow_brief_for_llm,
    )

    FUND_AVAILABLE = True
except Exception as e:
    FUND_AVAILABLE = False
    FUND_ERROR = str(e)

# v0.7 新增前端组件
try:
    from components import fundamentals_panel, ai_chat_panel, expert_panel_view

    COMPONENTS_AVAILABLE = True
except Exception as e:
    COMPONENTS_AVAILABLE = False
    COMPONENTS_ERROR = str(e)
    # 单个组件导入失败时不要拖垮全部前端组件。AI 咨询/专家团导入异常时，
    # 基本面 Tab 仍可照常渲染，具体错误在对应功能入口处提示。
    try:
        from components import fundamentals_panel

        FUNDAMENTALS_PANEL_AVAILABLE = True
    except Exception as _fund_e:
        FUNDAMENTALS_PANEL_AVAILABLE = False
        FUNDAMENTALS_PANEL_ERROR = str(_fund_e)
    try:
        from components import ai_chat_panel

        AI_CHAT_PANEL_AVAILABLE = True
    except Exception as _chat_e:
        AI_CHAT_PANEL_AVAILABLE = False
        AI_CHAT_PANEL_ERROR = str(_chat_e)
    try:
        from components import expert_panel_view

        EXPERT_PANEL_AVAILABLE = True
    except Exception as _expert_e:
        EXPERT_PANEL_AVAILABLE = False
        EXPERT_PANEL_ERROR = str(_expert_e)
else:
    FUNDAMENTALS_PANEL_AVAILABLE = True
    AI_CHAT_PANEL_AVAILABLE = True
    EXPERT_PANEL_AVAILABLE = True

try:
    from components import ai_settings_center

    AI_SETTINGS_AVAILABLE = True
except Exception as e:
    AI_SETTINGS_AVAILABLE = False
    AI_SETTINGS_ERROR = str(e)

# v0.16: AI 智能助手页面
try:
    from components import ai_assistant_page

    AI_ASSISTANT_AVAILABLE = True
except Exception as e:
    AI_ASSISTANT_AVAILABLE = False
    AI_ASSISTANT_ERROR = str(e)

# v1.1: Agent 工作室、团队构建器、模型提供商管理
try:
    from components import agent_studio

    AGENT_STUDIO_AVAILABLE = True
except Exception:
    AGENT_STUDIO_AVAILABLE = False

try:
    from components import team_builder

    TEAM_BUILDER_AVAILABLE = True
except Exception:
    TEAM_BUILDER_AVAILABLE = False

try:
    from components import model_provider_manager

    MODEL_PROVIDER_AVAILABLE = True
except Exception:
    MODEL_PROVIDER_AVAILABLE = False

# ============== Agent 自定义配置 UI ==============
AGENT_CARD_STYLES = ["default", "value", "growth", "technical", "risk", "macro"]


def _ensure_agent_config_state(symbol: str) -> list:
    key = f"agent_config_{symbol}"
    if key not in st.session_state:
        st.session_state[key] = get_default_agent_configs()
    return st.session_state[key]


def _new_agent_template(idx: int) -> dict:
    return {
        "key": f"custom_agent_{idx}",
        "name": f"🤖 自定义 Agent {idx}",
        "avatar": "🤖",
        "role": "你是一位专业投资分析 Agent，强调证据、风险和可执行建议。",
        "instruction": "请基于市场简报输出 JSON：signal=买入/卖出/观望，confidence=0-100，reason=100字内理由。",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "enabled": True,
        "card_style": "default",
    }


def _render_agent_config_editor(symbol: str) -> list:
    configs = _ensure_agent_config_state(symbol)
    with st.expander("Agent 人设与数量管理", expanded=False):
        st.caption("当前为会话内临时配置：可新增、复制、删除 Agent，并自定义人设、模型和卡片样式。")
        e1, e2, e3 = st.columns([1, 1, 1])
        with e1:
            st.metric("启用 Agent 数", sum(1 for a in configs if a.get("enabled", True)))
        with e2:
            if st.button("新增 Agent", use_container_width=True, key=f"agent_add_{symbol}"):
                configs.append(_new_agent_template(len(configs) + 1))
                st.session_state[f"agent_config_{symbol}"] = configs
                st.rerun()
        with e3:
            if st.button("恢复默认 Agent", use_container_width=True, key=f"agent_reset_{symbol}"):
                st.session_state[f"agent_config_{symbol}"] = get_default_agent_configs()
                st.rerun()

        for i, cfg in enumerate(list(configs)):
            with st.expander(cfg.get("name", cfg.get("key", "Agent")), expanded=False):
                c0, c1, c2, c3 = st.columns([0.8, 1.2, 1.2, 1])
                with c0:
                    cfg["enabled"] = st.checkbox(
                        "启用",
                        value=cfg.get("enabled", True),
                        key=f"agent_enabled_{symbol}_{i}",
                    )
                    cfg["avatar"] = st.text_input(
                        "头像",
                        value=cfg.get("avatar", "🤖"),
                        key=f"agent_avatar_{symbol}_{i}",
                    )
                with c1:
                    cfg["key"] = st.text_input(
                        "Key",
                        value=cfg.get("key", f"agent_{i + 1}"),
                        key=f"agent_key_{symbol}_{i}",
                    )
                    cfg["name"] = st.text_input(
                        "名称",
                        value=cfg.get("name", "自定义 Agent"),
                        key=f"agent_name_{symbol}_{i}",
                    )
                with c2:
                    cfg["provider"] = st.text_input(
                        "Provider",
                        value=cfg.get("provider", "deepseek"),
                        key=f"agent_provider_{symbol}_{i}",
                    )
                    cfg["model"] = st.text_input(
                        "Model",
                        value=cfg.get("model", "deepseek-chat"),
                        key=f"agent_model_{symbol}_{i}",
                    )
                with c3:
                    cfg["card_style"] = st.selectbox(
                        "卡片样式",
                        AGENT_CARD_STYLES,
                        index=AGENT_CARD_STYLES.index(cfg.get("card_style", "default"))
                        if cfg.get("card_style", "default") in AGENT_CARD_STYLES
                        else 0,
                        key=f"agent_style_{symbol}_{i}",
                    )
                cfg["role"] = st.text_area(
                    "系统人设",
                    value=cfg.get("role", ""),
                    height=90,
                    key=f"agent_role_{symbol}_{i}",
                )
                cfg["instruction"] = st.text_area(
                    "分析指令",
                    value=cfg.get("instruction", ""),
                    height=120,
                    key=f"agent_instruction_{symbol}_{i}",
                )
                b1, b2 = st.columns([1, 1])
                with b1:
                    if st.button(
                        "复制该 Agent",
                        use_container_width=True,
                        key=f"agent_copy_{symbol}_{i}",
                    ):
                        clone = dict(cfg)
                        clone["key"] = f"{cfg.get('key', 'agent')}_copy"
                        clone["name"] = f"{cfg.get('name', 'Agent')} 副本"
                        configs.insert(i + 1, clone)
                        st.session_state[f"agent_config_{symbol}"] = configs
                        st.rerun()
                with b2:
                    if st.button(
                        "删除该 Agent",
                        use_container_width=True,
                        key=f"agent_delete_{symbol}_{i}",
                    ):
                        configs.pop(i)
                        st.session_state[f"agent_config_{symbol}"] = configs
                        st.rerun()
        st.session_state[f"agent_config_{symbol}"] = configs
    return configs


# ============== 页面配置 ==============
st.set_page_config(
    page_title="金融 Agent 工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============== 自定义 CSS ==============
st.markdown(
    """
<style>
    /* 全局字体 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    /* 隐藏 Streamlit 默认元素（保留 header，避免侧边栏收起后无法通过原生按钮展开） */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* 主容器 */
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 100%;
    }

    /* 标题渐变 */
    .gradient-title {
        background: linear-gradient(90deg, #ef5350 0%, #ff9800 50%, #ffd54f 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2.4rem;
        font-weight: 700;
        margin-bottom: 0;
        letter-spacing: -0.5px;
    }
    .subtitle {
        color: #888;
        font-size: 0.95rem;
        margin-top: 0;
    }

    /* 指标卡片 */
    .metric-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fb 100%);
        border: 1px solid #e8eaed;
        border-radius: 14px;
        padding: 18px 22px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: all 0.3s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.08);
    }
    .metric-label {
        color: #6b7280;
        font-size: 0.78rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 1.85rem;
        font-weight: 700;
        color: #1f2937;
        line-height: 1.1;
    }
    .metric-delta-up {
        color: #ef5350;
        font-size: 0.88rem;
        font-weight: 600;
        margin-top: 4px;
    }
    .metric-delta-down {
        color: #26a69a;
        font-size: 0.88rem;
        font-weight: 600;
        margin-top: 4px;
    }

    /* Agent 卡片 */
    .agent-card {
        background: white;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        border-left: 4px solid #667eea;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .agent-card.buy { border-left-color: #ef5350; }
    .agent-card.sell { border-left-color: #26a69a; }
    .agent-card.hold { border-left-color: #ff9800; }

    .agent-name {
        font-weight: 600;
        font-size: 1rem;
        color: #1f2937;
    }
    .agent-signal {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-left: 8px;
    }
    .signal-buy { background: #fee2e2; color: #ef5350; }
    .signal-sell { background: #d1fae5; color: #26a69a; }
    .signal-hold { background: #fed7aa; color: #ea580c; }

    /* 模型徽章（vendor/model） */
    .model-badge {
        display: inline-block;
        padding: 2px 8px;
        margin-left: 6px;
        border-radius: 6px;
        font-size: 0.7rem;
        font-weight: 500;
        background: #eef2ff;
        color: #4f46e5;
        border: 1px solid #c7d2fe;
        font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
    }
    .model-badge.claude { background:#fef3c7; color:#b45309; border-color:#fde68a; }
    .model-badge.gpt { background:#dcfce7; color:#15803d; border-color:#bbf7d0; }
    .model-badge.deepseek { background:#dbeafe; color:#1d4ed8; border-color:#bfdbfe; }
    .model-badge.mimo { background:#fae8ff; color:#a21caf; border-color:#f5d0fe; }
    .model-badge.sensenova { background:#ffe4e6; color:#be123c; border-color:#fecdd3; }

    /* 模型阵容总览条 */
    .model-lineup {
        background: linear-gradient(135deg, #f8fafc, #ffffff);
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .model-lineup-title {
        font-size: 0.78rem;
        color: #64748b;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        margin-bottom: 10px;
    }
    .model-lineup-row {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
    }
    .model-lineup-item {
        flex: 1 1 auto;
        min-width: 200px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 0.82rem;
    }
    .model-lineup-agent {
        color: #1f2937;
        font-weight: 500;
    }
    .model-lineup-model {
        color: #64748b;
        font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
        font-size: 0.75rem;
        margin-top: 2px;
    }

    .agent-reason {
        color: #6b7280;
        font-size: 0.88rem;
        margin-top: 6px;
        line-height: 1.5;
    }

    /* 分隔线 */
    hr.fancy {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, #e5e7eb, transparent);
        margin: 1.5rem 0;
    }

    /* 侧边栏 */
    [data-testid="stSidebar"] {
        background: #fafbfc;
    }
    [data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem;
    }

    /* 标签页 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        font-weight: 500;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ============== 数据获取（带缓存）==============
def _to_tx_symbol(symbol: str) -> str:
    """6位代码 → 腾讯接口格式（sh600519/sz000858/bj430047）"""
    s = symbol.strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    if s.startswith(("0", "3")):
        return f"sz{s}"
    if s.startswith(("4", "8")):
        return f"bj{s}"
    return s


def _fetch_hist_tx(symbol: str, start: str, end: str):
    """腾讯接口兜底：返回与东财对齐的 12 列 DataFrame，缺失字段用合理默认值填充。"""
    tx_symbol = _to_tx_symbol(symbol)
    df = ak.stock_zh_a_hist_tx(symbol=tx_symbol, start_date=start, end_date=end, adjust="qfq")
    if df is None or df.empty:
        return None
    # Tencent 列：date / open / close / high / low / amount
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["code"] = symbol
    # 派生字段
    prev_close = df["close"].shift(1).fillna(df["open"])
    df["change"] = (df["close"] - prev_close).round(2)
    df["pct_chg"] = ((df["close"] - prev_close) / prev_close * 100).round(2)
    df["amplitude"] = ((df["high"] - df["low"]) / prev_close * 100).round(2)
    # amount 是元（×1000？腾讯返回的 amount 单位为"手×成交额"近似，这里降级处理）
    # 用收盘价估算成交量（避免成交量字段空导致图表炸）
    df["volume"] = (df["amount"] / df["close"].clip(lower=0.01)).round(0).astype(int)
    df["turnover"] = 0.0  # 换手率腾讯不提供，置 0
    return df[
        [
            "date",
            "code",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "pct_chg",
            "change",
            "turnover",
        ]
    ]


@st.cache_data(ttl=300)
def get_stock_list():
    """获取 A 股股票列表"""
    try:
        df = ak.stock_zh_a_spot_em()
        return df[["代码", "名称", "最新价", "涨跌幅"]].head(200)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def get_stock_hist(symbol: str, days: int = 180):
    """获取个股历史 K 线（东财主路径，腾讯兜底）"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")

    # ---- 主路径：东方财富 ----
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is not None and not df.empty:
            expected_cols = [
                "date",
                "code",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "amount",
                "amplitude",
                "pct_chg",
                "change",
                "turnover",
            ]
            if len(df.columns) == len(expected_cols):
                df.columns = expected_cols
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df
    except Exception:
        pass

    # ---- 兜底：腾讯财经 ----
    try:
        df_tx = _fetch_hist_tx(symbol, start, end)
        if df_tx is not None and not df_tx.empty:
            return df_tx.tail(days).reset_index(drop=True)
    except Exception:
        pass

    return None


@st.cache_data(ttl=600)
def get_stock_info(symbol: str):
    """获取个股基本信息（东财主路径 + 腾讯名称兜底）"""
    info = {}
    try:
        df = ak.stock_individual_info_em(symbol=symbol)
        info = dict(zip(df["item"], df["value"]))
    except Exception:
        pass
    # 名称兜底：东财挂时从腾讯行情接口拿股票简称
    if not info.get("股票简称"):
        try:
            import requests

            tx_sym = _to_tx_symbol(symbol)
            r = requests.get(f"http://qt.gtimg.cn/q={tx_sym}", timeout=3)
            r.encoding = "gbk"
            text = r.text or ""
            # 格式: v_sh600519="1~贵州茅台~600519~...";
            if "=" in text and '"' in text:
                payload = text.split('"', 2)[1] if text.count('"') >= 2 else ""
                parts = payload.split("~")
                if len(parts) > 1 and parts[1]:
                    info["股票简称"] = parts[1]
        except Exception:
            pass
    return info


@st.cache_data(ttl=300)
def get_market_overview():
    """主要指数概览"""
    try:
        df = ak.stock_zh_index_spot_em(symbol="上证系列指数")
        return df[["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额"]].head(10)
    except Exception:
        return pd.DataFrame()


# ============== 资讯/研报缓存 ==============
@st.cache_data(ttl=180)
def cached_telegraph_em(limit: int = 200):
    if not NEWS_AVAILABLE:
        return []
    return fetch_telegraph_em(limit=limit)


@st.cache_data(ttl=180)
def cached_telegraph_cls(limit: int = 30):
    if not NEWS_AVAILABLE:
        return []
    return fetch_telegraph_cls(limit=limit)


@st.cache_data(ttl=180)
def cached_telegraph_sina(limit: int = 20):
    if not NEWS_AVAILABLE:
        return []
    return fetch_telegraph_sina(limit=limit)


@st.cache_data(ttl=600)
def cached_research_report(symbol: str, limit: int = 20):
    if not NEWS_AVAILABLE:
        return []
    return fetch_research_report(symbol, limit=limit)


# v0.10: 个股公告 + 主营业务 + 行业名缓存
@st.cache_data(ttl=600)
def cached_announcements_cninfo(symbol: str, days: int = 30):
    if not NEWS_AVAILABLE:
        return []
    return fetch_announcements_cninfo(symbol, days=days)


@st.cache_data(ttl=900)
def cached_announcements_em_today():
    if not NEWS_AVAILABLE:
        return []
    return fetch_announcements_em_today()


@st.cache_data(ttl=3600)
def cached_main_business(symbol: str):
    if not NEWS_AVAILABLE:
        return {}
    return fetch_main_business(symbol)


@st.cache_data(ttl=3600)
def cached_industry_name(symbol: str):
    if not NEWS_AVAILABLE:
        return ""
    return fetch_industry_name(symbol)


@st.cache_data(ttl=600)
def cached_stock_news_em(symbol: str, limit: int = 20):
    if not NEWS_AVAILABLE:
        return []
    return fetch_stock_news_em(symbol, limit=limit)


@st.cache_data(ttl=600)
def cached_topic_news_em(keywords_tuple, limit_each: int = 8, total_limit: int = 30):
    if not NEWS_AVAILABLE:
        return []
    return fetch_topic_news_em(list(keywords_tuple or ()), limit_each=limit_each, total_limit=total_limit)


@st.cache_data(ttl=3600)
def cached_stock_concepts(symbol: str, stock_name: str):
    if not NEWS_AVAILABLE:
        return []
    return fetch_stock_concepts(symbol, stock_name=stock_name, max_concepts=12)


# ============== 资金流向缓存 ==============
@st.cache_data(ttl=300)
def cached_individual_fund_flow(symbol: str, days: int = 30):
    if not FUND_AVAILABLE:
        return None
    return fetch_individual_fund_flow(symbol, days=days)


@st.cache_data(ttl=300)
def cached_market_fund_flow(days: int = 30):
    if not FUND_AVAILABLE:
        return None
    return fetch_market_fund_flow(days=days)


# ============== 技术指标计算 ==============
def calc_ma(df, periods=[5, 10, 20, 60]):
    for p in periods:
        df[f"MA{p}"] = df["close"].rolling(p).mean()
    return df


def calc_macd(df, fast=12, slow=26, signal=9):
    df["EMA_fast"] = df["close"].ewm(span=fast).mean()
    df["EMA_slow"] = df["close"].ewm(span=slow).mean()
    df["DIF"] = df["EMA_fast"] - df["EMA_slow"]
    df["DEA"] = df["DIF"].ewm(span=signal).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    return df


def calc_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


# ============== 标题 ==============
col_t1, col_t2 = st.columns([3, 1])
with col_t1:
    st.markdown('<div class="gradient-title">📊 金融 Agent 工作台</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Multi-Agent · Real-time Data · A-Share Market</div>',
        unsafe_allow_html=True,
    )
with col_t2:
    st.html(f"""
    <div style='text-align:right; padding-top:15px;'>
        <div style='color:#888; font-size:0.8rem;'>当前时间</div>
        <div style='color:#1f2937; font-size:1.1rem; font-weight:600;'>{datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
    </div>
    """)

st.markdown('<hr class="fancy">', unsafe_allow_html=True)

# ============== 侧边栏 ==============
with st.sidebar:
    st.markdown("### ⚙️ 标的配置")

    # 热门股票预设（按板块分组）
    popular_groups = {
        "🥇 大消费": {
            "贵州茅台 (600519)": "600519",
            "五粮液 (000858)": "000858",
            "美的集团 (000333)": "000333",
            "格力电器 (000651)": "000651",
            "伊利股份 (600887)": "600887",
        },
        "🔋 新能源 / 制造": {
            "宁德时代 (300750)": "300750",
            "比亚迪 (002594)": "002594",
            "立讯精密 (002475)": "002475",
            "海康威视 (002415)": "002415",
            "三一重工 (600031)": "600031",
        },
        "🏦 金融": {
            "招商银行 (600036)": "600036",
            "工商银行 (601398)": "601398",
            "中国平安 (601318)": "601318",
            "东方财富 (300059)": "300059",
        },
        "💊 医药 / 科技": {
            "恒瑞医药 (600276)": "600276",
            "药明康德 (603259)": "603259",
            "中芯国际 (688981)": "688981",
            "韦尔股份 (603501)": "603501",
        },
    }

    group_label = st.selectbox("板块", list(popular_groups.keys()), index=0)
    popular_stocks = popular_groups[group_label]
    selected_label = st.selectbox("选择股票", list(popular_stocks.keys()), index=0)
    symbol = popular_stocks[selected_label]

    custom = st.text_input("或输入其他 6 位代码", value="", placeholder="如 600519")
    use_custom = bool(custom and len(custom) == 6 and custom.isdigit())
    if use_custom:
        symbol = custom

    days = st.slider("时间跨度（交易日）", 30, 365, 120)

    st.markdown("---")
    st.markdown("### 📈 技术指标")
    show_ma = st.checkbox("显示均线 MA", value=True)
    show_macd = st.checkbox("显示 MACD", value=True)
    show_rsi = st.checkbox("显示 RSI", value=False)

    st.markdown("---")
    st.markdown("### 🤖 Agent 分析")
    enable_agents = st.checkbox("启用 Agent 模拟分析", value=True)
    use_llm = st.checkbox(
        "使用 LLM 深度分析（5 模型异构）",
        value=False,
        disabled=not LLM_AVAILABLE,
        help="勾选后调用 5 厂商异构 LLM（Claude / GPT / DeepSeek / Mimo / SenseNova）真实推理"
        if LLM_AVAILABLE
        else f"LLM 模块不可用: {LLM_ERROR}",
    )

    # v0.12: Analysis mode selector
    if LLM_AVAILABLE:
        try:
            from backend.agent_modes import get_mode_resolver, AnalysisMode

            _resolver = get_mode_resolver()
            _mode_choices = _resolver.list_modes()
            _mode_labels = [f"{m['name']}" for m in _mode_choices]
            _mode_values = [m["value"] for m in _mode_choices]
            _mode_descs = [m["description"] for m in _mode_choices]

            selected_mode_idx = st.radio(
                "分析模式",
                options=range(len(_mode_labels)),
                format_func=lambda i: _mode_labels[i],
                index=2,  # Default to AUTO
                help="标准: 3 Agent 快速分析 | 深入: 5 Agent 全面分析 | 自动: 先预筛再决定",
                key="analysis_mode_radio",
            )
            analysis_mode = AnalysisMode(_mode_values[selected_mode_idx])
            st.caption(f"💡 {_mode_descs[selected_mode_idx]}")
        except Exception:
            analysis_mode = AnalysisMode.DEEP
    else:
        analysis_mode = AnalysisMode.DEEP

    st.markdown("---")
    st.markdown("### 🤖 AI 咨询")
    if st.button(
        "🤖 打开 AI 咨询" if not st.session_state.get("show_ai_chat", False) else "✕ 关闭 AI 咨询",
        use_container_width=True,
        key="sidebar_ai_chat_toggle",
        help="启用后,看板顶部出现可折叠的对话面板,任意 Tab 浏览中都能与 AI 多轮对话",
    ):
        st.session_state["show_ai_chat"] = not st.session_state.get("show_ai_chat", False)
        st.rerun()
    st.caption("也可以在主界面指标卡下方打开 AI 咨询。")

    st.markdown("---")
    st.caption("数据源: akshare（无需 API Key）")
    st.caption(f"标的代码: **{symbol}**")

# ============== 主内容 ==============
with st.spinner(f"正在加载 {symbol} 的数据..."):
    df = get_stock_hist(symbol, days)
    info = get_stock_info(symbol)

if df is None or df.empty:
    st.error(f"❌ 无法获取股票 {symbol} 的数据，请检查代码或稍后重试")
    st.stop()

# 技术指标
if show_ma:
    df = calc_ma(df)
if show_macd:
    df = calc_macd(df)
if show_rsi:
    df = calc_rsi(df)

# 关键指标
last = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else last
period_high = df["high"].max()
period_low = df["low"].min()
period_change = (last["close"] / df.iloc[0]["close"] - 1) * 100
total_amount = df["amount"].sum() / 1e8  # 亿元

stock_name = info.get("股票简称") or (custom if use_custom else selected_label.split(" ")[0])

# ============== 指标卡片 ==============
st.markdown(f"### {stock_name} · {symbol}")

c1, c2, c3, c4, c5 = st.columns(5)

day_chg = (last["close"] / prev["close"] - 1) * 100
chg_class = "metric-delta-up" if day_chg >= 0 else "metric-delta-down"
chg_arrow = "▲" if day_chg >= 0 else "▼"

c1.markdown(
    f"""
<div class="metric-card">
    <div class="metric-label">最新价</div>
    <div class="metric-value">¥{last["close"]:.2f}</div>
    <div class="{chg_class}">{chg_arrow} {abs(day_chg):.2f}%</div>
</div>
""",
    unsafe_allow_html=True,
)

period_class = "metric-delta-up" if period_change >= 0 else "metric-delta-down"
period_arrow = "▲" if period_change >= 0 else "▼"
c2.markdown(
    f"""
<div class="metric-card">
    <div class="metric-label">区间涨跌</div>
    <div class="metric-value">{period_change:+.2f}%</div>
    <div class="{period_class}">{period_arrow} {days} 日累计</div>
</div>
""",
    unsafe_allow_html=True,
)

c3.markdown(
    f"""
<div class="metric-card">
    <div class="metric-label">区间最高</div>
    <div class="metric-value">¥{period_high:.2f}</div>
    <div class="metric-delta-up">{((period_high / last["close"] - 1) * 100):+.1f}% 距今</div>
</div>
""",
    unsafe_allow_html=True,
)

c4.markdown(
    f"""
<div class="metric-card">
    <div class="metric-label">区间最低</div>
    <div class="metric-value">¥{period_low:.2f}</div>
    <div class="metric-delta-down">{((period_low / last["close"] - 1) * 100):+.1f}% 距今</div>
</div>
""",
    unsafe_allow_html=True,
)

c5.markdown(
    f"""
<div class="metric-card">
    <div class="metric-label">区间成交额</div>
    <div class="metric-value">{total_amount:.1f}<span style='font-size:1rem;color:#888;'> 亿</span></div>
    <div style='color:#6b7280; font-size:0.85rem; margin-top:4px;'>换手 {last.get("turnover", 0):.2f}%</div>
</div>
""",
    unsafe_allow_html=True,
)


# 主区快捷入口：侧边栏收起后仍可打开 AI 咨询，并提示原生侧栏展开按钮可用
quick_col1, quick_col2, quick_col3 = st.columns([1.3, 1.3, 5])
with quick_col1:
    if st.button(
        "🤖 打开 AI 咨询" if not st.session_state.get("show_ai_chat", False) else "✕ 关闭 AI 咨询",
        type="primary" if not st.session_state.get("show_ai_chat", False) else "secondary",
        use_container_width=True,
        key="main_ai_chat_toggle",
        help="在当前股票上下文中进行多轮 AI 咨询",
    ):
        st.session_state["show_ai_chat"] = not st.session_state.get("show_ai_chat", False)
        st.rerun()
with quick_col2:
    if not st.session_state.get("dismiss_sidebar_hint", False):
        hint_col, close_col = st.columns([5, 1])
        with hint_col:
            st.caption("📌 侧栏收起后，可点页面右上角 Streamlit 箭头重新展开。")
        with close_col:
            if st.button(
                "×",
                key="dismiss_sidebar_hint_btn",
                help="隐藏这条提示",
                use_container_width=True,
            ):
                st.session_state["dismiss_sidebar_hint"] = True
                st.rerun()

st.markdown('<hr class="fancy">', unsafe_allow_html=True)


def safe_list_reports(type_filter=None, **kwargs) -> list:
    """兼容旧版 archive.list_reports: 若不支持 type_filter, 回退后在前端本地过滤。"""
    try:
        return list_reports(type_filter=type_filter, **kwargs)
    except TypeError as exc:
        if "type_filter" not in str(exc):
            raise
        reports = list_reports(**kwargs)
        if not type_filter:
            return reports
        return [r for r in reports if r.get("type", "agent") == type_filter]


# ============== v0.7: AI 咨询上下文构造 ==============
def build_chat_context() -> dict:
    """拼接最新价 / MA / 资金方向 / 最近归档报告摘要,供 ai_chat 注入"""
    ma5_v = df["MA5"].iloc[-1] if "MA5" in df.columns else last["close"]
    ma20_v = df["MA20"].iloc[-1] if "MA20" in df.columns else last["close"]
    ma60_v = df["MA60"].iloc[-1] if "MA60" in df.columns else last["close"]

    fund_dir = "暂无主力资金数据"
    if FUND_AVAILABLE:
        try:
            df_fund_ctx = cached_individual_fund_flow(symbol, days=30)
            if df_fund_ctx is not None and len(df_fund_ctx) > 0:
                s_ctx = summarize_fund_flow(df_fund_ctx, recent_days=5)
                fund_dir = build_fund_flow_brief_for_llm(s_ctx, kind=stock_name)
        except Exception:
            pass

    archive_excerpt = ""
    if ARCHIVE_AVAILABLE:
        try:
            recent_arc = safe_list_reports(
                stock_filter=symbol,
                type_filter="agent",
                limit=1,
            )
            if recent_arc:
                archive_excerpt = recent_arc[0].get("chairman_excerpt", "") or ""
        except Exception:
            pass

    return {
        "close": float(last["close"]),
        "day_change": float(day_chg),
        "period_change": float(period_change),
        "ma5": f"{ma5_v:.2f}",
        "ma20": f"{ma20_v:.2f}",
        "ma60": f"{ma60_v:.2f}",
        "fund_dir": fund_dir,
        "latest_archive_excerpt": archive_excerpt,
        "data_date": datetime.now().strftime("%Y-%m-%d"),
    }


# ============== v0.7: AI 咨询面板(在 Tab 之上,任意 Tab 浏览时都可见) ==============
if st.session_state.get("show_ai_chat", False):
    if AI_CHAT_PANEL_AVAILABLE:
        st.info(
            "AI 投资咨询工作区已开启：会结合当前页面行情上下文回答，快捷问题会先填入输入框供你确认。",
            icon="🤖",
        )
        with st.expander("🤖 AI 投资咨询工作区", expanded=True):
            try:
                chat_ctx = build_chat_context()
                ai_chat_panel.render(symbol, stock_name, chat_ctx)
            except Exception as _e:
                st.error(f"AI 咨询面板渲染失败: {_e}")
        st.markdown('<hr class="fancy">', unsafe_allow_html=True)
    else:
        st.error(f"AI 咨询组件未加载: {AI_CHAT_PANEL_ERROR if 'AI_CHAT_PANEL_ERROR' in dir() else '未知错误'}")
        if st.button("✕ 关闭 AI 咨询", key="close_broken_ai_chat", type="secondary"):
            st.session_state["show_ai_chat"] = False
            st.rerun()

# ============== 图表 ==============
(
    tab1,
    tab2,
    tab3,
    tab4,
    tab5,
    tab6,
    tab7,
    tab8,
    tab9,
    tab10,
    tab11,
    tab12,
    tab13,
    tab14,
) = st.tabs(
    [
        "📈 K 线 & 技术指标",
        "🤖 Agent 协作分析",
        "⚙️ AI 设置中心",
        "📰 资讯 & 研报",
        "💰 资金流向",
        "📋 数据明细",
        "💡 基本面",
        "📚 研究存档",
        "🎓 专家团圆桌",
        "📊 数据源健康",
        "🧠 AI 智能助手",
        "🎛️ Agent 工作室",
        "👥 团队构建器",
        "🔌 模型提供商",
    ]
)

with tab1:
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

with tab2:
    if not enable_agents:
        st.info("请在侧边栏启用 Agent 分析")
    else:
        # 计算共用指标
        ma5 = df["MA5"].iloc[-1] if "MA5" in df.columns else last["close"]
        ma20 = df["MA20"].iloc[-1] if "MA20" in df.columns else last["close"]
        ma60 = df["MA60"].iloc[-1] if "MA60" in df.columns else last["close"]
        macd_val = df["MACD"].iloc[-1] if "MACD" in df.columns else 0
        dif_val = df["DIF"].iloc[-1] if "DIF" in df.columns else 0
        dea_val = df["DEA"].iloc[-1] if "DEA" in df.columns else 0
        rsi_val = df["RSI"].iloc[-1] if "RSI" in df.columns else 50
        recent_chg = (last["close"] / df["close"].iloc[-min(20, len(df))] - 1) * 100
        recent_vol = df["volume"].tail(5).mean()
        prev_vol = df["volume"].head(20).mean()
        vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1
        volatility = df["close"].pct_change().std() * 100

        # ========== 量化因子分析 (v0.12) ==========
        try:
            from frontend.components.factor_panel import render_factor_panel

            st.markdown("#### 📊 量化因子分析")
            render_factor_panel(symbol, stock_name)
            st.divider()
        except Exception as _factor_e:
            pass  # 因子面板加载失败不影响主流程

        # ========== LLM 深度分析模式 ==========
        if use_llm and LLM_AVAILABLE:
            st.markdown("#### 🧠 LLM 深度分析（可自定义 Agent 团队）")
            agent_configs = (
                ai_settings_center.ensure_agent_config_state(symbol)
                if AI_SETTINGS_AVAILABLE
                else _ensure_agent_config_state(symbol)
            )
            active_agent_count = sum(1 for a in agent_configs if a.get("enabled", True))
            global_ai_settings = ai_settings_center.get_global_ai_settings() if AI_SETTINGS_AVAILABLE else {}
            st.caption(
                f"{active_agent_count} 位 Agent 使用 AI 设置中心的人设与模型并行推理，避免单一模型偏见，约 20-60 秒。要修改 Agent/Key/模型，请打开「AI 设置中心」Tab。"
            )

            # 模型阵容展示条
            try:
                lineup_rows = get_custom_agent_model_table(agent_configs)
                lineup_items = []
                for key, name, vendor_label, model in lineup_rows:
                    vendor_cls = vendor_label.lower().replace(" ", "")
                    lineup_items.append(f"""
                        <div class="model-lineup-item">
                            <div class="model-lineup-agent">{name}</div>
                            <div class="model-lineup-model">
                                <span class="model-badge {vendor_cls}">{vendor_label}</span> {model}
                            </div>
                        </div>
                    """)
                st.html(f"""
                <div class="model-lineup">
                    <div class="model-lineup-title">本次决策模型阵容（{active_agent_count} Agent 自定义团队）</div>
                    <div class="model-lineup-row">{"".join(lineup_items)}</div>
                </div>
                """)
            except Exception:
                pass

            col_run, col_info = st.columns([1, 4])
            with col_run:
                run_btn = st.button("🚀 启动深度分析", type="primary", use_container_width=True)

            cache_key = f"llm_result_{symbol}_{days}"

            if run_btn:
                with st.spinner(f"🤖 {active_agent_count} 位 Agent 正在并行分析中..."):
                    fundamentals_text = ""
                    if info:
                        keys_of_interest = [
                            "行业",
                            "总市值",
                            "流通市值",
                            "市盈率",
                            "市净率",
                            "总股本",
                            "流通股",
                            "上市时间",
                        ]
                        items = [f"{k}: {info.get(k, 'N/A')}" for k in keys_of_interest if k in info]
                        fundamentals_text = "; ".join(items) if items else "暂无"

                    # 拉取真实新闻 & 研报
                    related_brief = ""
                    market_brief_text = ""
                    research_brief = ""
                    announcements_brief = ""
                    industry_news_brief = ""
                    concepts_brief = ""
                    if NEWS_AVAILABLE:
                        try:
                            em_news = cached_telegraph_em(limit=200)
                            cls_news = cached_telegraph_cls(limit=30)
                            sina_news = cached_telegraph_sina(limit=20)
                            all_news = em_news + cls_news + sina_news
                            main_biz = cached_main_business(symbol) or {}
                            industry = cached_industry_name(symbol)
                            concepts = cached_stock_concepts(symbol, stock_name) or []
                            # v0.10.2: 优先取东财个股专属新闻,确保即使大盘快讯没匹配也至少有内容
                            stock_specific = cached_stock_news_em(symbol, limit=10) or []
                            keyword_matched = get_stock_related_news(
                                stock_name,
                                all_news,
                                limit=8,
                                symbol=symbol,
                                products=main_biz.get("products"),
                            )
                            seen_t2 = set()
                            related = []
                            for src_list in (stock_specific, keyword_matched):
                                for n in src_list:
                                    key = (
                                        n.get("title", "").strip(),
                                        n.get("datetime", "")[:10],
                                    )
                                    if not key[0] or key in seen_t2:
                                        continue
                                    seen_t2.add(key)
                                    related.append(n)
                            related_brief = build_news_brief_for_llm(related[:10], max_items=10)
                            market_brief_text = build_news_brief_for_llm(em_news[:6], max_items=6)
                            reports = cached_research_report(symbol, limit=15)
                            research_brief = build_research_brief_for_llm(reports, max_items=8)
                            # v0.10: 个股公告 + 行业新闻进入 Agent 简报
                            cninfo_ann = cached_announcements_cninfo(symbol, days=30)
                            em_today = cached_announcements_em_today() or []
                            em_for_stock = [a for a in em_today if a.get("code") == symbol]
                            ann_list = merge_announcements(cninfo_ann, em_for_stock)
                            announcements_brief = build_announcements_brief_for_llm(ann_list, max_items=8)
                            if industry:
                                excluded_titles = {n.get("title", "").strip() for n in (related or [])}
                                extra_ind_kws = extract_business_terms((main_biz or {}).get("scope") or "", max_terms=8)
                                extra_ind_kws += get_concept_keywords(concepts, limit=10)
                                pool_ind_news = get_industry_news(
                                    industry,
                                    all_news,
                                    limit=6,
                                    exclude_titles=excluded_titles,
                                    extra_keywords=extra_ind_kws,
                                )
                                topic_kws = build_topic_news_keywords(
                                    industry=industry,
                                    business_terms=extra_ind_kws,
                                    concepts=concepts,
                                    limit=8,
                                )
                                topic_ind_news = cached_topic_news_em(tuple(topic_kws), limit_each=6, total_limit=12)
                                topic_ind_news = [
                                    n for n in topic_ind_news if n.get("title", "").strip() not in excluded_titles
                                ]
                                ind_news = merge_news_items(pool_ind_news, topic_ind_news, limit=8)
                                industry_news_brief = build_news_brief_for_llm(ind_news, max_items=8)
                            concept_excluded = {n.get("title", "").strip() for n in (related or [])}
                            pool_concept_news = get_concept_news(
                                concepts,
                                all_news,
                                limit=6,
                                exclude_titles=concept_excluded,
                            )
                            concept_kws = get_concept_keywords(concepts, limit=8)
                            topic_concept_news = cached_topic_news_em(tuple(concept_kws), limit_each=5, total_limit=10)
                            topic_concept_news = [
                                n for n in topic_concept_news if n.get("title", "").strip() not in concept_excluded
                            ]
                            concept_news = merge_news_items(pool_concept_news, topic_concept_news, limit=8)
                            concepts_brief = build_concepts_brief_for_llm(
                                concepts, concept_news, max_concepts=10, max_news=8
                            )
                        except Exception as e:
                            st.warning(f"新闻数据拉取失败（不影响 LLM 推理）: {e}")

                    # 拉取真实资金流向
                    stock_fund_brief = ""
                    market_fund_brief = ""
                    if FUND_AVAILABLE:
                        try:
                            df_stock_fund = cached_individual_fund_flow(symbol, days=30)
                            if df_stock_fund is not None and len(df_stock_fund) > 0:
                                s_stock = summarize_fund_flow(df_stock_fund, recent_days=5)
                                stock_fund_brief = build_fund_flow_brief_for_llm(s_stock, kind=stock_name)

                            df_market_fund = cached_market_fund_flow(days=30)
                            if df_market_fund is not None and len(df_market_fund) > 0:
                                s_market = summarize_fund_flow(df_market_fund, recent_days=5)
                                market_fund_brief = build_fund_flow_brief_for_llm(s_market, kind="大盘")
                        except Exception as e:
                            st.warning(f"资金流向拉取失败（不影响 LLM 推理）: {e}")

                    stock_payload = {
                        "name": stock_name,
                        "symbol": symbol,
                        "close": float(last["close"]),
                        "day_change": float(day_chg),
                        "period_change": float(period_change),
                        "period_high": float(period_high),
                        "period_low": float(period_low),
                        "days": days,
                        "ma5": f"{ma5:.2f}",
                        "ma20": f"{ma20:.2f}",
                        "ma60": f"{ma60:.2f}",
                        "macd": f"{macd_val:.3f}",
                        "dif": f"{dif_val:.3f}",
                        "dea": f"{dea_val:.3f}",
                        "rsi": f"{rsi_val:.2f}",
                        "volume": float(last["volume"]),
                        "total_amount": float(total_amount),
                        "turnover": float(last.get("turnover", 0)),
                        "vol_ratio": float(vol_ratio),
                        "volatility": float(volatility),
                        "fundamentals": fundamentals_text,
                        "related_news_brief": related_brief,
                        "announcements_brief": announcements_brief,
                        "industry_news_brief": industry_news_brief,
                        "concepts_brief": concepts_brief,
                        "market_news_brief": market_brief_text,
                        "research_brief": research_brief,
                        "stock_fund_brief": stock_fund_brief,
                        "market_fund_brief": market_fund_brief,
                    }
                    try:
                        # v0.12: Use mode-based agent execution if available
                        if "analysis_mode" in dir():
                            llm_result = run_agents_with_mode(
                                stock_payload,
                                mode=analysis_mode,
                                agent_configs=agent_configs,
                                global_ai_settings=global_ai_settings,
                            )
                        else:
                            llm_result = run_custom_agents(
                                stock_payload,
                                agent_configs,
                                global_ai_settings=global_ai_settings,
                            )
                        st.session_state[cache_key] = llm_result
                        st.session_state[cache_key + "_payload"] = stock_payload
                    except Exception as e:
                        st.error(f"LLM 分析失败: {e}")
                        llm_result = None

            # 显示缓存的结果
            if cache_key in st.session_state:
                llm_result = st.session_state[cache_key]
                payload = st.session_state.get(cache_key + "_payload", {})

                # v0.12: Show mode indicator
                result_mode = llm_result.get("mode", "")
                mode_name = llm_result.get("mode_name", "")
                auto_escalated = llm_result.get("auto_escalated", False)
                if result_mode:
                    mode_colors = {
                        "standard": "#10b981",
                        "deep": "#8b5cf6",
                        "auto": "#f59e0b",
                    }
                    mode_color = mode_colors.get(result_mode, "#6b7280")
                    escalation_badge = ""
                    if result_mode == "auto" and auto_escalated:
                        escalation_badge = " <span style='font-size:0.75em; color:#f59e0b;'>(已升级到深入分析)</span>"
                    elif result_mode == "auto" and not auto_escalated:
                        escalation_badge = " <span style='font-size:0.75em; color:#10b981;'>(预筛直接输出)</span>"
                    st.markdown(
                        f"<div style='text-align:center; margin-bottom:12px;'>"
                        f"<span style='background:{mode_color}22; color:{mode_color}; "
                        f"padding:4px 12px; border-radius:12px; font-size:0.85em; font-weight:600;'>"
                        f"🔍 {mode_name}</span>{escalation_badge}</div>",
                        unsafe_allow_html=True,
                    )

                cls_map = {"买入": "buy", "卖出": "sell", "观望": "hold"}
                agent_keys_order = llm_result.get("agent_order") or list(llm_result.get("agents", {}).keys())
                # 用 3 列网格更协调
                cols = st.columns(2)
                for idx, key in enumerate(agent_keys_order):
                    if key not in llm_result["agents"]:
                        continue
                    r = llm_result["agents"][key]
                    cls = cls_map.get(r["signal"], "hold")
                    signal_class = f"signal-{cls}"
                    vendor_label = r.get("vendor", "?")
                    model_name = r.get("model", "?")
                    primary_vendor = r.get("primary_vendor", vendor_label)
                    fallback_used = bool(r.get("fallback_used", False))
                    vendor_cls = vendor_label.lower().replace(" ", "")
                    # 三态指示：失败=红 / 兜底=琥珀 / 正常=不显示
                    if not r.get("ok", True):
                        status_dot = "<span title='主+兜底都失败' style='color:#ef4444; margin-left:6px;'>●</span>"
                    elif fallback_used:
                        status_dot = f"<span title='主厂商({primary_vendor})失败已切兜底' style='color:#f59e0b; margin-left:6px;'>●</span>"
                    else:
                        status_dot = ""

                    # v0.9: 审稿质量徽标(仅当 critic 写回了 review 才显示)
                    review = r.get("review") or {}
                    quality_badge_html = ""
                    review_block_html = ""
                    if review and isinstance(review.get("quality_score"), int):
                        q = review["quality_score"]
                        if q >= 80:
                            q_color, q_label = "#16a34a", "高质量"
                        elif q >= 60:
                            q_color, q_label = "#0ea5e9", "可参考"
                        elif q >= 40:
                            q_color, q_label = "#f59e0b", "待商榷"
                        else:
                            q_color, q_label = "#dc2626", "存疑"
                        oc_html = ""
                        if review.get("overconfident"):
                            oc_html = "<span title='审稿人认为本结论过度自信' style='margin-left:6px; color:#dc2626;'>⚠ 过度自信</span>"
                        quality_badge_html = (
                            f"<span title='审稿评分' "
                            f"style='display:inline-block; margin-left:6px; padding:1px 8px; "
                            f"border-radius:8px; font-size:0.7rem; background:{q_color}1a; color:{q_color}; "
                            f"border:1px solid {q_color}55;'>审 {q} · {q_label}</span>{oc_html}"
                        )

                        bullets = []
                        for kind, label, items in (
                            ("supported", "✅ 站得住的证据", review.get("supported")),
                            (
                                "contradictions",
                                "❌ 与简报矛盾",
                                review.get("contradictions"),
                            ),
                            (
                                "missing_evidence",
                                "🔍 漏掉的关键证据",
                                review.get("missing_evidence"),
                            ),
                        ):
                            if items:
                                inner = "".join(f"<li>{i}</li>" for i in items)
                                bullets.append(
                                    f"<div style='margin-top:4px; font-size:0.75rem; color:#374151;'>"
                                    f"<strong>{label}</strong><ul style='margin:2px 0 0 18px; padding:0;'>{inner}</ul>"
                                    f"</div>"
                                )
                        comment = review.get("comment") or ""
                        if comment:
                            bullets.append(
                                f"<div style='margin-top:6px; font-size:0.75rem; color:#6b7280; font-style:italic;'>"
                                f"📝 {comment}</div>"
                            )
                        if bullets:
                            review_block_html = (
                                "<div style='margin-top:10px; padding:8px 10px; background:#f9fafb; "
                                "border-left:3px solid "
                                + q_color
                                + "; border-radius:6px;'>"
                                + "".join(bullets)
                                + "</div>"
                            )
                    with cols[idx % 2]:
                        st.html(f"""
                        <div class="agent-card {cls}">
                            <div>
                                <span class="agent-name">{r["name"]}</span>
                                <span class="agent-signal {signal_class}">{r["signal"]}</span>
                                {status_dot}
                                {quality_badge_html}
                            </div>
                            <div style='margin-top:6px;'>
                                <span class="model-badge {vendor_cls}">{vendor_label}</span>
                                <span style='font-size:0.72rem; color:#9ca3af; font-family:monospace;'>{model_name}</span>
                            </div>
                            <div style='margin-top:10px;'>
                                <div style='display:flex; justify-content:space-between; align-items:center;'>
                                    <span style='font-size:0.85rem; color:#6b7280;'>置信度</span>
                                    <span style='font-weight:600; color:#1f2937;'>{r["confidence"]}%</span>
                                </div>
                                <div style='background:#f3f4f6; height:6px; border-radius:3px; margin-top:4px; overflow:hidden;'>
                                    <div style='background:linear-gradient(90deg,#667eea,#764ba2); width:{r["confidence"]}%; height:100%;'></div>
                                </div>
                            </div>
                            <div class="agent-reason">{r["reason"]}</div>
                            {review_block_html}
                        </div>
                        """)

                # 综合决策
                st.markdown('<hr class="fancy">', unsafe_allow_html=True)
                summary = llm_result["summary"]
                final_color = {
                    "建议买入": "#ef5350",
                    "建议卖出": "#26a69a",
                    "建议观望": "#ff9800",
                }.get(summary["final"], "#667eea")

                st.html(f"""
                <div style='background:linear-gradient(135deg,#fafbfc,#ffffff); border-radius:14px; padding:24px;
                            border:1px solid #e5e7eb; box-shadow:0 4px 12px rgba(0,0,0,0.05);'>
                    <div style='color:#6b7280; font-size:0.85rem; margin-bottom:8px;'>多 Agent 投票结果</div>
                    <div style='display:flex; justify-content:space-between; align-items:center;'>
                        <div style='font-size:1.8rem; font-weight:700; color:{final_color};'>{summary["final"]}</div>
                        <div style='text-align:right;'>
                            <div style='font-size:0.85rem; color:#6b7280;'>买入 {summary["buy"]} · 卖出 {summary["sell"]} · 观望 {summary["hold"]}</div>
                            <div style='font-size:1.1rem; font-weight:600; color:#1f2937;'>平均置信度 {summary["avg_confidence"]:.0f}%</div>
                        </div>
                    </div>
                </div>
                """)

                # v0.9: 审稿员 / 分歧来源
                critic_block = llm_result.get("critic")
                if critic_block:
                    if critic_block.get("ok"):
                        agents_review = critic_block.get("agents") or {}
                        scores = [
                            r.get("review", {}).get("quality_score")
                            for r in llm_result.get("agents", {}).values()
                            if isinstance(r.get("review"), dict) and isinstance(r["review"].get("quality_score"), int)
                        ]
                        avg_q = round(sum(scores) / len(scores), 1) if scores else None
                        oc = sum(
                            1
                            for r in llm_result.get("agents", {}).values()
                            if isinstance(r.get("review"), dict) and r["review"].get("overconfident")
                        )
                        div = critic_block.get("divergence") or {}
                        level = div.get("level") or "无"
                        level_color = {
                            "高": "#dc2626",
                            "中": "#f59e0b",
                            "低": "#16a34a",
                            "无": "#9ca3af",
                        }.get(level, "#6b7280")

                        critic_vendor = critic_block.get("vendor", "?")
                        critic_model = critic_block.get("model", "?")
                        critic_fb = " ⚠️ 已兜底" if critic_block.get("fallback_used") else ""

                        avg_q_text = f"{avg_q:.1f}" if avg_q is not None else "—"
                        st.html(f"""
                        <div style='margin-top:16px; padding:16px 20px; background:#f8fafc;
                                    border-radius:12px; border-left:4px solid {level_color};'>
                            <div style='display:flex; justify-content:space-between; align-items:center;'>
                                <div style='font-weight:600; color:#1f2937;'>🧐 审稿员观察</div>
                                <div style='font-size:0.78rem; color:#6b7280;'>
                                    审稿模型 {critic_vendor} / <code>{critic_model}</code>{critic_fb}
                                </div>
                            </div>
                            <div style='display:flex; gap:24px; margin-top:8px; flex-wrap:wrap;'>
                                <div><span style='color:#6b7280; font-size:0.8rem;'>平均质量分</span>
                                     <span style='margin-left:6px; font-weight:600;'>{avg_q_text}</span></div>
                                <div><span style='color:#6b7280; font-size:0.8rem;'>已审 / 总数</span>
                                     <span style='margin-left:6px; font-weight:600;'>{len(agents_review)} / {len(llm_result.get("agents", {}))}</span></div>
                                <div><span style='color:#6b7280; font-size:0.8rem;'>过度自信</span>
                                     <span style='margin-left:6px; font-weight:600; color:{"#dc2626" if oc else "#1f2937"};'>{oc}</span></div>
                                <div><span style='color:#6b7280; font-size:0.8rem;'>分歧度</span>
                                     <span style='margin-left:6px; font-weight:600; color:{level_color};'>{level}</span></div>
                            </div>
                        """)

                        axis = div.get("main_axis") or ""
                        summary_txt = div.get("summary") or ""
                        if axis or summary_txt:
                            st.html(f"""
                            <div style='margin-top:10px; padding:10px 12px; background:#ffffff;
                                        border-radius:8px; border:1px solid #e5e7eb;'>
                                <div style='font-size:0.8rem; color:#6b7280;'>💭 主要分歧轴</div>
                                <div style='font-weight:600; color:#1f2937; margin-top:2px;'>{axis or "(无)"}</div>
                                <div style='margin-top:6px; color:#374151; font-size:0.88rem;'>{summary_txt}</div>
                            </div>
                            """)
                        st.html("</div>")
                    elif critic_block.get("error"):
                        st.caption(f"🧐 审稿员未能完成本次审稿: {critic_block.get('error')}")

                # 主席总结
                st.markdown("#### 🎩 投资委员会主席总结")
                # 显示主席模型徽章
                try:
                    chair_vendor, chair_model = AGENT_MODEL_CONFIG.get("chairman", ("?", "?"))
                    chair_vendor_label = VENDORS.get(chair_vendor, {}).get("label", chair_vendor)
                    chair_vendor_cls = chair_vendor_label.lower().replace(" ", "")
                    st.html(f"""
                    <div style='margin-bottom:8px;'>
                        <span class="model-badge {chair_vendor_cls}">{chair_vendor_label}</span>
                        <span style='font-size:0.75rem; color:#9ca3af; font-family:monospace;'>{chair_model}</span>
                        <span style='font-size:0.75rem; color:#6b7280; margin-left:8px;'>· 综合 5 Agent 异构观点输出最终决策</span>
                    </div>
                    """)
                except Exception:
                    pass

                chairman_key = cache_key + "_chairman"
                if chairman_key not in st.session_state:
                    if st.button("📝 生成主席总结", key="gen_chairman"):
                        with st.spinner("主席正在思考..."):
                            try:
                                chairman_text = summarize_with_chairman(llm_result, stock_name)
                                st.session_state[chairman_key] = chairman_text
                                st.rerun()
                            except Exception as e:
                                st.error(f"主席总结失败: {e}")
                else:
                    # 主席总结是 LLM 返回的 markdown,不能用 st.html(会原样显示 ** # - 等符号)。
                    # 这里把外壳画成浅黄渐变卡片,正文走 st.markdown 正常渲染。
                    st.html("""
                    <div style='background:linear-gradient(135deg,#fff8e1,#ffffff); border-radius:14px;
                                padding:20px 24px; border-left:4px solid #ff9800;
                                box-shadow:0 4px 12px rgba(255,152,0,0.08); margin-bottom:8px;'
                         id='chairman-card-shell'>
                        <div style='font-size:0.78rem; color:#9a6f00; margin-bottom:6px;'>主席总结(Markdown)</div>
                    </div>
                    """)
                    st.markdown(st.session_state[chairman_key])

                    col_regen, col_export = st.columns([1, 1])
                    with col_regen:
                        if st.button(
                            "🔄 重新生成",
                            key="regen_chairman",
                            use_container_width=True,
                        ):
                            del st.session_state[chairman_key]
                            st.rerun()
                    with col_export:
                        # 生成 Markdown 报告
                        # 模型阵容表
                        try:
                            lineup_rows_md = get_custom_agent_model_table(agent_configs)
                            model_lineup_md = "\n".join([f"| {n} | {v} | `{m}` |" for _k, n, v, m in lineup_rows_md])
                        except Exception:
                            model_lineup_md = ""

                        report_lines = [
                            f"# {stock_name}（{symbol}）AI 投研报告",
                            "",
                            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
                            "> 工作台：金融 Agent 工作台 v0.7（自定义多 Agent 架构）",
                            "",
                            "## 🧬 决策模型阵容",
                            "",
                            f"本次决策由 {len(agent_keys_order)} 位自定义 Agent 组成投资委员会，每位可使用不同人设、厂商和模型：",
                            "",
                            "| 角色 | 厂商 | 模型 |",
                            "| --- | --- | --- |",
                            model_lineup_md,
                            "",
                            "## 📊 行情快照",
                            "",
                            "| 项目 | 数值 |",
                            "| --- | --- |",
                            f"| 最新价 | ¥{payload.get('close', 0):.2f} |",
                            f"| 当日涨跌 | {payload.get('day_change', 0):+.2f}% |",
                            f"| 区间涨跌（{payload.get('days', 0)}日） | {payload.get('period_change', 0):+.2f}% |",
                            f"| 区间高/低 | ¥{payload.get('period_high', 0):.2f} / ¥{payload.get('period_low', 0):.2f} |",
                            f"| MA5 / MA20 / MA60 | {payload.get('ma5')} / {payload.get('ma20')} / {payload.get('ma60')} |",
                            f"| MACD / DIF / DEA | {payload.get('macd')} / {payload.get('dif')} / {payload.get('dea')} |",
                            f"| RSI(14) | {payload.get('rsi')} |",
                            f"| 当日换手率 | {payload.get('turnover', 0):.2f}% |",
                            f"| 5日量比 | {payload.get('vol_ratio', 1):.2f} |",
                            f"| 日波动率 | {payload.get('volatility', 0):.2f}% |",
                            "",
                        ]

                        if payload.get("stock_fund_brief"):
                            report_lines += [
                                "## 💰 资金流向",
                                "",
                                "```",
                                payload["stock_fund_brief"],
                                "```",
                                "",
                            ]
                        if payload.get("market_fund_brief"):
                            report_lines += [
                                "```",
                                payload["market_fund_brief"],
                                "```",
                                "",
                            ]

                        if payload.get("research_brief"):
                            report_lines += [
                                "## 📑 机构研报评级",
                                "",
                                payload["research_brief"],
                                "",
                            ]

                        if payload.get("announcements_brief") and payload["announcements_brief"] != "无近期公告":
                            report_lines += [
                                "## 📋 个股近 30 天公告",
                                "",
                                "```",
                                payload["announcements_brief"],
                                "```",
                                "",
                            ]

                        if payload.get("related_news_brief"):
                            report_lines += [
                                "## 📰 个股相关资讯",
                                "",
                                "```",
                                payload["related_news_brief"][:1500],
                                "```",
                                "",
                            ]

                        if payload.get("industry_news_brief"):
                            report_lines += [
                                "## 🏭 行业相关动态",
                                "",
                                "```",
                                payload["industry_news_brief"][:1500],
                                "```",
                                "",
                            ]

                        if payload.get("concepts_brief"):
                            report_lines += [
                                "## 🧩 关联概念与板块动态",
                                "",
                                "```",
                                payload["concepts_brief"][:1500],
                                "```",
                                "",
                            ]

                        report_lines += [
                            f"## 🤖 {len(agent_keys_order)} 位 Agent 独立观点（自定义团队）",
                            "",
                        ]
                        for k in agent_keys_order:
                            if k in llm_result["agents"]:
                                r = llm_result["agents"][k]
                                vendor_md = r.get("vendor", "?")
                                model_md = r.get("model", "?")
                                ok_md = "" if r.get("ok", True) else " ⚠️ *主模型失败已切兜底*"
                                report_lines += [
                                    f"### {r['name']}",
                                    "",
                                    f"> 模型：**{vendor_md}** / `{model_md}`{ok_md}",
                                    "",
                                    f"- **信号**：{r['signal']}",
                                    f"- **置信度**：{r['confidence']}%",
                                    f"- **理由**：{r['reason']}",
                                ]
                                ev_list = r.get("evidence") or []
                                if ev_list:
                                    report_lines.append("- **关键依据**：")
                                    for ev in ev_list:
                                        if isinstance(ev, dict):
                                            claim = (ev.get("claim") or "").strip()
                                            if not claim:
                                                continue
                                            etype = ev.get("type") or ""
                                            date = ev.get("data_date") or ""
                                            tags = []
                                            if etype and etype != "other":
                                                tags.append(f"`{etype}`")
                                            if date:
                                                tags.append(f"`{date}`")
                                            tag_suffix = (" " + " ".join(tags)) if tags else ""
                                            report_lines.append(f"  - {claim}{tag_suffix}")
                                        else:
                                            text = str(ev).strip()
                                            if text:
                                                report_lines.append(f"  - {text}")
                                if r.get("invalid_if"):
                                    report_lines.append(f"- **失效条件**：{r['invalid_if']}")
                                risks = r.get("risks") or []
                                if risks:
                                    report_lines.append("- **主要风险**：")
                                    for risk in risks:
                                        report_lines.append(f"  - {risk}")
                                report_lines.append("")

                        # 主席模型署名
                        try:
                            chair_v, chair_m = AGENT_MODEL_CONFIG.get("chairman", ("?", "?"))
                            chair_v_label = VENDORS.get(chair_v, {}).get("label", chair_v)
                        except Exception:
                            chair_v_label, chair_m = "?", "?"

                        report_lines += [
                            "## 🗳️ 投票结果",
                            "",
                            f"- 买入 **{summary['buy']}** / 卖出 **{summary['sell']}** / 观望 **{summary['hold']}**",
                            f"- 平均置信度：**{summary['avg_confidence']:.0f}%**",
                            f"- **决策：{summary['final']}**",
                            "",
                        ]

                        # v0.9: 审稿员观察
                        critic_md = llm_result.get("critic")
                        if isinstance(critic_md, dict) and critic_md.get("ok"):
                            div_md = critic_md.get("divergence") or {}
                            report_lines += [
                                "## 🧐 审稿员观察",
                                "",
                                f"> 审稿模型：**{critic_md.get('vendor', '?')}** / "
                                f"`{critic_md.get('model', '?')}`"
                                + ("（已兜底）" if critic_md.get("fallback_used") else ""),
                                "",
                                f"- **分歧度**：{div_md.get('level', '无')}",
                            ]
                            if div_md.get("main_axis"):
                                report_lines.append(f"- **主要分歧轴**：{div_md['main_axis']}")
                            if div_md.get("summary"):
                                report_lines.append(f"- **分歧解读**：{div_md['summary']}")
                            report_lines.append("")

                            for k in agent_keys_order:
                                review = (llm_result.get("agents", {}).get(k) or {}).get("review")
                                if not review:
                                    continue
                                ag_name = llm_result["agents"][k].get("name", k)
                                report_lines.append(f"### {ag_name} · 审稿评分 {review.get('quality_score', '?')}")
                                if review.get("comment"):
                                    report_lines.append(f"> {review['comment']}")
                                if review.get("supported"):
                                    report_lines.append("- ✅ 站得住的证据：")
                                    for s in review["supported"]:
                                        report_lines.append(f"  - {s}")
                                if review.get("contradictions"):
                                    report_lines.append("- ❌ 与简报矛盾：")
                                    for s in review["contradictions"]:
                                        report_lines.append(f"  - {s}")
                                if review.get("missing_evidence"):
                                    report_lines.append("- 🔍 漏掉的关键证据：")
                                    for s in review["missing_evidence"]:
                                        report_lines.append(f"  - {s}")
                                if review.get("overconfident"):
                                    report_lines.append("- ⚠️ 审稿人认为本结论过度自信")
                                report_lines.append("")

                        report_lines += [
                            "## 🎩 投资委员会主席总结",
                            "",
                            f"> 模型：**{chair_v_label}** / `{chair_m}`",
                            "",
                            st.session_state[chairman_key],
                            "",
                            "---",
                            "",
                            "*本报告由金融 Agent 工作台 v0.9 基于多厂商异构 LLM + 独立审稿 Agent 自动生成,仅供研究参考,不构成投资建议。*",
                        ]
                        report_md = "\n".join(report_lines)
                        report_filename = f"{stock_name}_{symbol}_AI报告_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

                        # 自动落盘到研究存档（5 分钟内同股票去重）
                        if ARCHIVE_AVAILABLE:
                            archive_key = f"archived_{symbol}_{chairman_key}"
                            if archive_key not in st.session_state:
                                try:
                                    arc_res = save_report(
                                        stock_name=stock_name,
                                        symbol=symbol,
                                        payload=payload,
                                        llm_result=llm_result,
                                        chairman_text=st.session_state[chairman_key],
                                        report_md=report_md,
                                    )
                                    st.session_state[archive_key] = arc_res
                                except Exception as _e:
                                    st.session_state[archive_key] = {
                                        "saved": False,
                                        "reason": f"存档失败：{_e}",
                                    }

                            arc_res = st.session_state[archive_key]
                            if arc_res.get("saved"):
                                st.success(
                                    f"📚 报告已自动存档至 `{arc_res['path']}`，可在「研究存档」Tab 检索历史决策。"
                                )
                            else:
                                st.caption(f"📚 {arc_res.get('reason', '存档跳过')}")

                        st.download_button(
                            label="📥 导出 Markdown 报告",
                            data=report_md.encode("utf-8"),
                            file_name=report_filename,
                            mime="text/markdown",
                            use_container_width=True,
                            key="download_report",
                        )
            else:
                st.caption("点击「启动深度分析」开始调用当前 AI 设置中心里的 Agent 团队。")

        # ========== 规则化 Agent 模式 ==========
        else:
            st.markdown("#### 🤖 多 Agent 协作分析（规则化）")
            st.caption("基于实时计算指标的快速推断。开启侧边栏「使用 LLM 深度分析」可获得真实 LLM 推理。")

            # 技术派
            if ma5 > ma20 and macd_val > 0:
                tech_signal, tech_conf, tech_class = "买入", 75, "buy"
                tech_reason = f"MA5({ma5:.2f}) 上穿 MA20({ma20:.2f})，MACD 红柱为正，短期动能向上"
            elif ma5 < ma20 and macd_val < 0:
                tech_signal, tech_conf, tech_class = "卖出", 70, "sell"
                tech_reason = f"MA5({ma5:.2f}) 下穿 MA20({ma20:.2f})，MACD 绿柱扩大，短期承压"
            else:
                tech_signal, tech_conf, tech_class = "观望", 55, "hold"
                tech_reason = "均线纠缠，MACD 信号不明确，建议等待方向选择"

            # 趋势派
            if period_change > 10:
                trend_signal, trend_conf, trend_class = (
                    "买入" if recent_chg > 0 else "观望",
                    68,
                    "buy" if recent_chg > 0 else "hold",
                )
                trend_reason = f"区间涨幅 {period_change:.1f}%，处于上升趋势中"
            elif period_change < -10:
                trend_signal, trend_conf, trend_class = "卖出", 65, "sell"
                trend_reason = f"区间跌幅 {period_change:.1f}%，下行趋势尚未结束"
            else:
                trend_signal, trend_conf, trend_class = "观望", 50, "hold"
                trend_reason = f"区间波动 {period_change:+.1f}%，无明显趋势"

            # 量价派
            if vol_ratio > 1.5 and recent_chg > 0:
                vol_signal, vol_conf, vol_class = "买入", 72, "buy"
                vol_reason = f"近 5 日均量放大 {vol_ratio:.1f}x，价升量增，主力进场迹象"
            elif vol_ratio > 1.5 and recent_chg < 0:
                vol_signal, vol_conf, vol_class = "卖出", 68, "sell"
                vol_reason = f"近 5 日均量放大 {vol_ratio:.1f}x 但下跌，警惕高位出货"
            else:
                vol_signal, vol_conf, vol_class = "观望", 52, "hold"
                vol_reason = f"近 5 日量比 {vol_ratio:.2f}，量能平稳无异动"

            # 风险派
            if volatility > 3:
                risk_signal, risk_conf, risk_class = "卖出", 60, "sell"
                risk_reason = f"日波动率 {volatility:.2f}%，风险偏高，建议降低仓位"
            elif volatility < 1.5:
                risk_signal, risk_conf, risk_class = "买入", 58, "buy"
                risk_reason = f"日波动率 {volatility:.2f}%，市场情绪稳定"
            else:
                risk_signal, risk_conf, risk_class = "观望", 50, "hold"
                risk_reason = f"日波动率 {volatility:.2f}%，处于正常区间"

            agents = [
                {
                    "name": "📐 技术分析师",
                    "signal": tech_signal,
                    "conf": tech_conf,
                    "reason": tech_reason,
                    "cls": tech_class,
                },
                {
                    "name": "📈 趋势跟踪师",
                    "signal": trend_signal,
                    "conf": trend_conf,
                    "reason": trend_reason,
                    "cls": trend_class,
                },
                {
                    "name": "💰 量价分析师",
                    "signal": vol_signal,
                    "conf": vol_conf,
                    "reason": vol_reason,
                    "cls": vol_class,
                },
                {
                    "name": "⚠️ 风险控制师",
                    "signal": risk_signal,
                    "conf": risk_conf,
                    "reason": risk_reason,
                    "cls": risk_class,
                },
            ]

            cols = st.columns(2)
            for idx, agent in enumerate(agents):
                with cols[idx % 2]:
                    signal_class = f"signal-{agent['cls']}"
                    st.html(f"""
                    <div class="agent-card {agent["cls"]}">
                        <div>
                            <span class="agent-name">{agent["name"]}</span>
                            <span class="agent-signal {signal_class}">{agent["signal"]}</span>
                        </div>
                        <div style='margin-top:10px;'>
                            <div style='display:flex; justify-content:space-between; align-items:center;'>
                                <span style='font-size:0.85rem; color:#6b7280;'>置信度</span>
                                <span style='font-weight:600; color:#1f2937;'>{agent["conf"]}%</span>
                            </div>
                            <div style='background:#f3f4f6; height:6px; border-radius:3px; margin-top:4px; overflow:hidden;'>
                                <div style='background:linear-gradient(90deg,#667eea,#764ba2); width:{agent["conf"]}%; height:100%;'></div>
                            </div>
                        </div>
                        <div class="agent-reason">{agent["reason"]}</div>
                    </div>
                    """)

            # 综合决策
            st.markdown('<hr class="fancy">', unsafe_allow_html=True)
            buy_count = sum(1 for a in agents if a["signal"] == "买入")
            sell_count = sum(1 for a in agents if a["signal"] == "卖出")
            hold_count = sum(1 for a in agents if a["signal"] == "观望")
            avg_conf = sum(a["conf"] for a in agents) / len(agents)

            if buy_count > sell_count and buy_count >= 2:
                final_signal, final_color = "建议买入", "#ef5350"
            elif sell_count > buy_count and sell_count >= 2:
                final_signal, final_color = "建议卖出", "#26a69a"
            else:
                final_signal, final_color = "建议观望", "#ff9800"

            st.html(f"""
            <div style='background:linear-gradient(135deg,#fafbfc,#ffffff); border-radius:14px; padding:24px;
                        border:1px solid #e5e7eb; box-shadow:0 4px 12px rgba(0,0,0,0.05);'>
                <div style='color:#6b7280; font-size:0.85rem; margin-bottom:8px;'>综合决策</div>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <div style='font-size:1.8rem; font-weight:700; color:{final_color};'>{final_signal}</div>
                    <div style='text-align:right;'>
                        <div style='font-size:0.85rem; color:#6b7280;'>买入 {buy_count} · 卖出 {sell_count} · 观望 {hold_count}</div>
                        <div style='font-size:1.1rem; font-weight:600; color:#1f2937;'>平均置信度 {avg_conf:.0f}%</div>
                    </div>
                </div>
                <div style='margin-top:14px; padding-top:14px; border-top:1px solid #f0f0f0; color:#888; font-size:0.82rem;'>
                    💡 当前为基于行情数据的快速规则推断。开启侧边栏「使用 LLM 深度分析」可获得 5 厂商异构 LLM 协同推理。
                </div>
            </div>
            """)

with tab3:
    if AI_SETTINGS_AVAILABLE:
        ai_settings_center.render_ai_settings_center(symbol)
    else:
        st.error(f"AI 设置中心未加载: {AI_SETTINGS_ERROR if 'AI_SETTINGS_ERROR' in dir() else '未知错误'}")

with tab4:
    st.markdown("#### 📰 实时资讯 & 机构研报")
    if not NEWS_AVAILABLE:
        st.error(f"新闻模块加载失败: {NEWS_ERROR if 'NEWS_ERROR' in dir() else '未知错误'}")
    else:
        # 顶部操作栏 + v0.7 视图切换
        col_refresh, col_view, col_info = st.columns([1, 2, 4])
        with col_refresh:
            if st.button("🔄 刷新数据", use_container_width=True):
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
            st.caption("时间轴模式合并三源最近 10 条按时间倒序;分类模式展示原有子 Tab。")

        # ---------- v0.7 时间轴模式 ----------
        if "时间轴" in view_mode:
            with st.spinner("正在合并三源最近资讯..."):
                em_news = cached_telegraph_em(limit=50)
                cls_news = cached_telegraph_cls(limit=20)
                sina_news = cached_telegraph_sina(limit=20)
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
                    f"合并财联社 / 东财 / 新浪,共 <b>{len(merged_sorted)}</b> 条(按时间倒序)</div>",
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
            # v0.10: 子 Tab 拆分为 5 个,公告与行业新闻独立成区
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

            # ---------- 子 Tab 1: 个股相关 ----------
            with sub_tab1:
                with st.spinner("正在筛选相关资讯..."):
                    em_news = cached_telegraph_em(limit=200)
                    cls_news = cached_telegraph_cls(limit=30)
                    sina_news = cached_telegraph_sina(limit=20)
                    all_news = em_news + cls_news + sina_news
                    main_biz = cached_main_business(symbol) or {}
                    industry = cached_industry_name(symbol)
                    # v0.10.2: 优先使用东财个股专属新闻 API(直接按代码搜),
                    # 然后追加关键词在大盘快讯里匹配的条目。两类用 (title, date) 去重。
                    stock_specific = cached_stock_news_em(symbol, limit=20) or []
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
                    # v0.10.3: 把召回逻辑透明化 —— 显示个股相关用了哪些关键词,以及 N 条来自东财个股 API、N 条来自大盘快讯关键词命中
                    from news_data import _expand_stock_keywords

                    stock_kws = _expand_stock_keywords(stock_name, symbol, products=main_biz.get("products"))
                    n_specific = len(stock_specific or [])
                    n_total = len(related)
                    n_kw = max(0, n_total - n_specific)
                    kw_chip_str = " · ".join(stock_kws) if stock_kws else "(空)"
                    st.markdown(
                        f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                        f"共 <b>{n_total}</b> 条:东财个股 API <b>{n_specific}</b> 条 + 大盘快讯关键词命中 <b>{n_kw}</b> 条"
                        f"<br><span style='color:#9ca3af; font-size:0.78rem;'>关键词: {kw_chip_str}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    for n in related:
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
                            f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                            if url
                            else title
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

            # ---------- 子区: 个股公告 ----------
            with sub_ann:
                with st.spinner("正在加载公告..."):
                    cninfo_ann = cached_announcements_cninfo(symbol, days=30)
                    em_ann_today = cached_announcements_em_today() or []
                    em_ann_for_stock = [a for a in em_ann_today if a.get("code") == symbol]
                    ann_list = merge_announcements(cninfo_ann, em_ann_for_stock)

                if not ann_list:
                    st.info(f"近 30 天内未发现 {stock_name}({symbol}) 的公告。可能是接口暂时不可用,稍后刷新重试。")
                else:
                    cat_counts = {}
                    for a in ann_list:
                        cat_counts[a.get("category", "其他")] = cat_counts.get(a.get("category", "其他"), 0) + 1
                    summary_chips = " · ".join(
                        f"<span style='color:{ANN_COLORS.get(c, '#6b7280')};'>{c} {n}</span>"
                        for c, n in sorted(cat_counts.items(), key=lambda x: -x[1])
                    )
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

            # ---------- 子区: 行业新闻 ----------
            with sub_concept:
                concepts = cached_stock_concepts(symbol, stock_name) or []
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
                        topic_concept_news = cached_topic_news_em(tuple(concept_kws[:8]), limit_each=6, total_limit=24)
                        topic_concept_news = [
                            n for n in topic_concept_news if n.get("title", "").strip() not in excluded
                        ]
                        concept_news = merge_news_items(pool_concept_news, topic_concept_news, limit=30)
                    if concept_kws:
                        st.caption("匹配词: " + " · ".join(concept_kws))
                    if not concept_news:
                        st.caption("近期未在快讯池或东财主题搜索中发现这些概念的直接相关新闻。")
                    else:
                        st.caption(
                            f"快讯池命中 {len(pool_concept_news)} 条 + 主题搜索补充 {len(topic_concept_news)} 条"
                        )
                        for n in concept_news:
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
                                f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                                if url
                                else title
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

            # ---------- 子区: 行业新闻 ----------
            with sub_industry:
                # v0.14: 如果行业名为空,尝试从概念板块中提取
                if not industry:
                    concepts_for_industry = cached_stock_concepts(symbol, stock_name) or []
                    if concepts_for_industry:
                        industry = fetch_industry_name(symbol, concepts=concepts_for_industry)
                if not industry:
                    st.info("未能识别该股票的行业,无法生成行业新闻。")
                else:
                    # v0.10.3: 经营范围里的具体业务词作为行业关键词扩展,让"计算机设备"这种
                    # 宽泛行业的小股票也能召回到机器学习 / 数据存储等相关行业新闻
                    extra_kws = []
                    scope_text = (main_biz or {}).get("scope") or ""
                    if scope_text:
                        extra_kws = extract_business_terms(scope_text, max_terms=8)
                    concepts = cached_stock_concepts(symbol, stock_name) or []
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
                        topic_ind_news = cached_topic_news_em(tuple(topic_kws), limit_each=6, total_limit=24)
                        topic_ind_news = [n for n in topic_ind_news if n.get("title", "").strip() not in excluded]
                        ind_news = merge_news_items(pool_ind_news, topic_ind_news, limit=30)
                    if not ind_news:
                        st.caption(f"近期未发现「{industry}」行业的快讯或主题搜索新闻。")
                    else:
                        # 关键词诊断:让用户看到行业新闻匹配用了哪些词
                        kw_chips = " · ".join(topic_kws or [industry] + list(extra_kws))
                        st.markdown(
                            f"<div style='color:#6b7280; font-size:0.9rem; margin-bottom:10px;'>"
                            f"行业:<b>{industry}</b> · 共 <b>{len(ind_news)}</b> 条相关行业资讯"
                            f" · 快讯池 <b>{len(pool_ind_news)}</b> 条 + 主题搜索 <b>{len(topic_ind_news)}</b> 条"
                            f"<br><span style='color:#9ca3af; font-size:0.78rem;'>匹配词: {kw_chips}</span></div>",
                            unsafe_allow_html=True,
                        )
                        for n in ind_news:
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
                                f"<a href='{url}' target='_blank' style='color:#1f2937; text-decoration:none;'>{title}</a>"
                                if url
                                else title
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

            # ---------- 子 Tab 2: 大盘快讯 ----------
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
                    items = cached_telegraph_cls(limit=20)
                    src, src_color = "财联社", "#d32f2f"
                elif "东方财富" in src_choice:
                    items = cached_telegraph_em(limit=30)
                    src, src_color = "东财", "#1976d2"
                else:
                    items = cached_telegraph_sina(limit=20)
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

            # ---------- 子 Tab 3: 研报评级 ----------
            with sub_tab3:
                with st.spinner(f"正在抓取 {stock_name} 的研报..."):
                    reports = cached_research_report(symbol, limit=20)

                if not reports:
                    st.info(f"暂未抓到 {stock_name}（{symbol}）的近期研报。")
                else:
                    # 评级分布饼图
                    rating_dist = {}
                    for r in reports:
                        rating = (r.get("rating") or "").strip()
                        # akshare 缺值会塞 nan 字符串过来
                        if not rating or rating.lower() == "nan":
                            rating = "未评级"
                        rating_dist[rating] = rating_dist.get(rating, 0) + 1

                    col_pie, col_table = st.columns([1, 2])
                    with col_pie:
                        st.markdown("##### 评级分布")
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
                        show_df = (
                            rdf[show_cols].rename(columns=rename) if all(c in rdf.columns for c in show_cols) else rdf
                        )

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
                    import math as _math

                    def _is_num(x):
                        try:
                            return x is not None and not _math.isnan(float(x))
                        except (TypeError, ValueError):
                            return False

                    for r in reports[:8]:
                        rating = r.get("rating") or ""
                        # NaN-safe: 评级字段可能是 nan 字符串
                        if rating.strip().lower() == "nan":
                            rating = "未评级"
                        rc = rating_colors_map.get(rating, "#9e9e9e")
                        pdf_link = (
                            f"<a href='{r.get('pdf', '')}' target='_blank' style='color:#667eea;'>📄 PDF</a>"
                            if r.get("pdf")
                            else ""
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

with tab5:
    st.markdown("#### 💰 资金流向（主力 / 超大单 / 大单 / 中单 / 小单）")
    if not FUND_AVAILABLE:
        st.error(f"资金流向模块加载失败: {FUND_ERROR if 'FUND_ERROR' in dir() else '未知错误'}")
    else:
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
            with st.spinner("正在拉取个股资金流向..."):
                df_ff = cached_individual_fund_flow(symbol, days=30)

            if df_ff is None or len(df_ff) == 0:
                st.info("未获取到该股资金流向数据（接口可能限速，请稍后重试）。")
            else:
                # 顶部 4 个核心指标卡
                s = summarize_fund_flow(df_ff, recent_days=5)
                kc1, kc2, kc3, kc4 = st.columns(4)

                def fund_card(label, value_yi, sub=""):
                    pos = value_yi >= 0
                    color = "#ef5350" if pos else "#26a69a"
                    sign = "+" if pos else ""
                    return f"""
                    <div class='metric-card'>
                        <div class='metric-label'>{label}</div>
                        <div class='metric-value' style='color:{color};'>{sign}{value_yi:.2f}<span style='font-size:0.9rem; color:#9ca3af; margin-left:4px;'>亿</span></div>
                        <div style='color:#9ca3af; font-size:0.78rem; margin-top:4px;'>{sub}</div>
                    </div>"""

                with kc1:
                    st.markdown(
                        fund_card(
                            "近5日主力净额",
                            s["main_total_yi"],
                            f"流入{s['inflow_days']}天 / 流出{s['outflow_days']}天",
                        ),
                        unsafe_allow_html=True,
                    )
                with kc2:
                    st.markdown(
                        fund_card("近5日超大单", s["super_total_yi"], "机构主力"),
                        unsafe_allow_html=True,
                    )
                with kc3:
                    st.markdown(
                        fund_card("近5日大单", s["large_total_yi"], "游资/大户"),
                        unsafe_allow_html=True,
                    )
                with kc4:
                    st.markdown(
                        fund_card("近5日小单", s["small_total_yi"], "散户"),
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

                def color_pos_neg(v):
                    if isinstance(v, (int, float)):
                        if v > 0:
                            return "color: #ef5350; font-weight: 600"
                        elif v < 0:
                            return "color: #26a69a; font-weight: 600"
                    return ""

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
                    tbl.style.format(fmt_dict).map(color_pos_neg, subset=num_cols),
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
                st.markdown("##### 🪙 4 类资金细分(超大/大/中/小单)")

                # 饼图(用绝对值)+ 5 日柱图
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
                            text="近 5 日 4 类资金按日趋势(亿元)",
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

                # 主力进出场判定(规则:超大单近 5 日净流入 > 5000 万 → "主力进场")
                super_5d_yi = float(s.get("super_total_yi", 0) or 0)
                large_5d_yi = float(s.get("large_total_yi", 0) or 0)
                small_5d_yi = float(s.get("small_total_yi", 0) or 0)
                if super_5d_yi > 0.5:  # 5000 万 = 0.5 亿
                    judge_label = "🟥 主力进场"
                    judge_color = "#ef5350"
                    if small_5d_yi < -0.3:
                        judge_detail = (
                            f"超大单近 5 日净流入 {super_5d_yi:+.2f} 亿(>5000万),"
                            f"散户净流出 {small_5d_yi:+.2f} 亿,典型主力底部吸筹特征。"
                        )
                    else:
                        judge_detail = f"超大单近 5 日净流入 {super_5d_yi:+.2f} 亿(>5000万),机构主导买入。"
                elif super_5d_yi < -0.5:
                    judge_label = "🟩 主力出货"
                    judge_color = "#26a69a"
                    if small_5d_yi > 0.3:
                        judge_detail = (
                            f"超大单近 5 日净流出 {super_5d_yi:+.2f} 亿,散户净流入 "
                            f"{small_5d_yi:+.2f} 亿,警惕主力借利好出货 / 散户接盘。"
                        )
                    else:
                        judge_detail = f"超大单近 5 日净流出 {super_5d_yi:+.2f} 亿,主力撤退中。"
                else:
                    judge_label = "🟨 主力观望"
                    judge_color = "#ff9800"
                    judge_detail = f"超大单近 5 日净额 {super_5d_yi:+.2f} 亿(±5000万 内),主力暂未明确选择方向。"

                st.html(f"""
                <div style='background:#f8f9fb; border-left:5px solid {judge_color};
                            border-radius:8px; padding:14px 18px; margin-top:14px;'>
                    <div style='font-weight:700; font-size:1rem; color:{judge_color};'>{judge_label}</div>
                    <div style='font-size:0.88rem; color:#374151; margin-top:4px;'>{judge_detail}</div>
                </div>
                """)

        # ---------- 大盘资金流向 ----------
        with sub_f2:
            with st.spinner("正在拉取大盘资金流向..."):
                df_mf = cached_market_fund_flow(days=30)

            if df_mf is None or len(df_mf) == 0:
                st.info("未获取到大盘资金流向数据。")
            else:
                s_m = summarize_fund_flow(df_mf, recent_days=5)

                mc1, mc2, mc3, mc4 = st.columns(4)

                def fund_card2(label, value_yi, sub=""):
                    pos = value_yi >= 0
                    color = "#ef5350" if pos else "#26a69a"
                    sign = "+" if pos else ""
                    return f"""
                    <div class='metric-card'>
                        <div class='metric-label'>{label}</div>
                        <div class='metric-value' style='color:{color}; font-size:1.5rem;'>{sign}{value_yi:.0f}<span style='font-size:0.85rem; color:#9ca3af; margin-left:4px;'>亿</span></div>
                        <div style='color:#9ca3af; font-size:0.78rem; margin-top:4px;'>{sub}</div>
                    </div>"""

                with mc1:
                    st.markdown(
                        fund_card2(
                            "近5日主力净额",
                            s_m["main_total_yi"],
                            f"流入{s_m['inflow_days']}天 / 流出{s_m['outflow_days']}天",
                        ),
                        unsafe_allow_html=True,
                    )
                with mc2:
                    st.markdown(
                        fund_card2("近5日超大单", s_m["super_total_yi"], "机构主力"),
                        unsafe_allow_html=True,
                    )
                with mc3:
                    st.markdown(
                        fund_card2("近5日大单", s_m["large_total_yi"], "游资/大户"),
                        unsafe_allow_html=True,
                    )
                with mc4:
                    st.markdown(
                        fund_card2("近5日小单", s_m["small_total_yi"], "散户"),
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
                        name="主力净流入(亿)",
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

with tab6:
    st.markdown("#### 📋 近期交易数据")
    display_df = df.tail(30).iloc[::-1].copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    display_cols = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "turnover",
    ]
    rename_map = {
        "date": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
        "pct_chg": "涨跌幅%",
        "turnover": "换手率%",
    }
    display_df = display_df[display_cols].rename(columns=rename_map)

    st.dataframe(
        display_df.style.format(
            {
                "开盘": "{:.2f}",
                "最高": "{:.2f}",
                "最低": "{:.2f}",
                "收盘": "{:.2f}",
                "成交量": "{:,.0f}",
                "成交额": "{:,.0f}",
                "涨跌幅%": "{:+.2f}",
                "换手率%": "{:.2f}",
            }
        ).map(
            lambda v: (
                "color: #ef5350"
                if isinstance(v, (int, float)) and v > 0
                else ("color: #26a69a" if isinstance(v, (int, float)) and v < 0 else "")
            ),
            subset=["涨跌幅%"],
        ),
        height=500,
        use_container_width=True,
    )

with tab7:
    if FUNDAMENTALS_PANEL_AVAILABLE:
        try:
            fundamentals_panel.render(symbol, stock_name, info or {})
        except Exception as _e:
            st.error(f"基本面面板渲染失败: {_e}")
            st.markdown("#### 💡 基本面信息")
            if info:
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
    else:
        st.warning(
            f"基本面组件未加载: {FUNDAMENTALS_PANEL_ERROR if 'FUNDAMENTALS_PANEL_ERROR' in dir() else '未知错误'}"
        )
        st.markdown("#### 💡 基本面信息")
        if info:
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
        else:
            st.info("基本面数据暂未获取到")

# ============== Tab 7: 研究存档 ==============
with tab8:
    st.markdown("#### 📚 研究存档")
    st.caption("每次 LLM 深度分析的报告会自动归档到此处，支持检索、后验标签和模型组合统计。")

    if TAGGER_AVAILABLE:
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

    if not ARCHIVE_AVAILABLE:
        st.error("⚠️ 存档模块未加载")
    else:
        stats = get_stats()

        # 顶部统计卡片
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">报告总数</div>
            <div class="metric-value">{stats["total"]}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        sc2.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">覆盖股票</div>
            <div class="metric-value">{stats["stocks"]}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        sc3.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">建议买入</div>
            <div class="metric-value" style='color:#ef5350;'>{stats["buy"]}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        sc4.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">建议卖出</div>
            <div class="metric-value" style='color:#26a69a;'>{stats["sell"]}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        sc5.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">建议观望</div>
            <div class="metric-value" style='color:#ff9800;'>{stats["hold"]}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # 多模型异构架构 v0.5：模型组合健康度小卡（仅当索引存在 combo 数据时显示）
        if stats.get("distinct_combos", 0) > 0 or stats.get("fallback_total", 0) > 0:
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

        st.markdown("")

        # 决策分布 & 活跃度可视化（仅当有数据时显示）
        if stats["total"] > 0:
            all_reports = safe_list_reports(limit=500)
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
                from collections import Counter

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

        # 模型组合统计（当前为信号分布统计；只有完成历史行情标签后，才可进一步扩展为收益命中率回测）
        combo_stats = get_combo_stats()
        if combo_stats:
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

        # v0.8: 模型组合后验表现(基于 archive_tagger 回填的 3/5/10/20 日收益与命中标签)
        try:
            combo_perf = get_combo_performance(min_samples=0)
        except Exception as _perf_e:
            combo_perf = []
            st.caption(f"模型组合后验表现暂不可用: {_perf_e}")

        if combo_perf:
            labeled_total = sum(c.get("samples_with_label", 0) for c in combo_perf)
            with st.expander(
                f"⚖️ 模型组合后验表现({labeled_total} 条已回填)",
                expanded=False,
            ):
                st.caption(
                    "聚合 3/5/10/20 日真实涨跌幅、10 日最大回撤,以及按方向拆分的 5 日命中率。"
                    " 命中口径:买入信号区间内上涨 / 卖出信号区间内下跌 / 观望信号 |涨跌幅| ≤ 2%。"
                    " 排序按 5 日总命中率降序,样本量过小的组合请审慎参考。"
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
                        "尚未有已回填的后验数据。请等待 T+3 / T+5 交易日,然后在上方"
                        "「🏷️ 历史归档自动标签」中点击「刷新行情标签」重新计算。"
                    )
                else:
                    top_perf = [c for c in combo_perf if c.get("avg_5d_return") is not None][:5]
                    if top_perf:
                        ret_fig = go.Figure(
                            go.Bar(
                                x=[c["avg_5d_return"] for c in top_perf][::-1],
                                y=[(c["combo"][:40] + "...") if len(c["combo"]) > 40 else c["combo"] for c in top_perf][
                                    ::-1
                                ],
                                orientation="h",
                                marker=dict(
                                    color=["#ef5350" if c["avg_5d_return"] > 0 else "#26a69a" for c in top_perf][::-1]
                                ),
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

        st.markdown("---")

        # 检索栏(v0.7 增加类型过滤)
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
        reports = safe_list_reports(
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
        else:
            # 列表 + 详情切换
            view_key = "arc_view_path"
            if view_key not in st.session_state:
                st.session_state[view_key] = None

            if st.session_state[view_key] is None:
                # 列表视图
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

                    # 行情标签:3/5/10/20 日涨跌幅(A股惯例:正红负绿)
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
                            ret_html += (
                                f"<span style='color:{dcolor}; margin-left:10px;'>{demoji} {dlabel} {dval:+.2f}%</span>"
                            )

                    # v0.8: 10 日窗口最大回撤(总是非正,因此恒绿;为 0 时灰显)
                    dd_val = r.get("max_drawdown_10d")
                    if dd_val is not None:
                        dd_color = "#26a69a" if dd_val < 0 else "#9ca3af"
                        ret_html += (
                            f"<span style='color:{dd_color}; margin-left:10px;' "
                            f"title='报告日起 10 日内最大回撤'>📉 回撤 {dd_val:+.2f}%</span>"
                        )

                    # v0.8: 5 日命中徽标(若 archive_tagger 已根据 decision 推断)
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

                    # v0.9: 审稿质量徽标(归档元数据里有 critic 摘要才显示)
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
            else:
                # 详情视图
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

# ============== Tab 9: 专家团圆桌（v0.7 新增）==============
with tab9:
    if not EXPERT_PANEL_AVAILABLE:
        st.error(f"专家团圆桌组件未加载: {EXPERT_PANEL_ERROR if 'EXPERT_PANEL_ERROR' in dir() else '未知错误'}")
    else:
        try:
            # 复用 llm_agents.build_market_brief() 拼接简报
            ma5_v = df["MA5"].iloc[-1] if "MA5" in df.columns else last["close"]
            ma20_v = df["MA20"].iloc[-1] if "MA20" in df.columns else last["close"]
            ma60_v = df["MA60"].iloc[-1] if "MA60" in df.columns else last["close"]
            macd_v = df["MACD"].iloc[-1] if "MACD" in df.columns else 0
            dif_v = df["DIF"].iloc[-1] if "DIF" in df.columns else 0
            dea_v = df["DEA"].iloc[-1] if "DEA" in df.columns else 0
            rsi_v = df["RSI"].iloc[-1] if "RSI" in df.columns else 50
            recent_vol_v = df["volume"].tail(5).mean()
            prev_vol_v = df["volume"].head(20).mean()
            vol_ratio_v = recent_vol_v / prev_vol_v if prev_vol_v > 0 else 1
            volatility_v = df["close"].pct_change().std() * 100

            # 资金简报
            stock_fund_brief_t8 = ""
            if FUND_AVAILABLE:
                try:
                    df_fund_t8 = cached_individual_fund_flow(symbol, days=30)
                    if df_fund_t8 is not None and len(df_fund_t8) > 0:
                        s_t8 = summarize_fund_flow(df_fund_t8, recent_days=5)
                        stock_fund_brief_t8 = build_fund_flow_brief_for_llm(s_t8, kind=stock_name)
                except Exception:
                    pass

            # v0.10: 专家圆桌也带上公告 + 行业新闻 + 研报
            announcements_brief_t8 = ""
            industry_news_brief_t8 = ""
            concepts_brief_t8 = ""
            related_brief_t8 = ""
            research_brief_t8 = ""
            if NEWS_AVAILABLE:
                try:
                    em_t8 = cached_telegraph_em(limit=200) or []
                    cls_t8 = cached_telegraph_cls(limit=30) or []
                    sina_t8 = cached_telegraph_sina(limit=20) or []
                    all_t8 = em_t8 + cls_t8 + sina_t8
                    main_biz_t8 = cached_main_business(symbol) or {}
                    industry_t8 = cached_industry_name(symbol)
                    concepts_t8 = cached_stock_concepts(symbol, stock_name) or []
                    # v0.10.2: 与 Tab 2 一致,先取个股专属新闻,再补关键词命中
                    stock_specific_t8 = cached_stock_news_em(symbol, limit=10) or []
                    keyword_matched_t8 = get_stock_related_news(
                        stock_name,
                        all_t8,
                        limit=8,
                        symbol=symbol,
                        products=main_biz_t8.get("products"),
                    )
                    seen_t9 = set()
                    related_t8 = []
                    for src_list in (stock_specific_t8, keyword_matched_t8):
                        for n in src_list:
                            key = (
                                n.get("title", "").strip(),
                                n.get("datetime", "")[:10],
                            )
                            if not key[0] or key in seen_t9:
                                continue
                            seen_t9.add(key)
                            related_t8.append(n)
                    related_brief_t8 = build_news_brief_for_llm(related_t8[:10], max_items=10)
                    if industry_t8:
                        excluded_t8 = {n.get("title", "").strip() for n in (related_t8 or [])}
                        extra_t8 = extract_business_terms((main_biz_t8 or {}).get("scope") or "", max_terms=8)
                        extra_t8 += get_concept_keywords(concepts_t8, limit=10)
                        pool_ind_t8 = get_industry_news(
                            industry_t8,
                            all_t8,
                            limit=6,
                            exclude_titles=excluded_t8,
                            extra_keywords=extra_t8,
                        )
                        topic_kws_t8 = build_topic_news_keywords(
                            industry=industry_t8,
                            business_terms=extra_t8,
                            concepts=concepts_t8,
                            limit=8,
                        )
                        topic_ind_t8 = cached_topic_news_em(tuple(topic_kws_t8), limit_each=6, total_limit=12)
                        topic_ind_t8 = [n for n in topic_ind_t8 if n.get("title", "").strip() not in excluded_t8]
                        ind_t8 = merge_news_items(pool_ind_t8, topic_ind_t8, limit=8)
                        industry_news_brief_t8 = build_news_brief_for_llm(ind_t8, max_items=6)
                    concept_excluded_t8 = {n.get("title", "").strip() for n in (related_t8 or [])}
                    pool_concept_t8 = get_concept_news(concepts_t8, all_t8, limit=6, exclude_titles=concept_excluded_t8)
                    concept_kws_t8 = get_concept_keywords(concepts_t8, limit=8)
                    topic_concept_t8 = cached_topic_news_em(tuple(concept_kws_t8), limit_each=5, total_limit=10)
                    topic_concept_t8 = [
                        n for n in topic_concept_t8 if n.get("title", "").strip() not in concept_excluded_t8
                    ]
                    concept_news_t8 = merge_news_items(pool_concept_t8, topic_concept_t8, limit=8)
                    concepts_brief_t8 = build_concepts_brief_for_llm(
                        concepts_t8, concept_news_t8, max_concepts=10, max_news=8
                    )
                    cninfo_t8 = cached_announcements_cninfo(symbol, days=30) or []
                    em_today_t8 = cached_announcements_em_today() or []
                    em_for_stock_t8 = [a for a in em_today_t8 if a.get("code") == symbol]
                    ann_t8 = merge_announcements(cninfo_t8, em_for_stock_t8)
                    announcements_brief_t8 = build_announcements_brief_for_llm(ann_t8, max_items=8)
                    rep_t8 = cached_research_report(symbol, limit=10) or []
                    research_brief_t8 = build_research_brief_for_llm(rep_t8, max_items=6)
                except Exception:
                    pass

            stock_payload_t8 = {
                "name": stock_name,
                "symbol": symbol,
                "close": float(last["close"]),
                "day_change": float(day_chg),
                "period_change": float(period_change),
                "period_high": float(period_high),
                "period_low": float(period_low),
                "days": days,
                "ma5": f"{ma5_v:.2f}",
                "ma20": f"{ma20_v:.2f}",
                "ma60": f"{ma60_v:.2f}",
                "macd": f"{macd_v:.3f}",
                "dif": f"{dif_v:.3f}",
                "dea": f"{dea_v:.3f}",
                "rsi": f"{rsi_v:.2f}",
                "volume": float(last["volume"]),
                "total_amount": float(total_amount),
                "turnover": float(last.get("turnover", 0)),
                "vol_ratio": float(vol_ratio_v),
                "volatility": float(volatility_v),
                "fundamentals": "; ".join(
                    f"{k}: {v}" for k, v in (info or {}).items() if k in ("行业", "总市值", "市盈率", "市净率")
                ),
                "stock_fund_brief": stock_fund_brief_t8,
                "related_news_brief": related_brief_t8,
                "announcements_brief": announcements_brief_t8,
                "industry_news_brief": industry_news_brief_t8,
                "concepts_brief": concepts_brief_t8,
                "research_brief": research_brief_t8,
            }
            stock_brief_t8 = (
                build_market_brief(stock_payload_t8)
                if LLM_AVAILABLE
                else (
                    f"【{stock_name}({symbol})】最新价 ¥{last['close']:.2f},当日 {day_chg:+.2f}%,"
                    f"区间涨跌 {period_change:+.2f}% MA5/20/60: {ma5_v:.2f}/{ma20_v:.2f}/{ma60_v:.2f}"
                    + ("\n" + stock_fund_brief_t8 if stock_fund_brief_t8 else "")
                )
            )

            expert_panel_view.render(symbol, stock_name, stock_brief_t8)
        except Exception as _e:
            st.error(f"专家圆桌 Tab 渲染失败: {_e}")

# ============== Tab 10: 数据源健康度 ==============
with tab10:
    try:
        from components.source_health_panel import render_source_health_panel

        render_source_health_panel()
    except Exception as _health_e:
        st.error(f"数据源健康度面板加载失败: {_health_e}")
        st.info("请确认 backend/ 模块可正常导入")

# ============== Tab 11: AI 智能助手 ==============
with tab11:
    if AI_ASSISTANT_AVAILABLE:
        try:
            # 构建 stock_data 供 AI 助手使用
            _ai_ma5 = df["MA5"].iloc[-1] if "MA5" in df.columns else last["close"]
            _ai_ma20 = df["MA20"].iloc[-1] if "MA20" in df.columns else last["close"]
            _ai_ma60 = df["MA60"].iloc[-1] if "MA60" in df.columns else last["close"]
            _ai_macd = df["MACD"].iloc[-1] if "MACD" in df.columns else 0
            _ai_dif = df["DIF"].iloc[-1] if "DIF" in df.columns else 0
            _ai_dea = df["DEA"].iloc[-1] if "DEA" in df.columns else 0
            _ai_rsi = df["RSI"].iloc[-1] if "RSI" in df.columns else 50
            _ai_vol_ratio = (
                df["volume"].tail(5).mean() / df["volume"].head(20).mean() if df["volume"].head(20).mean() > 0 else 1
            )
            _ai_volatility = df["close"].pct_change().std() * 100

            ai_stock_data = {
                "name": stock_name,
                "symbol": symbol,
                "close": float(last["close"]),
                "day_change": float(day_chg),
                "period_change": float(period_change),
                "period_high": float(period_high),
                "period_low": float(period_low),
                "days": days,
                "ma5": f"{_ai_ma5:.2f}",
                "ma20": f"{_ai_ma20:.2f}",
                "ma60": f"{_ai_ma60:.2f}",
                "macd": f"{_ai_macd:.3f}",
                "dif": f"{_ai_dif:.3f}",
                "dea": f"{_ai_dea:.3f}",
                "rsi": f"{_ai_rsi:.2f}",
                "volume": float(last["volume"]),
                "total_amount": float(total_amount),
                "turnover": float(last.get("turnover", 0)),
                "vol_ratio": float(_ai_vol_ratio),
                "volatility": float(_ai_volatility),
                "fundamentals": "; ".join(
                    f"{k}: {v}" for k, v in (info or {}).items() if k in ("行业", "总市值", "市盈率", "市净率")
                ),
            }
            ai_assistant_page.render(stock_data=ai_stock_data)
        except Exception as _ai_e:
            st.error(f"AI 智能助手加载失败: {_ai_e}")
    else:
        st.error(f"AI 智能助手模块不可用: {AI_ASSISTANT_ERROR}")
        st.info("请检查 backend/ai_assistant/ 目录是否完整")

# ============== Tab 12: Agent 工作室 ==============
with tab12:
    if AGENT_STUDIO_AVAILABLE:
        try:
            agent_studio.render()
        except Exception as _e:
            st.error(f"Agent 工作室加载失败: {_e}")
    else:
        st.warning("Agent 工作室模块不可用")
        st.info("请检查 frontend/components/agent_studio.py 是否存在")

# ============== Tab 13: 团队构建器 ==============
with tab13:
    if TEAM_BUILDER_AVAILABLE:
        try:
            team_builder.render()
        except Exception as _e:
            st.error(f"团队构建器加载失败: {_e}")
    else:
        st.warning("团队构建器模块不可用")
        st.info("请检查 frontend/components/team_builder.py 是否存在")

# ============== Tab 14: 模型提供商管理 ==============
with tab14:
    if MODEL_PROVIDER_AVAILABLE:
        try:
            model_provider_manager.render()
        except Exception as _e:
            st.error(f"模型提供商管理加载失败: {_e}")
    else:
        st.warning("模型提供商管理模块不可用")
        st.info("请检查 frontend/components/model_provider_manager.py 是否存在")

# ============== 底部 ==============
st.markdown('<hr class="fancy">', unsafe_allow_html=True)
st.html(f"""
<div style='text-align:center; color:#9ca3af; font-size:0.82rem; padding:10px;'>
    🚀 金融 Agent 工作台 v0.12 ·
    数据: <strong>Provider 插件体系</strong>(AkShare/Tushare/SEC/HKEX/OpenBB) ·
    LLM: <strong>Claude · GPT · DeepSeek · Mimo · SenseNova · Kimi</strong>(6 厂商) ·
    新增: 数据管道 / 证据驱动 Agent / 数据源健康度 ·
    生成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>
""")
