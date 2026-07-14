"""可选 LangGraph 编排旁路 — 默认关闭, 不替换自研 orchestrator。

启用条件:
  ALPHASCOPE_ORCHESTRATION=langgraph
  且已安装 langgraph (pip install 'alphascope[mlops]' 或 langgraph)

图节点顺序对齐自研 deep 路径的角色: agents 并行(简化为串行节点占位) →
critic 摘要 → chairman。实际 LLM 调用仍走 provider_gateway / financial_agents,
本模块只提供 StateGraph 外壳与状态传递, 失败则返回 None 让调用方回退自研。

合规: 研究流程编排, 不产生买卖指令。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LANGGRAPH = None
try:
    from langgraph.graph import END, StateGraph  # type: ignore

    _LANGGRAPH = True
except Exception:  # noqa: BLE001
    StateGraph = None  # type: ignore
    END = None  # type: ignore
    _LANGGRAPH = False


def langgraph_available() -> bool:
    return bool(_LANGGRAPH)


def orchestration_backend() -> str:
    raw = os.getenv("ALPHASCOPE_ORCHESTRATION", "self").strip().lower()
    if raw in {"langgraph", "lg", "graph"} and langgraph_available():
        return "langgraph"
    return "self"


def build_analysis_graph():
    """构建最小分析图; 不可用时返回 None。"""
    if not langgraph_available() or StateGraph is None:
        return None

    try:
        from typing import TypedDict

        class AnalysisState(TypedDict, total=False):
            stock_data: dict
            agents: dict
            critic: dict
            chairman_summary: str
            brief: str
            errors: list

        def node_agents(state: AnalysisState) -> AnalysisState:
            # 真正执行仍委托自研 run_custom_agent 循环 — 由 run_via_langgraph 注入
            return state

        def node_critic(state: AnalysisState) -> AnalysisState:
            return state

        def node_chairman(state: AnalysisState) -> AnalysisState:
            return state

        g = StateGraph(AnalysisState)
        g.add_node("agents", node_agents)
        g.add_node("critic", node_critic)
        g.add_node("chairman", node_chairman)
        g.set_entry_point("agents")
        g.add_edge("agents", "critic")
        g.add_edge("critic", "chairman")
        g.add_edge("chairman", END)
        return g.compile()
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangGraph 构图失败: %s", exc)
        return None


def run_via_langgraph(
    stock_data: dict[str, Any],
    *,
    agent_configs: Optional[list] = None,
    global_ai_settings: Optional[dict] = None,
) -> Optional[dict[str, Any]]:
    """尝试用 LangGraph 外壳跑一轮; 失败返回 None(调用方回退自研)。

    当前实现: 构图校验 + 调用自研 ``run_agents_with_mode`` 的核心逻辑标记
    ``orchestration=langgraph``, 保证行为与自研一致, 同时验证依赖可用。
    完整节点级 LLM 拆分留作后续迭代(避免半吊子双实现)。
    """
    if orchestration_backend() != "langgraph":
        return None
    graph = build_analysis_graph()
    if graph is None:
        return None
    try:
        # 执行图外壳(空状态推进), 证明 runtime 可用
        graph.invoke({"stock_data": stock_data or {}, "agents": {}, "errors": []})
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangGraph invoke 失败, 回退自研: %s", exc)
        return None

    # 委托自研完整分析, 标注 backend
    try:
        from backend.agent_modes import AnalysisMode
        from backend.runtime.orchestrator import run_agents_with_mode

        # 防重入: 自研入口检测到此 flag 会跳过再次进入 langgraph 旁路
        if getattr(run_agents_with_mode, "_langgraph_reentry", False):
            return None
        run_agents_with_mode._langgraph_reentry = True  # type: ignore[attr-defined]
        try:
            result = run_agents_with_mode(
                stock_data=stock_data,
                mode=AnalysisMode.DEEP,
                agent_configs=agent_configs,
                global_ai_settings=global_ai_settings,
            )
        finally:
            run_agents_with_mode._langgraph_reentry = False  # type: ignore[attr-defined]
        if isinstance(result, dict):
            result = {**result, "orchestration": "langgraph", "langgraph_available": True}
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangGraph 委托自研失败: %s", exc)
        return None
