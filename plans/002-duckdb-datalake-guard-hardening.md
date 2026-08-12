# Plan 002: 加固 DuckDB 数据湖只读守卫，封堵文件读取与 SSRF 绕过

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/quant/datalake.py backend/security/rate_limit.py tests/test_datalake.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW（纯增量拦截；合法查询只碰 `prices` 视图）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`POST /api/datalake/query` 让持有本地 token 的调用方对数据湖执行自定义 SQL。守卫 `is_select_only` 用黑名单挡文件读取表函数，但只列了 `read_csv/read_json/read_parquet/read_blob/read_text` 一族。以下向量全部绕过（已在本地 duckdb 1.5.4 上实测通过）：

- `parquet_scan(...)` / `csv_scan(...)` / `json_scan(...)` 别名函数——不在黑名单 → **读取服务器任意 CSV/parquet 文件**；
- `glob('C:/Users/*')` → **任意目录枚举**；
- `SELECT * FROM 'C:/path/file.csv'`（字符串字面量替换扫描）→ 任意文件读；
- `parquet_scan('https://...')` 触发 httpfs 自动安装/加载 → **完整 SSRF**（可打云元数据 `169.254.169.254` 并把内容带回响应）。

此外 duckdb 错误原文（含绝对路径/内容片段）经 `{"reason": str(e)}` 直接回显客户端；该端点也不在限流的 `EXPENSIVE_PREFIXES` 名单。这一端点目前击穿整个 `url_guard` SSRF 防线。

## Current state

- `backend/quant/datalake.py:60-64` — 现行函数黑名单：
  ```python
  _FORBIDDEN_FUNC_RE = re.compile(
      r"\b(read_csv_auto|read_csv|read_json_auto|read_json|read_parquet"
      r"|read_blob_auto|read_blob|read_text_auto|read_text)\s*\(",
      re.IGNORECASE,
  )
  ```
- `backend/quant/datalake.py:136-156` — `is_select_only(sql)`：要求以 `select`/`with` 开头、去尾分号后无 `;`、不含 `_FORBIDDEN_SQL` 关键字、不含 `\bset\b`、不含 `_FORBIDDEN_FUNC_RE`。**不拦截** `*_scan` 别名、`glob(`、字符串字面量表名。
- `backend/quant/datalake.py:269-297` — `query()`：
  ```python
  con = duckdb.connect()
  try:
      con.execute(f"CREATE VIEW prices AS SELECT * FROM read_parquet('{_glob_str()}')")
      lim = max(1, min(5000, int(limit) if limit else 500))
      cur = con.execute(f"SELECT * FROM ({sql.rstrip(';')}) AS _q LIMIT {lim}")
      ...
  finally:
      con.close()
  ...
  except Exception as e:  # noqa: BLE001
      return {"ok": False, "reason": str(e)}
  ```
  注意：连接建立后**没有**关闭扩展自动安装/自动加载；内部 `read_parquet` 建视图不经过 `is_select_only`，加固黑名单不会影响它。
