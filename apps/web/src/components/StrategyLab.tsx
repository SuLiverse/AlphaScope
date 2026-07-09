/**
 * StrategyLab — 低代码策略编辑器(v1.9.4, 1.txt + deep-research)。
 *
 * 用「字段 + 操作符 + 阈值」无代码组合买卖信号, 编译成后端 custom_rule 策略的
 * params, 复用现有 /api/quant/backtest 与回测引擎(不新建引擎)。内置模板卡、
 * 自定义保存、AI 规则导入, 三类标签 builtin / custom / ai。
 */
import { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import {
  Beaker,
  Bot,
  Play,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { fetchApi } from '../lib/api';
import { getErrorMessage } from '../lib/dataFetch';
import { useQuantPreviewOptIn } from '../lib/quantPreview';
import { getPersistedStock } from '../lib/workspaceEvents';
import { ThemedSelect } from './ThemedSelect';

// 与后端 backend/quant/strategies/custom_rule.py FIELD_CATALOG 对齐。
const FIELD_CATALOG: Record<string, string> = {
  close: '收盘价',
  pct_change: '当日涨跌幅%',
  rsi: 'RSI(14)',
  macd_hist: 'MACD 柱(DIF-DEA)',
  dif: 'DIF',
  dea: 'DEA',
  vol_ratio: '量比(量/5日均量)',
  close_vs_ma5_pct: '现价距MA5 %',
  close_vs_ma20_pct: '现价距MA20 %',
  close_vs_ma60_pct: '现价距MA60 %',
  ma5_vs_ma20_pct: 'MA5距MA20 %(>0金叉态)',
  ma10_vs_ma20_pct: 'MA10距MA20 %',
  drawdown_from_high_pct: '距区间高点回撤 %',
};

const OPS = ['>', '>=', '<', '<='] as const;

type Tag = 'builtin' | 'custom' | 'ai';

interface Rule {
  field: string;
  op: string;
  value: number;
}

interface StrategyDraft {
  name: string;
  tag: Tag;
  buy_rules: Rule[];
  sell_rules: Rule[];
  logic: 'and' | 'or';
  position_size_pct: number;
}

interface SavedStrategy extends StrategyDraft {
  id: string;
  created_at: number;
}

interface BacktestMetrics {
  total_return?: number;
  annual_return?: number;
  max_drawdown?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  trade_count?: number;
  final_equity?: number;
}

interface BacktestResult {
  metrics?: BacktestMetrics;
  assumptions?: { note?: string; t_plus_1?: boolean };
  summary?: { data_source_label?: string; bar_count?: number };
}

// 内置规则模板(标签 builtin)——可加载后再改。
const PRESETS: StrategyDraft[] = [
  {
    name: 'RSI 超卖反弹',
    tag: 'builtin',
    buy_rules: [{ field: 'rsi', op: '<', value: 30 }],
    sell_rules: [{ field: 'rsi', op: '>', value: 70 }],
    logic: 'and',
    position_size_pct: 20,
  },
  {
    name: '均线金叉',
    tag: 'builtin',
    buy_rules: [{ field: 'ma5_vs_ma20_pct', op: '>', value: 0 }],
    sell_rules: [{ field: 'ma5_vs_ma20_pct', op: '<', value: 0 }],
    logic: 'and',
    position_size_pct: 25,
  },
  {
    name: '放量突破',
    tag: 'builtin',
    buy_rules: [
      { field: 'vol_ratio', op: '>', value: 1.5 },
      { field: 'pct_change', op: '>', value: 3 },
    ],
    sell_rules: [{ field: 'close_vs_ma20_pct', op: '<', value: -3 }],
    logic: 'and',
    position_size_pct: 20,
  },
  {
    name: '回调买入(趋势中低吸)',
    tag: 'builtin',
    buy_rules: [
      { field: 'close_vs_ma60_pct', op: '>', value: 0 },
      { field: 'close_vs_ma20_pct', op: '<', value: -5 },
    ],
    sell_rules: [{ field: 'drawdown_from_high_pct', op: '<', value: -12 }],
    logic: 'and',
    position_size_pct: 20,
  },
];

const STORAGE_KEY = 'alphascope.customStrategies';

function loadSaved(): SavedStrategy[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SavedStrategy[]) : [];
  } catch {
    return [];
  }
}

