# Plan 021: 复活自选股监控告警——修复 get_price_range 误用与元组/字典形状错配

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — a reviewer
> maintains the index.
>
> **Drift check (run first)**: `git diff --stat 06182ca..HEAD -- backend/price_fetcher.py backend/ingestion/scheduled_reports.py backend/runtime/tool_router.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `06182ca`, 2026-08-01

## Why this matters

自选股价格/成交量告警功能当前**整体失效**：`backend/ingestion/scheduled_reports.py:152` 用 2 个参数调用 `get_price_range(symbol, date_str, days)`（该函数要求 3 参），抛 `TypeError` 后被 `except Exception` 吞掉；即便修好参数，代码按 dict 访问返回的元组（`latest.get("close")`）也会再失败。10 分钟监控循环与 `POST /api/alerts/check` 因此永远产出零告警。同一签名误用还使 Tool Router 的 `market_data` 工具**永远返回错误**（`backend/runtime/tool_router.py:238`）。本计划让两个死功能复活，且不改变其他 3 处正确调用（archive_tagger.py:151、portfolio_calc.py:106、vision_agent.py:136 均传满 3 参，保持不变）。

## Current state

- `backend/price_fetcher.py:28-78` — `_load_history(symbol, base_date)` 经 akshare 拉取 base_date 前后约 6 个月的日线，返回含 `date`(YYYY-MM-DD 字符串) 与 `close`(float) 两列的 DataFrame（**无 volume 列**）。列名归一化逻辑：
  ```python
  df.columns = [str(c).strip().lower() for c in df.columns]
  date_col = next((c for c in df.columns if "date" in c or "日期" in c), None)
  close_col = next((c for c in df.columns if c in ("close", "收盘", "收盘价", "closeprice")), None)
  ```
  akshare `stock_zh_a_hist` 的成交量列名为 `"volume"`/`"成交量"`。
- `backend/price_fetcher.py:110-149` — `get_price_range(symbol, date_str, days)` 返回 **date 之后**的 `[(date, close), ...]` 元组序列；要求起始日期，语义是"某日之后的 N 个交易日"，不是"最近 N 个交易日"。**不要改它的签名**（archive_tagger/portfolio_calc/vision_agent 依赖它）。
- `backend/ingestion/scheduled_reports.py:143-202` — `_check_item_alerts(item)`（告警检查核心，本计划要修）：
  ```python
  from backend.price_fetcher import get_price_range
  data = get_price_range(item.symbol, days=5)          # ← 缺 date_str, TypeError
  latest = data[-1] if data else {}
  price = latest.get("close", 0)
  volume = latest.get("volume", 0)
  trade_day = str(latest.get("date") or latest.get("day") or "")[:10]
  # 价格变动: data[-2]["close"] 与 latest 对比, 阈值 item.alert_conditions.get("price_change_pct", 5)
  # 成交量: sum(d.get("volume", 0) for d in data[-5:-1]) / 4 为基线, volume > 基线*2 → volume_spike
  ```
  该代码期望 `data` 是**按日期升序的 dict 列表**，每项含 `close`/`volume`/`date`。调用方 `check_alerts()`（同文件 :81-115）把结果持久化到 `alert_store.add_alert`，其签名（`backend/alert_store.py:82`）为 `add_alert(alert_id, symbol, name, alert_type, message, severity, timestamp)` —— **不要动**。
- `backend/runtime/tool_router.py:233-241` — `_tool_market_data`：
  ```python
  from backend.price_fetcher import get_price_range
  data = get_price_range(symbol, days=30)              # ← 同样的缺参 bug
  return {"symbol": symbol, "data": data}
  ```
  调用方契约：`ToolRouter` 工具调用后返回 dict（见 `tests/test_agent_tool_routing.py` 的工具调用测试模式）。
- 监控循环入口：`backend/ingestion/startup.py:75-87`（每 10 分钟调 `manager.check_alerts()`）—— 不需要改。
- 测试模式参考：`tests/test_alerts_api.py:117-125`（`test_alerts_api_check_endpoint` 只断言不抛异常）；`tests/test_agent_tool_routing.py` 用 `unittest.mock.patch` 注入 mock（读该文件模仿其风格）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全过（含新增） |
| 定向回归 | `python -m pytest tests/test_alerts_api.py tests/test_agent_tool_routing.py tests/test_scheduled_reports.py -q` | 全过 |
| Lint      | `python -m ruff check backend/price_fetcher.py backend/ingestion/scheduled_reports.py backend/runtime/tool_router.py tests/test_scheduled_reports.py` | exit 0 |

## Scope

**In scope**:
- `backend/price_fetcher.py`
- `backend/ingestion/scheduled_reports.py`
- `backend/runtime/tool_router.py`
- `tests/test_scheduled_reports.py`（新建）

**Out of scope**（看起来相关但**不要动**）:
- `backend/price_fetcher.py` 中 `get_price_range`/`get_price_after` 的签名与语义
- `backend/archive_tagger.py`、`backend/api/portfolio_calc.py`、`backend/vision/vision_agent.py` 中对 `get_price_range` 的正确 3 参调用
- `backend/alert_store.py`、`backend/ingestion/startup.py`、`backend/watchlist_store.py`
- CORR-08 的"内存告警列表无界 + ack 状态分叉"（`scheduled_reports.py:98,204-227`）——另一个已记录发现，不在本计划

## Git workflow

- Branch: `advisor/021-watchlist-alerts-fix`
- 提交风格（参考仓库 log）：`fix(alerts): revive watchlist alert monitoring broken by get_price_range misuse`
- 不要 push、不要开 PR；把分支留给操作者审阅合并。

## Steps

### Step 1: 给 `_load_history` 增加 volume 列（additive）

在 `backend/price_fetcher.py` 的 `_load_history` 中，在 `close_col` 判定之后加：
```python
volume_col = next(
    (c for c in df.columns if c in ("volume", "成交量")),
    None,
)
```
在 `out = pd.DataFrame({...})` 里加 `"volume": pd.to_numeric(df[volume_col], errors="coerce") if volume_col else 0.0`，`dropna(subset=["close"])` 之后用 `.fillna(0.0)` 或 `.where(pd.notna(out["volume"]), 0.0)` 把 NaN 成交量补 0。**不得改变 `date`/`close` 列的产出**。

**Verify**: `python -m pytest tests/test_price_store.py -q` → 全过（该文件覆盖价格存储，确认无回归）；再 `python -c "from backend.price_fetcher import _load_history; from datetime import datetime; df=_load_history('600519', datetime.now()); print(list(df.columns) if df is not None else 'no data')"` → 若联网成功应含 `date, close, volume`；无网则打印 `no data` 也视为通过（本步验证以测试为准）。

### Step 2: 新增 `get_recent_bars(symbol, count)` 帮助函数

在 `backend/price_fetcher.py` 中 `get_price_range` 之后新增：
```python
def get_recent_bars(symbol: str, count: int = 5) -> List[Dict[str, float | str]]:
    """获取最近 count 个交易日的 [{"date","close","volume"}] 序列(按日期升序)。

    供告警检查/行情工具使用;数据失败或为空返回 []。
    """
