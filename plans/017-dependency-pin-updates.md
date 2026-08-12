# Plan 017: 依赖钉版升级——删除零导入的 aiohttp，修复 requests/curl_cffi/python-dotenv 已知漏洞

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- requirements-core.txt pyproject.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（删 aiohttp）/ MED（curl_cffi 的 TLS 指纹行为跨版本可能变化，它正是反爬抓取所选）
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`requirements-core.txt` 的钉版存在已知漏洞与一处纯负担：

- `aiohttp==3.12.4` — pip-audit 报 31 条 advisory，而**全仓库零导入**（`grep -rn "aiohttp" backend/ frontend/ tests/ --include="*.py"` 无匹配，已核实）——纯攻击面与供应链重量，删除零成本。
- `requests==2.32.3`（PYSEC-2026-1872 / PYSEC-2026-2275，新闻抓取路径可达）、`curl_cffi==0.13.0`（PYSEC-2026-2431，`backend/news_data.py` 与 `backend/providers/eastmoney_provider.py` 可达）、`python-dotenv==1.1.0`（PYSEC-2026-2270）均有修复版未升。

本仓库的整洁约定：requirements 文件与 `pyproject.toml` 依赖**逐钉一致**（已核验零漂移），改动必须两边同步。

## Current state

- `requirements-core.txt:12-25` 一带：`pandas==3.0.3`、`requests==2.32.3`、`curl_cffi==0.13.0`、`openai==2.3.0`、`python-dotenv==1.1.0`、`aiohttp==3.12.4` 等（行号以 `grep -n` 实测为准）。
- `pyproject.toml:21-38` — `dependencies` 列表与 core 清单一一对应（含 `aiohttp==3.12.4`、`requests==2.32.3` 等）。
- curl_cffi 的调用点：`grep -rn "curl_cffi" backend/ --include="*.py" | head`（`news_data.py`、`eastmoney_provider.py`）——升级后必须烟测这两处。
- 审计基线：`pip-audit -r requirements-core.txt -r requirements-api.txt` 报 35 条已知漏洞（4 个包）。逐条 CVE 的运行时可达性**未**逐一核实——按姿态债处理。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 漏洞基线 | `pipx run pip-audit -r requirements-core.txt 2>/dev/null || pip-audit -r requirements-core.txt` | 输出 advisory 列表（升级后 4 包清零） |
| 零导入确认 | `grep -rn "aiohttp" backend/ frontend/ tests/ scripts/ --include="*.py"` | 无匹配 |
| 目标回归 | `python -m pytest tests/test_news_data.py tests/test_news_stale_cache.py tests/test_settings.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| 清单一致 | `grep -E "requests|curl_cffi|dotenv|aiohttp" requirements-core.txt pyproject.toml` | 两边钉版一致 |

## Scope

**In scope**:
- `requirements-core.txt`（删 aiohttp；升 requests/curl_cffi/python-dotenv）
- `pyproject.toml`（`dependencies` 同步）

**Out of scope**:
- 其他 requirements-*.txt（本次审计未发现它们有 advisory）。
- 逐 CVE 可达性分析。
- 实际重装环境——执行者只改清单；本地环境重装由人执行（见 Done criteria 的人工项）。
- akshare/openai/pandas 等其他钉版。

## Git workflow

- Branch: `advisor/017-dependency-pin-updates`
- 提交风格：`build(deps): drop unused aiohttp and bump requests/curl_cffi/python-dotenv for CVE fixes`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 确认 aiohttp 零导入并删除

`grep -rn "aiohttp" backend/ frontend/ tests/ scripts/ --include="*.py"` → 必须无匹配（有匹配 = STOP）。从 `requirements-core.txt` 与 `pyproject.toml` 两处删除该行。

**Verify**: `python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in pathlib.Path('backend').rglob('*.py')]; print('parse ok')"` → `parse ok`（无隐藏依赖导致语法级问题——真正的验证是全量测试）。

### Step 2: 升级三个有修复版的钉版

运行 `pipx run pip-audit -r requirements-core.txt`（无 pipx 则 `pip install --user pip-audit` 后运行；不要在项目 venv 里装审计工具）拿到当前 advisory 与**修复版本号**。把 `requests`、`curl_cffi`、`python-dotenv` 升到各自**最小修复版**（不要顺手大版本跳跃），`requirements-core.txt` 与 `pyproject.toml` 同步改。

**Verify**: 再跑一次 pip-audit → 这三个包与 aiohttp 的 advisory 清零（其余包若有新增 advisory 与本计划无关，记录不处理）。

### Step 3: 烟测抓取链路

`python -m pytest tests/test_news_data.py tests/test_news_stale_cache.py tests/test_settings.py -q` → 全过。curl_cffi 的 TLS 指纹行为是其反爬用途的关键——**检查测试是否真正覆盖 impersonate 行为**：`grep -rn "impersonate" backend/ tests/ | head`；若仅生产代码有、测试全 mock，则在 commit message 标注"curl_cffi 运行时行为未被离线测试覆盖，需一次联网烟测"，并把联网烟测（启动后端访问 `/api/news?symbol=600519` 与 `/api/fund-flow/600519?days=30` 确认 `source_status=ok`）列入人工清单。

**Verify**: 上述测试全过。

### Step 4: 全量回归

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Test plan

- 无新测试；以既有新闻/设置测试 + 全量回归为验证。
- 若本地环境仍装着旧版依赖：本计划验证以**清单文本**与（可选）在干净 venv 中 `pip install -r requirements-core.txt` 后的导入冒烟为准——执行者如无法创建隔离环境，在报告中声明验证边界，不要污染项目 venv。

## Done criteria

- [ ] `grep -n "aiohttp" requirements-core.txt pyproject.toml` 无匹配
- [ ] pip-audit 输出中 requests/curl_cffi/python-dotenv/aiohttp 四条清零
- [ ] 两清单钉版一致（`grep -E "requests==|curl_cffi==|dotenv==" requirements-core.txt pyproject.toml`）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `git status` 无 scope 外文件
- [ ] 人工清单（联网烟测 curl_cffi 两接口）写入提交说明
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- aiohttp 出现任何真实导入（Step 1 的 grep 有匹配）。
- 最小修复版与本仓库其他约束冲突（如 requests 新版要求 urllib3 大版本跳跃）——记录冲突矩阵，报告，不要连带升级。
- pip-audit 报出本计划范围外包的高危 advisory——记录，报告，不顺手处理。

## Maintenance notes

- 建议把 `pip-audit` 纳入 CI 的周期性（非阻塞）任务——本次是人工触发的点查，会再次过时。
- PR 评审重点：curl_cffi 版本差（release notes 中 TLS 指纹/浏览器模拟变化）；两清单严格同步。
- 明确延期：其余 31 条 aiohttp advisory 随删除自动消失；逐 CVE 可达性不分析。
