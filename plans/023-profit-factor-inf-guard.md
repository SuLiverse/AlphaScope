# Plan 023: 回测全胜时 profit_factor=inf 导致 JSON 序列化 500——加非有限值防护

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 06182ca..HEAD -- backend/quant/metrics.py backend/api/quant_core.py tests/test_backtest_engine.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `06182ca`, 2026-08-01

## Why this matters

当回测没有任何亏损交易（短趋势行情中很常见）时，`calc_profit_factor` 返回 `float("inf")`。该值经 `round()` 仍是 `inf`，随后进入回测 API 的响应 payload；FastAPI/Starlette 的 `JSONResponse` 用 `json.dumps(..., allow_nan=False)` 序列化，遇到 `inf` 直接抛 `ValueError` → 整个回测接口返回 HTTP 500。同一 payload 还会喂给 experiment_store 落库与报告生成。修复方式是在 `build_performance_summary` 出口对非有限浮点值统一防护（本仓库 `backend/funds/metrics.py:95-98` 已有同款 `_round_json_float` 模式）。

## Current state

- `backend/quant/metrics.py:61-67` — 问题源头：
  ```python
  def calc_profit_factor(trades: list[dict[str, Any]]) -> float:
      """Profit factor: gross profit / gross loss."""
      gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
      gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
      if gross_loss == 0:
          return float("inf") if gross_profit > 0 else 0.0
      return gross_profit / gross_loss
  ```
- `backend/quant/metrics.py:199-212` — 出口处（`build_performance_summary`，`summary` dict 构造）：`"profit_factor": round(calc_profit_factor(trades), 2)` 以及 `total_return`/`annualized_return`/`sharpe_ratio` 等一串 `round(...)`。`max_drawdown`/`calmar_ratio` 理论上也可能非有限（如除零），本计划只保证出口整体安全。
- 参考模式：`backend/funds/metrics.py:95-98` 的 `_round_json_float`（读它，模仿其行为：非有限值返回 `None` 或 0，有限值 round 到 2 位）。**读这个文件确认它现在怎么写的再照抄风格。**
- payload 消费者：`backend/api/quant_core.py:476-489`（`_run_local_backtest` 的 `metrics` dict 直接取 `performance.get(...)`），`backend/api/quant_core.py:579`（`_run_portfolio_backtest_local`，同形状）。它们只透传，不需要改。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 定向回归 | `python -m pytest tests/test_backtest_engine.py tests/test_quant_api.py tests/test_metrics_advanced.py -q` | 全过（含新增） |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全过 |
| Lint      | `python -m ruff check backend/quant/metrics.py tests/test_quant_metrics.py` | exit 0 |

## Scope

**In scope**:
- `backend/quant/metrics.py`（`build_performance_summary` 内，或新增一个模块级私有辅助函数）
- `tests/test_quant_metrics.py`（若已存在则追加；不存在则新建）

**Out of scope**:
- `calc_profit_factor` 的返回值语义（`inf` 表示"全胜"本身是合理中间态，不改成 `0` 或 `None`——改的是出口防护）
- `backend/api/quant_core.py`、`backend/quant/engine.py`、`backend/quant/experiment_store.py`（纯消费者）
- plan 003 的信号/指标修复（不同计划）

## Git workflow

- Branch: `advisor/023-profit-factor-inf-guard`
- 提交风格：`fix(quant): guard non-finite metrics from breaking backtest JSON responses`
- 不要 push、不要开 PR。

## Steps

### Step 1: 确认 funds/metrics.py 的现成模式

读 `backend/funds/metrics.py` 中 `_round_json_float` 的实现（约 :95-98），理解它的输入输出约定。

**Verify**: `grep -n "_round_json_float" backend/funds/metrics.py` → 有匹配（确认模式存在）。

### Step 2: 在 quant/metrics.py 加出口防护

