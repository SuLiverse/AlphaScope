"""Local Beta (v0.50) 验收测试 — 8 个验收标准端到端验证"""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


def _pyproject_version() -> str:
    """pyproject.toml 的 project.version —— 版本号单一来源。"""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ========== 1. 一键启动 ==========


class TestOneClickStartup:
    """验收标准 1: 一键启动脚本存在"""

    def test_start_bat_exists(self):
        bat = Path("scripts/start_local.bat")
        assert bat.exists(), "start_local.bat 不存在"

    def test_start_ps1_exists(self):
        ps1 = Path("scripts/start_local.ps1")
        assert ps1.exists(), "start_local.ps1 不存在"

    def test_stop_ps1_exists(self):
        ps1 = Path("scripts/stop_local.ps1")
        assert ps1.exists(), "stop_local.ps1 不存在"

    def test_check_env_exists(self):
        check = Path("scripts/check_env.py")
        assert check.exists(), "check_env.py 不存在"


# ========== 2. 配置 API Key ==========


class TestAPIKeyConfig:
    """验收标准 2: API Key 配置"""

    @pytest.mark.anyio
    async def test_settings_providers_endpoint(self, client):
        """GET /api/settings/providers 可访问"""
        with patch("backend.settings_store.list_providers", return_value=[]):
            resp = await client.get("/api/settings/providers")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_settings_save_provider(self, client):
        """POST /api/settings/providers 可保存"""
        mock_provider = {
            "id": "test-p",
            "name": "test",
            "type": "openai_compatible",
            "base_url": "http://localhost",
            "api_key_masked": "***abc",
            "enabled": True,
        }
        with patch("backend.settings_store.save_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/settings/providers",
                json={
                    "id": "test-p",
                    "name": "test",
                    "base_url": "http://localhost",
                    "api_key": "sk-abc123",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ========== 3. 专家团分析 ==========


class TestExpertAnalysis:
    """验收标准 3: 专家团分析"""

    @pytest.mark.anyio
    async def test_chat_stream_expert_mode(self, client):
        """POST /api/chat/stream mode=expert 返回 SSE"""
        mock_orch = MagicMock()
        mock_orch.new_conversation.return_value = "test-conv"
        mock_orch.send_message.return_value = {
            "mode": "expert",
            "content": "专家团分析结果",
            "evidence": [],
            "agents": {},
        }

        with patch(
            "backend.ai_assistant.orchestrator.ChatOrchestrator",
            return_value=mock_orch,
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={
                    "message": "分析茅台",
                    "mode": "expert",
                    "stock_symbol": "600519",
                },
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "expert" in resp.text


# ========== 4. K 线图上传 ==========


class TestKlineUpload:
    """验收标准 4: K 线图上传与分析"""

    @pytest.mark.anyio
    async def test_file_upload_png(self, client):
        """POST /api/files/upload 上传 PNG"""
        resp = await client.post(
            "/api/files/upload",
            files={"file": ("kline.png", PNG_BYTES, "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_vision_analyze(self, client):
        """POST /api/vision/analyze 图片分析"""
        from backend.vision.chart_detector import ChartDetectionResult
        from backend.vision.vision_agent import VisionAnalysisResult

        mock_result = VisionAnalysisResult(
            detection=ChartDetectionResult(is_chart=True, chart_type="kline", ticker="600519"),
            summary="上升趋势",
            ok=True,
        )

        with patch("backend.vision.vision_agent.analyze_image", return_value=mock_result):
            resp = await client.post(
                "/api/vision/analyze",
                json={"image_base64": "dGVzdA==", "mime_type": "image/png"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["ticker"] == "600519"


# ========== 5. 报告生成与保存 ==========


class TestReportGeneration:
    """验收标准 5: 报告生成与保存"""

    @pytest.mark.anyio
    async def test_report_generation(self, client):
        """GET /api/reports/{id} 生成报告"""
        mock_conv = {"id": "c1", "title": "测试", "mode": "standard"}
        mock_msgs = [
            {"role": "user", "content": "分析茅台", "metadata": "{}"},
            {
                "role": "assistant",
                "content": "茅台分析结果",
                "metadata": '{"mode":"standard","evidence":[{"type":"fundamental","claim":"业绩增长"}]}',
            },
        ]

        with (
            patch(
                "backend.ai_assistant.conversation_store.ConversationStore.get_conversation",
                return_value=mock_conv,
            ),
            patch(
                "backend.ai_assistant.conversation_store.ConversationStore.get_messages",
                return_value=mock_msgs,
            ),
        ):
            resp = await client.get("/api/reports/c1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "茅台" in data["data"]["content"]

    @pytest.mark.anyio
    async def test_archive_list(self, client):
        """GET /api/archive 列出归档报告"""
        with patch("backend.archive.list_reports", return_value=[]):
            resp = await client.get("/api/archive")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ========== 6. 历史持久化 ==========


class TestHistoryPersistence:
    """验收标准 6: 重启后历史仍在"""

    @pytest.mark.anyio
    async def test_conversation_persistence(self, client):
        """会话 CRUD 全流程"""
        # 创建
        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.create_conversation",
            return_value="conv-123",
        ):
            resp = await client.post("/api/conversations", json={"title": "持久化测试", "mode": "free"})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "conv-123"

        # 列出
        mock_list = [
            {
                "id": "conv-123",
                "title": "持久化测试",
                "mode": "free",
                "message_count": 0,
            }
        ]
        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.list_conversations",
            return_value=mock_list,
        ):
            resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["conversations"]) == 1

    @pytest.mark.anyio
    async def test_conversation_get_and_delete(self, client):
        """会话详情和删除"""
        mock_conv = {"id": "conv-123", "title": "test"}
        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.get_conversation",
            return_value=mock_conv,
        ):
            resp = await client.get("/api/conversations/conv-123")
        assert resp.json()["data"]["conversation"]["id"] == "conv-123"

        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.delete_conversation",
            return_value=True,
        ):
            resp = await client.delete("/api/conversations/conv-123")
        assert resp.json()["success"] is True


# ========== 7. 无 ChromaDB 不崩 ==========


class TestNoChromaDegradation:
    """验收标准 7: 无 ChromaDB 时优雅降级"""

    @pytest.mark.anyio
    async def test_health_without_chromadb(self, client):
        """无 ChromaDB 时 /health 正常"""
        with patch("backend.rag.vector_store.VectorStore._get_client", return_value=None):
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "healthy"

    @pytest.mark.anyio
    async def test_search_fallback_to_sqlite(self, client):
        """知识库搜索降级到 SQLite"""
        with patch(
            "backend.rag.vector_store.VectorStore",
            side_effect=RuntimeError("chromadb 未安装"),
        ):
            with patch("backend.file_store.search_documents", return_value=[]):
                resp = await client.post("/api/knowledge/search", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ========== 8. 无数据源不崩 ==========


class TestNoDataSourceDegradation:
    """验收标准 8: 无数据源时不崩溃"""

    @pytest.mark.anyio
    async def test_providers_health_endpoint(self, client):
        """GET /api/providers/health 正常返回"""
        resp = await client.get("/api/providers/health")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_analysis_with_no_providers(self, client):
        """无 Provider 时分析不崩溃"""
        mock_orch = MagicMock()
        mock_orch.new_conversation.return_value = "test"
        mock_orch.send_message.return_value = {
            "mode": "standard",
            "content": "数据源不可用",
            "evidence": [],
            "agents": {},
        }

        with patch(
            "backend.ai_assistant.orchestrator.ChatOrchestrator",
            return_value=mock_orch,
        ):
            resp = await client.post(
                "/api/chat/stream",
                json={"message": "test", "mode": "standard"},
            )
        assert resp.status_code == 200


# ========== 版本号 ==========


class TestVersion:
    """版本号验证"""

    @pytest.mark.anyio
    async def test_version_matches_pyproject(self, client):
        """/health 版本应与 pyproject.toml 的 project.version 一致(单一来源)"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["version"] == _pyproject_version()
