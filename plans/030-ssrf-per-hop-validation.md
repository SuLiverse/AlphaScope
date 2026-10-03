# Plan 030: 新闻抓取与 provider HTTP 的重定向逐跳 SSRF 校验——堵住「首跳合法、中间跳进内网」的盲 SSRF

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 375285d..HEAD -- backend/api/news.py backend/providers/http_json_provider.py backend/security/url_guard.py`
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

`POST /api/news/parse-url` 与 provider HTTP 通道都在**抓取前**校验 URL 公网合法性，却用 `allow_redirects=True`（requests 默认）让中间每一跳 30x 由 HTTP 库自行解析并请求——`url_guard` 只在**抓取完成后**对最终 URL 复检。攻击者提交一个首跳公网、重定向链穿过 `127.0.0.1`/内网/云元数据地址的 URL，服务器会真实发出这些内部请求（盲 SSRF：内网探测、触发内部服务的 GET 副作用）；且最终复检失败时返回的"重定向到不安全目标"错误本身就是一个干净的内网可达性 oracle。这正是上轮审计列入"下一批安全专项"的遗留项。

## Current state

- `backend/api/news.py:417-435` — `_fetch_html`（现状节选）：
  ```python
  safe_url = _validate_public_http_url(url)
  response = requests.get(
      safe_url,
      headers={...},
      timeout=(3.0, 5.0),
      allow_redirects=True,        # ← 中间跳不受校验
      stream=True,
  )
  try:
      response.raise_for_status()
      final_url = _validate_public_http_url(str(response.url or safe_url))   # ← 只查最终 URL
  ```
  `_validate_public_http_url` 是 `backend.security.url_guard.validate_public_http_url(..., allow_local=False)` 的包装（见 `news.py:366-373` 附近）。全仓 `grep allow_redirects backend/` 仅此一处显式 `True`。
- `backend/providers/http_json_provider.py:300-345` — 两条路径同样"抓取后复检最终 URL"：requests 路径 `requests.request(method, safe_url, ...)`（默认跟随重定向，`:311` 后复检 `resp.url`）；urllib 回退路径 `urllib.request.urlopen(req, ...)`（默认跟随重定向，`:339-345` 复检 `r.geturl()`）。注释「重定向后复校验最终 URL(防 302→内网绕过)」表明意图是逐跳安全，但实现只覆盖了末跳。
- `backend/security/url_guard.py` — 已有 `validate_public_http_url`（DNS 解析 → 地址分类 → 拒绝非全局地址）。本计划新增的逐跳能力放进该模块（或同包新文件），复用同一判定函数。
- 仓库约定：security 模块中文注释 + `__init__` 导出；测试离线（monkeypatch，不触网）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 定向测试 | `python -m pytest tests/test_redirect_guard.py -q` | 全部通过（新建） |
| 现有安全测试 | `python -m pytest tests/test_security_enhanced.py tests/test_news.py -q` | 全部通过 |
| 全量离线 | `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` | 与基线一致 |

（若 `tests/test_news.py` 不存在，以 `ls tests/ | grep -i news` 的实际文件名为准。）

## Scope

**In scope**:
- `backend/security/url_guard.py`（新增逐跳安全抓取 helper）
- `backend/api/news.py`（`_fetch_html` 改用 helper）
- `backend/providers/http_json_provider.py`（requests 路径与 urllib 回退路径改用 helper / 逐跳校验）
- `tests/test_redirect_guard.py`（新建）

**Out of scope**:
- `url_guard` 现有 `validate_public_http_url` 的判定语义（DNS 解析、地址分类、allow_local 开关）——只复用，不修改。
- `backend/ai_chat.py`、`backend/rag/vector_store.py` 的 OpenAI 客户端 pinned-DNS 问题 —— 另有计划 031。
- 新闻解析的 HTML 抽取逻辑、provider 的业务重试/降级语义。

## Git workflow

- Branch: `advisor/030-ssrf-per-hop-validation`
- Commit style: conventional commits（中文正文）
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: 新增逐跳安全抓取 helper

在 `backend/security/url_guard.py` 增加（中文 docstring 说明威胁模型）：

```python
def fetch_public_url(url, *, method="GET", headers=None, timeout=(3.0, 5.0),
                     max_hops=5, stream=False, body=None):
    """逐跳校验的重定向安全抓取。

    每一跳（含首跳）都先 validate_public_http_url(allow_local=False) 再请求；
    任一跳失败抛 ValueError；超过 max_hops 抛 ValueError。
    """
