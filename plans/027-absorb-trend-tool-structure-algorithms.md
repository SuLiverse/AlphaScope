# Plan 027: 汲取买卖点工具的结构算法（不搬综合打分）

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> ```
> git diff --stat HEAD -- backend/quant/strategies/turtle.py backend/quant/patterns.py backend/indicators.py backend/quant/factor_registry.py backend/agents/quant_referee.py backend/api/quant_core.py backend/api/quant.py prompts/experts/chanlun.md
> ```
> If any in-scope file changed since this plan was written (planned at
> `c8fb531` / v1.9.55), compare the "Current state" excerpts against live
> code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L（建议拆 4 个 commit，不要一次巨型 PR）
- **Risk**: MED（海龟参数变化会改回测数字；缠论/形态只标注不决策，风险低）
- **Depends on**: none（v1.9.55 已在 `main`）
- **Category**: feature
- **Planned at**: commit `c8fb531` (v1.9.55), 2026-08-13

## Why this matters

工作区里有一套独立商业看板
`D:\AI-Finance\趋势分析实时买卖点工具-v4.0-发行版`。
它的**产品层**（五维加权、强烈买入、固定 5% 止损、假 CAN SLIM、中文关键词否决）
和 AlphaScope 红线冲突，**不要搬**。

它真正值得要的是三条**可检验的结构算法**，主项目现在没有对等实现：

1. **海龟原版细节**：System1/2、ATR 的 N、2N 止损、0.5N 加仓。主项目
   `turtle.py` 只有「收盘破 20 日高 / 跌破 10 日低」。
2. **缠论几何引擎**：合并 K → 分型 → 笔 → 中枢 → MACD 面积背驰。主项目只有
   `prompts/experts/chanlun.md` 人设，LLM 会编中枢。
3. **收紧后的箱体 / 头肩 / 杯柄**：主项目 `patterns.py` 已有蜡烛+双顶双底，
   缺可单测的大结构；买卖点工具的实现太松（近 20 日高低点×0.98、柄低点用全局最低）。

**不要新建 `backend/algorithms/`。** 主项目扩展方式已经是：
`strategies/` 一文件一策略、`patterns.py` 结构识别、`factor_registry.py` 因子、
`quant_referee.py` 规则对照。再开第三套入口会重复买卖点工具的「五个相关模块加出一个分数」。

## Current state

- `backend/quant/strategies/turtle.py` — `default_params = {entry_period: 20, exit_period: 10, position_size_pct: 20}`。
  `generate_signals` 用 `close > max(highs[i-entry:i])` 买、`close < min(lows[i-exit:i])` 卖。
  **必须** `assert len(signals) == len(bars)`（plan 003 契约：`signals[i]` 对应 bar `i`，成交在 `i+1` 开盘）。
- `backend/quant/engine.py` — T 日信号 T+1 开盘成交；A 股 T+1 结算、印花税、滑点、涨跌停。
  海龟加仓/止损必须走这条引擎，不能在策略里假装成交。
- `backend/quant/patterns.py` — `detect_patterns(bars, symbol, lookback)` → `PatternReport`；
  方向只标 `bullish|bearish|neutral`；免责写死在 `_DISCLAIMER`。
  API：`backend/api/quant_core.py:676` `_run_patterns_local`。
- `backend/indicators.py` — MA / MACD / RSI / KDJ / 量比 / 支撑压力。**没有 ATR、没有唐奇安。**
- `backend/quant/factor_registry.py` — 有 `mom_20` / `ma20_gap` / `rsi_14` 等，**没有 `atr_20` / `donchian_width_20`。**
- `backend/agents/quant_referee.py` — 均线排列 / RSI / MACD 对照轨，不发买卖指令。
- `prompts/experts/chanlun.md` — 要求专家「给出明确入场点和止损位」。几何引擎落地后必须改掉这句话。
- 买卖点工具参考实现（只读，禁止整文件复制进主树）：
  - `D:\AI-Finance\趋势分析实时买卖点工具-v4.0-发行版\analysis\breakout_module.py`（海龟 N / 2N / 双系统；注意它跟踪空头，A 股默认禁止）
  - `...\analysis\chanlun_daily.py`（管线可用；中枢用「相邻两笔重叠」——主项目必须改成至少三段重叠）
  - `...\analysis\pattern_module.py`（箱体/头肩/杯柄规则太松，只作几何参考）
  - **不要读、不要抄** `signal_engine.py` 的加权合成、`app.py` 的关键词否决、`canslim_module.py`。

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| 海龟+走查 | `python -m pytest tests/test_strategies_catalogue.py tests/test_backtest_engine.py tests/test_walk_forward.py tests/test_quant_api.py -q` | 全部通过 |
| 形态+指标 | `python -m pytest tests/test_patterns.py tests/test_indicators.py -q` | 全部通过（含新增用例） |
| 缠论 | `python -m pytest tests/test_chanlun.py -q` | 全部通过 |
| Referee | `python -m pytest tests/test_quant_referee.py -q` | 全部通过 |
| 全量 | `python -m pytest tests/ -q -m "not network" --ignore=tests/probes` | 全部通过 |
| Lint | `ruff check backend frontend tests` | exit 0 |
| Format | `ruff format --check backend frontend tests` | exit 0 |

