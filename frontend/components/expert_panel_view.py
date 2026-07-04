"""
专家圆桌视图组件(v0.7 新增)
- 召开圆桌按钮 → 5 卡片横排 → 点击展开 → 底部统计 → 纪要导出
- 复用 expert_panel.run_roundtable / export_md
- 自动入档:archive.save_roundtable
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from expert_panel import (  # noqa: E402
    export_md,
    load_default_team,
    team_to_editable_dict,
    editable_dict_to_team,
    run_team_roundtable,
)
import archive  # noqa: E402

# 热重载兼容：运行时获取函数，避免模块缓存导致别名不可见
save_roundtable = getattr(archive, "save_roundtable", None)


# 默认专家顺序兜底；自定义模式下使用 team.member_order
EXPERT_ORDER = ["buffett", "lynch", "chanlun", "macro", "risk_officer"]

CARD_STYLES = {
    "default": "#667eea",
    "value": "#b45309",
    "growth": "#16a34a",
    "technical": "#7c3aed",
    "risk": "#dc2626",
    "macro": "#0284c7",
}

# 决策颜色
ACTION_COLORS = {
    "买入": "#ef5350",
    "观望": "#ff9800",
    "减持": "#26a69a",
    "卖出": "#00897b",
}


def _action_color(action: str) -> str:
    return ACTION_COLORS.get(action, "#6b7280")


def _render_card(op, idx: int, symbol: str):
    """渲染单个专家卡片(顶部摘要,可折叠展开依据)"""
    if not op:
        return
    color = CARD_STYLES.get(getattr(op, "card_style", "default"), _action_color(op.action))
    fb_tag = ""
    if op.fallback_used and op.ok:
        fb_tag = "<span style='background:#fef3c7; color:#b45309; font-size:0.66rem; padding:1px 6px; border-radius:4px; margin-left:4px;'>降级模型</span>"
    elif not op.ok:
        fb_tag = "<span style='background:#fee2e2; color:#dc2626; font-size:0.66rem; padding:1px 6px; border-radius:4px; margin-left:4px;'>不可用</span>"

    sl_text = f"¥{op.stop_loss:.2f}" if op.stop_loss > 0 else "—"

    st.html(f"""
    <div style='background:white; border:1px solid #e5e7eb; border-top:4px solid {color};
                border-radius:10px; padding:12px 14px; height:240px; box-shadow:0 1px 3px rgba(0,0,0,0.05);
                display:flex; flex-direction:column;'>
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <div>
                <span style='font-size:1.4rem;'>{op.icon}</span>
                <span style='font-weight:700; font-size:0.95rem; color:#1f2937;'>{op.expert_name}</span>
            </div>
            {fb_tag}
        </div>
        <div style='font-size:0.74rem; color:#9ca3af; margin-top:2px;'>{op.style} · {op.vendor}/{op.model}</div>
        <div style='margin-top:10px; font-size:0.82rem; color:#374151; line-height:1.4;
                    overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;'>
            {op.view if op.ok else "该专家本次不可用,请稍后重试"}
        </div>
        <div style='flex-grow:1;'></div>
        <div style='display:flex; justify-content:space-between; align-items:flex-end; margin-top:8px;
                    padding-top:8px; border-top:1px solid #f3f4f6;'>
            <div>
                <div style='font-size:0.7rem; color:#9ca3af;'>操作</div>
                <div style='font-weight:700; color:{color}; font-size:0.92rem;'>{op.action}</div>
            </div>
            <div>
                <div style='font-size:0.7rem; color:#9ca3af;'>仓位</div>
                <div style='font-weight:700; color:#1f2937; font-size:0.92rem;'>{op.position}%</div>
            </div>
            <div>
                <div style='font-size:0.7rem; color:#9ca3af;'>止损</div>
                <div style='font-weight:700; color:#1f2937; font-size:0.86rem;'>{sl_text}</div>
            </div>
        </div>
    </div>
    """)

    with st.expander(f"查看 {op.expert_name} 完整观点与依据", expanded=False):
        if not op.ok:
            st.warning(f"该专家本次调用失败: {op.error_msg or '未知错误'}")
            return
        st.markdown(f"**核心观点**: {op.view}")
        if op.evidence:
            st.markdown("**关键依据**:")
            for ev in op.evidence:
                if isinstance(ev, dict):
                    claim = (ev.get("claim") or "").strip()
                    if not claim:
                        continue
                    etype = ev.get("type") or ""
                    date = ev.get("data_date") or ""
                    badges = []
                    if etype and etype != "other":
                        badges.append(f"`{etype}`")
                    if date:
                        badges.append(f"`{date}`")
                    suffix = (" " + " ".join(badges)) if badges else ""
                    st.markdown(f"- {claim}{suffix}")
                else:
                    text = str(ev).strip()
                    if text:
                        st.markdown(f"- {text}")
        else:
            st.caption("(无具体依据)")
        if getattr(op, "invalid_if", ""):
            st.markdown(f"**失效条件**: {op.invalid_if}")
        if getattr(op, "risks", None):
            st.markdown("**主要风险**:")
            for r in op.risks:
                st.markdown(f"- {r}")
        st.markdown(f"**操作建议**: {op.action} | **建议仓位**: {op.position}% | **止损位**: ¥{op.stop_loss:.2f}")
        st.caption(f"模型: {op.vendor} / `{op.model}` | 关注维度风格: {op.style}")


def _render_summary(summary: dict, elapsed: float):
    """底部统计"""
    buy = summary.get("buy", 0)
    hold = summary.get("hold", 0)
    reduce_ = summary.get("reduce", 0)
    sell = summary.get("sell", 0)
    avg_pos = summary.get("avg_position", 0)
    valid = summary.get("valid_count", 0)
    total = summary.get("total_count", 0)

    # 决策倾向
    counts = {"买入": buy, "观望": hold, "减持": reduce_, "卖出": sell}
    leader = max(counts, key=counts.get) if any(counts.values()) else "观望"
    leader_color = _action_color(leader)

    # 分歧度估算
    max(valid, 1)
    diversity = sum(c > 0 for c in counts.values())
    if diversity >= 3:
        gap_label, gap_color = "高", "#ef4444"
    elif diversity == 2:
        gap_label, gap_color = "中", "#f59e0b"
    else:
        gap_label, gap_color = "低", "#10b981"

    st.html(f"""
    <div style='background:linear-gradient(135deg,#fafbfc,#ffffff); border-radius:14px;
                padding:20px 24px; border:1px solid #e5e7eb; box-shadow:0 4px 12px rgba(0,0,0,0.05);'>
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <div>
                <div style='color:#6b7280; font-size:0.82rem;'>圆桌共识</div>
                <div style='font-size:1.5rem; font-weight:700; color:{leader_color}; margin-top:4px;'>
                    多数倾向{leader} · {counts[leader]}/{valid} 票
                </div>
            </div>
            <div style='text-align:right;'>
                <div style='font-size:0.85rem; color:#6b7280;'>
                    🔴 {buy} 买 · 🟡 {hold} 观 · 🟢 {reduce_} 减 · 🟢 {sell} 卖
                </div>
                <div style='font-size:1rem; font-weight:600; color:#1f2937; margin-top:4px;'>
                    平均建议仓位 {avg_pos:.1f}%
                </div>
                <div style='font-size:0.78rem; color:#9ca3af; margin-top:4px;'>
                    分歧度 <span style='color:{gap_color}; font-weight:600;'>{gap_label}</span>
                    · 有效 {valid}/{total} 位
                    · 用时 {elapsed:.1f}s
                </div>
            </div>
        </div>
    </div>
    """)


def _ensure_team_state(symbol: str) -> dict:
    key = f"expert_team_config_{symbol}"
    if key not in st.session_state:
        st.session_state[key] = team_to_editable_dict(load_default_team())
    return st.session_state[key]


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
        "focus_dims": "趋势, 资金, 风险",
        "stop_loss_style": "中等",
        "system_prompt": "你是一位自定义投资专家，请基于给定市场简报，从你的专业视角输出克制、可验证、可执行的投资观点。",
        "card_style": "default",
    }


def _render_team_editor(symbol: str) -> dict:
    data = _ensure_team_state(symbol)
    with st.expander("专家团人设与成员管理", expanded=False):
        st.caption("当前为会话内临时配置：可新增/复制/删除专家，刷新页面后如未导出会恢复默认。")
        t1, t2, t3 = st.columns([1.2, 1.2, 1])
        with t1:
            data["display_name"] = st.text_input(
                "专家团名称",
                value=data.get("display_name", "自定义专家团"),
                key=f"team_name_{symbol}",
            )
        with t2:
            data["avatar"] = st.text_input("团队头像", value=data.get("avatar", "🎓"), key=f"team_avatar_{symbol}")
        with t3:
            st.metric(
                "启用专家数",
                sum(1 for m in data.get("members", []) if m.get("enabled", True)),
            )

        a1, a2 = st.columns([1, 1])
        with a1:
            if st.button("新增专家", use_container_width=True, key=f"expert_add_{symbol}"):
                data.setdefault("members", []).append(_new_expert_template(len(data.get("members", [])) + 1))
                st.session_state[f"expert_team_config_{symbol}"] = data
                st.rerun()
        with a2:
            if st.button("恢复默认专家团", use_container_width=True, key=f"expert_reset_{symbol}"):
                st.session_state[f"expert_team_config_{symbol}"] = team_to_editable_dict(load_default_team())
                st.rerun()

        for i, member in enumerate(list(data.get("members", []))):
            title = f"{member.get('avatar', '🧠')} {member.get('name', member.get('id', '专家'))}"
            with st.expander(title, expanded=False):
                c0, c1, c2, c3 = st.columns([0.8, 1.2, 1.2, 1])
                with c0:
                    member["enabled"] = st.checkbox(
                        "启用",
                        value=member.get("enabled", True),
                        key=f"expert_enabled_{symbol}_{i}",
                    )
                    member["avatar"] = st.text_input(
                        "头像",
                        value=member.get("avatar", "🧠"),
                        key=f"expert_avatar_{symbol}_{i}",
                    )
                with c1:
                    member["id"] = st.text_input(
                        "ID",
                        value=member.get("id", f"expert_{i + 1}"),
                        key=f"expert_id_{symbol}_{i}",
                    )
                    member["name"] = st.text_input(
                        "名称",
                        value=member.get("name", "自定义专家"),
                        key=f"expert_name_{symbol}_{i}",
                    )
                with c2:
                    member["profession"] = st.text_input(
                        "职业/风格",
                        value=member.get("profession", "投资专家"),
                        key=f"expert_prof_{symbol}_{i}",
                    )
                    member["role"] = st.selectbox(
                        "角色",
                        ["member", "lead"],
                        index=1 if member.get("role") == "lead" else 0,
                        key=f"expert_role_{symbol}_{i}",
                    )
                with c3:
                    member["card_style"] = st.selectbox(
                        "卡片样式",
                        list(CARD_STYLES.keys()),
                        index=list(CARD_STYLES.keys()).index(member.get("card_style", "default"))
                        if member.get("card_style", "default") in CARD_STYLES
                        else 0,
                        key=f"expert_style_{symbol}_{i}",
                    )

                p1, p2 = st.columns([1, 1])
                with p1:
                    member["provider"] = st.text_input(
                        "Provider",
                        value=member.get("provider", "deepseek"),
                        key=f"expert_provider_{symbol}_{i}",
                    )
                with p2:
                    member["model"] = st.text_input(
                        "Model",
                        value=member.get("model", "deepseek-chat"),
                        key=f"expert_model_{symbol}_{i}",
                    )
                member["focus_dims"] = st.text_input(
                    "关注维度（逗号分隔）",
                    value=member.get("focus_dims", ""),
                    key=f"expert_focus_{symbol}_{i}",
                )
                member["stop_loss_style"] = st.text_input(
                    "止损风格",
                    value=member.get("stop_loss_style", "中等"),
                    key=f"expert_stop_{symbol}_{i}",
                )
                member["system_prompt"] = st.text_area(
                    "系统人设 Prompt",
                    value=member.get("system_prompt", ""),
                    height=120,
                    key=f"expert_prompt_{symbol}_{i}",
                )

                b1, b2 = st.columns([1, 1])
                with b1:
                    if st.button(
                        "复制该专家",
                        use_container_width=True,
                        key=f"expert_copy_{symbol}_{i}",
                    ):
                        clone = dict(member)
                        clone["id"] = f"{member.get('id', 'expert')}_copy"
                        clone["name"] = f"{member.get('name', '专家')} 副本"
                        data["members"].insert(i + 1, clone)
                        st.session_state[f"expert_team_config_{symbol}"] = data
                        st.rerun()
                with b2:
                    if st.button(
                        "删除该专家",
                        use_container_width=True,
                        key=f"expert_delete_{symbol}_{i}",
                    ):
                        data["members"].pop(i)
                        st.session_state[f"expert_team_config_{symbol}"] = data
                        st.rerun()
        st.session_state[f"expert_team_config_{symbol}"] = data
    return data


# ============== 主入口 ==============
def render(symbol: str, stock_name: str, stock_brief: str):
    """
    Tab8 完整渲染。
    - symbol/stock_name: 当前股票
    - stock_brief: 通过 llm_agents.build_market_brief() 拼接好的市场简报
    """
    st.markdown("#### 🎓 专家团圆桌")
    team_data = _ensure_team_state(symbol)
    st.caption("完整专家人设、数量、模型和 API Key 设置已集中到「AI 设置中心」。这里保留轻量查看和运行入口。")
    team_cfg = editable_dict_to_team(team_data)
    active_count = sum(1 for m in team_cfg.members if getattr(m, "enabled", True))
    st.caption(f"{active_count} 位可自定义风格化投顾并行输出三段式 JSON，与 Tab2 的职能型 Agent 互为补充。")

    if not symbol or not stock_name:
        st.info("请先在侧边栏选择股票")
        return

    cache_key = f"roundtable_{symbol}"
    progress_key = "roundtable_in_progress"

    # ---- 顶部操作栏 ----
    cb1, cb2, cb3 = st.columns([2, 2, 5])
    with cb1:
        run_btn = st.button(
            "🚀 召开圆桌",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.get(progress_key, False),
            key=f"rt_run_{symbol}",
        )
    with cb2:
        clear_btn = st.button(
            "🗑 清空结果",
            use_container_width=True,
            key=f"rt_clear_{symbol}",
        )
    with cb3:
        st.caption(f"目标股票: **{stock_name}** ({symbol}) · {active_count} 路并行，预计 8-30 秒完成")

    if clear_btn:
        st.session_state.pop(cache_key, None)
        st.rerun()

    # ---- 召开圆桌 ----
    if run_btn:
        st.session_state[progress_key] = True
        try:
            with st.spinner(f"{active_count} 位专家并行思考中..."):
                global_ai_settings = st.session_state.get("ai_global_settings", {})
                result = run_team_roundtable(
                    team_cfg,
                    stock_brief,
                    stock_name,
                    global_ai_settings=global_ai_settings,
                )
                st.session_state[cache_key] = result
        except Exception as e:
            st.error(f"圆桌调用失败: {e}")
        finally:
            st.session_state[progress_key] = False
        st.rerun()

    # ---- 展示结果 ----
    result = st.session_state.get(cache_key)
    if not result:
        st.info(f"👆 点击「召开圆桌」启动 {active_count} 位专家并行分析。")
        with st.expander("查看当前启用专家的人设介绍", expanded=False):
            for m in team_cfg.members:
                if not getattr(m, "enabled", True):
                    continue
                dims = "、".join(m.focus_dims or []) or "综合判断"
                st.markdown(
                    f"- **{m.avatar} {m.display_name}（{m.profession}）**: 关注 {dims}，止损风格：{m.stop_loss_style}"
                )
        return

    opinions = result.get("opinions", {})
    summary = result.get("summary", {})
    elapsed = result.get("elapsed", 0)

    order = (
        result.get("member_order") or [m.id for m in team_cfg.members if getattr(m, "enabled", True)] or EXPERT_ORDER
    )
    cols_per_row = min(3, max(1, len(order)))
    for row_start in range(0, len(order), cols_per_row):
        row_keys = order[row_start : row_start + cols_per_row]
        cols = st.columns(len(row_keys))
        for i, key in enumerate(row_keys):
            op = opinions.get(key)
            with cols[i]:
                _render_card(op, row_start + i, symbol)

    st.markdown(
        '<hr style="margin:1.5rem 0; border:none; height:1px; '
        'background:linear-gradient(90deg,transparent,#e5e7eb,transparent);" />',
        unsafe_allow_html=True,
    )

    _render_summary(summary, elapsed)

    # ---- 导出纪要 ----
    st.markdown("")
    ec1, ec2, ec3 = st.columns([2, 2, 5])
    with ec1:
        if st.button("📥 导出纪要", use_container_width=True, key=f"rt_export_{symbol}"):
            try:
                md_text = export_md(opinions, summary, stock_name, symbol)
                arc = save_roundtable(stock_name, symbol, opinions, summary, md_text, dedupe_minutes=1)
                st.session_state[f"rt_last_archive_{symbol}"] = arc
            except Exception as e:
                st.error(f"导出失败: {e}")

    arc_info = st.session_state.get(f"rt_last_archive_{symbol}")
    if arc_info:
        if arc_info.get("saved"):
            st.success(f"📚 纪要已存档: `{arc_info['path']}`,可在「研究存档」Tab 检索")
        else:
            st.caption(f"📚 {arc_info.get('reason', '已跳过')}")
        # 立刻提供下载
        try:
            md_text = export_md(opinions, summary, stock_name, symbol)
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            st.download_button(
                label="下载 Markdown 纪要",
                data=md_text.encode("utf-8"),
                file_name=f"roundtable_{symbol}_{ts}.md",
                mime="text/markdown",
                key=f"rt_dl_{symbol}",
            )
        except Exception:
            pass
