# Plan 028: 修复 RAG 检索与摄取链路——agent 证据工具必然报错、symbol 过滤静默失效、上传双重索引、分块器丢尾损数

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 375285d..HEAD -- backend/rag/retriever.py backend/rag/document_pipeline.py backend/rag/chunker.py backend/runtime/tool_router.py backend/pipeline.py tests/test_knowledge.py tests/test_hybrid_retriever.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M（四个同子系统小修复，合计约一天）
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `375285d`, 2026-08-30

## Why this matters

RAG 是 agent 证据链与知识库检索的底座，当前有四个互相独立的缺陷，共同效果是「agent 拿不到证据、拿到了也是错的/重复的」，且全程无报错：

1. agent 的 `evidence_search` 工具调用 `Retriever.search` 时漏传必填参数，**每次调用必抛 `TypeError`**，工具开箱即坏。
2. 向量库元数据键名不一致：检索过滤用 `symbol`，但 news/reports 索引写入的是 `symbols`——**带 symbol 的证据检索对 4 个集合中的 3 个永远返回空**（静默，仅 DEBUG 日志）。
3. 知识库上传把同一文档**索引进 ChromaDB 两次**（两个不同 doc_id），搜索结果每条 chunk 重复出现，浪费一倍向量存储与 embedding 费用。
4. `TextChunker` 把短文档整篇丢弃、把不足 `min_chunk_size` 的尾段丢弃、并在切分超长段落时把句读统一替换成 `。`——**把 `12.50` 这类小数价格破坏成 `12。50`**。

## Current state

- `backend/runtime/tool_router.py:288-296` — agent 证据工具（现状全文）：
  ```python
  def _tool_evidence_search(self, query: str = "", symbol: str = "", **kwargs) -> Dict[str, Any]:
      """证据检索工具（RAG）"""
      try:
          from backend.rag.retriever import Retriever

          retriever = Retriever()
          results = retriever.search(query, symbol=symbol, n_results=5)   # ← TypeError
          return {"query": query, "results": results}
      except Exception as e:
          return {"query": query, "error": str(e)}
  ```
- `backend/rag/retriever.py:47-57` — 签名与过滤（现状）：
  ```python
  def search(
      self,
      collection: str,          # ← 必填位置参数，tool_router 漏传
      query: str,
      n_results: int = 5,
      symbol: Optional[str] = None,
  ) -> list[dict]:
      """检索相似文档"""
      where = None
      if symbol:
          where = {"symbol": symbol}     # ← 过滤键是 "symbol"
      return self.store.query(collection, query, n_results, where)
  ```
- `backend/rag/retriever.py:71, 87, 103` — 索引写入的元数据键：`index_news` 与 `index_reports` 写 `"symbols": ",".join(item.get("symbols", []))`，只有 `index_announcements` 写 `"symbol": item.get("symbol", "")`。
- `backend/pipeline.py:459-478` — `DataPipeline.search_evidence` 对 4 个集合统一套 symbol 过滤（`news_chunks` / `report_chunks` / `announcement_chunks` / `user_documents`），异常只记 DEBUG。这是上述过滤失效的影响面。
- `backend/rag/document_pipeline.py` — 双重索引链路：`process_file()` 生成 md5 `doc_id`（`:66-68`），`self._processed[doc_id] = doc`（`:78`）后调用 `self._index_document(doc)`（`:83`）；随后 `process_and_persist()` 把 `doc.doc_id` 改写为 SQLite 行 id（`:287`）并**再次** `self._index_document(doc)`（`:293`）。`_processed` 仍以旧 md5 为键，`get_document(saved_id)`（`:298-299`）因此 miss。
- `backend/rag/chunker.py:42-43` — 入口丢弃短文档：
  ```python
  if not text or len(text.strip()) < self.min_chunk_size:
      return []
  ```
- `backend/rag/chunker.py:66-67` — 尾段只在 `>= min_chunk_size` 时输出：
  ```python
  if current_text.strip() and len(current_text.strip()) >= self.min_chunk_size:
      chunks.append(...)
  ```
- `backend/rag/chunker.py:78-89` — `_split_long_text` 丢弃分隔符后统一用 `"。"` 重接（小数点破坏的根源）：
  ```python
  sentences = re.split(r"[。！？.!?\n]", text)      # ← 分隔符被丢弃
  ...
  current += sent + "。"                            # ← 每段后面补 "。"
  ```