## Scope

**做：**

1. 升级现有 `turtle` 策略（同一注册名，参数化，默认行为向后可解释）。
2. `indicators.py` + `factor_registry.py` 增加 ATR / 唐奇安宽度。
3. 新建 `backend/quant/chanlun.py`（风格对齐 `patterns.py` / `chip_distribution.py`）+ `POST /api/quant/chanlun`。
4. 收紧后的箱体 / 头肩 / 杯柄并入 `patterns.py`。
5. 缠论结果注入专家简报；改 `prompts/experts/chanlun.md`。
6. 可选最后一步：`strategies/chanlun_structure.py` 只把**一条**可执行规则送进回测引擎。

**不做（STOP 如果开始做这些）：**

- 新建 `backend/algorithms/` 或搬运 `signal_engine.run_analysis`
- 「强烈买入 / 谨慎买入 / 操作计划 / 仓位 1/4」产品层
- 假 CAN SLIM（涨幅冒充盈利和机构）
- 中文关键词硬否决
- 固定 5% 止损、固定「中线 1–3 月」
- 全 A 扫描买入前 20
- 把空头平仓映射成买入（买卖点工具的做法；A 股默认禁止空头）
- 改 LLM 编排主路径、加 LangGraph、改前端设计系统

## 产品契约（每条新代码必须遵守）

- 纯函数、失败安全、不触网。
- 策略：`signals[i]` 只用 `bars[:i+1]` 里 bar `i` 及更早的数据；`len(signals)==len(bars)`。
- 识别器 / 因子：描述历史结构，方向只是口径，**不构成买卖建议**。
- 回测数字变化必须在 commit message 和 CHANGELOG 里写明「数字会变」。
- 每个新规则先写失败测试再实现（先红后绿）。

---

## Step 0 — 定向阅读（不改代码）

读完再动手：

1. `backend/quant/strategies/base.py` + `turtle.py` + `tests/test_strategies_catalogue.py`
2. `backend/quant/patterns.py` 末尾 `detect_patterns` + `tests/test_patterns.py`
3. `backend/quant/chip_distribution.py` 的 report / disclaimer 形状（缠论模块照抄这个外壳）
4. `backend/api/quant.py` 里 patterns 路由怎么挂的（缠论抄同一模式）
5. 买卖点工具三个参考文件（见 Current state），只记公式，不复制产品包装

记录：主项目 patterns 路由的 HTTP 方法/路径、Request body 字段名。后续缠论 API 必须同形。

## Step 1 — 海龟补全（第一个 commit）

**目标：** 现有 `name="turtle"` 增加可选原版细节，默认仍防未来函数。

`default_params` 扩成：

```python
default_params = {
    "entry_period": 20,       # System 1
    "exit_period": 10,
    "system2_period": 55,     # 0 = 关闭 System 2
    "use_atr_stop": False,    # 默认关，保持旧回测可比
    "atr_period": 20,
    "stop_n_mult": 2.0,
    "pyramid": False,         # 默认关
    "pyramid_step_n": 0.5,
    "max_units": 4,
    "allow_short": False,     # A 股默认禁止
    "position_size_pct": 20,
}
```

实现约束：

