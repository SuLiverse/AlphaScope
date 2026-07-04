import os
import sys
from copy import deepcopy
from pathlib import Path

import streamlit as st

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_chat import fetch_model_list  # noqa: E402
from expert_panel import load_default_team, team_to_editable_dict  # noqa: E402
from llm_agents import get_default_agent_configs  # noqa: E402


AGENT_CARD_STYLES = ["default", "value", "growth", "technical", "risk", "macro"]
PROVIDER_OPTIONS = ["deepseek", "kimi", "claude", "gpt", "mimo", "sensenova", "custom"]


def get_global_ai_settings() -> dict:
    if "ai_global_settings" not in st.session_state:
        st.session_state["ai_global_settings"] = {
            "use_unified_key": True,
            "provider": os.getenv("AI_CHAT_PROVIDER", "deepseek"),
            "model": "deepseek-chat",
            "base_url": "",
            "api_key": "",
            "custom_models": [],
        }
    return st.session_state["ai_global_settings"]


def ensure_agent_config_state(symbol: str) -> list:
    key = f"agent_config_{symbol}"
    if key not in st.session_state:
        configs = get_default_agent_configs()
        for cfg in configs:
            cfg.setdefault("inherit_global_key", True)
            cfg.setdefault("base_url", "")
            cfg.setdefault("api_key", "")
        st.session_state[key] = configs
    else:
        for cfg in st.session_state[key]:
            cfg.setdefault("inherit_global_key", True)
            cfg.setdefault("base_url", "")
            cfg.setdefault("api_key", "")
    return st.session_state[key]


def ensure_expert_team_state(symbol: str) -> dict:
    key = f"expert_team_config_{symbol}"
    if key not in st.session_state:
        data = team_to_editable_dict(load_default_team())
        for member in data.get("members", []):
            member.setdefault("inherit_global_key", True)
            member.setdefault("base_url", "")
            member.setdefault("api_key", "")
        st.session_state[key] = data
    else:
        for member in st.session_state[key].get("members", []):
            member.setdefault("inherit_global_key", True)
            member.setdefault("base_url", "")
            member.setdefault("api_key", "")
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
        "base_url": "",
        "api_key": "",
        "inherit_global_key": True,
        "enabled": True,
        "card_style": "default",
    }


def _new_expert_template(idx: int) -> dict:
    return {
        "id": f"custom_expert_{idx}",
        "enabled": True,
        "name": f"自定义专家 {idx}",
        "profession": "自定义投资专家",
        "avatar": "🧠",
        "role": "member",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "",
        "api_key": "",
        "inherit_global_key": True,
        "focus_dims": "趋势, 资金, 风险",
        "stop_loss_style": "中等",
        "system_prompt": "你是一位自定义投资专家，请基于给定市场简报，从你的专业视角输出克制、可验证、可执行的投资观点。",
        "card_style": "default",
    }


def _render_global_settings() -> dict:
    settings = get_global_ai_settings()
    st.markdown("### 统一 AI 连接设置")
    st.caption(
        "统一 Key/Base URL 会被 AI 咨询、Agent 和专家团继承；单个成员取消继承后可单独设置。Key 仅保存在当前会话内存。"
    )
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        settings["use_unified_key"] = st.checkbox(
            "启用统一 API Key",
            value=settings.get("use_unified_key", True),
            key="ai_global_use_unified",
        )
        settings["provider"] = st.selectbox(
            "默认 Provider",
            PROVIDER_OPTIONS,
            index=PROVIDER_OPTIONS.index(settings.get("provider", "deepseek"))
            if settings.get("provider", "deepseek") in PROVIDER_OPTIONS
            else 0,
            key="ai_global_provider",
        )
    with c2:
        settings["model"] = st.text_input(
            "默认模型",
            value=settings.get("model", "deepseek-chat"),
            key="ai_global_model",
        )
        settings["base_url"] = st.text_input(
            "统一 Base URL（custom/OpenAI 兼容）",
            value=settings.get("base_url", ""),
            key="ai_global_base_url",
            placeholder="https://api.example.com/v1",
        )
    with c3:
        settings["api_key"] = st.text_input(
            "统一 API Key",
            value=settings.get("api_key", ""),
            type="password",
            key="ai_global_api_key",
        )
        if st.button("获取统一模型列表", use_container_width=True, key="ai_global_fetch_models"):
            try:
                models = fetch_model_list(settings.get("base_url", ""), settings.get("api_key", ""))
                settings["custom_models"] = models
                if models:
                    settings["model"] = models[0]
                st.session_state["ai_global_settings"] = settings
                st.success(f"已获取 {len(models)} 个模型。")
                st.rerun()
            except Exception as e:
                st.error(f"获取模型列表失败: {str(e)[:220]}")
    if settings.get("custom_models"):
        selected = st.selectbox(
            "统一模型列表",
            settings["custom_models"],
            index=settings["custom_models"].index(settings.get("model"))
            if settings.get("model") in settings["custom_models"]
            else 0,
            key="ai_global_model_select",
        )
        settings["model"] = selected
    st.session_state["ai_global_settings"] = settings
    return settings


