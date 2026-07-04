"""
Expert Team Builder UI 组件。

功能：
- 查看现有专家团配置
- 编辑团队成员和协作流程
- 创建新的专家团模板
- 专家团运行模式选择
"""

import streamlit as st
from typing import Dict, Any, List


def _get_teams() -> Dict[str, Any]:
    """获取所有专家团配置"""
    try:
        from backend.teams.team_loader import load_teams

        return load_teams()
    except Exception:
        return {}


def _get_team_names() -> List[Dict[str, str]]:
    """获取团队名称列表"""
    try:
        from backend.teams.team_loader import list_team_names

        return list_team_names()
    except Exception:
        return []


def _get_experts_config() -> Dict[str, Any]:
    """获取 experts.yaml 原始配置"""
    try:
        import yaml
        from project_paths import CONFIG_DIR

        p = CONFIG_DIR / "experts.yaml"
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def render():
    """渲染专家团编辑器页面"""
    st.header("👥 专家团编辑器")
    st.caption("配置和管理投研专家团，定义协作流程和投票规则")

    teams = _get_teams()

    # 现有专家团列表
    if teams:
        st.subheader("已配置的专家团")
        for team_id, team in teams.items():
            with st.expander(f"**{team.name}** (`{team.id}`)", expanded=False):
                st.markdown(f"**描述**: {team.description}")
                st.markdown(f"**成员数**: {len(team.members)}")

                if team.members:
                    members_data = []
                    for m in team.members:
                        members_data.append(
                            {
                                "角色": m.role,
                                "名称": m.name,
                                "供应商": m.provider,
                                "模型": m.model,
                                "状态": "✅" if m.enabled else "❌",
                            }
                        )
                    st.dataframe(members_data, use_container_width=True, hide_index=True)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("工作流", team.workflow)
                with col2:
                    st.metric("最大轮次", team.max_rounds)
                with col3:
                    st.metric("引用要求", "是" if team.require_citations else "否")
    else:
        st.info("未找到专家团配置。请检查 config/experts.yaml 文件。")

    # 专家团模板
    st.divider()
    st.subheader("专家团模板")
    st.markdown("从 config/agent_teams.yaml 加载预定义模板：")

    try:
        import yaml
        from project_paths import CONFIG_DIR

        p = CONFIG_DIR / "agent_teams.yaml"
        if p.exists():
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for team in raw.get("teams", []):
                with st.expander(f"📋 {team['name']} (`{team['id']}`)"):
                    st.markdown(f"**描述**: {team.get('description', '')}")
                    st.markdown(f"**工作流**: {team.get('workflow', 'parallel')}")
                    st.markdown("**Agent 列表**:")
                    for agent in team.get("agents", []):
                        st.markdown(f"- `{agent}`")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Critic", "启用" if team.get("enable_critic") else "禁用")
                    with col2:
                        st.metric("主席", "启用" if team.get("enable_chairman") else "禁用")
    except Exception as e:
        st.warning(f"加载模板失败: {e}")

    # 创建新专家团
    st.divider()
    st.subheader("创建新专家团")
    with st.form("new_team"):
        col1, col2 = st.columns(2)
        with col1:
            team_id = st.text_input("团队 ID", placeholder="my-team")
            team_name = st.text_input("团队名称", placeholder="我的投研团队")
        with col2:
            workflow = st.selectbox(
                "工作流模式",
                [
                    "parallel_then_debate",
                    "parallel",
                    "sequential",
                    "debate_only",
                ],
            )
            max_rounds = st.number_input("最大轮次", min_value=1, max_value=5, value=2)

        description = st.text_area("团队描述", placeholder="专注于...")

        st.markdown("**选择团队成员（Agent）：**")
        available_agents = [
            ("fundamental", "🏛️ 基本面分析师"),
            ("technical", "📐 技术分析师"),
            ("sentiment", "💬 舆情分析师"),
            ("risk", "⚠️ 风险控制师"),
            ("retail", "🏪 散户行为分析师"),
        ]
        selected_agents = []
        cols = st.columns(len(available_agents))
        for i, (key, name) in enumerate(available_agents):
            with cols[i]:
                if st.checkbox(name, key=f"team_agent_{key}"):
                    selected_agents.append(key)

        col1, col2 = st.columns(2)
        with col1:
            enable_critic = st.checkbox("启用 Critic 审稿", value=True)
        with col2:
            enable_chairman = st.checkbox("启用主席总结", value=True)

        if st.form_submit_button("创建专家团"):
            if team_id and team_name and selected_agents:
                st.success(f"专家团 '{team_name}' 配置已记录")
                st.json(
                    {
                        "id": team_id,
                        "name": team_name,
                        "description": description,
                        "workflow": workflow,
                        "max_rounds": max_rounds,
                        "agents": selected_agents,
                        "enable_critic": enable_critic,
                        "enable_chairman": enable_chairman,
                    }
                )
            else:
                st.error("请填写团队 ID、名称并至少选择一个 Agent")

    # 专家团运行模式说明
    st.divider()
    with st.expander("运行模式说明"):
        st.markdown("""
        | 模式 | 说明 |
        |------|------|
        | `parallel_then_debate` | 各专家独立分析 → 反方审查 → 主席综合 |
        | `parallel` | 各专家独立分析，直接汇总投票 |
        | `sequential` | 按顺序执行，前一个的输出作为后一个的输入 |
        | `debate_only` | 仅进行辩论/审查，不进行独立分析 |

        ### 专家输出结构
        每个专家输出标准化 JSON：
        ```json
        {
          "signal": "买入|卖出|观望",
          "confidence": 0-100,
          "reason": "核心理由",
          "evidence": [{"type": "...", "claim": "...", "data_date": "..."}],
          "invalid_if": "失效条件",
          "risks": ["风险1", "风险2"]
        }
        ```
        """)
