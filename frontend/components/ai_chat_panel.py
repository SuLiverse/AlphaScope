"""
AI 咨询面板组件(v0.7)
- Streamlit 聊天工作区:模型状态 + 上下文卡片 + 快捷问题 + 消息流 + 输入区
- 通过 ai_chat 后端模块完成会话状态/上下文注入/LLM 调用
- session_state key 命名:`chat_session_{symbol}` 保存 ChatSession
"""

import html
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from ai_chat import (  # noqa: E402
    ChatSession,
    new_session,
    send_message,
    export_to_markdown,
    PROVIDER_DEFAULT_MODEL,
    MAX_ROUNDS,
    fetch_model_list,
)
from project_paths import REPORTS_DIR  # noqa: E402


CHAT_HISTORY_DIR = REPORTS_DIR / "chat_history"


# ============== 引导问题 ==============
GUIDE_QUESTIONS = [
    "请解读当前走势和关键价位。",
    "当前最大的风险点是什么？",
    "从短线 5 个交易日角度怎么看？",
    "从中线持有角度看，应该重点跟踪哪些指标？",
    "现在估值贵不贵？请结合已知数据说明。",
    "请把机会、风险和后续观察点整理成表格。",
]


# ============== 基础工具 ==============
def _get_session(symbol: str) -> ChatSession | None:
    return st.session_state.get(f"chat_session_{symbol}")


def _set_session(symbol: str, sess: ChatSession):
    st.session_state[f"chat_session_{symbol}"] = sess


def _html(value) -> str:
    """只用于本地 HTML 模板中的变量，不用于渲染 Markdown 内容。"""
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt_num(value, digits: int = 2, suffix: str = "") -> str:
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return "N/A"


def _trend_class(value) -> str:
    try:
        v = float(value)
    except Exception:
        return "neutral"
    if v > 0:
        return "up"
    if v < 0:
        return "down"
    return "neutral"


def _message_count(sess: ChatSession) -> int:
    return sum(1 for m in getattr(sess, "messages", []) if getattr(m, "role", "") != "system")


def _round_count(sess: ChatSession) -> int:
    return sum(1 for m in getattr(sess, "messages", []) if getattr(m, "role", "") == "user")


def _ensure_session(
    symbol: str,
    stock_name: str,
    ctx: dict,
    provider: str | None = None,
    api_key: str | None = None,
) -> ChatSession:
    sess = _get_session(symbol)
    if sess is None:
        # 不把 api_key 直接传给 new_session：Streamlit 热重载时可能缓存旧版 ai_chat.new_session，
        # 旧函数不接受 api_key 参数。先创建会话，再动态补字段，兼容新旧后端。
        sess = new_session(symbol, stock_name, ctx, provider=provider)
        sess.api_key = api_key or ""
        sess.custom_base_url = ""
        sess.custom_models = []
        _set_session(symbol, sess)
    else:
        # 旧对象兼容：动态添加缺失字段，保留对话历史。
        changed = False
        if not hasattr(sess, "api_key"):
            sess.api_key = api_key or ""
            changed = True
        if not hasattr(sess, "custom_base_url"):
            sess.custom_base_url = ""
            changed = True
        if not hasattr(sess, "custom_models") or sess.custom_models is None:
            sess.custom_models = []
            changed = True
        if not hasattr(sess, "messages") or sess.messages is None:
            sess.messages = []
            changed = True
        if not hasattr(sess, "context_snapshot") or sess.context_snapshot is None:
            sess.context_snapshot = dict(ctx or {})
            changed = True
        if not hasattr(sess, "max_rounds") or not sess.max_rounds:
            sess.max_rounds = MAX_ROUNDS
            changed = True
        if not hasattr(sess, "created_at") or not sess.created_at:
            sess.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            changed = True
        if not hasattr(sess, "provider") or not sess.provider:
            sess.provider = provider or "deepseek"
            changed = True
        if not hasattr(sess, "model") or not sess.model:
            sess.model = PROVIDER_DEFAULT_MODEL.get(sess.provider, "deepseek-chat")
            changed = True
        if changed:
            _set_session(symbol, sess)
    return sess


def _save_chat_md(sess: ChatSession) -> Path:
    CHAT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"chat_{sess.stock_symbol}_{ts}.md"
    fpath = CHAT_HISTORY_DIR / fname
    fpath.write_text(export_to_markdown(sess), encoding="utf-8")
    return fpath


