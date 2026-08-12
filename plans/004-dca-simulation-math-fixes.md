# Plan 004: 修复定投模拟的三处数学错误与遗留 DCA 端点的假公式

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/funds/dca.py backend/api/funds.py tests/test_dca_simulation.py tests/test_funds_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED（模拟结果数字变化——这是修复目的；用户可见，需在提交说明中写明）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

定投（DCA）模拟是用户直接看到的决策参考，当前三处数学错误叠加：

1. **年化收益口径错误**：`total_return = final_value / total_invested - 1` 把每期投入都当作第 0 天一次性投入，再按全程年化——定投的正确口径是对分期现金流求 XIRR（资金加权收益率）。上涨市低估、下跌市高估。
2. **买入可能取到未来净值**：`_find_nearest_nav` 注释写"向前找"（找历史最近），代码却用 `abs()` 日期距离——某期扣款日附近若未来某日净值更近，就按尚不存在的价格成交（模拟器内部的未来函数）。
3. **最大回撤被定投摊薄**：回撤在"市值 = 累计份额 × 净值"曲线上计算，而新投入会持续抬高市值，真实回撤被后续入金掩盖。

另有遗留兼容端点 `_legacy_dca_result`：`final_value = total_invested * growth` 是一次性投入公式冒充定投；对照组"一次性"硬编码 `growth * 0.98`——只要增长率为正，`winner` 恒为 `"dca"`，结论是被构造出来的。

## Current state

- `backend/funds/dca.py:36-51` — `_find_nearest_nav`：
  ```python
  # 找最近的（向前找）
  best = None
  best_diff = float("inf")
  for r in nav_records:
      diff = abs((datetime.strptime(r["date"], "%Y-%m-%d") - datetime.strptime(target_date, "%Y-%m-%d")).days)
      if diff < best_diff:
          best_diff = diff
          best = r["nav"]
  return best
  ```
- `backend/funds/dca.py:135-144` — 终值与年化：
  ```python
  final_nav = nav_records[-1]["nav"]
  final_value = total_shares * final_nav
  total_return = (final_value / total_invested - 1) if total_invested > 0 else 0
  start_dt = datetime.strptime(records[0]["date"], "%Y-%m-%d")
  end_dt = datetime.strptime(end_date, "%Y-%m-%d")
  days = (end_dt - start_dt).days
  annualized_return = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0
  ```
