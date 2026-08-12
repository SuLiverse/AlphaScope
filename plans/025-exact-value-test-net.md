# Plan 025: 为 DCA 模拟与回测引擎补精确值测试网（plan 003/004 的前置安全网）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 06182ca..HEAD -- backend/funds/dca.py backend/quant/engine.py backend/api/quant_core.py tests/test_dca_simulation.py tests/test_backtest_engine.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1（它是 plan 003/004 修复的前置回归网）
- **Effort**: M
- **Risk**: LOW-MED（纯测试，不改生产代码；只"锁定当前行为"）
- **Depends on**: none（**必须**在 plan 003/004 之前合并，或与之同时但在其改动前落地）
- **Category**: tests
- **Planned at**: commit `06182ca`, 2026-08-01

## Why this matters

两处资金核心计算当前被"烟雾测试"保护，任何公式错误都能全绿通过：

1. **DCA 定投模拟**（`backend/funds/dca.py`）：现有测试（`tests/test_dca_simulation.py:30-113`）只断言 `>0`、区间、方向——与当前**已知错误**的数学（plan 004 记录的：`_find_nearest_nav` 未来净值、总收益率按 day-0 计、30 天固定步长）完全兼容。plan 004 修复公式时会改全部数字，没有网兜底就无法证明修对了、也无法防回归。
2. **回测引擎**（`backend/quant/engine.py`）：`tests/test_backtest_engine.py:353-398` 只断言 `final > 0`、key 存在。plan 003 会改信号对齐与指标，同样需要精确基线。

本计划只写**表征测试（characterization tests）**：用手工推导的精确值锁定**当前行为**（含已知缺陷点），并在注释中标记哪些行对应 plan 003/004 必须更新的目标值。生产代码一行不动。

## Current state

- `backend/funds/dca.py` — 先通读全文（约 150+ 行）。已知关键行为（行号以实测为准，**以你通读后的实际代码为准**）：
  - `DCASimulator.simulate(nav_records, amount, frequency, start_date, end_date)` → 结果含 `total_invested`/`final_value`/`total_return`/`avg_cost`/`investment_count`/`records`（读文件确认确切字段）
  - `_generate_dates` 用固定 30 天步长生成投资日（注意：计划称 :28-29 有"先赋值后覆盖"的死代码——不用修，只记录）
  - `_find_nearest_nav` 用 `abs()` 日期差（可能取到未来净值——**当前行为，测试按现状锁定**）
  - 总收益率按"全部投入视为第 0 天"计算（**当前行为**）
- `backend/quant/engine.py` — 通读 `BacktestEngine`（`run(strategy, bars, symbol)`）与交易循环。测试模式参考 `tests/test_backtest_engine.py` 现有文件（`TestBacktestEngine` 类、`_make_bars` 之类辅助构造假 K 线——读它，模仿它的 bar 构造方式）。
- 现有测试：
  - `tests/test_dca_simulation.py`（113 行，6 个测试，全是弱断言）
  - `tests/test_backtest_engine.py`（约 400 行，强断言集中在费用/滑点约束层 `test_backtest_constraints.py`；引擎层弱）

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| DCA 定向 | `python -m pytest tests/test_dca_simulation.py -q` | 全过（含新增） |
| 引擎定向 | `python -m pytest tests/test_backtest_engine.py tests/test_backtest_constraints.py -q` | 全过（含新增） |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全过 |
| Lint      | `python -m ruff check tests/test_dca_simulation.py tests/test_backtest_engine.py` | exit 0 |

## Scope

**In scope**:
- `tests/test_dca_simulation.py`（追加精确值测试）
- `tests/test_backtest_engine.py`（追加 golden 测试）

**Out of scope**:
- `backend/funds/dca.py`、`backend/quant/engine.py`、`backend/api/quant_core.py`、`backend/quant/metrics.py` —— **只读**。哪怕看到明显 bug 也**不修**，在最终报告中列出行号供 plan 003/004 使用。
- plan 003/004 的公式修复本身。
- 新增任何生产代码。

## Git workflow

- Branch: `advisor/025-exact-value-test-net`
- 提交风格：`test(quant): add exact-value regression net for DCA simulation and backtest engine`
- 不要 push、不要开 PR。

## Steps

### Step 1: 通读被测代码，确定精确场景

读 `backend/funds/dca.py` 全文与 `backend/quant/engine.py` 的交易循环、`build_performance_summary` 输出形状。确定：

- DCA：`DCASimulator.simulate` 的返回字段名与 `records` 结构；`_generate_dates` 的日期生成规则；`_find_nearest_nav` 的匹配规则。
- 引擎：`engine.run` 返回 `result.equity_curve`/`result.trades`/`result.performance` 的形状；`BacktestEngine(initial_capital=..., commission_rate=...)` 构造参数。

**Verify**: 在 REPL 里跑一个最小 DCA 模拟（用 `tests/test_dca_simulation.py` 的 `_make_nav_records` 生成 8 条记录，3 期投资），打印 `total_invested`/`investment_count`/`total_return`/`avg_cost`/`final_value`，对照你的通读理解。

### Step 2: 手算 DCA golden 值，写精确测试

追加到 `tests/test_dca_simulation.py`（新类 `TestDCAGoldenValues`）。设计一个**完全手工可推**的场景：

