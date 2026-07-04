"""Tests for Enhanced Vision Analysis — 视觉报告生成器 + API"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== 报告生成器测试 ==============


class TestVisionReportGenerator:
    """测试 generate_vision_report"""

    def test_report_with_ticker(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult
        from backend.vision.chart_detector import ChartDetectionResult
        from backend.vision.kline_interpreter import KlineAnalysis

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(
                is_chart=True,
                chart_type="kline",
                ticker="600519",
                ticker_name="贵州茅台",
                market="CN",
                period="日线",
                confidence=0.85,
            ),
            kline_analysis=KlineAnalysis(
                trend="上升趋势",
                support_levels=[1750, 1700],
                resistance_levels=[1850, 1900],
                patterns=["双底"],
                summary="整体呈上升趋势",
            ),
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "600519" in report
        assert "上升趋势" in report
        assert "支撑位" in report
        assert "压力位" in report
        assert "双底" in report
        assert "风险提示" in report

    def test_report_without_ticker(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult
        from backend.vision.chart_detector import ChartDetectionResult

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(is_chart=True, chart_type="kline"),
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "K线视觉分析报告" in report

    def test_report_with_conflicts(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult, RealDataComparison
        from backend.vision.chart_detector import ChartDetectionResult

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(is_chart=True, chart_type="kline", ticker="600519"),
            real_data=RealDataComparison(
                data_available=True,
                latest_close=1800.0,
                trend_consistent=False,
                conflicts=["趋势不一致: 视觉上升 vs 真实下降"],
                data_source="akshare",
            ),
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "交叉验证" in report
        assert "冲突" in report
        assert "1800" in report

    def test_report_no_real_data(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult, RealDataComparison
        from backend.vision.chart_detector import ChartDetectionResult

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(is_chart=True, chart_type="kline"),
            real_data=RealDataComparison(data_available=False),
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "未能获取" in report

    def test_report_with_missing_info(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult
        from backend.vision.chart_detector import ChartDetectionResult

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(is_chart=True, chart_type="kline"),
            needs_more_info=True,
            missing_info=["请提供股票代码", "请提供K线周期"],
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "需要补充" in report
        assert "股票代码" in report


# ============== 市场推断测试 ==============


class TestMarketInference:
    """测试从 ticker 推断 market"""

    def test_cn_inference(self):
        from backend.price_store import get_market

        assert get_market("600519") == "CN"
        assert get_market("000001") == "CN"

    def test_hk_inference(self):
        from backend.price_store import get_market

        assert get_market("00700") == "HK"


# ============== 置信度门控测试 ==============


class TestConfidenceGating:
    """测试置信度警告"""

    def test_low_confidence_in_report(self):
        from backend.vision.report_generator import generate_vision_report
        from backend.vision.vision_agent import VisionAnalysisResult
        from backend.vision.chart_detector import ChartDetectionResult

        result = VisionAnalysisResult(
            detection=ChartDetectionResult(
                is_chart=True,
                chart_type="kline",
                confidence=0.3,
            ),
            summary="",
            ok=True,
        )
        report = generate_vision_report(result)
        assert "30%" in report


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_vision_analyze_not_chart(client):
    """POST /api/vision/analyze 非图表图片"""
    mock_result = MagicMock()
    mock_result.ok = False
    mock_result.summary = "图片未识别为金融图表"
    mock_result.detection = MagicMock()
    mock_result.detection.is_chart = False
    mock_result.detection.ticker = ""
    mock_result.detection.ticker_name = ""
    mock_result.detection.chart_type = ""
    mock_result.detection.period = ""
    mock_result.needs_more_info = False
    mock_result.missing_info = []
    mock_result.kline_analysis = None
    mock_result.real_data = None

    with patch("backend.vision.vision_agent.analyze_image", return_value=mock_result):
        resp = await client.post(
            "/api/vision/analyze",
            json={"image_base64": "dGVzdA==", "mime_type": "image/png"},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_vision_analyze_with_ticker(client):
    """POST /api/vision/analyze 带 ticker"""
    mock_detection = MagicMock()
    mock_detection.is_chart = True
    mock_detection.ticker = "600519"
    mock_detection.ticker_name = "贵州茅台"
    mock_detection.chart_type = "kline"
    mock_detection.period = "日线"
    mock_detection.confidence = 0.8

    mock_kline = MagicMock()
    mock_kline.trend = "上升趋势"
    mock_kline.support_levels = [1750]
    mock_kline.resistance_levels = [1850]
    mock_kline.patterns = ["双底"]
    mock_kline.summary = "上升趋势"
    mock_kline.confidence = 0.8

    mock_real = MagicMock()
    mock_real.data_available = True
    mock_real.latest_close = 1800.0
    mock_real.real_trend = "bullish"
    mock_real.trend_consistent = True
    mock_real.conflicts = []
    mock_real.data_source = "akshare"

    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.summary = "# K线视觉分析报告\n\n上升趋势"
    mock_result.detection = mock_detection
    mock_result.kline_analysis = mock_kline
    mock_result.real_data = mock_real
    mock_result.needs_more_info = False
    mock_result.missing_info = []

    with patch("backend.vision.vision_agent.analyze_image", return_value=mock_result):
        resp = await client.post(
            "/api/vision/analyze",
            json={
                "image_base64": "dGVzdA==",
                "mime_type": "image/png",
                "ticker": "600519",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["ticker"] == "600519"
    assert data["data"]["is_chart"] is True


@pytest.mark.anyio
async def test_vision_report_endpoint(client):
    """POST /api/vision/report"""
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.detection = MagicMock()
    mock_result.detection.ticker = "600519"
    mock_result.detection.is_chart = True

    with (
        patch("backend.vision.vision_agent.analyze_image", return_value=mock_result),
        patch(
            "backend.vision.report_generator.generate_vision_report",
            return_value="# 报告内容",
        ),
    ):
        resp = await client.post(
            "/api/vision/report",
            json={"image_base64": "dGVzdA==", "mime_type": "image/png"},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "报告" in resp.json()["data"]["report"]
