"""
Vision Agent: 视觉分析编排。

职责：
- 编排完整的K线图分析流程
- 图片检测 → K线解读 → 行情验证 → 综合分析
- 处理用户追问和缺失信息补充
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

from backend.vision.image_loader import load_image
from backend.vision.chart_detector import detect_chart, ChartDetectionResult
from backend.vision.kline_interpreter import interpret_kline, KlineAnalysis
from backend.provider_timeout import call_with_timeout

logger = logging.getLogger(__name__)

VISION_PRICE_TIMEOUT_SECONDS = 8.0


@dataclass
class RealDataComparison:
    """视觉分析与真实行情数据的交叉验证结果"""

    # 真实数据计算出的趋势 (bullish / bearish / sideways)
    real_trend: str = ""
    # 趋势是否一致
    trend_consistent: bool = True
    # 真实最近收盘价
    latest_close: float = 0.0
    # 真实价格区间 (最近 N 个交易日)
    real_price_range: dict = field(default_factory=dict)  # {"low": x, "high": x}
    # 支撑位验证: {vision_level: {"near_pivot": bool, "actual_low": float}}
    support_validation: dict = field(default_factory=dict)
    # 压力位验证: {vision_level: {"near_pivot": bool, "actual_high": float}}
    resistance_validation: dict = field(default_factory=dict)
    # 冲突警告列表
    conflicts: list = field(default_factory=list)
    # 数据是否成功获取
    data_available: bool = False
    # 数据来源
    data_source: str = ""
    # 原始数据摘要 (最近 5 个交易日)
    recent_ohlcv: list = field(default_factory=list)


@dataclass
class VisionAnalysisResult:
    """视觉分析完整结果"""

    detection: Optional[ChartDetectionResult] = None
    kline_analysis: Optional[KlineAnalysis] = None
    real_data: Optional[RealDataComparison] = None
    needs_more_info: bool = False
    missing_info: list = field(default_factory=list)
    disclaimer: str = ""
    summary: str = ""
    ok: bool = False


# 需要用户补充的信息清单
REQUIRED_INFO = {
    "ticker": "请提供股票代码（如 600519、AAPL）",
    "market": "请确认市场（A股/港股/美股）",
    "period": "请确认分析周期（日线/周线/月线）",
}


def _fetch_real_price_data(
    ticker: str,
    market: str = "CN",
    days: int = 60,
) -> list[dict]:
    """
    获取真实 OHLCV 行情数据。

    优先使用 ProviderRegistry，失败时回退到 price_fetcher。

    Args:
        ticker: 股票代码
        market: 市场 (CN/HK/US)
        days: 获取最近 N 个交易日

    Returns:
        list[dict] 每条含 date/open/high/low/close/volume，按日期升序
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")

    # 优先尝试 ProviderRegistry
    try:
        from backend.providers.registry import get_registry

        registry = get_registry()
        raw = call_with_timeout(
            lambda: registry.get(
                data_type="prices",
                market=market,
                symbol=ticker,
                start_date=start_date,
                end_date=end_date,
            ),
            VISION_PRICE_TIMEOUT_SECONDS,
            name="vision-price-provider",
        )
        if raw and isinstance(raw, list) and len(raw) > 0:
            # 确保每条记录有必要的字段
            cleaned = []
            for row in raw:
                cleaned.append(
                    {
                        "date": str(row.get("date", "")),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": float(row.get("volume", 0)),
                        "source": row.get("source", "registry"),
                    }
                )
            # 按日期升序排列，取最近 days 条
            cleaned.sort(key=lambda x: x["date"])
            return cleaned[-days:]
    except Exception as e:
        logger.debug("ProviderRegistry 获取价格数据失败: %s", e)

    # 回退到 price_fetcher
    try:
        from backend.price_fetcher import get_price_range

        series = call_with_timeout(
            lambda: get_price_range(ticker, start_date, days),
            VISION_PRICE_TIMEOUT_SECONDS,
            name="vision-price-fetcher",
        )
        if series:
            result = []
            for date_str, close in series:
                result.append(
                    {
                        "date": date_str,
                        "open": 0.0,
                        "high": 0.0,
                        "low": 0.0,
                        "close": close,
                        "volume": 0.0,
                        "source": "price_fetcher",
                    }
                )
            return result
    except Exception as e:
        logger.debug("price_fetcher 获取价格数据失败: %s", e)

    return []


