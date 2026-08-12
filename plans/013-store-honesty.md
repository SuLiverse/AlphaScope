# Plan 013: 组合存储失败要显式失败、基本面缓存不再缓存错误结果

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/funds/portfolio.py backend/api/funds.py backend/fundamentals.py tests/test_funds_api.py tests/test_fundamentals.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（失败变得可见；成功路径不变）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

两处"假成功"：

1. **基金组合静默丢数据**：`FundPortfolioStore.create/update` 把数据库异常 catch 后仅记日志，然后照样返回"已保存"的组合对象；API 层无条件 `success=True`。用户的组合实际从未落库，下次读取凭空消失，全程无任何错误提示。
2. **基本面错误结果按 24h TTL 缓存**：5 路数据源全部失败时 `has_error=True` 的错误载荷照样 `_write_cache`——一次网络抖动把某标的的基本面毒害一整天，期间所有请求都看到"全部数据源不可用"，只能手工 `force_refresh`。

## Current state

- `backend/funds/portfolio.py:54-72` — `create`：
  ```python
  if self._db:
      try:
          with self._db.transaction() as conn:
              conn.execute("INSERT INTO fund_portfolios VALUES (?, ?, ?, ?, ?, ?)", (...))
              conn.commit()
      except Exception as e:
          logger.error(f"保存组合失败: {e}")

  return {"id": portfolio_id, "name": name, ...}   # 无论是否落库都返回
  ```
- `backend/funds/portfolio.py:143-161` — `update` 同款（UPDATE 失败仅 log，仍返回"更新后"对象）。
- `backend/api/funds.py:405-465` — 组合 CRUD 端点（`grep -n "portfolio" backend/api/funds.py | head` 定位 create/update 调用点；现状是拿到 store 返回值就 `ApiResponse(success=True, ...)`）。**先读这段再改。**
- `backend/fundamentals.py:550-556` — `load_fundamentals` 尾部：
  ```python
  # 全部失败才标 has_error
  if not data.financials and not data.top_holders and not data.peers:
      data.has_error = True
      data.error_msg = "; ".join(errors) if errors else "全部数据源不可用"

  # 写缓存
  _write_cache(symbol, data.to_dict())
  return data
  ```
  `_read_cache`（:509-512 调用处）对 TTL 内错误载荷直接命中返回。
- 测试：`tests/test_funds_api.py`、`tests/test_fundamentals.py` 均已存在，沿用其 mock 方式。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_funds_api.py tests/test_fundamentals.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/funds/portfolio.py`（`create`/`update` 失败传播）
- `backend/api/funds.py`（组合 create/update 两个端点的失败映射）
- `backend/fundamentals.py`（`_write_cache` 调用条件一处）
- `tests/test_funds_api.py`、`tests/test_fundamentals.py`

**Out of scope**:
- `delete` 及 `list_all`/`get` 的异常语义（读路径失败不伪造数据，现状可接受）。
- 负缓存（错误结果短 TTL 缓存）——干脆不缓存错误即可，不引入 TTL 分级。
- 前端组合页的错误提示文案。

## Git workflow

- Branch: `advisor/013-store-honesty`
- 提交风格：`fix(funds): propagate portfolio write failures and skip caching failed fundamentals`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 组合存储失败传播

`backend/funds/portfolio.py`：`create`/`update` 的 `except Exception` 分支在 log 后 `raise`（保留日志）。`backend/api/funds.py` 对应两端点：用 try/except 包住 store 调用，异常时 `ApiResponse(success=False, error=f"保存组合失败: {e}")`（沿用该文件既有的错误文案与 `error_code` 惯例——读邻近端点确认是否有 `error_code` 字段用法，有则补一个如 `"PORTFOLIO_SAVE_FAILED"`）。

**Verify**: `python -m pytest tests/test_funds_api.py -q` → 既有用例全过（成功路径不变）。

### Step 2: 组合写失败回归测试

`tests/test_funds_api.py` 追加：monkeypatch 使 `Database.transaction` 抛错（参照文件内既有 mock 方式），调 create 与 update 端点，断言 `success is False` 且 `error` 非空；再断言未 monkeypatch 时成功路径返回 `success is True`（防过度mock）。

**Verify**: `python -m pytest tests/test_funds_api.py -q` → 全过，新增 2 用例。

### Step 3: 基本面错误结果不入缓存

`backend/fundamentals.py:555-556`：

```python
# 写缓存(错误结果不缓存——避免一次抖动毒害 24h TTL)
if not data.has_error:
    _write_cache(symbol, data.to_dict())
```

**Verify**: `python -m pytest tests/test_fundamentals.py -q` → 既有用例全过。

### Step 4: 负缓存回归测试

`tests/test_fundamentals.py` 追加：monkeypatch 5 路 fetch 全部抛错 + 一个计数 spy 包住 `_write_cache`，连续两次 `load_fundamentals(symbol)`，断言两次都返回 `has_error is True`、`_write_cache` 从未被调、且 fetch 被调了两轮（未被缓存短路）。再补一个对照：fetch 成功时 `_write_cache` 被调一次。

**Verify**: `python -m pytest tests/test_fundamentals.py -q` → 全过，新增 2 用例。

## Test plan

- 见 Step 2 / Step 4。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "if not data.has_error" backend/fundamentals.py` 命中
- [ ] 组合 create/update 在 DB 异常时 API 返回 `success=False`（新测试断言）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `backend/api/funds.py` 的组合端点还有**其他**调用方（前端之外）依赖"永远 success=True"（grep 前端 `apps/web/src` 对 `/api/fund-portfolio` 的消费——前端按 `success` 分支处理即为兼容）。
- `FundPortfolioStore` 存在无 db 的内存模式（`self._db is None` 时现状同样返回对象）——该模式语义保持不动（它本来就是易失演示模式），若发现它对端点也报成功，记录并在报告中说明，不擅自改。
- `_write_cache` 另有他处调用且依赖错误缓存（`grep -n "_write_cache" backend/fundamentals.py`）。

## Maintenance notes

- "失败要显式失败"是本仓库既定原则（`_persist_experiment` 的注释"诚实降级:没存就是没存,不假装成功"）——本计划把两处漏网点拉齐到同一原则；评审时如发现其他模块有同类"catch 后返回成功对象"模式，记录进 plans/README.md 的"considered"区，不要在本 PR 扩大范围。
- PR 评审重点：API 层 `error_code` 是否与既有命名风格一致；Step 4 对照用例确保正常缓存行为未被破坏。
