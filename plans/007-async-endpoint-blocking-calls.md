# Plan 007: 把 async 端点里的同步阻塞调用移出事件循环

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/api/dragon_tiger.py backend/api/settings.py backend/api/prices.py backend/api/news.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（纯并发方式变更，无逻辑变化）
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

FastAPI 的 `async def` 端点在事件循环上执行；其中的同步阻塞调用（akshare HTTP、OpenAI SDK、SQLite）会冻结**整个进程**的全部并发请求（SSE 流、行情轮询、健康检查）。两个最重站点：龙虎榜端点内联 akshare 抓取（秒级），Provider 连接测试内联 `client.models.list()`（15 秒超时——用户每点一次"测试连接"，全站卡 15 秒）。代码库已有正确惯例（`asyncio.to_thread`），这些是漏网点。

## Current state

- `backend/api/dragon_tiger.py:20-27` — `async def get_dragon_tiger(...)` 内同步调用：
  ```python
  data = DragonTigerProvider().get_dragon_tiger({"symbol": symbol, "days": days})
  ```
  （Provider 走 akshare HTTP，多秒。）
- `backend/api/settings.py:240-246` — `async def test_provider_connection(provider_id)` 内同步调用 `_test(provider_id)`；`backend/settings_store.py:540-550` 显示该函数构建 OpenAI 客户端并同步 `client.models.list()`（timeout=15.0）。**同文件已有正确先例**——用 `grep -n "asyncio.to_thread" backend/api/settings.py` 找到它（probe 类端点），照抄其写法。
- `backend/api/prices.py:158-165` 与 `:185-192` — `async def get_prices` 内两处同步 SQLite `_get(...)`（毫秒级但仍在循环上）。
- `backend/api/news.py:56,66` — `async def list_news` / `list_announcements` 内同步 `news_store` 的 `_list(...)`（:92 附近 announcements 分支还有第二处调用）。
- 正确惯例参照：`backend/api/prices.py:96` 一带已有 `asyncio.to_thread` 用法（`grep -n "asyncio.to_thread" backend/api/` 可看到全部既有先例）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_settings.py tests/test_news_store.py tests/test_news_stale_cache.py tests/test_quant_api.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**（仅下列文件中的指定调用点）:
- `backend/api/dragon_tiger.py`（:26 provider 调用）
- `backend/api/settings.py`（:245 `_test(provider_id)` 一处；同函数其余行不动）
- `backend/api/prices.py`（:159 与 :186 两处 `_get(...)`）
- `backend/api/news.py`（`list_news` 与 `list_announcements` 内的 `_list(...)` 调用）
- `tests/test_settings.py`（追加 1 个卸载行为用例）

**Out of scope**:
- 把这些端点整体改写为同步 `def`（可行替代方案，但逐个 `to_thread` 包裹 diff 更小、更符合本文件已有惯例——保持统一）。
- 其他文件中毫秒级的同步调用（如各 settings 读库小调用）——收益不抵 churn，不动。
- `news.py` 的抓取管道并行化（fetch 串行 + 逐行 commit）——那是独立的 M 级性能项，不在本计划。

## Git workflow

- Branch: `advisor/007-async-endpoint-offload`
- 提交风格：`fix(api): offload blocking provider/store calls from async endpoints`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 龙虎榜端点卸载

`backend/api/dragon_tiger.py`：文件顶部确保 `import asyncio`；:26 改为
```python
data = await asyncio.to_thread(DragonTigerProvider().get_dragon_tiger, {"symbol": symbol, "days": days})
```

**Verify**: `ruff check backend/api/dragon_tiger.py` → exit 0。

### Step 2: Provider 连接测试卸载

`backend/api/settings.py:245`：`result = _test(provider_id)` → `result = await asyncio.to_thread(_test, provider_id)`（确保 `asyncio` 已导入——参照同文件 probe 端点的导入与用法）。

**Verify**: `python -m pytest tests/test_settings.py -q` → 全过。

### Step 3: prices/news 的 SQLite 读卸载

`backend/api/prices.py` 两处 `_get(...)` 与 `backend/api/news.py` 的 `_list(...)` 调用，逐处包 `await asyncio.to_thread(...)`。注意保持参数传递形式（`_get` 全关键字参数：`await asyncio.to_thread(_get, symbol=..., frequency=..., ...)`）。

**Verify**: `python -m pytest tests/test_news_store.py tests/test_news_stale_cache.py tests/test_quant_api.py -q` → 全过。

### Step 4: 卸载行为回归测试

`tests/test_settings.py` 追加：monkeypatch `backend.settings_store.test_connection` 为一个记录"是否在主事件循环线程之外被执行"的假实现（`threading.get_ident()` 对比），通过该文件既有的 API 调用方式（TestClient/httpx，参照文件内既有用例）调 `POST /api/settings/providers/{id}/test`，断言假实现运行在与请求协程不同的线程。实现上若既有测试全用同步 TestClient，允许简化为：monkeypatch 后断言端点返回结构不变 + `asyncio.to_thread` 被调用（用 `unittest.mock.patch` 包一层 spy 亦可，选与文件内风格一致的）。

**Verify**: `python -m pytest tests/test_settings.py -q` → 全过，新增 1 用例。

## Test plan

- Step 4 的一个新用例；其余靠既有回归（上述目标测试文件）。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "get_dragon_tiger({" backend/api/dragon_tiger.py` 所在行含 `to_thread`
- [ ] `grep -n "_test(provider_id)" backend/api/settings.py` 所在行含 `to_thread`
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 目标调用点已被改写（异步化/删除），"Current state" 摘录对不上。
- `DragonTigerProvider().get_dragon_tiger` 的签名不是位置参数字典形式（先 `grep -n "def get_dragon_tiger" backend/providers/dragontiger_provider.py` 核实，按实际签名调整 `to_thread` 传参）。
- 卸载后某既有测试失败两次仍无法解释（可能隐含对调用时序的依赖）。

## Maintenance notes

- 评审 checklist：本仓库新增 `async def` 端点时，函数体内不得出现裸的 `requests.*`/akshare/SQLite 直连调用；要么 `asyncio.to_thread`，要么定义为同步 `def`（FastAPI 自动进线程池）。
- PR 评审重点：`to_thread` 的关键字传参是否完整（漏参会被 `TypeError` 立即暴露，测试中应覆盖到每个改动端点至少一次调用）。
- 明确延期：新闻抓取管道并行化、SSE 真流式（advisor 报告 PERF-05/PERF-06，未立项）。