def _compute_real_trend(ohlcv: list[dict], lookback: int = 20) -> str:
    """
    根据真实收盘价计算趋势。

    使用简单线性回归斜率判断:
    - 斜率 > 0 且幅度 > 1%: bullish
    - 斜率 < 0 且幅度 > 1%: bearish
    - 否则: sideways

    Args:
        ohlcv: OHLCV 数据列表 (日期升序)
        lookback: 回看天数

    Returns:
        "bullish" / "bearish" / "sideways"
    """
    closes = [d["close"] for d in ohlcv if d["close"] > 0]
    if len(closes) < 5:
        return "unknown"

    recent = closes[-lookback:] if len(closes) >= lookback else closes
    n = len(recent)
    x_mean = (n - 1) / 2.0
    y_mean = sum(recent) / n

    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return "sideways"

    slope = numerator / denominator
    pct_change = (slope * n) / y_mean * 100 if y_mean != 0 else 0

    if pct_change > 1.0:
        return "bullish"
    elif pct_change < -1.0:
        return "bearish"
    return "sideways"


def _normalize_trend_label(trend: str) -> str:
    """
    将中英文趋势标签统一为标准标签。

    Returns:
        "bullish" / "bearish" / "sideways" / ""
    """
    t = trend.strip().lower()
    if any(k in t for k in ("上升", "上涨", "看涨", "多头", "bull", "up")):
        return "bullish"
    if any(k in t for k in ("下降", "下跌", "看跌", "空头", "bear", "down")):
        return "bearish"
    if any(k in t for k in ("震荡", "横盘", "盘整", "sideways", "range", "整理")):
        return "sideways"
    return ""


def _extract_numeric_levels(levels: list) -> list[float]:
    """
    从支撑位/压力位列表中提取数值。

    处理格式: "12.50", "12.50元", "$120", 12.5 等。
    """
    import re

    nums = []
    for lv in levels:
        if isinstance(lv, (int, float)):
            nums.append(float(lv))
        elif isinstance(lv, str):
            m = re.search(r"[\d]+\.?\d*", lv.replace(",", ""))
            if m:
                try:
                    nums.append(float(m.group()))
                except ValueError:
                    pass
    return nums


def _validate_price_levels(
    vision_levels: list,
    ohlcv: list[dict],
    level_type: str = "support",
) -> dict:
    """
    验证视觉模型识别的支撑/压力位是否与真实价格数据吻合。

    对每个视觉识别的价位:
    - 检查真实价格是否在该价位附近有触碰/反弹
    - 检查该价位是否落在真实价格区间的合理范围内

    Args:
        vision_levels: 视觉模型识别的价位列表
        ohlcv: OHLCV 数据
        level_type: "support" 或 "resistance"

    Returns:
        dict {level_str: {"near_pivot": bool, "actual_price": float, "note": str}}
    """
    numeric_levels = _extract_numeric_levels(vision_levels)
    if not numeric_levels or not ohlcv:
        return {}

    all_lows = [d["low"] for d in ohlcv if d.get("low", 0) > 0]
    all_highs = [d["high"] for d in ohlcv if d.get("high", 0) > 0]
    all_closes = [d["close"] for d in ohlcv if d["close"] > 0]

    if not all_closes:
        return {}

    data_min = min(all_lows) if all_lows else min(all_closes)
    data_max = max(all_highs) if all_highs else max(all_closes)
    data_range = data_max - data_min if data_max != data_min else 1.0
    tolerance = data_range * 0.03  # 3% 容差

    validation = {}
    for i, level in enumerate(numeric_levels):
        key = str(vision_levels[i]) if i < len(vision_levels) else str(level)

        if level_type == "support":
            # 支撑位应接近真实数据中的某个低点
            nearest_low = min(all_lows, key=lambda x: abs(x - level)) if all_lows else 0
            near_pivot = abs(nearest_low - level) <= tolerance
            in_range = data_min * 0.9 <= level <= data_max * 1.1
            validation[key] = {
                "near_pivot": near_pivot,
                "actual_price": nearest_low,
                "in_data_range": in_range,
                "note": (
                    f"接近真实低点 {nearest_low:.2f}"
                    if near_pivot
                    else f"偏离真实低点 {nearest_low:.2f} (差 {abs(nearest_low - level):.2f})"
                ),
            }
        else:
            # 压力位应接近真实数据中的某个高点
            nearest_high = max(all_highs, key=lambda x: abs(x - level)) if all_highs else 0
            # 修正: 取最接近的高点而非绝对值最大的
            if all_highs:
                nearest_high = min(all_highs, key=lambda x: abs(x - level))
            near_pivot = abs(nearest_high - level) <= tolerance
            in_range = data_min * 0.9 <= level <= data_max * 1.1
            validation[key] = {
                "near_pivot": near_pivot,
                "actual_price": nearest_high,
                "in_data_range": in_range,
                "note": (
                    f"接近真实高点 {nearest_high:.2f}"
                    if near_pivot
                    else f"偏离真实高点 {nearest_high:.2f} (差 {abs(nearest_high - level):.2f})"
                ),
            }

    return validation


