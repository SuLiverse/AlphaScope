# Plan 010: 修复聊天端点每请求泄漏一个 SQLite 连接（共享 ConversationStore）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/api/main.py backend/ai_assistant/orchestrator.py backend/ai_assistant/conversation_store.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW-MED（共享存储后并发语义变化：从"每请求独立连接"变为"共享连接 + 共享锁"——`Database` 单例本就是为共享设计的）
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`/api/chat/stream` 与 `/api/chat` 每个请求都 `ChatOrchestrator()` 新建实例，其构造函数创建**无参** `ConversationStore()`——走"独立连接"分支：自开 `sqlite3.connect`（`_own_conn=True`，**从不关闭**）且每次执行 `_ensure_ai_tables` DDL。每条聊天消息 = 泄漏一个 SQLite/WAL 句柄 + 一次 DDL 往返；长时运行的桌面服务文件描述符单调增长。修复思路：让 `ConversationStore` 绑定 `Database` 单例（共享连接 + 共享 `_db_lock`，这正是它的 `db` 参数的设计用途），`ChatOrchestrator` 仍按请求构造以保住会话缓存语义不变。

## Current state

- `backend/api/main.py:574-576`（stream）与 `:626-628`（非 stream）：
  ```python
  orch = ChatOrchestrator()
  ```
- `backend/ai_assistant/orchestrator.py:370-372`：
  ```python
  def __init__(self, store: Optional[ConversationStore] = None):
      self._store = store or ConversationStore()
      self._chat_sessions = {}  # conversation_id -> ChatSession (for FREE mode)
  ```
  ——构造函数**接受** `store` 参数，调用方没传。
- `backend/ai_assistant/conversation_store.py:59-74`：
  ```python
  def __init__(self, db=None):
      if db is not None:
          self._conn = db.conn
          self._db_lock = db._db_lock
          self._own_conn = False
      else:
          ...
          self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
          ...
          self._own_conn = True
      _ensure_ai_tables(self._conn)   # 每次构造都跑 DDL
  ```
- `Database` 单例：`backend/storage/db.py`（`grep -n "class Database" backend/storage/db.py` 确认单例实现与 `.conn`/`._db_lock` 属性）。`backend/task_queue.py:156` 等处 `Database()` 的用法是参照。
- 聊天端点是同步 `def`（`backend/api/main.py:569` `def chat_stream(...)`），FastAPI 自动放线程池执行——共享连接由 `_db_lock` 串行化，安全。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_tasks.py tests/test_task_router.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/api/main.py`（两个聊天端点构造方式 + 模块级共享 store 的懒加载辅助）
- `tests/test_chat_orchestrator_store.py`（新建）

**Out of scope**:
- `backend/ai_assistant/orchestrator.py` / `conversation_store.py` 本体——它们的 `store`/`db` 参数已是正确设计，只是调用方没用。
- `ChatOrchestrator` 整体单例化（顺带保住 `_chat_sessions` 暖缓存）——需要 `_chat_sessions` 的并发审计，延期。
- SSE 假流式问题（独立发现，未立项）。

## Git workflow

- Branch: `advisor/010-chat-store-shared`
- 提交风格：`fix(api): share ConversationStore across chat requests to stop sqlite connection leak`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 模块级共享 ConversationStore（懒加载）

`backend/api/main.py`（在聊天端点所在的作用域内）新增：

```python
_shared_conversation_store = None
_shared_store_lock = threading.Lock()

def _get_conversation_store():
    global _shared_conversation_store
    if _shared_conversation_store is None:
        with _shared_store_lock:
            if _shared_conversation_store is None:
                from backend.ai_assistant.conversation_store import ConversationStore
                from backend.storage.db import Database
                _shared_conversation_store = ConversationStore(db=Database())
    return _shared_conversation_store
```

（`threading` 若未导入则补导入；放置位置参照该作用域内其他模块级单例的写法。）确认 `Database` 是单例（读 `backend/storage/db.py` 的类实现——若 `Database()` 每次新建而非单例，是 STOP 条件）。

**Verify**: `ruff check backend/api/main.py` → exit 0。

### Step 2: 两个端点改用共享 store

:576 与 :628 两处 `orch = ChatOrchestrator()` → `orch = ChatOrchestrator(store=_get_conversation_store())`。

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes -k "chat or sse"` → 相关用例全过（若无命中则跑全量回归）。

### Step 3: 回归测试

新建 `tests/test_chat_orchestrator_store.py`：

- 调 `_get_conversation_store()` 两次，断言同一对象；
- 断言 `store._own_conn is False`（关键：不再自开连接）；
- 用两个 `ChatOrchestrator(store=...)` 实例断言共享同一 `store._conn`；
- （结构参照 `tests/test_tasks.py` 中对 `Database` 单例的既有处理方式；注意测试隔离——`_shared_conversation_store` 是模块态，测试间如需重置直接置 `None`，加注释说明。）

**Verify**: `python -m pytest tests/test_chat_orchestrator_store.py -q` → 3 用例全过。

## Test plan

- 见 Step 3。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "ChatOrchestrator()" backend/api/main.py` 无匹配（两处都传了 store）
- [ ] 新测试断言 `_own_conn is False` 通过
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `Database()` 不是单例（每次新建连接）——那么共享 store 方案前提不成立，报告后改走"每请求构造但用完显式关闭连接"的备选。
- `ConversationStore` 的其他调用方依赖"无参 = 独立连接"行为做隔离（`grep -rn "ConversationStore(" backend/ tests/` 排查；本计划只改 api/main.py 两处，其他调用方不动）。
- 共享后出现 SQLite 线程错误（`check_same_thread` 类）——`Database` 单例连接若未以 `check_same_thread=False` 创建，报告并停止（不自行改 `Database` 构造）。

## Maintenance notes

- 后续若要 `ChatOrchestrator` 全单例（消除每请求重建会话历史的 O(history) 开销），需先审计 `_chat_sessions` 与 `ChatSession` 的线程安全，再加锁——本计划刻意未做。
- PR 评审重点：双重检查锁的写法；`_ensure_ai_tables` 现在进程内只跑一次（首次），后续请求省掉 DDL——确认其幂等性本来就成立（`CREATE TABLE IF NOT EXISTS` 类）。
- 关联：`plans/011` 处理同进程内另一类未关闭资源（LLM 客户端连接池）。
