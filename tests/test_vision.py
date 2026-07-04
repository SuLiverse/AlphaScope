"""Vision 图表分析测试"""

from __future__ import annotations


def test_vision_schemas_import():
    """Vision 相关 schema 可正常导入"""
    from backend.schemas.api import VisionRequest, KlineAnalysisData, RealDataComparison

    req = VisionRequest(image_base64="dGVzdA==")
    assert req.mime_type == "image/png"
    assert req.ticker == ""

    kline = KlineAnalysisData(trend="bullish", summary="上升趋势")
    assert kline.trend == "bullish"
    assert kline.support_levels == []

    real = RealDataComparison(real_trend="bullish", trend_consistent=True, latest_close=100.0)
    assert real.trend_consistent is True
    assert real.conflicts == []


def test_vision_result_with_ticker():
    """VisionRequest 支持 ticker 参数"""
    from backend.schemas.api import VisionRequest

    req = VisionRequest(
        image_base64="dGVzdA==",
        ticker="600519",
        user_context="贵州茅台",
    )
    assert req.ticker == "600519"


def test_image_loader_supported_formats():
    """image_loader 支持常见图片格式"""
    from backend.vision.image_loader import SUPPORTED_FORMATS

    assert ".png" in SUPPORTED_FORMATS
    assert ".jpg" in SUPPORTED_FORMATS
    assert ".jpeg" in SUPPORTED_FORMATS
    assert ".gif" in SUPPORTED_FORMATS
    assert ".webp" in SUPPORTED_FORMATS


def test_image_loader_from_bytes():
    """load_image_from_bytes 处理空数据"""
    from backend.vision.image_loader import load_image_from_bytes

    # 空数据：size_bytes 为 0
    result = load_image_from_bytes(b"", "test.png")
    assert result is not None
    assert result.size_bytes == 0


def test_image_loader_from_bytes_valid():
    """load_image_from_bytes 处理有效数据"""
    import base64
    from backend.vision.image_loader import load_image_from_bytes

    # 创建一个最小的有效图片数据
    data = base64.b64decode("dGVzdA==")
    result = load_image_from_bytes(data, "test.png")
    # 应该成功加载（即使是非图片数据，只要格式和大小OK）
    assert result is not None
    assert result.filename == "test.png"
    assert result.size_bytes > 0


def test_chart_detection_result_defaults():
    """ChartDetectionResult 默认值正确"""
    from backend.vision.chart_detector import ChartDetectionResult

    r = ChartDetectionResult(is_chart=False)
    assert r.is_chart is False
    assert r.chart_type == ""
    assert r.ticker == ""
    assert r.confidence == 0.0


def test_kline_analysis_defaults():
    """KlineAnalysis 默认值正确"""
    from backend.vision.kline_interpreter import KlineAnalysis

    k = KlineAnalysis()
    assert k.trend == ""
    assert k.support_levels == []
    assert k.resistance_levels == []
    assert k.patterns == []
    assert k.confidence == 0.0


def test_vision_analysis_result_defaults():
    """VisionAnalysisResult 默认值正确"""
    from backend.vision.vision_agent import VisionAnalysisResult

    r = VisionAnalysisResult()
    assert r.ok is False  # 默认 False
    assert r.needs_more_info is False
    assert r.missing_info == []
    assert r.summary == ""


def test_normalize_trend_label():
    """_normalize_trend_label 正确映射趋势标签"""
    from backend.vision.vision_agent import _normalize_trend_label

    assert _normalize_trend_label("看涨") == "bullish"
    assert _normalize_trend_label("看跌") == "bearish"
    assert _normalize_trend_label("横盘") == "sideways"
    assert _normalize_trend_label("bullish") == "bullish"
    assert _normalize_trend_label("bearish") == "bearish"
    # unknown 标签映射为空字符串
    assert _normalize_trend_label("unknown") == ""


def test_extract_numeric_levels():
    """_extract_numeric_levels 从混合格式提取数值"""
    from backend.vision.vision_agent import _extract_numeric_levels

    levels = _extract_numeric_levels(["12.50", "1500元", "$120", "无数据"])
    assert 12.50 in levels
    assert 1500.0 in levels
    assert 120.0 in levels
    # "无数据" 不应产生数值


def test_orchestrator_has_vision_mode():
    """orchestrator 支持 VISION 模式"""
    from backend.ai_assistant.orchestrator import AnalysisMode

    assert AnalysisMode.VISION.value == "vision"