```
实现：`base_date = datetime.now()`，`_load_history(symbol, base_date)`，空则返回 `[]`；取末尾 `count` 行，返回 `[{"date": row["date"], "close": float(row["close"]), "volume": float(row["volume"])} for ...]`。文件顶部 import 需含 `Dict`（当前只有 `List, Tuple, Optional`——按仓库风格在 typing import 里补 `Dict`）。

**Verify**: `python -c "from backend.price_fetcher import get_recent_bars; print(get_recent_bars('600519', 3) or '[]')"` → 联网时输出 3 个 dict；无网时 `[]`（本步的正式验证是 Step 3 的测试）。

### Step 3: 修 `_check_item_alerts`

在 `backend/ingestion/scheduled_reports.py:150-152`，把
```python
from backend.price_fetcher import get_price_range
data = get_price_range(item.symbol, days=5)
```
改为
```python
from backend.price_fetcher import get_recent_bars
data = get_recent_bars(item.symbol, count=5)
```
其余告警逻辑（dict 访问、去重 ID、阈值）**原样保留**——`data` 现在是它本来就期望的形状。`data` 仍为空时返回空列表的逻辑不变。

**Verify**: `python -m pytest tests/test_scheduled_reports.py -q`（Step 5 创建）→ 全过。

### Step 4: 修 `_tool_market_data`

在 `backend/runtime/tool_router.py:236-238`，改为 `get_recent_bars(symbol, count=30)`，返回形状不变（`{"symbol", "data"}`）。

**Verify**: `python -m pytest tests/test_agent_tool_routing.py -q` → 全过。

### Step 5: 写回归测试 `tests/test_scheduled_reports.py`（新建）

参照 `tests/test_alerts_api.py` 的导入风格（函数内 import、无夹具依赖）。测试以下：

1. `test_check_item_alerts_price_change_fires` — monkeypatch `backend.ingestion.scheduled_reports.get_recent_bars`（用 `unittest.mock.patch` 或在函数内 `import backend.ingestion.scheduled_reports as sr; sr.get_recent_bars = fake`）返回构造数据：5 天序列，`close` 从 10.0 涨到 11.0（+10% ≥ 默认阈值 5%），`volume` 恒定 1000。构造 `WatchListItem`（`backend.ingestion.scheduled_reports.WatchListItem`，字段 symbol/name/added_at/alert_conditions）→ `manager._check_item_alerts(item)` 返回 ≥1 条 `price_change` 告警，且 `message` 含符号。
2. `test_check_item_alerts_no_alert_within_threshold` — 5 天 `close` 波动 <5% → 返回空列表。
3. `test_check_item_alerts_volume_spike_fires` — `close` 恒 10.0，`volume` 前 4 天 100、最后 1 天 300（>2× 均值）→ 有 `volume_spike` 告警。
4. `test_check_item_alerts_empty_data_ok` — `get_recent_bars` 返回 `[]` → 返回空列表、不抛异常。
5. `test_check_alerts_persists_through_store` — monkeypatch 上述函数返回含 1 条告警的数据，`manager.check_alerts(persist=True)` → 返回的 `new_alerts` 长度 ≥1（不依赖真网络）。

**Verify**: `python -m pytest tests/test_scheduled_reports.py -q` → 5 个测试全过。

### Step 6: 全量回归 + lint

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过；`python -m ruff check`（scope 内 4 文件）→ exit 0。

## Test plan

- 新增 `tests/test_scheduled_reports.py` 5 个测试（见 Step 5），全部 mock 行情、无网络依赖。
- 复用模式：`tests/test_alerts_api.py:117-125`（API 契约）+ `tests/test_agent_tool_routing.py` 的 `unittest.mock.patch` 用法。
- 不需要新增 API 级测试（`test_alerts_api_check_endpoint` 已存在，且现在会真实走修复后的路径——注意它在无自选股时只断言 `scanned`/`new` 字段，仍然通过）。

## Done criteria

- [ ] `python -m pytest tests/test_scheduled_reports.py -q` → 5 过
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过
- [ ] `python -m ruff check backend/price_fetcher.py backend/ingestion/scheduled_reports.py backend/runtime/tool_router.py tests/test_scheduled_reports.py` → exit 0
- [ ] `grep -n "get_price_range(item.symbol\|get_price_range(symbol, days" backend/ingestion/scheduled_reports.py backend/runtime/tool_router.py` → 无匹配
- [ ] `git status` 只含 scope 内文件
- [ ] 已按 Git workflow 提交到 `advisor/021-watchlist-alerts-fix` 分支

## STOP conditions

- `_load_history` 的改动导致 `tests/test_price_store.py` 或现有 `date`/`close` 断言失败（说明 shape 被破坏）。
- `_check_item_alerts` 或 `_tool_market_data` 的实际代码与 "Current state" 摘录不一致（已漂移）。
- 需要修改 scope 外文件才能达成目标。
- `get_recent_bars` 的返回形状与 `_check_item_alerts` 的既有 dict 访问（`.get("close")`/`.get("volume")`/`.get("date")`）对不上。

## Maintenance notes

- 告警去重 ID 依赖 `trade_day`（最新 K 线日期）：`get_recent_bars` 返回升序序列，`data[-1]` 是最新交易日——与现有逻辑一致。
- 本计划只修"数据通路"；"监控线程内存列表无界"（CORR-08）仍是独立未决问题，评审时留意不要顺手改 `self._alerts` 逻辑。
- 若未来把行情源切到 provider 注册表（`backend/providers/registry`），`get_recent_bars` 是实现对齐点（当前直接走 akshare，与 `get_price_range` 一致）。