- 已由审计在内存中复现：685 字单段切分后出现 `12。50元`；`chunk_text('很短的文档。') == []`；带短尾段的两段文档尾段丢失。
- 仓库约定：后端中文注释、模块级 docstring、`logger = logging.getLogger(__name__)`；测试为离线 pytest（`-m "not network"`）。参考已修好的同类实现：`backend/rag/external_corpus.py` 的 `_chunk_text`（正确保留分隔符、正确处理短尾），只作对照，不要引入它。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 定向测试 | `python -m pytest tests/test_rag_retriever_chain.py tests/test_rag_chunker.py tests/test_knowledge.py -q` | 全部通过 |
| 全量离线 | `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` | 与基线一致（2147 passed / 5 skipped 量级），新增用例全过 |
| 语法检查 | `python -c "import backend.rag.retriever, backend.rag.chunker, backend.rag.document_pipeline, backend.runtime.tool_router"` | exit 0 |

## Scope

**In scope**（唯一允许修改的文件）:
- `backend/rag/retriever.py`
- `backend/rag/document_pipeline.py`
- `backend/rag/chunker.py`
- `backend/runtime/tool_router.py`
- `tests/test_rag_retriever_chain.py`（新建）
- `tests/test_rag_chunker.py`（新建）

**Out of scope**（不要动，尽管看起来相关）:
- `backend/pipeline.py` — 它的调用方式 `search(collection=col, query=...)` 在本计划改动后必须保持原样可用；不要改它的过滤逻辑。
- `backend/rag/external_corpus.py` 与 `document_pipeline._chunk_content` 的三套分块实现合并 —— 结构性重构，另行立项。
- 已入库的旧 Chroma chunk 的 reindex（元数据修复只对新写入生效，旧数据迁移记入 Maintenance notes）。
- ChromaDB / embedding 生命周期问题（`vector_store.py`）—— 另有候选计划。

## Git workflow

- Branch: `advisor/028-rag-retrieval-chain-fixes`（从当前 HEAD 切出；若 `main` 已前移则以 `main` 为基）
- Commit style: conventional commits，中文正文，如 `fix(rag): evidence_search 漏传 collection 参数导致 TypeError`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `Retriever.search` 兼容无 collection 调用

在 `backend/rag/retriever.py` 中把 `collection` 改为带默认值的关键字参数：`def search(self, query: str, n_results: int = 5, symbol: Optional[str] = None, collection: Optional[str] = None)`。当 `collection` 为 `None` 时，遍历默认集合 `["news_chunks", "report_chunks", "announcement_chunks", "user_documents"]`（与 `backend/pipeline.py:459` 的列表字面量保持一致，抽成模块级常量 `DEFAULT_COLLECTIONS` 放在 retriever.py 顶部），把各集合结果合并后按 `distance` 升序排序并截取 `n_results`；单集合行为不变。注意 `pipeline.py:466-471` 是关键字传参（`collection=col, query=query`），改签名后无需改它，但必须实际验证。

**Verify**: `python -c "import backend.pipeline"` → exit 0；`grep -n "search(" backend/pipeline.py | grep retriever` 确认调用点未被改动。

### Step 2: 修复 `tool_router` 的调用

`backend/runtime/tool_router.py:292` 改为 `results = retriever.search(query, symbol=symbol or None, n_results=5)`（依赖 Step 1 的默认集合行为；`symbol=""` 时传 `None` 以保持"不过滤"语义）。

**Verify**: `python -c "from backend.runtime.tool_router import ToolRouter; r=ToolRouter(); print(r._tool_evidence_search(query='测试')['results'] is not None or 'error' not in r._tool_evidence_history)"` 不可行（无数据时结果可为空列表）——改用 Step 6 的单测验证不抛 `TypeError`。

### Step 3: 统一元数据键，新写入的 news/reports 同时带 `symbol`

`backend/rag/retriever.py` 的 `index_news`（`:71` 附近）与 `index_reports`（`:87` 附近）在写 `"symbols"` 的同一 metadata dict 里**追加** `"symbol"` 键：取 `item.get("symbol", "")`（news 侧若条目只有多 symbol 列表，则写列表第一个非空值，保持与 `index_announcements` 单值语义一致）。**保留** `"symbols"` 键不动（向后兼容，别处可能读取）。

**Verify**: `grep -n '"symbol"' backend/rag/retriever.py` → `index_news`/`index_reports`/`index_announcements` 三处均出现。

### Step 4: 消除上传双重索引

`backend/rag/document_pipeline.py`：删除 `process_file()` 中的 `self._index_document(doc)`（`:83` 附近）——索引只在 `process_and_persist()`（`:293`）发生一次。同时把 `process_and_persist` 中改写 `doc.doc_id = saved["id"]` 之后补一行 `self._processed[doc.doc_id] = doc`，使 `get_document(saved_id)` 命中；旧 md5 键保留亦可（内存 map，无碍），但在其 docstring 中说明键为最终 id。先 `grep -rn "process_file(" backend/ tests/` 确认 `process_file` 是否存在"只处理不持久化"的独立调用方；若有，给 `process_file` 加参数 `index: bool = False` 并让该调用方显式传 `index=True`——以 grep 结果为准，两种路径都要在测试中覆盖。

