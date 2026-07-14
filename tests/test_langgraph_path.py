"""LangGraph optional path tests."""

from backend.runtime.langgraph_path import (
    build_analysis_graph,
    langgraph_available,
    orchestration_backend,
)


def test_orchestration_default_self(monkeypatch):
    monkeypatch.delenv("ALPHASCOPE_ORCHESTRATION", raising=False)
    assert orchestration_backend() == "self"


def test_build_graph_when_available():
    if not langgraph_available():
        assert build_analysis_graph() is None
    else:
        g = build_analysis_graph()
        assert g is not None
