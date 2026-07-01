"""AkShare Provider - 主力免费数据源

覆盖: A股/港股/美股行情, 新闻, 研报, 公告, 资金流, 基本面, 宏观数据
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

import logging
from datetime import datetime, timedelta

import akshare as ak

from .base import BaseProvider

logger = logging.getLogger(__name__)

from backend.utils import safe_call as _safe


def _to_tx_symbol(symbol: str) -> str:
    code = str(symbol or "").strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _float_value(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_hk_symbol(symbol: str) -> str:
    digits = "".join(ch for ch in str(symbol or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[:5].zfill(5)


def _looks_like_hk_symbol(symbol: str) -> bool:
    raw = str(symbol or "").strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return ".HK" in raw or raw.startswith("HK") or len(digits) == 5


class AkShareProvider(BaseProvider):
    name = "akshare"
    markets = ["CN", "ALL"]
    data_types = [
        "news",
        "reports",
        "announcements",
        "prices",
        "fundamentals",
        "fund_flow",
    ]
    priority = 60
    license_level = "research_only"

    # ---- 新闻 ----
    def get_news(self, query: dict, **kwargs) -> list[dict]:
        import time as _time

        _t0 = _time.time()
        results = []
        limit = query.get("limit", 30)

        # 财联社快讯
        try:
            df = _safe(ak.stock_info_global_cls, symbol="全部")
            if df is not None and len(df) > 0:
                for _, row in df.head(limit).iterrows():
                    results.append(
                        {
                            "source": "cls",
                            "upstream": "cls",
                            "title": str(row.get("标题", "")).strip(),
                            "summary": str(row.get("内容", "")).strip()[:200],
                            "datetime": f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip(),
                            "url": "",
                        }
                    )
        except Exception as e:
            logger.debug("AkShare CLS news failed: %s", e)
            self._record_failure(f"cls news: {e}")

        # 东财快讯
        try:
            df = _safe(ak.stock_info_global_em)
            if df is not None and len(df) > 0:
                for _, row in df.head(limit).iterrows():
                    results.append(
                        {
                            "source": "eastmoney",
                            "upstream": "eastmoney",
                            "title": str(row.get("标题", "")).strip(),
                            "summary": str(row.get("摘要", "")).strip()[:200],
                            "datetime": str(row.get("发布时间", "")).strip(),
                            "url": str(row.get("链接", "")).strip(),
                        }
                    )
        except Exception as e:
            logger.debug("AkShare EM news failed: %s", e)

        # 新浪快讯
        try:
            df = _safe(ak.stock_info_global_sina)
            if df is not None and len(df) > 0:
                for _, row in df.head(min(limit, 20)).iterrows():
                    content = str(row.get("内容", "")).strip()
                    title = content
                    if content.startswith("【"):
                        end = content.find("】")
                        if end > 0:
                            title = content[1:end]
                    results.append(
                        {
                            "source": "sina",
                            "upstream": "sina",
                            "title": title[:80],
                            "summary": content[:200],
                            "datetime": str(row.get("时间", "")).strip(),
                            "url": "",
                        }
                    )
        except Exception as e:
            logger.debug("AkShare Sina news failed: %s", e)

        if results:
            self._record_success((_time.time() - _t0) * 1000)
        elif not results:
            self._record_failure("all news sub-sources returned empty")
        return results

    # ---- 研报 ----
    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        try:
            df = _safe(ak.stock_research_report_em, symbol=symbol)
            if df is None or len(df) == 0:
                return []
            results = []
            for _, row in df.head(query.get("limit", 30)).iterrows():
                results.append(
                    {
                        "source": "eastmoney",
                        "upstream": "eastmoney",
                        "title": str(row.get("报告名称", "")).strip(),
                        "institution": str(row.get("机构", "")).strip(),
                        "rating": str(row.get("最新评级", "")).strip(),
                        "industry": str(row.get("行业", "")).strip(),
                        "datetime": str(row.get("日期", "")).strip(),
                        "pdf_url": str(row.get("报告链接", "")).strip(),
                        "symbols": [symbol],
                    }
                )
            return results
        except Exception as e:
            logger.debug("AkShare reports failed: %s", e)
            self._record_failure(f"reports: {e}")
            return []

    # ---- 公告 ----
    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        symbol = query.get("symbol", "")
        results = []

        # 巨潮公告
        try:
            df = _safe(
                ak.stock_zh_a_disclosure_report_cninfo,
                symbol=symbol,
                market="",
                keyword="",
                category="",
                start_date=query.get("start_date", ""),
                end_date=query.get("end_date", ""),
            )
            if df is not None and len(df) > 0:
                for _, row in df.head(query.get("limit", 30)).iterrows():
                    results.append(
                        {
                            "source": "cninfo",
                            "upstream": "cninfo",
                            "symbol": symbol,
                            "title": str(row.get("公告标题", "")).strip(),
                            "datetime": str(row.get("公告时间", "")).strip(),
                            "url": str(row.get("公告链接", "")).strip(),
                        }
                    )
        except Exception as e:
            logger.debug("AkShare CNInfo announcements failed: %s", e)

        # 东财公告
        try:
            df = _safe(
                ak.stock_individual_notice_report,
                symbol=symbol,
            )
            if df is not None and len(df) > 0:
                for _, row in df.head(query.get("limit", 20)).iterrows():
                    results.append(
                        {
                            "source": "eastmoney",
                            "upstream": "eastmoney",
                            "symbol": symbol,
                            "title": str(row.get("公告标题", "")).strip(),
                            "datetime": str(row.get("公告日期", "")).strip(),
                            "url": "",
                        }
                    )
        except Exception as e:
            logger.debug("AkShare EM announcements failed: %s", e)

        return results

    # ---- 行情 ----
    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        market = str(query.get("market") or "").upper()
        if market == "HK" or _looks_like_hk_symbol(symbol):
            return self._get_hk_prices(query)

        frequency = str(query.get("frequency") or "").lower()
        period = query.get("period") or {"1w": "weekly", "1mo": "monthly"}.get(
            frequency, "daily"
        )
        start_date = query.get("start_date", "")
        end_date = query.get("end_date", "")
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            limit = int(query.get("limit", 120) or 120)
            start_date = (datetime.now() - timedelta(days=max(limit * 2, 30))).strftime(
                "%Y%m%d"
            )
        adjust = query.get("adjust", "")

        try:
            df = _safe(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period=period,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", "") if end_date else "",
                adjust=adjust,
            )
            if df is None or len(df) == 0:
                em = self._get_prices_from_eastmoney(symbol, start_date, end_date)
                if em:
                    return em
                return self._get_prices_from_tencent(symbol, start_date, end_date)
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "symbol": symbol,
                        "market": "CN",
                        "date": str(row.get("日期", "")),
                        "open": _float_value(row.get("开盘", 0)),
                        "high": _float_value(row.get("最高", 0)),
                        "low": _float_value(row.get("最低", 0)),
                        "close": _float_value(row.get("收盘", 0)),
                        "volume": _float_value(row.get("成交量", 0)),
                        "amount": _float_value(row.get("成交额", 0)),
                        "turnover": _float_value(row.get("换手率", 0)),
                        "amplitude": _float_value(row.get("振幅", 0)),
                        "change_pct": _float_value(row.get("涨跌幅", 0)),
                        "adjust": adjust,
                        "frequency": {"weekly": "1w", "monthly": "1mo"}.get(
                            str(period), "1d"
                        ),
                        "source": "akshare",
                    }
                )
            return results
        except Exception as e:
            logger.debug("AkShare prices failed: %s", e)
        em = self._get_prices_from_eastmoney(symbol, start_date, end_date)
        if em:
            return em
        return self._get_prices_from_tencent(symbol, start_date, end_date)

    def _get_hk_prices(self, query: dict) -> list[dict]:
        symbol = _normalize_hk_symbol(query.get("symbol", ""))
        if not symbol:
            return []
        start_date = str(query.get("start_date") or "").replace("-", "")
        end_date = str(query.get("end_date") or "").replace("-", "")
        adjust = query.get("adjust", "")
        limit = int(query.get("limit", 120) or 120)

        try:
            df = _safe(ak.stock_hk_daily, symbol=symbol, adjust=adjust)
            if df is None or len(df) == 0:
                return []
            df = df.copy()
            if "date" in df.columns:
                df["date"] = df["date"].astype(str)
                df = df.sort_values("date")
                if start_date:
                    start_text = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                    df = df[df["date"] >= start_text]
                if end_date:
                    end_text = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
                    df = df[df["date"] <= end_text]
            df = df.tail(max(1, min(limit, 500)))
            results = []
            prev_close = 0.0
            for _, row in df.iterrows():
                open_price = _float_value(row.get("open", 0))
                high = _float_value(row.get("high", 0))
                low = _float_value(row.get("low", 0))
                close = _float_value(row.get("close", 0))
                volume = _float_value(row.get("volume", 0))
                amount = _float_value(row.get("amount", 0))
                base = prev_close or open_price or close
                change_pct = ((close - base) / base * 100) if base else 0.0
                amplitude = ((high - low) / base * 100) if base else 0.0
                results.append(
                    {
                        "symbol": symbol,
                        "market": "HK",
                        "date": str(row.get("date", "")),
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                        "amount": amount,
                        "turnover": 0.0,
                        "amplitude": round(amplitude, 4),
                        "change_pct": round(change_pct, 4),
                        "adjust": adjust,
                        "frequency": "1d",
                        "source": "akshare:stock_hk_daily",
                    }
                )
                prev_close = close
            return results
        except Exception as e:
            logger.debug("AkShare HK prices failed: %s", e)
            self._record_failure(f"hk prices: {e}")
            return []

    def _get_prices_from_tencent(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        try:
            df = _safe(
                ak.stock_zh_a_hist_tx,
                symbol=_to_tx_symbol(symbol),
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
            if df is None or len(df) == 0:
                return []
            df = df.copy().sort_values("date")
            results = []
            prev_close = None
            for _, row in df.iterrows():
                open_price = _float_value(row.get("open", 0))
                high = _float_value(row.get("high", 0))
                low = _float_value(row.get("low", 0))
                close = _float_value(row.get("close", 0))
                amount = _float_value(row.get("amount", 0))
                base = prev_close or open_price or close
                change_pct = ((close - base) / base * 100) if base else 0.0
                amplitude = ((high - low) / base * 100) if base else 0.0
                volume = round(amount / max(close, 0.01), 0) if amount else 0.0
                results.append(
                    {
                        "symbol": symbol,
                        "market": "CN",
                        "date": str(row.get("date", "")),
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                        "amount": amount,
                        "turnover": 0.0,
                        "amplitude": round(amplitude, 4),
                        "change_pct": round(change_pct, 4),
                        "adjust": "",
                        "source": "tencent",
                    }
                )
                prev_close = close
            return results
        except Exception as e:
            logger.debug("Tencent prices fallback failed: %s", e)
            return []

    def _get_prices_from_eastmoney(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """直连东方财富 push2his 日线接口。

        akshare 的 stock_zh_a_hist / 腾讯兜底当前都可能失效(拉不到最新日线),
        东财 push2his 是稳定可靠的兜底源,自带正确的开高低收/量额。
        """
        import json
        import urllib.request

        digits = "".join(ch for ch in str(symbol or "") if ch.isdigit())
        if not digits:
            return []
        if len(digits) == 5:
            secid = f"116.{digits}"  # 港股
        elif digits.startswith("6"):
            secid = f"1.{digits}"  # 沪市
        else:
            secid = f"0.{digits}"  # 深市/创业/北交所
        beg = (start_date or "").replace("-", "") or "19900101"
        end = (end_date or "").replace("-", "") or "20500101"
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57"
            f"&klt=101&fqt=1&beg={beg}&end={end}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            logger.debug("Eastmoney prices failed for %s: %s", symbol, e)
            return []
        klines = ((payload or {}).get("data") or {}).get("klines") or []
        if not klines:
            return []
        market = "HK" if len(digits) == 5 else "CN"
        results: list[dict] = []
        prev_close = None
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 7:
                continue
            open_price = _float_value(parts[1])
            close = _float_value(parts[2])
            high = _float_value(parts[3])
            low = _float_value(parts[4])
            volume = _float_value(parts[5])
            amount = _float_value(parts[6])
            base = prev_close or open_price or close
            change_pct = ((close - base) / base * 100) if base else 0.0
            amplitude = ((high - low) / base * 100) if base else 0.0
            results.append(
                {
                    "symbol": symbol,
                    "market": market,
                    "date": parts[0],
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "turnover": 0.0,
                    "amplitude": round(amplitude, 4),
                    "change_pct": round(change_pct, 4),
                    "adjust": "",
                    "frequency": "1d",
                    "source": "eastmoney",
                }
            )
            prev_close = close
        return results

    # ---- 资金流 ----
    def get_fund_flow(self, query: dict, **kwargs) -> list[dict]:
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        try:
            market = "sh" if symbol.startswith(("60", "68", "9")) else "sz"
            if symbol.startswith(("8", "4")):
                market = "bj"
            df = _safe(ak.stock_individual_fund_flow, stock=symbol, market=market)
            if df is None or len(df) == 0:
                return []
            df = df.tail(query.get("days", 30))
            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "symbol": symbol,
                        "date": str(row.get("日期", "")),
                        "main_net_inflow": float(row.get("主力净流入-净额", 0)),
                        "super_large_net_inflow": float(
                            row.get("超大单净流入-净额", 0)
                        ),
                        "large_net_inflow": float(row.get("大单净流入-净额", 0)),
                        "medium_net_inflow": float(row.get("中单净流入-净额", 0)),
                        "small_net_inflow": float(row.get("小单净流入-净额", 0)),
                        "close": float(row.get("收盘价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "source": "eastmoney",
                    }
                )
            return results
        except Exception as e:
            logger.debug("AkShare fund flow failed: %s", e)
            return []

    # ---- 基本面 ----
    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        symbol = query.get("symbol", "")
        if not symbol:
            return {}
        result = {}
        try:
            df = _safe(ak.stock_financial_analysis_indicator, symbol=symbol)
            if df is not None and len(df) > 0:
                result["financial_indicators"] = df.head(4).to_dict("records")
        except Exception as e:
            logger.debug("AkShare fundamentals failed: %s", e)
        return result
