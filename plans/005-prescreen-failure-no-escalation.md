# Plan 005: Auto 模式预筛失败时降级返回，不再升级全量 DEEP 分析

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 98478de..HEAD -- backend/runtime/orchestrator.py backend/agent_modes.py tests/test_runtime_orchestrator.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW（只改失败路径行为）
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `98478de`, 2026-07-27

## Why this matters

Auto 模式先做快速预筛（单次 LLM 调用），置信度落在升级带 `[escalate_below, escalate_above]`（默认 [30, 70]）内才升级全量多 Agent DEEP 分析。但预筛**抛异常**时，`except` 分支把 `pre_confidence` 设为 50——恰好落在升级带中央。Provider 挂掉/配置错误（预筛失败的最常见原因）时，Auto 模式会再烧一整轮 DEEP（所有 Agent 用同一个坏 Provider 再失败一遍），延迟、费用、限流压力全部乘上 Agent 数量，最后才返回失败。失败应当就地降级返回，而不是升级。

## Current state

- `backend/runtime/orchestrator.py:1026-1039` — 预筛调用与异常分支：
  ```python
  try:
      ...  # 预筛 LLM 调用
      pre_result = _extract_json(text)
      pre_signal = pre_result.get("signal", "观望")
      pre_confidence = int(pre_result.get("confidence", 50))
      pre_reason = pre_result.get("reason", "")
  except Exception as e:
      pre_signal = "观望"
      pre_confidence = 50
      pre_reason = f"预筛失败: {e}"
  ```
- `backend/runtime/orchestrator.py:1041-1042` — 升级判定（条件为真 = 不升级、直接返回预筛结果）：
  ```python
  # Check if escalation is needed
  if pre_confidence < config.escalate_below or pre_confidence > config.escalate_above:
  ```
  条件为假（置信度落入 [30,70]）时执行 :1094-1101 的 `run_agents_with_mode(..., mode=AnalysisMode.DEEP, ...)`，并标 `auto_escalated: True`。
- `backend/agent_modes.py:74-75` — 默认值：`escalate_below: int = 30`、`escalate_above: int = 70`。50 在带内 ⇒ 失败必升级。
- 直接返回分支（:1043-1092）构造的响应形状：`{"agents": {...}, "summary": {...}, "brief", "agent_order": ["pre_screen"], "critic": None, "chairman_summary": None, "evidence_pool": [], "research_trust": ..., "research_snapshot": ..., "risk_gate": None, "data_verification": verification.to_dict(), "mode": "auto", "mode_name": "自动模式 (预筛直接输出)", "auto_escalated": False, "pre_screen_result": {...}}`。**降级返回复用这个形状**，只改 `mode_name` 与预筛字段，前端契约不变。
- 测试：`tests/test_runtime_orchestrator.py` 已存在（先读，沿用其 mock 编排方式）。

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| 目标测试 | `python -m pytest tests/test_runtime_orchestrator.py -q` | 全部通过 |
| 全量回归 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**In scope**:
- `backend/runtime/orchestrator.py`（仅 auto 预筛函数内）
- `tests/test_runtime_orchestrator.py`（追加用例）

**Out of scope**:
- `backend/agent_modes.py` 的阈值默认值——30/70 的产品语义不变。
- DEEP 模式本身的降级策略、Agent 级重试——别的问题域。
- 预筛 prompt 或 `_extract_json` 的健壮性改进。

## Git workflow

- Branch: `advisor/005-prescreen-failure-no-escalation`
- 提交风格：`fix(runtime): degrade auto-mode pre-screen failures instead of escalating to DEEP`
- 不要 push、不要开 PR，除非操作者明确指示。

## Steps

### Step 1: 标记预筛失败

`backend/runtime/orchestrator.py` 预筛 `try/except` 之前加 `pre_screen_failed = False`；`except` 分支内置 `True`（其余赋值不变）。

**Verify**: `ruff check backend/runtime/orchestrator.py` → exit 0。

### Step 2: 失败时短路降级返回

在 :1041 升级判定**之前**插入：`if pre_screen_failed:` 走与 :1043-1092 相同的预筛直出响应（复用同一构造代码——把 :1043-1092 的响应构造提取为局部变量/内联函数供两处使用，避免复制粘贴两大段；若提取导致 diff 过大，允许直接复制构造块，但必须在两处之间加注释互相指引）。差异点：`mode_name` 改为 `"自动模式 (预筛失败, 已降级)"`，`pre_screen_result` 沿用含 `预筛失败: {e}` 的 `pre_reason`，`auto_escalated: False`。

**Verify**: `python -m pytest tests/test_runtime_orchestrator.py -q` → 既有用例全过。

### Step 3: 回归测试

`tests/test_runtime_orchestrator.py` 追加用例：mock 预筛 LLM 调用抛异常（参照文件内既有 mock 方式），断言：
- 返回 `auto_escalated is False`；
- `mode_name` 含"降级"；
- `run_agents_with_mode` 未被以 `AnalysisMode.DEEP` 调用（用 mock 的 call 参数断言）；
- `pre_screen_result.reason` 含"预筛失败"。

再加一个对照用例：预筛正常返回 confidence=50（模糊结论）时**仍然升级** DEEP（防止把正常升级路径一起短路）。

**Verify**: `python -m pytest tests/test_runtime_orchestrator.py -q` → 全过，新增 2 个用例。

## Test plan

- 见 Step 3。结构参照 `tests/test_runtime_orchestrator.py` 既有用例。
- 全量回归：`python -m pytest tests/ -q -m "not network" --ignore=tests/probes` → 全过。

## Done criteria

- [ ] 预筛异常路径不再调用 DEEP（新测试断言）
- [ ] 正常模糊置信度（50）仍触发升级（对照测试断言）
- [ ] `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` 全过
- [ ] `ruff check backend frontend tests && ruff format --check backend frontend tests` exit 0
- [ ] `git status` 无 scope 外文件
- [ ] `plans/README.md` 状态行已更新

## STOP conditions

- 预筛失败语义被上游（API 层/前端）依赖为"必出 DEEP 结果"（检查 `backend/api/` 中 auto 模式调用方与前端 `apps/web/src` 对 `auto_escalated` 的消费——若前端对降级态没有展示路径，记录后再继续，通常按现有 `source_status`/`error` 惯例展示即可）。
- :1043-1092 的响应构造与"Current state"描述差异大到无法复用。

## Maintenance notes

- 未来若给预筛增加"重试一次"逻辑，失败标记应在重试耗尽后再置位。
- PR 评审重点：降级响应与直出响应的构造是否真正同源（避免两处漂移）；`mode_name` 文案改动对前端展示的影响（前端按字符串展示，无枚举依赖——确认 `apps/web/src` 无对 `"预筛直接输出"` 的硬匹配）。
- 关联：Auto 模式的成本/延迟还可由真流式进一步改善，见 advisor 报告的方向建议（不在本批计划内）。
