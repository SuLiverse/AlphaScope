# Plan 015: 拆除四个模块 import 时的全进程 warnings 静默

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/news_data.py backend/fundamentals.py backend/fund_flow.py backend/providers/akshare_provider.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW-MED（真实警告会重新出现在日志里；个别 akshare 调用点如确实刷屏，按 Step 2 局部收敛）
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

四个模块在 **import 时**执行 `warnings.filterwarnings("ignore")`——这是进程级全局副作用：任何模块 import 它们之后，整个 Python 进程的所有警告类别（DeprecationWarning、FutureWarning、ResourceWarning……）被无差别静默。它掩盖的东西包括：pandas 3.0 迁移警告（仓库钉了 `pandas==3.0.3`，正需要这些警告来发现兼容问题）和未关闭资源的 ResourceWarning（ Plans 010/011 修的两类泄漏本可由它提前暴露）。警告治理应该发生在调用点，而不是 import 时污染全局。

## Current state

四处模块级调用（`import warnings` 后紧跟裸 `warnings.filterwarnings("ignore")`，无任何条件）：

- `backend/news_data.py:19-21`
- `backend/fundamentals.py:13-14` 一带
- `backend/fund_flow.py:8-9` 一带
- `backend/providers/akshare_provider.py:9-10` 一带

（行号以 `grep -n "filterwarnings" backend/news_data.py backend/fundamentals.py backend/fund_flow.py backend/providers/akshare_provider.py` 实测为准。）历史动机几乎可以确定是压 akshare/pandas 的刷屏警告；`pyproject.toml:119` 在 pytest 层已有 `filterwarnings = ["ignore::DeprecationWarning"]`（测试输出的既有治理，不受影响）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_news_data.py tests/test_fundamentals.py tests/test_fund_flow_api.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- 上述四个模块（删除模块级 filterwarnings；必要时在个别调用点加 `warnings.catch_warnings()` 局部收敛）
- `tests/test_no_global_warning_suppression.py`（新建）

**Out of scope**:
- 修任何因此暴露的第三方库警告本身（属于各依赖的事）。
- `pyproject.toml` 的 pytest filterwarnings 配置。
- 其他模块的 logging 配置。

## Git workflow

- Branch: `advisor/015-scope-warning-filters`
- 提交风格：`fix(core): remove import-time global warnings suppression from four modules`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 删除模块级静默

四处 `warnings.filterwarnings("ignore")` 连同失去用途的 `import warnings` 一并删除（若模块内另有 warnings 的正当使用则保留 import）。

**Verify**: `grep -rn "warnings.filterwarnings" backend/ frontend/` → 无匹配。

### Step 2: 运行并观察警告面

`python -m pytest tests/ -q -m "not network" --ignore=tests/probes 2>&1 | tee /tmp/pytest_after.txt | tail -3`（Windows 下用 `%TEMP%` 路径亦可），再 `grep -c "Warning" /tmp/pytest_after.txt`。

- 若某个 akshare/pandas 调用点产生**可复现的刷屏**（同类警告几十条以上、源自仓库自己的调用而非依赖内部）：在该调用点用
  ```python
  with warnings.catch_warnings():
      warnings.simplefilter("ignore", <具体类别>)
      <akshare 调用>
  ```
  局部收敛，并加注释注明动机与警告类别。**只收敛具体类别**（如 `FutureWarning`），不得再出现裸 `simplefilter("ignore")`。
- 若没有明显刷屏：什么都不加，直接进 Step 3。

**Verify**: `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过（pytest 的 `-W` 默认不因警告失败；若仓库配置使警告变错误，按上一条处理刷屏点后重跑）。

### Step 3: 防回归测试

新建 `tests/test_no_global_warning_suppression.py`：对每个目标模块，先 `sys.modules.pop` 干净后 `importlib.import_module` 重新导入，断言 `warnings.filters[0]` 不是裸全局静默（`("ignore", None, Warning, None, 0)` 形态）：

```python
BARE_IGNORE = ("ignore", None, Warning, None, 0)

@pytest.mark.parametrize("module", ["backend.news_data", "backend.fundamentals", "backend.fund_flow", "backend.providers.akshare_provider"])
def test_import_does_not_silence_warnings(module):
    ...
```

（导入副作用重的模块注意：这四个都是数据访问模块，导入本身不发网络请求——若发现某模块 import 时有重副作用，从参数列表去掉它并在报告说明。）

**Verify**: `python -m pytest tests/test_no_global_warning_suppression.py -q` → 4 用例全过。

## Test plan

- 见 Step 3。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] `grep -rn "warnings.filterwarnings" backend/ frontend/` 无匹配
- [ ] `grep -rn "simplefilter(\"ignore\")" backend/ frontend/` 无匹配（只允许带类别的 `simplefilter("ignore", SomeWarning)`）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 删除后全量测试出现与警告相关的**失败**（而非刷屏）——说明有代码路径依赖被静默的行为，定位并报告，不要为过关把全局静默加回去。
- 某模块 import 副作用超出预期（发网络/连库），导致 Step 3 测试无法安全重导入——按 Step 3 的排除条款处理并记录。

## Maintenance notes

- 约定：警告治理只能在调用点用 `catch_warnings` + 具体类别；新增模块级 `filterwarnings` 应被评审拦截（本计划的测试兜底）。
- 暴露出的 pandas 3.0 DeprecationWarning 值得另开技术债逐项清理（不在本计划）。
- PR 评审重点：Step 2 的判断要有证据（pytest 输出中警告计数写进 commit message）。
