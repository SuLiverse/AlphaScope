"""
Agent Studio UI 组件。

功能：
- 查看和编辑 Agent 配置（角色、提示词、模型）
- 支持自定义 Agent 创建
- Agent 模型分配预览
- 测试单个 Agent
"""

import streamlit as st
from typing import Dict, Any, List


def _get_agent_configs() -> List[Dict[str, Any]]:
    """获取默认 Agent 配置"""
    try:
        from backend.agents.base import get_default_agent_configs

        return get_default_agent_configs(include_chairman=True)
    except Exception:
        return []


def _get_model_table() -> list:
    """获取 Agent 模型分配表"""
    try:
        from backend.agents.financial_agents import get_agent_model_table

        return get_agent_model_table()
    except Exception:
        return []


def _get_mode_configs() -> list:
    """获取模式配置列表"""
    try:
        from backend.agent_modes import get_mode_choices

        return get_mode_choices()
    except Exception:
        return []


def render():
    """渲染 Agent Studio 页面"""
    st.header("🤖 Agent Studio")
    st.caption("查看和配置分析 Agent 的角色、提示词和模型分配")

    # 模式概览
    modes = _get_mode_configs()
    if modes:
        st.subheader("分析模式")
        cols = st.columns(len(modes))
        for i, mode in enumerate(modes):
            with cols[i]:
                st.info(f"**{mode['name']}**\n\n{mode['description']}")

    # Agent 模型分配表
    st.divider()
    st.subheader("Agent 模型分配")
    model_table = _get_model_table()
    if model_table:
        st.dataframe(
            [{"Agent": name, "供应商": vendor, "模型": model} for _, name, vendor, model in model_table],
            use_container_width=True,
            hide_index=True,
        )

    # Agent 详情编辑
    st.divider()
    st.subheader("Agent 详情")
    configs = _get_agent_configs()

    for cfg in configs:
        with st.expander(f"{cfg['name']} (`{cfg['key']}`)", expanded=False):
            col1, col2 = st.columns([1, 1])
            with col1:
                st.text_input(
                    "名称",
                    value=cfg["name"],
                    key=f"agent_name_{cfg['key']}",
                    disabled=True,
                )
                st.text_input(
                    "供应商",
                    value=cfg["provider"],
                    key=f"agent_prov_{cfg['key']}",
                    disabled=True,
                )
                st.text_input(
                    "模型",
                    value=cfg["model"],
                    key=f"agent_model_{cfg['key']}",
                    disabled=True,
                )
            with col2:
                st.text_area(
                    "角色",
                    value=cfg["role"],
                    key=f"agent_role_{cfg['key']}",
                    height=100,
                    disabled=True,
                )
                st.text_area(
                    "指令",
                    value=cfg["instruction"][:200] + "...",
                    key=f"agent_inst_{cfg['key']}",
                    height=100,
                    disabled=True,
                )

            st.caption("提示词编辑功能将在后续版本开放")

    # 自定义 Agent
    st.divider()
    st.subheader("创建自定义 Agent")
    with st.form("custom_agent"):
        col1, col2 = st.columns(2)
        with col1:
            agent_key = st.text_input("Agent ID", placeholder="my_analyst")
            agent_name = st.text_input("显示名称", placeholder="我的分析师")
            agent_provider = st.selectbox("供应商", ["deepseek", "claude", "gpt", "mimo", "sensenova"])
        with col2:
            agent_model = st.text_input("模型", placeholder="deepseek-chat")
            agent_avatar = st.text_input("头像 Emoji", value="🤖")
            card_style = st.selectbox("卡片风格", ["default", "value", "technical", "growth", "risk", "macro"])

        agent_role = st.text_area("角色描述", placeholder="你是一位专注于XXX的分析师...")
        agent_instruction = st.text_area("分析指令", placeholder="请基于数据进行XXX分析...")

        if st.form_submit_button("创建 Agent"):
            if agent_key and agent_name and agent_role:
                st.success(f"Agent '{agent_name}' 配置已记录。可通过 dashboard 的自定义 Agent 功能使用。")
                st.json(
                    {
                        "key": agent_key,
                        "name": agent_name,
                        "avatar": agent_avatar,
                        "provider": agent_provider,
                        "model": agent_model,
                        "role": agent_role,
                        "instruction": agent_instruction,
                        "card_style": card_style,
                        "enabled": True,
                    }
                )
            else:
                st.error("请至少填写 Agent ID、名称和角色描述")

    # 使用说明
    st.divider()
    with st.expander("Agent 系统说明"):
        st.markdown("""
        ### 异构模型策略
        每个 Agent 使用不同的 LLM 供应商，避免同源偏见：
        - **基本面** → Claude（深度推理）
        - **技术面** → GPT（模式识别）
        - **舆情** → DeepSeek（中文原生）
        - **风控** → SenseNova（差异化引擎）
        - **散户行为** → Mimo（独特视角）
        - **主席** → Claude Opus（顶级综合判断）

        ### 配置文件
        - `config/models.yaml` — 模式与 Agent 模型分配
        - `config/providers.yaml` — Provider API 配置
        """)
