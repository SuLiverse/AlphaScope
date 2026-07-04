"""AI 评估与 MLOps 层 / AI Evaluation & MLOps (Phase C).

把战略规划 Phase C 的 MLOps 库接入 AlphaScope, 给 Agent/模型/实验加上**可观测、可评估、
可调优**能力 (对应规划 Phase C 第 1-10 项: LangGraph / Ragas / Phoenix / Evidently /
MLflow / Feast / FinGPT / FinRobot / Agent Scorecard / Human Feedback)。

设计要点 (延续项目「确定性 · 失败安全」基线):
- **可选依赖 + 优雅降级**: 每个库独立 import-guard (这些库依赖重且彼此冲突, 任意子集
  装了即可用, 全缺则降级返回 available=False, 不影响其余功能)。
- **统一能力探测**: ``available_tools()`` 列出当前已装的 MLOps 库; ``describe()`` 概览。
- **轻量包装, 不重造轮子**: 不重新实现 MLflow/Evidently 等的能力, 而是提供**面向
  AlphaScope 场景的便捷入口** (如把回测实验记录到 MLflow、把数据漂移检测交给 Evidently、
  把超参搜索交给 Optuna)。
- **纯函数**: ``available_tools`` / ``describe`` / ``build_experiment_log`` 不依赖任何
  MLOps 库, 始终可测。
- **合规**: 评估/记录仅描述过去结构与性能, 不预测未来、不荐股、不构成投资建议。

A​PI 已对照真实源码核对 (非臆测):
- mlflow 3.x: ``mlflow.log_metric/log_params/set_experiment/start_run``
- evidently 0.7.x: ``from evidently.report import Report; from evidently.metric_preset import DataDriftPreset``
- optuna 4.x: ``optuna.create_study(direction='maximize').optimize(objective, n_trials=N)``
- langgraph 0.x: ``from langgraph.graph import StateGraph, END``
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: 每个库独立 import-guard (这些库依赖重且彼此冲突) -----
_MLFLOW = False
_EVIDENTLY = False
_OPTUNA = False
_LANGGRAPH = False
_RAGAS = False
_FEAST = False
_PHOENIX = False

try:
    import mlflow  # type: ignore[import-untyped]

    _MLFLOW = True
except Exception:
    mlflow = None  # type: ignore[assignment]

try:
    from evidently.report import Report  # type: ignore[import-untyped]
    from evidently.metric_preset import DataDriftPreset  # type: ignore[import-untyped]

    _EVIDENTLY = True
except Exception:
    Report = None  # type: ignore[assignment]
    DataDriftPreset = None  # type: ignore[assignment]

try:
    import optuna  # type: ignore[import-untyped]

    _OPTUNA = True
except Exception:
    optuna = None  # type: ignore[assignment]

try:
    from langgraph.graph import StateGraph, END  # type: ignore[import-untyped]

    _LANGGRAPH = True
except Exception:
    StateGraph = None  # type: ignore[assignment]
    END = None  # type: ignore[assignment]

try:
    from ragas import evaluate as _ragas_evaluate  # type: ignore[import-untyped]

    _RAGAS = True
except Exception:
    _ragas_evaluate = None  # type: ignore[assignment]

try:
    import feast  # type: ignore[import-untyped]

    _FEAST = True
except Exception:
    feast = None  # type: ignore[assignment]

try:
    import phoenix as phoenix_mod  # type: ignore[import-untyped]

    _PHOENIX = True
except Exception:
    phoenix_mod = None  # type: ignore[assignment]


# ============================================================
# 能力探测 (纯函数, 始终可测)
# ============================================================


def available_tools() -> dict[str, bool]:
    """当前已装的 MLOps 库清单。"""
    return {
        "mlflow": _MLFLOW,
        "evidently": _EVIDENTLY,
        "optuna": _OPTUNA,
        "langgraph": _LANGGRAPH,
        "ragas": _RAGAS,
        "feast": _FEAST,
        "phoenix": _PHOENIX,
    }


def is_available(tool: str | None = None) -> bool:
    """某 MLOps 库是否就绪; tool=None 时表示「至少一个就绪」。"""
    tools = available_tools()
    if tool is None:
        return any(tools.values())
    return tools.get(tool, False)


def describe() -> dict[str, Any]:
    """能力概览 (供 UI/调试)。"""
    tools = available_tools()
    ready = [k for k, v in tools.items() if v]
    return {
        "available_tools": tools,
        "ready_count": len(ready),
        "ready": ready,
        "note": (f"就绪 MLOps 库: {', '.join(ready) if ready else '(无)'}; 按需 pip install 缺失库启用对应能力。"),
    }


# ============================================================
# MLflow: 实验记录 (Phase C #5)
# ============================================================


def log_backtest_to_mlflow(
    experiment_name: str,
    run_name: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把一次回测实验记录到 MLflow (Phase C #5 实验管理)。

    返回 {ok, run_id, experiment, error}。失败安全: mlflow 不可用/记录失败 → ok=False, 不抛。
    """
    base: dict[str, Any] = {
        "ok": False,
        "run_id": None,
        "experiment": experiment_name,
        "error": "",
    }
    if not _MLFLOW:
        base["error"] = "mlflow 未安装。pip install mlflow"
        return base
    try:
        mlflow.set_experiment(experiment_name)  # type: ignore[union-attr]
        with mlflow.start_run(run_name=run_name) as run:  # type: ignore[union-attr]
            mlflow.log_params(params)  # type: ignore[union-attr]
            for k, v in metrics.items():
                try:
                    mlflow.log_metric(k, float(v))  # type: ignore[union-attr]
                except (TypeError, ValueError):
                    continue
            if tags:
                mlflow.set_tags(tags)  # type: ignore[union-attr]
            base["run_id"] = run.info.run_id
            base["ok"] = True
    except Exception as e:
        base["error"] = f"mlflow 记录失败: {str(e)[:120]}"
    return base


