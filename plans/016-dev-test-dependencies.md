# Plan 016: 补齐测试期依赖声明（httpx/fastapi/pytest-cov）并对齐本地与 CI 的测试口径

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- requirements-dev.txt pyproject.toml Makefile CONTRIBUTING.md .gitignore`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（钉住已实际解析的传递依赖；文档命令对齐 CI）
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

1. **42 个测试文件的生存依赖没有声明**：它们用 `pytest.importorskip("fastapi")` / `importorskip("httpx")` 守护，但 `httpx` 不在任何 requirements 文件或 pyproject extra 里——今天它仅靠 `openai` 的传递依赖解析出来。哪天 openai 调整依赖，42 个 API 测试文件（settings、quant、tasks、SSE 契约、上传安全……）会**静默 skip 而非失败**，套件照样全绿，API 覆盖凭空蒸发。`importorskip` 把缺依赖变成隐形洞。
2. **`make test-cov` 必失败**：Makefile 调 `--cov=backend` 但 `pytest-cov` 不在任何清单。
3. **本地与 CI 口径漂移**：CI 跑 `-m "not network" --ignore=tests/probes`，Makefile/CONTRIBUTING 都没写，本地全量跑会触发那条需要真实网络的用例，离线即红。

## Current state

- `requirements-dev.txt`（全文 9 行）：`-r requirements-core.txt` + `pytest==8.4.0` + `ruff==0.15.13`——无 httpx/fastapi/pytest-cov。
- `pyproject.toml:47` — `dev = ["pytest==8.4.0", "ruff==0.15.13"]`；`:45` api extra 有 `fastapi>=0.115.0,<1.0`（版本区间照抄它）。
- importorskip 面：`grep -rl "importorskip" tests/ | wc -l` → 42（httpx/fastapi 两组）。
- `Makefile:16-19`：`test: python -m pytest tests/ -v`；`test-cov: ... --cov=backend --cov-report=term-missing`。
- `CONTRIBUTING.md:24`：`python -m pytest tests/ -v`。
- CI 口径（`.github/workflows/ci.yml`）：`python -m pytest tests/ -v --tb=short -m "not network" --ignore=tests/probes`。
- 根目录未跟踪杂物：`pytest_out.txt`、`output/`（`git status --short` 可见），`.gitignore` 未覆盖。
- requirements 与 pyproject 的版本一致性是本仓库已核验的整洁点——新增条目要两边同步。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 清单一致性 | `grep -n "httpx\|fastapi\|pytest-cov" requirements-dev.txt pyproject.toml` | 两边都命中 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Makefile 干跑 | `make -n test`（无 make 环境则核对文件文本） | 命令含 `-m "not network"` |

## Scope

**In scope**:
- `requirements-dev.txt`（加 `httpx`、`fastapi`、`pytest-cov`）
- `pyproject.toml`（dev extra 同步三项）
- `Makefile`（test/test-cov 口径）
- `CONTRIBUTING.md`（pytest 命令一处）
- `.gitignore`（加 `pytest_out.txt`、`output/`）

**Out of scope**:
- CI workflow 本身（它已经装了 api 清单且命令正确）。
- 把 importorskip 改成硬 import 的 42 个文件——churn 大收益小；依赖显式声明后守护不再必要但无害。
- 覆盖率门槛（`--cov-fail-under`）——先能跑，再谈门槛。
- 实际 `pip install` 执行——执行者只改清单，安装由人按需进行。

## Git workflow

- Branch: `advisor/016-dev-test-dependencies`
- 提交风格：`build(deps-dev): declare httpx/fastapi/pytest-cov and align local test invocation with CI`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 声明缺失依赖

`requirements-dev.txt` 追加（保持该文件的简洁风格，带一行注释）：

```
httpx>=0.27           # 42 个 API 测试文件 importorskip 依赖; 此前仅靠 openai 传递解析
fastapi>=0.115.0,<1.0 # 与 pyproject api extra 同区间
pytest-cov>=5.0       # Makefile test-cov 目标需要
```

`pyproject.toml` 的 `dev` extra 同步为：`["pytest==8.4.0", "ruff==0.15.13", "httpx>=0.27", "fastapi>=0.115.0,<1.0", "pytest-cov>=5.0"]`。

**Verify**: `grep -n "httpx\|fastapi\|pytest-cov" requirements-dev.txt pyproject.toml` → 两处都命中。

### Step 2: 对齐本地测试口径

- `Makefile`：`test` 目标改为 `python -m pytest tests/ -v -m "not network" --ignore=tests/probes`；`test-cov` 同样补 `-m "not network" --ignore=tests/probes`。
- `CONTRIBUTING.md:24`：命令改为与 CI 相同。

**Verify**: `make -n test` → 输出含 `-m "not network"`；`grep -n "not network" CONTRIBUTING.md` → 命中。

### Step 3: 忽略根目录杂物

`.gitignore` 追加 `pytest_out.txt` 与 `output/`（参照文件内现有分组注释风格放置）。

**Verify**: `git status --short` → 不再出现 `?? pytest_out.txt` / `?? output/`。

### Step 4: 回归

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过（skip 数不应变化——当前环境 httpx/fastapi 本来就在；若 skip 数异常波动，记录并报告）。

## Test plan

- 无新测试（清单/文档变更）。验证即上述命令。

## Done criteria

- [ ] `grep -c "httpx" requirements-dev.txt pyproject.toml` 均 ≥1
- [ ] `make -n test` 输出含 `-m "not network" --ignore=tests/probes`
- [ ] `git status --short` 无 `pytest_out.txt` / `output/`
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `requirements-dev.txt` 或 pyproject dev extra 已含这些条目（漂移检查发现计划过时——直接标记 REJECTED 并说明）。
- 本地 `pip` 解析出新条目与既有钉版的冲突（执行者**不要**现场改其他钉版，记录冲突并报告）。

## Maintenance notes

- 约定：测试 `importorskip` 的第三方包必须出现在 dev 清单——评审新增 importorskip 时同步检查。
- 后续可考虑给 CI 加一条"skip 数阈值"守卫（skip 突增即失败），把隐形洞彻底堵死；超出本计划。
- PR 评审重点：fastapi 区间与 api extra 严格一致，避免双源漂移（本仓库 requirements/pyproject 零漂移是已验证的优点，保持）。
