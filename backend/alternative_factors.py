"""替代因子(另类数据) — 把 FRED 宏观 / Finnhub 情绪等「注册了但无消费链路」的 provider
能力, 转化为归一化的另类因子向量([-1, +1])供因子注册中心 / Agent / 研报使用。

设计要点(延续项目「确定性 · 失败安全」基线):
- **纯函数**: normalize_sentiment / score_macro_overview / build_vector 不依赖网络,
  可单测;fetch_*_* 只负责取数并容错。
- **失败安全**: provider 不可用/缺凭证/取数失败 → 对应因子返回 None + degraded 标记,
  不抛、不影响其他因子。
- **归一化**: 所有因子压缩到 [-1, +1], 正=偏多, 负=偏空, 与软因子语义一致。
- **合规**: 仅研究语义, 不预测不荐股。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def normalize_sentiment(raw: Any) -> Optional[float]:
    """把 Finnhub 情绪/内部人交易等原始数据归一化到 [-1, +1]。

    Finnhub /stock/sentiment 返回 {bearishPercent, bullPercent}; 取净多 = bull - bear。
    内部人净买入为辅。失败/无数据返回 None。
    """
    if not isinstance(raw, dict) or not raw:
        return None
    bull = raw.get("bullPercent")
    bear = raw.get("bearishPercent")
    if isinstance(bull, (int, float)) and isinstance(bear, (int, float)):
        return max(-1.0, min(1.0, float(bull) - float(bear)))
    # 兜底: 有 buzz/scores 字段的情况
    scores = raw.get("scores") or {}
    if isinstance(scores, dict):
        b = scores.get("bullPercent")
        s = scores.get("bearPercent")
        if isinstance(b, (int, float)) and isinstance(s, (int, float)):
            return max(-1.0, min(1.0, float(b) - float(s)))
    return None


def score_insider(transactions: Any) -> Optional[float]:
    """内部人交易净额归一化:近 N 笔净买入>0 偏多。无数据返回 None。"""
    if not isinstance(transactions, list) or not transactions:
        return None
    net = 0
    n = 0
    for t in transactions[:20]:
        if not isinstance(t, dict):
            continue
        change = t.get("change") or t.get("transactionShares")
        try:
            net += float(change)
            n += 1
        except (TypeError, ValueError):
            continue
    if n == 0:
        return None
    # 用 sign + 软幅度, 限制在 [-1,1]
    if net > 0:
        return min(1.0, 0.3 + min(net / 10000, 1.0) * 0.7)
    if net < 0:
        return max(-1.0, -0.3 + max(net / 10000, -1.0) * 0.7)
    return 0.0


def score_macro_overview(overview: Any) -> Optional[float]:
    """把 FRED 宏观概览(GDP/CPI/利率/失业率等)合成一个粗略的「风险偏好」因子。

    启发式(研究用, 非预测):
    - 国债收益率上行 / 信用利差走阔 → 偏空(收紧);
    - 失业率回落 → 偏多。
    缺关键字段返回 None。值域 [-1, +1]。
    """
    if not isinstance(overview, dict) or not overview:
        return None
    score = 0.0
    contributions = 0

    def _latest(name: str) -> Optional[float]:
        item = overview.get(name)
        if isinstance(item, dict):
            v = item.get("value")
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return None

    # 10 年期国债收益率:显著上行偏空(分位启发式)
    gs10 = _latest("10_Years_Treasury_Rate") or _latest("GS10")
    if gs10 is not None:
        score += -0.2 if gs10 > 4.0 else (0.1 if gs10 < 2.5 else 0.0)
        contributions += 1
    # 失业率:回落偏低偏多
    unrate = _latest("Unemployment_Rate") or _latest("UNRATE")
    if unrate is not None:
        score += 0.2 if unrate < 4.0 else (-0.2 if unrate > 6.0 else 0.0)
        contributions += 1
    # CPI:高位偏空
    cpi = _latest("CPI") or _latest("CPIAUCSL")
    if cpi is not None:
        score += -0.2 if cpi > 4.0 else (0.1 if cpi < 2.0 else 0.0)
        contributions += 1

    if contributions == 0:
        return None
    return max(-1.0, min(1.0, score))


def fetch_fred_overview() -> Optional[dict]:
    """从 FRED provider 取宏观概览(失败/无凭证返回 None)。"""
    try:
        from backend.providers.fred_provider import FredProvider

        prov = FredProvider()
        if not prov.is_available():
            return None
        raw = prov.get_macro({})
        return raw if isinstance(raw, dict) and raw else None
    except Exception as e:  # noqa: BLE001
        logger.debug("FRED 宏观取数失败: %s", e)
        return None


def fetch_finnhub_sentiment(symbol: str) -> Optional[dict]:
    """从 Finnhub 取个股情绪(失败/无凭证/非美股返回 None)。"""
    try:
        from backend.providers.finnhub_provider import FinnhubProvider

        prov = FinnhubProvider()
        if not prov.is_available() or not prov._api_key:
            return None
        return prov.get_sentiment({"symbol": symbol}) or None
    except Exception as e:  # noqa: BLE001
        logger.debug("Finnhub 情绪取数失败: %s", e)
        return None


def fetch_finnhub_insider(symbol: str) -> Optional[list]:
    """从 Finnhub 取内部人交易(失败返回 None)。"""
    try:
        from backend.providers.finnhub_provider import FinnhubProvider

        prov = FinnhubProvider()
        if not prov.is_available() or not prov._api_key:
            return None
        data = prov.get_insider_transactions({"symbol": symbol, "limit": 20})
        return data if data else None
    except Exception as e:  # noqa: BLE001
        logger.debug("Finnhub 内部人取数失败: %s", e)
        return None


def build_vector(symbol: str = "") -> dict[str, Any]:
    """构建替代因子向量(研究用)。symbol 给定时附加美股情绪/内部人因子。

    返回:
    ```
    {
      "macro_risk_appetite": {"value": float|None, "degraded": bool, "source": str},
      "us_sentiment": {"value": float|None, "insider": float|None, "degraded": bool},
      "available_providers": [...],
      "degraded": bool,
    }
    ```
    """
    overview = fetch_fred_overview()
    macro_score = score_macro_overview(overview) if overview else None

    sentiment_raw = fetch_finnhub_sentiment(symbol) if symbol else None
    insider_raw = fetch_finnhub_insider(symbol) if symbol else None
    sent_score = normalize_sentiment(sentiment_raw) if sentiment_raw else None
    insider_score = score_insider(insider_raw) if insider_raw else None

    degraded_macro = overview is None
    degraded_sent = sentiment_raw is None and insider_raw is None

    available = []
    if overview is not None:
        available.append("fred")
    if sentiment_raw is not None or insider_raw is not None:
        available.append("finnhub")

    return {
        "symbol": symbol or "",
        "macro_risk_appetite": {
            "value": macro_score,
            "degraded": degraded_macro,
            "source": "fred" if overview is not None else "unavailable",
        },
        "us_sentiment": {
            "value": sent_score,
            "insider": insider_score,
            "degraded": degraded_sent,
            "source": "finnhub" if not degraded_sent else "unavailable",
        },
        "available_providers": available,
        "degraded": degraded_macro and degraded_sent,
        "disclaimer": "替代因子由 FRED 宏观 / Finnhub 情绪等另类数据合成, 仅作研究参考, 不构成投资建议。",
    }
