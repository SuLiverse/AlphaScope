# AlphaScope 审查收口工程 Implementation Plan

> **For agentic workers:** 分批实现；每批 git commit；批末自审；**功能只增不减**。

**Goal:** 在既有安全/诚实性/高级侧栏收口之上，清掉审查残留债（巨石文件、CI 格式门禁、文档对齐），使 `main` 可持续迭代。

**Architecture:** 不改产品能力面；后端契约与鉴权已定。本阶段以前端量化页拆分、工程门禁、CHANGELOG 为主。Streamlit / 高级模块 / 回测能力全部保留。

**Tech Stack:** Python 3.11+/FastAPI、Vite React 19、pytest、ruff、git

**用户原则（会话约束）:**
- 功能模块不缩减；侧栏可整理到「高级」
- 每批次独立 commit
- 批后自审再继续
- 不推送除非用户明确要求

---

## 状态总览

### 已完成（origin/main..HEAD 基线 + 后续）

| 批次 | Commit 主题 | 状态 |
|------|-------------|------|
| A1 | local token / preview 默认 / 高级侧栏 / SECURITY | ✅ `60f18a2` |
| A2 | 三态 price feed + SyntheticDataBanner | ✅ `6709975` |
| A3 | PreviewOptIn + `_require_bars` | ✅ `35ab762` |
| A4 | runtime_config 共享 + lifespan | ✅ `4c9c077` |
| A5 | StrategyLab preview 对齐 | ✅ `5339fd4` |
| A6 | is_preview 契约 + quant_schemas + quantPreview hook | ✅ `f3119f4` |
| A7 | QuantPreviewCheckbox + lookbackRange | ✅ `0aac336` |

### 本计划待完成 → 已完成

| 批次 | 目标 | 验收 | 状态 |
|------|------|------|------|
| B1 | Backtesting 类型 + 格式工具拆出 | Backtesting 行数明显下降；tsc/行为不变 | ✅ |
| B2 | MetricCard / AssumptionsCard / TradeTable 拆组件 | 同上 | ✅ |
| B3 | pre-commit（ruff check + format） | 配置进仓；本地可跑 | ✅ |
| B4 | CHANGELOG 汇总 v1.9.50 收口说明 + 版本号 | pyproject/web 版本一致 | ✅ |
| B5 | 计划勾选 + 终审清单 | docs 计划更新；测试全绿 | ✅ |

**明确不做（本长期任务边界）:** 实盘、砍功能、重写 Streamlit、全量 except:pass 清零、强制 push。

---

## 文件结构（B1–B2）

```
apps/web/src/
  components/
    Backtesting.tsx              # 编排 + 各 Tab UI（变薄）
    quant/
      QuantPreviewCheckbox.tsx   # 已有
      backtestTypes.ts           # 新建：类型与 Tab 常量
      backtestFormat.ts          # 新建：format* / parsePool
      MetricCard.tsx             # 新建
      AssumptionsCard.tsx        # 新建
      TradeTable.tsx             # 新建
  lib/
    quantDates.ts                # 已有
    quantPreview.ts              # 已有
    priceFeed.ts                 # 已有
```

---

### Task B1: 拆类型与格式工具

**Files:**
- Create: `apps/web/src/components/quant/backtestTypes.ts`
- Create: `apps/web/src/components/quant/backtestFormat.ts`
- Modify: `apps/web/src/components/Backtesting.tsx`（改为 import）

- [ ] **Step 1:** 把 `TabID`、`TABS`、`EXP_MODE_META`、`EVO_METRIC_LABELS`、全部 `interface` 迁到 `backtestTypes.ts` 并 export
- [ ] **Step 2:** 把 `formatExpSummary`、`formatGenome`、`parsePoolText`、`formatFactor`、`formatPercent`、`DEFAULT_POOL_TEXT` 迁到 `backtestFormat.ts`
- [ ] **Step 3:** Backtesting.tsx 改为从 quant/* 导入；确认无重复定义
- [ ] **Step 4:** `npx tsc --noEmit`（apps/web）通过
- [ ] **Step 5:** Commit `refactor(web): extract Backtesting types and format helpers`

---

### Task B2: 拆展示子组件

**Files:**
- Create: `apps/web/src/components/quant/MetricCard.tsx`
- Create: `apps/web/src/components/quant/AssumptionsCard.tsx`
- Create: `apps/web/src/components/quant/TradeTable.tsx`
- Modify: `apps/web/src/components/Backtesting.tsx`

- [ ] **Step 1:** 原样搬迁三组件（保持 className / props）
- [ ] **Step 2:** Backtesting 改 import
- [ ] **Step 3:** tsc 通过；行数目标 Backtesting &lt; 2200
- [ ] **Step 4:** Commit `refactor(web): split Backtesting MetricCard/Assumptions/TradeTable`

---

### Task B3: pre-commit 防 CI format 再红

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `docs/superpowers/plans/2026-07-09-alphascope-review-closeout.md`（勾选）

```yaml
# 使用 ruff 官方 hook；与 CI ruff check + format --check 对齐
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.13
    hooks:
      - id: ruff
        args: [--fix]
        types_or: [python]
      - id: ruff-format
        types_or: [python]
```

- [ ] **Step 1:** 写入配置（ruff 版本对齐 requirements-dev / pyproject）
- [ ] **Step 2:** README 或 CONTRIBUTING 加一句：可选 `pre-commit install`
- [ ] **Step 3:** Commit `chore: add pre-commit ruff hooks to match CI`

---

### Task B4: 版本与 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（顶部 v1.9.50 条目）
- Modify: `pyproject.toml` version
- Modify: `apps/web/package.json` version（及 lock 中 name version 若存在）

- [ ] **Step 1:** 版本 1.9.49 → 1.9.50
- [ ] **Step 2:** CHANGELOG 汇总本线：鉴权默认、合成数据诚实、高级侧栏、is_preview、拆分、pre-commit
- [ ] **Step 3:** Commit `chore: release notes and version 1.9.50 review closeout`

---

### Task B5: 终验

- [ ] **Step 1:** `pytest tests/test_quant_api.py tests/test_local_token_bootstrap.py tests/test_local_api_boundary.py -q`
- [ ] **Step 2:** `ruff check backend/api/quant.py backend/security/`
- [ ] **Step 3:** 更新本计划 checkbox 为完成
- [ ] **Step 4:** 终审摘要写入本文件「终审」节；不自动 push

---

## 终审（完成后填写）

- 功能是否缩减：**否**（高级侧栏仍可达；Streamlit/回测/策略实验室保留）
- 测试：`test_quant_api` + token bootstrap + boundary 全绿；`tsc --noEmit` 通过
- 剩余债：Backtesting 仍约 2k 行（已拆类型/卡片，可再拆 Tab 子页）；Workbench 巨石未动
- 是否 push：仅用户授权后
- 版本：**1.9.50**
