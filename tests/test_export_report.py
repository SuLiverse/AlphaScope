"""研报导出 API — /api/export/report/{task_id}.md 契约测试。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


def _wait_done(task_id: str, timeout: float = 10.0) -> dict:
    from backend.task_queue import TaskQueue

    deadline = time.time() + timeout
    tq = TaskQueue()
    while time.time() < deadline:
        task = tq.get_task(task_id)
        if task and task.get("status") in {"success", "failed", "cancelled"}:
            return task or {}
        time.sleep(0.05)
    return tq.get_task(task_id) or {}


def _submit_with_result(result: dict, *, template: str = "standard") -> str:
    from backend.task_queue import TaskQueue

    def _run():
        return result

    return TaskQueue().submit(
        task_type="analysis",
        func=_run,
        input_data={
            "stock_symbol": "600519",
            "stock_name": "贵州茅台",
            "mode": "deep",
            "report_template": template,
        },
    )


def test_export_report_standard_template(client):
    task_id = _submit_with_result(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "summary": {"final": "建议买入", "score": 72, "rating": "推荐"},
            "chairman_summary": "主席综合:基本面稳健,估值合理。",
            "agents": {
                "fundamental": {
                    "name": "基本面Agent",
                    "signal": "买入",
                    "confidence": 80,
                    "reason": "ROE 稳定高位",
                    "risks": ["行业增速放缓"],
                }
            },
            "critic": {"ok": True, "divergence": {"summary": "分歧较小"}},
        },
        template="standard",
    )
    _wait_done(task_id)
    r = client.get(f"/api/export/report/{task_id}.md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    body = r.text
    # 标准范式标题
    assert "个股深度评级研究报告" in body
    # 标的与评级
    assert "贵州茅台" in body and "600519" in body
    assert "买入" in body or "建议买入" in body
    # 免责声明始终存在
    assert "不构成投资建议" in body
    # 下载文件名
    assert "attachment" in r.headers["content-disposition"]


def test_export_report_template_switch(client):
    """macro / risk 范式应产出不同的标题框架。"""
    for template, expected_title in [
        ("macro", "行业及产业链专题跟踪报告"),
        ("risk", "黑天鹅情绪避险与信用预警评估"),
    ]:
        task_id = _submit_with_result(
            {"symbol": "000001", "name": "平安银行", "summary": {"final": "建议观望"}},
            template=template,
        )
        _wait_done(task_id)
        r = client.get(f"/api/export/report/{task_id}.md")
        assert r.status_code == 200
        assert expected_title in r.text


def test_export_report_missing_task_404(client):
    r = client.get("/api/export/report/nonexistent_task.md")
    assert r.status_code == 404


def test_async_analysis_accepts_report_template(client):
    """report_template 字段应被请求接受并存入 task input_data。"""
    from backend.task_queue import TaskQueue

    # 用一个不会真正调 LLM 的 func (demo fallback 路径会被触发,但字段应已存)
    r = client.post(
        "/api/analysis/async",
        json={
            "stock_symbol": "600519",
            "stock_name": "贵州茅台",
            "mode": "standard",
            "report_template": "risk",
        },
    )
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]
    task = TaskQueue().get_task(task_id)
    assert task is not None
    # get_task 返回 input_json(JSON 字符串)
    import json as _json

    input_data = _json.loads(task["input_json"] or "{}")
    assert input_data.get("report_template") == "risk"
