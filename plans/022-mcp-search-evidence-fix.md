# Plan 022: 修复 MCP search_evidence 工具——导入不存在的符号，永远报错

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 06182ca..HEAD -- backend/mcp_server.py backend/rag/hybrid_retriever.py tests/test_mcp_server.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none（可在 024 之前或之后独立落地；二者同文件 `hybrid_retriever.py` 不同区域，无硬冲突）
- **Category**: bug
- **Planned at**: commit `06182ca`, 2026-08-01

## Why this matters

`backend/mcp_server.py` 的 `search_evidence` 工具（Phase D MCP 面的旗舰研究工具，供外部 LLM 客户端/Claude Desktop 检索证据）导入 `backend.rag.hybrid_retriever.retrieve`，但该模块**只有** `search` 和 `get_hybrid_retriever` 两个公开函数（`grep` 全仓无 `retrieve`）。每次调用都抛 `ImportError`，被 `except Exception` 捕获后返回 `{"error": "证据检索失败: ..."}` —— 工具开箱即坏。本计划把工具接到真实入口并补一个可离线执行的回归测试。

## Current state

- `backend/mcp_server.py:117-148` — 工具实现（全部现状）：
  ```python
  @server.tool()
  def search_evidence(query: str, top_k: int = 5) -> str:
      """在证据库 / RAG 中检索研究证据 (财报/新闻/公告片段)。
      ...
      """
      try:
          from backend.rag.hybrid_retriever import retrieve     # ← ImportError: 符号不存在

          import json

          k = max(1, min(int(top_k), 20))
          hits = retrieve(query, top_k=k)                        # ← 这行从未执行到
          if not hits:
              return json.dumps({"query": query, "hits": []}, ensure_ascii=False)
          rows = [
              {
                  "content": str(getattr(h, "content", h.get("content", "")))[:300],
                  "source": str(getattr(h, "source", h.get("source", "")))[:80],
                  "score": float(getattr(h, "score", h.get("score", 0.0))),
              }
              for h in hits
          ]
          return json.dumps({"query": query, "hits": rows}, ensure_ascii=False)
      except Exception as e:
          return f'{{"error": "证据检索失败: {str(e)[:100]}"}}'
  ```
- `backend/rag/hybrid_retriever.py` — 真实入口与返回类型：
  - `get_hybrid_retriever() -> HybridRetriever`（模块级单例，:224-233）
  - `HybridRetriever.search(query, symbol="", n_results=10, doc_types=None, time_decay=True) -> List[RetrievalResult]`（:55-88）
  - `RetrievalResult` dataclass 字段（:22-38）：`text`、`source`、`doc_type`、`published_at`、`trust_score`、`vector_score`、`bm25_score`、`combined_score`、`metadata`
- 注意：`search` 的第一个参数是 `query`，结果条数参数是 **`n_results`**（不是 `top_k`，也不是 `k`）。
- 测试模式参考：`tests/test_mcp_server.py` —— 全部通过 `backend.mcp_server` 模块函数直接断言（如 `mcp_server.list_tool_names()`），文件头 `mcp_real = pytest.importorskip("mcp")`。`search_evidence` 是 `@server.tool()` 装饰的普通函数，**可以直接调用** `mcp_server.search_evidence(query, top_k)`。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 定向回归 | `python -m pytest tests/test_mcp_server.py tests/test_mcp_server_entry.py -q` | 全过（含新增） |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全过 |
| Lint      | `python -m ruff check backend/mcp_server.py tests/test_mcp_server.py` | exit 0 |

## Scope

**In scope**:
- `backend/mcp_server.py`（仅 `search_evidence` 函数体）
- `tests/test_mcp_server.py`（新增 2 个测试）

**Out of scope**:
- `backend/rag/hybrid_retriever.py` 的排序/BM25 缺陷（plan 024 负责；若你发现 `_merge_results` 分数逻辑有问题，**不要顺手修**，只在报告中注明）
- `backend/rag/retriever.py`、向量存储
- 其他 MCP 工具
- 任何运行 MCP 服务器的集成测试（本计划全部测试离线、mock 检索器）

## Git workflow

- Branch: `advisor/022-mcp-search-evidence-fix`
- 提交风格：`fix(mcp): wire search_evidence to real hybrid retriever entry point`
- 不要 push、不要开 PR。

## Steps

### Step 1: 替换导入与调用