def _render_agent_settings(symbol: str) -> list:
    configs = ensure_agent_config_state(symbol)
    st.markdown("### Agent 团队设置")
    a1, a2, a3 = st.columns([1, 1, 1])
    with a1:
        st.metric("启用 Agent", sum(1 for c in configs if c.get("enabled", True)))
    with a2:
        if st.button("新增 Agent", use_container_width=True, key=f"settings_agent_add_{symbol}"):
            configs.append(_new_agent_template(len(configs) + 1))
            st.session_state[f"agent_config_{symbol}"] = configs
            st.rerun()
    with a3:
        if st.button(
            "恢复默认 Agent",
            use_container_width=True,
            key=f"settings_agent_reset_{symbol}",
        ):
            st.session_state[f"agent_config_{symbol}"] = get_default_agent_configs()
            st.rerun()

    for i, cfg in enumerate(list(configs)):
        with st.expander(cfg.get("name", cfg.get("key", "Agent")), expanded=False):
            c0, c1, c2, c3 = st.columns([0.8, 1.2, 1.2, 1])
            with c0:
                cfg["enabled"] = st.checkbox(
                    "启用",
                    value=cfg.get("enabled", True),
                    key=f"settings_agent_enabled_{symbol}_{i}",
                )
                cfg["avatar"] = st.text_input(
                    "头像",
                    value=cfg.get("avatar", "🤖"),
                    key=f"settings_agent_avatar_{symbol}_{i}",
                )
            with c1:
                cfg["key"] = st.text_input(
                    "Key",
                    value=cfg.get("key", f"agent_{i + 1}"),
                    key=f"settings_agent_key_{symbol}_{i}",
                )
                cfg["name"] = st.text_input(
                    "名称",
                    value=cfg.get("name", "自定义 Agent"),
                    key=f"settings_agent_name_{symbol}_{i}",
                )
            with c2:
                cfg["inherit_global_key"] = st.checkbox(
                    "继承统一 AI 设置",
                    value=cfg.get("inherit_global_key", True),
                    key=f"settings_agent_inherit_{symbol}_{i}",
                )
                cfg["card_style"] = st.selectbox(
                    "卡片样式",
                    AGENT_CARD_STYLES,
                    index=AGENT_CARD_STYLES.index(cfg.get("card_style", "default"))
                    if cfg.get("card_style", "default") in AGENT_CARD_STYLES
                    else 0,
                    key=f"settings_agent_style_{symbol}_{i}",
                )
            with c3:
                cfg["provider"] = st.text_input(
                    "Provider",
                    value=cfg.get("provider", "deepseek"),
                    key=f"settings_agent_provider_{symbol}_{i}",
                    disabled=cfg.get("inherit_global_key", True),
                )
                cfg["model"] = st.text_input(
                    "Model",
                    value=cfg.get("model", "deepseek-chat"),
                    key=f"settings_agent_model_{symbol}_{i}",
                    disabled=cfg.get("inherit_global_key", True),
                )
            if not cfg.get("inherit_global_key", True):
                k1, k2 = st.columns([1, 1])
                with k1:
                    cfg["base_url"] = st.text_input(
                        "单独 Base URL",
                        value=cfg.get("base_url", ""),
                        key=f"settings_agent_base_url_{symbol}_{i}",
                    )
                with k2:
                    cfg["api_key"] = st.text_input(
                        "单独 API Key",
                        value=cfg.get("api_key", ""),
                        type="password",
                        key=f"settings_agent_api_key_{symbol}_{i}",
                    )
            cfg["role"] = st.text_area(
                "系统人设",
                value=cfg.get("role", ""),
                height=80,
                key=f"settings_agent_role_{symbol}_{i}",
            )
            cfg["instruction"] = st.text_area(
                "分析指令",
                value=cfg.get("instruction", ""),
                height=100,
                key=f"settings_agent_instruction_{symbol}_{i}",
            )
            b1, b2 = st.columns([1, 1])
            with b1:
                if st.button(
                    "复制该 Agent",
                    use_container_width=True,
                    key=f"settings_agent_copy_{symbol}_{i}",
                ):
                    clone = deepcopy(cfg)
                    clone["key"] = f"{cfg.get('key', 'agent')}_copy"
                    clone["name"] = f"{cfg.get('name', 'Agent')} 副本"
                    configs.insert(i + 1, clone)
                    st.session_state[f"agent_config_{symbol}"] = configs
                    st.rerun()
            with b2:
                if st.button(
                    "删除该 Agent",
                    use_container_width=True,
                    key=f"settings_agent_delete_{symbol}_{i}",
                ):
                    configs.pop(i)
                    st.session_state[f"agent_config_{symbol}"] = configs
                    st.rerun()
    st.session_state[f"agent_config_{symbol}"] = configs
    return configs


