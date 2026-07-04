"""Tests for report templates and evidence chain graph (v1.1.4)."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ================================================================
# Test Report Templates (pure logic)
# ================================================================


class TestReportTemplates:
    """Test report template generation."""

    def test_list_templates(self):
        from backend.ai_assistant.report_templates import list_templates

        templates = list_templates()
        assert len(templates) == 3
        names = [t["name"] for t in templates]
        assert "stock_deep_rating" in names
        assert "industry_thematic" in names
        assert "black_swan_warning" in names

    def test_get_template(self):
        from backend.ai_assistant.report_templates import get_template

        t = get_template("stock_deep_rating")
        assert t is not None
        assert t.name == "stock_deep_rating"
        assert len(t.sections) > 0

    def test_get_template_not_found(self):
        from backend.ai_assistant.report_templates import get_template

        assert get_template("nonexistent") is None

    def test_stock_deep_rating_generation(self):
        from backend.ai_assistant.report_templates import generate_report

        data = {
            "symbol": "600519",
            "name": "贵州茅台",
            "industry": "白酒",
            "fundamental_score": 85,
            "financials": {
                "营收": {"value": "1241亿", "yoy": "+16.2%"},
                "净利润": {"value": "627亿", "yoy": "+19.5%"},
            },
            "valuation": {"PE(TTM)": 33.5, "PB": 11.2},
            "risks": ["估值偏高", "政策风险"],
        }
        report = generate_report("stock_deep_rating", data)
        assert report is not None
        assert "600519" in report
        assert "贵州茅台" in report
        assert "强烈推荐" in report  # score 85 >= 80
        assert "免责声明" in report

    def test_stock_deep_rating_low_score(self):
        from backend.ai_assistant.report_templates import generate_report

        report = generate_report("stock_deep_rating", {"symbol": "000001", "fundamental_score": 15})
        assert report is not None
        assert "回避" in report

    def test_industry_thematic_generation(self):
        from backend.ai_assistant.report_templates import generate_report

        data = {
            "industry": "新能源",
            "overview": "新能源行业高速增长",
            "market": {"市场规模": "5万亿", "增速": "+25%"},
            "opportunities": ["储能", "光伏"],
            "risks": ["产能过剩", "补贴退坡"],
        }
        report = generate_report("industry_thematic", data)
        assert report is not None
        assert "新能源" in report
        assert "储能" in report

    def test_black_swan_generation(self):
        from backend.ai_assistant.report_templates import generate_report

        data = {
            "event": "某大型房企债务违约",
            "severity": "high",
            "description": "突发债务违约事件",
            "signals": [
                {"signal": "债券价格暴跌", "source": "市场数据", "confidence": 0.9},
            ],
            "impact": {"股市": "短期下跌", "债市": "信用利差扩大"},
            "recommendations": ["降低仓位", "增持现金"],
        }
        report = generate_report("black_swan_warning", data)
        assert report is not None
        assert "高" in report  # severity high
        assert "债券价格暴跌" in report

    def test_generate_report_unknown(self):
        from backend.ai_assistant.report_templates import generate_report

        assert generate_report("unknown_template", {}) is None

    def test_template_to_dict(self):
        from backend.ai_assistant.report_templates import get_template

        t = get_template("industry_thematic")
        d = t.to_dict()
        assert "name" in d
        assert "description" in d
        assert "sections" in d


# ================================================================
# Test Report Templates API
# ================================================================


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from backend.api.main import app

    return TestClient(app)


class TestReportTemplateAPI:
    """Test /api/reports/templates/* endpoints."""

    def test_list_templates(self, client):
        resp = client.get("/api/reports/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) == 3

    def test_get_template(self, client):
        resp = client.get("/api/reports/templates/stock_deep_rating")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["name"] == "stock_deep_rating"

    def test_get_template_not_found(self, client):
        resp = client.get("/api/reports/templates/nonexistent")
        assert resp.status_code == 404

    def test_generate_report(self, client):
        resp = client.post(
            "/api/reports/templates/generate",
            json={
                "template_name": "stock_deep_rating",
                "data": {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "fundamental_score": 75,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "600519" in data["data"]["content"]
        assert data["data"]["format"] == "markdown"

    def test_generate_unknown_template(self, client):
        resp = client.post(
            "/api/reports/templates/generate",
            json={"template_name": "unknown", "data": {}},
        )
        assert resp.status_code == 400


# ================================================================
# Test Evidence Chain Graph API
# ================================================================


class TestEvidenceChainGraph:
    """Test /api/evidence/chain/graph endpoint."""

    def test_build_graph_with_evidence(self, client):
        resp = client.post(
            "/api/evidence/chain/graph",
            json={
                "evidence": [
                    {
                        "id": "ev1",
                        "title": "茅台财报超预期",
                        "evidence_type": "fundamental",
                        "confidence": 0.9,
                        "source": "年报",
                        "symbols": ["600519"],
                        "claim": "茅台营收增长强劲",
                    },
                    {
                        "id": "ev2",
                        "title": "白酒板块资金流入",
                        "evidence_type": "fund_flow",
                        "confidence": 0.7,
                        "source": "资金流向",
                        "symbols": ["600519"],
                        "claim": "主力资金持续流入白酒板块",
                    },
                    {
                        "id": "ev3",
                        "title": "消费行业政策利好",
                        "evidence_type": "news",
                        "confidence": 0.6,
                        "source": "新闻",
                        "symbols": [],
                        "claim": "消费刺激政策出台",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]["nodes"]) == 3
        # ev1 and ev2 share symbol 600519, should have an edge
        assert len(data["data"]["edges"]) >= 1
        assert "pillars" in data["data"]

    def test_build_graph_empty(self, client):
        resp = client.post(
            "/api/evidence/chain/graph",
            json={"evidence": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]["nodes"]) == 0
