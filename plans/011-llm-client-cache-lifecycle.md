# Plan 011: 自定义 key/base_url 的 LLM 客户端纳入缓存生命周期，不再每调用泄漏连接池

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/models/provider_gateway.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M（小 M：改动集中在一个函数 + 缓存清理逻辑）
- **Risk**: LOW（缓存键复合化是增量行为；不引入 key 混淆——键内含 key 的哈希）
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`get_client(vendor, api_key, base_url)` 一旦传入自定义 `api_key`/`base_url` 就绕过缓存直接 `create_client`（新建 `OpenAI` + 新 httpx 连接池），而调用链（`_call_with` 及专家团/critic/chairman 各路径）**从不关闭**这些客户端。用户配置了按专家/按功能的自定义 key 后，每轮深度分析泄漏 5+ 个 TCP/TLS 连接池，长跑会话累积文件描述符与 TLS 会话。修复：把缓存键从单一 `vendor` 扩展为 `(vendor, base_url, key_hash)` 复合键，让自定义客户端也进入缓存复用，并随 `clear_client_cache` 统一关闭。缓存键**绝不包含明文 key**（用 SHA-256 截断哈希），避免日志/调试泄露。

## Current state

- `backend/models/provider_gateway.py:688-702`：
  ```python
  def get_client(vendor: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> OpenAI:
      """
      获取客户端。
      如果提供了 api_key/base_url，则创建独立客户端（不走缓存，避免 Key/URL 混淆）。
      """
      if api_key or base_url:
          return create_client(vendor, api_key, base_url)

      cache_key = vendor
      with _client_cache_lock:
          if cache_key in _client_cache:
              return _client_cache[cache_key]
          client = create_client(vendor)
          _client_cache[cache_key] = client
          return client
  ```
- `backend/models/provider_gateway.py:802` — `_call_with` 中 `client = get_client(vendor, api_key, base_url)`，其后没有任何 close。
- `backend/models/provider_gateway.py:665-681` — `create_client`：构造 `OpenAI(api_key, base_url, timeout, http_client=create_ssrf_safe_http_client(...))`（失败时关闭 http_client，正确先例）。
- `clear_client_cache`：`grep -n "def clear_client_cache" backend/models/provider_gateway.py` 定位——**先确认它是否关闭缓存客户端**（调用方期望它 close）；若只是 `dict.clear()` 而未 close，本计划一并在其中补 close（OpenAI SDK 客户端有 `.close()`）。
- 自定义 key/base_url 的主要调用方（不需修改，供理解流量）：`backend/agents/financial_agents.py:144-153,335-356`、`backend/expert_panel.py:334,797,1144,1347`、`backend/ai_chat.py:44`。
- 注释（:691）已警告"避免 Key/URL 混淆"——复合键正是为此：同 vendor 不同 key 必须互不串用。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_provider_gateway_cache.py -q`（新建） | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/models/provider_gateway.py`（`get_client` 复合缓存键、必要时 `clear_client_cache` 补 close）
- `tests/test_provider_gateway_cache.py`（新建）

**Out of scope**:
- 调用方（agents/expert_panel/ai_chat）——流量不变，只改变客户端获取语义。
- `_record_cost` 成本记录逻辑。
- `create_ssrf_safe_http_client` 的 DNS 固定机制。
- 给 `OpenAI` 客户端加显式池大小/keep-alive 调参——无证据需要。

## Git workflow

- Branch: `advisor/011-llm-client-cache-lifecycle`
- 提交风格：`fix(models): cache custom-key LLM clients under composite keys and close them on clear`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 核实 `clear_client_cache` 现状

`grep -n "def clear_client_cache" -A 15 backend/models/provider_gateway.py`。
- 若已遍历 close：记录行为，Step 3 复用；
- 若只是清空 dict：本计划中给它补 close（逐个 `client.close()`，单个 close 失败用 try/except 容忍并 log，不得中断清理）。

**Verify**: 无命令，把结论写进 commit message。

### Step 2: 复合缓存键

`get_client` 改为：

```python
def get_client(vendor: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> OpenAI:
    """获取客户端。自定义 api_key/base_url 也走缓存——键为 (vendor, base_url, key 哈希)，避免混淆。"""
    if api_key or base_url:
        key_hash = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]
        cache_key = (vendor, (base_url or "").strip(), key_hash)
    else:
        cache_key = (vendor, "", "")
    with _client_cache_lock:
        if cache_key in _client_cache:
            return _client_cache[cache_key]
        client = create_client(vendor, api_key, base_url)
        _client_cache[cache_key] = client
        return client
```

（`import hashlib` 按文件现有导入区补充；`_client_cache` 的 Dict 类型注解同步放宽为 `Dict[tuple, OpenAI]`。）注意：`create_client` 内部对缺省补全（env 配置）的逻辑不变——`(vendor, "", "")` 键等价于原 `vendor` 键，老行为保持。

**Verify**: `ruff check backend/models/provider_gateway.py` → exit 0。

### Step 3: 测试

新建 `tests/test_provider_gateway_cache.py`（monkeypatch `create_client` 为计数工厂，返回带 `.close()` 的轻量假客户端——不要真连网络）：

- 同 `(vendor, key, url)` 两次 `get_client` → 工厂只被调 1 次，返回同一对象；
- 同 vendor 不同 key → 两个客户端；
- 无自定义参数 → 与原 `vendor` 单键行为一致（两次调用同一个）；
- `clear_client_cache()` 后所有缓存客户端的 `.close()` 被调用（若 Step 1 确认原本就 close，则改为回归断言）。
- 测试隔离：每个用例前后清空 `_client_cache`（fixture）。

**Verify**: `python -m pytest tests/test_provider_gateway_cache.py -q` → 全过。

### Step 4: 全量回归

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`ruff check backend frontend tests && ruff format --check backend frontend tests` → exit 0。

## Test plan

- 见 Step 3（4 用例）。
- 若存在既有 provider_gateway 测试文件（`ls tests/ | grep -i gateway`），优先追加进去而非新建。

## Done criteria

- [ ] `grep -n "if api_key or base_url:" -A 3 backend/models/provider_gateway.py` 显示缓存路径而非直接 `return create_client`
- [ ] 缓存键不含明文 key（`grep -n "sha256" backend/models/provider_gateway.py` 命中）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `_client_cache` 有其他读写方假设键是字符串 vendor（`grep -rn "_client_cache" backend/` 排查；若有，先统一改复合键再动 `get_client`）。
- `OpenAI` 客户端版本无 `.close()`（查 `openai==2.3.0` 的 API——有 `close()`；若验证不符，报告并改用弱引用+显式注册表方案）。
- 某调用方依赖"每次拿到全新客户端"（例如测试并发隔离）——全量回归若出现相关失败，定位调用方并报告，不要为其开后门。

## Maintenance notes

- 缓存增长上界 = 不同 (vendor, base_url, key) 组合数，量级很小（用户可配置的 provider 数）；如未来支持按请求临时 key，需加 LRU 上限。
- PR 评审重点：key 哈希截断 16 位足够防碰撞于此规模；**任何地方不得把 api_key 明文拼进日志/异常消息**（顺手确认 `create_client` 的 RuntimeError 文案不含配置值）。
- 关联：`plans/010` 修同类资源泄漏（SQLite 连接）；专家团配置磁盘读缓存见 `plans/012`。
