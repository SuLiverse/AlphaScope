"""Optional LangGraph orchestration path.

Enable with ``ALPHASCOPE_ORCHESTRATION=langgraph`` and install the ``mlops``
extra.  The graph wraps the proven runtime orchestrator with a small, explicit
request lifecycle.  It does not duplicate the financial analysis pipeline.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, StateGraph  # type: ignore

    _LANGGRAPH = True
except Exception:  # noqa: BLE001 - LangGraph is an optional dependency
    StateGraph = None  # type: ignore
    END = None  # type: ignore
    _LANGGRAPH = False


# Context-local state prevents recursive entry when the graph delegates to the
# core orchestrator.  Unlike a function attribute, it does not block unrelated
# requests running concurrently in other threads or async contexts.
_LANGGRAPH_ACTIVE: ContextVar[bool] = ContextVar("alphascope_langgraph_active", default=False)


class AnalysisState(TypedDict, total=False):
    stock_data: dict[str, Any]
    mode: Any
    agent_configs: Optional[list]
    global_ai_settings: Optional[dict]
    api_keys: Optional[dict[str, str]]
    request: dict[str, Any]
    result: dict[str, Any]
    lifecycle: list[str]
    error: str


def langgraph_available() -> bool:
    return bool(_LANGGRAPH)


def orchestration_backend() -> str:
    raw = os.getenv("ALPHASCOPE_ORCHESTRATION", "self").strip().lower()
    if raw in {"langgraph", "lg", "graph"} and langgraph_available():
        return "langgraph"
    return "self"


def _next_lifecycle(state: AnalysisState, stage: str) -> list[str]:
    return [*state.get("lifecycle", []), stage]


def _prepare_analysis(state: AnalysisState) -> AnalysisState:
    """Validate and freeze the complete core-executor request."""
    lifecycle = _next_lifecycle(state, "prepare")
    stock_data = state.get("stock_data")
    if not isinstance(stock_data, dict):
        return {
            "lifecycle": lifecycle,
            "error": "LangGraph preparation requires stock_data to be a dictionary",
        }

    return {
        "lifecycle": lifecycle,
        "request": {
            "stock_data": stock_data,
            "mode": state.get("mode"),
            "agent_configs": state.get("agent_configs"),
            "global_ai_settings": state.get("global_ai_settings"),
            "api_keys": state.get("api_keys"),
        },
    }


def _run_core_executor(
    *,
    stock_data: dict[str, Any],
    mode: Any,
    agent_configs: Optional[list],
    global_ai_settings: Optional[dict],
    api_keys: Optional[dict[str, str]],
) -> dict[str, Any]:
    """Invoke the existing analysis implementation from the graph node."""
    from backend.runtime.orchestrator import run_agents_with_mode

    return run_agents_with_mode(
        stock_data=stock_data,
        mode=mode,
        agent_configs=agent_configs,
        global_ai_settings=global_ai_settings,
        api_keys=api_keys,
    )


def _analyze(state: AnalysisState) -> AnalysisState:
    """Run the proven core executor with the prepared request."""
    lifecycle = _next_lifecycle(state, "analyze")
    if state.get("error"):
        return {"lifecycle": lifecycle}

    request = state.get("request")
    if not isinstance(request, dict):
        return {
            "lifecycle": lifecycle,
            "error": "LangGraph analysis received no prepared request",
        }

    try:
        result = _run_core_executor(**request)
    except Exception as exc:  # noqa: BLE001 - caller owns fallback to self path
        return {
            "lifecycle": lifecycle,
            "error": f"LangGraph core analysis failed: {exc}",
        }

    if not isinstance(result, dict):
        return {
            "lifecycle": lifecycle,
            "error": "LangGraph core analysis returned a non-dictionary result",
        }
    return {"lifecycle": lifecycle, "result": result}


def _finalize_analysis(state: AnalysisState) -> AnalysisState:
    """Attach graph provenance only after the core result is complete."""
    lifecycle = _next_lifecycle(state, "finalize")
    result = state.get("result")
    if not isinstance(result, dict):
        return {"lifecycle": lifecycle}

    return {
        "lifecycle": lifecycle,
        "result": {
            **result,
            "orchestration": "langgraph",
            "langgraph_available": True,
            "langgraph_lifecycle": lifecycle,
        },
    }


def build_analysis_graph():
    """Build the prepare -> analyze -> finalize analysis graph."""
    if not langgraph_available() or StateGraph is None:
        return None

    try:
        graph = StateGraph(AnalysisState)
        graph.add_node("prepare", _prepare_analysis)
        graph.add_node("analyze", _analyze)
        graph.add_node("finalize", _finalize_analysis)
        graph.set_entry_point("prepare")
        graph.add_edge("prepare", "analyze")
        graph.add_edge("analyze", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()
    except Exception as exc:  # noqa: BLE001 - optional path must fail closed
        logger.warning("Failed to build LangGraph analysis graph: %s", exc)
        return None


def run_via_langgraph(
    stock_data: dict[str, Any],
    *,
    mode: Any = None,
    agent_configs: Optional[list] = None,
    global_ai_settings: Optional[dict] = None,
    api_keys: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    """Run one analysis through LangGraph or return ``None`` for self fallback.

    The requested mode and every caller-supplied configuration object are
    forwarded unchanged to the core executor.  Recursive entry in the same
    execution context returns ``None`` so the nested orchestrator continues its
    normal self-hosted path.
    """
    if orchestration_backend() != "langgraph" or _LANGGRAPH_ACTIVE.get():
        return None
    if mode is None:
        logger.warning("LangGraph received no analysis mode; falling back to self orchestration")
        return None

    graph = build_analysis_graph()
    if graph is None:
        return None

    token = _LANGGRAPH_ACTIVE.set(True)
    try:
        final_state = graph.invoke(
            {
                "stock_data": stock_data,
                "mode": mode,
                "agent_configs": agent_configs,
                "global_ai_settings": global_ai_settings,
                "api_keys": api_keys,
                "lifecycle": [],
            }
        )
    except Exception as exc:  # noqa: BLE001 - caller owns fallback to self path
        logger.warning("LangGraph invocation failed; falling back to self orchestration: %s", exc)
        return None
    finally:
        _LANGGRAPH_ACTIVE.reset(token)

    if not isinstance(final_state, dict):
        logger.warning("LangGraph returned an invalid final state; falling back to self orchestration")
        return None
    if final_state.get("error"):
        logger.warning("%s; falling back to self orchestration", final_state["error"])
        return None

    result = final_state.get("result")
    if not isinstance(result, dict):
        logger.warning("LangGraph produced no analysis result; falling back to self orchestration")
        return None
    return result