- `nav_records`：8 条，`date` 用真实日历日（如 2024-01-02 至 2024-01-09，日频），`nav` 用简单的整数/半整数（如 1.00, 1.10, 1.05, 1.20, 1.15, 1.25, 1.30, 1.35）。
- `amount=1000`，`frequency=MONTHLY`，`start_date="2024-01-01"`，`end_date="2024-01-31"`。
- **手算**（按代码实际语义）：投资日（30 天步长）落在哪些日期、每次投入买入份额（`amount / nav`，注意份额舍入规则——读代码确认）、累计投入、期末价值（按**当前**的收益率公式）、`total_return`、`avg_cost`、`investment_count`。
- 断言用 `pytest.approx`（避免浮点尾差），每个字段一个断言。
- 关键注释（写在测试 docstring 里，中文）：
  ```
  本测试锁定的是 2026-08-01 的当前行为（含已知缺陷：30 天固定步长 /
  未来净值匹配 / 第 0 天计收益）。plan 004 修复公式后必须同步更新下方
  期望值——更新即证明修复生效；若修复后本测试仍过，说明修复未生效。
  ```
- 再补一个 `test_generate_dates_sequence`：直接断言 `_generate_dates`（或对应私有函数，读代码确认名字与可见性）对给定起止日返回的日期序列——把 30 天步长行为精确钉死。

**Verify**: `python -m pytest tests/test_dca_simulation.py -q` → 全部通过（新增测试用你手算的值，若与代码行为不符，回到 Step 1 重新核对理解——**不要**为了让测试过而改用代码跑出来的值，除非你的推导有误；两者不一致时 STOP 报告）。

### Step 3: 手算回测 golden 测试

追加到 `tests/test_backtest_engine.py`（新类 `TestBacktestEngineGolden`）。设计确定性场景：

1. `test_engine_accounting_identity` — 任意策略跑完后断言记账恒等式：`final_equity == cash + Σ(shares_i * price_i)`。需要从引擎结果/内部状态取持仓——读 `engine.py` 确认 `result` 是否暴露持仓；若 `equity_curve` 每点是标记市值，则恒等式换成对 `equity_curve[-1]` 的验证。若引擎不暴露 cash/持仓细节，改用下面的全胜场景精确断言。
2. `test_golden_run_hand_computed` — 用**极简确定性策略**（如固定每日买入 1 股、无择时；或参照 `test_backtest_engine.py` 现有测试用的策略构造方式）在 5-10 根手工构造 K 线上运行：
   - `BacktestEngine(initial_capital=100000, commission_rate=0.0)`（零摩擦，手算友好）
   - 手算：每笔成交的成交价、现金变动、最终 `total_return`（按 `performance["total_return"]` 字段的实际语义）
   - 断言 `performance["total_return"]`、`final_equity`、`trades` 数量精确等于手算值（`pytest.approx`）
   - 注释：plan 003 会改信号对齐/指标口径，届时本测试的期望值必须随 plan 003 有意更新；"若 plan 003 合并后本测试仍全绿，需人工确认修复未影响本场景或期望值已同步"。
   - 若引擎有滑点/税费默认值，显式传 0 或按默认值手算（读构造参数确认）。

**Verify**: `python -m pytest tests/test_backtest_engine.py -q` → 全过（新增测试全绿；若手算与代码不符，先自查推导；仍不符则 STOP 报告，不强行改断言凑绿）。

### Step 4: 全量回归 + lint

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`python -m ruff check tests/test_dca_simulation.py tests/test_backtest_engine.py` → exit 0。

## Test plan

- DCA：`TestDCAGoldenValues`（精确值全字段断言 + `_generate_dates` 序列断言）。
- 引擎：`TestBacktestEngineGolden`（记账恒等式或全胜精确 run + 手算 total_return/final_equity/trades 数量）。
- 全部离线、确定性数据，无网络/无真实行情。
- 模式参照：现有 `tests/test_dca_simulation.py`（fixture 构造）+ `tests/test_backtest_engine.py`（K 线构造方式）。

## Done criteria

- [ ] `python -m pytest tests/test_dca_simulation.py -q` → 全过，含新 golden 测试
- [ ] `python -m pytest tests/test_backtest_engine.py -q` → 全过，含新 golden 测试
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过
- [ ] `python -m ruff check tests/test_dca_simulation.py tests/test_backtest_engine.py` → exit 0
- [ ] `git diff --stat` 只含 2 个测试文件
- [ ] 生产代码（`backend/`）零改动（`git status` 确认）
- [ ] 已按 Git workflow 提交到 `advisor/025-exact-value-test-net` 分支

## STOP conditions

- 手算值与代码行为在核对后仍不一致（推导无误但代码输出不同）——说明代码与摘录理解有偏差，报告而不是凑断言。
- 需要修改生产代码才能让测试通过。
- `DCASimulator.simulate` 或 `BacktestEngine.run` 的接口/返回形状与描述不符。
- 发现现有测试文件结构完全不同于描述（如类名/辅助函数差异太大）——调整测试写法可以，但接口理解偏差要报告。

## Maintenance notes

- **这是 plan 003/004 的前置计划**：`plans/README.md` 依赖注记已声明。两个修复计划合并时，执行者必须同步更新本计划锁定的期望值（测试注释里已写指引）。
- 评审时重点：期望值是否真是手算推导（不是从代码输出抄的）——抽查一个中间量。
- 若未来 DCA/引擎 API 重构（如改返回 dataclass），这些 golden 测试是第一批要同步改的——保持断言只依赖公共字段。
