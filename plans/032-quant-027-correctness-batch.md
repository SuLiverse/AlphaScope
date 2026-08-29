# Plan 032: 修复 advisor/027 新量化代码三处正确性缺陷——ATR 因子错位、箱体/杯柄突破分支永不可达、海龟参数窗口无保护

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 375285d..HEAD -- backend/quant/factor_registry.py backend/quant/patterns.py backend/quant/strategies/turtle.py tests/test_factor_registry.py tests/test_patterns.py tests/test_turtle_params.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M（三处独立修复，同一批 027 新代码）
- **Risk**: LOW–MED（会改变部分因子/回测输出的数值，属"修复错误数字"，需同步更新受影响的 golden 断言）
- **Depends on**: **advisor/027 分支并入 main**（本计划的修复对象就是 027 引入的代码；若 027 尚未合并，直接在 `advisor/027` 分支之上切工作分支修复，随 027 一起合入）
- **Category**: bug
- **Planned at**: commit `375285d`（advisor/027 分支 tip），2026-08-30

## Why this matters

027 号计划（汲取买卖点工具结构算法）引入的四组新代码里有三处实证缺陷：

1. **ATR 因子序列错位**：`_atr_pct` 用"过滤掉无效 close 之后的 closes"与"未过滤的 highs/lows"按下标配对——只要历史中有一根 K 线 close 缺失，其后所有 TR 的前收盘（PDC）错位一根，ATR 数值大幅失真（审计复现：同一序列插一个坏 close，atr_20 从 2.696% 变 0.576%）。该因子流入技术因子表、SQLite 缓存与因子矩阵，**错数字静默进入研究结论**。
2. **箱体/杯柄突破分支死代码**：上/下轨与柄高把检测 bar 自身算进窗口，`close > upper` / `close < lower` / `close > handle_high` 对合法 OHLC 永不成立——两个形态的看涨/看跌突破输出从未触发过，功能事实上未生效。
3. **海龟参数无校验**：`exit_period > entry_period` 或周期 ≤0 时 `lows[i - exit_p : i]` 产生空切片 `ValueError`（遗传优化器按独立区间采样， routinely 采到该区域后被 `_safe_eval` 静默记为最差分），或负起点回卷出错误通道。

## Current state

- `backend/quant/factor_registry.py:310-330` — `_atr_pct`（现状节选）：
  ```python
  def _atr_pct(bars, closes, window=20):
      ...
      highs = _series(bars, "high")     # ← 未过滤（长度 = 全部 bars，坏值置 0.0）
      lows = _series(bars, "low")
      ...
      start = len(closes) - window      # ← closes 是过滤后的（_closes，:195-206 丢弃坏 close）
      for i in range(start, len(closes)):
          hl = highs[i] - lows[i]       # ← 下标语义混用：i 是 closes 的下标
          pdc = closes[i - 1]
          trs.append(max(hl, abs(highs[i] - pdc), abs(lows[i] - pdc)))
  ```
  `_closes`（`:195-206`）跳过无效 close；`_series`（`:209-219`）保留全部 bars。
- `backend/quant/patterns.py:542-572` — `_box_pattern`：
  ```python
  window = bars[-_BOX_WINDOW:]              # ← 含检测 bar
  upper, lower = max(highs), min(lows)
  ...
  if close > upper:        # ← close ≤ 自身 high ≤ upper，合法数据下不可达
      direction = BULLISH
  elif close < lower:      # ← 同理不可达
      direction = BEARISH
  ```
- `backend/quant/patterns.py:713-728` — `_cup_handle`：`handle_highs = highs[handle_start:]`（含末 bar），`direction = BULLISH if close > handle_high else NEUTRAL`（`:728`）——`close ≤ 末 bar high ≤ handle_high`，不可达。
- `backend/quant/strategies/turtle.py:87-91`（默认路径）与 `:121-124`（ATR/pyramid 路径）：
  ```python
  if i < entry:                       # ← 只挡 entry
      signals.append(Signal("hold", ...)); continue
  prev_high = max(highs[i - entry : i])
  prev_low = min(lows[i - exit_p : i])   # ← i < exit_p 时起点为负
  ```