- ATR / N：`TR = max(H-L, |H-PDC|, |L-PDC|)`；`N` = 前 `atr_period` 根 TR 的 SMA，**不含当日**（买卖点工具 `calc_n` 含当日，主项目不要学）。
- 入场通道：**不含当日**（现有 `highs[i-entry:i]` 已对）。
- `use_atr_stop=True` 时：持仓中收盘跌破 `entry - 2N` 发 `sell`（多头）。不要在策略里改成交价。
- `pyramid=True` 时：价格每上涨 `0.5N` 再发一次 `buy`（单位数 ≤ `max_units`）。引擎会按 T+1 成交；reason 写清「加仓 第 k 单位」。
- `system2_period>0`：55 日突破作为**额外入场规则**（仍只发 buy/sell/hold），与 System1 共用同一信号序列，不要注册第二个策略名。
- `allow_short=False`：忽略向下突破的空头开仓；禁止把「空头平仓」写成 buy。

测试（新建 `tests/test_turtle_params.py` 或扩目录测试）：

1. 默认参数：与升级前同一组 SAMPLE_BARS，buy/sell 位置不变（锁回归）。
2. 通道不含当日：构造「仅当日创新高」的序列，当日必须是 hold。
3. ATR 止损：人造序列入场后收盘跌破 entry-2N，必须出现 sell。
4. `allow_short=False`：大阴线跌破下轨不得出现 sell-to-open 之外的空头语义（只允许平多）。
5. `len(signals)==len(bars)`。

验证：Step 表格里「海龟+走查」命令全绿。

Commit：`feat(quant): optional ATR stop and dual Donchian on turtle strategy`

## Step 2 — ATR / 唐奇安进指标和因子（第二个 commit）

`backend/indicators.py` 增加：

- `calc_atr(bars, period=20) -> list[dict]` 每根 bar 带 `atr`（不足 period 为 0 / 跳过）
- `calc_donchian(bars, period=20) -> list[dict]` 带 `donchian_high` / `donchian_low` / `donchian_width`（通道不含当日）

`calc_all` 若存在，按现有风格接入，不要破坏已有字段。

`factor_registry.py` 登记：

- `atr_20`：20 日 ATR / close，单位 `%` 或价格，`direction=0`
- `donchian_width_20`：(上轨-下轨)/close，`direction=0`

测试扩 `tests/test_indicators.py`：不足 period、含当日高点不得泄漏进通道。

Commit：`feat(quant): add ATR and Donchian width indicators and factors`

## Step 3 — 缠论结构引擎 + API（第三个 commit，本计划主体）

新建 `backend/quant/chanlun.py`，对外：

```python
def analyze_chanlun(bars: list[dict], symbol: str = "") -> ChanlunReport:
    ...
```

`ChanlunReport` 至少含：`status` (`ok|insufficient`)、`symbol`、`bars_used`、
`fractals`、`strokes`、`zhongshus`、`divergences`、`note`、`disclaimer`。
disclaimer 必须写：描述历史走势结构，不预测、不构成买卖建议。

算法要求（相对买卖点工具的修正）：

| 步骤 | 主项目必须 | 买卖点工具不要学 |
|------|------------|------------------|
| 合并 K | 包含关系合并，方向继承 | — |
| 分型 | 合并 K 上顶/底分型 | — |
| 笔 | 分型间合并 K 索引差 ≥ 4 | — |
| **中枢** | **至少三段重叠**（经典：离开后连续三笔有重叠区间） | 相邻两笔有交集就算中枢 |
| 背驰 | MACD 柱面积衰减 + 价格新极值；标在笔上 | 可参考面积公式，但置信度数字不要包装成「买入把握」 |
| 一二三类点 | 先做成**可选标注字段** `signals: list[{type, date, price, note}]` | 不要在 API 顶层输出 action=买入 |

失败安全：bars < 10 或脏 OHLC → `status=insufficient`，空列表，不抛。

API：照抄 patterns 的挂法。

- `backend/api/quant.py` 增加 `POST /api/quant/chanlun`（body 与 patterns 同形：symbol / start / end / lookback）
- `quant_core.py` 增加 `_run_chanlun_local`，用 `_require_bars` + `analyze_chanlun`

测试 `tests/test_chanlun.py`（人造序列，不要打网）：

1. 不足 K 线 → insufficient
2. 简单上升三段：能检出笔，中枢在该有重叠时出现、无重叠时不出现
3. 两笔重叠**不足以**单独成中枢（锁住对买卖点工具简化的拒绝）
4. `to_dict()` 含 disclaimer
5. 确定性：同一 bars 两次调用结果相等