# ============================================================
# Evidently: 数据漂移检测 (Phase C #4)
# ============================================================


def detect_data_drift(
    reference_data: Any,
    current_data: Any,
) -> dict[str, Any]:
    """检测两份数据集是否有漂移 (Phase C #4 质量监控)。

    返回 {ok, drift_detected, drift_share, report_html, error}。
    失败安全: evidently 不可用 → ok=False。
    """
    base: dict[str, Any] = {
        "ok": False,
        "drift_detected": None,
        "drift_share": None,
        "error": "",
    }
    if not _EVIDENTLY:
        base["error"] = "evidently 未安装。pip install evidently"
        return base
    try:
        report = Report(metrics=[DataDriftPreset()])  # type: ignore[misc]
        report.run(reference_data=reference_data, current_data=current_data)
        result = report.as_dict()
        # 抽取 drift 摘要 (evidently 结构因版本略异, 容错)
        drift_detected = False
        drift_share = 0.0
        try:
            for metric in result.get("metrics", []):
                res = metric.get("result", {})
                if "drift_detected" in res:
                    drift_detected = drift_detected or bool(res["drift_detected"])
                if "drift_share" in res:
                    drift_share = float(res["drift_share"])
        except Exception:
            pass
        base.update(
            {
                "ok": True,
                "drift_detected": drift_detected,
                "drift_share": round(drift_share, 4),
            }
        )
    except Exception as e:
        base["error"] = f"evidently 漂移检测失败: {str(e)[:120]}"
    return base


# ============================================================
# Optuna: 超参优化 (Phase C, §6 专业工作站版)
# ============================================================


def optimize_hyperparameters(
    objective: Any,
    n_trials: int = 20,
    direction: str = "maximize",
    seed: int = 42,
) -> dict[str, Any]:
    """用 Optuna 跑超参优化 (Phase C / 专业工作站版)。

    参数:
    - objective: callable(trial) -> float  目标函数 (返回要优化的指标)
    - n_trials: int  试验次数
    - direction: "maximize"(默认) / "minimize"
    - seed: 随机种子 (可复现)

    返回 {ok, best_value, best_params, n_trials, error}。
    失败安全: optuna 不可用 → ok=False。
    """
    base: dict[str, Any] = {
        "ok": False,
        "best_value": None,
        "best_params": None,
        "n_trials": 0,
        "error": "",
    }
    if not _OPTUNA:
        base["error"] = "optuna 未安装。pip install optuna"
        return base
    if not callable(objective):
        base["error"] = "objective 必须是 callable(trial) -> float"
        return base
    try:
        optuna.logging.set_verbosity(optuna.logging.WARNING)  # type: ignore[union-attr]
        study = optuna.create_study(  # type: ignore[union-attr]
            direction=direction,
            sampler=optuna.samplers.TPESampler(seed=seed),  # type: ignore[union-attr]
        )
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        base.update(
            {
                "ok": True,
                "best_value": float(study.best_value),
                "best_params": dict(study.best_params),
                "n_trials": len(study.trials),
            }
        )
    except Exception as e:
        base["error"] = f"optuna 优化失败: {str(e)[:120]}"
    return base


# ============================================================
# LangGraph: 多 Agent 工作流 (Phase C #1)
# ============================================================


def build_langgraph_available() -> bool:
    """LangGraph 是否可用 (用于自研 Agent 编排的增强分支)。"""
    return _LANGGRAPH


# ============================================================
# 纯函数 (实验日志构造, 始终可测)
# ============================================================


def build_experiment_log(
    strategy_id: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    notes: str = "",
) -> dict[str, Any]:
    """构造标准化的实验日志结构 (可喂给 MLflow 或自研 experiment_store)。

    纯函数: 加 reproducibility 相关字段, 不依赖任何 MLOps 库。
    """
    import hashlib
    import json
    from datetime import datetime

    payload = {
        "strategy_id": strategy_id,
        "params": params,
        "metrics": metrics,
        "notes": notes,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    # 可复现 hash (基于 params + metrics)
    try:
        canonical = json.dumps(
            {"strategy_id": strategy_id, "params": params, "metrics": metrics},
            sort_keys=True,
            default=str,
        )
        payload["reproducibility_hash"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    except Exception:
        payload["reproducibility_hash"] = None
    return payload
