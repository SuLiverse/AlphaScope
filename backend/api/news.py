"""新闻/公告/事件 API"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.provider_timeout import call_with_timeout
from backend.schemas.api import ApiResponse
from backend.utils.datetime_util import normalize_dt_str

router = APIRouter(prefix="/api/news", tags=["news"])

NEWS_PROVIDER_TIMEOUT_SECONDS = 8.0
MAX_NEWS_LIMIT = 100
MAX_EVENT_DAYS = 180
MAX_EVENT_WINDOW = 30
MAX_PARSE_URL_BYTES = 512_000
NEWS_PARSE_TIMEOUT_SECONDS = 8.0


class NewsSearchRequest(BaseModel):
    query: str = Field(description="搜索关键词")
    limit: int = Field(default=20, ge=1, le=MAX_NEWS_LIMIT, description="最大结果数")


class NewsUrlParseRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048, description="待解析的新闻 URL")
    symbol: str | None = Field(default=None, max_length=32, description="关联股票代码")
    stock_name: str | None = Field(default=None, max_length=80, description="关联股票名称")


def _coerce_fetch_result(result: Any) -> tuple[str, str]:
    if isinstance(result, tuple) and len(result) >= 2:
        return str(result[0] or "ok"), str(result[1] or "")
    return "ok", ""


@router.get("")
async def list_news(
    symbol: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_NEWS_LIMIT),
):
    """新闻列表"""
    from backend.news_store import list_news as _list

    items = _list(symbol=symbol, event_type=event_type, limit=limit)
    fetch_status = "ok"
    fetch_error = ""
    if not items:
        fetch_status, fetch_error = _coerce_fetch_result(
            await _fetch_and_store_news(
                symbol=symbol,
                limit=limit,
            )
        )
        items = _list(symbol=symbol, event_type=event_type, limit=limit)
    degraded = not items and fetch_status != "ok"
    return ApiResponse(
        success=True,
        data={
            "news": items,
            "total": len(items),
            "degraded": degraded,
            "source_status": fetch_status,
            "error": fetch_error,
        },
        error=fetch_error or None,
        error_code="NEWS_DEGRADED" if degraded else None,
    )


@router.get("/announcements")
async def list_announcements(
    symbol: str | None = None,
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_NEWS_LIMIT),
):
    """公告列表"""
    from backend.news_store import list_announcements as _list
    from backend.news_store import list_news as _list_news

    items = _list(symbol=symbol, category=category, limit=limit)
    attempted_provider_fetch = False
    if not items and symbol:
        attempted_provider_fetch = True
        fetch_status, fetch_error = _coerce_fetch_result(
            await _fetch_and_store_announcements(
                symbol=symbol,
                limit=limit,
            )
        )
        items = _list(symbol=symbol, category=category, limit=limit)
    else:
        fetch_status, fetch_error = "ok", ""

    related_news = []
    if not items and symbol:
        related_news = _list_news(symbol=symbol, limit=min(limit, 5))

    degraded = not items and bool(symbol)
    source_status = "ok"
    if degraded and related_news:
        source_status = "fallback_related_news"
    elif degraded and attempted_provider_fetch:
        source_status = fetch_status if fetch_status != "ok" else "empty"
    elif degraded:
        source_status = "local_empty"

    return ApiResponse(
        success=True,
        data={
            "announcements": items,
            "total": len(items),
            "degraded": degraded,
            "source": "local_store+provider_registry",
            "source_status": source_status,
            "related_news": related_news,
            "fallback_sources": [
                "local_announcements",
                "provider_registry",
                "local_news",
            ],
        },
        error=fetch_error or ("No announcements available from configured sources" if degraded else None),
        error_code="ANNOUNCEMENTS_DEGRADED" if degraded else None,
    )


@router.get("/events/{symbol}")
async def get_event_summary(symbol: str, days: int = Query(default=30, ge=1, le=MAX_EVENT_DAYS)):
    """事件摘要（类型分布+情绪）"""
    from backend.news_store import get_event_summary as _summary

    result = _summary(symbol, days=days)
    return ApiResponse(success=True, data=result)


@router.get("/impact/{symbol}")
async def get_event_impact(
    symbol: str,
    days: int = Query(default=30, ge=1, le=MAX_EVENT_DAYS),
    window: int = Query(default=5, ge=1, le=MAX_EVENT_WINDOW),
):
    """事件影响分析"""
    from backend.event_impact import analyze_event_impact, correlate_events_prices
    from backend.news_store import list_news
    from backend.price_store import get_prices

    events = list_news(symbol=symbol, limit=100)
    prices = get_prices(symbol, limit=250)

    if not events:
        return ApiResponse(success=False, error="无事件数据")
    if not prices:
        return ApiResponse(success=False, error="无价格数据")

    impacted = analyze_event_impact(events, prices, window_days=window)
    correlation = correlate_events_prices(events, prices)

    return ApiResponse(
        success=True,
        data={
            "symbol": symbol,
            "events": impacted[:20],  # 返回前 20 条
            "correlation": correlation,
        },
    )


@router.post("/parse-url")
async def parse_news_url(req: NewsUrlParseRequest):
    """解析外部新闻链接；失败时返回结构化降级结果。"""

    try:
        parsed = await asyncio.wait_for(
            asyncio.to_thread(_parse_external_news_url, req.url),
            timeout=NEWS_PARSE_TIMEOUT_SECONDS,
        )
        return ApiResponse(success=True, data=parsed)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        data = _fallback_url_parse(req.url, "timeout", str(exc))
    except ValueError as exc:
        data = _fallback_url_parse(req.url, "blocked", str(exc))
    except Exception as exc:
        data = _fallback_url_parse(req.url, "unavailable", str(exc))

    return ApiResponse(
        success=True,
        data=data,
        error=data["error"],
        error_code="NEWS_URL_PARSE_DEGRADED",
    )


@router.post("/search")
async def search_news(req: NewsSearchRequest):
    """搜索新闻"""
    from backend.news_store import search_news as _search

    items = _search(req.query, limit=req.limit)
    if not items:
        fetch_status, fetch_error = _coerce_fetch_result(
            await _fetch_and_store_news(
                symbol=req.query,
                limit=req.limit,
            )
        )
        items = _search(req.query, limit=req.limit)
    else:
        fetch_status, fetch_error = "ok", ""
    return ApiResponse(
        success=True,
        data={
            "query": req.query,
            "results": items,
            "total": len(items),
            "degraded": not items and fetch_status != "ok",
            "source_status": fetch_status,
            "error": fetch_error,
        },
        error=fetch_error or None,
        error_code="NEWS_SEARCH_DEGRADED" if not items and fetch_status != "ok" else None,
    )


@router.get("/{news_id}")
async def get_news(news_id: str):
    """新闻详情"""
    from backend.news_store import get_news as _get

    item = _get(news_id)
    if not item:
        return ApiResponse(success=False, error="新闻不存在")
    return ApiResponse(success=True, data=item)


async def _fetch_and_store_news(
    symbol: str | None = None,
    limit: int = 50,
) -> tuple[str, str]:
    """异步包装：把阻塞的 provider 调用丢到线程池，避免冻结事件循环。"""
    try:
        return await asyncio.to_thread(_fetch_and_store_news_sync, symbol, limit)
    except TimeoutError as exc:
        return "timeout", str(exc)
    except Exception as exc:
        return "unavailable", str(exc)


def _fetch_and_store_news_sync(
    symbol: str | None = None,
    limit: int = 50,
) -> tuple[str, str]:
    try:
        from backend.news_data import (
            fetch_telegraph_cls,
            fetch_telegraph_em,
            fetch_telegraph_sina,
            fetch_stock_news_em,
            get_stock_related_news,
            merge_news_items,
        )
        from backend.storage.db import Database

        def fetch_raw_items() -> list[dict[str, Any]]:
            raw_items: list[dict[str, Any]] = []
            if symbol:
                raw_items.extend(fetch_stock_news_em(symbol, limit=limit))
            if not raw_items:
                market_items = merge_news_items(
                    fetch_telegraph_cls(limit=min(limit, 30)),
                    fetch_telegraph_em(limit=min(limit, 50)),
                    fetch_telegraph_sina(limit=min(limit, 20)),
                    limit=limit,
                )
                raw_items = (
                    get_stock_related_news("", market_items, limit=limit, symbol=symbol or "")
                    if symbol
                    else market_items
                )
            return raw_items

        raw_items = call_with_timeout(
            fetch_raw_items,
            NEWS_PROVIDER_TIMEOUT_SECONDS,
            name="news-provider",
        )

        db = Database()
        now = datetime.now().isoformat()
        for item in raw_items[:limit]:
            row = _to_news_row(item, symbol=symbol or "", fetched_at=now)
            if row["title"]:
                db.insert_news(row)
        return "ok", ""
    except TimeoutError as exc:
        return "timeout", str(exc)
    except Exception as exc:
        return "unavailable", str(exc)


async def _fetch_and_store_announcements(
    symbol: str,
    limit: int = 50,
) -> tuple[str, str]:
    """异步包装：阻塞调用丢线程池，避免冻结事件循环。"""
    try:
        return await asyncio.to_thread(_fetch_and_store_announcements_sync, symbol, limit)
    except TimeoutError as exc:
        return "timeout", str(exc)
    except Exception as exc:
        return "unavailable", str(exc)


def _fetch_and_store_announcements_sync(
    symbol: str,
    limit: int = 50,
) -> tuple[str, str]:
    try:
        from backend.providers.registry import get_registry
        from backend.storage.db import Database

        raw_items = call_with_timeout(
            lambda: get_registry().get(
                data_type="announcements",
                market="CN",
                symbol=symbol,
                limit=limit,
            ),
            NEWS_PROVIDER_TIMEOUT_SECONDS,
            name="announcement-provider",
        )
        db = Database()
        now = datetime.now().isoformat()
        for item in raw_items[:limit]:
            row = _to_announcement_row(item, symbol=symbol, fetched_at=now)
            if row["title"]:
                db.insert_announcement(row)
        return "ok", ""
    except TimeoutError as exc:
        return "timeout", str(exc)
    except Exception as exc:
        return "unavailable", str(exc)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _domain_from_url(url: str) -> str:
    return (urlsplit(url).hostname or "external-link").lower()


def _validate_public_http_url(url: str) -> str:
    """news 路径强制拒绝本地(allow_local=False, 不受 ALPHASCOPE_ALLOW_LOCAL_FETCH 影响)。

    SSRF 校验逻辑统一收敛到 ``backend.security.url_guard``。
    """
    from backend.security.url_guard import validate_public_http_url

    return validate_public_http_url(url, allow_local=False)


def _clean_html_text(value: str) -> str:
    text = re.sub(
        r"(?is)<(script|style|svg|noscript|header|footer|nav).*?</\1>",
        " ",
        value,
    )
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_meta(content: str, *names: str) -> str:
    for name in names:
        pattern = (
            rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+'
            r'content=["\']([^"\']+)["\']'
        )
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
        reverse_pattern = (
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
            rf'(?:name|property)=["\']{re.escape(name)}["\']'
        )
        match = re.search(reverse_pattern, content, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _extract_title(content: str) -> str:
    title = _extract_meta(content, "og:title", "twitter:title")
    if title:
        return title
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", content)
    if not match:
        return ""
    return _clean_html_text(match.group(1))


def _fetch_html(url: str) -> tuple[str, str]:
    import requests

    safe_url = _validate_public_http_url(url)
    response = requests.get(
        safe_url,
        headers={
            "User-Agent": (
                "AlphaScope/1.7 news parser (research link preview; +https://github.com/TIANWEN-cpu/AlphaScope)"
            )
        },
        timeout=(3.0, 5.0),
        allow_redirects=True,
        stream=True,
    )
    try:
        response.raise_for_status()
        final_url = _validate_public_http_url(str(response.url or safe_url))
        content_type = str(response.headers.get("content-type", "")).lower()
        if content_type and not any(token in content_type for token in ("html", "text")):
            raise ValueError(f"Unsupported content type: {content_type}")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=32_768):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_PARSE_URL_BYTES:
                chunks.append(chunk[: max(0, MAX_PARSE_URL_BYTES - (total - len(chunk)))])
                break
            chunks.append(chunk)
        body = b"".join(chunks)
        encoding = response.encoding or "utf-8"
        return final_url, body.decode(encoding, errors="replace")
    finally:
        response.close()


def _parse_external_news_url(url: str) -> dict[str, Any]:
    final_url, content = _fetch_html(url)
    title = _extract_title(content)
    description = _extract_meta(
        content,
        "description",
        "og:description",
        "twitter:description",
    )
    published_at = normalize_dt_str(
        _extract_meta(
            content,
            "article:published_time",
            "og:published_time",
            "datePublished",
            "pubdate",
        )
    )
    text = _clean_html_text(content)
    if title and text.startswith(title):
        text = text[len(title) :].strip()
    summary = description or text[:260]
    body = text[:1600] or summary or title
    source = _extract_meta(content, "og:site_name", "application-name") or _domain_from_url(final_url)
    if not title:
        title = f"外部新闻链接解析：{_domain_from_url(final_url)}"

    return {
        "title": title,
        "summary": summary,
        "content": body,
        "source": source,
        "source_url": final_url,
        "published_at": published_at,
        "sentiment": 0,
        "importance": 0.55,
        "category": "macro",
        "degraded": False,
        "source_status": "ok",
    }


def _fallback_url_parse(url: str, status: str, error: str) -> dict[str, Any]:
    source = _domain_from_url(url) if urlsplit((url or "").strip()).scheme else "external-link"
    return {
        "title": f"外部新闻链接解析：{source}",
        "summary": "链接正文暂时无法自动抓取，已保留 URL 作为待核验证据。",
        "content": (f"用户提交外部新闻链接：{url}。解析状态：{status}。建议打开原文核对来源、时间和关键数字。"),
        "source": source,
        "source_url": url,
        "published_at": "",
        "sentiment": 0,
        "importance": 0.5,
        "category": "macro",
        "degraded": True,
        "source_status": status,
        "error": error,
    }


def _to_news_row(
    item: dict[str, Any],
    symbol: str = "",
    fetched_at: str = "",
) -> dict[str, Any]:
    title = str(item.get("title", "")).strip()
    published_at = normalize_dt_str(item.get("datetime", item.get("published_at", "")))
    source_url = str(item.get("source_url", item.get("url", ""))).strip()
    symbols = item.get("symbols")
    if not symbols and symbol and symbol.isdigit():
        symbols = [symbol]
    return {
        "id": item.get("id") or _stable_id("news", title, published_at, source_url, symbol),
        "title": title,
        "summary": str(item.get("summary", "")).strip(),
        "content": str(item.get("content", item.get("summary", ""))).strip(),
        "source": str(item.get("source", "unknown")).strip() or "unknown",
        "upstream": str(item.get("upstream", item.get("source", ""))).strip(),
        "source_url": source_url,
        "published_at": published_at,
        "fetched_at": fetched_at or datetime.now().isoformat(),
        "symbols": symbols or [],
        "industries": item.get("industries", []),
        "event_type": item.get("event_type", "news"),
        "sentiment": item.get("sentiment", 0),
        "importance": item.get("importance", 0.5),
        "confidence": item.get("confidence", 0.6),
        "license_level": item.get("license_level", "research_only"),
    }


def _to_announcement_row(
    item: dict[str, Any],
    symbol: str,
    fetched_at: str = "",
) -> dict[str, Any]:
    title = str(item.get("title", "")).strip()
    published_at = normalize_dt_str(item.get("datetime", item.get("published_at", "")))
    source_url = str(item.get("source_url", item.get("url", ""))).strip()
    return {
        "id": item.get("id") or _stable_id("ann", title, published_at, source_url, symbol),
        "symbol": item.get("symbol", symbol),
        "company_name": item.get("company_name", ""),
        "title": title,
        "category": item.get("category", "other"),
        "published_at": published_at,
        "fetched_at": fetched_at or datetime.now().isoformat(),
        "source": item.get("source", "unknown"),
        "source_url": source_url,
        "pdf_url": item.get("pdf_url", source_url),
        "pdf_hash": item.get("pdf_hash", ""),
        "parsed_text_path": item.get("parsed_text_path", ""),
        "importance": item.get("importance", 0.5),
        "confidence": item.get("confidence", 0.9),
    }
