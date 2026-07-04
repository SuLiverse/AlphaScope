"""AI 智能助手页面组件 (v0.22)

全功能 AI 分析对话页面，支持：
- 自由问答 / 标准分析 / 深度分析 / 专家团圆桌 / K线图分析 五种模式
- 对话持久化（SQLite）
- 证据链展示
- 报告导出
- 图片/K线图上传分析 (v0.22)
- 与现有数据源和知识库共享
"""

import html
import os
import sys
from datetime import datetime

import streamlit as st

# 确保 backend 在 path 中
_backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 延迟导入，避免在模块级别触发导入错误
_orchestrator = None
_import_error = None


def _get_orchestrator():
    global _orchestrator, _import_error
    if _orchestrator is not None:
        return _orchestrator
    try:
        from ai_assistant.orchestrator import ChatOrchestrator

        _orchestrator = ChatOrchestrator()
        return _orchestrator
    except Exception as e:
        _import_error = str(e)
        return None


def _html(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


# ============== 模式配置 ==============
MODE_OPTIONS = {
    "自由问答": "free",
    "标准分析": "standard",
    "深度分析": "deep",
    "专家团圆桌": "expert",
    "K线图分析": "vision",
}

MODE_ICONS = {
    "free": "💬",
    "standard": "⚡",
    "deep": "🔬",
    "expert": "🎓",
    "vision": "📊",
}

MODE_DESCRIPTIONS = {
    "free": "简单问答，快速回复",
    "standard": "3 Agent 快速分析，低成本",
    "deep": "5 Agent + Critic + Chairman，全面深度",
    "expert": "多专家圆桌讨论，多视角",
    "vision": "上传K线图，AI识别形态并结合行情分析",
}


# ============== 会话状态管理 ==============
def _get_state(key, default=None):
    return st.session_state.get(f"ai_assistant_{key}", default)


def _set_state(key, value):
    st.session_state[f"ai_assistant_{key}"] = value


def _ensure_state():
    if "ai_assistant_conversation_id" not in st.session_state:
        st.session_state["ai_assistant_conversation_id"] = None
    if "ai_assistant_mode" not in st.session_state:
        st.session_state["ai_assistant_mode"] = "free"


# ============== 侧边栏：对话历史 ==============
def _render_sidebar(orchestrator):
    """渲染左侧对话历史"""
    with st.sidebar:
        st.markdown("### 📋 对话历史")

        # 新建对话按钮
        if st.button("➕ 新建对话", use_container_width=True, key="ai_new_conv"):
            st.session_state["ai_assistant_conversation_id"] = None
            st.rerun()

        st.divider()

        # 列出历史对话
        try:
            conversations = orchestrator.list_conversations(limit=20)
        except Exception:
            conversations = []

        if not conversations:
            st.caption("暂无历史对话")
            return

        for conv in conversations:
            conv_id = conv["id"]
            title = conv.get("title", "未命名对话")
            mode = conv.get("mode", "free")
            updated = conv.get("updated_at", "")
            msg_count = conv.get("message_count", 0)
            icon = MODE_ICONS.get(mode, "💬")

            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(
                    f"{icon} {title[:20]}",
                    key=f"conv_{conv_id}",
                    use_container_width=True,
                    help=f"{msg_count} 条消息 | {updated}",
                ):
                    st.session_state["ai_assistant_conversation_id"] = conv_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{conv_id}", help="删除对话"):
                    orchestrator.delete_conversation(conv_id)
                    if st.session_state.get("ai_assistant_conversation_id") == conv_id:
                        st.session_state["ai_assistant_conversation_id"] = None
                    st.rerun()


# ============== 消息渲染 ==============
def _render_message(msg: dict):
    """渲染单条消息"""
    role = msg.get("role", "")
    content = msg.get("content", "")
    timestamp = msg.get("timestamp", "")
    metadata = msg.get("metadata", {})
    if isinstance(metadata, str):
        import json

        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
            if timestamp:
                st.caption(f"🕐 {timestamp}")

    elif role == "assistant":
        mode = metadata.get("mode", "free")
        icon = MODE_ICONS.get(mode, "🤖")
        mode_label = {
            "free": "自由问答",
            "standard": "标准分析",
            "deep": "深度分析",
            "expert": "专家团",
            "vision": "K线图分析",
        }.get(mode, mode)

        with st.chat_message("assistant"):
            # 模式标签
            st.caption(f"{icon} {mode_label} | {timestamp}")
            st.markdown(content)

            # 证据链（可折叠）
            evidence = metadata.get("evidence", [])
            if evidence and isinstance(evidence, list):
                with st.expander(f"📎 证据链 ({len(evidence)} 条)", expanded=False):
                    for i, ev in enumerate(evidence, 1):
                        claim = ev.get("claim", ev.get("title", ""))
                        source = ev.get("source", ev.get("source_name", ""))
                        ev_type = ev.get("type", ev.get("evidence_type", ""))
                        st.markdown(f"**{i}. [{ev_type}]** {claim}")
                        if source:
                            st.caption(f"来源: {source}")

            # Agent 投票（可折叠）
            agents = metadata.get("agents", {})
            if agents and isinstance(agents, dict):
                with st.expander("🗳️ Agent 投票详情", expanded=False):
                    for agent_key, agent_result in agents.items():
                        if isinstance(agent_result, dict):
                            signal = agent_result.get("signal", "hold")
                            conf = agent_result.get("confidence", 0)
                            st.markdown(f"- **{agent_key}**: {signal} ({conf}%)")

            # 专家团观点（可折叠）
            opinions = metadata.get("opinions", {})
            if opinions and isinstance(opinions, dict):
                with st.expander("🎓 专家观点详情", expanded=False):
                    for expert_key, op in opinions.items():
                        if isinstance(op, dict):
                            name = op.get("expert_name", expert_key)
                            action = op.get("action", "观望")
                            pos = op.get("position", 0)
                            conf = op.get("confidence", 0)
                            st.markdown(f"- **{name}**: {action} | 仓位 {pos}% | 置信度 {conf}%")


# ============== 分析结果面板 ==============
def _render_analysis_panel(orchestrator, conversation_id: str):
    """渲染右侧分析结果面板"""
    if not conversation_id:
        return

    data = orchestrator.load_conversation(conversation_id)
    if not data:
        return

    conv = data.get("conversation", {})
    messages = data.get("messages", [])

    # 分析模式信息
    mode = conv.get("mode", "free")
    mode_label = {
        "free": "自由问答",
        "standard": "标准分析",
        "deep": "深度分析",
        "expert": "专家团圆桌",
        "vision": "K线图分析",
    }.get(mode, mode)

    st.markdown("### 📊 分析面板")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("分析模式", mode_label)
    with col2:
        st.metric("消息数", conv.get("message_count", 0))

    # 最近分析摘要
    analysis_msgs = [
        m
        for m in messages
        if m.get("role") == "assistant"
        and isinstance(m.get("metadata", {}), dict)
        and m.get("metadata", {}).get("mode") in ("standard", "deep", "expert")
    ]

    if analysis_msgs:
        latest = analysis_msgs[-1]
        meta = latest.get("metadata", {})
        summary = meta.get("summary", {})

        if summary:
            st.markdown("#### 最近投票")
            buy = summary.get("buy", 0)
            hold = summary.get("hold", 0)
            sell = summary.get("sell", 0)
            reduce = summary.get("reduce", 0)

            cols = st.columns(4)
            cols[0].metric("买入", buy)
            cols[1].metric("观望", hold)
            cols[2].metric("减持", reduce)
            cols[3].metric("卖出", sell)

    # 导出按钮
    st.divider()
    if st.button("📄 导出 Markdown 报告", use_container_width=True, key="ai_export"):
        try:
            md_content = orchestrator.export_conversation(conversation_id)
            st.download_button(
                "⬇️ 下载报告",
                data=md_content,
                file_name=f"ai_report_{conv.get('stock_symbol', 'general')}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                key="ai_download",
            )
        except Exception as e:
            st.error(f"导出失败: {e}")


# ============== 主渲染函数 ==============
def render(stock_data=None):
    """渲染 AI 智能助手页面

    Args:
        stock_data: 股票数据字典，来自 dashboard 的 stock_data 构建。
                    包含 symbol, name, close, day_change 等字段。
    """
    _ensure_state()

    # 检查模块是否可用
    orchestrator = _get_orchestrator()
    if orchestrator is None:
        st.error(f"AI 助手模块加载失败: {_import_error}")
        st.info("请检查 backend/ai_assistant/ 目录是否完整。")
        return

    # 侧边栏
    _render_sidebar(orchestrator)

    # 主区域标题
    st.markdown("## 🧠 AI 智能助手")
    st.caption("多模式金融分析对话 | 信息源与知识库共享")

    # 模式选择和股票信息
    col_mode, col_stock, col_info = st.columns([1, 1, 1])

    with col_mode:
        mode_label = st.selectbox(
            "分析模式",
            options=list(MODE_OPTIONS.keys()),
            index=0,
            key="ai_mode_select",
            help="选择分析模式",
        )
        current_mode = MODE_OPTIONS[mode_label]

    with col_stock:
        stock_symbol = ""
        stock_name = ""
        if stock_data:
            stock_symbol = stock_data.get("symbol", "")
            stock_name = stock_data.get("name", "")
        if stock_symbol:
            st.info(f"📌 当前标的: {stock_name}({stock_symbol})")
        else:
            st.warning("⚠️ 未选择标的 (自由问答模式可不选)")

    with col_info:
        st.caption(MODE_DESCRIPTIONS.get(current_mode, ""))

    # 当前对话 ID
    conversation_id = st.session_state.get("ai_assistant_conversation_id")

    # 主内容区：左对话 + 右面板
    col_chat, col_panel = st.columns([3, 1])

    with col_chat:
        # 如果没有活跃对话，显示欢迎信息
        if not conversation_id:
            st.markdown("""
            ### 👋 欢迎使用 AI 智能助手

            **开始分析：**
            1. 选择分析模式（自由问答 / 标准 / 深度 / 专家团）
            2. 在下方输入框输入问题
            3. 如需分析个股，请先在左侧选择股票

            **模式说明：**
            - 💬 **自由问答**: 快速问答，适合一般性金融问题
            - ⚡ **标准分析**: 3 个 Agent 并行分析，快速给出买卖建议
            - 🔬 **深度分析**: 5 个 Agent + Critic + Chairman，全面深度研究
            - 🎓 **专家团圆桌**: 多投资流派专家圆桌讨论
            """)

        # 显示对话消息
        if conversation_id:
            try:
                data = orchestrator.load_conversation(conversation_id)
                messages = data.get("messages", [])
                for msg in messages:
                    if msg.get("role") != "system":
                        _render_message(msg)
            except Exception as e:
                st.error(f"加载对话失败: {e}")

        # 输入区
        st.divider()

        # 图片上传（v0.22 视觉管线）
        col_input, col_upload = st.columns([4, 1])
        with col_upload:
            uploaded_image = st.file_uploader(
                "📎",
                type=["png", "jpg", "jpeg", "webp", "gif"],
                key="ai_image_upload",
                help="上传K线图/行情截图进行视觉分析",
            )

        with col_input:
            user_input = st.chat_input(
                "输入你的问题...",
                key="ai_chat_input",
            )

        # 图片上传触发视觉分析（v0.22）
        if uploaded_image and current_mode == "vision":
            if not conversation_id:
                conversation_id = orchestrator.new_conversation(
                    stock_symbol=stock_symbol,
                    stock_name=stock_name,
                    mode=AnalysisMode("vision"),
                    provider="deepseek",
                    model="deepseek-chat",
                )
                st.session_state["ai_assistant_conversation_id"] = conversation_id

            # 显示用户上传的图片
            with st.chat_message("user"):
                st.image(uploaded_image, caption="上传的K线图", use_container_width=True)
                if user_input:
                    st.markdown(user_input)

            # 视觉分析
            with st.spinner("正在分析K线图..."):
                try:
                    from backend.vision.vision_agent import analyze_image

                    img_bytes = uploaded_image.read()
                    import base64

                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    mime = uploaded_image.type or "image/png"

                    vision_result = analyze_image(
                        img_b64,
                        mime,
                        user_context=user_input or "",
                        vendor="deepseek",
                        model="deepseek-chat",
                    )

                    if vision_result.ok:
                        response_parts = []
                        if vision_result.detection:
                            d = vision_result.detection
                            if d.ticker:
                                response_parts.append(f"**识别标的**: {d.ticker_name} ({d.ticker})")
                            if d.period:
                                response_parts.append(f"**识别周期**: {d.period}")
                            response_parts.append(f"**图表类型**: {d.chart_type}")

                        if vision_result.kline_analysis:
                            k = vision_result.kline_analysis
                            if k.trend:
                                response_parts.append(f"**趋势判断**: {k.trend}")
                            if k.support_levels:
                                response_parts.append(f"**支撑位**: {', '.join(str(s) for s in k.support_levels)}")
                            if k.resistance_levels:
                                response_parts.append(f"**压力位**: {', '.join(str(r) for r in k.resistance_levels)}")
                            if k.patterns:
                                response_parts.append(f"**识别形态**: {', '.join(k.patterns)}")
                            if k.summary:
                                response_parts.append(f"\n**综合判断**: {k.summary}")

                        if vision_result.needs_more_info:
                            response_parts.append(f"\n**需要补充**: {', '.join(vision_result.missing_info)}")

                        if vision_result.disclaimer:
                            response_parts.append(f"\n⚠️ {vision_result.disclaimer}")

                        response_content = (
                            "\n\n".join(response_parts) if response_parts else "图片分析完成，但未提取到有效信息。"
                        )
                    else:
                        response_content = vision_result.summary or "图片分析失败，请确保上传的是K线图或金融图表。"

                    # 保存到对话
                    orchestrator.store.add_message(
                        conversation_id,
                        "user",
                        user_input or "[上传K线图]",
                        metadata={"mode": "vision", "has_image": True},
                    )
                    orchestrator.store.add_message(
                        conversation_id,
                        "assistant",
                        response_content,
                        metadata={"mode": "vision", "vision_analysis": True},
                    )

                except Exception as e:
                    response_content = f"视觉分析失败: {str(e)[:300]}"

            # 显示助手回复
            with st.chat_message("assistant"):
                st.markdown(response_content)

            st.rerun()

        if user_input:
            # 如果没有活跃对话，创建新对话
            if not conversation_id:
                conversation_id = orchestrator.new_conversation(
                    stock_symbol=stock_symbol,
                    stock_name=stock_name,
                    mode=AnalysisMode(current_mode),
                    provider="deepseek",
                    model="deepseek-chat",
                )
                st.session_state["ai_assistant_conversation_id"] = conversation_id

            # 显示用户消息
            with st.chat_message("user"):
                st.markdown(user_input)

            # 发送消息并获取响应
            with st.spinner(f"正在{mode_label}中..."):
                try:
                    result = orchestrator.send_message(
                        conversation_id=conversation_id,
                        user_input=user_input,
                        stock_data=stock_data,
                        expert_team_id=None,
                        global_ai_settings=None,
                    )
                except Exception as e:
                    result = {
                        "mode": current_mode,
                        "content": f"处理失败: {str(e)[:300]}",
                        "error": True,
                    }

            # 显示助手回复
            response_content = result.get("content", "未获取到回复")
            with st.chat_message("assistant"):
                st.markdown(response_content)

                # 证据链
                evidence = result.get("evidence", [])
                if evidence and isinstance(evidence, list):
                    with st.expander(f"📎 证据链 ({len(evidence)} 条)", expanded=False):
                        for i, ev in enumerate(evidence, 1):
                            claim = ev.get("claim", ev.get("title", ""))
                            source = ev.get("source", ev.get("source_name", ""))
                            st.markdown(f"**{i}.** {claim}")
                            if source:
                                st.caption(f"来源: {source}")

            # 刷新页面以显示新消息
            st.rerun()

    with col_panel:
        _render_analysis_panel(orchestrator, conversation_id)


# ============== 导入 AnalysisMode ==============
try:
    from ai_assistant.orchestrator import AnalysisMode
except Exception:

    class AnalysisMode:
        FREE = "free"
        STANDARD = "standard"
        DEEP = "deep"
        EXPERT = "expert"
        VISION = "vision"

        def __init__(self, value):
            self.value = value
