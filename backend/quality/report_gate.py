"""研报质量「机械门控」— 确定性 pass/fail，critical 不清零则拒绝发布。

**为什么存在**:AlphaScope 已有 LLM 审稿(:mod:`backend.critic`)与证据链评分
(:mod:`backend.quality.evidence_chain`)。但这些是"软"信号。本模块提供**确定性**、
程序化的发布门控:跑一组检查 → 产出 critical/warning/info issues(各带 ``suggested_fix``)
→ ``critical_count > 0`` 即判 **不可发布**。

设计模式移植自 UZI-Skill ``scripts/lib/self_review.py`` (MIT)；检查项为 AlphaScope 自有
(贴合 evidence_chain / critic / 报告正文)。见 ``docs/uzi-integration/ATTRIBUTION.md``。

用法::

    from backend.quality.report_gate import run_gate
    result = run_gate(report_text, evidence_chain=ec, critic=cr, mode="deep")
    if not result["passed"]:
        ...  # 拒绝发布，按 issues[].suggested_fix 修复后重跑
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Issue:
    severity: str  # critical / warning / info
    category: str  # fluff / placeholder / evidence / contradiction / compliance / structure
    issue: str  # 人读问题描述
    evidence: str = ""  # 触发的具体内容
    suggested_fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ReportBlockedError(RuntimeError):
    """critical issue 未清零时禁止发布报告。"""

    def __init__(self, result: dict):
        self.result = result
        crit = result.get("critical_count", 0)
        super().__init__(f"报告被门控拦截:{crit} 个 critical 问题未解决")


# ── 阈值/词表 ──────────────────────────────────────────────────
COVERAGE_WARN = 0.60  # 证据覆盖率低于此 → warning
COVERAGE_CRIT = 0.40  # 低于此 → critical
CONFIDENCE_WARN = 0.30  # 综合置信度低于此 → warning
MIN_REPORT_CHARS = 80

# 空泛废话:出现即视为质量缺陷(经典三件套判 critical)
FLUFF_CRITICAL = ["基本面良好", "前景广阔", "值得关注"]
FLUFF_WARNING = ["值得期待", "表现良好", "稳健增长", "前景光明", "潜力巨大", "建议关注"]
PLACEHOLDER_MARKERS = [
    "[TODO]",
    "TODO",
    "占位",
    "PLACEHOLDER",
    "[未实现]",
    "待补充",
    "xxx",
    "XXX",
]
CONTRADICTION_HINTS = ["矛盾", "分歧", "冲突", "背离", "不一致"]
DISCLAIMER_HINTS = ["风险提示", "不构成", "投资建议", "仅供参考"]


def _ctx(report_text, evidence_chain, critic, mode) -> dict:
    return {
        "text": report_text or "",
        "ec": evidence_chain or {},
        "critic": critic or {},
        "mode": mode or "",
    }


# ── 检查函数:接收 ctx，返回 list[Issue] ─────────────────────────


def check_empty_report(ctx: dict) -> list[Issue]:
    text = ctx["text"]
    if len(text.strip()) < MIN_REPORT_CHARS:
        return [
            Issue(
                severity="critical",
                category="structure",
                issue=f"报告正文过短(<{MIN_REPORT_CHARS} 字符),疑似生成失败",
                evidence=f"len={len(text.strip())}",
                suggested_fix="检查报告生成链路是否异常,重跑生成",
            )
        ]
    return []


def check_placeholder(ctx: dict) -> list[Issue]:
    text = ctx["text"]
    issues = []
    for marker in PLACEHOLDER_MARKERS:
        if marker in text:
            issues.append(
                Issue(
                    severity="critical",
                    category="placeholder",
                    issue=f"报告含占位符 {marker!r}",
                    evidence=_snippet(text, marker),
                    suggested_fix=f"用真实内容替换 {marker!r}",
                )
            )
    return issues


def check_fluff_phrases(ctx: dict) -> list[Issue]:
    text = ctx["text"]
    issues = []
    for ph in FLUFF_CRITICAL:
        if ph in text:
            issues.append(
                Issue(
                    severity="critical",
                    category="fluff",
                    issue=f"含空泛结论 {ph!r}(必须用带数字的定量判断替换)",
                    evidence=_snippet(text, ph),
                    suggested_fix=f"把 {ph!r} 改写成可证伪的定量金句(含具体数字/估值/对比)",
                )
            )
    for ph in FLUFF_WARNING:
        if ph in text:
            issues.append(
                Issue(
                    severity="warning",
                    category="fluff",
                    issue=f"含模糊表述 {ph!r}",
                    evidence=_snippet(text, ph),
                    suggested_fix=f"尽量用数据支撑 {ph!r} 这一判断",
                )
            )
    return issues


def check_evidence_coverage(ctx: dict) -> list[Issue]:
    ec = ctx["ec"]
    if "coverage" not in ec:
        return []
    cov = float(ec.get("coverage") or 0)
    if cov < COVERAGE_CRIT:
        return [
            Issue(
                severity="critical",
                category="evidence",
                issue=f"证据覆盖率仅 {cov * 100:.0f}%(< {COVERAGE_CRIT * 100:.0f}% 不应发布)",
                evidence=f"coverage={cov}",
                suggested_fix="为缺证据的关键结论补充来源(WebSearch / 权威数据源)后重跑",
            )
        ]
    if cov < COVERAGE_WARN:
        return [
            Issue(
                severity="warning",
                category="evidence",
                issue=f"证据覆盖率偏低 {cov * 100:.0f}%(< {COVERAGE_WARN * 100:.0f}%)",
                evidence=f"coverage={cov}",
                suggested_fix="补充关键结论的证据来源",
            )
        ]
    return []


def check_missing_evidence(ctx: dict) -> list[Issue]:
    missing = ctx["ec"].get("missing_evidence") or []
    if missing:
        return [
            Issue(
                severity="warning",
                category="evidence",
                issue=f"{len(missing)} 个关键结论缺少证据",
                evidence="; ".join(str(m) for m in missing[:3]),
                suggested_fix="为这些结论补充可引用的数据/来源",
            )
        ]
    return []


def check_unresolved_contradictions(ctx: dict) -> list[Issue]:
    contradictions = ctx["ec"].get("contradictions") or []
    if not contradictions:
        return []
    text = ctx["text"]
    surfaced = any(h in text for h in CONTRADICTION_HINTS)
    if not surfaced:
        return [
            Issue(
                severity="warning",
                category="contradiction",
                issue=f"证据链发现 {len(contradictions)} 处矛盾,但报告正文未呈现",
                evidence="; ".join(str(c) for c in contradictions[:3]),
                suggested_fix="把矛盾写进报告(矛盾本身就是信息),不要和稀泥",
            )
        ]
    return []


def check_low_confidence(ctx: dict) -> list[Issue]:
    ec = ctx["ec"]
    if "overall_confidence" not in ec:
        return []
    conf = float(ec.get("overall_confidence") or 0)
    if conf < CONFIDENCE_WARN:
        return [
            Issue(
                severity="warning",
                category="evidence",
                issue=f"综合置信度偏低 {conf * 100:.0f}%",
                evidence=f"overall_confidence={conf}",
                suggested_fix="提升高可信来源占比,或在结论中明确不确定性",
            )
        ]
    return []


def check_disclaimer(ctx: dict) -> list[Issue]:
    text = ctx["text"]
    if not any(h in text for h in DISCLAIMER_HINTS):
        return [
            Issue(
                severity="warning",
                category="compliance",
                issue="报告缺少风险提示/免责声明",
                evidence="",
                suggested_fix="用 backend.ai_assistant.compliance.wrap_with_disclaimer 包裹输出",
            )
        ]
    return []


def check_critic_flags(ctx: dict) -> list[Issue]:
    """若提供了 LLM 审稿结果,把其严重信号纳入门控。"""
    critic = ctx["critic"]
    if not critic:
        return []
    issues = []
    qs = critic.get("quality_score")
    if isinstance(qs, (int, float)) and qs <= 40:
        issues.append(
            Issue(
                severity="warning",
                category="evidence",
                issue=f"LLM 审稿质量分偏低 ({qs})",
                evidence=f"quality_score={qs}",
                suggested_fix="按审稿 comment 修订论据与结论",
            )
        )
    if critic.get("overconfident"):
        issues.append(
            Issue(
                severity="warning",
                category="evidence",
                issue="LLM 审稿标记结论过度自信",
                evidence=str(critic.get("overconfident"))[:120],
                suggested_fix="为强结论补充反方证据或下调确定性措辞",
            )
        )
    return issues


CHECKS = [
    check_empty_report,
    check_placeholder,
    check_fluff_phrases,
    check_evidence_coverage,
    check_missing_evidence,
    check_unresolved_contradictions,
    check_low_confidence,
    check_disclaimer,
    check_critic_flags,
]


def _snippet(text: str, marker: str, pad: int = 30) -> str:
    i = text.find(marker)
    if i < 0:
        return ""
    return text[max(0, i - pad) : i + len(marker) + pad].replace("\n", " ")


def run_gate(
    report_text: str,
    evidence_chain: dict | None = None,
    critic: dict | None = None,
    mode: str | None = None,
) -> dict:
    """对一份报告跑全部门控检查。

    Returns:
        ``{passed, critical_count, warning_count, info_count, issues, checks_run}``。
        ``passed = critical_count == 0``。
    """
    ctx = _ctx(report_text, evidence_chain, critic, mode)
    all_issues: list[Issue] = []
    for fn in CHECKS:
        try:
            all_issues.extend(fn(ctx) or [])
        except Exception as exc:  # 单个 check 失败不应拖垮门控
            all_issues.append(
                Issue(
                    severity="warning",
                    category="structure",
                    issue=f"门控检查 {fn.__name__} 自身异常: {type(exc).__name__}: {str(exc)[:80]}",
                )
            )

    crit = sum(1 for i in all_issues if i.severity == "critical")
    warn = sum(1 for i in all_issues if i.severity == "warning")
    info = sum(1 for i in all_issues if i.severity == "info")
    return {
        "passed": crit == 0,
        "critical_count": crit,
        "warning_count": warn,
        "info_count": info,
        "issues": [i.to_dict() for i in all_issues],
        "checks_run": [c.__name__ for c in CHECKS],
    }


def gate_or_raise(report_text: str, **kwargs) -> dict:
    """跑门控;critical>0 时抛 :class:`ReportBlockedError`。"""
    result = run_gate(report_text, **kwargs)
    if not result["passed"]:
        raise ReportBlockedError(result)
    return result


def format_human(result: dict) -> str:
    mark = "✓ 通过" if result["passed"] else "✗ 拦截"
    lines = [
        f"{mark} · 研报门控 "
        f"(critical={result['critical_count']} warning={result['warning_count']} info={result['info_count']})"
    ]
    for sev in ("critical", "warning", "info"):
        sev_issues = [i for i in result["issues"] if i["severity"] == sev]
        if not sev_issues:
            continue
        icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[sev]
        lines.append(f"  {icon} {sev.upper()} ({len(sev_issues)}):")
        for i in sev_issues:
            lines.append(f"    [{i['category']}] {i['issue']}")
            if i.get("suggested_fix"):
                lines.append(f"      fix: {i['suggested_fix']}")
    return "\n".join(lines)
