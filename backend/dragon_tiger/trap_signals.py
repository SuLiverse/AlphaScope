"""杀猪盘(拉高出货 / 荐股诈骗)信号扫描。

扫 8 类推广痕迹信号;每类用关键词在网搜结果里命中计数，命中 ≥2 关键词算触发。
按触发数给出风险等级与评分。

**注入式设计**:``scan_trap_signals`` 接收一个 ``search_fn(query, max_results) -> list[dict]``，
默认绑定到 AlphaScope 的 web_search provider;测试可注入假函数，无需联网。

移植并改编自 UZI-Skill ``scripts/fetch_trap_signals.py`` (MIT)，见
``docs/uzi-integration/ATTRIBUTION.md``。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 每个信号: id / name / queries(查询模板，{name} 占位) / positive_kws(命中关键词)
SIGNALS: list[dict] = [
    {
        "id": 1,
        "name": "大量低质量账号同时推荐",
        "queries": ["{name} 强烈推荐 必涨", "{name} 内部消息 暴涨"],
        "positive_kws": ["必涨", "强烈推荐", "内部", "稳赚"],
    },
    {
        "id": 2,
        "name": "推荐话术模板化",
        "queries": ["{name} 主力建仓完毕 即将爆发", "{name} 翻倍 目标价"],
        "positive_kws": ["即将爆发", "主力建仓完毕", "翻倍", "目标翻倍"],
    },
    {
        "id": 3,
        "name": "付费社群/VIP直播间引流",
        "queries": ["{name} 股票 微信群", "{name} 老师 带单 VIP 直播间"],
        "positive_kws": ["微信群", "VIP 直播", "老师带", "收费群", "加入群聊"],
    },
    {
        "id": 4,
        "name": "基本面与热度脱节",
        "queries": ["{name} 业绩亏损 推荐 暴涨", "{name} ST 推荐 拉升"],
        "positive_kws": ["亏损但推荐", "ST", "垃圾股 推荐"],
    },
    {
        "id": 5,
        "name": "K线异常配合",
        "queries": ["{name} 异动 操纵 拉升"],
        "positive_kws": ["异动", "操纵", "快速拉升", "直线拉升"],
    },
    {
        "id": 6,
        "name": "老师/股神人设推广",
        "queries": ["{name} 老师 股神 跟单", "{name} 实盘 老师"],
        "positive_kws": ["老师", "股神", "跟单", "操盘手"],
    },
    {
        "id": 7,
        "name": "跨平台联动推广",
        "queries": ["小红书 {name} 股票 推荐", "抖音 {name} 股票"],
        "positive_kws": ["小红书", "抖音", "快手", "B站 推荐"],
    },
    {
        "id": 8,
        "name": "虚假研报/伪造消息",
        "queries": ["{name} 虚假研报 谣言", "{name} 辟谣 澄清"],
        "positive_kws": ["虚假", "谣言", "澄清", "辟谣", "伪造"],
    },
]

# search_fn(query, max_results) -> list[{"title","body","url"}]
SearchFn = Callable[[str, int], list[dict]]


def _default_search_fn() -> Optional[SearchFn]:
    """绑定 AlphaScope 的 web_search provider;不可用返回 None。"""
    try:
        from backend.providers.web_search_provider import WebSearchProvider

        provider = WebSearchProvider()

        def _search(query: str, max_results: int = 3) -> list[dict]:
            rows = provider.get_news({"query": query, "limit": max_results}) or []
            out = []
            for r in rows:
                out.append(
                    {
                        "title": r.get("title", ""),
                        "body": r.get("summary") or r.get("body") or r.get("content", ""),
                        "url": r.get("url", ""),
                    }
                )
            return out

        return _search
    except Exception:
        return None


def scan_trap_signals(
    name: str,
    search_fn: Optional[SearchFn] = None,
    queries_per_signal: int = 1,
    max_results: int = 3,
) -> dict:
    """对个股名称扫描 8 类杀猪盘推广信号。

    Args:
        name: 股票名称(或代码)。
        search_fn: 注入的搜索函数;``None`` 时尝试绑定 web_search provider。
        queries_per_signal: 每个信号执行的查询数(默认 1，省搜索调用)。

    Returns:
        含 trap_level / trap_score / signals_hit / signals_hit_detail / recommendation 的字典。
    """
    search_fn = search_fn or _default_search_fn()
    if search_fn is None:
        return {
            "trap_level": "⚪ 未扫描",
            "trap_score": None,
            "signals_hit": "0/8",
            "signals_hit_count": 0,
            "signals_hit_detail": [],
            "recommendation": "web_search 不可用，未执行杀猪盘扫描。",
            "snippets": {},
        }

    hit_signals: list[dict] = []
    snippets: dict[str, list[dict]] = {}
    for sig in SIGNALS:
        bodies: list[str] = []
        for q_template in sig["queries"][:queries_per_signal]:
            q = q_template.format(name=name)
            try:
                res = search_fn(q, max_results) or []
            except Exception as exc:
                logger.debug("[trap] 搜索失败 %r: %s", q, exc)
                continue
            valid = [r for r in res if isinstance(r, dict) and "error" not in r]
            bodies.extend(str(r.get("body", "")) for r in valid)
            snippets.setdefault(f"signal_{sig['id']}", []).extend(
                {
                    "title": str(r.get("title", ""))[:80],
                    "body": str(r.get("body", ""))[:180],
                    "url": r.get("url", ""),
                }
                for r in valid[:2]
            )
        text = " ".join(bodies)
        hits = [kw for kw in sig["positive_kws"] if kw in text]
        if len(hits) >= 2:
            hit_signals.append(
                {
                    "id": sig["id"],
                    "name": sig["name"],
                    "evidence_kws": hits[:3],
                    "severity": "high" if len(hits) >= 3 else "medium",
                }
            )

    n = len(hit_signals)
    if n <= 1:
        level, score, rec = "🟢 安全", 9, "数据正常，未发现明显推广痕迹。"
    elif n <= 3:
        level, score, rec = "🟡 注意", 7, f"发现 {n} 个推广信号，建议核实信息源。"
    elif n <= 5:
        level, score, rec = "🟠 警惕", 4, f"发现 {n} 个推广信号，强烈建议谨慎。"
    else:
        level, score, rec = (
            "🔴 高度可疑",
            1,
            f"发现 {n} 个推广信号，疑似杀猪盘特征，强烈建议回避。",
        )

    return {
        "trap_level": level,
        "trap_score": score,
        "signals_hit": f"{n}/8",
        "signals_hit_count": n,
        "signals_hit_detail": hit_signals,
        "recommendation": rec,
        "high_risk_kw": ", ".join(s["name"] for s in hit_signals[:3]) if hit_signals else "未发现",
        "snippets": snippets,
    }
