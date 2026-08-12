# Plan 020: 清理文档与清单头部的版本漂移（contract.md / requirements.txt / README 测试数）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- docs/contract.md requirements.txt README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（文档文本）
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

`docs/contract.md` 自称 "API Contract Reference (v0.40.8)"、"所有接口格式以此为准"，`requirements.txt` 头注 `(v0.40)`——而 `pyproject.toml` 已是 1.9.54。读者无法判断这份"契约准绳"是否适用于当前版本；抽查还发现文档路径参数名与代码不符（文档 `{id}` vs 代码 `{task_id}`/`{provider_id}`/`{team_id}`），会误导手写客户端。另外 README 旗舰质量声明 "1800+ 项自动化测试" 与 CI 实测口径（1791 passed + 2 skipped + 1 deselected = 1794）不符——磁盘上虽有 1941 个 `def test_`，但约 150 个在被 ignore 的 `tests/probes/` 中不被收集；按"CI 收集数"口径该声明 overstated。

## Current state

- `docs/contract.md:1` — `# API Contract Reference (v0.40.8)`；`:3` "前后端契约文档。所有接口格式以此为准。"
- `requirements.txt:1` — `# 研策中枢 AlphaScope Dependencies (v0.40)`。
- `README.md:167` — "后端核心路径有 1800+ 项自动化测试覆盖，并在 Python 3.11 / 3.12 上执行非网络套件。"
- 路径参数抽查基线（advisor 已做）：`docs/api.md` 的 54 条路径与代码 200 个端点比对，无幽灵端点；差异仅在参数命名。
- 版本事实源：`pyproject.toml:7` `version = "1.9.54"`。
- 测试数事实源：CI 命令 `python -m pytest tests/ -m "not network" --ignore=tests/probes`，最近全量运行 `1791 passed, 2 skipped, 1 deselected`。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 漂移检查 | `grep -n "v0.40" docs/contract.md requirements.txt` | 修复后无匹配 |
| 参数名抽查 | `grep -n "{id}" docs/contract.md docs/api.md` | 修复后无匹配（或仅余确实为 `{id}` 的路由） |
| 测试数核对 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes --collect-only 2>/dev/null \| tail -2` | 收集数与 README 新表述一致 |

## Scope

**In scope**:
- `docs/contract.md`（头部版本 + 路径参数名对齐）
- `docs/api.md`（仅路径参数名对齐——若抽查发现与 contract.md 同类问题）
- `requirements.txt`（头注版本）
- `README.md`（测试数表述一处）

**Out of scope**:
- 文档内容的全面重审（api.md 本次抽查已确认无幽灵端点，不做全文逐行校对）。
- CHANGELOG 与各历史 release notes（历史文档不追溯改版本）。
- 任何代码。

## Git workflow

- Branch: `advisor/020-docs-version-drift`
- 提交风格：`docs: drop stale version headers and align path params and test-count wording`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 头部版本改为"以 pyproject 为准"

- `docs/contract.md:1` 标题去掉硬编码版本，副标题或首行注改为 "当前版本以 `pyproject.toml` 为准（撰写时 1.9.x）"。
- `requirements.txt:1` 头注同样去掉 `(v0.40)`，改为 "依赖钉版与 `pyproject.toml` 保持一致"。

（选"去硬编码"而非"改成 1.9.54"——避免下次发版再漂移。）

**Verify**: `grep -n "v0.40" docs/contract.md requirements.txt` → 无匹配。

### Step 2: 路径参数名对齐代码

`grep -n "{id}" docs/contract.md docs/api.md` 逐条核对对应路由在 `backend/api/` 的真实签名（如 `backend/api/tasks.py` 的 `{task_id}`、`backend/api/settings.py` 的 `{provider_id}`、`backend/api/experts.py` 的 `{team_id}`），把文档参数名改成与代码一致。仅改路径字符串中的参数名，不动描述文字。

**Verify**: `grep -n "{id}" docs/contract.md docs/api.md` → 无匹配；抽查三条改后的路径与 `grep -n "task_id\|provider_id\|team_id" backend/api/*.py` 的路由一致。

### Step 3: README 测试数表述

`README.md:167` 改为按 CI 口径的诚实表述，例如："后端核心路径有 1700+ 项非网络自动化测试在 Python 3.11 / 3.12 CI 上执行（另有网络标记与探针用例不计入）"。

**Verify**: `grep -n "1800+" README.md` → 无匹配；`python -m pytest tests/ -q -m "not network" --ignore=tests/probes --collect-only 2>/dev/null | tail -1` 的收集数 ≥ 1700 且与新表述兼容。

## Test plan

- 无代码变更，无需新测试。验证即上述 grep/收集命令。
- 全量回归（防御性）：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -n "v0.40" docs/contract.md requirements.txt` 无匹配
- [ ] `grep -n "{id}" docs/contract.md docs/api.md` 无匹配
- [ ] README 测试数与 CI 收集口径一致
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 文档中 `{id}` 对应的某些路由在代码里**确实**叫 `{id}`（逐条核实，不是批量替换——这正是本计划要求逐条核对的原因）。
- contract.md 内容已大幅改写（漂移检查发现摘录对不上）。

## Maintenance notes

- 约定：文档头部不再硬编码版本号，统一"以 pyproject.toml 为准"；发版流程无需再扫文档版本串。
- 测试数这类会自然漂移的指标，长期更好由 CI badge 生成（README badge 区已有 CI 徽章，可加测试数徽章）——超出本计划。
- PR 评审重点：Step 2 逐条核对的记录（commit message 列出改了哪几条路径）。
