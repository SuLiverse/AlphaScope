"""量化因子生成器

从数据库中的新闻、公告、研报、价格等数据生成标准化因子。
所有因子归一化到 [-1.0, 1.0] 区间, 正值看多, 负值看空。

因子维度:
- news_sentiment: 新闻情绪因子 (加权情绪均值)
- event_signal: 事件信号因子 (公告事件类型打分)
- analyst_rating: 分析师评级因子 (评级+目标价)
- fund_flow: 资金流向因子 (主力净流入趋势)
- momentum: 价格动量因子 (涨跌幅+成交量变化)
- composite: 综合因子 (加权组合)
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ---- 事件类型 → 情绪映射 ----

_EVENT_CATEGORY_SCORES: dict[str, float] = {
    "earnings": 0.3,  # 业绩报告中性偏正, 具体看内容
    "dividend": 0.4,  # 分红一般利好
    "mna": 0.2,  # 并购中性, 取决于具体情况
    "financing": -0.2,  # 融资偏利空 (稀释)
    "litigation": -0.6,  # 诉讼/处罚利空
    "policy": 0.0,  # 政策中性
    "supply_chain": 0.3,  # 中标/合同利好
    "insider": 0.0,  # 增减持需看方向
}

# 研报评级 → 数值映射
_RATING_SCORES: dict[str, float] = {
    "买入": 1.0,
    "强烈推荐": 1.0,
    "推荐": 0.7,
    "增持": 0.5,
    "持有": 0.0,
    "中性": 0.0,
    "观望": -0.2,
    "减持": -0.5,
    "卖出": -1.0,
    "回避": -0.7,
    "buy": 1.0,
    "strong_buy": 1.0,
    "overweight": 0.5,
    "hold": 0.0,
    "neutral": 0.0,
    "underweight": -0.5,
    "sell": -1.0,
}

# 因子权重配置
DEFAULT_WEIGHTS: dict[str, float] = {
    "news_sentiment": 0.20,
    "event_signal": 0.25,
    "analyst_rating": 0.25,
    "fund_flow": 0.15,
    "momentum": 0.15,
}

FUND_FLOW_FACTOR_TIMEOUT_SECONDS = 6.0


def _call_with_timeout(fn, timeout: float):
    """Run a blocking factor input provider without stalling the whole report."""
    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put((True, fn()), block=False)
        except Exception as exc:
            try:
                result_queue.put((False, exc), block=False)
            except queue.Full:
                pass

    thread = threading.Thread(target=worker, name="factor-provider", daemon=True)
    thread.start()
    try:
        ok, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("factor provider timed out") from exc
    if ok:
        return payload
    raise payload


@dataclass
class FactorReport:
    """单只股票的因子报告"""

    symbol: str
    stock_name: str = ""
    computed_at: str = ""

    # 各维度因子 [-1.0, 1.0]
    news_sentiment: float = 0.0
    event_signal: float = 0.0
    analyst_rating: float = 0.0
    fund_flow: float = 0.0
    momentum: float = 0.0
    composite: float = 0.0

    # 各维度样本量
    news_count: int = 0
    event_count: int = 0
    report_count: int = 0

    # 数据质量
    degraded_inputs: list[str] = field(default_factory=list)
    missing_dimensions: list[str] = field(default_factory=list)

    # 详细信号
    signals: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.computed_at:
            self.computed_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "stock_name": self.stock_name,
            "computed_at": self.computed_at,
            "factors": {
                "news_sentiment": round(self.news_sentiment, 3),
                "event_signal": round(self.event_signal, 3),
                "analyst_rating": round(self.analyst_rating, 3),
                "fund_flow": round(self.fund_flow, 3),
                "momentum": round(self.momentum, 3),
                "composite": round(self.composite, 3),
            },
            "sample_counts": {
                "news": self.news_count,
                "events": self.event_count,
                "reports": self.report_count,
            },
            "degraded_inputs": self.degraded_inputs,
            "missing_dimensions": self.missing_dimensions,
            "signals": self.signals[:20],  # 最多返回 20 条信号
        }


class FactorGenerator:
    """量化因子生成器"""

    def __init__(self, weights: Optional[dict[str, float]] = None) -> None:
        self._weights = weights or DEFAULT_WEIGHTS.copy()

    def generate(
        self,
        symbol: str,
        stock_name: str = "",
        days: int = 30,
        include_signals: bool = True,
    ) -> FactorReport:
        """生成单只股票的因子报告

        Args:
            symbol: 股票代码 (如 "600519")
            stock_name: 股票名称 (可选)
            days: 回溯天数
            include_signals: 是否包含详细信号
        """
        report = FactorReport(symbol=symbol, stock_name=stock_name)
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        try:
            self._compute_news_sentiment(report, symbol, cutoff, include_signals)
        except Exception as e:
            logger.warning(f"news_sentiment factor error for {symbol}: {e}")

        try:
            self._compute_event_signal(report, symbol, cutoff, include_signals)
        except Exception as e:
            logger.warning(f"event_signal factor error for {symbol}: {e}")

        try:
            self._compute_analyst_rating(report, symbol, cutoff, include_signals)
        except Exception as e:
            logger.warning(f"analyst_rating factor error for {symbol}: {e}")

        try:
            self._compute_fund_flow(report, symbol, include_signals)
        except Exception as e:
            logger.warning(f"fund_flow factor error for {symbol}: {e}")

        try:
            self._compute_momentum(report, symbol, days, include_signals)
        except Exception as e:
            logger.warning(f"momentum factor error for {symbol}: {e}")

        # 计算综合因子
        report.composite = self._weighted_composite(report)
        return report

    def generate_batch(
        self,
        symbols: list[str],
        stock_names: Optional[dict[str, str]] = None,
        days: int = 30,
    ) -> list[FactorReport]:
        """批量生成因子报告"""
        names = stock_names or {}
        return [
            self.generate(s, stock_name=names.get(s, ""), days=days) for s in symbols
        ]

    # ---- 各维度因子计算 ----

    def _compute_news_sentiment(
        self,
        report: FactorReport,
        symbol: str,
        cutoff: str,
        include_signals: bool,
    ) -> None:
        """新闻情绪因子: 加权平均新闻情绪"""
        from backend.storage.db import Database

        db = Database()
        with db.transaction() as conn:
            rows = conn.execute(
                """SELECT title, sentiment, importance, confidence, published_at
                   FROM news_items
                   WHERE published_at >= ? AND symbols LIKE ?
                   ORDER BY published_at DESC""",
                (cutoff, f'%"{symbol}"%'),
            ).fetchall()

        sentiments = []
        for row in rows:
            sent = row["sentiment"] or 0.0
            imp = row["importance"] or 0.5
            conf = row["confidence"] or 0.6
            weight = imp * conf
            sentiments.append((sent, weight, row["title"]))

        report.news_count = len(sentiments)
        if not sentiments:
            return

        total_weight = sum(w for _, w, _ in sentiments)
        if total_weight > 0:
            report.news_sentiment = max(
                -1.0, min(1.0, sum(s * w for s, w, _ in sentiments) / total_weight)
            )

        if include_signals:
            for sent, _, title in sentiments[:10]:
                report.signals.append(
                    {
                        "type": "news",
                        "title": title[:60],
                        "sentiment": round(sent, 2),
                    }
                )

    def _compute_event_signal(
        self,
        report: FactorReport,
        symbol: str,
        cutoff: str,
        include_signals: bool,
    ) -> None:
        """事件信号因子: 基于公告事件类型打分"""
        from backend.storage.db import Database

        db = Database()
        with db.transaction() as conn:
            rows = conn.execute(
                """SELECT title, category, importance, published_at
                   FROM announcements
                   WHERE symbol = ? AND published_at >= ?
                   ORDER BY published_at DESC""",
                (symbol, cutoff),
            ).fetchall()

        scores = []
        for row in rows:
            cat = (row["category"] or "").lower()
            imp = row["importance"] or 0.5
            base_score = _EVENT_CATEGORY_SCORES.get(cat, 0.0)
            # importance 加权
            score = base_score * imp
            scores.append((score, imp, row["title"], cat))

        report.event_count = len(scores)
        if not scores:
            return

        total_imp = sum(imp for _, imp, _, _ in scores)
        if total_imp > 0:
            report.event_signal = max(
                -1.0, min(1.0, sum(s for s, _, _, _ in scores) / total_imp)
            )

        if include_signals:
            for score, _, title, cat in scores[:10]:
                report.signals.append(
                    {
                        "type": "event",
                        "category": cat,
                        "title": title[:60],
                        "score": round(score, 2),
                    }
                )

    def _compute_analyst_rating(
        self,
        report: FactorReport,
        symbol: str,
        cutoff: str,
        include_signals: bool,
    ) -> None:
        """分析师评级因子: 评级打分 + 目标价溢价"""
        from backend.storage.db import Database

        db = Database()
        with db.transaction() as conn:
            rows = conn.execute(
                """SELECT title, rating, target_price, institution, published_at
                   FROM research_reports
                   WHERE published_at >= ? AND symbols LIKE ?
                   ORDER BY published_at DESC""",
                (cutoff, f'%"{symbol}"%'),
            ).fetchall()

        ratings = []
        for row in rows:
            rating_str = (row["rating"] or "").strip()
            rating_score = _RATING_SCORES.get(rating_str, None)

            # 模糊匹配
            if rating_score is None:
                for key, val in _RATING_SCORES.items():
                    if key in rating_str:
                        rating_score = val
                        break

            if rating_score is not None:
                ratings.append((rating_score, row["institution"], row["title"]))

        report.report_count = len(ratings)
        if not ratings:
            return

        report.analyst_rating = max(
            -1.0, min(1.0, sum(r for r, _, _ in ratings) / len(ratings))
        )

        if include_signals:
            for score, inst, title in ratings[:10]:
                report.signals.append(
                    {
                        "type": "analyst",
                        "institution": inst or "",
                        "title": title[:60],
                        "rating_score": round(score, 2),
                    }
                )

    def _compute_fund_flow(
        self,
        report: FactorReport,
        symbol: str,
        include_signals: bool,
    ) -> None:
        """资金流向因子: 主力净流入趋势"""
        try:
            from backend.fund_flow import (
                fetch_individual_fund_flow,
                summarize_fund_flow,
            )

            df = _call_with_timeout(
                lambda: fetch_individual_fund_flow(symbol, days=5),
                FUND_FLOW_FACTOR_TIMEOUT_SECONDS,
            )
            if df is None or len(df) == 0:
                report.degraded_inputs.append("fund_flow")
                report.missing_dimensions.append("fund_flow")
                if include_signals:
                    report.signals.append(
                        {
                            "type": "fund_flow",
                            "degraded": True,
                            "reason": "fund-flow provider returned no data",
                        }
                    )
                return
            if getattr(df, "attrs", {}).get("degraded"):
                report.degraded_inputs.append("fund_flow")
            summary = summarize_fund_flow(df, recent_days=5)
        except Exception as exc:
            report.degraded_inputs.append("fund_flow")
            report.missing_dimensions.append("fund_flow")
            if include_signals:
                report.signals.append(
                    {
                        "type": "fund_flow",
                        "degraded": True,
                        "reason": str(exc),
                    }
                )
            return

        if not summary:
            return

        # 主力净流入总额 (亿元) → 归一化
        main_total = summary.get("main_total_yi", 0)
        inflow_days = summary.get("inflow_days", 0)
        outflow_days = summary.get("outflow_days", 0)
        last_main_yi = summary.get("last_main_yi", 0)

        # 基于最近一日主力净流入和趋势打分
        # 大额净流入 (>1亿) → 强信号, 小额 → 弱信号
        if last_main_yi > 0:
            flow_score = min(1.0, last_main_yi / 5.0)  # 5亿以上满分
        elif last_main_yi < 0:
            flow_score = max(-1.0, last_main_yi / 5.0)
        else:
            flow_score = 0.0

        # 趋势加成: 连续流入/流出天数
        total_days = inflow_days + outflow_days
        if total_days > 0:
            trend = (inflow_days - outflow_days) / total_days
            flow_score = 0.7 * flow_score + 0.3 * trend

        report.fund_flow = max(-1.0, min(1.0, flow_score))

        if include_signals:
            report.signals.append(
                {
                    "type": "fund_flow",
                    "last_main_yi": round(last_main_yi, 2),
                    "main_total_yi": round(main_total, 2),
                    "inflow_days": inflow_days,
                    "outflow_days": outflow_days,
                }
            )

    def _compute_momentum(
        self,
        report: FactorReport,
        symbol: str,
        days: int,
        include_signals: bool,
    ) -> None:
        """价格动量因子: 涨跌幅 + 成交量变化"""
        from backend.price_store import get_prices

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = [
            row
            for row in get_prices(symbol, frequency="1d", limit=max(days * 2, 30))
            if str(row.get("date", "")) >= cutoff
        ]
        rows.sort(key=lambda row: str(row.get("date", "")))

        if len(rows) < 2:
            return

        # 短期动量: 近5日涨跌幅
        recent = rows[-5:] if len(rows) >= 5 else rows
        short_return = 0.0
        recent_first_close = float(recent[0].get("close") or 0)
        recent_last_close = float(recent[-1].get("close") or 0)
        if recent_first_close > 0:
            short_return = (recent_last_close - recent_first_close) / recent_first_close

        # 中期动量: 全周期涨跌幅
        mid_return = 0.0
        first_close = float(rows[0].get("close") or 0)
        last_close = float(rows[-1].get("close") or 0)
        if first_close > 0:
            mid_return = (last_close - first_close) / first_close

        # 成交量变化: 近期 vs 前期
        vol_score = 0.0
        if len(rows) >= 10:
            early_vol = sum(float(r.get("volume") or 0) for r in rows[: len(rows) // 2])
            late_vol = sum(float(r.get("volume") or 0) for r in rows[len(rows) // 2 :])
            if early_vol > 0:
                vol_change = (late_vol - early_vol) / early_vol
                vol_score = max(-1.0, min(1.0, vol_change))

        # 组合: 60% 短期动量 + 20% 中期动量 + 20% 量能变化
        momentum = (
            0.6 * max(-1.0, min(1.0, short_return * 10))
            + 0.2 * max(-1.0, min(1.0, mid_return * 5))
            + 0.2 * vol_score
        )

        report.momentum = max(-1.0, min(1.0, momentum))

        if include_signals:
            report.signals.append(
                {
                    "type": "momentum",
                    "short_return_pct": round(short_return * 100, 2),
                    "mid_return_pct": round(mid_return * 100, 2),
                    "volume_change_pct": round(vol_score * 100, 2),
                    "data_points": len(rows),
                }
            )

    def _weighted_composite(self, report: FactorReport) -> float:
        """加权计算综合因子"""
        factors = {
            "news_sentiment": report.news_sentiment,
            "event_signal": report.event_signal,
            "analyst_rating": report.analyst_rating,
            "fund_flow": report.fund_flow,
            "momentum": report.momentum,
        }

        total_weight = 0.0
        weighted_sum = 0.0
        for name, value in factors.items():
            w = self._weights.get(name, 0.0)
            if w > 0:
                weighted_sum += value * w
                total_weight += w

        if total_weight > 0:
            return max(-1.0, min(1.0, weighted_sum / total_weight))
        return 0.0


# ---- 便捷函数 ----

_generator: Optional[FactorGenerator] = None


def get_factor_generator() -> FactorGenerator:
    global _generator
    if _generator is None:
        _generator = FactorGenerator()
    return _generator


def generate_factor_report(
    symbol: str, stock_name: str = "", days: int = 30
) -> FactorReport:
    """生成单只股票因子报告"""
    return get_factor_generator().generate(symbol, stock_name, days)


def generate_factor_batch(
    symbols: list[str],
    stock_names: Optional[dict[str, str]] = None,
    days: int = 30,
) -> list[FactorReport]:
    """批量生成因子报告"""
    return get_factor_generator().generate_batch(symbols, stock_names, days)


def format_factor_summary(report: FactorReport) -> str:
    """格式化因子报告为文本摘要, 供 Agent prompt 使用"""
    lines = [
        f"==== 量化因子分析 ({report.symbol} {report.stock_name}) ====",
        f"综合因子: {report.composite:+.2f}",
        "",
        "各维度因子:",
        f"  📰 新闻情绪: {report.news_sentiment:+.2f}  (样本: {report.news_count})",
        f"  📋 事件信号: {report.event_signal:+.2f}  (样本: {report.event_count})",
        f"  📊 分析师评级: {report.analyst_rating:+.2f}  (样本: {report.report_count})",
        f"  💰 资金流向: {report.fund_flow:+.2f}",
        f"  📈 价格动量: {report.momentum:+.2f}",
    ]

    if report.signals:
        lines.append("")
        lines.append("关键信号:")
        for sig in report.signals[:5]:
            sig_type = sig.get("type", "")
            if sig_type == "news":
                lines.append(
                    f"  - [新闻] {sig.get('title', '')} (情绪: {sig.get('sentiment', 0):+.2f})"
                )
            elif sig_type == "event":
                lines.append(
                    f"  - [公告:{sig.get('category', '')}] {sig.get('title', '')} (得分: {sig.get('score', 0):+.2f})"
                )
            elif sig_type == "analyst":
                lines.append(
                    f"  - [研报] {sig.get('institution', '')}: {sig.get('title', '')} (评级: {sig.get('rating_score', 0):+.2f})"
                )
            elif sig_type == "fund_flow":
                lines.append(
                    f"  - [资金] 主力净流入: {sig.get('last_main_yi', 0):.2f}亿, 连续流入{sig.get('inflow_days', 0)}天"
                )
            elif sig_type == "momentum":
                lines.append(
                    f"  - [动量] 近期涨幅: {sig.get('short_return_pct', 0):+.1f}%, 量能变化: {sig.get('volume_change_pct', 0):+.1f}%"
                )

    return "\n".join(lines)