前端：本计划**不强制**做完整缠论图层。最低要求是 API 可调用。若改 `MultimodalChart.tsx` / 交互 K 线，只叠加笔和中枢矩形，文案用「结构标注」不要「买卖点」。做 UI 则桌面+窄屏各看一次；没浏览器就写明未验证 UI。

Commit：`feat(quant): deterministic Chanlun structure annotator`

## Step 4 — 注入缠论专家 + 收紧大形态（第四个 commit）

**4a. Prompt**

改 `prompts/experts/chanlun.md`：

- 删「给出明确入场点和止损位」
- 改为：只解释引擎给出的分型/笔/中枢/背驰；止损描述用「中枢沿」，不另造点位；无引擎结果时明确说「无几何结构，不编造」

**4b. 简报注入**

找到分析路径里给专家拼 brief 的位置（`backend/runtime/orchestrator.py` / `backend/expert_panel.py` / `backend/api/analysis_stock_data.py` 之一）。
在**已有行情之后、LLM 调用之前**，若 `analyze_chanlun` 成功，把中枢区间、最近笔方向、是否标背驰写成一段纯文本塞进缠论专家的输入。
失败则不注入、不阻断。不要为了注入去新增 LLM Agent。

**4c. patterns.py 扩结构**

只收可单测几何，置信度不要写进综合分（本模块本来就没有综合分）：

- **箱体**：窗口内上沿被触及 ≥2 次、下沿 ≥2 次、振幅有上下界；「接近上沿」用收盘距上沿比例，禁止「近 20 日最高×0.98 就算看涨突破」
- **头肩**：左右肩对称（价差阈值写死）、头比两肩更极端、颈线定义写死
- **杯柄**：柄必须落在杯右沿之后的子区间；禁止用「最近 20 日全局最低」当柄低

每个形态一条先红后绿测试。方向仍只标 bullish/bearish/neutral。目标价若输出，字段名叫 `projection`，detail 写「几何投影不是预测」。

Commit：`feat(research): feed Chanlun geometry to expert brief and tighten structure patterns`

## Step 5 — 可选：一条可回测的缠论规则

仅当 Step 3 测试全绿且你还有时间。否则标为未做，不要半套策略。

新建 `backend/quant/strategies/chanlun_structure.py`，`name="chanlun_structure"`：

- **唯一入场：** 中枢向上突破后，回抽笔结束价仍在中枢上沿之上 → 该 bar `buy`
- **唯一出场：** 收盘跌回中枢区间 → `sell`
- 其它时刻 `hold`
- 信号序列仍满足 plan 003 契约

跑一次 `walk_forward` + 默认回测，把数字写进 `progress` / commit body。证明不了稳健就保持「只标注」，不要把策略设为 UI 默认。

Commit：`feat(quant): optional Chanlun structure breakout strategy`

## Step 6 — 文档与收尾

- `CHANGELOG.md` 顶部加一条（不要擅自 bump 版本号，除非用户要求发版）
- `docs/technical-analysis.md` 补 ATR / 唐奇安 / 缠论 API 各一段
- `plans/README.md` 本行改为 DONE，写分支名和测试结果

不要改 README 徽章版本。

## STOP conditions

- 发现自己在实现「综合分 / 强烈买入 / 操作计划」——停，删掉，回到本计划 Scope。
- `generate_signals` 长度不等于 `len(bars)`，或用了当日未来 bar。
- 缠论中枢做成了「两笔重叠」。
- 为过测试去改 plan 003 的成交契约。
- 全量测试红且原因不是本计划改动面——停，报告，不要顺手修无关失败。
- 买卖点工具 `license_core.py` / 许可证绕过——禁止改、禁止讨论进主项目。

## Done when

- [ ] turtle 默认回归锁住；新参数有单测
- [ ] ATR / 唐奇安在 indicators + factor catalog
- [ ] `analyze_chanlun` + `POST /api/quant/chanlun` + `tests/test_chanlun.py`
- [ ] 中枢至少三段重叠，有拒绝两笔中枢的测试
- [ ] 缠论专家 prompt 不再要求「明确入场点」；brief 能注入几何结果
- [ ] 箱体/头肩/杯柄规则收紧并单测
- [ ] ruff check/format + 全量 `not network` 测试通过
- [ ] CHANGELOG 已记；本 plan 状态 DONE
- [ ] （可选）`chanlun_structure` 策略存在且可走查
