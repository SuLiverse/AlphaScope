"""
真实 LLM 多 Agent 金融分析模块（多供应商异构版本 v2.0）

v2.0 架构重构：本文件现在是向后兼容的门面（facade）。
实际实现已拆分到：
- backend/models/provider_gateway.py — Provider 配置、客户端管理、LLM 调用
- backend/agents/base.py — Agent 配置、提示词、模型映射
- backend/agents/financial_agents.py — Agent 执行逻辑
- backend/agents/chairman.py — 主席综合判断
- backend/runtime/context_builder.py — 市场简报构建
- backend/runtime/orchestrator.py — 模式感知编排

所有公开 API 保持不变，现有代码无需修改。
"""

# ============== 向后兼容导入（re-export）=============

# Provider 配置与客户端
from backend.models.provider_gateway import (  # noqa: F401
    _resolve_env,
    normalize_openai_base_url,
    _allow_local_base_url,
    validate_custom_base_url,
    load_providers,
    _PROVIDER_CONFIG,
    VENDORS,
    get_vendor_config,
    create_client,
    get_client,
    clear_client_cache,
    DEFAULT_PROVIDER_MODELS,
    get_configured_provider,
    _call_with,
    call_llm,
    _extract_json,
    get_provider_list,
    get_provider_models,
)

# Agent 配置与提示词
from backend.agents.base import (  # noqa: F401
    AgentConfig,
    AGENT_MODEL_CONFIG,
    FALLBACK_VENDOR_MODEL,
    AGENT_PROMPTS,
    get_default_agent_configs,
    _agent_config_from_dict,
    _resolve_agent_ai_config,
    _strict_json_messages,
)

# Agent 执行
from backend.agents.financial_agents import (  # noqa: F401
    run_one_agent,
    run_all_agents,
    run_custom_agent,
    run_custom_agents,
    get_custom_agent_model_table,
    get_agent_model_table,
)

# 主席
from backend.agents.chairman import summarize_with_chairman  # noqa: F401

# 上下文构建
from backend.runtime.context_builder import (  # noqa: F401
    fetch_evidence_context,
    fetch_factor_context,
    build_market_brief,
)

# 模式感知编排
from backend.runtime.orchestrator import (  # noqa: F401
    run_agents_with_mode,
    _run_auto_mode,
    _mode_config_to_agent_dicts,
    get_mode_model_table,
)

# Agent mode system
from backend.agent_modes import AnalysisMode, AgentModeConfig, get_mode_resolver  # noqa: F401

# Schema 校验
try:
    from backend.validators import validate_agent_output as _validate_agent_output  # noqa: F401
except Exception:

    def _validate_agent_output(data):
        if not isinstance(data, dict):
            return {}
        return data


if __name__ == "__main__":
    print("=" * 70)
    print("Agent 模型分配：")
    for k, name, vendor, model in get_agent_model_table():
        print(f"  {name:<28} → {vendor}/{model}")
    print("=" * 70)

    sample = {
        "name": "贵州茅台",
        "symbol": "600519",
        "close": 1680.50,
        "day_change": 1.25,
        "period_change": 8.6,
        "period_high": 1750,
        "period_low": 1520,
        "days": 120,
        "ma5": "1665.30",
        "ma20": "1640.20",
        "ma60": "1620.10",
        "macd": "5.2",
        "dif": "12.3",
        "dea": "7.1",
        "rsi": "62.5",
        "volume": 28500,
        "total_amount": 350.5,
        "turnover": 0.23,
        "vol_ratio": 1.35,
        "volatility": 1.85,
        "fundamentals": "白酒龙头, 高端市占第一, 毛利率 91%, ROE 30%",
    }
    import time

    t0 = time.time()
    res = run_all_agents(sample, include_retail=True)
    print(f"\n[5 Agent 并行] 用时 {time.time() - t0:.1f}s\n")
    for r in res["agents"].values():
        flag = "OK" if r["ok"] else "FAIL"
        print(f"{r['name']:<24} [{r['vendor']}/{r['model']}] {flag}")
        print(f"  → {r['signal']} ({r['confidence']}%)  {r['reason'][:80]}")
    s = res["summary"]
    print(
        f"\n[投票] 买{s['buy']}/卖{s['sell']}/观{s['hold']} → {s['final']} | 均值 {s['avg_confidence']:.0f}%"
    )
    print("\n[主席总结]")
    print(summarize_with_chairman(res, sample["name"]))
