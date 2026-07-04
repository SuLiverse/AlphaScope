"""研究/决策期风控规则(v1.9.x)。

与回测期 risk_controller.py 区分:
- risk_controller.py: 交易级, 在回测主循环逐 bar 校验单笔/总仓位/止损/回撤/日亏。
- 本包 rules.py: 决策级, 在「研报发布前」评估标的黑名单/集中度/置信度等,
  返回带 severity(info/warn/critical) 的 RiskFinding, 供 engine.gate() 汇总。

设计原则(对标 vn.py vnpy_riskmanager 插件式风控):
- 纯规则、确定性、可单测, 不依赖 LLM。
- 规则配置化(config/risk_rules.yaml), 用户可调阈值。
- 风控 Agent 只把引擎结果翻译成人话, 不自己算 —— 职责分离。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

INFO = "info"
WARN = "warn"
CRITICAL = "critical"
_SEVERITY_RANK = {INFO: 0, WARN: 1, CRITICAL: 2}


@dataclass
class RiskFinding:
    """单条风控发现。

    Attributes:
        rule: 规则名(对应 config 键)。
        severity: info / warn / critical。critical 触发一票否决。
        message: 人类可读的理由(会写入研报)。
    """

    rule: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITY_RANK:
            raise ValueError(f"unknown severity: {self.severity}")


@dataclass
class RiskGateDecision:
    """研报发布前风控 gate 的汇总裁决。

    vetoed=True 时研报仍会生成(保留结论可追溯), 但顶部红字写明否决理由,
    且 summary 不给出买入方向。合规要求: 风控只做提示与约束, 绝不输出买卖指令。
    """

    vetoed: bool
    findings: List[RiskFinding] = field(default_factory=list)
    veto_reasons: List[str] = field(default_factory=list)

    @property
    def max_severity(self) -> str:
        if not self.findings:
            return INFO
        return max(self.findings, key=lambda f: _SEVERITY_RANK[f.severity]).severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vetoed": self.vetoed,
            "max_severity": self.max_severity,
            "findings": [{"rule": f.rule, "severity": f.severity, "message": f.message} for f in self.findings],
            "veto_reasons": list(self.veto_reasons),
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check_blacklist(stock_data: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[RiskFinding]:
    """ST / 退市 / 暂停上市 → critical 否决。"""
    if not cfg.get("enabled", True):
        return None
    patterns = [str(p) for p in cfg.get("name_patterns", [])]
    name = str(stock_data.get("name", ""))
    symbol = str(stock_data.get("symbol", ""))
    haystack = f"{name} {symbol}"
    for pat in patterns:
        if pat and pat in haystack:
            return RiskFinding(
                rule="blacklist",
                severity=CRITICAL,
                message=f"标的命中风控黑名单({pat}): {name}({symbol}),不建议作为投资标的。",
            )
    return None


def check_position(stock_data: Dict[str, Any], summary: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[RiskFinding]:
    """单标的建议仓位超限 → warn(提示而非否决,因研报不直接下单)。"""
    if not cfg.get("enabled", True):
        return None
    limit = _safe_float(cfg.get("limit"), 30.0)
    # 研报场景无真实下单; 用 summary 里若有 suggested_position_pct 则校验, 否则跳过。
    pos_pct = _safe_float(summary.get("suggested_position_pct"), -1.0)
    if pos_pct < 0:
        return None
    if pos_pct > limit:
        return RiskFinding(
            rule="max_position_pct",
            severity=WARN,
            message=f"建议仓位 {pos_pct:.1f}% 超过单标的上限 {limit:.0f}%, 请审慎控制仓位。",
        )
    return None


def check_concentration(summary: Dict[str, Any], cfg: Dict[str, Any]) -> List[RiskFinding]:
    """总仓位/集中度超限 → warn。"""
    findings: List[RiskFinding] = []
    if not cfg.get("enabled", True):
        return findings
    total_limit = _safe_float(cfg.get("max_total_exposure_pct"), 80.0)
    sector_limit = _safe_float(cfg.get("max_single_sector_pct"), 50.0)
    total = _safe_float(summary.get("total_exposure_pct"), -1.0)
    if total >= 0 and total > total_limit:
        findings.append(
            RiskFinding(
                rule="concentration.total",
                severity=WARN,
                message=f"总仓位 {total:.1f}% 超过上限 {total_limit:.0f}%, 建议降低整体暴露。",
            )
        )
    sector = _safe_float(summary.get("single_sector_pct"), -1.0)
    if sector >= 0 and sector > sector_limit:
        findings.append(
            RiskFinding(
                rule="concentration.sector",
                severity=WARN,
                message=f"单行业集中度 {sector:.1f}% 超过上限 {sector_limit:.0f}%, 建议分散配置。",
            )
        )
    return findings


def check_confidence_floor(summary: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[RiskFinding]:
    """AI 结论平均置信度过低 → warn 或 critical(否决, 结论不可信)。"""
    if not cfg.get("enabled", True):
        return None
    warn_below = _safe_float(cfg.get("warn_below_pct"), 35.0)
    veto_below = _safe_float(cfg.get("veto_below_pct"), 15.0)
    conf = _safe_float(summary.get("avg_confidence"), -1.0)
    if conf < 0:
        return None
    # orchestrator 的 avg_confidence 可能是 0-1 也可能是 0-100, 归一到 0-100
    if conf <= 1.0:
        conf *= 100
    if conf < veto_below:
        return RiskFinding(
            rule="confidence_floor",
            severity=CRITICAL,
            message=f"AI 结论平均置信度仅 {conf:.0f}%, 低于否决阈值 {veto_below:.0f}%, 结论不可信, 建议补充数据或换模型后重测。",
        )
    if conf < warn_below:
        return RiskFinding(
            rule="confidence_floor",
            severity=WARN,
            message=f"AI 结论平均置信度 {conf:.0f}% 偏低(低于 {warn_below:.0f}%), 方向性结论需谨慎, 请结合更多证据复核。",
        )
    return None
