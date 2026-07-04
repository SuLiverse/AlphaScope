"""插件市场 / Plugin Marketplace (Phase D #2, §9 #9).

在 Integration Registry 之上提供一层**插件发现、分类、推荐与安装指引**能力
(对应战略规划 Phase D 第 2 项「Plugin Marketplace」与 §9 想法 #9)。

与 ``integrations.registry`` 的区别:
- Registry 负责「注册 + 边界断言 + 自动发现」(已实现, v1.9.24+)
- Marketplace 负责「分类展示 + 未装插件推荐 + 安装指引 + 能力标签」(本模块)

设计要点 (延续项目「确定性 · 失败安全」基线):
- **只读聚合**: 不重复注册逻辑, 只读取 registry 的 metadata + 健康状态, 聚合成
  「市场视图」(已装/未装/推荐)。
- **catalog 维护**: 维护一份「已知插件目录」(即使未装也能展示 + 给安装命令), 让
  用户知道 AlphaScope 生态还能接哪些项目。
- **失败安全**: 任何单插件/registry 异常不影响整体列表; 全部失败返回空。
- **合规**: 推荐仅是研究能力说明, 不预测、不荐股。

本模块纯函数为主, 不需要额外可选依赖 (复用 registry)。
"""

from __future__ import annotations

from typing import Any


# ============================================================
# 已知插件目录 (catalog) — 即使未装也展示, 给安装指引
# ============================================================