```

实现要点：`allow_redirects=False` 的循环——当前 URL 校验 → `requests.request(method, current, headers=..., timeout=..., allow_redirects=False, stream=stream, data=body)` → 若 3xx 且有 `Location`，按 RFC 3986 `urljoin(current, location)` 解析下一跳（相对重定向必须正确处理）→ 继续循环；非 3xx 返回 response。把 `raise_for_status()`、content-type 判断等**留给调用方**（保持现有职责划分）。helper 不读环境代理以外的全局状态。

**Verify**: `python -c "from backend.security.url_guard import fetch_public_url; print('ok')"` → `ok`

### Step 2: 接入 news `_fetch_html`

`backend/api/news.py:417-435`：`requests.get(..., allow_redirects=True, ...)` 整体替换为 `fetch_public_url(safe_url, headers={...}, timeout=(3.0, 5.0), stream=True)`。保留其后的 `raise_for_status()`、`_validate_public_http_url(str(response.url or safe_url))` 复检（最终复检无害，且对"无重定向直连内网"仍是必要防线——虽然首跳校验已覆盖）、content-type 检查与分块读取逻辑原样保留。`_fallback_url_parse` 的调用链无需改动（异常语义不变：仍抛 `ValueError`）。

**Verify**: `grep -n "allow_redirects=True" backend/api/news.py` → 无匹配。

### Step 3: 接入 http_json_provider

`backend/providers/http_json_provider.py`：requests 路径（`:300-326`）改为调用 `fetch_public_url(..., method=method, headers=headers, timeout=timeout, body=body if method == "POST" else None)`，随后保留「重定向后复校验最终 URL」的兜底块与 `status >= 400` 处理。urllib 回退路径：不要试图给 urllib 写手动循环——改为给 `urllib.request.build_opener` 挂一个校验型 `HTTPRedirectHandler`（重写 `redirect_request`，对每个新 URL 先 `validate_public_http_url(newurl)`，不合法则抛 `ValueError`），首跳仍由现有 `validate_public_http_url(safe_url)` 把守。若判断 urllib 回退在该工程从未被实际触发（requests 是硬依赖），可改为：回退路径直接抛出带指引的 `RuntimeError` 并在注释说明原因——**但必须先 `grep -rn "http_json_provider" backend/` 确认调用方对该回退无特殊依赖**，两案择一，写清依据。

**Verify**: `python -c "import backend.providers.http_json_provider"` → exit 0。

### Step 4: 回归测试 `tests/test_redirect_guard.py`（新建）

全部离线（monkeypatch `requests.request` / `requests.get`）：
1. 两跳公网重定向 → 正常返回最终 response（证明合法多跳不被误伤）；
2. 首跳公网、`Location` 指向 `http://127.0.0.1:8000/` → 抛 `ValueError` 且**第二次请求从未发出**（用计数 stub 断言调用次数）；
3. 相对路径 `Location: /next` → 正确 urljoin 后继续；
4. `max_hops` 超限 → `ValueError`；
5. news `_fetch_html` 与 provider requests 路径的接入冒烟（桩掉底层后断言不走 `allow_redirects=True` 调用）。

**Verify**: `python -m pytest tests/test_redirect_guard.py -q` → 5+ 用例全过。

## Test plan

- 新测试文件与用例见 Step 4；断言"中间请求未发出"是本计划的核心回归点。
- 现有 `tests/test_news*.py`、`tests/test_security_enhanced.py` 必须保持全过。

## Done criteria

- [ ] `grep -rn "allow_redirects=True" backend/` 无匹配
- [ ] `python -m pytest tests/test_redirect_guard.py -q` 全过（≥5 用例）
- [ ] `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 与基线一致
- [ ] 两处调用点（news、provider）+ urllib 回退均已收敛到逐跳校验
- [ ] 无 Scope 外文件改动（`git status`）

## STOP conditions

- `url_guard.validate_public_http_url` 的现签名与摘录不符（说明 008 号计划后的代码已漂移）。
- news 或 provider 的调用方依赖"重定向自动跟随"的可见行为且逐跳循环改变其响应语义（如相对重定向处理差异导致测试大面积红）。
- 发现第三处 `allow_redirects` 真值调用点——报告并纳入，不要自行扩散改动面。

## Maintenance notes

- 今后任何新的出网抓取都应走 `fetch_public_url`，评审时以 `grep -rn "requests\.\(get\|request\)" backend/` 检查新调用点是否绕过。
- `max_hops=5` 的上限与 news 解析的 32KB/5s 预算共同构成抓取侧资源边界，改动其一需同步审视另一个。
- 未做（明确排除）：对重定向到 HTTPS 降级 HTTP 的策略约束、pinned-DNS transport 的全量收敛（见计划 031 与已否决区 SEC-07 备注）。
