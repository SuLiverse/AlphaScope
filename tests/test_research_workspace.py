"""Offline acceptance tests for saved research, reviews, comparison and retries."""

import copy
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.research_workspaces import router
from backend.api.tasks import router as tasks_router
from backend.research_workspace import ResearchWorkspaceStore, compare_versions, extract_claims, public_config
from backend.runtime.context_builder import append_research_materials
from backend.storage import db
from backend.task_queue import TaskQueue


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "research.db")
    monkeypatch.setattr(db.Database, "_instance", None)
    monkeypatch.setattr(TaskQueue, "_instance", None)
    result = ResearchWorkspaceStore()
    yield result
    if TaskQueue._instance:
        TaskQueue._instance._executor.shutdown(wait=True)
    result.db.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(router)
    app.include_router(tasks_router)
    with TestClient(app) as client:
        yield client


def draft():
    return {
        "stock_symbol": "600519.SH",
        "stock_name": "Test",
        "research_question": "Cash flow?",
        "as_of": "2026-06-30",
        "report_template": "standard",
        "materials": [],
    }


def result():
    return {
        "summary": {"final": "HOLD"},
        "agents": {
            "fundamental": {
                "name": "Fundamental",
                "reason": "现金流增长 1.5% [1]。收入未变。",
                "signal": "HOLD",
                "confidence": 70,
                "vendor": "test",
                "model": "m1",
                "evidence_ids": ["e1"],
            }
        },
        "evidence_pool": [
            {
                "evidence_id": "e1",
                "number": 1,
                "source": "filing",
                "published_at": "2026-06-29",
                "preview": "Cash flow +1.5%",
                "source_url": "https://example.com/filing",
            }
        ],
    }


def completed(store, workspace_id, output=None, stock=None):
    vid = store.create_version(workspace_id, draft())
    store.checkpoint(
        vid,
        status="success",
        stage="complete",
        result_json=json.dumps(output or result()),
        stock_json=json.dumps(stock or {"close": 10, "days": 30}),
    )
    return store.version(vid)


def test_draft_versions_and_reviews_survive_new_store_instance(store):
    ws = store.save_workspace(draft())
    first = completed(store, ws["id"])
    second = completed(store, ws["id"])
    reopened = ResearchWorkspaceStore()
    assert reopened.workspace(ws["id"])["draft"] == draft()
    assert [v["number"] for v in reopened.workspace(ws["id"])["versions"]] == [2, 1]
    assert reopened.version(first["id"])["result"] == second["result"]


def test_review_is_version_bound_append_only_and_does_not_change_model_output(store, client):
    ws = store.save_workspace(draft())
    first, second = completed(store, ws["id"]), completed(store, ws["id"])
    claim = extract_claims(first["result"])[0]
    path = f"/api/research-workspaces/versions/{first['id']}/claims/{claim['id']}"
    review = {
        "status": "partial",
        "reason": "Missing denominator",
        "revised_text": "Needs verification",
        "evidence_relations": {"e1": "opposes"},
        "expected_revision": 0,
    }
    assert client.put(path, json=review).json()["data"]["revision"] == 1
    assert client.put(path, json=review).status_code == 409
    review.update(expected_revision=1, status="unsupported")
    assert client.put(path, json=review).json()["data"]["revision"] == 2
    assert len(store.reviews(first["id"])[claim["id"]]) == 2
    assert store.reviews(second["id"]) == {}
    assert store.version(first["id"])["result"] == first["result"]
    store.checkpoint(first["id"], result_json='{"tampered": true}')
    assert store.version(first["id"])["result"] == first["result"]


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"status": "invented"}, 422),
        ({"reason": " "}, 422),
        ({"evidence_relations": {"outside-version": "supports"}}, 409),
        ({"evidence_relations": {"e1": "invented"}}, 422),
    ],
)
def test_review_rejects_invalid_input(store, client, patch, code):
    version = completed(store, store.save_workspace(draft())["id"])
    claim = extract_claims(version["result"])[0]
    data = {"status": "supported", "reason": "Checked", "evidence_relations": {}, **patch}
    response = client.put(f"/api/research-workspaces/versions/{version['id']}/claims/{claim['id']}", json=data)
    assert response.status_code == code


def test_claims_preserve_decimals_and_do_not_invent_sentence_citations():
    claims = extract_claims(result())
    assert len(claims) == 2
    assert "1.5%" in claims[0]["text"]
    assert claims[0]["evidence_ids"] == ["e1"]
    assert claims[1]["evidence_ids"] == []
    assert claims[1]["agent_evidence_ids"] == ["e1"]


def test_diff_ignores_evidence_number_but_tracks_data_agents_models_and_scope(store):
    ws = store.save_workspace(draft())
    old = completed(store, ws["id"], stock={"close": 10, "financial_metrics": {"cash_flow": 20}})
    output = result()
    output["evidence_pool"][0]["number"] = 4
    output["agents"]["fundamental"].update(signal="SELL", model="m2")
    new = completed(store, ws["id"], output, {"close": 10, "financial_metrics": {"cash_flow": 0}})
    diff = compare_versions(old, new)
    assert diff["evidence"] == []
    assert diff["metrics"] == [{"field": "financial_metrics.cash_flow", "before": 20, "after": 0, "status": "changed"}]
    assert diff["models"][0]["field"] == "actual"
    assert len(diff["agents"]) == 1
    with pytest.raises(ValueError):
        compare_versions(new, old)
    foreign = completed(store, store.save_workspace(draft())["id"])
    with pytest.raises(ValueError):
        compare_versions(old, foreign)


