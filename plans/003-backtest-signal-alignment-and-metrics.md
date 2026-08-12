# Plan 003: 修复回测引擎信号对齐（未来函数）与三件指标准确性问题

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/quant/engine.py backend/quant/metrics.py backend/quant/strategies backend/quant/portfolio.py backend/quant/etf_rotation.py backend/funds/metrics.py backend/api/quant_core.py tests/test_backtest_engine.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED（修复后所有回测数字变化——这正是目的；需一次性说明而非分四次变）
- **Depends on**: none（但应早于任何其他改动回测数字的工作；`plans/006` 与本计划同文件不同区域，建议本计划先落地）
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

引擎 docstring 宣称 "No look-ahead - a signal generated on bar ``i`` is executed on bar ``i+1`` at the open"。这个承诺只在 `signals[i]` 确实由第 i 根 bar 的数据产生时成立——但**全部内置策略返回的是更短、有偏移的信号表**：`signals[k]` 对应第 `k+offset` 根 bar（ma_crossover/macd/rsi 偏移 1，turtle 偏移 entry_period≈20）。引擎按 `signals[i] ↔ bar i` 读取并在 `i+1` 开盘成交，于是 ma_crossover 的买入在"产生信号那根 bar 的开盘价"成交（提前一根），turtle 的成交用了 ~19 根未来数据。**所有单标的回测、策略对比、走查、GA 进化的收益数字被系统性高估。** 同一次修复窗口内还要处理三个指标准确性问题（见下），避免回测数字分多次变动、无法向用户解释。

附带修复（同文件、同验证回路，一次落地）：
- **B. 年化口径**：`calc_annualized_return(total, days)` 收到的是交易日数（`days = len(bars)`，约 243/年），却按 365 天年做指数——一年期回测 10% 总收益被年化成 ≈15.4%。
- **C. 权益曲线错位一天**：`equity_history` 首元素是开局资金（无任何 bar 时记录），`zip(result.dates, result.equity_curve)` 把开局资金标在首个交易日并丢掉最后一天。
- **D. 过期订单处理与注释矛盾**：注释说"上一根未成交订单丢弃防陈旧成交"，代码却保留它重试——涨跌停拒单的订单可能在信号后第 2 根成交。契约决策（见 Step 5）：**采用注释行为**（订单只享有一次次根开盘的成交尝试，未成交即丢弃），与 docstring 的一次性语义一致。

## Current state

- `backend/quant/engine.py:163-168` — 引擎的契约假设（注释原文）："a signal at index i is filled at index i+1, never at i"；`signals = strategy.generate_signals(bars, ...)` 一次性生成。
- `backend/quant/engine.py:190-215` — 主循环（摘录要点）：
  ```python
  for signal, gen_idx in pending_orders:
      filled = self._fill_order(signal=signal, generated_at=gen_idx, bar_index=i, ...)
      if not filled and gen_idx == i - 1:
          # An order from the immediately preceding bar that did not
          # fill (e.g. limit-locked) is dropped to avoid stale fills.
          still_pending.append((signal, gen_idx))   # ← 与注释矛盾：实际保留了
      elif not filled:
          pass
  pending_orders = still_pending
  if i < len(signals):
      new_signal = signals[i]
      if new_signal.action in ("buy", "sell"):
          pending_orders.append((new_signal, i))
  ```
- `backend/quant/engine.py:221` — `days = len(bars)` 传入 `build_performance_summary`。
- `backend/quant/metrics.py:46-50` — `calc_annualized_return`：`return (1 + total_return) ** (365.0 / days) - 1`。
- `backend/quant/strategies/ma_crossover.py:33` — `for i in range(1, len(bars)):`（返回 `len(bars)-1` 条；`signals[k]` 由 bar `k+1` 产生）。
- `backend/quant/strategies/turtle.py:36` — `for i in range(entry, len(bars)):`（偏移 entry_period，默认 20；其注释 "exclude today's high (no look-ahead)" 只保证信号内部不算当日，管不住引擎错位）。
- `backend/quant/strategies/rsi_reversal.py:31-37` — `for i in range(len(rsi_values))` 且引用 `bars[i + 1]`（偏移 ≥1）。
- `backend/quant/portfolio.py:59` — `self.equity_history: list[float] = [initial_capital]`（长度恒为 `len(bars)+1`）。
- `backend/api/quant_core.py:467-469` — 单标的回测 payload：
  ```python
  equity_curve = [
      {"date": date, "equity": equity, "value": equity} for date, equity in zip(result.dates, result.equity_curve)
  ]
  ```