- `backend/funds/dca.py:146-162` — 回撤在含入金的市值曲线上计算（`cumulative_shares * rec["nav"]`）。
- `backend/api/funds.py:335-356` — `_legacy_dca_result`：`final_value = total_invested * growth`；`lumpsum_value = total_invested * (growth * 0.98)`；`"winner": "dca" if final_value >= lumpsum_value else "lumpsum"`。该函数服务 `POST /api/funds/dca/simulate`（:360-362）和 `POST /api/fund-dca/simulate` 的无日期分支（:365-370）。
- `records` 列表（dca.py:111-119）已含每笔扣款的 `date/nav/amount/shares`——XIRR 所需现金流都在，无需改数据结构。
- 测试：`tests/test_dca_simulation.py`、`tests/test_funds_api.py` 已存在，沿用其构造方式（先读它们再写用例）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_dca_simulation.py tests/test_funds_api.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/funds/dca.py`（`_find_nearest_nav` 方向约束、XIRR 年化、单位净值法回撤）
- `backend/api/funds.py`（仅 `_legacy_dca_result` 函数体）
- `tests/test_dca_simulation.py`、`tests/test_funds_api.py`（追加/更新用例）

**Out of scope**:
- `backend/funds/metrics.py` 的通用指标函数 —— 年化口径统一由 `plans/003` 处理（本计划只动 DCA 模拟器自己的年化计算，不碰共享 metrics）。
- 前端定投页展示字段 —— 返回字段名全部保留（`total_return`/`annualized_return`/`max_drawdown` 含义修正，名字不变）。
- `POST /api/fund-dca/simulate` 的有日期分支（走 `DCASimulator`，随之自动修复）。

## Git workflow

- Branch: `advisor/004-dca-math-fixes`
- 提交风格：`fix(funds): use XIRR for DCA annualization, forbid future NAV fills, unitize drawdown`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: `_find_nearest_nav` 只向前找

`backend/funds/dca.py:43-51`：保持精确命中快路径不变；模糊匹配改为只考虑 `r["date"] <= target_date` 的记录，取其中日期最大者。字符串 `YYYY-MM-DD` 可直接字典序比较，无需 strptime（保留现有解析也行，二选一，选改动小的）。

**Verify**: `python -c "from backend.funds.dca import _find_nearest_nav; recs=[{'date':'2024-01-02','nav':1.0},{'date':'2024-01-10','nav':9.9}]; print(_find_nearest_nav(recs,'2024-01-09'))"` → `1.0`（修复前会返回 9.9）

### Step 2: 年化改为 XIRR

在 `backend/funds/dca.py` 新增 `_xirr(cashflows: list[tuple[date, float]], guess=0.1) -> float`：对 `Σ amount_i / (1+r)^((d_i - d_0)/365) = 0` 求解。实现用二分法（区间 `[-0.9999, 10]`，200 次迭代足够），避免 Newton 法在平坦现金流下发散；现金流不含正负两种符号时返回 0.0 并注释原因。在 `simulate` 中：

- 现金流 = 每笔扣款 `(-amount, date)` + 期末 `(+final_value, end_date)`；
- `annualized_return = _xirr(cashflows)`；
- `total_return` 字段保留现有简单口径（它是展示用的"总收益率"，含义成立），不改动。

**Verify**: `python -c "from backend.funds.dca import _xirr; from datetime import date; r=_xirr([(date(2024,1,1),-1000),(date(2024,7,1),-1000),(date(2025,1,1),2200)]); print(round(r,4))"` → 约 `0.1416`（半年期的第二笔把整体年化拉高；用独立 XIRR 工具复核过此数再断言进测试）

### Step 3: 回撤改为单位净值法

`dca.py:146-162`：不再用市值曲线。改为对每条扣款记录计算**份额调整收益率**：`unit_value_i = nav_i / nav_first`（首笔扣款净值归一），在该曲线上算最大回撤。曲线单点或 `nav_first <= 0` 时回撤为 0.0。保留注释说明："市值口径会被后续入金摊薄，故用单位净值口径"。

**Verify**: 新测试（Step 4 用例 c）通过。

### Step 4: 测试（tests/test_dca_simulation.py）

追加用例：
a. **未来净值禁令**：构造 nav 记录使模糊匹配的旧逻辑会选未来日期（Step 1 的验证数据），断言成交价为历史最近净值；
b. **XIRR 正确性**：月定投 1000、净值单边上涨 12 期的合成序列，断言 `annualized_return` 与独立计算的 XIRR 一致（容差 1e-4），且**大于**简单口径 `(final/invested-1)` 按全程年化的旧值（上涨市旧口径低估）；
c. **回撤不被入金摊薄**：构造净值先跌 30% 再回升、期间持续扣款的序列，断言 `max_drawdown` ≈ 0.30（容差 0.01）；
d. 空数据/单点数据不报错（既有行为保持）。

**Verify**: `python -m pytest tests/test_dca_simulation.py -q` → 全过。

### Step 5: 遗留端点改为真公式（`_legacy_dca_result`）

`backend/api/funds.py:335-356`：
- DCA 终值改为逐期复利求和：`final_value = Σ amount * growth^(periods - i)`（i 从 1 到 periods，第 i 期投入享受剩余 `periods - i` 期增长）；
- 一次性对照组改为诚实的"第 0 期全额投入"：`lumpsum_value = total_invested * growth^periods`（注意原公式连 `^periods` 都没有，只有单期 growth——按函数内 `growth = 1 + pct/100` 的语义与 `periods` 的关系实现为幂）；
- `winner` 用两个真实值比较得出；
- 函数顶部加注释："简化确定性模型（固定增长率），仅用于无净值数据时的粗略对比"。

**Verify**: `python -m pytest tests/test_funds_api.py -q` → 全过；`python -c` 手工抽查：growth=1.1、periods=2、amount=1000 ⇒ dca.final_value = 1000*1.1 + 1000 = 2100，lumpsum.final_value = 2000*1.21 = 2420，winner == "lumpsum"。

### Step 6: 全量回归

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`ruff check backend frontend tests && ruff format --check backend frontend tests` → exit 0。

## Test plan

- `tests/test_dca_simulation.py`：Step 4 的 a-d 用例；结构沿用该文件现有的合成 nav 记录方式。
- `tests/test_funds_api.py`：为 `_legacy_dca_result` 的两个端点各加一个数值断言用例（Step 5 的手工数）。
- 验证命令：`python -m pytest tests/test_dca_simulation.py tests/test_funds_api.py -q` → 全过，新增 ≥5 个用例。

## Done criteria

- [ ] Step 1/2/5 的三条 `python -c` 抽查输出与预期一致
- [ ] `python -m pytest tests/test_dca_simulation.py tests/test_funds_api.py -q` 全过
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `records` 现金流结构与本计划描述不符（例如不记录每笔扣款日期）。
- 既有测试里有断言**旧错误数值**（而非结构）的用例——记录清单并报告，由人决定重算基线；不要静默改数字。
- `_legacy_dca_result` 的 `annual_growth_pct`/`periods` 语义与"每期增长率"假设不符（例如它实际是年化且 periods 是年数）——按函数内实际语义调整公式并报告差异，不要照搬 Step 5 的指数关系。

## Maintenance notes

- 落地后历史定投模拟结果与旧版不可比；提交说明中写明口径变化（XIRR / 单位净值回撤 / 禁未来净值）。
- PR 评审重点：`_xirr` 的边界（全负/全正现金流、r 接近 -1）；`_find_nearest_nav` 的日期比较在跨格式（`2024-1-5` vs `2024-01-05`）输入下是否仍正确——若上游可能给非零填充日期，统一规范化后再比较。
- 明确延期：`backend/funds/metrics.py` 的通用年化口径在 `plans/003` 修；定投与真实交易费率的结合不在本计划。
