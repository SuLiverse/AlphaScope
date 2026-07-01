"""
财经资讯 & 研报数据聚合模块 (v0.11)

v0.11 新增: Provider 插件集成
- fetch_news_via_provider(): 通过 Provider Registry 获取新闻
- fetch_reports_via_provider(): 通过 Provider Registry 获取研报
- fetch_announcements_via_provider(): 通过 Provider Registry 获取公告

原有函数保持不变, 向后兼容。

数据源:
- 财联社电报 stock_info_global_cls
- 东财快讯  stock_info_global_em
- 新浪快讯  stock_info_global_sina
- 财新摘要  stock_news_main_cx
- 东财个股研报 stock_research_report_em
"""

import warnings

warnings.filterwarnings("ignore")

import json
import logging
import akshare as ak
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from backend.utils import safe_call as _safe


def fetch_telegraph_cls(limit: int = 30) -> List[Dict[str, Any]]:
    """财联社电报（最实时，含正文）"""
    df = _safe(ak.stock_info_global_cls, symbol="全部")
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "source": "财联社",
                "title": str(row.get("标题", "")).strip(),
                "summary": str(row.get("内容", "")).strip()[:200],
                "datetime": f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip(),
                "url": "",
            }
        )
    return out


def fetch_telegraph_em(limit: int = 30) -> List[Dict[str, Any]]:
    """东方财富快讯（覆盖面最广）"""
    df = _safe(ak.stock_info_global_em)
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "source": "东财",
                "title": str(row.get("标题", "")).strip(),
                "summary": str(row.get("摘要", "")).strip()[:200],
                "datetime": str(row.get("发布时间", "")).strip(),
                "url": str(row.get("链接", "")).strip(),
            }
        )
    return out


def fetch_telegraph_sina(limit: int = 20) -> List[Dict[str, Any]]:
    """新浪快讯（速度快，文本短）"""
    df = _safe(ak.stock_info_global_sina)
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out = []
    for _, row in df.iterrows():
        content = str(row.get("内容", "")).strip()
        # 截取标题（通常用【】包起来）
        title = content
        if content.startswith("【"):
            end = content.find("】")
            if end > 0:
                title = content[1:end]
        out.append(
            {
                "source": "新浪",
                "title": title[:80],
                "summary": content[:200],
                "datetime": str(row.get("时间", "")).strip(),
                "url": "",
            }
        )
    return out


def fetch_caixin(limit: int = 10) -> List[Dict[str, Any]]:
    """财新摘要"""
    df = _safe(ak.stock_news_main_cx)
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out = []
    for _, row in df.iterrows():
        summary = str(row.get("summary", "")).strip()
        out.append(
            {
                "source": "财新",
                "title": summary[:60],
                "summary": summary[:200],
                "datetime": "",
                "url": str(row.get("url", "")).strip(),
                "tag": str(row.get("tag", "")).strip(),
            }
        )
    return out


def _clean_str(value, default: str = "") -> str:
    """akshare 经常把缺失值返成 NaN/None,直接 str() 会得到 'nan'。统一过滤。"""
    if value is None:
        return default
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return default
    except Exception:
        pass
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return default
    return s


def _to_float_or_none(value):
    """akshare 数值列偶有 NaN/空字符串,这里统一收敛成 None。"""
    if value is None:
        return None
    try:
        import math

        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _eastmoney_article_url(code: Any) -> str:
    """Build an Eastmoney article URL only for plausible numeric article ids."""
    code_s = _clean_str(code)
    if not code_s or not code_s.isdigit():
        return ""
    return f"http://finance.eastmoney.com/a/{code_s}.html"