- 参数入口：`backend/quant/strategies/base.py:45` 直接 `params` 合并无校验；`backend/quant/evolution.py:160-178` 遗传采样 `entry_period ∈ [10,40]`、`exit_period ∈ [5,20]` 独立区间（交叉出 exit>entry 属常态）；`backend/quant/evolution.py:418-437` `_safe_eval` 捕获异常记 `_WORST`（静默）。
- 仓库约定（003 号计划确立的口径）：**任何"日期化"的结构必须只使用该日期之前的数据**；`chanlun_structure.py:43-47` 注释是范例。测试遵循先红后绿。
- 审计已复现：`{entry_period: 20, exit_period: 25}` → `ValueError: min() iterable argument is empty`；`{entry_period: 0}` → `ValueError: max()...`；箱体最后收盘 11.5 vs 上轨 11.6、杯柄收盘 13.0 高于全部柄高均返回 `neutral`。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 定向测试 | `python -m pytest tests/test_factor_registry.py tests/test_patterns.py tests/test_turtle_params.py -q` | 全部通过（含新增） |
| 全量离线 | `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` | 与基线一致；golden 失败仅限本计划说明中列出的预期变化 |
| 漂移探针 | Step 2/3 中的 python -c 断言 | 输出 `OK` |

## Scope

**In scope**:
- `backend/quant/factor_registry.py`
- `backend/quant/patterns.py`
- `backend/quant/strategies/turtle.py`
- `tests/test_factor_registry.py`、`tests/test_patterns.py`、`tests/test_turtle_params.py`（修改/新增用例）

**Out of scope**:
- `backend/quant/evolution.py` 的采样区间设计（是否该约束 exit ≤ entry 是产品决策，只在测试里覆盖该区域不崩即可）。
- `_local_extrema` 的"确认滞后 2 bar、形态日期回标"问题（head-shoulders/double-top 的几何锚定 vs 确认日期）——已记录为设计项，另行讨论。
- `chanlun_structure` 的出场语义（跌回区间 vs 跌破区间）——docstring 与实现一致，属策略设计确认项。
- 其余因子（`_donchian_width_pct` 已核验正确，勿动）。

## Git workflow

- Branch: `advisor/032-quant-027-correctness`（自 advisor/027 已合并后的 main 切出；若 027 未合并，自 `advisor/027` tip 切出并在 README 状态中注明）
- Commit style: conventional commits（中文正文），先红后绿的分步提交
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: 海龟参数保护

`backend/quant/strategies/turtle.py`：在两条信号循环路径统一加"所需窗口下界"保护。设 `warmup = max(entry, exit_p, system2 if system2 > 0 else 0, atr_period if use_atr_stop else 0)`，把 `if i < entry` 改为 `if i < warmup`（reason 仍为 "数据不足"）；并在 `generate_signals` 入口校验 `entry >= 1`、`exit_p >= 1`、`system2 >= 0`、`atr_period >= 1`（不合法抛 `ValueError(f"参数不合法: ...")`，消息点名参数）。**不要**改变 warmup 之后窗口语义（`[i - window : i]` 排除当日保持不变——027 的无未来函数口径不可回退）。

**Verify**: `python -c "import sys; sys.path.insert(0,'.'); from backend.quant.strategies.turtle import TurtleStrategy; s=TurtleStrategy(); import inspect; print('ok')"` → `ok`；行为断言在 Step 4 测试中。

### Step 2: 箱体/杯柄轨道排除检测 bar

`backend/quant/patterns.py`：
- `_box_pattern`：轨道窗口改为 `bars[-_BOX_WINDOW - 1 : -1]`（即"检测 bar 之前的 `_BOX_WINDOW` 根"），`highs/lows/upper/lower/touches` 全部基于该窗口；`last`/`close` 仍取 `bars[-1]`；`idx` 仍为 `n - 1`。若 `n < _BOX_WINDOW + 1` 则 return []。触及计数（`_distinct_touches`）的索引现在相对新窗口——若 `detail`/`projection` 未引用索引则无影响，先读代码确认。
- `_cup_handle`：`handle_highs`/`handle_lows` 切片改为 `[handle_start : w - 1]`（排除检测 bar）；`close` 与 `last_i` 语义不变；确认 `handle_start >= w - 2` 的边界在新切片下仍成立（现为 `handle_start >= w - 2` return []，保持）。

