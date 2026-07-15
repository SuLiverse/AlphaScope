"""研究记忆 Post-mortem — 把历史结论偏差注入简报 (P1)。

从 research_memory 读取同标的历史快照,生成一段**确定性**「自我复盘」提示,
供 Agent 简报使用:提醒模型关注近期信号转折与置信度漂移,降低重复偏见。

纯函数 + 失败安全,不触网、不新增 LLM。
"""

from __future__ import annotations


def build_post_mortem_brief(symbol: str, limit: int = 8) -> str:
    """返回可拼进市场简报的文本;无历史则空串。永不抛出。"""
    try:
        if not symbol or not str(symbol).strip():
            return ""
        from backend.quant import research_memory

        timeline = research_memory.get_timeline(str(symbol).strip(), limit=max(3, min(limit, 30)))
        snaps = timeline.get("snapshots") or []
        if not snaps:
            return ""
        summary = timeline.get("summary") or research_memory.summarize_history(snaps)
        changes = timeline.get("changes") or []
        latest = snaps[-1] if snaps else {}
        lines = [
            "",
            "【研究记忆 · 自我复盘 (Post-mortem)】",
            f"- 历史快照: {summary.get('count', 0)} 次 · 最新信号 {summary.get('latest_signal') or '—'} "
            f"(置信 {float(summary.get('latest_confidence') or 0):.0f})",
            f"- 信号分布: {summary.get('signal_distribution') or {}}",
            f"- 转折次数: {summary.get('change_count', 0)} · 均置信 {float(summary.get('avg_confidence') or 0):.0f}",
        ]
        for ch in changes[-3:] if changes else []:
            if not isinstance(ch, dict):
                continue
            lines.append(
                f"- 转折: {ch.get('from')}→{ch.get('to')} ({ch.get('direction') or ''}) "
                f"@ {str(ch.get('to_date') or '')[:10]}"
            )
        if latest.get("risk_vetoed"):
            lines.append("- 最近一次曾触发风控否决,请优先复核风险维度。")
        lines.append(
            "- 约束: 复盘仅描述**过去研究轨迹**,不得编造未发生的历史结论;"
            "若当前数据与历史判断冲突,须显式说明冲突点并下调过度自信。"
        )
        lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""