**Verify**: `python -m pytest tests/test_knowledge.py -q` → 全过（若该文件 mock 了 Chroma，需确认断言仍成立）。

### Step 5: 修复 TextChunker 三处

`backend/rag/chunker.py`：
1. 短文档：入口处 `if not text: return []` 放行短文本，改为在末尾统一兜底——若 `chunks` 为空且 `text.strip()` 非空，输出单条 `min_chunk_size` 之下的整文 chunk。
2. 短尾：`chunk_text` 末段 flush 条件从 `>= self.min_chunk_size` 改为非空即收；若尾段长度 < `min_chunk_size` 且 `chunks` 非空，则**并入最后一个 chunk**（加 `"\n"` 连接），而不是丢弃。
3. 分隔符：`_split_long_text` 用捕获组切分并成对重接：`parts = re.split(r"([。！？.!?\n])", text)`，遍历时把 `parts[i] + (parts[i+1] if i+1 < len(parts) else "")` 作为一个句子累加（句读用原字符，不再统一补 `"。"`）。

**Verify**: `python -c "from backend.rag.chunker import TextChunker; c=TextChunker(); para='支撑位在12.50元附近，随后回落到11.20元。'+'填充。'*120; ch=c.chunk_text(para); assert not any('12。50' in t['text'] or '11。20' in t['text'] for t in ch), 'decimal corrupted'; assert c.chunk_text('很短的文档。'), 'short doc dropped'; print('OK')"` → 输出 `OK`。

### Step 6: 回归测试

- `tests/test_rag_retriever_chain.py`（新建）：参照 `tests/test_hybrid_retriever.py` 的 fake store 模式。用例：(a) `_tool_evidence_search` 不抛 `TypeError`、返回 dict 且无 `error` 键（monkeypatch `Retriever` 为 stub）；(b) `Retriever.search(query=...)` 无 collection 时遍历 4 集合并按 distance 合并排序；(c) `index_news` 写入的 metadata 同时含 `symbol` 与 `symbols` 键。
- `tests/test_rag_chunker.py`（新建）：用例：小数价格不被破坏（Step 5 的探针断言）、短文档产单 chunk、短尾并入前块、`min_chunk_size` 语义变化处加注释。

**Verify**: `python -m pytest tests/test_rag_retriever_chain.py tests/test_rag_chunker.py -q` → 全过。

## Test plan

- 新测试文件与用例见 Step 6；结构性范式参照 `tests/test_hybrid_retriever.py`（fake store + 不 mock 被测方法本身）。
- 回归确认：`python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 全过，无新增 skip。

## Done criteria

- [ ] `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 全过
- [ ] `python -c "from backend.rag.chunker import TextChunker; ..."`（Step 5 探针）输出 `OK`
- [ ] `grep -n '"symbols"' backend/rag/retriever.py` 仍有 ≥2 处，且 `'"symbol"'` 在三个 index_* 中都出现
- [ ] `grep -n "_index_document" backend/rag/document_pipeline.py` 只剩 `process_and_persist` 一处调用
- [ ] 无 Scope 外文件被改动（`git status`）
- [ ] `plans/README.md` 状态行由 reviewer 更新

## STOP conditions

- `git diff 375285d..HEAD` 显示 in-scope 文件已变动且摘录对不上。
- Step 4 发现 `process_file` 有除 `process_and_persist` 外的调用方且其语义与 `index` 参数方案冲突。
- 修复 `Retriever.search` 签名导致 `pipeline.py` 或 `hybrid_retriever.py` 出现测试失败且原因不是本计划的断言更新。
- ChromaDB 在测试环境不可用导致行为断言无法离线验证（已有代码用 try/except 降级——若无法在离线条件下测 Step 3/4，改为对 fake store 断言，不要引入网络或真实 Chroma 依赖）。

## Maintenance notes

- 旧 chunk 迁移：Step 3 只修复新写入；存量 `news_chunks`/`report_chunks` 的 metadata 没有 `symbol` 键。后续应提供一次性 reindex 脚本（或在 `index_news`/`index_reports` 层做 dual-key 读），评审时关注。
- 三套分块实现（`chunker.py` / `document_pipeline._chunk_content` / `external_corpus._chunk_text`）行为漂移是本类 bug 的土壤，合并到 `external_corpus` 语义是既定方向，未列入本计划。
- 评审重点：`Retriever.search` 签名变更的全部调用点（`grep -rn "\.search(" backend/ apps/ frontend/ --include=*.py`）；`document_pipeline` 的 `_processed` 键语义。