function persistSaved(list: SavedStrategy[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* localStorage 不可用时静默(隐私模式) */
  }
}

function pct(v?: number): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(2)}%`;
}

const TAG_STYLE: Record<Tag, string> = {
  builtin: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  custom: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  ai: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30',
};
const TAG_LABEL: Record<Tag, string> = { builtin: '内置', custom: '自建', ai: 'AI' };

function emptyDraft(): StrategyDraft {
  return {
    name: '我的策略',
    tag: 'custom',
    buy_rules: [{ field: 'rsi', op: '<', value: 30 }],
    sell_rules: [{ field: 'rsi', op: '>', value: 70 }],
    logic: 'and',
    position_size_pct: 20,
  };
}

export function StrategyLab() {
  const [draft, setDraft] = useState<StrategyDraft>(emptyDraft);
  const [saved, setSaved] = useState<SavedStrategy[]>(() => loadSaved());
  const [symbol, setSymbol] = useState<string>(() => getPersistedStock()?.symbol?.replace(/\..*$/, '') || '600519');
  const [days, setDays] = useState(180);
  const [capital, setCapital] = useState(100000);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const { allowPreviewData, setAllowPreviewData, previewBody } = useQuantPreviewOptIn(false);
  const [aiText, setAiText] = useState('');
  const [aiOpen, setAiOpen] = useState(false);

  useEffect(() => {
    persistSaved(saved);
  }, [saved]);

  const fieldOptions = useMemo(
    () => Object.entries(FIELD_CATALOG).map(([value, label]) => ({ value, label })),
    [],
  );
  const opOptions = useMemo(() => OPS.map((o) => ({ value: o, label: o })), []);

  const updateRule = (kind: 'buy_rules' | 'sell_rules', idx: number, patch: Partial<Rule>) => {
    setDraft((d) => {
      const rules = d[kind].slice();
      rules[idx] = { ...rules[idx], ...patch };
      return { ...d, [kind]: rules };
    });
  };
  const addRule = (kind: 'buy_rules' | 'sell_rules') =>
    setDraft((d) => ({ ...d, [kind]: [...d[kind], { field: 'close', op: '>', value: 0 }] }));
  const removeRule = (kind: 'buy_rules' | 'sell_rules', idx: number) =>
    setDraft((d) => ({ ...d, [kind]: d[kind].filter((_, i) => i !== idx) }));

  const loadDraft = (d: StrategyDraft) =>
    setDraft({ ...d, buy_rules: d.buy_rules.map((r) => ({ ...r })), sell_rules: d.sell_rules.map((r) => ({ ...r })) });

  const saveDraft = (tag: Tag = 'custom') => {
    const id = `${Date.now()}-${Math.floor(Math.random() * 1e4)}`;
    const entry: SavedStrategy = { ...draft, tag, id, created_at: Date.now() };
    setSaved((s) => [entry, ...s.filter((x) => x.name !== draft.name)].slice(0, 30));
    setMessage(`已保存策略「${draft.name}」(${TAG_LABEL[tag]})`);
  };

  const deleteSaved = (id: string) => setSaved((s) => s.filter((x) => x.id !== id));

  const importAi = () => {
    try {
      const parsed = JSON.parse(aiText);
      const next: StrategyDraft = {
        name: typeof parsed.name === 'string' ? parsed.name : 'AI 生成策略',
        tag: 'ai',
        logic: parsed.logic === 'or' ? 'or' : 'and',
        position_size_pct: Number(parsed.position_size_pct) || 20,
        buy_rules: Array.isArray(parsed.buy_rules) ? parsed.buy_rules : [],
        sell_rules: Array.isArray(parsed.sell_rules) ? parsed.sell_rules : [],
      };
      if (!next.buy_rules.length && !next.sell_rules.length) {
        setMessage('AI 规则解析失败:buy_rules / sell_rules 为空');
        return;
      }
      loadDraft(next);
      setAiOpen(false);
      setAiText('');
      setMessage('已导入 AI 规则,可直接回测或微调后保存');
    } catch {
      setMessage('AI 规则 JSON 解析失败,请检查格式');
    }
  };

  const runBacktest = async () => {
    if (!draft.buy_rules.length && !draft.sell_rules.length) {
      setMessage('请至少配置一条买入或卖出规则');
      return;
    }
    setRunning(true);
    setResult(null);
    setMessage(`正在回测「${draft.name}」 @ ${symbol} ...`);
    try {
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<BacktestResult>('/api/quant/backtest', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: 'custom_rule',
          symbol,
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: capital,
          ...previewBody,
          params: {
            buy_rules: draft.buy_rules,
            sell_rules: draft.sell_rules,
            logic: draft.logic,
            position_size_pct: draft.position_size_pct,
          },
        }),
      });
      setResult(res);
      const m = res.metrics || {};
      const trades = m.trade_count ?? 0;
      setMessage(
        trades === 0
          ? `回测完成但 0 笔交易:规则未触发,或本金按 A 股 100 股整手买不进。${res.summary?.data_source_label ? ' 数据来源:' + res.summary.data_source_label : ''}`
          : `回测完成:${trades} 笔交易,累计 ${pct(m.total_return)},最大回撤 ${pct(m.max_drawdown)}。${res.summary?.data_source_label ? ' 数据来源:' + res.summary.data_source_label : ''}`,
      );
    } catch (err) {
      setMessage(`回测失败:${getErrorMessage(err)}`);
    } finally {
      setRunning(false);
    }
  };

  const renderRules = (kind: 'buy_rules' | 'sell_rules', title: string, accent: string) => (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className={cn('text-sm font-semibold', accent)}>{title}</span>
        <button
          onClick={() => addRule(kind)}
          className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-neutral-300 transition-colors hover:bg-white/10"
        >
          <Plus className="h-3.5 w-3.5" /> 加规则
        </button>
      </div>
      <div className="space-y-2">
        {draft[kind].length === 0 && (
          <p className="py-2 text-center text-xs text-neutral-500">无规则(该方向不触发)</p>
        )}
        {draft[kind].map((rule, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <ThemedSelect
                value={rule.field}
                options={fieldOptions}
                onChange={(v) => updateRule(kind, idx, { field: v })}
                buttonClassName="text-xs"
              />
            </div>
            <div className="w-16 flex-shrink-0">
              <ThemedSelect
                value={rule.op}
                options={opOptions}
                onChange={(v) => updateRule(kind, idx, { op: v })}
                buttonClassName="text-xs"
              />
            </div>
            <input
              type="number"
              value={Number.isNaN(rule.value) ? '' : rule.value}
              onChange={(e) => updateRule(kind, idx, { value: parseFloat(e.target.value) })}
              className="w-20 flex-shrink-0 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-neutral-200 outline-none focus:border-indigo-500/50"
            />
            <button
              onClick={() => removeRule(kind, idx)}
              className="flex-shrink-0 rounded-lg p-1.5 text-neutral-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
              aria-label="删除规则"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <motion.div
      key="strategy-lab"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex h-full flex-col gap-4 overflow-y-auto p-5"
    >
      <header className="flex items-start gap-3">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
          <Beaker className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-neutral-100">低代码策略编辑器</h1>
          <p className="mt-1 text-xs text-neutral-500">
            字段 + 操作符 + 阈值,无代码组合买卖信号 → 编译为 custom_rule 策略 → 复用真实回测引擎(T+1/印花税/滑点/防未来函数)。
          </p>
          <label className="mt-2 inline-flex max-w-xl cursor-pointer items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-100/90">
            <input
              type="checkbox"
              data-testid="strategy-lab-allow-preview"
              checked={allowPreviewData}
              onChange={(e) => setAllowPreviewData(e.target.checked)}
              className="mt-0.5 rounded border-amber-500/40 bg-black/40"
            />
            <span>允许演示样例行情（无真实行情时；默认关闭，与「量化回测」一致）</span>
          </label>
        </div>
      </header>

      {/* 模板卡片 */}
      <section>
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
          <Sparkles className="h-3.5 w-3.5" /> 内置模板(点击载入后可改)
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {PRESETS.map((p, idx) => (
            <motion.button
              key={p.name}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.04, duration: 0.25 }}
              onClick={() => loadDraft(p)}
              className="group rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left transition-all hover:border-indigo-500/40 hover:bg-indigo-500/[0.06]"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-neutral-200">{p.name}</span>
                <span className={cn('rounded border px-1.5 py-0.5 text-[10px]', TAG_STYLE[p.tag])}>
                  {TAG_LABEL[p.tag]}
                </span>
              </div>
              <p className="mt-1.5 text-[11px] text-neutral-500">
                买 {p.buy_rules.length} 条 / 卖 {p.sell_rules.length} 条 · {p.logic === 'and' ? '全部满足' : '任一满足'}
              </p>
            </motion.button>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        {/* 编辑区 */}
        <div className="space-y-4 lg:col-span-3">
          <div className="flex items-center gap-3">
            <input
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              className="flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm font-medium text-neutral-100 outline-none focus:border-indigo-500/50"
              placeholder="策略名称"
            />
            <div className="flex overflow-hidden rounded-lg border border-white/10">
              {(['and', 'or'] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setDraft((d) => ({ ...d, logic: l }))}
                  className={cn(
                    'px-3 py-2 text-xs font-medium transition-colors',
                    draft.logic === l ? 'bg-indigo-500/30 text-indigo-200' : 'bg-white/5 text-neutral-400 hover:bg-white/10',
                  )}
                >
                  {l === 'and' ? '全部满足' : '任一满足'}
                </button>
              ))}
            </div>
          </div>

          {renderRules('buy_rules', '买入规则', 'text-emerald-300')}
          {renderRules('sell_rules', '卖出规则', 'text-rose-300')}

          <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <span className="text-sm text-neutral-400">单次仓位</span>
            <input
              type="number"
              value={draft.position_size_pct}
              onChange={(e) => setDraft((d) => ({ ...d, position_size_pct: parseFloat(e.target.value) || 0 }))}
              className="w-20 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-neutral-200 outline-none focus:border-indigo-500/50"
            />
            <span className="text-sm text-neutral-400">% 权益</span>
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => setAiOpen((v) => !v)}
                className="flex items-center gap-1.5 rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-2 text-xs font-medium text-fuchsia-300 transition-colors hover:bg-fuchsia-500/20"
              >
                <Bot className="h-4 w-4" /> AI 规则导入
              </button>
              <button
                onClick={() => saveDraft('custom')}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-neutral-200 transition-colors hover:bg-white/10"
              >
                <Save className="h-4 w-4" /> 保存
              </button>
            </div>
          </div>

          {aiOpen && (
            <div className="rounded-xl border border-fuchsia-500/30 bg-fuchsia-500/[0.05] p-4">
              <p className="mb-2 flex items-center gap-1.5 text-xs text-fuchsia-300">
                <Wand2 className="h-3.5 w-3.5" /> 粘贴 AI 生成的规则 JSON(buy_rules / sell_rules / logic / position_size_pct)
              </p>
              <textarea
                value={aiText}
                onChange={(e) => setAiText(e.target.value)}
                rows={5}
                placeholder='{"name":"AI动量","buy_rules":[{"field":"pct_change","op":">","value":5}],"sell_rules":[],"logic":"and","position_size_pct":20}'
                className="w-full rounded-lg border border-white/10 bg-black/40 p-2 font-mono text-xs text-neutral-200 outline-none focus:border-fuchsia-500/50"
              />
              <div className="mt-2 flex justify-end">
                <button
                  onClick={importAi}
                  className="rounded-lg bg-fuchsia-500/80 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-fuchsia-500"
                >
                  导入并载入
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 回测区 */}
        <div className="space-y-4 lg:col-span-2">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div className="mb-3 text-sm font-semibold text-neutral-200">回测设置</div>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-neutral-500">标的代码</span>
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.trim())}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-indigo-500/50"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-xs text-neutral-500">回看天数</span>
                  <input
                    type="number"
                    value={days}
                    onChange={(e) => setDays(parseInt(e.target.value) || 180)}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-indigo-500/50"
                  />
                </label>
                <label className="block">
                  <span className="text-xs text-neutral-500">初始本金</span>
                  <input
                    type="number"
                    value={capital}
                    onChange={(e) => setCapital(parseInt(e.target.value) || 100000)}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-indigo-500/50"
                  />
                </label>
              </div>
              <button
                onClick={runBacktest}
                disabled={running}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-500/80 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-500 disabled:opacity-50"
              >
                <Play className="h-4 w-4" /> {running ? '回测中...' : '运行回测'}
              </button>
            </div>
          </div>

          {message && (
            <div className="rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-neutral-300">{message}</div>
          )}

          {result?.metrics && (
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 text-sm font-semibold text-neutral-200">回测结果</div>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: '累计收益', value: pct(result.metrics.total_return), good: (result.metrics.total_return ?? 0) >= 0 },
                  { label: '年化收益', value: pct(result.metrics.annual_return), good: (result.metrics.annual_return ?? 0) >= 0 },
                  { label: '最大回撤', value: pct(result.metrics.max_drawdown), good: false },
                  { label: '夏普', value: (result.metrics.sharpe_ratio ?? 0).toFixed(2), good: (result.metrics.sharpe_ratio ?? 0) >= 1 },
                  { label: '胜率', value: pct(result.metrics.win_rate), good: (result.metrics.win_rate ?? 0) >= 0.5 },
                  { label: '交易笔数', value: String(result.metrics.trade_count ?? 0), good: true },
                ].map((s, idx) => (
                  <motion.div
                    key={s.label}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.05, duration: 0.25 }}
                    className="rounded-lg border border-white/5 bg-black/20 p-2.5"
                  >
                    <div className="text-[11px] text-neutral-500">{s.label}</div>
                    <div className={cn('mt-0.5 text-base font-semibold', s.good ? 'text-emerald-300' : 'text-rose-300')}>
                      {s.value}
                    </div>
                  </motion.div>
                ))}
              </div>
              {result.assumptions?.note && (
                <p className="mt-3 text-[11px] leading-relaxed text-neutral-500">假设:{result.assumptions.note}</p>
              )}
            </div>
          )}

          {/* 已保存策略 */}
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div className="mb-3 text-sm font-semibold text-neutral-200">我的策略库({saved.length})</div>
            {saved.length === 0 && <p className="text-xs text-neutral-500">还没有保存的策略。配置规则后点「保存」。</p>}
            <div className="space-y-2">
              {saved.map((s, idx) => (
                <motion.div
                  key={s.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.04, duration: 0.25 }}
                  className="flex items-center gap-2 rounded-lg border border-white/5 bg-black/20 p-2"
                >
                  <span className={cn('rounded border px-1.5 py-0.5 text-[10px]', TAG_STYLE[s.tag])}>{TAG_LABEL[s.tag]}</span>
                  <button onClick={() => loadDraft(s)} className="min-w-0 flex-1 truncate text-left text-sm text-neutral-200 hover:text-indigo-300">
                    {s.name}
                  </button>
                  <span className="flex-shrink-0 text-[10px] text-neutral-600">买{s.buy_rules.length}/卖{s.sell_rules.length}</span>
                  <button onClick={() => deleteSaved(s.id)} className="flex-shrink-0 rounded p-1 text-neutral-500 hover:bg-red-500/10 hover:text-red-400" aria-label="删除">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