def _inject_ai_chat_css():
    st.markdown(
        """
<style>
.ai-chat-hero {
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: 18px;
    padding: 16px 18px;
    margin-bottom: 14px;
    background: linear-gradient(135deg, rgba(99,102,241,0.10), rgba(14,165,233,0.06) 45%, rgba(255,255,255,0.98));
    box-shadow: 0 8px 26px rgba(15, 23, 42, 0.06);
}
.ai-chat-hero-top {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
    flex-wrap: wrap;
}
.ai-chat-title {
    font-size: 1.12rem;
    line-height: 1.35;
    font-weight: 800;
    color: #111827;
    margin-bottom: 4px;
}
.ai-chat-subtitle {
    color: #64748b;
    font-size: 0.84rem;
}
.ai-chat-badges {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
}
.ai-chat-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 650;
    background: #eef2ff;
    color: #4f46e5;
    border: 1px solid #c7d2fe;
}
.ai-chat-badge.gray {
    background: #f8fafc;
    color: #475569;
    border-color: #e2e8f0;
}
.ai-chat-badge.green {
    background: #ecfdf5;
    color: #047857;
    border-color: #a7f3d0;
}
.ai-chat-badge.orange {
    background: #fff7ed;
    color: #c2410c;
    border-color: #fed7aa;
}
.ai-chat-context {
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 16px;
    padding: 12px 14px;
    margin: 10px 0 12px;
    background: #ffffff;
}
.ai-chat-context-title {
    font-weight: 750;
    color: #111827;
    font-size: 0.92rem;
    margin-bottom: 8px;
}
.ai-chat-context-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
}
.ai-chat-context-item {
    border-radius: 12px;
    background: #f8fafc;
    border: 1px solid #eef2f7;
    padding: 8px 10px;
}
.ai-chat-context-label {
    color: #64748b;
    font-size: 0.72rem;
    margin-bottom: 2px;
}
.ai-chat-context-value {
    color: #0f172a;
    font-size: 0.9rem;
    font-weight: 760;
}
.ai-chat-context-value.up { color: #ef4444; }
.ai-chat-context-value.down { color: #16a34a; }
.ai-chat-section-title {
    font-size: 0.86rem;
    color: #475569;
    font-weight: 700;
    margin: 8px 0 6px;
}
.ai-chat-empty {
    border: 1px dashed rgba(99, 102, 241, 0.35);
    border-radius: 16px;
    padding: 16px;
    margin: 10px 0;
    background: linear-gradient(135deg, rgba(238,242,255,0.75), rgba(255,255,255,0.95));
    color: #334155;
}
.ai-chat-empty-title {
    font-weight: 800;
    color: #1e1b4b;
    margin-bottom: 6px;
}
.ai-chat-note {
    color: #64748b;
    font-size: 0.78rem;
    line-height: 1.55;
}
.ai-chat-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.35), transparent);
    margin: 12px 0;
}
@media (max-width: 900px) {
    .ai-chat-context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .ai-chat-badges { justify-content: flex-start; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_header(symbol: str, stock_name: str, ctx: dict, sess: ChatSession):
    data_date = ctx.get("data_date") or datetime.now().strftime("%Y-%m-%d")
    key_status = "临时密钥" if getattr(sess, "api_key", "") else "默认密钥"
    key_cls = "orange" if getattr(sess, "api_key", "") else "gray"
    st.markdown(
        f"""
<div class="ai-chat-hero">
  <div class="ai-chat-hero-top">
    <div>
      <div class="ai-chat-title">AI 投资咨询工作区</div>
      <div class="ai-chat-subtitle">当前标的：<b>{_html(stock_name)}</b> ({_html(symbol)}) · 数据日期 {_html(data_date)}</div>
    </div>
    <div class="ai-chat-badges">
      <span class="ai-chat-badge">Provider: {_html(sess.provider)}</span>
      <span class="ai-chat-badge gray">Model: {_html(sess.model)}</span>
      <span class="ai-chat-badge green">行情上下文已注入</span>
      <span class="ai-chat-badge {key_cls}">{key_status}</span>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _render_context_card(ctx: dict):
    close = _fmt_num(ctx.get("close"), suffix=" ¥")
    day_change = _fmt_num(ctx.get("day_change"), suffix="%")
    period_change = _fmt_num(ctx.get("period_change"), suffix="%")
    fund_dir = ctx.get("fund_dir") or "暂无主力资金数据"
    if len(str(fund_dir)) > 38:
        fund_dir = str(fund_dir)[:38] + "..."

    st.markdown(
        f"""
<div class="ai-chat-context">
  <div class="ai-chat-context-title">已传给 AI 的行情摘要</div>
  <div class="ai-chat-context-grid">
    <div class="ai-chat-context-item">
      <div class="ai-chat-context-label">最新价</div>
      <div class="ai-chat-context-value">{_html(close)}</div>
    </div>
    <div class="ai-chat-context-item">
      <div class="ai-chat-context-label">当日涨跌</div>
      <div class="ai-chat-context-value {_trend_class(ctx.get("day_change"))}">{_html(day_change)}</div>
    </div>
    <div class="ai-chat-context-item">
      <div class="ai-chat-context-label">区间涨跌</div>
      <div class="ai-chat-context-value {_trend_class(ctx.get("period_change"))}">{_html(period_change)}</div>
    </div>
    <div class="ai-chat-context-item">
      <div class="ai-chat-context-label">均线 MA5/20/60</div>
      <div class="ai-chat-context-value">{_html(ctx.get("ma5", "N/A"))} / {_html(ctx.get("ma20", "N/A"))} / {_html(ctx.get("ma60", "N/A"))}</div>
    </div>
  </div>
  <div class="ai-chat-note" style="margin-top:8px;">资金面：{_html(fund_dir)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("查看完整上下文快照", expanded=False):
        safe_ctx = {
            k: v for k, v in (ctx or {}).items() if "key" not in str(k).lower() and "token" not in str(k).lower()
        }
        st.json(safe_ctx)


def _render_model_settings(symbol: str, stock_name: str, ctx: dict, sess: ChatSession) -> ChatSession:
    providers = list(PROVIDER_DEFAULT_MODEL.keys())
    custom_provider_label = "custom"

    if not hasattr(sess, "custom_base_url"):
        sess.custom_base_url = ""
    if not hasattr(sess, "custom_models") or sess.custom_models is None:
        sess.custom_models = []
    if sess.provider not in providers and sess.provider != custom_provider_label:
        sess.provider = providers[0] if providers else "deepseek"
        sess.model = PROVIDER_DEFAULT_MODEL.get(sess.provider, "deepseek-chat")
        _set_session(symbol, sess)

    with st.expander("模型与连接设置", expanded=False):
        st.markdown("**内置厂商**")
        c1, c2 = st.columns([1, 1])
        builtin_provider = sess.provider if sess.provider in providers else (providers[0] if providers else "deepseek")
        with c1:
            selected_builtin_provider = st.selectbox(
                "模型厂商",
                providers,
                index=providers.index(builtin_provider) if builtin_provider in providers else 0,
                key=f"chat_provider_select_{symbol}",
                help="内置厂商使用项目预设 Base URL。下面可以单独启用自定义 OpenAI 兼容接口。",
            )
        with c2:
            builtin_model = st.text_input(
                "模型名称",
                value=sess.model
                if sess.provider != custom_provider_label
                else PROVIDER_DEFAULT_MODEL.get(selected_builtin_provider, "deepseek-chat"),
                key=f"chat_model_input_{symbol}",
                help="默认使用项目内置模型映射；如需测试兼容模型，可在这里临时覆盖。",
            )

        st.markdown("---")
        st.markdown("**自定义厂商（OpenAI 兼容 / CherryStudio 风格）**")
        enable_custom = st.checkbox(
            "启用自定义厂商 API 接口",
            value=(sess.provider == custom_provider_label or bool(getattr(sess, "custom_base_url", ""))),
            key=f"chat_enable_custom_{symbol}",
            help="开启后会使用你填写的 Base URL + API Key 调用模型，并支持从 /models 获取模型列表。",
        )

        custom_base_url = st.text_input(
            "自定义 API Base URL",
            value=getattr(sess, "custom_base_url", "") or "",
            key=f"chat_custom_base_url_{symbol}",
            placeholder="https://api.example.com/v1",
            help="兼容 OpenAI API 的地址；如果没有写 /v1，后端会自动补齐。",
        )
        custom_key = st.text_input(
            "自定义 API Key",
            value=getattr(sess, "api_key", "") or "",
            type="password",
            key=f"chat_api_key_{symbol}",
            help="仅保存在当前 Streamlit 会话内存中，不会保存、导出或写入上下文。",
        )

        custom_model_options = list(dict.fromkeys([m for m in getattr(sess, "custom_models", []) if m]))
        current_custom_model = sess.model if sess.provider == custom_provider_label else ""
        if current_custom_model and current_custom_model not in custom_model_options:
            custom_model_options.insert(0, current_custom_model)

        mc1, mc2 = st.columns([1, 1])
        with mc1:
            if custom_model_options:
                custom_model = st.selectbox(
                    "自定义模型",
                    custom_model_options,
                    index=custom_model_options.index(current_custom_model)
                    if current_custom_model in custom_model_options
                    else 0,
                    key=f"chat_custom_model_select_{symbol}",
                    help="模型列表来自你填写的 Base URL /models，也可以手动添加。",
                )
            else:
                custom_model = st.text_input(
                    "自定义模型",
                    value=current_custom_model,
                    key=f"chat_custom_model_input_{symbol}",
                    placeholder="例如 deepseek-chat / gpt-4o-mini / qwen-plus",
                )
        with mc2:
            manual_model = st.text_input(
                "手动添加模型",
                value="",
                key=f"chat_manual_model_{symbol}",
                placeholder="输入模型 ID 后点击添加",
            )

        bc1, bc2 = st.columns([1, 1])
        with bc1:
            if st.button(
                "获取模型列表",
                use_container_width=True,
                key=f"chat_fetch_models_{symbol}",
            ):
                try:
                    models = fetch_model_list(custom_base_url, custom_key)
                    if models:
                        sess.custom_models = models
                        sess.model = models[0]
                        sess.provider = custom_provider_label
                        sess.custom_base_url = custom_base_url
                        sess.api_key = custom_key
                        st.session_state["chat_provider_override"] = custom_provider_label
                        _set_session(symbol, sess)
                        st.success(f"已获取 {len(models)} 个模型。")
                        st.rerun()
                    else:
                        st.warning("接口已连接，但没有返回可用模型。可以手动添加模型名称。")
                except Exception as e:
                    st.error(f"获取模型列表失败: {str(e)[:220]}")
        with bc2:
            if st.button("添加模型", use_container_width=True, key=f"chat_add_model_{symbol}"):
                model_id = (manual_model or "").strip()
                if not model_id:
                    st.warning("请先输入模型 ID。")
                else:
                    models = list(dict.fromkeys([*getattr(sess, "custom_models", []), model_id]))
                    sess.custom_models = models
                    sess.model = model_id
                    sess.provider = custom_provider_label
                    sess.custom_base_url = custom_base_url
                    sess.api_key = custom_key
                    st.session_state["chat_provider_override"] = custom_provider_label
                    _set_session(symbol, sess)
                    st.success(f"已添加模型: {model_id}")
                    st.rerun()

        st.caption(
            "安全提示：Base URL、API Key 和自定义模型只保存在当前 Streamlit 会话内存中，不写入配置文件和 Markdown 导出。"
        )

        changed = False
        if enable_custom:
            if sess.provider != custom_provider_label:
                sess.provider = custom_provider_label
                st.session_state["chat_provider_override"] = custom_provider_label
                changed = True
            if custom_base_url != getattr(sess, "custom_base_url", ""):
                sess.custom_base_url = custom_base_url
                changed = True
            if custom_key != getattr(sess, "api_key", ""):
                sess.api_key = custom_key
                changed = True
            if (custom_model or "").strip() and custom_model.strip() != sess.model:
                sess.model = custom_model.strip()
                changed = True
        else:
            if sess.provider == custom_provider_label or selected_builtin_provider != sess.provider:
                sess.provider = selected_builtin_provider
                sess.custom_base_url = ""
                sess.model = PROVIDER_DEFAULT_MODEL.get(selected_builtin_provider, "deepseek-chat")
                st.session_state["chat_provider_override"] = selected_builtin_provider
                changed = True
            elif builtin_model.strip() and builtin_model.strip() != sess.model:
                sess.model = builtin_model.strip()
                changed = True
            if custom_key != getattr(sess, "api_key", ""):
                sess.api_key = custom_key
                changed = True

        if changed:
            _set_session(symbol, sess)
            st.rerun()

    return sess


def _render_actions(symbol: str, stock_name: str, ctx: dict, sess: ChatSession):
    c1, c2, c3, c4 = st.columns([1.2, 1.1, 1.1, 1.1])
    with c1:
        st.caption(
            f"消息 {_message_count(sess)} 条 · 轮次 {_round_count(sess)}/{getattr(sess, 'max_rounds', MAX_ROUNDS)}"
        )
    with c2:
        if st.button("新会话", use_container_width=True, key=f"chat_new_{symbol}"):
            new_sess = new_session(
                symbol,
                stock_name,
                ctx,
                provider=sess.provider if sess.provider != "custom" else "deepseek",
            )
            new_sess.provider = getattr(sess, "provider", "deepseek")
            new_sess.model = getattr(sess, "model", "") or PROVIDER_DEFAULT_MODEL.get(
                new_sess.provider, "deepseek-chat"
            )
            new_sess.api_key = getattr(sess, "api_key", "") or ""
            new_sess.custom_base_url = getattr(sess, "custom_base_url", "") or ""
            new_sess.custom_models = list(getattr(sess, "custom_models", []) or [])
            _set_session(symbol, new_sess)
            st.rerun()
    with c3:
        if st.button("导出 MD", use_container_width=True, key=f"chat_export_{symbol}"):
            try:
                p = _save_chat_md(sess)
                st.session_state[f"chat_last_export_{symbol}"] = str(p)
                st.success(f"已保存: {p.name}")
            except Exception as e:
                st.error(f"导出失败: {e}")
    with c4:
        if st.button("关闭", use_container_width=True, key=f"chat_close_{symbol}"):
            st.session_state["show_ai_chat"] = False
            st.rerun()

    if st.session_state.get(f"chat_last_export_{symbol}"):
        st.caption(f"上次导出: `{st.session_state[f'chat_last_export_{symbol}']}`")


def _prepare_input_state(symbol: str, input_key: str):
    clear_flag = f"chat_clear_input_next_{symbol}"
    if st.session_state.pop(clear_flag, False):
        st.session_state[input_key] = ""


def _render_quick_prompts(symbol: str, input_key: str):
    st.markdown("<div class='ai-chat-section-title'>快捷问题</div>", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, q in enumerate(GUIDE_QUESTIONS):
        with cols[i % 3]:
            if st.button(q, key=f"chat_g_{symbol}_{i}", use_container_width=True):
                # 只填入输入框，不自动发送，避免误调用模型。
                st.session_state[input_key] = q
                st.rerun()


def _render_messages(sess: ChatSession):
    st.markdown("<div class='ai-chat-section-title'>对话历史</div>", unsafe_allow_html=True)
    chat_msgs = [m for m in getattr(sess, "messages", []) if getattr(m, "role", "") != "system"]
    if not chat_msgs:
        st.markdown(
            """
<div class="ai-chat-empty">
  <div class="ai-chat-empty-title">我是你的 AI 投资咨询助手</div>
  <div class="ai-chat-note">
    我会结合当前仪表盘中的行情、均线、资金面和最近 Agent 研究摘要来回答。<br>
    可以先点击上方快捷问题填入输入框，确认后再发送。
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        return

    for m in chat_msgs:
        role = getattr(m, "role", "assistant")
        content = getattr(m, "content", "") or ""
        timestamp = getattr(m, "timestamp", "") or ""
        if role == "user":
            with st.chat_message("user", avatar="🙋"):
                st.caption(f"我 · {timestamp}")
                st.markdown(content)
        else:
            with st.chat_message("assistant", avatar="🤖"):
                st.caption(f"AI 分析师 · {getattr(sess, 'provider', 'provider')} · {timestamp}")
                st.markdown(content)


def _render_input_area(symbol: str, sess: ChatSession):
    input_key = f"chat_input_{symbol}"
    _prepare_input_state(symbol, input_key)

    st.markdown("<div class='ai-chat-section-title'>继续提问</div>", unsafe_allow_html=True)
    user_input = st.text_area(
        "向 AI 提问",
        key=input_key,
        height=96,
        label_visibility="collapsed",
        placeholder="例如：请结合当前趋势、资金流和风险因素，给出一份简明分析。",
    )

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        st.caption("发送前可编辑快捷问题；空输入不会调用模型。")
    with c2:
        if st.button("清空输入", use_container_width=True, key=f"chat_clear_input_btn_{symbol}"):
            st.session_state[f"chat_clear_input_next_{symbol}"] = True
            st.rerun()
    with c3:
        send_clicked = st.button("发送", use_container_width=True, type="primary", key=f"chat_send_{symbol}")

    if send_clicked:
        msg_to_send = (user_input or "").strip()
        if not msg_to_send:
            st.warning("请先输入问题。")
            return
        with st.spinner("AI 正在结合行情上下文分析..."):
            try:
                sess = send_message(sess, msg_to_send)
                _set_session(symbol, sess)
                st.session_state[f"chat_clear_input_next_{symbol}"] = True
            except Exception as e:
                st.error(f"对话失败: {e}")
        st.rerun()


# ============== 主入口 ==============
def render(symbol: str, stock_name: str, ctx: dict):
    """
    渲染 AI 咨询面板。
    - symbol/stock_name: 当前股票
    - ctx: 通过 dashboard.build_chat_context() 拼接好的上下文 dict
    """
    _inject_ai_chat_css()

    if not symbol or not stock_name:
        st.info("请先在侧边栏选择股票")
        return

    input_key = f"chat_input_{symbol}"
    _prepare_input_state(symbol, input_key)

    cur_override = st.session_state.get("chat_provider_override")
    default_provider = cur_override or os.getenv("AI_CHAT_PROVIDER", "deepseek")
    if default_provider not in PROVIDER_DEFAULT_MODEL and default_provider != "custom":
        default_provider = "deepseek"
    session_provider = default_provider if default_provider in PROVIDER_DEFAULT_MODEL else "deepseek"

    sess = _ensure_session(symbol, stock_name, ctx, provider=session_provider)
    global_ai_settings = st.session_state.get("ai_global_settings", {})
    if global_ai_settings.get("use_unified_key", False):
        provider = global_ai_settings.get("provider") or sess.provider
        sess.provider = provider if provider in PROVIDER_DEFAULT_MODEL else "custom"
        sess.model = global_ai_settings.get("model") or sess.model
        sess.api_key = global_ai_settings.get("api_key", "") or getattr(sess, "api_key", "")
        sess.custom_base_url = global_ai_settings.get("base_url", "") or getattr(sess, "custom_base_url", "")
        if global_ai_settings.get("custom_models"):
            sess.custom_models = list(global_ai_settings.get("custom_models") or [])
        _set_session(symbol, sess)
    sess = _render_model_settings(symbol, stock_name, ctx, sess)
    _render_header(symbol, stock_name, ctx, sess)
    _render_context_card(ctx)
    _render_actions(symbol, stock_name, ctx, sess)
    st.markdown("<div class='ai-chat-divider'></div>", unsafe_allow_html=True)
    _render_quick_prompts(symbol, input_key)
    st.markdown("<div class='ai-chat-divider'></div>", unsafe_allow_html=True)
    _render_messages(sess)
    st.markdown("<div class='ai-chat-divider'></div>", unsafe_allow_html=True)
    _render_input_area(symbol, sess)


def render_floating_button():
    """
    渲染右下角浮动按钮的 HTML(供 dashboard 在主区域顶层注入)。
    点击通过 form 提交切换 show_ai_chat 状态(Streamlit 不支持原生 JS 触发回调,
    所以这里用 CSS 固定按钮 + 实际 toggle 由调用方提供的 st.button 完成)。
    """
    is_open = st.session_state.get("show_ai_chat", False)
    label = "✕ 关闭咨询" if is_open else "🤖 AI 咨询"
    color = "#ef4444" if is_open else "#6366f1"
    st.html(f"""
    <style>
    .ai-chat-fab {{
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999;
        background: {color};
        color: white;
        border-radius: 28px;
        padding: 12px 22px;
        font-size: 0.92rem;
        font-weight: 600;
        box-shadow: 0 6px 18px rgba(0,0,0,0.18);
        cursor: pointer;
        user-select: none;
        font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
        display: flex;
        align-items: center;
        gap: 6px;
    }}
    .ai-chat-fab:hover {{
        transform: translateY(-1px);
        box-shadow: 0 8px 22px rgba(0,0,0,0.25);
    }}
    .ai-chat-fab-hint {{
        position: fixed;
        bottom: 78px;
        right: 24px;
        z-index: 9998;
        background: rgba(31,41,55,0.92);
        color: white;
        font-size: 0.72rem;
        padding: 4px 10px;
        border-radius: 6px;
        opacity: 0.85;
    }}
    </style>
    <div class="ai-chat-fab-hint">点击右上角按钮切换 →</div>
    <div class="ai-chat-fab">{label}</div>
    """)