def _parse_eastmoney_search_payload(text: str) -> Dict[str, Any]:
    import json as _json
    import re as _re

    m = _re.search(r"^[^(]+\((.+)\)\s*;?\s*$", text or "", _re.DOTALL)
    if not m:
        return {}
    try:
        data = _json.loads(m.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fetch_eastmoney_search_text(
    cf_requests, params: dict, headers: dict, use_cffi: bool = True
) -> str:
    """Try Eastmoney search without cookie first, then fall back to a minimal history cookie."""
    base_headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    try:
        if use_cffi:
            r = cf_requests.get(
                url,
                params=params,
                headers=base_headers,
                impersonate="chrome",
                timeout=10,
            )
        else:
            r = cf_requests.get(url, params=params, headers=base_headers, timeout=10)
        text = r.text
        payload = _parse_eastmoney_search_payload(text)
        if (payload.get("result") or {}).get("cmsArticleWebOld"):
            return text
        if "passportWeb" not in text and payload:
            return text
    except Exception:
        pass

    try:
        if use_cffi:
            r = cf_requests.get(
                url, params=params, headers=headers, impersonate="chrome", timeout=10
            )
        else:
            r = cf_requests.get(url, params=params, headers=headers, timeout=10)
        return r.text
    except Exception:
        return ""


# ============== 公告分类(纯函数) ==============

# (canonical_label, priority, keywords)
# 一条公告可能命中多个关键词,priority 用来挑出最有价值的标签;
# 例如同时含"业绩预告"和"修订",取业绩预告。数字越小越高优。
_ANN_RULES: List[tuple] = [
    ("业绩预告", 1, ["业绩预告", "业绩预增", "业绩预减", "业绩预亏", "业绩快报"]),
    (
        "年报/季报",
        2,
        ["年度报告", "半年度报告", "第一季度报告", "第三季度报告", "季度报告"],
    ),
    ("回购", 3, ["回购"]),
    ("股权激励", 4, ["股权激励", "限制性股票激励"]),
    ("减持", 5, ["减持", "减持计划", "减持股份"]),
    ("增持", 5, ["增持"]),
    ("股权质押", 6, ["质押", "解除质押"]),
    ("分红送转", 7, ["利润分配", "派息", "送转", "股东大会"]),
    ("解禁", 8, ["解除限售", "解禁"]),
    ("重大合同", 9, ["重大合同", "重大经营合同", "签署"]),
    ("重大资产重组", 10, ["重组", "收购", "出售资产", "股权转让"]),
    ("关联交易", 11, ["关联交易", "对外担保"]),
    ("监管问询", 12, ["问询函", "关注函", "监管函", "立案"]),
    ("ST/退市", 13, ["特别处理", "退市"]),
    ("调研活动", 20, ["调研", "投资者关系", "业绩说明会"]),
]

# 公告类型 → 颜色,UI 直接用
ANN_COLORS: Dict[str, str] = {
    "业绩预告": "#ef5350",
    "年报/季报": "#f59e0b",
    "回购": "#16a34a",
    "增持": "#16a34a",
    "股权激励": "#16a34a",
    "减持": "#dc2626",
    "股权质押": "#dc2626",
    "解禁": "#f59e0b",
    "分红送转": "#0ea5e9",
    "重大合同": "#16a34a",
    "重大资产重组": "#a855f7",
    "关联交易": "#9ca3af",
    "监管问询": "#dc2626",
    "ST/退市": "#dc2626",
    "调研活动": "#9ca3af",
    "其他": "#6b7280",
}


def classify_announcement(title: str) -> str:
    """根据公告标题/类型字段返回规范化的中文标签。

    匹配按优先级顺序进行,首个命中胜出。无法匹配的返回 "其他"。
    """
    if not title:
        return "其他"
    text = str(title)
    best_label = None
    best_priority = 999
    for label, priority, keywords in _ANN_RULES:
        if any(k in text for k in keywords):
            if priority < best_priority:
                best_label = label
                best_priority = priority
    return best_label or "其他"


def _date_n_days_ago(days: int) -> str:
    from datetime import timedelta

    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def _date_today() -> str:
    return datetime.now().strftime("%Y%m%d")


def fetch_announcements_cninfo(
    symbol: str, days: int = 30, limit: int = 40
) -> List[Dict[str, Any]]:
    """巨潮资讯个股公告(支持按代码 + 日期范围筛选,质量最高)。

    Returns 列表,每条字段:
    - title (公告标题)
    - category (本地分类:业绩预告 / 回购 / ...)
    - date (公告日期 YYYY-MM-DD)
    - url (公告原始链接)
    - source ("巨潮")
    """
    if not symbol:
        return []
    df = _safe(
        ak.stock_zh_a_disclosure_report_cninfo,
        symbol=symbol,
        market="沪深京",
        keyword="",
        category="",
        start_date=_date_n_days_ago(days),
        end_date=_date_today(),
    )
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        title = _clean_str(row.get("公告标题"))
        if not title:
            continue
        out.append(
            {
                "title": title,
                "category": classify_announcement(title),
                "date": _clean_str(row.get("公告时间"))[:10],
                "url": _clean_str(row.get("公告链接")),
                "source": "巨潮",
            }
        )
    return out


def fetch_announcements_em_today(
    date_str: Optional[str] = None, limit: int = 60
) -> List[Dict[str, Any]]:
    """东财全市场当日公告。supplements 巨潮接口,有时巨潮当日还没收录,东财已经发布。

    返回字段对齐 :func:`fetch_announcements_cninfo`,额外带 ``code`` / ``name``,便于行业过滤。
    """
    date_str = date_str or _date_today()
    df = _safe(ak.stock_notice_report, symbol="全部", date=date_str)
    if df is None or len(df) == 0:
        return []
    df = df.head(limit).copy()
    out: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        title = _clean_str(row.get("公告标题"))
        if not title:
            continue
        out.append(
            {
                "title": title,
                "category": classify_announcement(
                    title + " " + _clean_str(row.get("公告类型"))
                ),
                "date": _clean_str(row.get("公告日期"))[:10],
                "url": _clean_str(row.get("网址")),
                "source": "东财",
                "code": _clean_str(row.get("代码")),
                "name": _clean_str(row.get("名称")),
            }
        )
    return out


def merge_announcements(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 title+date 去重,保留最先出现的(传参顺序代表数据源优先级,巨潮在前)。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for lst in lists:
        for item in lst or []:
            key = (item.get("title", "").strip(), item.get("date", "")[:10])
            if not key[0] or key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=lambda x: x.get("date", ""), reverse=True)
    return out


def build_announcements_brief_for_llm(
    items: List[Dict[str, Any]], max_items: int = 8
) -> str:
    """把公告列表压缩成给 LLM 看的简报。"""
    if not items:
        return "无近期公告"
    lines = []
    for i, x in enumerate(items[:max_items], 1):
        cat = x.get("category", "其他")
        lines.append(f"{i}. [{x.get('date', '')} {cat}] {x.get('title', '')[:80]}")
    return "\n".join(lines)


def fetch_research_report(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """个股研报(含评级)。"""
    df = _safe(ak.stock_research_report_em, symbol=symbol)
    if df is None or len(df) == 0:
        return []
    # 按日期降序
    if "日期" in df.columns:
        df = df.sort_values("日期", ascending=False)
    df = df.head(limit).copy()
    out = []
    for _, row in df.iterrows():
        out.append(
            {
                "title": _clean_str(row.get("报告名称")),
                "rating": _clean_str(row.get("东财评级")),
                "institution": _clean_str(row.get("机构")),
                "date": _clean_str(row.get("日期")),
                "industry": _clean_str(row.get("行业")),
                "eps_2026": _to_float_or_none(row.get("2026-盈利预测-收益")),
                "pe_2026": _to_float_or_none(row.get("2026-盈利预测-市盈率")),
                "pdf": _clean_str(row.get("报告PDF链接")),
            }
        )
    return out


def fetch_stock_news_em(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """东方财富搜索 API 抓取**特定股票**的近期新闻(标题级别相关性最强的来源)。

    实现取舍:
    - akshare 自带的 ``stock_news_em`` 在 pandas+pyarrow 下有 bug
      (``r"\\u3000"`` 当作 regex 传给 pyarrow 抛 ArrowInvalid),所以这里
      重新写一份;关键是用 ``curl_cffi`` 模拟 Chrome TLS 指纹,否则
      搜索 API 会返回 passportWeb(账号信息)而不是 cmsArticleWebOld(新闻)。
    - 服务端的 cb 名/timestamp 实际被忽略,所以保留 akshare 用过的硬编码值。
    - 字符串清理用普通 ``str.replace``,不再走 pandas accessor。

    返回字段对齐其他 fetch_telegraph_*: ``source / title / summary / datetime / url``,
    所以可以直接合并到 dashboard 现有的"个股相关资讯"流里。
    """
    if not symbol:
        return []
    try:
        # 延迟导入,curl_cffi 偶发 ABI 问题不该拖垮整个 news_data 模块
        from curl_cffi import requests as _cf_requests
    except Exception:
        return []

    inner = {
        "uid": "",
        "keyword": str(symbol),
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": max(1, min(int(limit), 50)),
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    params = {
        "cb": "jQuery35101792940631092459_1764599530165",
        "param": json.dumps(inner, ensure_ascii=False),
        "_": "1764599530176",
    }
    headers = {
        "accept": "*/*",
        "accept-language": "en,zh-CN;q=0.9,zh;q=0.8",
        "cache-control": "no-cache",
        "cookie": f"emshistory=%5B%22{symbol}%22%5D",
        "host": "search-api-web.eastmoney.com",
        "referer": f"https://so.eastmoney.com/news/s?keyword={symbol}",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
    }
    text = _fetch_eastmoney_search_text(_cf_requests, params, headers)
    payload = _parse_eastmoney_search_payload(text)
    if not payload:
        return []

    arts = (payload.get("result") or {}).get("cmsArticleWebOld") or []
    out: List[Dict[str, Any]] = []
    for a in arts:
        if not isinstance(a, dict):
            continue
        title = _clean_str(a.get("title")).replace("<em>", "").replace("</em>", "")
        if not title:
            continue
        content = _clean_str(a.get("content")).replace("<em>", "").replace("</em>", "")
        # 全角空格 + CRLF,普通 replace 即可,不再触发 pyarrow regex bug
        content = content.replace("　", "").replace("\r\n", " ")
        url = ""
        code = _clean_str(a.get("code"))
        if code:
            url = _eastmoney_article_url(code)
        out.append(
            {
                "source": _clean_str(a.get("mediaName")) or "东方财富",
                "title": title,
                "summary": content[:240],
                "datetime": _clean_str(a.get("date")),
                "url": url,
            }
        )
    return out


def fetch_keyword_news_em(keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    """东方财富搜索 API 按任意主题词抓新闻。

    这是 ``fetch_stock_news_em`` 的行业/概念版:股票代码能查到个股新闻,但小盘股
    的行业动态往往藏在"算力""存储芯片""信创"这类主题词下面。主动按主题词
    搜索,比只在大盘快讯池里做关键词过滤召回更高。

    v0.14: curl_cffi 不可用时自动降级到 requests。
    """
    keyword = _clean_str(keyword)
    if not keyword:
        return []

    use_cffi = True
    try:
        from curl_cffi import requests as _http
    except Exception:
        use_cffi = False
        try:
            import requests as _http  # type: ignore[no-redef]
        except Exception:
            logger.warning(
                "Neither curl_cffi nor requests available for East Money search"
            )
            return []

    page_size = max(1, min(int(limit), 50))
    inner = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    params = {
        "cb": "jQuery35101792940631092459_1764599530165",
        "param": json.dumps(inner, ensure_ascii=False),
        "_": "1764599530176",
    }
    from urllib.parse import quote as _urlencode

    kw_encoded = _urlencode(keyword)
    headers = {
        "accept": "*/*",
        "accept-language": "en,zh-CN;q=0.9,zh;q=0.8",
        "cache-control": "no-cache",
        "cookie": f"emshistory=%5B%22{kw_encoded}%22%5D",
        "host": "search-api-web.eastmoney.com",
        "referer": f"https://so.eastmoney.com/news/s?keyword={kw_encoded}",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
    }
    text = _fetch_eastmoney_search_text(_http, params, headers, use_cffi=use_cffi)
    payload = _parse_eastmoney_search_payload(text)
    if not payload:
        return []

    arts = (payload.get("result") or {}).get("cmsArticleWebOld") or []
    out: List[Dict[str, Any]] = []
    for a in arts:
        if not isinstance(a, dict):
            continue
        title = _clean_str(a.get("title")).replace("<em>", "").replace("</em>", "")
        if not title:
            continue
        content = _clean_str(a.get("content")).replace("<em>", "").replace("</em>", "")
        content = content.replace("　", "").replace("\r\n", " ")
        code = _clean_str(a.get("code"))
        out.append(
            {
                "source": "东财搜索",
                "topic": keyword,
                "title": title,
                "summary": content[:240],
                "datetime": _clean_str(a.get("date")),
                "url": _eastmoney_article_url(code),
            }
        )
    return out


def _news_date_key(item: Dict[str, Any]) -> str:
    """取新闻排序日期。字符串日期格式不稳定,这里只做保守字典序排序。"""
    return _clean_str(item.get("datetime")) or _clean_str(item.get("date"))


def merge_news_items(
    *lists: List[Dict[str, Any]], limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """合并多路新闻,按 title+date 去重并尽量按时间倒序。

    传参顺序仍有意义:同一标题同一天重复时,保留先出现的数据源。
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for lst in lists:
        for item in lst or []:
            title = _clean_str(item.get("title"))
            if not title:
                continue
            key = (title, _news_date_key(item)[:10])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=_news_date_key, reverse=True)
    if limit is not None:
        return out[: max(0, int(limit))]
    return out


def build_topic_news_keywords(
    industry: str = "",
    business_terms: Optional[List[str]] = None,
    concepts: Optional[List[Dict[str, Any]]] = None,
    limit: int = 8,
) -> List[str]:
    """生成主动搜索行业/概念新闻的主题词。

    借鉴 vendor router 的思路,上层只提供行业、主营业务词、概念归属,这里统一
    收敛成有限主题词,避免前端到处拼接关键词。
    """
    candidates: List[str] = []
    candidates.extend(get_industry_keywords(industry))
    candidates.extend([_clean_str(x) for x in (business_terms or [])])
    candidates.extend(get_concept_keywords(concepts or [], limit=12))

    seen: set = set()
    out: List[str] = []
    for kw in candidates:
        kw = _clean_str(kw)
        if len(kw) < 2 or kw in seen:
            continue
        seen.add(kw)
        out.append(kw)
        if len(out) >= limit:
            break
    return out


def fetch_topic_news_em(
    keywords: List[str],
    limit_each: int = 8,
    total_limit: int = 30,
) -> List[Dict[str, Any]]:
    """按多个行业/概念主题词主动搜索东财新闻并去重。"""
    if not keywords:
        return []
    batches: List[List[Dict[str, Any]]] = []
    seen_kw: set = set()
    for kw in keywords:
        kw = _clean_str(kw)
        if not kw or kw in seen_kw:
            continue
        seen_kw.add(kw)
        batches.append(fetch_keyword_news_em(kw, limit=limit_each))
        if len(seen_kw) >= 10:
            break
    return merge_news_items(*batches, limit=total_limit)


def aggregate_market_news(limit_each: int = 15) -> Dict[str, List[Dict]]:
    """聚合大盘资讯"""
    return {
        "财联社": fetch_telegraph_cls(limit=limit_each),
        "东财": fetch_telegraph_em(limit=limit_each),
        "新浪": fetch_telegraph_sina(limit=limit_each),
    }


# ============== 概念板块召回 ==============

_BROAD_CONCEPT_BLACKLIST = {
    "融资融券",
    "转融券标的",
    "昨日涨停",
    "昨日连板",
    "昨日触板",
}


def _normalize_stock_code(value) -> str:
    """把股票代码规整为 6 位字符串,兼容数值/带交易所前后缀的输入。"""
    s = _clean_str(value)
    if not s:
        return ""
    s = s.upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    s = s.replace("SH", "").replace("SZ", "").replace("BJ", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6) if digits else ""


def _extract_concept_name(row) -> str:
    """从 akshare 概念列表行里取概念名,兼容东财/同花顺字段。"""
    return (
        _clean_str(row.get("板块名称"))
        or _clean_str(row.get("name"))
        or _clean_str(row.get("概念名称"))
        or _clean_str(row.get("名称"))
    )


def _extract_concept_code(row) -> str:
    """从 akshare 概念列表行里取概念代码。"""
    return (
        _clean_str(row.get("板块代码"))
        or _clean_str(row.get("code"))
        or _clean_str(row.get("概念代码"))
    )


def fetch_stock_concepts(
    symbol: str,
    stock_name: str = "",
    max_concepts: int = 12,
    max_scan: int = 50,
) -> List[Dict[str, Any]]:
    """反查股票所属东财概念板块。

    v0.15: 改用东财 datacenter API 直接查询个股所属板块(1 次请求),
    替代扫描板块列表+拉成分股的暴力方案(50+ 次请求)。
    """
    code = _normalize_stock_code(symbol)
    if not code:
        return []

    out = _fetch_stock_boards_datacenter(code, max_concepts=max_concepts)
    if out:
        return out

    # 回退: 扫描板块列表(慢但兼容性好)
    return _fetch_stock_boards_scan(code, stock_name, max_concepts, max_scan)


def _fetch_stock_boards_datacenter(
    code: str, max_concepts: int = 12
) -> List[Dict[str, Any]]:
    """通过东财 datacenter API 直接查个股所属板块(1 次 HTTP 请求)。"""
    import requests as _req

    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "BOARD_NAME,BOARD_CODE,BOARD_TYPE,IS_PRECISE,BOARD_RANK",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": 50,
        "sortTypes": "-1",
        "sortColumns": "BOARD_TYPE",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        "Referer": "https://emweb.securities.eastmoney.com/",
    }
    try:
        r = _req.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    items = (data.get("result") or {}).get("data") or []
    raw: List[Dict[str, Any]] = []
    seen: set = set()
    for item in items:
        name = _clean_str(item.get("BOARD_NAME"))
        if not name or name in _BROAD_CONCEPT_BLACKLIST or name in seen:
            continue
        seen.add(name)
        board_code = _clean_str(item.get("BOARD_CODE"))
        board_type = _clean_str(item.get("BOARD_TYPE"))
        rank = _to_float_or_none(item.get("BOARD_RANK"))
        is_precise = item.get("IS_PRECISE") == 1 or item.get("IS_PRECISE") == "1"
        raw.append(
            {
                "name": name,
                "code": board_code,
                "board_type": board_type,
                "is_precise": is_precise,
                "rank": rank,
                "pct_chg": None,
                "lead_stock": "",
            }
        )

    # 排序: 精确匹配 > 行业 > 有 rank > 无 rank; 同级按 rank 升序
    def _sort_key(e: Dict) -> tuple:
        precise = 0 if e["is_precise"] else 1
        is_industry = 0 if e.get("board_type") == "行业" else 1
        r = e["rank"] if e["rank"] is not None else 999
        return (precise, is_industry, r)

    raw.sort(key=_sort_key)
    return raw[:max_concepts]


def _fetch_stock_boards_scan(
    code: str,
    stock_name: str,
    max_concepts: int = 12,
    max_scan: int = 50,
) -> List[Dict[str, Any]]:
    """回退方案: 扫描概念板块列表 + 拉成分股(慢,但不依赖 datacenter API)。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    concept_df = _safe(ak.stock_board_concept_name_em)
    if concept_df is None or len(concept_df) == 0:
        return []

    def _check_board(board_row) -> Optional[Dict[str, Any]]:
        name = _extract_concept_name(board_row)
        if not name or name in _BROAD_CONCEPT_BLACKLIST:
            return None
        board_code = _extract_concept_code(board_row)
        cons = _safe(ak.stock_board_concept_cons_em, symbol=board_code or name)
        if cons is None or len(cons) == 0:
            return None
        try:
            cons_codes = {
                _normalize_stock_code(v)
                for v in cons.get("代码", [])
                if _normalize_stock_code(v)
            }
            names = {_clean_str(v) for v in cons.get("名称", [])}
        except Exception:
            return None
        if code not in cons_codes and (stock_name and stock_name not in names):
            return None
        return {
            "name": name,
            "code": board_code,
            "pct_chg": _to_float_or_none(board_row.get("涨跌幅")),
            "lead_stock": _clean_str(board_row.get("领涨股票")),
        }

    scan_rows = list(concept_df.head(max_scan).iterrows())
    out: List[Dict[str, Any]] = []
    seen: set = set()

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_check_board, row): row for _, row in scan_rows}
        for fut in as_completed(futures):
            if len(out) >= max_concepts:
                break
            result = fut.result()
            if result and result["name"] not in seen:
                seen.add(result["name"])
                out.append(result)

    return out


def get_concept_keywords(concepts: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    """从概念列表生成新闻匹配词。"""
    out: List[str] = []
    seen: set = set()
    for item in concepts or []:
        name = _clean_str(item.get("name") if isinstance(item, dict) else item)
        if not name or name in _BROAD_CONCEPT_BLACKLIST:
            continue
        candidates = [name]
        for suffix in ("概念", "板块", "指数"):
            if name.endswith(suffix) and len(name) > len(suffix) + 1:
                candidates.append(name[: -len(suffix)])
        for kw in candidates:
            kw = kw.strip()
            if len(kw) < 2 or kw in seen:
                continue
            seen.add(kw)
            out.append(kw)
            if len(out) >= limit:
                return out
    return out


def get_concept_news(
    concepts: List[Dict[str, Any]],
    all_news: List[Dict],
    limit: int = 15,
    exclude_titles: Optional[set] = None,
) -> List[Dict]:
    """从大盘资讯里筛选概念板块相关新闻。"""
    keywords = get_concept_keywords(concepts, limit=12)
    if not keywords:
        return []
    seen: set = set(exclude_titles or set())
    out: List[Dict] = []
    for n in all_news or []:
        title = (n.get("title", "") or "").strip()
        if not title or title in seen:
            continue
        text = (title + " " + n.get("summary", "")).lower()
        matched = [kw for kw in keywords if kw.lower() in text]
        if not matched:
            continue
        seen.add(title)
        n["matched_keywords"] = matched
        out.append(n)
        if len(out) >= limit:
            break
    return out


def build_concepts_brief_for_llm(
    concepts: List[Dict[str, Any]],
    concept_news: List[Dict],
    max_concepts: int = 10,
    max_news: int = 6,
) -> str:
    """把概念归属和概念新闻压缩成 LLM 简报。"""
    if not concepts and not concept_news:
        return ""
    lines: List[str] = []
    if concepts:
        parts = []
        for c in concepts[:max_concepts]:
            name = c.get("name", "")
            pct = c.get("pct_chg")
            lead = c.get("lead_stock", "")
            tail = []
            if isinstance(pct, (int, float)):
                tail.append(f"{pct:+.2f}%")
            if lead:
                tail.append(f"领涨:{lead}")
            parts.append(name + (f"({', '.join(tail)})" if tail else ""))
        lines.append("所属概念: " + " / ".join(parts))
    if concept_news:
        lines.append("概念相关新闻:")
        lines.append(build_news_brief_for_llm(concept_news, max_items=max_news))
    return "\n".join(lines)


def _simplify_product(name: str) -> List[str]:
    """从冗长的产品描述抽 0-1 个高质量核心词。

    实测下来,新闻标题里 2-3 字的"行业小词"(证券/广告/互联网/数据)出现频率
    极高,任何包含它们的关键词都会大量误中(例如"中国移动"被"数据移动"命中)。
    所以这里非常保守:**只在能切出 4 字干净短语时返回**,否则返回空,让上层
    走 industry-based 召回。

    示例:
    - "茅台酒" -> ["茅台酒"]
    - "金融资讯及数据PC终端服务系统" -> ["金融资讯"](剥后缀+按"及"切分后取 4 字段)
    - "证券公司综合服务系统" -> []
    - "5G通信终端" -> []
    """
    name = (name or "").strip()
    if not name:
        return []

    SUFFIXES = (
        "解决方案",
        "服务系统",
        "服务平台",
        "推广服务",
        "终端服务",
        "终端",
        "服务",
        "系统",
        "平台",
        "业务",
        "产品",
        "方案",
        "工具",
        "软件",
        "客户端",
    )
    cleaned = name
    changed = True
    while changed:
        changed = False
        for s in SUFFIXES:
            if cleaned.endswith(s) and len(cleaned) > len(s) + 1:
                cleaned = cleaned[: -len(s)]
                changed = True

    SEPARATORS = ["及", "和", "与", "、", ",", "，", "的", "/"]
    fragments = [cleaned]
    for sep in SEPARATORS:
        new_frags = []
        for f in fragments:
            new_frags.extend(f.split(sep))
        fragments = new_frags

    out: List[str] = []
    GENERIC = {
        "证券",
        "公司",
        "服务",
        "数据",
        "终端",
        "系统",
        "客户",
        "平台",
        "信息",
        "互联",
        "网络",
        "技术",
        "产品",
        "业务",
        "互联网",
        "广告",
        "网站",
        "用户",
        "运营",
        "管理",
        "数字化",
        "智能",
        "数据化",
        "云端",
    }
    for f in fragments:
        f = f.strip()
        for s in SUFFIXES:
            if f.endswith(s) and len(f) > len(s) + 1:
                f = f[: -len(s)]
        if not f:
            continue
        if any(ch.isascii() and ch.isalnum() for ch in f):
            continue
        # 只接受刚好 3-4 字、且不在通用词黑名单、且不以通用词开头的核心词。
        # "数据移动" 4 字但前 2 字"数据"是通用词,排除。
        if not (3 <= len(f) <= 4):
            continue
        if f in GENERIC:
            continue
        if f[:2] in GENERIC:
            continue
        if f not in out:
            out.append(f)
        if len(out) >= 2:
            break
    return out


def _expand_stock_keywords(
    stock_name: str,
    symbol: str = "",
    industry: str = "",
    products: Optional[List[str]] = None,
) -> List[str]:
    """从股票全名生成新闻匹配关键词集。

    A 股新闻里很少出现公司全名(例如"贵州茅台酒股份有限公司")或"贵州茅台",
    更多是简称、品牌名、地名 + 主营。这里做几条简单可靠的扩展:

    - 去掉常见后缀(银行/证券/股份/集团/科技/控股/能源/传媒/...)
    - 全名长度 >= 4 时加"前 2 字"和"后 2 字"
    - 把符号代码(600519)也作为关键词
    - 主营产品(products)经 :func:`_simplify_product` 抽核心词后加入,
      用于提升非品牌型股票(如大智慧、广联达)的召回
    - 行业名(industry)也加入个股关键词。原本 v0.10 step 2 把行业排除在外,
      但实测对"大智慧"这种行业即业务的股票,行业新闻就是它的核心新闻;
      现在统一加入,长度 >= 2 即接受。
    """
    keywords: list[str] = []

    name = (stock_name or "").strip()
    if name:
        keywords.append(name)
        for suffix in (
            "银行",
            "证券",
            "股份",
            "集团",
            "控股",
            "科技",
            "能源",
            "传媒",
            "保险",
            "实业",
            "电子",
            "电力",
            "汽车",
            "重工",
            "地产",
            "医药",
            "食品",
            "化学",
            "化工",
            "信息",
            "通信",
            "网络",
            "软件",
            "环保",
            "建设",
            "工业",
            "机械",
            "国际",
        ):
            if name.endswith(suffix) and len(name) > len(suffix) + 1:
                trimmed = name[: -len(suffix)]
                if len(trimmed) >= 2:
                    keywords.append(trimmed)
        if len(name) >= 4:
            keywords.append(name[:2])
            keywords.append(name[-2:])
        elif len(name) >= 2:
            keywords.append(name)

    if symbol:
        keywords.append(str(symbol).strip())

    # 主营产品 -> 核心词
    for raw in products or []:
        for token in _simplify_product(raw):
            keywords.append(token)

    # 行业名(剥罗马尾)。注意:在 :func:`get_stock_related_news` 里默认不传 industry,
    # 以保持"个股相关 / 行业新闻"两区分明;但保留参数,允许调用方在 LLM 简报场景
    # 显式打开,扩大召回。
    if industry:
        keywords.append(industry)
        for suffix in ("Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"):
            if industry.endswith(suffix) and len(industry) > 1:
                keywords.append(industry[:-1])

    seen: set[str] = set()
    out: list[str] = []
    for kw in sorted({k for k in keywords if k}, key=len, reverse=True):
        if kw and kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out


def get_industry_keywords(industry: str) -> List[str]:
    """从一个行业名生成行业新闻匹配的关键词集。"""
    industry = (industry or "").strip()
    if not industry:
        return []
    out = [industry]
    # akshare 行业名常带罗马数字后缀(白酒Ⅱ / 化工Ⅲ),剥掉
    for suffix in ("Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"):
        if industry.endswith(suffix) and len(industry) > 1:
            base = industry[:-1]
            if base and base not in out:
                out.append(base)
    return out


def fetch_main_business(symbol: str) -> Dict[str, Any]:
    """同花顺主营业务接口(stock_zyjs_ths)。

    返回 ``{"industry": "白酒", "products": ["茅台酒", "其他系列酒"],
    "main_business": "...", "scope": "..."}``,任一字段缺失返回空。失败返回 ``{}``。
    """
    df = _safe(ak.stock_zyjs_ths, symbol=symbol)
    if df is None or len(df) == 0:
        return {}
    row = df.iloc[0]
    products_raw = _clean_str(row.get("产品类型")) or _clean_str(row.get("产品名称"))
    products: List[str] = []
    if products_raw:
        for sep in ["、", "，", ",", ";", "/", "|"]:
            products_raw = products_raw.replace(sep, "|")
        products = [p.strip() for p in products_raw.split("|") if p.strip()]
    return {
        "industry": _clean_str(row.get("行业")),
        "products": products[:6],
        "main_business": _clean_str(row.get("主营业务")),
        "scope": _clean_str(row.get("经营范围")),
    }


def extract_business_terms(scope_text: str, max_terms: int = 8) -> List[str]:
    """从"经营范围"等长文本里抽 3-5 字的行业/技术关键词。

    经营范围里通常是"数据存储技术产品、微电子芯片技术产品、机器学习产品..."
    这类长串,直接用作关键词会 0 命中(新闻里没人说"机器学习产品")。这里:

    1. 按常见分隔符("、"、","、";"、"，")切分;
    2. 剥掉每段尾部的通用后缀(产品/技术/服务/系统/设备/平台/装备);
    3. 保留长度 3-5 的核心词,且不在通用词黑名单(数据/技术/产品/...)里;
    4. 去重,长度降序输出最多 ``max_terms`` 个。

    示例: "数据存储技术产品、微电子芯片技术产品、机器学习产品、软件产品" 抽出
    ``['数据存储', '微电子芯片', '机器学习']``。
    """
    if not scope_text:
        return []

    SUFFIXES_3 = ("技术产品", "解决方案", "技术开发", "系统集成", "及系统集成")
    SUFFIXES_2 = (
        "产品",
        "技术",
        "服务",
        "系统",
        "设备",
        "平台",
        "装备",
        "工程",
        "材料",
        "设计",
        "解决",
        "运营",
        "管理",
        "进出口",
    )
    GENERIC = {
        "数据",
        "信息",
        "技术",
        "产品",
        "服务",
        "系统",
        "设备",
        "平台",
        "客户",
        "网络",
        "软件",
        "硬件",
        "通信",
        "互联网",
        "智能",
        "管理",
        "运营",
        "工程",
        "解决",
        "测试",
        "咨询",
        "销售",
        "进口",
        "出口",
        "生产",
        "其他",
        "项目",
        "技术进出口",
        "防伪开发",
        "防伪",
        "进出口",
    }

    text = str(scope_text)
    SEPARATORS = ["、", "，", ",", ";", "；", "/", "(", ")", "(", ")", "和", "及"]
    fragments = [text]
    for sep in SEPARATORS:
        new_frags: List[str] = []
        for f in fragments:
            new_frags.extend(f.split(sep))
        fragments = new_frags

    out: List[str] = []
    seen: set = set()
    for f in fragments:
        f = f.strip().strip("。.的")
        # 去尾部修饰
        for s in SUFFIXES_3 + SUFFIXES_2:
            while f.endswith(s) and len(f) > len(s) + 1:
                f = f[: -len(s)]
        if not f or any(ch.isascii() and ch.isalnum() for ch in f):
            continue
        if not (3 <= len(f) <= 6):
            continue
        if f in GENERIC:
            continue
        # 整段恰好是"通用 + 通用"两词拼接,过滤;但 4 字时只看是否完全通用,
        # "数据存储"前两字虽通用,后两字"存储"是行业关键字,放行
        if len(f) == 4 and f[:2] in GENERIC and f[2:] in GENERIC:
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
        if len(out) >= max_terms:
            break

    out.sort(key=len, reverse=True)
    return out


def _infer_industry_from_text(text: str) -> str:
    """从一段中文文本(常见来源:主营业务/经营范围描述)启发式抽出行业名。

    A 股的主营文本里通常会出现一个 2-4 字的行业核心词,例如"证券信息服务"
    包含"证券",`xxx 银行业务`包含"银行"。这里用一张白名单做关键词匹配,
    精度优先于召回——找不到就返回空字符串,让上层走"行业未知"分支。
    """
    if not text:
        return ""
    text = str(text)
    # 白名单按"重要 + 长词优先"排序,长词排前避免短词误中(例如"证券保险" 应识别为证券)
    HINTS = [
        "证券信息服务",
        "金融信息服务",
        "信息技术服务",
        "白酒",
        "啤酒",
        "葡萄酒",
        "饮料",
        "乳制品",
        "证券",
        "银行",
        "保险",
        "信托",
        "期货",
        "基金",
        "光伏",
        "风电",
        "电池",
        "新能源",
        "半导体",
        "芯片",
        "医药",
        "医疗器械",
        "生物制品",
        "中药",
        "创新药",
        "汽车",
        "整车",
        "汽车零部件",
        "新能源汽车",
        "钢铁",
        "煤炭",
        "有色金属",
        "稀土",
        "化工",
        "石油",
        "房地产",
        "建筑",
        "建材",
        "水泥",
        "工程",
        "传媒",
        "游戏",
        "影视",
        "广告",
        "出版",
        "通信",
        "5G",
        "运营商",
        "通信设备",
        "软件",
        "计算机",
        "云计算",
        "数据中心",
        "人工智能",
        "互联网",
        "电商",
        "O2O",
        "外卖",
        "金融科技",
        "食品",
        "调味品",
        "速冻",
        "肉制品",
        "纺织",
        "服装",
        "家纺",
        "鞋类",
        "家电",
        "白电",
        "黑电",
        "厨电",
        "机械",
        "重工",
        "工程机械",
        "机器人",
        "自动化",
        "物流",
        "快递",
        "航运",
        "港口",
        "教育",
        "酒店",
        "旅游",
        "餐饮",
        "环保",
        "节能",
        "新材料",
    ]
    # 显式品牌/产品 → 行业映射,弥补主营文本不直接含行业关键词的情况
    PRODUCT_TO_INDUSTRY = [
        (("茅台", "五粮液", "汾酒", "泸州老窖", "洋河", "白酒"), "白酒"),
        (("锂电", "动力电池", "储能电池"), "电池"),
        (("光伏组件", "硅片", "电池片"), "光伏"),
        (("风电整机", "风机"), "风电"),
        (("乳制品", "奶粉", "酸奶"), "乳制品"),
        (("猪肉", "肉鸡", "饲料"), "畜牧"),
    ]
    for products, ind in PRODUCT_TO_INDUSTRY:
        if any(p in text for p in products):
            return ind
    # 排长在前
    for kw in sorted(HINTS, key=len, reverse=True):
        if kw in text:
            return kw
    return ""


def fetch_industry_name(
    symbol: str, concepts: Optional[List[Dict[str, Any]]] = None
) -> str:
    """获取股票行业名;多级回退。

    1. 东财 datacenter API 直接查板块(1 次请求,最快);
    2. stock_individual_info_em(东财抽风时常挂);
    3. stock_research_report_em 行业列(研报为空时也无效);
    4. stock_zyjs_ths 主营业务文本启发式抽行业;
    5. 从已获取的概念板块名中提取行业关键词(零网络请求)。
    """
    code = _normalize_stock_code(symbol)

    # 优先: datacenter API 直接查板块类型
    if code:
        boards = _fetch_stock_boards_datacenter(code, max_concepts=30)
        # 先找 BOARD_TYPE 明确标记为 "行业" 的板块
        for b in boards:
            if _clean_str(b.get("board_type")) == "行业":
                name = _clean_str(b.get("name"))
                if name and len(name) >= 2:
                    return name
        # 回退: 排除明显的指数/ETF/区域/市场概念板块
        _NOT_INDUSTRY = {
            "大盘股",
            "大盘价值",
            "大盘成长",
            "权重股",
            "百元股",
            "行业龙头",
            "超级品牌",
            "机构重仓",
            "证金持股",
            "MSCI中国",
            "标准普尔",
        }
        _NOT_INDUSTRY_SUFFIXES = (
            "概念",
            "指数",
            "ETF",
            "LOF",
            "板块",
            "通",
            "50_",
            "180_",
            "300_",
            "500_",
        )
        for b in boards:
            name = _clean_str(b.get("name"))
            if not name or len(name) < 2:
                continue
            if name in _NOT_INDUSTRY:
                continue
            if any(name.endswith(s) for s in _NOT_INDUSTRY_SUFFIXES):
                continue
            if name.endswith(("省", "市", "区", "特区")):
                continue
            return name

    df = _safe(ak.stock_individual_info_em, symbol=symbol)
    if df is not None and len(df):
        try:
            info = dict(zip(df["item"], df["value"]))
            ind = _clean_str(info.get("行业"))
            if ind:
                return ind
        except Exception:
            pass

    # 研报回退:取最新一行的行业
    df2 = _safe(ak.stock_research_report_em, symbol=symbol)
    if df2 is not None and len(df2) and "行业" in df2.columns:
        for v in df2["行业"]:
            ind = _clean_str(v)
            if ind:
                return ind

    # 主营业务文本兜底
    df3 = _safe(ak.stock_zyjs_ths, symbol=symbol)
    if df3 is not None and len(df3):
        row = df3.iloc[0]
        text = " ".join(
            _clean_str(row.get(c))
            for c in ("主营业务", "产品类型", "产品名称", "经营范围")
        )
        ind = _infer_industry_from_text(text)
        if ind:
            return ind

    # 概念板块兜底:从已获取的概念名中提取行业
    if concepts:
        for c in concepts:
            name = _clean_str(c.get("name") if isinstance(c, dict) else c)
            if not name:
                continue
            for suffix in ("概念", "板块", "指数"):
                if name.endswith(suffix) and len(name) > len(suffix) + 1:
                    name = name[: -len(suffix)].strip()
            if len(name) >= 2:
                return name

    return ""


def get_stock_related_news(
    stock_name: str,
    all_news: List[Dict],
    limit: int = 15,
    symbol: str = "",
    industry: str = "",
    products: Optional[List[str]] = None,
) -> List[Dict]:
    """从大盘资讯里筛选与个股相关的条目。

    关键词通过 :func:`_expand_stock_keywords` 扩展,既支持"贵州茅台"全名,
    也能匹配只写"茅台"或股票代码的新闻条目;若提供 ``products``,主营产品名
    也参与匹配。``industry`` 仅在调用方愿意接受行业新闻时使用——一般通过
    :func:`get_industry_news` 单独获取。
    """
    keywords = _expand_stock_keywords(
        stock_name, symbol, industry=industry, products=products
    )
    if not keywords:
        return []

    related = []
    seen_titles: set = set()
    for n in all_news:
        text = (n.get("title", "") + " " + n.get("summary", "")).lower()
        if not any(k.lower() in text for k in keywords):
            continue
        title = n.get("title", "").strip()
        if title in seen_titles:
            continue
        seen_titles.add(title)
        related.append(n)
        if len(related) >= limit:
            break
    return related


def get_industry_news(
    industry: str,
    all_news: List[Dict],
    limit: int = 15,
    exclude_titles: Optional[set] = None,
    extra_keywords: Optional[List[str]] = None,
) -> List[Dict]:
    """从大盘资讯里筛选行业新闻。

    ``extra_keywords`` 是从经营范围抽出的行业级关键词(如"数据存储""机器学习"),
    会和 ``industry`` 一并加入匹配集合,显著提升小盘股 / 行业泛化股的召回。
    """
    keywords = list(get_industry_keywords(industry))
    for kw in extra_keywords or []:
        kw = (kw or "").strip()
        if kw and kw not in keywords:
            keywords.append(kw)
    if not keywords:
        return []
    # 长关键词优先,降低误判
    keywords.sort(key=len, reverse=True)
    out: List[Dict] = []
    seen: set = set(exclude_titles or [])
    for n in all_news:
        title = (n.get("title", "") or "").strip()
        if not title or title in seen:
            continue
        text = (title + " " + n.get("summary", "")).lower()
        matched = [k for k in keywords if k.lower() in text]
        if not matched:
            continue
        seen.add(title)
        n["matched_keywords"] = matched
        out.append(n)
        if len(out) >= limit:
            break
    return out


def build_news_brief_for_llm(news_list: List[Dict], max_items: int = 10) -> str:
    """把新闻列表压缩成给 LLM 看的简报"""
    if not news_list:
        return "无最新资讯"
    lines = []
    for i, n in enumerate(news_list[:max_items], 1):
        title = n.get("title", "")[:80]
        summary = n.get("summary", "")[:120]
        time = n.get("datetime", "")[:16]
        src = n.get("source", "")
        lines.append(f"{i}. [{src} {time}] {title} | {summary}")
    return "\n".join(lines)


def build_research_brief_for_llm(reports: List[Dict], max_items: int = 8) -> str:
    """把研报列表压缩成 LLM 简报"""
    if not reports:
        return "暂无近期研报"
    lines = []
    rating_counter = {}
    for r in reports[:max_items]:
        rating = r.get("rating") or "未评级"
        rating_counter[rating] = rating_counter.get(rating, 0) + 1
        lines.append(
            f"- [{r.get('date', '')}] {r.get('institution', '')}: 《{r.get('title', '')[:40]}》评级={rating}"
        )

    summary_line = "评级分布: " + " / ".join(
        f"{k}×{v}" for k, v in rating_counter.items()
    )
    return summary_line + "\n" + "\n".join(lines)


# ============== v0.11: Provider 插件集成 ==============


def _get_registry():
    """延迟导入 Provider Registry"""
    try:
        from backend.providers.registry import get_registry

        return get_registry()
    except Exception as e:
        logger.debug("Provider Registry 不可用: %s", e)
        return None


def fetch_news_via_provider(
    market: str = "CN",
    symbol: str = "",
    limit: int = 30,
    sources: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """通过 Provider Registry 获取新闻 (v0.11)

    v0.12: 优先通过 DataPipeline 采集 (含去重/排序/存储/索引),
    Pipeline 不可用时回退到 Provider Registry, 最终回退到原有函数。
    """
    # v0.12: 优先使用 Pipeline
    try:
        from backend.pipeline import get_pipeline

        results = get_pipeline().ingest_news(market=market, symbol=symbol, limit=limit)
        if results:
            return results
    except Exception:
        pass

    # v0.11 回退: 直接使用 Registry
    registry = _get_registry()
    if registry:
        results = registry.get(
            data_type="news",
            market=market,
            symbol=symbol,
            limit=limit,
        )
        if results:
            return results

    # 最终回退到原有实现
    return merge_news_items(
        fetch_telegraph_cls(limit=limit),
        fetch_telegraph_em(limit=limit),
        fetch_telegraph_sina(limit=min(limit, 20)),
    )


def fetch_reports_via_provider(
    symbol: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """通过 Provider Registry 获取研报 (v0.11, v0.12 增强)"""
    try:
        from backend.pipeline import get_pipeline

        results = get_pipeline().ingest_reports(symbol=symbol, limit=limit)
        if results:
            return results
    except Exception:
        pass

    registry = _get_registry()
    if registry:
        results = registry.get(
            data_type="reports",
            market="CN",
            symbol=symbol,
            limit=limit,
        )
        if results:
            return results

    return fetch_research_report(symbol, limit=limit)


def fetch_announcements_via_provider(
    symbol: str,
    limit: int = 30,
    start_date: str = "",
    end_date: str = "",
) -> List[Dict[str, Any]]:
    """通过 Provider Registry 获取公告 (v0.11, v0.12 增强)"""
    try:
        from backend.pipeline import get_pipeline

        results = get_pipeline().ingest_announcements(
            symbol=symbol,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        if results:
            return results
    except Exception:
        pass

    registry = _get_registry()
    if registry:
        results = registry.get(
            data_type="announcements",
            market="CN",
            symbol=symbol,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )
        if results:
            return results

    return fetch_announcements_cninfo(symbol, days=30, limit=limit)


def get_provider_health_summary() -> str:
    """获取所有数据源的健康状态摘要 (v0.11)"""
    try:
        from backend.observability.source_health import SourceHealthMonitor

        monitor = SourceHealthMonitor()
        return monitor.get_source_summary()
    except Exception:
        return "Provider 健康监控不可用"


if __name__ == "__main__":
    print("=" * 70)
    print("测试 1: 财联社电报")
    print("=" * 70)
    items = fetch_telegraph_cls(limit=3)
    for x in items:
        print(f"[{x['datetime']}] {x['title']}")

    print("\n" + "=" * 70)
    print("测试 2: 东财快讯")
    print("=" * 70)
    items = fetch_telegraph_em(limit=3)
    for x in items:
        print(f"[{x['datetime']}] {x['title']}")

    print("\n" + "=" * 70)
    print("测试 3: 个股研报 (600519)")
    print("=" * 70)
    items = fetch_research_report("600519", limit=3)
    for x in items:
        print(f"[{x['date']}] {x['institution']} | {x['rating']} | {x['title']}")

    print("\n" + "=" * 70)
    print("测试 4: 个股相关资讯（贵州茅台）")
    print("=" * 70)
    all_news = (
        fetch_telegraph_em(limit=200)
        + fetch_telegraph_cls(limit=20)
        + fetch_telegraph_sina(limit=20)
    )
    related = get_stock_related_news("贵州茅台", all_news, limit=5)
    print(f"匹配到 {len(related)} 条")
    for x in related:
        print(f"[{x.get('source')} {x.get('datetime')}] {x.get('title')}")