def test_diff_missing_data_is_not_financial_stability(store):
    ws = store.save_workspace(draft())
    diff = compare_versions(completed(store, ws["id"]), completed(store, ws["id"]))
    assert any("结构化财务指标" in warning for warning in diff["warnings"])
    assert diff["metrics"] == []


def test_cannot_change_stock_or_start_duplicate_run(store):
    ws = store.save_workspace(draft())
    with pytest.raises(ValueError):
        store.save_workspace({**draft(), "stock_symbol": "000001"}, ws["id"])
    store.create_version(ws["id"], draft())
    with pytest.raises(ValueError):
        store.create_version(ws["id"], draft())


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///secret", "https://user:secret@example.com", "//example.com"]
)
def test_material_url_validation(client, url):
    response = client.post(
        "/api/research-workspaces",
        json={**draft(), "materials": [{"title": "Report", "source_url": url, "excerpt": "text"}]},
    )
    assert response.status_code == 422


def test_material_cutoffs_deduplication_and_stable_ids():
    material = {"title": "Report", "published_at": "2026-06-29", "excerpt": "Cash flow", "source_url": ""}
    inputs = [material, material, {**material, "published_at": None}, {**material, "published_at": "2026-07-01"}]
    pool = append_research_materials(result()["evidence_pool"], inputs, "2026-06-30")
    assert len(pool) == 2
    assert pool[1]["number"] == 2
    assert pool[1]["excerpt"] == "Cash flow"
    assert pool[1]["evidence_id"] == append_research_materials([], [material])[0]["evidence_id"]


def test_config_scrubbing_preserves_agent_identity_and_never_mutates_inputs():
    config = {
        "key": "fundamental",
        "max_tokens": 4096,
        "api_key": "SECRET",
        "base_url": "https://secret",
        "routes": [{"token": "SECRET", "model": "m1"}],
    }
    before = copy.deepcopy(config)
    clean = public_config(config)
    assert clean == {"key": "fundamental", "max_tokens": 4096, "routes": [{"model": "m1"}]}
    assert "SECRET" not in json.dumps(clean)
    assert config == before


def wait_task(task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = TaskQueue().get_task(task_id)
        if task["status"] in {"success", "failed", "cancelled"}:
            TaskQueue()._sync_research_versions()
            return task
        time.sleep(0.01)
    pytest.fail("Task did not finish")


def test_retry_reuses_market_checkpoint_and_original_question(store, client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "backend.api.tasks._build_analysis_stock_data",
        lambda *a, **kw: calls.append(kw) or {"close": 10, "symbol": a[0]},
    )

    def fail(**kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("backend.runtime.orchestrator.run_agents_with_mode", fail)
    started = client.post("/api/analysis/async", json=draft()).json()["data"]
    assert wait_task(started["task_id"])["status"] == "failed"
    first = store.version(started["version_id"])
    assert first["stage"] == "analysis"
    seen = []
    monkeypatch.setattr("backend.runtime.orchestrator.run_agents_with_mode", lambda **kw: seen.append(kw) or result())
    retry = client.post(
        "/api/analysis/async",
        json={
            "stock_symbol": draft()["stock_symbol"],
            "workspace_id": started["workspace_id"],
            "retry_from": started["version_id"],
            "research_question": "Must not override original",
        },
    ).json()["data"]
    assert wait_task(retry["task_id"])["status"] == "success"
    assert len(calls) == 1
    assert seen[0]["stock_data"]["close"] == 10
    version = store.version(retry["version_id"])
    assert version["input"]["research_question"] == "Cash flow?"
    assert version["parent_id"] == first["id"]
    assert store.version(first["id"])["status"] == "failed"


def test_restart_marks_orphaned_research_failed(store):
    queue = TaskQueue()
    ws = store.save_workspace(draft())
    vid = store.create_version(ws["id"], draft())
    store.checkpoint(vid, task_id="orphan", status="running")
    with store.db.transaction() as conn:
        conn.execute(
            "INSERT INTO analysis_tasks (id, task_type, status, created_at) VALUES ('orphan', 'analysis', 'running', 0)"
        )
        conn.commit()
    queue._executor.shutdown(wait=True)
    TaskQueue._instance = None
    TaskQueue()
    assert store.version(vid)["status"] == "failed"
    assert "interrupted" in store.version(vid)["error"]


def test_missing_version_and_foreign_comparison_are_not_found(client, store):
    assert client.get("/api/research-workspaces/versions/missing").status_code == 404
    a = completed(store, store.save_workspace(draft())["id"])
    b = completed(store, store.save_workspace(draft())["id"])
    assert (
        client.get(f"/api/research-workspaces/{a['workspace_id']}/compare?before={a['id']}&after={b['id']}").status_code
        == 404
    )


def test_submission_failure_does_not_leave_workspace_permanently_active(client, store, monkeypatch):
    ws = store.save_workspace(draft())

    def fail(**kwargs):
        raise RuntimeError("executor stopped")

    monkeypatch.setattr(TaskQueue, "submit", fail)
    response = client.post("/api/analysis/async", json={**draft(), "workspace_id": ws["id"]})
    assert response.status_code == 503
    assert store.workspace(ws["id"])["versions"][0]["status"] == "failed"


def test_retry_refuses_to_silently_drop_transient_model_endpoint(client, store):
    ws = store.save_workspace(draft())
    vid = store.create_version(ws["id"], {**draft(), "transient_overrides_omitted": True})
    store.checkpoint(vid, status="failed")
    response = client.post("/api/analysis/async", json={**draft(), "workspace_id": ws["id"], "retry_from": vid})
    assert response.status_code == 409
    assert len(store.workspace(ws["id"])["versions"]) == 1
