# Plan 019: Prefect 单元测试不再启动真实临时服务器

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- tests/test_workflow_orchestration.py backend/workflow_orchestration.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW（只改测试的桩方式，不动被测模块）
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

装了 mlops 依赖的本地环境里跑全量测试时，`test_workflow_orchestration.py` 会真正调用 `@wo.as_prefect_flow` 装饰的函数——Prefect 引擎随之拉起一个临时服务器进程（`http://127.0.0.1:<随机端口>`），套件尾声被一大段 `--- Logging error ---` / "Stopping temporary server" 堆栈污染（`pytest_out.txt` 末尾即是）。噪音会掩埋真实失败，且测试产生进程级副作用。本计划只处理**测试侧**：在模块自带的 `_prefect_flow`/`_prefect_task` 间接层上打桩，验证"装饰器接线"语义而不再启动引擎。

**明确不在本计划**：`backend/workflow_orchestration.py` 除测试外无任何生产调用方（已核实：`grep -rln "workflow_orchestration" backend/ tests/` 只有测试文件）。它是"接线进产品还是删除"的产品决策，已记入 `plans/README.md` 的 considered 区与 advisor 方向建议，不在此处理。

## Current state

- `tests/test_workflow_orchestration.py:92-115` — Prefect 路径：
  ```python
  prefect_required = pytest.mark.skipif(not wo.is_available("prefect"), reason="prefect 未装")

  @prefect_required
  def test_as_prefect_flow_decorates():
      @wo.as_prefect_flow
      def my_flow(x: int) -> int:
          return x * 2

      result = my_flow(5)      # ← 真跑 prefect 引擎, 拉起临时服务器
      assert result == 10
  ```
- `backend/workflow_orchestration.py:27-42` — 模块的 import-guard 间接层：`from prefect import flow as _prefect_flow` / `task as _prefect_task`，失败时置 None 且 `_PREFECT=False`。`as_prefect_flow`/`as_prefect_task` 基于 `_prefect_flow`/`_prefect_task` 实现（**先 `grep -n "def as_prefect_flow" -A 20 backend/workflow_orchestration.py` 读实现再打桩**）。
- `wo.is_available("prefect")` 依据 `_PREFECT` 标志（跳过逻辑依赖它，保留）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_workflow_orchestration.py -q` | 全部通过 |
| 噪音检查 | `python -m pytest tests/test_workflow_orchestration.py -q 2>&1 \| grep -c "Stopping temporary server"` | `0`（环境装了 prefect 时验证；未装则用例本就 skip） |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `tests/test_workflow_orchestration.py`（Prefect 用例的打桩方式）

**Out of scope**:
- `backend/workflow_orchestration.py` 本体（不改动、不删除、不接线——产品决策另议）。
- dagster/otel 路径的用例（它们不拉起服务器）。
- `pytest_out.txt` 文件本身（本地未跟踪杂物，`plans/016` 已 gitignore）。

## Git workflow

- Branch: `advisor/019-prefect-test-isolation`
- 提交风格：`test(workflow): stub prefect engine in decorator tests to avoid ephemeral server`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 读实现，确定打桩点

`grep -n "def as_prefect_flow\|def as_prefect_task" -A 20 backend/workflow_orchestration.py`。确认 `as_prefect_flow` 是直接返回 `_prefect_flow(fn)` 还是另有包装。桩点选择模块的 `_prefect_flow`/`_prefect_task` 名字（monkeypatch.setattr(wo, "_prefect_flow", fake)），**不要** patch prefect 库内部。

**Verify**: 无命令；把实现形态写进 commit message。

### Step 2: 用假引擎替换真实装饰器

在 Prefect 用例模块级加 fixture（或每个用例内 monkeypatch）：

```python
@pytest.fixture
def fake_prefect(monkeypatch):
    def fake_flow(fn=None, **kwargs):
        def wrap(f):
            def runner(*a, **kw):
                return f(*a, **kw)
            runner.__wrapped__ = f
            return runner
        return wrap(fn) if fn else wrap
    monkeypatch.setattr(wo, "_prefect_flow", fake_flow)
    # _prefect_task 同款
```

（按 Step 1 读到的真实签名调整——若 `as_prefect_flow` 带参数用法 `@as_prefect_flow(name=...)`，fake 也要兼容。）断言保持原义：`my_flow(5) == 10`、task 可调用——语义验证对象是 **wo 的接线**，不再是 prefect 引擎。

**Verify**: `python -m pytest tests/test_workflow_orchestration.py -q` → 全过；装了 prefect 的环境下 `grep -c "Stopping temporary server"` 输出为 `0`。

## Test plan

- 本计划即测试改造本身；验证 = 上述两条命令 + 全量回归。

## Done criteria

- [ ] Prefect 用例在装了 prefect 的环境中不再产生 "temporary server" / "Logging error" 输出
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- `as_prefect_flow` 的实现不经过 `_prefect_flow`（例如 import 时已固化引用）——以实际实现选择桩点；若模块设计使替换不可行，报告并改为在用例内 skip-if-prefect-server 策略（下策，先报告）。
- 打桩后发现用例原本断言的是 prefect 特有行为（如 `.name`/`.fn` 属性）而非接线语义——按真实断言调整，并在报告中说明哪些 prefect 行为因此不再被覆盖。

## Maintenance notes

- 若未来 `workflow_orchestration.py` 接线进产品（API lifespan 注册 tracing 等），应为其写**边界 mock** 的集成测试而不是启动真实引擎——本计划的 fixture 可复用。
- PR 评审重点：fake 是否精确模仿了 `as_prefect_flow` 的两种调用形态（无参/带参）；skipif 逻辑未被破坏（未装 prefect 时用例仍 skip 而非错误）。
- 明确延期：模块生死决策（接线 vs 删除）——见 `plans/README.md` considered 区。
