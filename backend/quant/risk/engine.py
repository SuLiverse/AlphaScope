"""研究/决策期风控引擎(v1.9.x)。

聚合 rules.py 的所有规则, 在「研报发布前」给出 RiskGateDecision:
任一 critical → 一票否决(vetoed=True), 理由写入研报顶部。

与回测期共用同一套风控哲学(纯规则、确定性、可单测), 但作用域不同:
- 回测期: backend/quant/risk_controller.py(交易级, 逐 bar)。
- 决策期: 本 engine(标的/组合/结论级, 发布前)。
二者职责分离, 不耦合。

使用:
    from backend.quant.risk.engine import RiskEngine
    engine = RiskEngine()
    decision = engine.gate(stock_data, summary)
    if decision.vetoed:  # 顶部红字写 decision.veto_reasons
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from . import (
    CRITICAL,
    RiskGateDecision,
    check_blacklist,
    check_confidence_floor,
    check_concentration,
    check_position,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "risk_rules.yaml"

# 引擎失败时的安全默认: 宁可放过也不误伤(研报场景, 风控 gate 是提示而非阻断交易)。
_SAFE_FALLBACK_CONFIG: Dict[str, Any] = {
    "blacklist": {"enabled": True, "name_patterns": ["ST", "*ST", "退", "暂停上市"]},
    "max_position_pct": {"enabled": True, "limit": 30.0},
    "concentration": {
        "enabled": True,
        "max_total_exposure_pct": 80.0,
        "max_single_sector_pct": 50.0,
    },
    "confidence_floor": {
        "enabled": True,
        "warn_below_pct": 35.0,
        "veto_below_pct": 15.0,
    },
}


class RiskEngine:
    """决策期风控引擎: 加载 config/risk_rules.yaml, 评估所有规则。

    纯规则、确定性、可单测;失败时降级到内置安全默认, 不抛异常打断研报流程。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None):
        if config is not None:
            self.config = config
        else:
            self.config = self._load_config(config_path or str(_DEFAULT_CONFIG_PATH))

    @staticmethod
    def _load_config(path: str) -> Dict[str, Any]:
        try:
            import yaml  # type: ignore

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict) and data:
                return data
            logger.debug("risk_rules.yaml 为空, 使用安全默认")
        except Exception as exc:  # noqa: BLE001 - 配置缺失不应阻断研报
            logger.debug("风控配置加载失败, 使用安全默认: %s", exc)
        return _SAFE_FALLBACK_CONFIG

    def gate(
        self,
        stock_data: Dict[str, Any],
        summary: Optional[Dict[str, Any]] = None,
    ) -> RiskGateDecision:
        """评估所有规则, 返回汇总裁决。

        Args:
            stock_data: 标的快照(name/symbol 等)。
            summary: orchestrator 的结论汇总(avg_confidence/方向性信号等)。

        Returns:
            RiskGateDecision.vetoed=True 表示存在 critical 否决。
        """
        summary = summary or {}
        findings = []

        bl = check_blacklist(stock_data, self.config.get("blacklist", {}))
        if bl:
            findings.append(bl)

        pos = check_position(stock_data, summary, self.config.get("max_position_pct", {}))
        if pos:
            findings.append(pos)

        findings.extend(check_concentration(summary, self.config.get("concentration", {})))

        conf = check_confidence_floor(summary, self.config.get("confidence_floor", {}))
        if conf:
            findings.append(conf)

        veto_reasons = [f.message for f in findings if f.severity == CRITICAL]
        return RiskGateDecision(
            vetoed=bool(veto_reasons),
            findings=findings,
            veto_reasons=veto_reasons,
        )
