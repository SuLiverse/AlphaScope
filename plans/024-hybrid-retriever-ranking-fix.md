# Plan 024: 修复混合检索——排序反向（distance 当相似度）与 BM25 腿的缺失方法调用

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 06182ca..HEAD -- backend/rag/hybrid_retriever.py backend/rag/retriever.py backend/storage/db.py tests/test_vector_store.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED（检索排序行为变化；先补表征测试再改）
- **Depends on**: none（022 与之同文件不同区域，无硬冲突）
- **Category**: bug
- **Planned at**: commit `06182ca`, 2026-08-01

## Why this matters

`backend/rag/hybrid_retriever.py` 是证据检索（证据链/研究记忆/MCP search_evidence）的设计主路径，当前有两个确定性缺陷：

1. **排序反向**：`_vector_search` 正确地把 `combined_score` 初始化为 `1.0 - distance`（Chroma 距离越小越相似），但 `_merge_results:176` 用 `r.vector_score * self.vector_weight` **覆盖**了它——`vector_score` 是原始距离（0=最相似），于是 `search()` 末尾 `sort(..., reverse=True)` 把**最不相似**的文档排最前。
2. **BM25 腿必死**：`_bm25_search:121` 调用 `db.get_connection()`，但 `backend/storage/db.py` 的 `Database` 单例只有 `transaction()` 上下文管理器（:60-67）和 `conn` property（:197），没有 `get_connection` —— 每次抛 `AttributeError` 被吞，关键词信号 100% 丢失。

修复后排序正确、BM25 腿恢复，证据检索才真正可用。

## Current state

- `backend/rag/hybrid_retriever.py`（全文 233 行，关键段）：
  - `:90-113` `_vector_search` — `vector_score=r.get("distance", 0)`、`combined_score=1.0 - min(r.get("distance", 1.0), 1.0)`
  - `:115-163` `_bm25_search` — `db = Database()` 后 `conn = db.get_connection()`（**问题点 2**）；SQL 查 `evidence_items` 表（`id, claim, source_name, evidence_type, data_date`），按关键词 LIKE 匹配 `claim`
  - `:165-193` `_merge_results` — 向量结果进 merged 时 `r.combined_score = r.vector_score * self.vector_weight`（**问题点 1**）；BM25 结果重叠时 `existing.combined_score += r.bm25_score * self.bm25_weight`
  - `:55-88` `search` — `merged.sort(key=lambda x: x.combined_score, reverse=True)` 后 `merged[:n_results]`
- `backend/storage/db.py:59-67` — 正确用法：
  ```python
  @contextmanager
  def transaction(self):
      with self._db_lock:
          yield self._conn
  ```
  `self._conn.row_factory = sqlite3.Row`（:49）。
- 参考：`backend/rag/retriever.py:47-58` 的 `search` 走 `self.store.query(collection, query, n_results, where)`，返回 dict 列表，含 `distance` 键（hybrid 的 `_vector_search` 依赖它）。
- 测试现状：`tests/test_vector_store.py` 存在（向量存储基础测试）；`tests/test_rag` 相关——执行前先 `Get-ChildItem tests` 确认有无 `test_hybrid_retriever*` 或 `test_rag*` 测试文件，若有读它。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 定向回归 | `python -m pytest tests/test_hybrid_retriever.py tests/test_vector_store.py -q` | 全过（含新增） |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全过 |
| Lint      | `python -m ruff check backend/rag/hybrid_retriever.py tests/test_hybrid_retriever.py` | exit 0 |

## Scope

**In scope**:
- `backend/rag/hybrid_retriever.py`（`_merge_results` 排序修正 + `_bm25_search` 的 DB 访问）
- `tests/test_hybrid_retriever.py`（新建）

**Out of scope**:
- `backend/rag/retriever.py`、`backend/storage/db.py`（只读参考）
- `backend/mcp_server.py`（plan 022 负责）
- `_time_decay_factor`、`trust_score` 加权、`_parse_timestamp` 等其余逻辑（只读）
- 向量存储的 collection 命名/索引逻辑

## Git workflow

- Branch: `advisor/024-hybrid-retriever-ranking-fix`
- 提交风格：`fix(rag): correct inverted hybrid ranking and wire BM25 to the locked DB connection`
- 不要 push、不要开 PR。

## Steps

### Step 1: 先写表征测试（锁定当前行为与目标行为）

新建 `tests/test_hybrid_retriever.py`，参照 `tests/test_vector_store.py` 的导入/结构风格。**关键：不碰真实 chroma**——用 monkeypatch/直接构造。

