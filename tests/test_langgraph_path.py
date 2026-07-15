"""LangGraph optional path tests."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.agent_modes import AnalysisMode
from backend.runtime import langgraph_path


class _LifecycleGraph:
    """Dependency-free stand-in that executes the production graph nodes."""

    def invoke(self, initial_state):
        state = dict(initial_state)
        for node in (
            langgraph_path._prepare_analysis,
            langgraph_path._analyze,
            langgraph_path._finalize_analysis,
        ):
            state.update(node(state))
        return state


@pytest.fixture
def enabled_langgraph(monkeypatch):
    monkeypatch.setenv("ALPHASCOPE_ORCHESTRATION", "langgraph")
    monkeypatch.setattr(langgraph_path, "_LANGGRAPH", True)
    monkeypatch.setattr(langgraph_path, "build_analysis_graph", _LifecycleGraph)


def test_orchestration_default_self(monkeypatch):
    monkeypatch.delenv("ALPHASCOPE_ORCHESTRATION", raising=False)
    assert langgraph_path.orchestration_backend() == "self"


def test_build_graph_when_available():
    if not langgraph_path.langgraph_available():
        assert langgraph_path.build_analysis_graph() is None
    else:
        graph = langgraph_path.build_analysis_graph()
        assert graph is not None


def test_lifecycle_forwards_explicit_request_unchanged(enabled_langgraph, monkeypatch):
    stock_data = {"symbol": "600519"}
    agent_configs = [{"key": "technical", "enabled": True}]
    global_ai_settings = {"provider": "local", "temperature": 0.2}
    api_keys = {"technical": "test-key"}
    core_result = {"summary": {"final": "hold"}, "mode": "standard"}
    captured = {}

    def fake_core_executor(**kwargs):
        captured.update(kwargs)
        return core_result

    monkeypatch.setattr(langgraph_path, "_run_core_executor", fake_core_executor)

    result = langgraph_path.run_via_langgraph(
        stock_data,
        mode=AnalysisMode.STANDARD,
        agent_configs=agent_configs,
        global_ai_settings=global_ai_settings,
        api_keys=api_keys,
    )

    assert result == {
        **core_result,
        "orchestration": "langgraph",
        "langgraph_available": True,
        "langgraph_lifecycle": ["prepare", "analyze", "finalize"],
    }
    assert captured["stock_data"] is stock_data
    assert captured["mode"] is AnalysisMode.STANDARD
    assert captured["agent_configs"] is agent_configs
    assert captured["global_ai_settings"] is global_ai_settings
    assert captured["api_keys"] is api_keys
    assert "orchestration" not in core_result


def test_nested_entry_falls_back_without_blocking_outer_run(enabled_langgraph, monkeypatch):
    nested_results = []

    def fake_core_executor(**_kwargs):
        nested_results.append(
            langgraph_path.run_via_langgraph(
                {"symbol": "nested"},
                mode=AnalysisMode.AUTO,
                api_keys={"nested": "key"},
            )
        )
        return {"summary": {"final": "hold"}}

    monkeypatch.setattr(langgraph_path, "_run_core_executor", fake_core_executor)

    result = langgraph_path.run_via_langgraph(
        {"symbol": "outer"},
        mode=AnalysisMode.STANDARD,
    )

    assert nested_results == [None]
    assert result is not None
    assert result["orchestration"] == "langgraph"


def test_context_guard_does_not_block_concurrent_requests(enabled_langgraph, monkeypatch):
    rendezvous = Barrier(2)

    def fake_core_executor(*, stock_data, **_kwargs):
        rendezvous.wait(timeout=5)
        return {"symbol": stock_data["symbol"]}

    monkeypatch.setattr(langgraph_path, "_run_core_executor", fake_core_executor)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                langgraph_path.run_via_langgraph,
                {"symbol": symbol},
                mode=AnalysisMode.STANDARD,
            )
            for symbol in ("first", "second")
        ]
        results = [future.result(timeout=10) for future in futures]

    assert {result["symbol"] for result in results if result} == {"first", "second"}
    assert all(result and result["orchestration"] == "langgraph" for result in results)


def test_failed_analysis_returns_none_and_resets_context_guard(enabled_langgraph, monkeypatch):
    def failing_core_executor(**_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(langgraph_path, "_run_core_executor", failing_core_executor)
    assert (
        langgraph_path.run_via_langgraph(
            {"symbol": "failed"},
            mode=AnalysisMode.STANDARD,
        )
        is None
    )

    monkeypatch.setattr(
        langgraph_path,
        "_run_core_executor",
        lambda **_kwargs: {"summary": {"final": "hold"}},
    )
    retry = langgraph_path.run_via_langgraph(
        {"symbol": "retry"},
        mode=AnalysisMode.STANDARD,
    )
    assert retry is not None
    assert retry["orchestration"] == "langgraph"


def test_invalid_prepared_request_falls_back_without_calling_core(enabled_langgraph, monkeypatch):
    called = False

    def fake_core_executor(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(langgraph_path, "_run_core_executor", fake_core_executor)

    assert langgraph_path.run_via_langgraph([], mode=AnalysisMode.STANDARD) is None  # type: ignore[arg-type]
    assert called is False


def test_missing_mode_falls_back_instead_of_forcing_deep(enabled_langgraph, monkeypatch):
    called = False

    def fake_core_executor(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(langgraph_path, "_run_core_executor", fake_core_executor)

    assert langgraph_path.run_via_langgraph({"symbol": "600519"}) is None
    assert called is False