# 每个条目: name / category / display_name / description / homepage / package /
# install_hint / recommended(规划优先级) / license_safety
_PLUGIN_CATALOG: list[dict[str, Any]] = [
    # ===== Backtest 引擎 =====
    {
        "name": "vectorbt",
        "category": "backtest",
        "display_name": "vectorBT 向量化回测",
        "description": "向量化参数扫描, 一次跑完整张参数表",
        "homepage": "https://github.com/polakowo/vectorbt",
        "package": "vectorbt",
        "install_hint": "pip install vectorbt",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    {
        "name": "backtrader",
        "category": "backtest",
        "display_name": "Backtrader 经典回测",
        "description": "事件驱动 + 经典策略兼容层",
        "homepage": "https://github.com/mementum/backtrader",
        "package": "backtrader",
        "install_hint": "pip install backtrader",
        "recommended": "推荐",
        "license_safety": "safe",
        "license_name": "LGPL-2.1",
    },
    {
        "name": "pybroker",
        "category": "backtest",
        "display_name": "PyBroker ML 回测",
        "description": "ML + walk-forward 验证, 策略过拟合检测",
        "homepage": "https://github.com/edtechre/pybroker",
        "package": "lib-pybroker",
        "install_hint": "pip install lib-pybroker",
        "recommended": "推荐",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    {
        "name": "bt",
        "category": "backtest",
        "display_name": "bt 组合级回测",
        "description": "可组合 algo 链做资产配置/再平衡",
        "homepage": "https://github.com/pmorissette/bt",
        "package": "bt",
        "install_hint": "pip install bt",
        "recommended": "推荐",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    # ===== Data 数据源 =====
    {
        "name": "openbb",
        "category": "data",
        "display_name": "OpenBB 全球数据",
        "description": "聚合 FMP/Polygon/Yahoo/FRED 等数十源, 扩展全球品种",
        "homepage": "https://github.com/OpenBB-finance/OpenBB",
        "package": "openbb",
        "install_hint": "pip install openbb",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    # ===== Factor 因子/ML =====
    {
        "name": "qlib",
        "category": "factor",
        "display_name": "Qlib AI 量化因子",
        "description": "Alpha158/Alpha360 系统化因子 + ML 模型实验",
        "homepage": "https://github.com/microsoft/qlib",
        "package": "pyqlib",
        "install_hint": "pip install pyqlib",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    {
        "name": "alphalens",
        "category": "factor",
        "display_name": "Alphalens 因子分析",
        "description": "因子 IC/分层收益分析 (规划 Phase B #3)",
        "homepage": "https://github.com/quantopian/alphalens",
        "package": "alphalens-reloaded",
        "install_hint": "pip install alphalens-reloaded",
        "recommended": "推荐",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    # ===== Agent 团队 =====
    {
        "name": "tradingagents",
        "category": "agent",
        "display_name": "TradingAgents 外部投研团队",
        "description": "多 Agent 投研框架 (4 分析师 + 多空辩论 + 风控 + 组合经理)",
        "homepage": "https://github.com/TauricResearch/TradingAgents",
        "package": "tradingagents",
        "install_hint": "pip install git+https://github.com/TauricResearch/TradingAgents.git",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    # ===== 组合优化 (Phase B #5/#6/#7) =====
    {
        "name": "skfolio",
        "category": "portfolio",
        "display_name": "skfolio 组合优化",
        "description": "均值方差/CVaR/HRP 现代组合优化",
        "homepage": "https://github.com/skfolio/skfolio",
        "package": "skfolio",
        "install_hint": "pip install skfolio",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    {
        "name": "riskfolio",
        "category": "portfolio",
        "display_name": "Riskfolio-Lib",
        "description": "风险预算/CVaR/HRP 多种风险模型",
        "homepage": "https://github.com/dcajasn/Riskfolio-Lib",
        "package": "Riskfolio-Lib",
        "install_hint": "pip install Riskfolio-Lib",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    # ===== MLOps (Phase C) =====
    {
        "name": "mlflow",
        "category": "mlops",
        "display_name": "MLflow 实验管理",
        "description": "实验追踪/模型注册/LLM trace",
        "homepage": "https://github.com/mlflow/mlflow",
        "package": "mlflow",
        "install_hint": "pip install mlflow",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    {
        "name": "optuna",
        "category": "mlops",
        "display_name": "Optuna 超参优化",
        "description": "TPESampler/GP 等超参搜索算法",
        "homepage": "https://github.com/optuna/optuna",
        "package": "optuna",
        "install_hint": "pip install optuna",
        "recommended": "推荐",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    # ===== 数据底座 (Phase A) =====
    {
        "name": "exchange_calendars",
        "category": "data_quality",
        "display_name": "交易日历",
        "description": "全球交易所真实交易日历 (节假日/T+1)",
        "homepage": "https://github.com/gerrymanoim/exchange_calendars",
        "package": "exchange_calendars",
        "install_hint": "pip install exchange_calendars",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
    {
        "name": "pandera",
        "category": "data_quality",
        "display_name": "Pandera 数据契约",
        "description": "DataFrame schema 校验",
        "homepage": "https://github.com/unionai-oss/pandera",
        "package": "pandera",
        "install_hint": "pip install pandera",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "MIT",
    },
    {
        "name": "quantstats",
        "category": "report",
        "display_name": "QuantStats 绩效报告",
        "description": "Sharpe/Sortino/月度收益热力图等专业报告",
        "homepage": "https://github.com/ranaroussi/quantstats",
        "package": "quantstats",
        "install_hint": "pip install quantstats",
        "recommended": "必接",
        "license_safety": "safe",
        "license_name": "Apache-2.0",
    },
]


CATEGORY_LABEL: dict[str, str] = {
    "backtest": "回测引擎",
    "data": "数据源",
    "factor": "因子 / ML",
    "agent": "Agent 团队",
    "portfolio": "组合优化",
    "mlops": "MLOps 评估",
    "data_quality": "数据底座",
    "report": "报告发布",
}


# ============================================================
# 公开 API (纯函数)
# ============================================================


def list_catalog() -> list[dict[str, Any]]:
    """返回完整插件目录 (含已装和未装)。"""
    return list(_PLUGIN_CATALOG)


def list_installed() -> list[dict[str, Any]]:
    """返回当前已安装 (在 Integration Registry 注册) 的插件 + 健康状态。

    复用 registry 的 metadata + healthcheck; 失败安全: registry 异常返回空。
    """
    try:
        from backend.integrations.registry import get_registry

        reg = get_registry()
        health = reg.healthcheck_all()
        out: list[dict[str, Any]] = []
        for meta in reg.all_metadata():
            h = health.get(meta.name)
            out.append(
                {
                    "name": meta.name,
                    "category": meta.category.value,
                    "display_name": meta.display_name,
                    "health": h.status.value if h else "unknown",
                    "health_message": h.message if h else "",
                    "license_safety": meta.license_safety.value,
                    "allow_live_order": meta.allow_live_order,
                    "capabilities": [c.name for c in meta.capabilities],
                }
            )
        return out
    except Exception:
        return []


def list_not_installed() -> list[dict[str, Any]]:
    """返回未安装的插件 (catalog 里有, 但 registry 未注册)。"""
    try:
        from backend.integrations.registry import get_registry

        reg = get_registry()
        installed_names = set(reg.names())
    except Exception:
        installed_names = set()
    return [p for p in _PLUGIN_CATALOG if p["name"] not in installed_names]


def recommend(priority: str = "必接") -> list[dict[str, Any]]:
    """按规划优先级推荐插件 (默认「必接」)。"""
    return [p for p in _PLUGIN_CATALOG if p.get("recommended") == priority]


def by_category(category: str) -> list[dict[str, Any]]:
    """按类别筛选插件。"""
    return [p for p in _PLUGIN_CATALOG if p["category"] == category]


def install_hint(name: str) -> str | None:
    """取某插件的安装命令; 未知插件返回 None。"""
    for p in _PLUGIN_CATALOG:
        if p["name"] == name:
            return p.get("install_hint")
    return None


def describe() -> dict[str, Any]:
    """市场概览 (供 UI/调试)。"""
    try:
        installed = list_installed()
        not_installed = list_not_installed()
    except Exception:
        installed, not_installed = [], list_catalog()
    return {
        "total_catalog": len(_PLUGIN_CATALOG),
        "installed_count": len(installed),
        "not_installed_count": len(not_installed),
        "categories": sorted({p["category"] for p in _PLUGIN_CATALOG}),
        "must_have_remaining": [p["name"] for p in not_installed if p.get("recommended") == "必接"],
        "note": "插件市场: 已装自动注册, 未装按目录给安装指引; 全部研究语义, 不下单。",
    }