- `backend/api/quant_core.py:553-556` — **正确范例**（同文件组合回测分支）：`{"date": date, "equity": equity_values[index + 1], ...} if index + 1 < len(equity_values)`。
- `backend/funds/metrics.py:120-121` — `days = len(navs)` 同样的交易日当年历问题。
- `backend/quant/etf_rotation.py:539` — `build_performance_summary(equity_curve, closed_trades, initial_capital, len(dates))`。
- 现有测试把旧契约钉死：`tests/test_backtest_engine.py:304` `assert len(signals) == len(SAMPLE_BARS) - 1  # starts from index 1`（MA 与 MACD 各一处）。这些是**需要随契约更新**的断言，不是保留对象。
- 策略目录：`backend/quant/strategies/` 下还有 `macd_momentum.py`、`boll_break.py`、`dip_reversal.py`、`momentum_topn.py`、`volume_break.py` 等（本计划核验过 ma_crossover/turtle/rsi_reversal 三个，其余由 Step 2 逐一排查——每个都要确认偏移量）。
- 约定：`BackendStrategy.generate_signals(self, bars, portfolio_state)` 返回 `list[Signal]`；`Signal(action, symbol, shares=..., reason=...)`，warm-up 用 `Signal("hold", symbol, reason="数据不足")`（ma_crossover.py:35 已有此形态，照抄）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_backtest_engine.py tests/test_backtest_constraints.py tests/test_quant_api.py tests/test_portfolio_rotation_api.py tests/test_fund_metrics.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/quant/engine.py`、`backend/quant/metrics.py`、`backend/quant/strategies/*.py`（逐个策略修偏移）
- `backend/api/quant_core.py`（仅权益曲线 zip 一处）
- `backend/quant/etf_rotation.py`（仅年化 days 实参一处）
- `backend/funds/metrics.py`（仅年化 days 来源一处）
- `tests/test_backtest_engine.py`（更新两条钉长度断言 + 新增对齐/指标用例）
- `tests/test_backtest_alignment.py`（新建，characterization + 回归）
- `tests/test_quant_api.py` 或新文件（权益曲线日期对齐用例，按现有结构就近放）

**Out of scope**:
- `backend/quant/local_runner.py` —— 与 `quant_core.py` 的重复/漂移由技术债计划另行处理，本计划不动（避免双写）。
- 前端回测页展示 —— API payload 形状不变（只修正数值与日期对应关系）。
- `backend/quant/constraints.py`、`risk_controller.py` —— 摩擦模型本身无缺陷。
- 任何策略的交易逻辑（信号产生规则）—— 只改返回值对齐，不改策略意见。

## Git workflow

- Branch: `advisor/003-backtest-signal-alignment`
- 提交风格：`fix(quant): align strategy signals to bar indices and correct annualized-return basis`（一个逻辑单元一个 commit：characterization 测试 / 契约修复 / 年化 / 权益曲线 / 过期订单 可分 3-5 个 commit）
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 0: 建立 characterization 基线（先写会失败的测试）

新建 `tests/test_backtest_alignment.py`：

1. **对齐探针**：实现一个玩具策略（继承 `BaseStrategy`，参照 `ma_crossover.py` 的结构），规则为"当 `close[i] > close[i-1]` 时在第 i 根发出 buy"，构造一段手工 bars（含明确递增收口价与可区分开盘价）。断言：buy 信号由第 i 根产生 ⇒ 成交发生在第 `i+1` 根的**开盘价**。当前代码下此测试**必须失败**（成交落在第 i 根开盘价）——把失败信息贴在 commit message 里作为缺陷证据。
2. **长度契约**：断言每个注册策略（`StrategyRegistry` 全量遍历）对一段 60 根样例 bars 返回 `len(signals) == len(bars)`。当前失败。
3. **年化基准**：`calc_annualized_return(0.10, 365) ≈ 0.10`（容差 1e-9）；并钉"252 个交易日 ≈ 1 自然年"：用一段跨 365 自然日、252 根 bar 的 bars 跑引擎，断言 `annualized_return ≈ total_return`（容差 0.02）。
4. **权益曲线对齐**：跑 5 根 bars 的引擎最小用例，断言 API payload 层（`_run_local_backtest` 或等价）首点日期 == 首根 bar 日期且权益 ≠ initial_capital（第一根 bar 收盘后的市值），末点日期 == 末根 bar 日期。

**Verify**: `python -m pytest tests/test_backtest_alignment.py -q` → 相关用例按预期失败（这是本步骤的"通过"标准；在 commit message 记录失败列表）。

### Step 1: 策略契约改为"对齐 bars 长度"

逐一修改 `backend/quant/strategies/*.py`（`__init__.py` 与 `base.py` 除外）：

- 循环起点从 `range(offset, len(bars))` 改为 `range(len(bars))`，循环体开头保留 warm-up 分支：`if i < required_warmup: signals.append(Signal("hold", symbol, reason="数据不足")); continue`。ma_crossover 的 `if i < self.params["long_period"]` 分支已是此形态，把 `range(1, ...)` 改为 `range(len(bars))` 并把 `i == 0` 并入 warm-up 分支即可；turtle 把 `range(entry, ...)` 改为全量 + `if i < entry` 暖机；rsi_reversal 把 `bars[i + 1]` 的索引换算回 `bars[i]`（注意 rsi_values 与 closes 的原生偏移：`rsi_values[0]` 对应 closes[period+1]，改造时显式写出换算注释）。
- 每个策略改完后在文件内自查：`return` 前 `assert len(signals) == len(bars)`（开发期断言，保留无害）。
- `backend/quant/strategies/` 目录清单以 `ls backend/quant/strategies/*.py` 实际为准，逐一核对，**不得遗漏自定义/新增策略**。

**Verify**: `python -m pytest tests/test_backtest_alignment.py -q -k "长度 or contract or len"`（按你实际命名选择 `-k`）→ 长度契约用例通过。

### Step 2: 引擎加契约断言

`backend/quant/engine.py` 在 `signals = strategy.generate_signals(...)` 之后加：

```python
if len(signals) != len(bars):
    raise ValueError(
        f"策略 {strategy.name} 返回 {len(signals)} 条信号, 与 {len(bars)} 根 bar 不对齐; "
        "策略契约要求 signals[i] 由第 i 根 bar(含)之前的数据产生, 暖机位用 hold 补齐。"
    )
```

**Verify**: `python -m pytest tests/test_backtest_alignment.py -q` → 对齐探针通过（不再失败）。

### Step 3: 年化口径改自然日

- `backend/quant/engine.py:221`：`days = len(bars)` 改为从 bar 日期算自然日——解析 `bars[0]["date"]`/`bars[-1]["date"]`（`YYYY-MM-DD`，用 `datetime.strptime` 或 `datetime.date.fromisoformat`），`days = max((last - first).days, 1)`。
- `backend/quant/etf_rotation.py:539`：`build_performance_summary(..., len(dates))` 最后一个实参改为 `(dates[-1] - dates[0]).days`（dates 为字符串则先解析；该函数内已有日期处理惯例，沿用）。
- `backend/funds/metrics.py:120-121`：`days = len(navs)` 改为基于 nav 记录日期字段的自然日差。**先确认 nav 记录含日期字段**（查 `calc_nav_returns` 的输入约定与调用方）；若记录无日期字段，是 STOP 条件（见下），不得回退为旧行为。
- `backend/quant/metrics.py` 的 `calc_annualized_return(total_return, days)` 签名不变（语义变为"自然日"），更新 docstring；`build_performance_summary` 里 `trading_days` 标签保留原义（交易日数），不要把两个口径混在一个字段里——如 summary 需要，另加 `calendar_days` 字段而非改 `trading_days`。

**Verify**: `python -m pytest tests/test_backtest_alignment.py tests/test_fund_metrics.py -q` → 年化基准用例与既有基金指标测试全过。

### Step 4: 权益曲线与日期对齐

`backend/api/quant_core.py:467-469` 改为镜像同文件 :553-556 的正确写法：

```python
equity_values = result.equity_curve
equity_curve = [
    {"date": date, "equity": equity_values[index + 1], "value": equity_values[index + 1]}
    for index, date in enumerate(result.dates)
    if index + 1 < len(equity_values)
]
```

**Verify**: Step 0 的权益曲线对齐用例通过；`python -m pytest tests/test_quant_api.py -q` 全过。

### Step 5: 过期订单只享一次成交尝试（采用注释契约）

`backend/quant/engine.py:202-208`：删除 `if not filled and gen_idx == i - 1: still_pending.append(...)` 的保留分支，未成交订单一律丢弃（保留注释，并把注释更新为准确描述："未在次根开盘成交的订单（如涨跌停拒单）即丢弃，不做陈旧重试"）。新增回归用例：构造一根涨跌停 bar（参照 `tests/test_backtest_constraints.py` 的 PriceLimitFilter 用例形态），断言信号订单被拒后不会在再下一根成交。

**Verify**: `python -m pytest tests/test_backtest_alignment.py tests/test_backtest_constraints.py -q` → 全过。

### Step 6: 更新旧契约断言并全量回归

`tests/test_backtest_engine.py:304` 及 MACD 同款：`assert len(signals) == len(SAMPLE_BARS) - 1` → `assert len(signals) == len(SAMPLE_BARS)`，注释改为 `# 与 bars 等长, 暖机位为 hold`。然后全量回归。

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Test plan

- `tests/test_backtest_alignment.py`（新建）：对齐探针、全注册策略长度契约、年化基准（365 自然日 ≈ 1 年）、权益曲线日期对齐、涨跌停订单不陈旧重试。结构参照 `tests/test_backtest_engine.py`（SAMPLE_BARS 的构造方式可直接借用）。
- 更新：`tests/test_backtest_engine.py` 两条长度断言（Step 6）。
- 若某策略已有独立测试文件钉了旧长度（用 `grep -rn "len(signals)" tests/ | grep -v alignment` 排查），一并按新契约更新。
- 验证：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -rn "len(signals) == len(SAMPLE_BARS) - 1" tests/` 无匹配
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过，含新建的 alignment 测试文件
- [ ] `python -c` 抽查：`MAStrategy().generate_signals(bars60)` 长度 == 60（60 根样例）
- [ ] 引擎对不等长信号表抛 `ValueError`（手工单行脚本验证）
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `backend/quant/strategies/` 中存在不继承 `BaseStrategy`、或信号语义与"按 bar 对齐"根本不兼容的策略（例如本身返回的是"交易指令"而非"逐 bar 信号"）——不要强行套契约，记录并报告。
- `backend/funds/metrics.py` 的 nav 输入记录不含日期字段（无法算自然日）。
- Step 0 的对齐探针在**未修改**代码时竟然通过（说明错位机制理解有误，重新调查后再动手）。
- 修复后某个既有测试断言的是"旧（虚高）收益数值"本身而非结构——记录该测试，报告，由人决定是按新口径重算基线还是标注；不要默默改数字基线。

## Maintenance notes

- 落地后**所有历史回测数字不可与旧版直接对比**；对外口径建议："修复了信号对齐与年化口径，旧结果整体偏乐观"。报告/实验存档（experiment_store）中的旧记录保留原样即可，不要回填。
- 未来新增策略的评审 checklist 第一条：`generate_signals` 返回与 bars 等长、暖机 hold 补齐；引擎的 ValueError 会兜底，但评审应前置拦截。
- PR 评审重点：rsi_reversal 的索引换算（最容易改错的一位）；`calc_annualized_return` 调用方是否全部改为自然日；`trading_days` 字段语义未被偷换。
- 明确延期：真实逐根流式/向量化引擎、复权处理、`local_runner.py` 去重，均不在本计划。