在 `backend/mcp_server.py:128-134`，把 `from backend.rag.hybrid_retriever import retrieve` 改为：
```python
from backend.rag.hybrid_retriever import get_hybrid_retriever
```
把 `hits = retrieve(query, top_k=k)` 改为：
```python
hits = get_hybrid_retriever().search(query, n_results=k)
```
其余（`hits` 空判定、rows 映射、错误兜底）**原样保留**。

**Verify**: `python -c "from backend.mcp_server import search_evidence; r = search_evidence('茅台', 3); print(r[:200])"` → 打印 JSON（hits 可能为空数组，取决于本地 chroma 是否索引过数据；**不抛 ImportError 即通过**）。

### Step 2: 修 rows 映射的字段名（与 RetrievalResult 对齐）

现状 rows 映射用 `getattr(h, "content", h.get(...))`——`RetrievalResult` 没有 `content` 字段，是 `text`；score 应为 `combined_score`。改为：
```python
rows = [
    {
        "content": str(getattr(h, "text", h.get("text", "")))[:300],
        "source": str(getattr(h, "source", h.get("source", "")))[:80],
        "score": float(getattr(h, "combined_score", h.get("combined_score", 0.0))),
    }
    for h in hits
]
```
（保留 `getattr(..., h.get(...))` 的兼容写法是为了同时支持 dict 与 dataclass，风格与现状一致。）

**Verify**: `python -c "from backend.mcp_server import search_evidence; print(search_evidence('不存在', 2)[:120])"` → 无异常输出。

### Step 3: 补回归测试（`tests/test_mcp_server.py` 末尾追加）

用 `unittest.mock.patch` 把 `backend.rag.hybrid_retriever.get_hybrid_retriever` 替换为 fake，验证：

1. `test_search_evidence_uses_hybrid_retriever` — fake retriever 的 `search` 返回 2 个假 `RetrievalResult`（`text="<片段>", source="<来源>", combined_score=0.8`，直接构造 `backend.rag.hybrid_retriever.RetrievalResult`）。调用 `mcp_server.search_evidence("茅台", 2)` → 返回的 JSON 含 `"hits"`、第一个 hit 的 `content`/`source`/`score` 与 fake 数据一致，且 `search` 收到 `n_results=2`。
2. `test_search_evidence_error_path_returns_json_error` — patch `get_hybrid_retriever` 抛 `RuntimeError("boom")` → 返回字符串含 `"error"` 与 `"证据检索失败"`（验证错误兜底仍工作、不抛异常）。

参考现有测试风格：函数内 import、直接调用模块函数。

**Verify**: `python -m pytest tests/test_mcp_server.py -q` → 全过（含原有 6 个 + 新增 2 个）。

### Step 4: 全量回归 + lint

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`python -m ruff check backend/mcp_server.py tests/test_mcp_server.py` → exit 0。

## Test plan

- 新增 2 个测试（Step 3）：成功路径（mock 检索器、验证参数与返回映射）+ 错误兜底路径。
- 模式参照：`tests/test_mcp_server.py:26-66`（直接调用模块函数）+ `tests/test_agent_tool_routing.py` 的 `unittest.mock.patch` 用法。
- 全部离线：不启动 MCP server、不依赖 chroma 真实索引。

## Done criteria

- [ ] `python -m pytest tests/test_mcp_server.py -q` → 全过，新增 2 测试
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过
- [ ] `python -m ruff check backend/mcp_server.py tests/test_mcp_server.py` → exit 0
- [ ] `grep -n "from backend.rag.hybrid_retriever import retrieve" backend/mcp_server.py` → 无匹配
- [ ] `git status` 只含 scope 内文件
- [ ] 已按 Git workflow 提交到 `advisor/022-mcp-search-evidence-fix` 分支

## STOP conditions

- `search_evidence` 函数体与 "Current state" 摘录不一致（已漂移）。
- `RetrievalResult` 或 `search` 签名的实际代码与摘录不符。
- 需要修改 scope 外文件才能达成目标。

## Maintenance notes

- `search_evidence` 的 JSON 契约（`{"query", "hits": [{content, source, score}]}` 或 `{"error"}`）是 MCP 对外面，评审时确认未改变。
- plan 024 落地后，检索结果排序会修正（相似度升序问题）；本计划的映射逻辑不受影响。
- 若未来 `hybrid_retriever` 新增 `retrieve` 快捷函数，本计划保持 `get_hybrid_retriever().search(...)` 调用即可，无需迁移。