**Verify**: `python -c "import sys; sys.path.insert(0,'.'); ..."` 构造一个"检测 bar 收盘越过前窗上轨"的合成序列，断言 direction == BULLISH（具体构造放进 Step 4 的测试，跑红→修复→跑绿）。

### Step 3: `_atr_pct` 序列对齐

`backend/quant/factor_registry.py:_atr_pct`：改为**单次过滤、三序列同源**——先构造 `valid = [b for b in bars if isinstance(b, dict) 且 float(b.get('close')) 有效且 > 0]`，`closes = [float(b['close']) for b in valid]`，`highs = [float(b['high']) if 有效 else 0.0 for b in valid]`（lows 同理）。窗口起点与循环全部基于 `valid` 的长度。行为变化口径：任一坏 close 现在会**整体右移对齐**而不是错位；`_dist_high` / `_range_pos` 若存在同样的 closes/bars 混用（审计提示 `closes[-1]` 对 bar 索引窗口），逐一核对并按同一原则对齐——但只改确认存在混用的，勿动已核验正确的 `_donchian_width_pct`。

**Verify**: `python -c` 探针：25 根合成 bar（第 20 根 close=200 的跳空 + 中段插一个 close=None）断言修复后 atr_20 与"手工逐 bar 计算"一致（探针逻辑写进测试）。

### Step 4: 先红后绿测试

- `tests/test_turtle_params.py` 新增：`exit_period=25, entry_period=20` 不抛且前 25 bar 全 hold；`entry_period=0` 抛 `ValueError` 且消息含 "entry"；ATR 路径同样两条。
- `tests/test_patterns.py` 新增：箱体真突破（检测 bar 收盘 > 前窗上轨）→ BULLISH；箱体跌破下轨 → BEARISH；杯柄收盘 > 前窗柄高 → BULLISH；以及"窗口内正常震荡 → NEUTRAL"防误报。
- `tests/test_factor_registry.py` 新增：坏 close 中插后 atr_20 对齐手算值；全干净序列数值与修复前**一致**（防过度修复）。
- golden 断言：若既有 golden 数值因本次修复变化，逐条核对是"错误数字被纠正"后更新期望值并在断言旁注释本计划号；无法解释的变化即为修复引入的新错——STOP。

**Verify**: `python -m pytest tests/test_turtle_params.py tests/test_patterns.py tests/test_factor_registry.py -q` → 全过。

## Test plan

- 用例清单见 Step 4；结构参照 `tests/test_turtle_params.py` / `tests/test_patterns.py` 既有写法（合成 bars dict 列表，无网络）。
- 全量回归必须跑：本计划会改因子数值，任何未预期的 golden 变化都要能解释。

## Done criteria

- [ ] `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 全过（golden 更新均有注释依据）
- [ ] 三个新场景用例存在且通过（turtle 越界、箱体/杯柄真突破、ATR 坏 close 对齐）
- [ ] `grep -n "bars\[-_BOX_WINDOW:\]" backend/quant/patterns.py` 无匹配（旧含检测 bar 窗口已移除）
- [ ] 无 Scope 外文件改动（`git status`）

## STOP conditions

- advisor/027 尚未合并且无法在其上建立工作分支（合并决策属维护者）。
- golden 变化无法归因于本计划描述的三处修复（说明对现有行为的理解有误）。
- `_box_pattern` 的触及计数/投影逻辑与轨道窗口耦合，排除检测 bar 后需要重新设计触及语义——停下报告设计方案。
- 发现 `_atr_pct` 之外同一文件存在连锁错位且修复会成倍扩大数值变化面。

## Maintenance notes

- 本计划是"修错误数字"型变更：合入后应在 CHANGELOG 标注 atr_20 / 形态识别输出与海龟回测行为的变化，避免使用者把新旧数字当同一口径比较。
- 遗传优化器对 exit>entry 区域静默记 `_WORST` 的行为在参数校验后依然存在（错误变成显式 `ValueError` 仍被 `_safe_eval` 吃掉）——是否让 evolution 打日志/跳过该区域属后续改进。
- 评审重点：warmup 语义改动是否影响 027 "默认路径数字保持不变"的承诺（在 entry/exit/atr 默认参数下 warmup 应等于旧 `entry`，用测试钉死）。