def _render_expert_settings(symbol: str) -> dict:
    data = ensure_expert_team_state(symbol)
    st.markdown("### 专家团设置")
    t1, t2, t3 = st.columns([1.2, 1.2, 1])
    with t1:
        data["display_name"] = st.text_input(
            "专家团名称",
            value=data.get("display_name", "自定义专家团"),
            key=f"settings_team_name_{symbol}",
        )
    with t2:
        data["avatar"] = st.text_input(
            "团队头像",
            value=data.get("avatar", "🎓"),
            key=f"settings_team_avatar_{symbol}",
        )
    with t3:
        st.metric(
            "启用专家",
            sum(1 for m in data.get("members", []) if m.get("enabled", True)),
        )
    a1, a2 = st.columns([1, 1])
    with a1:
        if st.button("新增专家", use_container_width=True, key=f"settings_expert_add_{symbol}"):
            data.setdefault("members", []).append(_new_expert_template(len(data.get("members", [])) + 1))
            st.session_state[f"expert_team_config_{symbol}"] = data
            st.rerun()
    with a2:
        if st.button(
            "恢复默认专家团",
            use_container_width=True,
            key=f"settings_expert_reset_{symbol}",
        ):
            st.session_state[f"expert_team_config_{symbol}"] = team_to_editable_dict(load_default_team())
            st.rerun()

    for i, member in enumerate(list(data.get("members", []))):
        with st.expander(
            f"{member.get('avatar', '🧠')} {member.get('name', member.get('id', '专家'))}",
            expanded=False,
        ):
            c0, c1, c2, c3 = st.columns([0.8, 1.2, 1.2, 1])
            with c0:
                member["enabled"] = st.checkbox(
                    "启用",
                    value=member.get("enabled", True),
                    key=f"settings_expert_enabled_{symbol}_{i}",
                )
                member["avatar"] = st.text_input(
                    "头像",
                    value=member.get("avatar", "🧠"),
                    key=f"settings_expert_avatar_{symbol}_{i}",
                )
            with c1:
                member["id"] = st.text_input(
                    "ID",
                    value=member.get("id", f"expert_{i + 1}"),
                    key=f"settings_expert_id_{symbol}_{i}",
                )
                member["name"] = st.text_input(
                    "名称",
                    value=member.get("name", "自定义专家"),
                    key=f"settings_expert_name_{symbol}_{i}",
                )
            with c2:
                member["profession"] = st.text_input(
                    "职业/风格",
                    value=member.get("profession", "投资专家"),
                    key=f"settings_expert_prof_{symbol}_{i}",
                )
                member["inherit_global_key"] = st.checkbox(
                    "继承统一 AI 设置",
                    value=member.get("inherit_global_key", True),
                    key=f"settings_expert_inherit_{symbol}_{i}",
                )
            with c3:
                member["role"] = st.selectbox(
                    "角色",
                    ["member", "lead"],
                    index=1 if member.get("role") == "lead" else 0,
                    key=f"settings_expert_role_{symbol}_{i}",
                )
                member["card_style"] = st.selectbox(
                    "卡片样式",
                    AGENT_CARD_STYLES,
                    index=AGENT_CARD_STYLES.index(member.get("card_style", "default"))
                    if member.get("card_style", "default") in AGENT_CARD_STYLES
                    else 0,
                    key=f"settings_expert_style_{symbol}_{i}",
                )
            p1, p2 = st.columns([1, 1])
            with p1:
                member["provider"] = st.text_input(
                    "Provider",
                    value=member.get("provider", "deepseek"),
                    key=f"settings_expert_provider_{symbol}_{i}",
                    disabled=member.get("inherit_global_key", True),
                )
                if not member.get("inherit_global_key", True):
                    member["base_url"] = st.text_input(
                        "单独 Base URL",
                        value=member.get("base_url", ""),
                        key=f"settings_expert_base_url_{symbol}_{i}",
                    )
            with p2:
                member["model"] = st.text_input(
                    "Model",
                    value=member.get("model", "deepseek-chat"),
                    key=f"settings_expert_model_{symbol}_{i}",
                    disabled=member.get("inherit_global_key", True),
                )
                if not member.get("inherit_global_key", True):
                    member["api_key"] = st.text_input(
                        "单独 API Key",
                        value=member.get("api_key", ""),
                        type="password",
                        key=f"settings_expert_api_key_{symbol}_{i}",
                    )
            member["focus_dims"] = st.text_input(
                "关注维度（逗号分隔）",
                value=member.get("focus_dims", ""),
                key=f"settings_expert_focus_{symbol}_{i}",
            )
            member["stop_loss_style"] = st.text_input(
                "止损风格",
                value=member.get("stop_loss_style", "中等"),
                key=f"settings_expert_stop_{symbol}_{i}",
            )
            member["system_prompt"] = st.text_area(
                "系统人设 Prompt",
                value=member.get("system_prompt", ""),
                height=100,
                key=f"settings_expert_prompt_{symbol}_{i}",
            )
            b1, b2 = st.columns([1, 1])
            with b1:
                if st.button(
                    "复制该专家",
                    use_container_width=True,
                    key=f"settings_expert_copy_{symbol}_{i}",
                ):
                    clone = deepcopy(member)
                    clone["id"] = f"{member.get('id', 'expert')}_copy"
                    clone["name"] = f"{member.get('name', '专家')} 副本"
                    data["members"].insert(i + 1, clone)
                    st.session_state[f"expert_team_config_{symbol}"] = data
                    st.rerun()
            with b2:
                if st.button(
                    "删除该专家",
                    use_container_width=True,
                    key=f"settings_expert_delete_{symbol}_{i}",
                ):
                    data["members"].pop(i)
                    st.session_state[f"expert_team_config_{symbol}"] = data
                    st.rerun()
    st.session_state[f"expert_team_config_{symbol}"] = data
    return data


def render_ai_settings_center(symbol: str):
    st.markdown("## ⚙️ AI 设置中心")
    st.info(
        "这里集中管理 AI 咨询、Agent 团队、专家团的模型、人设和 API 连接。当前版本默认只保存在会话内存，不落盘。",
        icon="🤖",
    )
    settings = _render_global_settings()
    st.markdown("---")
    tab_agents, tab_experts = st.tabs(["Agent 团队", "专家团"])
    with tab_agents:
        _render_agent_settings(symbol)
    with tab_experts:
        _render_expert_settings(symbol)
    return settings