1. `test_merge_results_ranking_higher_similarity_first` — 构造两个 `RetrievalResult`（`vector_score` 分别为 0.1 和 0.9，即第 1 个更相似），直接调 `HybridRetriever._merge_results`（`bm25_results=[]` 以避免依赖 BM25 腿）→ 断言 `search` 结果顺序/`combined_score`：`combined_score` 与相似度同向（0.9 相似度的分数 > 0.1 相似度的分数）。**这个测试在修复前会 FAIL**（当前 0.1 的反而分高）。
2. `test_vector_search_combined_score_is_similarity` — patch `backend.rag.retriever.Retriever.search` 返回 `[{"text": "...", "metadata": {...}, "distance": 0.2}]` → `_vector_search` 返回的 `combined_score ≈ 0.8`（`1.0 - 0.2`）。
3. `test_bm25_search_uses_locked_connection` — patch `backend.storage.db.Database.transaction`（或直接在测试里 monkeypatch `_bm25_search` 内的 `Database()` 构造）→ 验证 `_bm25_search` 不再抛 `AttributeError`；理想做法：patch `Database.transaction` 返回假连接（实现 `execute(...).fetchall()` 返回构造行），断言返回 1 个 `RetrievalResult` 且 `bm25_score > 0`。

**Verify**: `python -m pytest tests/test_hybrid_retriever.py -q` → 测试 1 失败（排序反向的现状），2 通过，3 失败（BM25 现状）。**确认 1 和 3 失败后再进 Step 2**——如果 1 或 3 意外通过，说明代码与摘录不符，STOP 上报。

### Step 2: 修 `_merge_results` 排序

在 `_merge_results` 的向量分支（:176），把覆盖改为**保留相似度语义**：
```python
r.combined_score = (1.0 - min(r.vector_score, 1.0)) * self.vector_weight
```
（或等价：在构造 `RetrievalResult` 时已算好 `combined_score`，这里不再覆盖、只乘权重——二选一，保持 `search` 末尾 `sort(reverse=True)` 不变。）

注意 BM25 重叠分支（:186）`existing.combined_score += r.bm25_score * self.bm25_weight` 不动——它加的是分数，与向量分数同向。

**Verify**: `python -m pytest tests/test_hybrid_retriever.py -q` → 3 个测试全过（1 现在通过）。

### Step 3: 修 `_bm25_search` 的 DB 访问

把 `:120-121` 的
```python
db = Database()
conn = db.get_connection()
```
改为
```python
from backend.storage.db import Database
db = Database()
with db.transaction() as conn:
    ...
```
并把其后到 `return results` 的整段 SQL 查询/行处理**缩进进 `with` 块**。`conn.execute(...).fetchall()` 的用法不变（`sqlite3.Row` 行可用索引 `row[0]` 等，现状代码用 `row[1]`、`row[2]` 等索引访问，保持）。若 `transaction()` 内部有任何改变行工厂的可能——检查后确认 `row_factory` 已设（:49），无需额外处理。

**Verify**: `python -m pytest tests/test_hybrid_retriever.py -q` → 3 个测试全过（3 现在通过）。

### Step 4: 全量回归 + lint

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`python -m ruff check backend/rag/hybrid_retriever.py tests/test_hybrid_retriever.py` → exit 0。

## Test plan

- 新增 `tests/test_hybrid_retriever.py` 3 个测试（Step 1），其中 1 和 3 是**先红后绿**的表征测试。
- 模式参照：`tests/test_vector_store.py`（若内容相关）+ `tests/test_agent_tool_routing.py` 的 patch 风格。
- 不依赖真实 chroma/网络：所有数据源 mock。

## Done criteria

- [ ] `python -m pytest tests/test_hybrid_retriever.py -q` → 3 测试全过
- [ ] `python -m pytest tests/test_vector_store.py tests/test_rag* -q`（按实际存在的测试文件调整）→ 全过
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过
- [ ] `python -m ruff check backend/rag/hybrid_retriever.py tests/test_hybrid_retriever.py` → exit 0
- [ ] `grep -n "get_connection" backend/rag/hybrid_retriever.py` → 无匹配
- [ ] `git status` 只含 scope 内文件
- [ ] 已按 Git workflow 提交到 `advisor/024-hybrid-retriever-ranking-fix` 分支

## STOP conditions

- 测试 1 或 3 在 Step 1 意外通过（代码与摘录不符）。
- `RetrievalResult` 构造/`_vector_search` 的 `distance` 键约定与摘录不符（如 retriever.py 返回形状不同）。
- 需要修改 scope 外文件才能达成目标。
- `transaction()` 用法与摘录不一致（如它不 yield conn）。

## Maintenance notes

- 排序修正后，`search` 返回的 top-k 会与修复前完全不同——有真实索引数据的环境（chroma 已索引）评审时用一次真实查询对比相关性。
- BM25 腿恢复后 `evidence_items` 表的查询会真正执行：该表由 `backend/evidence_store.py` 维护，字段名若漂移会导致 BM25 静默失败（`except` 兜底仍在）——评审时确认表结构未变。
- plan 022 的 MCP 工具将开始返回真实结果，本修复是它的前置质量保障。
