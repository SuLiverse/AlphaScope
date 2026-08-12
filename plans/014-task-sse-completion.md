# Plan 014: 任务事件 SSE 流在终态后正常结束 + cancel_task 不再泄漏取消标记

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/api/tasks.py backend/task_queue.py tests/test_tasks.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（流消费者本就处理终态事件；提前结束流是增量行为）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

1. `GET /api/tasks/events` 的 SSE 生成器是 `while True` 死循环：指定 `task_id` 时任务到达终态（success/failed/cancelled）后，流**永不结束**——事件被 `terminal_sent` 去重，之后只剩每秒心跳，直到客户端断开。前端等不到"流完成"信号只能自行猜终态；永不断开的客户端把连接挂到天荒地老。且循环里每秒在事件循环上跑同步 SQLite 查询。
2. `TaskQueue.cancel_task` 在做存在性/终态检查**之前**就把 `task_id` 加进 `_cancelled` 集合；集合元素只在 `_run_task` 的 `finally` 里移除——对不存在或已终结任务的每次取消尝试都永久残留一个 ID，长跑服务上是个慢内存泄漏。

## Current state

- `backend/api/tasks.py:177-217` — `event_generator`：
  ```python
  async def event_generator():
      queue = TaskQueue()
      terminal_sent: set[str] = set()
      while True:
          if task_id:
              task = queue.get_task(task_id)      # 同步 SQLite, 事件循环上每秒一次
              if not task:
                  yield _sse_data({... "任务不存在" ...})
                  return
              tasks = [task]
          else:
              tasks = queue.list_tasks(limit=limit)
          emitted = False
          for task in tasks:
              ...
              if status in {"success", "failed", "cancelled"}:
                  if current_task_id in terminal_sent:
                      continue
                  terminal_sent.add(current_task_id)
              yield _sse_data(_task_to_event(task))
              emitted = True
          if not emitted:
              yield _sse_data(": heartbeat")
          await asyncio.sleep(1)
  ```
- `backend/task_queue.py:202-210`：
  ```python
  def cancel_task(self, task_id: str) -> bool:
      """取消任务"""
      with self._state_lock:
          self._cancelled.add(task_id)      # ← 在存在性/终态检查之前
      task = self.get_task(task_id)
      if not task:
          return False
      if task["status"] in ("success", "failed", "cancelled"):
          return False
  ```
  `_cancelled` 的唯一移除点：`_run_task` 的 `finally`（:149-152）。
- 测试：`tests/test_tasks.py` 已存在（先读，沿用其 TestClient/数据库 fixture 方式）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_tasks.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/api/tasks.py`（`event_generator` 终态结束 + 查询卸载）
- `backend/task_queue.py`（`cancel_task` 标记时机）
- `tests/test_tasks.py`（追加用例）

**Out of scope**:
- 不指定 `task_id` 的全局监听模式（天然无终点，保持长流——但其中的同步查询同样卸载）。
- 前端报告生成页的 SSE 消费逻辑（它对终态事件已有处理）。
- TaskQueue 的线程池/执行语义。

## Git workflow

- Branch: `advisor/014-task-sse-completion`
- 提交风格：`fix(api): end task-event SSE stream after terminal state and stop cancel-marker leak`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 提取可测的事件收集辅助

`backend/api/tasks.py`：把 `event_generator` 的单轮循环体抽成普通函数（便于脱离 SSE 单测）：

```python
def _collect_task_events(queue, task_id, limit, terminal_sent):
    """返回 (events, done)。done=True 表示指定任务已到终态, 流应结束。"""
```

逻辑：查询（`get_task`/`list_tasks`）→ 生成事件列表（含去重）；当 `task_id` 指定且该任务状态在终态集 → `done=True`。`event_generator` 改为：每轮 `events, done = await asyncio.to_thread(_collect_task_events, queue, task_id, limit, terminal_sent)`，逐个 yield；`done` 时 yield 后 `return`；无事件时 yield 心跳。"任务不存在"分支保持提前 return。

**Verify**: `ruff check backend/api/tasks.py` → exit 0。

### Step 2: cancel_task 标记时机

`backend/task_queue.py:202-210`：把 `self._cancelled.add(task_id)` 移到 `if not task` / 终态两个 guard **之后**（确认任务存在且非终态才标记）；两个提前 return 路径不再需要 discard（未 add）。

**Verify**: `python -m pytest tests/test_tasks.py -q` → 既有用例全过。

### Step 3: 测试

`tests/test_tasks.py` 追加：

a. **终态即完成**：构造终态任务（直接写库或 monkeypatch `get_task` 返回终态 dict，参照文件内既有构造方式），调 `_collect_task_events`，断言事件含终态状态且 `done is True`；非终态任务 `done is False`；
b. **去重保持**：同一终态任务第二轮调用不再产生事件（`terminal_sent` 语义不变）；
c. **取消标记不泄漏**：`TaskQueue().cancel_task("不存在的-id")` 返回 False 且 `_cancelled` 为空；对一个终态任务取消同样不残留（用 monkeypatch/临时库构造）。
（可选 d：经 TestClient 真连 SSE 读到终态事件后连接关闭——若文件内已有 SSE 测试先例则补上，没有则 a-c 已够，不强行搭流式测试架。）

**Verify**: `python -m pytest tests/test_tasks.py -q` → 全过，新增 ≥3 用例。

## Test plan

- 见 Step 3。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] 指定 `task_id` 的 SSE 在终态事件后 `return`（代码审查 + 单测 `done` 断言）
- [ ] `cancel_task` 对不存在/终态任务不污染 `_cancelled`（单测断言）
- [ ] `grep -n "queue.get_task\|queue.list_tasks" backend/api/tasks.py` 显示调用经 `to_thread`（或在被 `to_thread` 调用的辅助内）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 前端依赖"流永不结束"（例如断线重连逻辑假设服务端不主动关——`grep -rn "tasks/events" apps/web/src` 查看消费方；若其对 `done` 事件或流关闭有异常处理即兼容，有疑虑则记录并报告）。
- `_cancelled` 集合另有消费方依赖"先标记后检查"的时序（`grep -rn "_cancelled" backend/`）。

## Maintenance notes

- SSE 流结束后，前端如需持续观察应重新订阅（其现有重连/轮询逻辑即覆盖）。
- PR 评审重点：辅助函数 `terminal_sent` 的可变集合参数传递是否保持引用语义；心跳行为只在无事件时触发（不变）。
- 明确延期：任务进度细粒度回调（docstring 自述"当前任务队列没有细粒度进度回调"）是产品演进项，不在本计划。
