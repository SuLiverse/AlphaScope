# Plan 031: 两条 OpenAI 客户端路径接入 pinned-DNS transport——消除 DNS rebinding TOCTOU

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 375285d..HEAD -- backend/ai_chat.py backend/rag/vector_store.py backend/models/provider_gateway.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `375285d`, 2026-08-30

## Why this matters

provider_gateway 为所有 LLM 流量建立了"连接时解析 → 地址分类 → 只连已验证 IP"的 pinned-DNS httpx transport（`_PinnedTargetNetworkBackend`），并把本地回环设为显式开关（`ALLOW_LOCAL_LLM_BASE_URL=1`）。但仓库里仍有**两处**直接 `OpenAI(api_key=..., base_url=..., timeout=...)` 构造、未注入该 transport：自定义供应商聊天/模型列表路径（用户 API Key 真实流经）与向量 embedding 路径。这两条路径上，构造时校验过的公网主机名可以在每次请求时被 DNS 重新解析到内网/回环地址（DNS rebinding TOCTOU），用户密钥随之发往攻击者控制的地址。上轮审计已把此项列入"下一批安全专项"。

## Current state

- `backend/models/provider_gateway.py:287-378` — pinned transport 机制（**不要修改**，只消费）：`_PinnedTargetNetworkBackend`（连接时解析、拒绝非全局地址、禁止跨源 host/port 变化）与 `create_ssrf_safe_http_client(base_url, ...)`（no-proxy、no-redirect httpx.Client）。
- 参照实现 `backend/models/provider_gateway.py:673-681` — `create_client` 的标准用法（含出错即关 http_client 的生命周期处理）：
  ```python
  http_client = create_ssrf_safe_http_client(base_url=..., timeout=...)
  try:
      client = OpenAI(api_key=..., base_url=..., http_client=http_client, timeout=...)
  except Exception:
      http_client.close()
      raise
  ```
- 绕过点 1 — `backend/ai_chat.py:197-204`：
  ```python
  def _create_custom_client(base_url: str, api_key: str) -> OpenAI:
      """创建临时 OpenAI-compatible 客户端，不缓存、不落盘，避免 Key 串用。"""
      base_url = normalize_base_url(base_url)
      if not base_url:
          raise RuntimeError("请先填写自定义 API Base URL")
      if not (api_key or "").strip():
          raise RuntimeError("请先填写自定义 API Key")
      return OpenAI(api_key=api_key.strip(), base_url=base_url, timeout=60.0)   # ← 无 http_client
  ```
  调用方：`fetch_model_list`（`:209`）与 `call_llm_custom`（`:226`，`send_message` 的实盘聊天路径）。
- 绕过点 2 — `backend/rag/vector_store.py:29-33`：
  ```python
  def _get_client(self):
      # 懒建: openai 是可选依赖, 首次调用时 import + 实例化, 之后复用同一连接池。
      if self._client is None:
          from openai import OpenAI

          self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30.0)   # ← 无 http_client
      return self._client
  ```
  `self.base_url` 来自存储的供应商设置；本地回环 LLM 的显式开关语义必须保留（`ALLOW_LOCAL_LLM_BASE_URL=1` 时允许 loopback——确认 `create_ssrf_safe_http_client` 的参数支持该形态，参照 gateway 内部两种模式的使用方式）。
- 仓库约定：中文注释；security 相关行为配离线单测（monkeypatch）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 定向测试 | `python -m pytest tests/test_pinned_transport_coverage.py tests/test_security_enhanced.py -q` | 全部通过 |
| 冒烟 | `python -c "import backend.ai_chat, backend.rag.vector_store"` | exit 0 |
| 全量离线 | `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` | 与基线一致 |

## Scope

**In scope**:
- `backend/ai_chat.py`
- `backend/rag/vector_store.py`
- `tests/test_pinned_transport_coverage.py`（新建）

**Out of scope**:
- `backend/models/provider_gateway.py` — transport 实现是既定机制，只 import 消费。
- `backend/api/settings.py`、`backend/settings_store.py` — 已是安全路径（参照实现），不要顺手重构。
- openai 客户端的超时/重试参数调整。