def _compare_vision_with_real_data(
    kline: KlineAnalysis,
    ohlcv: list[dict],
) -> RealDataComparison:
    """
    将视觉分析结果与真实行情数据进行交叉比对。

    Args:
        kline: 视觉模型的 K 线分析结果
        ohlcv: 真实 OHLCV 数据

    Returns:
        RealDataComparison 交叉验证结果
    """
    comparison = RealDataComparison(data_available=bool(ohlcv))

    if not ohlcv:
        return comparison

    # 1. 计算真实趋势
    real_trend = _compute_real_trend(ohlcv)
    comparison.real_trend = real_trend

    # 2. 趋势一致性检查
    vision_trend = _normalize_trend_label(kline.trend)
    if vision_trend and real_trend and real_trend != "unknown":
        comparison.trend_consistent = vision_trend == real_trend
        if not comparison.trend_consistent:
            comparison.conflicts.append(f"趋势冲突: 视觉判断为 {kline.trend}，但真实行情数据显示 {real_trend}")

    # 3. 真实价格统计
    valid_closes = [d["close"] for d in ohlcv if d["close"] > 0]
    if valid_closes:
        comparison.latest_close = valid_closes[-1]
        all_lows = [d["low"] for d in ohlcv if d.get("low", 0) > 0]
        all_highs = [d["high"] for d in ohlcv if d.get("high", 0) > 0]
        comparison.real_price_range = {
            "low": min(all_lows) if all_lows else min(valid_closes),
            "high": max(all_highs) if all_highs else max(valid_closes),
        }

    # 4. 支撑位验证
    if kline.support_levels:
        comparison.support_validation = _validate_price_levels(kline.support_levels, ohlcv, "support")
        # 检查是否有支撑位完全偏离真实数据
        for level_str, info in comparison.support_validation.items():
            if not info.get("in_data_range", True):
                comparison.conflicts.append(
                    f"支撑位 {level_str} 不在真实价格区间 "
                    f"[{comparison.real_price_range.get('low', 0):.2f} - "
                    f"{comparison.real_price_range.get('high', 0):.2f}] 内"
                )

    # 5. 压力位验证
    if kline.resistance_levels:
        comparison.resistance_validation = _validate_price_levels(kline.resistance_levels, ohlcv, "resistance")
        for level_str, info in comparison.resistance_validation.items():
            if not info.get("in_data_range", True):
                comparison.conflicts.append(
                    f"压力位 {level_str} 不在真实价格区间 "
                    f"[{comparison.real_price_range.get('low', 0):.2f} - "
                    f"{comparison.real_price_range.get('high', 0):.2f}] 内"
                )

    # 6. 保存最近 5 个交易日数据摘要
    comparison.recent_ohlcv = ohlcv[-5:] if len(ohlcv) >= 5 else ohlcv
    if comparison.recent_ohlcv:
        comparison.data_source = comparison.recent_ohlcv[0].get("source", "unknown")

    return comparison


