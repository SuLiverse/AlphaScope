# Plan 018: 聚合 K 线对缺失/非法 OHLC 字段免疫（low 不再被 0 污染）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/price_periods.py tests/test_price_periods.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（只丢弃本就非法的 bar；正常数据路径不变）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

周/月/年 K 聚合时，`high/low` 用 `_as_number` 对组内所有 bar 取 max/min——`_as_number` 把缺失/非法值强转为 `0.0`。组内只要有一根 bar 缺 `low` 字段（上游数据源稀疏字段时会发生），聚合结果的 `low` 变成 `0.0`，`amplitude` 随之爆炸为荒谬值。上游的 `filter_incompatible_price_bars` 对零收盘 bar 是**跳过评估而非丢弃**（`close <= 0: continue`——不标记删除），所以这类 bar 会一路到达聚合器。置信度中等（需要数据源实际吐出残缺 bar），但修复是纯防御性的，成本 S。

## Current state

- `backend/price_periods.py:97-111` — 聚合核心：
  ```python
  for group in groups:
      first_dt, first_bar = group[0]
      last_dt, last_bar = group[-1]
      open_price = _as_number(first_bar.get("open"))
      close = _as_number(last_bar.get("close"))
      high = max(_as_number(bar.get("high")) for _, bar in group)
      low = min(_as_number(bar.get("low")) for _, bar in group)   # ← 缺失 low 被 0.0 污染
      volume = sum(_as_number(bar.get("volume")) for _, bar in group)
      amount = sum(_as_number(bar.get("amount")) for _, bar in group)
      base = previous_close or open_price or close
      change_pct = ((close - base) / base * 100) if base else 0.0
      amplitude = ((high - low) / base * 100) if base else 0.0
  ```
- `backend/price_periods.py` 的 `_as_number`（文件上部，`grep -n "def _as_number" backend/price_periods.py` 定位）：非法值 → `0.0`。
- `backend/price_quality.py:70-72` — 上游过滤器对 `close <= 0` 的 bar `continue`（跳过评估，不丢弃）。
- 测试：`tests/test_price_periods.py` 已存在（先读，沿用其 bar 构造方式）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_price_periods.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/price_periods.py`（`aggregate_price_bars` 的组内过滤/计算）
- `tests/test_price_periods.py`（追加用例）

**Out of scope**:
- `backend/price_quality.py` 的"跳过评估 vs 丢弃"语义——那是相邻比率异常过滤器的设计选择，改动影响面大于本问题。
- open/close/volume/amount 的聚合口径（缺失 volume 计 0 是合理默认）。
- 前端 K 线展示。

## Git workflow

- Branch: `advisor/018-kline-aggregation-guard`
- 提交风格：`fix(prices): ignore non-positive OHLC bars when aggregating period candles`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: characterization 测试先行

`tests/test_price_periods.py` 追加：构造一组待聚合 bar（同一周期内），其中一根 `low` 字段为 `None`（或缺失），其余正常；调 `aggregate_price_bars(..., "1w")`，断言聚合结果的 `low` 等于正常 bar 的最小 low（**> 0**），`amplitude` 在合理量级（< 100）。当前代码下 `low == 0.0` 断言失败——记录失败作为缺陷证据后进入 Step 2。

**Verify**: `python -m pytest tests/test_price_periods.py -q -k "聚合 or aggreg"` → 新用例按预期失败。

### Step 2: 组内非法 bar 过滤

`aggregate_price_bars` 的组循环开头加防御：

```python
valid = [bar for _, bar in group if _as_number(bar.get("open")) > 0 and _as_number(bar.get("high")) > 0 and _as_number(bar.get("low")) > 0 and _as_number(bar.get("close")) > 0]
if not valid:
    continue
```

后续 open/close/high/low/volume/amount 一律基于 `valid` 计算（注意原代码的 `first_bar`/`last_bar` 时序语义：用 `valid[0]`/`valid[-1]` 替代，保持日期来自组首尾的原逻辑或同步改用 valid 的首尾 bar 日期——选择语义更自洽的后者，并在注释说明）。

**Verify**: Step 1 的用例转绿；`python -m pytest tests/test_price_periods.py -q` → 全过。

### Step 3: 边界用例补齐

追加：整组 bar 全部非法 → 该周期被跳过（结果中无此周期）；单 bar 组正常聚合；`volume` 缺失按 0 计（既有行为保持，断言不变）。

**Verify**: `python -m pytest tests/test_price_periods.py -q` → 全过，新增 ≥3 用例。

## Test plan

- 见 Step 1/3。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] 缺失 `low` 的 bar 不再产出 `low == 0.0` 的聚合结果（测试断言）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `aggregate_price_bars` 的调用方依赖"非法 bar 也产出聚合点"（例如点位计数对齐——`grep -rn "aggregate_price_bars" backend/ | grep -v "def aggregate"` 排查各调用方对结果长度的假设）。
- `_as_number` 的语义与摘录不符（例如它已返回 `None` 而非 `0.0`）——以现状为准调整过滤写法。
- 聚合函数签名/返回结构与"Current state"不符。

## Maintenance notes

- 本修复与 `plans/003`（回测正确性）独立：回测走 `normalize_bars`/引擎自己的过滤，不经过本聚合器。
- PR 评审重点：`valid[0]`/`valid[-1]` 替代后周期内 open/close 的时序语义是否保持（组内 bar 已按日期排序——确认函数上游排序逻辑）。
- 明确延期：`price_quality.py` 的过滤语义统一（跳过 vs 丢弃）留待数据源治理专项。