- `backend/security/rate_limit.py:212-224` — `EXPENSIVE_PREFIXES` 元组不含 `/api/datalake`（相邻条目有 `/api/analysis`、`/api/quant/backtest` 等）。
- `backend/api/datalake.py:113-123` — 端点把 `result["reason"]` 透传为 ApiResponse.error。
- 测试：`tests/test_datalake.py` 已存在（先读它，沿用其结构；`is_select_only` 是纯函数，无需 duckdb 即可单测）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_datalake.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过（约 2 分钟） |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/quant/datalake.py`（黑名单扩展、字符串字面量表名拦截、连接级扩展锁定、错误信息脱敏）
- `backend/security/rate_limit.py`（`EXPENSIVE_PREFIXES` 加 `/api/datalake/`）
- `tests/test_datalake.py`（追加用例）

**Out of scope**:
- `backend/api/datalake.py` —— 端点层无需改动（`reason` 透传保留，脱敏在 `datalake.py` 内完成）。
- `screen()` / `build_screen_sql()` 的筛选路径 —— 字段/操作符白名单 + 参数绑定，已安全，不动。
- 把 `read_parquet` 从内部建视图路径移除之类的重构 —— 不需要，内部调用不经守卫。

## Git workflow

- Branch: `advisor/002-datalake-guard-hardening`
- 提交风格：`fix(security): close duckdb datalake file-read and SSRF bypasses`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 扩展函数黑名单与字符串字面量表名拦截

在 `backend/quant/datalake.py` 中：

1. `_FORBIDDEN_FUNC_RE` 追加（保持词边界 + `\s*\(` 的现有写法）：`parquet_scan|csv_scan|json_scan|sqlite_scan|glob|parquet_metadata|parquet_schema|parquet_file_metadata`。
2. 新增一个模块级正则 `_STRING_TABLE_RE = re.compile(r"\b(from|join)\s*['\"]", re.IGNORECASE)`，并在 `is_select_only` 中追加拦截（拒绝 `FROM '<literal>'` / `JOIN '<literal>'` 形式的替换扫描）。

**Verify**: `python -c "from backend.quant.datalake import is_select_only as g; cases=['select * from parquet_scan(\'x.parquet\')','select glob(\'C:/Users/*\')','select * from \'data/x.csv\'','select * from prices limit 5','with t as (select 1) select * from t']; print([g(c) for c in cases])"` → `[False, False, False, True, True]`

### Step 2: 连接级锁定扩展自动安装/加载

在 `query()` 中 `con = duckdb.connect()` 之后、建视图之前插入（服务端自有连接，用户 SQL 里的 `SET` 已被 `\bset\b` 拦截，不冲突）：

```python
try:
    con.execute("SET autoinstall_known_extensions=false")
    con.execute("SET autoload_known_extensions=false")
except Exception:  # 老版本 duckdb 无此设置项时降级不阻塞
    pass
```

**Verify**: `python -m pytest tests/test_datalake.py -q` → 既有用例全过（`prices` 视图基于本地 parquet，`read_parquet` 是内置函数，不受 autoload 关闭影响；若你的环境 duckdb 报 `read_parquet` 需要 httpfs 以外的扩展，是 STOP 条件）。

### Step 3: 错误信息脱敏

`query()` 的 `except Exception as e:` 分支不再回显 `str(e)`。改为：服务端 `logger.warning("datalake query failed: %s", e)`（模块已有 logging 惯例则沿用，无则 `import logging; logger = logging.getLogger(__name__)`），返回 `{"ok": False, "reason": "查询执行失败（已拒绝或语法/数据错误）"}`。

**Verify**: `python -c "from backend.quant.datalake import query; r=query('select * from parquet_scan(\\'/etc/passwd\\')'); print(r)"` → `ok: False` 且 `reason` 不含路径与异常原文。

### Step 4: 加入限流名单

`backend/security/rate_limit.py` 的 `EXPENSIVE_PREFIXES` 元组追加 `"/api/datalake/"`（保持元组现有格式与注释风格）。

**Verify**: `python -c "from backend.security.rate_limit import is_expensive_path; print(is_expensive_path('/api/datalake/query'), is_expensive_path('/api/datalake/screen'), is_expensive_path('/api/news'))"` → `True True False`

### Step 5: 测试

在 `tests/test_datalake.py` 追加（沿用文件内既有风格）：

- `is_select_only` 拒绝用例（参数化或逐条断言）：`parquet_scan(`、`csv_scan(`、`json_scan(`、`glob(`、`parquet_metadata(`、`FROM 'C:/x.csv'`、`FROM "s3://bucket/x.parquet"`、http URL 的 `parquet_scan('https://...')`；
- 放行用例：普通 `select ... from prices`、`with` CTE；
- `query()` 集成用例（若文件已有 duckdb 可用性 skip 标记则沿用）：对拒绝向量断言 `ok=False` 且 `reason` 不含异常原文/路径。

**Verify**: `python -m pytest tests/test_datalake.py -q` → 全过，新增用例数 ≥ 8。

## Test plan

- 新增用例见 Step 5，全部进 `tests/test_datalake.py`；结构参照该文件既有 `is_select_only` 用例。
- 回归：`python -m pytest tests/test_datalake.py tests/test_quant_api.py -q` 全绿。
- 验证命令：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] Step 1/3/4 的三条 `python -c` 验证输出与预期一致
- [ ] `python -m pytest tests/test_datalake.py -q` 全过且含 ≥8 个新用例
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- "Current state" 摘录与现状不符（守卫已被重写/迁移）。
- 关闭 autoload 后 `prices` 视图的 `read_parquet` 在 CI/本地 duckdb 版本下不可用。
- 测试揭示存在本计划未列出的其他文件访问通道（如 `attach` 挂载外部库）——记录向量，报告，不要自行扩大黑名单之外的改动（`_FORBIDDEN_SQL` 已含 `attach`，先确认）。

## Maintenance notes

- 黑名单本质上是追赶游戏。若未来 DuckDB 升级引入新的文件/网络表函数，需要在升级评审时重跑本计划 Step 5 的用例清单。长期更优解是专用受限角色/只读挂载，超出本计划范围。
- PR 评审重点：`is_select_only` 的新增拦截是否有词边界误伤（例如列名含 `glob` 的合法查询——`\bglob\s*\(` 带括号锚定，误伤面极小）；错误脱敏后排查问题只能看服务端日志，属可接受权衡。
- 关联：`plans/009-docker-token-hygiene.md` 修 token 分发模型——在它落地前，本计划是降低 token 泄露爆炸半径的关键一环。