## Git workflow

- Branch: `advisor/031-openai-pinned-transport`
- Commit style: conventional commits（中文正文）
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: ai_chat 自定义客户端接入

`backend/ai_chat.py:197-204`：`_create_custom_client` 内先 `from backend.models.provider_gateway import create_ssrf_safe_http_client`，按 `create_client` 的参照模式构造（`http_client = create_ssrf_safe_http_client(...)` → try/except close-and-raise → `OpenAI(..., http_client=http_client, timeout=60.0)`）。函数语义仍是"临时、不缓存"；调用方 `fetch_model_list` / `call_llm_custom` 增补 `try/finally` 确保 `client.close()`（openai SDK 的 close 会连带关闭注入的 http_client——先在 REPL 确认所装 openai 版本行为，若不连带则 finally 中显式关闭 `client._client`，以实际版本行为为准并加注释）。

**Verify**: `python -c "import backend.ai_chat"` → exit 0；`grep -n "http_client" backend/ai_chat.py` → ≥1 处。

### Step 2: embedding 客户端接入

`backend/rag/vector_store.py:29-33`：`_get_client` 懒建分支同样注入 `create_ssrf_safe_http_client(base_url=self.base_url, timeout=30.0)`。注意 `_OpenAIEmbeddingFunction` 会缓存 `self._client`——签名/配置变化触发重建时（该生命周期属另一候选计划，本计划不动它），必须先关闭旧 `http_client` 再置空，避免连接泄漏：在 `self._client = None` 的所有赋值点前补关闭逻辑（`grep -n "_client" backend/rag/vector_store.py` 找全）。

**Verify**: `python -c "import backend.rag.vector_store"` → exit 0。

### Step 3: 回归测试

`tests/test_pinned_transport_coverage.py`（新建）：
1. monkeypatch `backend.ai_chat.create_ssrf_safe_http_client` → 调 `_create_custom_client("https://api.example.com", "k")` → 断言被调用且 `OpenAI` 收到 `http_client`（对 openai 构造打桩记录 kwargs）；
2. 同法覆盖 `vector_store._OpenAIEmbeddingFunction._get_client`；
3. 防回归哨兵：遍历 `backend/` 源码文本，断言除 `provider_gateway.py`、`api/settings.py`、`settings_store.py` 白名单外，`grep "OpenAI("` 出现的行都包含 `http_client=`（把白名单写成显式列表并注释原因）。

**Verify**: `python -m pytest tests/test_pinned_transport_coverage.py -q` → 全过。

## Test plan

- 新测试见 Step 3；哨兵用例是本计划的长期价值（防止第三条路径再次绕开）。
- 离线约束：不真连 LLM；openai 构造全部打桩。

## Done criteria

- [ ] `grep -rn "OpenAI(" backend/ --include=*.py` 的非白名单行全部带 `http_client=`
- [ ] `python -m pytest tests/test_pinned_transport_coverage.py -q` 全过
- [ ] `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 与基线一致
- [ ] 无 Scope 外文件改动（`git status`）

## STOP conditions

- `create_ssrf_safe_http_client` 的参数形态与参照用法对不上（如不接受 `timeout`）——先读 `provider_gateway.py:287-378` 实际签名适配；若能力缺失（如无 loopback 开关透传），停下报告而不是自行改 gateway。
- 本地回环 LLM（`ALLOW_LOCAL_LLM_BASE_URL=1`）路径在注入 pinned transport 后被错误拒绝——此为功能回归，停下报告。
- 所装 openai 版本对 `http_client` 的生命周期行为与假设不符且无法在两行内确认。

## Maintenance notes

- Step 3 的哨兵测试白名单是活文档：新增合法裸构造必须同步更新白名单并写明原因，评审必查。
- embedding 客户端配置变更不重建 collection 的问题（embedding 签名缺 api_key、换模型不迁移向量空间）是另一个 M 级候选计划，本计划刻意不碰。
- 评审重点：http_client 关闭路径是否覆盖所有异常分支（连接失败、构造失败、重建）。
