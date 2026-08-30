"""自选晨报 API — 为一组标的聚合最新价 + 涨跌幅 + 近期新闻。

供前端"自选晨报"面板。自选列表由前端 localStorage 维护。行情/新闻优先取
本地库;新闻缺失的自选会在单次请求内**限量补抓**(每请求最多 3 只,复用
/api/news 的抓取-入库链路),多次刷新逐步补齐,避免一次请求长时间阻塞。
"""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _bare_code(symbol: str) -> str:
    """000977.SZ → 000977: 新闻库的 symbols 列存的是无后缀代码, LIKE 查询需用它。"""
    m = re.match(r"^(\d{6})", symbol.strip())
    return m.group(1) if m else symbol.strip()


def _latest_bar(bars: list[dict]) -> dict | None:
    if not bars:
        return None
    return sorted(bars, key=lambda b: str(b.get("date", "")))[-1]


@router.get("")
async def morning_brief(symbols: str = Query(default="", description="逗号分隔的标的代码")):
    """为自选标的聚合简报:最新收盘价、涨跌幅、近期新闻标题;缺失的新闻限量补抓。"""
    from backend.news_store import list_news
    from backend.price_store import get_prices

    syms = [s.strip() for s in symbols.split(",") if s.strip()][:30]
    items = []
    need_fetch: list[str] = []
    for sym in syms:
        close = change_pct = date = None
        try:
            bar = _latest_bar(await asyncio.to_thread(get_prices, sym, limit=5) or [])
            if bar:
                close = bar.get("close")
                change_pct = bar.get("change_pct")
                date = bar.get("date")
        except Exception as exc:  # 单只失败不影响其余(本地数据缺失常见)
            logger.debug("[brief] %s 行情缺失: %s", sym, exc)

        news = []
        try:
            for n in await asyncio.to_thread(list_news, symbol=_bare_code(sym)) or []:
                news.append(
                    {
                        "title": n.get("title", ""),
                        "published_at": n.get("published_at", ""),
                        "url": n.get("url", ""),
                    }
                )
        except Exception as exc:
            logger.debug("[brief] %s 新闻缺失: %s", sym, exc)

        if not news:
            need_fetch.append(sym)

        items.append(
            {
                "symbol": sym,
                "close": close,
                "change_pct": change_pct,
                "date": date,
                "news": news,
                "news_count": len(news),
            }
        )

    # 新闻补抓: 复用 /api/news 的「本地缺失→抓取入库」链路。每次请求最多 3 只,
    # 长自选列表通过多次刷新渐进补齐(单只失败静默跳过, 由失败安全基线兜底)。
    fetched = 0
    try:
        from backend.api.news import _fetch_and_store_news

        for sym in need_fetch[:3]:
            status, _err = await _fetch_and_store_news(symbol=sym, limit=6)
            if status == "ok":
                fetched += 1
                for item in items:
                    if item["symbol"] != sym:
                        continue
                    fresh = await asyncio.to_thread(list_news, symbol=_bare_code(sym), limit=3) or []
                    item["news"] = [
                        {
                            "title": n.get("title", ""),
                            "published_at": n.get("published_at", ""),
                            "url": n.get("url", ""),
                        }
                        for n in fresh
                    ]
                    item["news_count"] = len(item["news"])
    except Exception as exc:  # 补抓失败不阻断简报本体
        logger.debug("[brief] 新闻补抓跳过: %s", exc)

    return ApiResponse(
        success=True,
        data={"items": items, "count": len(items), "news_fetched": fetched},
    )
