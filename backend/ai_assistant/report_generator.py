"""AI 对话报告生成器

将对话历史和分析结果导出为 Markdown 研究报告。
"""

from __future__ import annotations

from typing import List

from .compliance import wrap_with_disclaimer


def generate_report(
    conversation: dict,
    messages: List[dict],
    include_evidence: bool = True,
) -> str:
    """生成完整 Markdown 研究报告

    结构：
    - 标题：对话标题、日期、股票、模式、模型
    - 对话记录
    - 证据链（如有）
    - 合规免责声明
    """
    lines = []

    # 标题
    title = conversation.get("title", "AI 分析对话")
    stock_symbol = conversation.get("stock_symbol", "")
    stock_name = conversation.get("stock_name", "")
    mode = conversation.get("mode", "free")
    provider = conversation.get("provider", "")
    model = conversation.get("model", "")
    created_at = conversation.get("created_at", "")

    mode_labels = {
        "free": "自由问答",
        "standard": "标准分析",
        "deep": "深度分析",
        "expert": "专家团圆桌",
    }

    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 创建时间: {created_at}  ")
    if stock_symbol:
        lines.append(f"> 标的: {stock_name}({stock_symbol})  ")
    lines.append(f"> 分析模式: {mode_labels.get(mode, mode)}  ")
    lines.append(f"> 模型: {provider} / `{model}`  ")
    lines.append(f"> 对话轮次: {sum(1 for m in messages if m.get('role') == 'user')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 对话记录
    lines.append("## 对话记录")
    lines.append("")

    all_evidence = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        meta = msg.get("metadata", {})
        if isinstance(meta, str):
            import json

            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        if role == "system":
            continue
        elif role == "user":
            lines.append(f"### 用户  `{timestamp}`")
            lines.append("")
            lines.append(content)
            lines.append("")
        elif role == "assistant":
            msg_mode = meta.get("mode", mode)
            mode_badge = mode_labels.get(msg_mode, msg_mode)
            lines.append(f"### 助手 [{mode_badge}]  `{timestamp}`")
            lines.append("")
            lines.append(content)
            lines.append("")
            # 收集证据
            if include_evidence and meta.get("evidence"):
                all_evidence.extend(meta["evidence"])
        elif role == "analysis":
            lines.append(f"### 分析结果  `{timestamp}`")
            lines.append("")
            lines.append(content)
            lines.append("")
            if include_evidence and meta.get("evidence"):
                all_evidence.extend(meta["evidence"])

        lines.append("---")
        lines.append("")

    # 证据链（结构化）
    if all_evidence:
        try:
            from backend.quality.evidence_chain import build_evidence_chain

            chain = build_evidence_chain(all_evidence)
            bundles = chain.get("bundles", [])

            if bundles:
                lines.append("## 证据链")
                lines.append("")

                for i, bundle in enumerate(bundles, 1):
                    claim = bundle["claim"]
                    conf = bundle["confidence"]
                    src_count = bundle["source_count"]
                    trust = bundle["trust_score"]
                    decay = bundle["decay_factor"]

                    lines.append(f"### {i}. {claim}")
                    lines.append(
                        f"> 置信度: {conf:.0%} | 来源数: {src_count} | 可信度: {trust:.0%} | 时效性: {decay:.0%}"
                    )
                    lines.append("")

                    for ev in bundle.get("evidence", []):
                        ev_type = ev.get("type", ev.get("evidence_type", ""))
                        source = ev.get("source", "")
                        data_date = ev.get("data_date", "")
                        lines.append(f"- [{ev_type}] {ev.get('claim', ev.get('title', ''))}")
                        if source:
                            lines.append(f"  来源: {source}")
                        if data_date:
                            lines.append(f"  日期: {data_date}")

                    # 矛盾标记
                    for c in bundle.get("contradictions", []):
                        lines.append(f"  > ⚠️ {c}")

                    lines.append("")

            # 全局矛盾
            contradictions = chain.get("contradictions", [])
            if contradictions:
                lines.append("### 证据矛盾")
                lines.append("")
                for c in contradictions:
                    lines.append(f"- ⚠️ {c}")
                lines.append("")

            # 证据缺失
            missing = chain.get("missing_evidence", [])
            if missing:
                lines.append("### 证据缺失警告")
                lines.append("")
                for m in missing:
                    lines.append(f"- ❗ {m}")
                lines.append("")

            # 覆盖率
            coverage = chain.get("coverage", 1.0)
            overall_conf = chain.get("overall_confidence", 0.0)
            lines.append(f"> 证据覆盖率: {coverage:.0%} | 综合置信度: {overall_conf:.0%}")
            lines.append("")

        except Exception:
            # 降级：扁平渲染
            lines.append("## 证据链")
            lines.append("")
            for i, ev in enumerate(all_evidence, 1):
                claim = ev.get("claim", ev.get("title", ""))
                source = ev.get("source", ev.get("source_name", ""))
                ev_type = ev.get("type", ev.get("evidence_type", ""))
                conf = ev.get("confidence", "")
                lines.append(f"{i}. **[{ev_type}]** {claim}")
                if source:
                    lines.append(f"   - 来源: {source}")
                if conf:
                    lines.append(f"   - 置信度: {conf}")
                lines.append("")

    # 免责声明
    mode_val = conversation.get("mode", "free")
    full_text = "\n".join(lines)
    full_text = wrap_with_disclaimer(full_text, mode_val)

    return full_text


def generate_summary(messages: List[dict]) -> str:
    """从对话消息中提取关键结论摘要"""
    summaries = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        meta = msg.get("metadata", {})
        if isinstance(meta, str):
            import json

            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        if role == "assistant" and meta.get("mode") in (
            "standard",
            "deep",
            "expert",
        ):
            # 提取前 200 字作为摘要
            summary = content[:200].strip()
            if len(content) > 200:
                summary += "..."
            summaries.append(summary)

    if not summaries:
        return "暂无分析摘要"

    return "\n\n".join(f"- {s}" for s in summaries)


def generate_report_with_gate(
    conversation: dict,
    messages: List[dict],
    include_evidence: bool = True,
    critic: dict | None = None,
) -> dict:
    """生成报告并运行质量门控(确定性 pass/fail)。

    返回 ``{"report": <markdown>, "gate": <run_gate 结果>}``。
    ``gate["passed"] is False`` 表示存在 critical 问题,调用方应据此拒绝
    或标红发布(见 :mod:`backend.quality.report_gate`)。不改变
    :func:`generate_report` 的既有行为。
    """
    report = generate_report(conversation, messages, include_evidence)

    # 复用消息中的 evidence 构造证据链作为门控输入(失败则降级为仅正文检查)
    evidence_chain = None
    try:
        all_evidence: list = []
        for msg in messages:
            meta = msg.get("metadata", {})
            if isinstance(meta, str):
                import json

                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict) and meta.get("evidence"):
                all_evidence.extend(meta["evidence"])
        if all_evidence:
            from backend.quality.evidence_chain import build_evidence_chain

            evidence_chain = build_evidence_chain(all_evidence)
    except Exception:
        evidence_chain = None

    from backend.quality.report_gate import run_gate

    gate = run_gate(
        report,
        evidence_chain=evidence_chain,
        critic=critic,
        mode=conversation.get("mode"),
    )
    return {"report": report, "gate": gate}
