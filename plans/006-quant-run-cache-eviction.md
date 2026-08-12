# Plan 006: 修复回测运行详情缓存淘汰方向（删旧留新，而非删新留旧）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/api/quant_core.py tests/test_quant_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（行为只在第 51 条运行详情之后变化）
- **Depends on**: 建议排在 `plans/003` 之后（同文件不同区域，避免 diff 互相干扰）
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`_local_run_details` 是回测运行详情的内存缓存，意图是上限 50 条、淘汰最旧。但淘汰切片写反了：`list(keys())[50:]` 选中的是**最新插入**的部分——第 51 次回测完成后，它自己的详情立即被淘汰，运行历史列表里的 `run_id` 随即 404；而最早 50 条详情被永久钉住。症状：服务跑得越久，"查看运行详情"越是稳定地查不到新运行。

## Current state

- `backend/api/quant_core.py:423-425`（一处）与 `:530-532`（另一处，逻辑相同）：
  ```python
  _local_run_details[payload["run_id"]] = payload
  for stale_run_id in list(_local_run_details.keys())[50:]:
      _local_run_details.pop(stale_run_id, None)
  ```
  Python dict 按键的**插入序**迭代：`keys()[50:]` 是索引 50 起的新条目。正确语义是保留最新 50 条、淘汰最旧（`keys()[:-50]`）。
- 相邻的 `_local_runs` 列表用 `del _local_runs[20:]`（:422、:529）截尾保留最新 20 条——语义正确的参照。
- 测试：`tests/test_quant_api.py` 已存在，沿用其结构。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_quant_api.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/api/quant_core.py`（两处淘汰切片）
- `tests/test_quant_api.py`（追加淘汰顺序用例）

**Out of scope**:
- `_local_runs` 的 20 条截尾——语义正确，不动。
- `_local_run_details` 与 `backend/quant/local_runner.py` 的重复状态——由技术债计划另行处理，不要在本计划中顺手合并。
- 把缓存改成持久化/LRU 库——无必要，进程内存缓存是现状设计。

## Git workflow

- Branch: `advisor/006-quant-run-cache-eviction`
- 提交风格：`fix(api): evict oldest local run details instead of newest`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 修两处淘汰切片

`backend/api/quant_core.py` 两处均改为淘汰最旧（保留最新 50 条）：

```python
for stale_run_id in list(_local_run_details.keys())[:-50]:
    _local_run_details.pop(stale_run_id, None)
```

**Verify**: `ruff check backend/api/quant_core.py` → exit 0。

### Step 2: 淘汰顺序测试

`tests/test_quant_api.py` 追加：直接操作模块级 `_local_run_details`（测试间用 fixture 或手工清理恢复原状，参照文件内对模块状态的既有处理），依次插入 55 条假详情（`run-001` … `run-055`），每次插入后执行与生产代码相同的淘汰调用——更好的做法是抽到一个小helper：若两处淘汰逻辑可提取为 `_evict_local_run_details()` 函数，则提取并在两处调用它（推荐，消除第三次写反的可能），测试直接调 helper。断言：插入 55 条后 `run-001..run-005` 被淘汰、`run-006..run-055` 俱在、长度为 50。

**Verify**: `python -m pytest tests/test_quant_api.py -q` → 全过，新增 1-2 个用例。

## Test plan

- 见 Step 2。验证命令：`python -m pytest tests/test_quant_api.py -q` → 全过。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "keys()\[50:\]" backend/api/quant_core.py` 无匹配
- [ ] 两处淘汰逻辑同源（提取 helper）或均为 `[:-50]`
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `_local_run_details` 的读写方不止这两处（用 `grep -rn "_local_run_details" backend/` 核实；若有第三方读写者依赖"旧条目常驻"的现状——极不可能但需确认）。

## Maintenance notes

- 若 `plans/003` 尚未落地，本计划 diff 与它的 `quant_core.py` 改动不重叠（不同行段），按 README 顺序执行即可。
- PR 评审重点：是否真的两处都改了；helper 提取是否改变了调用时机（应在插入后立即淘汰）。
- 明确延期：`local_runner.py` 双份状态合并且前搁置（advisor 报告 DEBT-01，未立项）。
