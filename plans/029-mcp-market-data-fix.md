# Plan 029: 修复 MCP get_market_data——导入不存在的 fetch_prices，旗舰行情工具开箱即坏；并给五个工具补调用级回归测试与错误脱敏

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 375285d..HEAD -- backend/mcp_server.py backend/price_fetcher.py tests/test_mcp_server.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `375285d`, 2026-08-30

## Why this matters

MCP server 是 AlphaScope 对外暴露研究能力的协议面（Claude Desktop 等）。其旗舰工具 `get_market_data` 导入 `backend.price_fetcher.fetch_prices`，但该模块**没有**这个符号——每次调用必抛 `ImportError`，被捕获后把 Python 报错文本返回给外部 LLM 客户端。五个工具的 catch 分支都在返回 `str(e)[:100]`，内部细节（模块名、路径、供应商报错）会泄入第三方客户端上下文。现有测试只断言工具名注册，从不调用工具本体，所以这类「开箱即坏」存活至今。

## Current state

- `backend/mcp_server.py:98-116` — `get_market_data` 工具（现状节选）：
  ```python
  try:
      import json

      from backend.price_fetcher import fetch_prices        # ← 符号不存在 → ImportError

      bars = fetch_prices(symbol, period="daily", count=30)  # ← 签名也不匹配
      if not bars:
          return json.dumps({"error": f"无 {symbol} 行情数据"}, ensure_ascii=False)
      rows = [... for b in bars[-10:]]
      return json.dumps({"symbol": symbol, "bars": rows}, ensure_ascii=False)
  except Exception as e:
      return f'{{"error": "获取行情失败: {str(e)[:100]}"}}'
  ```
- `backend/price_fetcher.py` 全部公开函数（grep 核验）：`_normalize_symbol`(:12)、`_load_history`(:28)、`get_price_after`(:87)、`get_price_range`(:116)、`get_recent_bars`(:158)。**没有** `fetch_prices`。`get_recent_bars(symbol, count=5)` 返回 `List[Dict[str, float | str]]`（含 date/close/volume 键），正是本工具需要的形状。
- `backend/mcp_server.py:115, 150, 179, 196, 220` — 五个工具的错误返回均为 `f'{{"error": "...失败: {str(e)[:100]}"}}'` 形态。
- `tests/test_mcp_server.py:29-40` — 只断言 5 个工具名注册；`backend/mcp_server.py` 头部注明使用 `from mcp.server.fastmcp import FastMCP`，`@server.tool()` 注册。
- 仓库约定：MCP 层「失败安全、结构化错误、不触网交易」（见文件头 docstring）；中文注释。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 定向测试 | `python -m pytest tests/test_mcp_server.py -q` | 全部通过（含新增用例） |
| 冒烟 | `python -c "import backend.mcp_server"` | exit 0 |
| 全量离线 | `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` | 与基线一致 |

## Scope

**In scope**:
- `backend/mcp_server.py`
- `tests/test_mcp_server.py`

**Out of scope**:
- `backend/price_fetcher.py` — 只消费其现有函数，不新增/修改（别的调用方依赖其行为）。
- `backend/api/prices.py` 里的 `async def fetch_prices` — 它是 API 层函数（签名 async + days），不要让 MCP 工具依赖 API 层。
- MCP 工具清单增删、transport 变更（stdio 是正确形态）。

## Git workflow

- Branch: `advisor/029-mcp-market-data-fix`
- Commit style: conventional commits（中文正文）
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: 换用真实存在的数据入口

`backend/mcp_server.py:98` 的 `from backend.price_fetcher import fetch_prices` 改为 `from backend.price_fetcher import get_recent_bars`；`:100` 改为 `bars = get_recent_bars(symbol, count=30)`。其后 `rows`/返回逻辑保持不变（`b.get("date","")` / `b.get("close",0)` / `b.get("volume",0)` 与 `get_recent_bars` 返回键兼容；先打开 `backend/price_fetcher.py:158-179` 核对返回 dict 的键名，若 volume 键名不同（如 `vol`），以实际键名为准映射并在 `rows` 处适配）。

**Verify**: `python -c "from backend.price_fetcher import get_recent_bars; print('ok')"` → `ok`

### Step 2: 五个工具的错误脱敏

为每个工具的 `except Exception as e:` 分支统一改为：本地 `logger.warning("<tool> 失败", exc_info=True)` + 返回稳定短错误（如 `json.dumps({"error": "行情数据暂不可用"}, ensure_ascii=False)`；检索类 `{"error": "证据检索暂不可用"}` 等，每个工具一个固定文案）。`backend/mcp_server.py` 顶部如无 `logger = logging.getLogger(__name__)` 则补上。不要改动非异常路径的返回结构。

**Verify**: `grep -n "str(e)\[:100\]" backend/mcp_server.py` → 无匹配。

### Step 3: 工具调用级回归测试

在 `tests/test_mcp_server.py` 中为 5 个工具各加一条"调用本体"的用例。实现路径二选一（以仓库实际安装的 `mcp` 包行为为准，先在 REPL 确认）：
- 若 `@server.tool()` 装饰后仍可通过原函数名直接调用（`mcp.server.fastmcp` 的装饰器多数版本返回原函数），直接 `get_market_data(symbol="600519")` 断言返回 JSON 可解析、或（离线无数据时）返回 `{"error": "无 ... 行情数据"}` / 稳定错误文案而非 ImportError 文本；
- 若装饰器替换了函数对象，则把每个工具的函数体抽成模块级 `_get_market_data_impl(symbol)` 等私有函数，装饰器内只做转发，测试调用 impl。
价格数据用 monkeypatch 桩掉 `backend.price_fetcher.get_recent_bars`（离线稳定）；`search_evidence` / `top_movers` 等同理桩其依赖入口。断言要点：返回是合法 JSON；错误路径**不含** `ImportError`/`TypeError`/文件路径字样。

**Verify**: `python -m pytest tests/test_mcp_server.py -q` → 全过，新增 ≥5 用例。

## Test plan

- 新增用例见 Step 3；结构参照 `tests/test_mcp_server.py` 既有 fixture（`create_server` 可用性 import-guard）。
- 离线约束：全部用 monkeypatch，不触网、不依赖真实 akshare。

## Done criteria

- [ ] `grep -n "fetch_prices" backend/mcp_server.py` 无匹配
- [ ] `grep -n "str(e)\[:100\]" backend/mcp_server.py` 无匹配
- [ ] `python -m pytest tests/test_mcp_server.py -q` 全过且含 5 个新调用级用例
- [ ] `python -m pytest tests/ -m "not network" --ignore=tests/probes -q` 与基线一致
- [ ] 无 Scope 外文件改动（`git status`）

## STOP conditions

- `get_recent_bars` 的返回键与工具 `rows` 映射对不上且改动会超出 `backend/mcp_server.py` 范围。
- `mcp` 包未安装导致既有测试本就 skip（此时 Step 3 以 impl 抽取方式落地并用 `pytest.importorskip` 保持一致口径；若抽取涉及 >5 个工具的大改，停下来报告）。
- 摘录与现场代码不符。

## Maintenance notes

- 后续任何 MCP 工具新增，必须同时加"调用本体"的用例——只断言注册的测试就是本次缺陷存活的原因。
- `get_recent_bars` 默认 `count=5`，工具用 30 后截尾 10 行，语义（"最近 N 日摘要"）在 docstring 里写清。