在 `backend/quant/metrics.py` 中新增模块级辅助（命名参照仓库风格，如 `_round_json_float` 或 `_safe_round`）：
- 输入 float，若 `math.isfinite(x)` 为真 → `round(x, 2)`；否则返回 `None`（`None` 在 JSON 中序列化为 `null`，前端 `performance.get("profit_factor", 0.0)` 兜底可接受）。

把 `build_performance_summary` 的 `summary` dict 中**所有** `round(calc_*, 2)` / `round(*, 2)` 的值改用该辅助（`total_return`、`annualized_return`、`max_drawdown`、`sharpe_ratio`、`sortino_ratio`、`calmar_ratio`、`win_rate`、`profit_factor`、`final_equity`）。注意保留**字段名不变**，值是 `None` 而非 `inf`/`nan`。

**Verify**: `python -m pytest tests/test_backtest_engine.py tests/test_metrics_advanced.py -q` → 全过（现有测试对正常值断言不受影响）。

### Step 3: 写回归测试

在 `tests/test_quant_metrics.py`（若不存在则新建，参照 `tests/test_backtest_engine.py` 的导入风格）追加：

1. `test_build_performance_summary_all_win_no_inf` — 构造全胜 trades（如 3 笔 `{"pnl": 100}`）+ 简单 equity_curve（如 `[100000, 100300]`）调 `build_performance_summary`（读它的完整签名再调用；需要 `initial_capital`、`days` 参数）→ 断言 `summary["profit_factor"] is None`（或 0，视你实现而定，二选一并写死），且 `json.dumps(summary, allow_nan=False)` 不抛异常（这行是关键回归断言：模拟 FastAPI 序列化）。
2. `test_build_performance_summary_no_loss_all_zero` — trades 为空或 `gross_loss==0 且 gross_profit==0` → `profit_factor` 为有限值（0.0），`json.dumps(..., allow_nan=False)` 不抛。

**Verify**: `python -m pytest tests/test_quant_metrics.py -q` → 新增 2 测试全过。

### Step 4: 全量回归 + lint

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`python -m ruff check backend/quant/metrics.py tests/test_quant_metrics.py` → exit 0。

## Test plan

- 新增 2 个测试（Step 3），核心断言用 `json.dumps(..., allow_nan=False)` 复现 FastAPI 的序列化失败模式。
- 模式参照：`tests/test_backtest_engine.py` 的直接函数调用风格 + `tests/test_metrics_advanced.py`（若该文件存在，读它看 metrics 测试的既有写法）。

## Done criteria

- [ ] `python -m pytest tests/test_quant_metrics.py -q` → 新增 2 测试全过
- [ ] `python -m pytest tests/test_backtest_engine.py tests/test_metrics_advanced.py tests/test_quant_api.py -q` → 全过
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过
- [ ] `python -m ruff check backend/quant/metrics.py tests/test_quant_metrics.py` → exit 0
- [ ] `grep -n 'round(calc_profit_factor' backend/quant/metrics.py` → 无匹配（旧写法消失）
- [ ] `git status` 只含 scope 内文件
- [ ] 已按 Git workflow 提交到 `advisor/023-profit-factor-inf-guard` 分支

## STOP conditions

- `build_performance_summary` 签名/字段与 "Current state" 摘录不一致（已漂移）。
- `funds/metrics.py` 的 `_round_json_float` 与预期行为完全不同（先读再抄，若不一致按本计划 Step 2 的语义实现并在报告说明）。
- 需要修改 scope 外文件才能达成目标。

## Maintenance notes

- plan 003 落地会改指标计算，但 `profit_factor` 的"全胜返回 inf"语义不变，本防护仍有效。
- 前端消费方（`performance.get("profit_factor", 0.0)`）对 `null` 的容忍度需在评审时确认；若前端把 `null` 渲染成空，这是可接受的降级（比 500 强）。
- 值从 `inf` 变 `null` 是行为变化，release notes 可提及（仅全胜回测场景）。