def analyze_image(
    image_base64: str,
    mime_type: str = "image/png",
    user_context: str = "",
    vendor: str = "deepseek",
    model: str = "deepseek-chat",
    ticker: str = "",
) -> VisionAnalysisResult:
    """
    完整的图片分析流程，包含真实行情数据交叉验证。

    流程:
    1. 检测图片类型 (detect_chart)
    2. 检查缺失信息
    3. K线解读 (interpret_kline)
    4. 获取真实行情数据并交叉验证
    5. 组装结果

    Args:
        image_base64: 图片 base64 编码
        mime_type: MIME 类型
        user_context: 用户提供的额外上下文
        vendor: 视觉模型供应商
        model: 视觉模型名称

    Returns:
        VisionAnalysisResult 完整分析结果
    """
    # Step 1: 检测图片类型
    detection = detect_chart(image_base64, mime_type, vendor, model)

    if not detection.is_chart:
        return VisionAnalysisResult(
            detection=detection,
            summary="图片未识别为金融图表。请上传K线图、行情截图等金融相关图片。",
            ok=False,
        )

    # Step 2: 检查缺失信息（用户提供 ticker 时跳过追问）
    if ticker and not detection.ticker:
        detection.ticker = ticker
    missing = []
    if not detection.ticker and "ticker" not in user_context.lower() and not ticker:
        missing.append(REQUIRED_INFO["ticker"])
    if not detection.period:
        missing.append(REQUIRED_INFO["period"])

    # Step 3: K线解读
    context_parts = []
    if detection.ticker:
        context_parts.append(f"标的: {detection.ticker} ({detection.ticker_name})")
    if detection.period:
        context_parts.append(f"周期: {detection.period}")
    if user_context:
        context_parts.append(user_context)
    context = " | ".join(context_parts) if context_parts else ""

    kline = interpret_kline(image_base64, mime_type, context, vendor, model)

    # Step 3.5: 市场推断
    if detection.ticker and not detection.market:
        try:
            from backend.price_store import get_market

            detection.market = get_market(detection.ticker)
        except Exception:
            detection.market = "CN"

    # Step 4: 真实行情数据交叉验证
    real_comparison = None
    if detection.ticker:
        try:
            market = detection.market or "CN"
            ohlcv = _fetch_real_price_data(detection.ticker, market)
            if ohlcv:
                real_comparison = _compare_vision_with_real_data(kline, ohlcv)
                logger.info(
                    "交叉验证完成: ticker=%s, trend_consistent=%s, conflicts=%d",
                    detection.ticker,
                    real_comparison.trend_consistent,
                    len(real_comparison.conflicts),
                )
            else:
                logger.info("未能获取到 %s 的真实行情数据，跳过交叉验证", detection.ticker)
                real_comparison = RealDataComparison(data_available=False)
        except Exception as e:
            logger.warning("交叉验证过程出错: %s", e)
            real_comparison = RealDataComparison(data_available=False)

    # Step 5: 组装结果
    disclaimer = (
        "注意：以上分析仅基于K线图形观察，可能与实际行情存在偏差。"
        "请结合实时行情数据验证关键价位。本分析不构成投资建议。"
    )

    # 置信度门控
    confidence_warnings = []
    if detection.confidence > 0 and detection.confidence < 0.6:
        confidence_warnings.append("图表识别置信度较低，结果仅供参考")
    if kline.confidence > 0 and kline.confidence < 0.6:
        confidence_warnings.append("K线解读置信度较低，建议结合其他分析")

    # 生成结构化报告
    try:
        from backend.vision.report_generator import generate_vision_report

        _temp_result = VisionAnalysisResult(
            detection=detection,
            kline_analysis=kline,
            real_data=real_comparison,
            needs_more_info=bool(missing),
            missing_info=missing,
            disclaimer=disclaimer,
            summary="",
            ok=True,
        )
        structured_summary = generate_vision_report(_temp_result)
    except Exception:
        # 降级到简单文本
        summary_parts = []
        if kline.trend:
            summary_parts.append(f"趋势判断: {kline.trend}")
        if kline.summary:
            summary_parts.append(kline.summary)
        if real_comparison and real_comparison.data_available:
            if real_comparison.conflicts:
                summary_parts.append(f"[交叉验证] 发现 {len(real_comparison.conflicts)} 处冲突:")
                for conflict in real_comparison.conflicts:
                    summary_parts.append(f"  - {conflict}")
            else:
                summary_parts.append("[交叉验证] 视觉分析与真实行情数据一致")
            if real_comparison.latest_close > 0:
                summary_parts.append(f"最新收盘价: {real_comparison.latest_close:.2f}")
        if missing:
            summary_parts.append(f"需要补充: {', '.join(missing)}")
        structured_summary = "\n".join(summary_parts)

    # 添加置信度警告
    if confidence_warnings:
        structured_summary += "\n\n## ⚠️ 置信度警告\n"
        for w in confidence_warnings:
            structured_summary += f"\n- {w}"

    return VisionAnalysisResult(
        detection=detection,
        kline_analysis=kline,
        real_data=real_comparison,
        needs_more_info=bool(missing),
        missing_info=missing,
        disclaimer=disclaimer,
        summary=structured_summary,
        ok=True,
    )


def analyze_uploaded_file(
    file_path: str,
    user_context: str = "",
    vendor: str = "deepseek",
    model: str = "deepseek-chat",
) -> VisionAnalysisResult:
    """分析上传的图片文件"""
    img = load_image(file_path)
    if not img:
        return VisionAnalysisResult(
            summary="无法加载图片文件。请确保文件格式为 PNG/JPG/GIF/WebP，大小不超过 20MB。",
            ok=False,
        )
    return analyze_image(img.base64_data, img.mime_type, user_context, vendor, model)
