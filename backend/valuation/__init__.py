"""机构级估值建模 (DCF / Comps / LBO / 三表 / 并购)。

- :func:`value_stock` — 对一个 ``features`` 字典跑全套估值(纯函数，可单测)。
- :func:`features_from_fundamentals` — 从 AlphaScope ``backend.fundamentals`` 构造 features(尽力而为)。
- :func:`value_symbol` — 给定股票代码，取数 + 估值的便捷入口。

引擎见 :mod:`backend.valuation.fin_models`。移植自 UZI-Skill (MIT)，
见 ``docs/uzi-integration/ATTRIBUTION.md``。
"""

from __future__ import annotations

import logging

from .fin_models import (
    accretion_dilution,
    build_comps_table,
    compute_dcf,
    compute_wacc,
    project_three_stmt,
    quick_lbo,
)

logger = logging.getLogger(__name__)

__all__ = [
    "compute_dcf",
    "compute_wacc",
    "build_comps_table",
    "project_three_stmt",
    "quick_lbo",
    "accretion_dilution",
    "value_stock",
    "features_from_fundamentals",
    "value_symbol",
]


def _comps_target(features: dict) -> dict:
    """从 features 抽取 comps 目标公司字段。"""
    return {
        "name": features.get("name") or features.get("ticker", "目标公司"),
        "pe": features.get("pe"),
        "pb": features.get("pb"),
        "ps": features.get("ps"),
        "roe": features.get("roe_last"),
        "net_margin": features.get("net_margin"),
        "revenue_growth": features.get("rev_growth_3y"),
        "market_cap_yi": features.get("market_cap_yi"),
        "price": features.get("price"),
        "eps": features.get("eps"),
        "bvps": features.get("bvps"),
    }


def value_stock(
    features: dict,
    assumptions: dict | None = None,
    peers: list[dict] | None = None,
) -> dict:
    """对一个 features 字典跑 DCF + LBO + 三表 (+ 有同行则跑 Comps)。

    返回 ``{dcf, comps, lbo, three_statement, summary}``。纯计算，无网络。
    """
    dcf = compute_dcf(features, assumptions)
    lbo = quick_lbo(features)
    three = project_three_stmt(features, assumptions)
    comps = build_comps_table(_comps_target(features), peers) if peers else {"note": "无同行数据，跳过 Comps"}

    summary = {
        "dcf_intrinsic_per_share": dcf.get("intrinsic_per_share"),
        "dcf_safety_margin_pct": dcf.get("safety_margin_pct"),
        "dcf_verdict": dcf.get("verdict"),
        "lbo_irr_pct": lbo.get("irr_pct"),
        "lbo_verdict": lbo.get("verdict"),
        "comps_verdict": comps.get("valuation_verdict", "—"),
    }
    return {
        "dcf": dcf,
        "comps": comps,
        "lbo": lbo,
        "three_statement": three,
        "summary": summary,
    }


def features_from_fundamentals(symbol: str) -> tuple[dict, list[dict]]:
    """从 ``backend.fundamentals`` 构造估值 features + 同行列表(尽力而为)。

    缺失的字段(如 FCF/EBITDA/股本)由 :mod:`fin_models` 内置近似兜底。
    返回 ``(features, peers)``。
    """
    features: dict = {"ticker": symbol, "name": symbol}
    peers: list[dict] = []
    try:
        from backend import fundamentals as F
    except Exception as exc:  # pragma: no cover
        logger.debug("[valuation] 无法导入 fundamentals: %s", exc)
        return features, peers

    # 最新一期财务
    try:
        periods = F.fetch_financial_summary(symbol) or []
        if periods:
            p = periods[0]
            rev = float(getattr(p, "revenue_yi", 0) or 0)
            ni = float(getattr(p, "net_profit_yi", 0) or 0)
            features["revenue_latest_yi"] = rev
            if rev > 0:
                features["net_margin"] = round(ni / rev * 100, 2)
            features["roe_last"] = float(getattr(p, "roe_pct", 0) or 0)
            features["rev_growth_3y"] = float(getattr(p, "yoy_revenue", 0) or 0)
            features["gross_margin"] = float(getattr(p, "gross_margin_pct", 0) or 0)
            features["debt_ratio"] = float(getattr(p, "debt_ratio_pct", 0) or 0)
    except Exception as exc:
        logger.debug("[valuation] 取财务摘要失败 %s: %s", symbol, exc)

    # 同行 + 自身行(用于 Comps 与目标 pe/pb/市值)
    try:
        result = F.fetch_industry_peers(symbol)
        rows = result[1] if isinstance(result, tuple) else (result or [])
        for r in rows:
            mc = float(getattr(r, "total_mcap_yi", 0) or 0)
            row = {
                "name": getattr(r, "name", "") or getattr(r, "symbol", ""),
                "ticker": getattr(r, "symbol", ""),
                "pe": getattr(r, "pe", None),
                "pb": getattr(r, "pb", None),
                "roe": getattr(r, "roe_pct", None),
                "revenue_growth": getattr(r, "yoy_revenue_pct", None),
                "market_cap_yi": mc,
            }
            if getattr(r, "is_self", False):
                features["market_cap_yi"] = mc
                if getattr(r, "pe", 0):
                    features["pe"] = float(r.pe)
                if getattr(r, "pb", 0):
                    features["pb"] = float(r.pb)
            else:
                peers.append(row)
    except Exception as exc:
        logger.debug("[valuation] 取同行失败 %s: %s", symbol, exc)

    return features, peers


def value_symbol(symbol: str, assumptions: dict | None = None) -> dict:
    """给定股票代码:取数 → 估值。便捷入口(API 用)。"""
    features, peers = features_from_fundamentals(symbol)
    result = value_stock(features, assumptions, peers or None)
    result["symbol"] = symbol
    result["features"] = features
    result["degraded"] = not features.get("revenue_latest_yi")
    return result
