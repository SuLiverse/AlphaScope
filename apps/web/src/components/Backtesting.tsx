import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ComponentType } from 'react';
import {
  Activity,
  BarChart,
  CheckCircle2,
  Code2,
  Cpu,
  Database,
  Download,
  Coins,
  Dna,
  Flag,
  Gauge,
  GitBranch,
  GitCompare,
  History,
  Layers,
  Play,
  ShieldAlert,
  Trash2,
  TrendingUp,
  Trophy,
  Upload,
} from 'lucide-react';
import { Bar, BarChart as RBarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { findStockTarget, STOCK_UNIVERSE, StockTarget } from '../lib/stocks';
import { API_BASE_URL, LOCAL_API_TOKEN, fetchApi } from '../lib/api';
import { getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import { getErrorMessage, stripSymbolSuffix, useAsync } from '../lib/dataFetch';
import { StableChartContainer } from './StableChartContainer';

type TabID = 'overview' | 'workshop' | 'leaderboard' | 'walkforward' | 'evolution' | 'chips' | 'experiments' | 'pool' | 'compare';

const TABS: Array<{ id: TabID; label: string; icon: ComponentType<{ className?: string }> }> = [
  { id: 'overview', label: '回测大厅', icon: History },
  { id: 'workshop', label: '策略工坊', icon: Code2 },
  { id: 'leaderboard', label: '策略榜', icon: Trophy },
  { id: 'walkforward', label: '样本外走查', icon: GitBranch },
  { id: 'evolution', label: '策略进化', icon: Dna },
  { id: 'chips', label: '筹码分布', icon: Coins },
  { id: 'experiments', label: '实验记录', icon: Database },
  { id: 'pool', label: '股票池解析', icon: Layers },
  { id: 'compare', label: '后验比对', icon: Activity },
];

// 实验记录类型元信息(标签 + 主题色)。
const EXP_MODE_META: Record<string, { label: string; tone: string }> = {
  backtest: { label: '回测', tone: 'text-indigo-300 border-indigo-500/30 bg-indigo-500/10' },
  walk_forward: { label: '走查', tone: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10' },
  chip_distribution: { label: '筹码', tone: 'text-amber-300 border-amber-500/30 bg-amber-500/10' },
  strategy_compare: { label: '策略榜', tone: 'text-rose-300 border-rose-500/30 bg-rose-500/10' },
  evolution: { label: '进化', tone: 'text-fuchsia-300 border-fuchsia-500/30 bg-fuchsia-500/10' },
};

// 进化适应度指标中文名。
const EVO_METRIC_LABELS: Record<string, string> = {
  sharpe_ratio: '夏普比率',
  calmar_ratio: '卡玛比率',
  sortino_ratio: '索提诺比率',
  total_return: '累计收益',
  annualized_return: '年化收益',
  profit_factor: '盈亏比',
  win_rate: '胜率',
};

/** 把实验摘要(随 mode 不同)渲染成一行紧凑文本。 */
function formatExpSummary(mode: string, summary?: Record<string, number | string>): string {
  if (!summary) return '--';
  const num = (v: unknown, d = 2) => (typeof v === 'number' ? v.toFixed(d) : '--');
  if (mode === 'backtest') {
    return `收益 ${num(summary.total_return)}% · 夏普 ${num(summary.sharpe_ratio)} · 回撤 ${num(summary.max_drawdown)}% · ${summary.trade_count ?? 0}笔`;
  }
  if (mode === 'walk_forward') {
    return `${summary.n_windows ?? 0}窗 · 样本外胜率 ${num(summary.pct_profitable_windows)}% · 一致性 ${num(summary.consistency_score)} · ${summary.robustness ?? ''}`;
  }
  if (mode === 'chip_distribution') {
    return `获利盘 ${num(summary.profit_ratio)}% · 均成本 ${num(summary.avg_cost)} · 90%集中度 ${num(summary.concentration_90)}%`;
  }
  if (mode === 'strategy_compare') {
    return `${summary.evaluated ?? 0}策略 · 冠军 ${summary.top_strategy ?? '--'}(${num(summary.top_total_return)}%) · 按${summary.rank_by ?? ''}`;
  }
  if (mode === 'evolution') {
    return `${summary.fitness_metric ?? ''} 最优 ${num(summary.best_fitness, 3)} · 较默认 ${num(summary.improvement, 3)} · ${summary.generations ?? 0}代×${summary.population_size ?? 0} · ${summary.evaluations ?? 0}评估`;
  }
  return Object.entries(summary).map(([k, v]) => `${k} ${typeof v === 'number' ? v.toFixed(2) : v}`).join(' · ');
}

const DEFAULT_POOL_TEXT = `600519 贵州茅台
300750 宁德时代
600036 招商银行
002594 比亚迪
300059 东方财富
601318 中国平安`;

// ---- Backend response contracts (backend/api/backtest_new.py + main.py) ----

interface PerformanceMetrics {
  total_return?: number;
  annual_return?: number;
  max_drawdown?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  calmar_ratio?: number;
  win_rate?: number;
  profit_factor?: number;
  trade_count?: number;
  initial_capital?: number;
  final_equity?: number;
  trading_days?: number;
  volatility?: number;
  // v1.9.4 基准相关指标(有基准时存在)
  has_benchmark?: boolean;
  benchmark_name?: string;
  excess_return?: number;
  information_ratio?: number;
  beta?: number;
  alpha?: number;
}

interface TradeRecord {
  symbol?: string;
  side?: string;
  shares?: number;
  price?: number;
  commission?: number;
  pnl?: number;
  timestamp?: string;
}

interface RiskViolation {
  rule?: string;
  reason?: string;
  date?: string;
}

/** Backtest engine friction assumptions (T+1 / stamp duty / slippage / etc.).
 * Mirrors backend/quant/engine.py BacktestEngine._assumptions(). */
interface BacktestAssumptions {
  commission_rate?: number;
  commission_min?: number;
  stamp_duty_rate?: number;
  slippage_rate?: number;
  t_plus_1?: boolean;
  price_limit_filter?: boolean;
  price_limit_band?: number;
  execution_price?: string;
  note?: string;
}

interface BacktestEquityPoint {
  date?: string;
  equity?: number;
  value?: number;
}

interface BacktestSummary {
  data_source?: string;
  data_source_label?: string;
  bar_count?: number;
  trade_count?: number;
  risk_violation_count?: number;
  start_date?: string;
  end_date?: string;
}

interface BacktestResultData {
  run_id?: string;
  strategy_id?: string;
  symbol?: string;
  equity_curve?: BacktestEquityPoint[];
  trades?: TradeRecord[];
  metrics?: PerformanceMetrics;
  risk_violations?: RiskViolation[];
  summary?: BacktestSummary;
  assumptions?: BacktestAssumptions;
  message?: string;
}

interface StrategyInfo {
  id: string;
  name: string;
  description?: string;
  default_params?: Record<string, unknown>;
}

// ---- Walk-forward contract (backend/quant/walk_forward.py to_dict) ----

interface WalkForwardWindow {
  index: number;
  scheme: string;
  is_start_date: string;
  is_end_date: string;
  oos_start_date: string;
  oos_end_date: string;
  is_bars: number;
  oos_bars: number;
  is_return: number;
  oos_return: number;
  is_annualized: number;
  oos_annualized: number;
  oos_sharpe: number;
  oos_max_drawdown: number;
  oos_win_rate: number;
  oos_trades: number;
  wfe: number;
  oos_profitable: boolean;
}

interface WalkForwardAggregate {
  windows_evaluated: number;
  mean_oos_return: number;
  median_oos_return: number;
  std_oos_return: number;
  best_oos_return: number;
  worst_oos_return: number;
  profitable_windows: number;
  pct_profitable_windows: number;
  mean_wfe: number;
  consistency_score: number;
  robustness: string;
}

interface WalkForwardData {
  run_id?: string;
  symbol?: string;
  strategy_name?: string;
  scheme?: string;
  n_windows?: number;
  requested_windows?: number;
  status?: string;
  note?: string;
  windows?: WalkForwardWindow[];
  aggregate?: WalkForwardAggregate;
  full_period?: PerformanceMetrics;
  assumptions?: BacktestAssumptions;
  disclaimer?: string;
  data_source_label?: string;
  bar_count?: number;
  message?: string;
}

// ---- Chip distribution contract (backend/quant/chip_distribution.py to_dict) ----

interface ChipLevel {
  price: number;
  pct: number;
}

interface ChipDistributionData {
  run_id?: string;
  symbol?: string;
  status?: string;
  model?: string;
  current_price?: number;
  avg_cost?: number;
  profit_ratio?: number;
  concentration_70?: number;
  concentration_90?: number;
  range_70_low?: number;
  range_70_high?: number;
  range_90_low?: number;
  range_90_high?: number;
  support_price?: number;
  resistance_price?: number;
  bars_used?: number;
  levels?: ChipLevel[];
  note?: string;
  disclaimer?: string;
  data_source_label?: string;
  message?: string;
}

// ---- Strategy comparison contract (backend/api/quant.py compare-strategies) ----

interface StrategyCompareRow {
  rank?: number;
  strategy_id: string;
  strategy_name?: string;
  description?: string;
  total_return?: number;
  annual_return?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  calmar_ratio?: number;
  max_drawdown?: number;
  win_rate?: number;
  profit_factor?: number;
  trade_count?: number;
  risk_violations?: number;
}

interface StrategyCompareData {
  run_id?: string;
  symbol?: string;
  rank_by?: string;
  ranking?: StrategyCompareRow[];
  skipped?: string[];
  evaluated?: number;
  assumptions?: BacktestAssumptions;
  data_source_label?: string;
  bar_count?: number;
  disclaimer?: string;
  message?: string;
}

// ---- Experiment store contract (backend/quant/experiment_store.py) ----

interface ExperimentRow {
  run_id: string;
  mode: string;
  symbol?: string;
  strategy_id?: string;
  created_at?: string;
  summary?: Record<string, number | string>;
}

// ---- TDX compile contract (backend/quant/tdx_compiler.py to_dict) ----

interface TdxCompileResult {
  ok: boolean;
  errors?: string[];
  warnings?: string[];
  var_names?: string[];
  buy_signals?: string[];
  sell_signals?: string[];
  refs_used?: string[];
  statement_count?: number;
}

const DEFAULT_TDX_FORMULA = `DIFF:=EMA(CLOSE,12)-EMA(CLOSE,26);
DEA:=EMA(DIFF,9);
MACD:2*(DIFF-DEA);
ENTERLONG:CROSS(DIFF,DEA) AND MACD>0;
EXITLONG:CROSS(DEA,DIFF);`;

// ---- Genetic-algorithm evolution contract (backend/quant/evolution.py to_dict) ----

interface EvolveIndividual {
  genome: Record<string, number>;
  params: Record<string, number>;
  fitness: number | null;
  metrics: Record<string, number>;
}

interface EvolveGenStat {
  generation: number;
  best_fitness: number | null;
  avg_fitness: number | null;
  best_genome: Record<string, number>;
}

interface EvolveData {
  run_id?: string;
  status?: string; // ok | insufficient | degraded | error
  strategy_id?: string;
  symbol?: string;
  fitness_metric?: string;
  population_size?: number;
  generations?: number;
  seed?: number;
  evaluations?: number;
  best?: EvolveIndividual | null;
  baseline?: EvolveIndividual | null;
  improvement?: number | null;
  history?: EvolveGenStat[];
  param_space?: Record<string, { type: string; min: number; max: number; step?: number; default?: number }>;
  message?: string;
  disclaimer?: string;
  data_source_label?: string;
  bar_count?: number;
}

/** 把基因组(被进化的参数子集)渲染成紧凑文本: short=5, threshold=1.250 */
function formatGenome(genome?: Record<string, number>): string {
  if (!genome || !Object.keys(genome).length) return '--';
  return Object.entries(genome)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(3)) : v}`)
    .join(', ');
}

interface FactorResponse {
  symbol: string;
  stock_name?: string;
  computed_at?: string;
  factors?: Record<string, number>;
  sample_counts?: Record<string, number>;
  degraded_inputs?: string[];
  missing_dimensions?: string[];
  signals?: Array<Record<string, number | string | boolean>>;
}

interface FactorRow {
  stock: StockTarget;
  composite?: number;
  momentum?: number;
  fund_flow?: number;
  quality: number;
  computed_at?: string;
  error?: string;
}

interface BacktestStats {
  total?: number;
  evaluated?: number;
  message?: string;
  buy_signals?: { count?: number; accuracy_5d?: number };
  sell_signals?: { count?: number };
  hold_signals?: { count?: number };
}

interface PendingEval {
  decision_id?: string;
  symbol?: string;
  signal?: string;
  price?: number;
  days_elapsed?: number;
}

interface AgentAccuracy {
  agents?: Record<string, { accuracy?: number; total_decisions?: number; avg_return?: number }>;
}

function parsePoolText(value: string): StockTarget[] {
  const tokens = value
    .split(/[\n,，;\t ]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  const seen = new Set<string>();
  return tokens.reduce<StockTarget[]>((acc, token) => {
    const stock = findStockTarget(token);
    if (stock && !seen.has(stock.symbol)) {
      seen.add(stock.symbol);
      acc.push(stock);
    }
    return acc;
  }, []);
}

function formatFactor(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return value.toFixed(2);
}

function formatPercent(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  hint: string;
  icon: ComponentType<{ className?: string }>;
  tone?: 'rose' | 'emerald' | 'indigo' | 'neutral' | 'amber';
}) {
  const color = {
    rose: 'text-rose-400',
    emerald: 'text-emerald-400',
    indigo: 'text-indigo-300',
    neutral: 'text-neutral-300',
    amber: 'text-amber-300',
  }[tone];

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-xl">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">{label}</p>
        <Icon className={cn('h-4 w-4', color)} />
      </div>
      <h3 className="text-3xl font-mono font-medium text-white">{value}</h3>
      <p className={cn('mt-2 text-[11px] font-mono', color)}>{hint}</p>
    </div>
  );
}

/** Render the backtest engine's friction assumptions so users can see exactly
 * what costs/limits were modelled (transparency / auditability). */
function AssumptionsCard({ assumptions }: { assumptions?: BacktestAssumptions }) {
  if (!assumptions) return null;
  const pct = (v?: number) => (typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : '--');
  const rows: Array<{ label: string; value: string; on?: boolean }> = [
    { label: 'T+1 结算', value: assumptions.t_plus_1 ? '启用' : '关闭', on: assumptions.t_plus_1 },
    { label: '涨跌停封板过滤', value: assumptions.price_limit_filter ? `启用 · ±${((assumptions.price_limit_band ?? 0.1) * 100).toFixed(0)}%` : '关闭', on: assumptions.price_limit_filter },
    { label: '佣金（双边）', value: pct(assumptions.commission_rate) + (assumptions.commission_min ? ` · 最低 ¥${assumptions.commission_min}` : '') },
    { label: '印花税（卖出）', value: pct(assumptions.stamp_duty_rate) },
    { label: '滑点', value: pct(assumptions.slippage_rate) },
    { label: '成交价口径', value: assumptions.execution_price === 'open' ? '次日开盘（防未来函数）' : (assumptions.execution_price || '--') },
  ];
  return (
    <div className="rounded-2xl border border-amber-500/15 bg-amber-500/[0.04] p-5 shadow-xl">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-amber-200/80">
          <ShieldAlert className="h-4 w-4" />
          本次回测假设
        </h3>
        <span className="rounded border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono text-amber-300">真实摩擦成本</span>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded-lg border border-white/5 bg-black/25 px-3 py-2">
            <p className="text-[10px] text-neutral-500">{row.label}</p>
            <p className={cn('mt-0.5 text-xs font-mono', row.on === false ? 'text-neutral-600' : 'text-neutral-200')}>{row.value}</p>
          </div>
        ))}
      </div>
      {assumptions.note && (
        <p className="mt-3 text-[10px] leading-relaxed text-neutral-500">{assumptions.note}</p>
      )}
    </div>
  );
}

/** Trade blotter — renders the `trades` field that was typed but never shown. */
function TradeTable({ trades }: { trades?: TradeRecord[] }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
        <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">交易明细</h3>
        <p className="text-xs text-neutral-500">本次回测无成交记录。</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
      <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">交易明细 · 共 {trades.length} 笔</h3>
      <div className="max-h-72 overflow-auto custom-scrollbar">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-black/40 text-[10px] uppercase tracking-wider text-neutral-500">
            <tr>
              <th className="px-2 py-2 font-medium">时间</th>
              <th className="px-2 py-2 font-medium">方向</th>
              <th className="px-2 py-2 text-right font-medium">数量</th>
              <th className="px-2 py-2 text-right font-medium">成交价</th>
              <th className="px-2 py-2 text-right font-medium">佣金</th>
              <th className="px-2 py-2 text-right font-medium">盈亏</th>
            </tr>
          </thead>
          <tbody className="font-mono text-neutral-300">
            {trades.map((t, i) => (
              <tr key={i} className="border-t border-white/5">
                <td className="px-2 py-1.5 text-neutral-500">{t.timestamp || '--'}</td>
                <td className="px-2 py-1.5">
                  <span className={cn('rounded px-1.5 py-0.5 text-[10px]', t.side === 'buy' ? 'bg-rose-500/10 text-rose-300' : 'bg-emerald-500/10 text-emerald-300')}>
                    {t.side === 'buy' ? '买入' : '卖出'}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right">{t.shares ?? '--'}</td>
                <td className="px-2 py-1.5 text-right">{t.price != null ? t.price.toFixed(2) : '--'}</td>
                <td className="px-2 py-1.5 text-right text-neutral-500">{t.commission != null ? t.commission.toFixed(2) : '--'}</td>
                <td className={cn('px-2 py-1.5 text-right', (t.pnl ?? 0) >= 0 ? 'text-rose-300' : 'text-emerald-300')}>
                  {t.pnl != null ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2) : '--'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Backtesting() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const persisted = getPersistedStock();
  const [activeTab, setActiveTab] = useState<TabID>('overview');
  const [poolText, setPoolText] = useState(DEFAULT_POOL_TEXT);
  const [actionMessage, setActionMessage] = useState('回测引擎待命，选择策略与标的后可启动真实回测。');

  // Backtest run state
  const persistedStock = useMemo(() => persisted ?? STOCK_UNIVERSE[0], [persisted]);
  const [selectedSymbol, setSelectedSymbol] = useState(persistedStock.symbol);
  const [selectedStockName, setSelectedStockName] = useState(persistedStock.name);
  const [days, setDays] = useState(180);
  const [initialCapital, setInitialCapital] = useState(1000000);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResultData | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // QuantStats 完整绩效报告(接出 performance_report)
  const [qsMetrics, setQsMetrics] = useState<Record<string, number | string> | null>(null);
  const [qsAvailable, setQsAvailable] = useState(true);
  const [qsLoading, setQsLoading] = useState(false);
  const [qsError, setQsError] = useState('');

  const computeQuantStats = async () => {
    const curve = result?.equity_curve
      ?.map((p) => Number(p.equity ?? p.value ?? 0))
      .filter((v) => Number.isFinite(v) && v > 0) ?? [];
    if (curve.length < 3) {
      setQsError('净值曲线点数不足(需 ≥3 个点)');
      return;
    }
    setQsLoading(true);
    setQsError('');
    try {
      const res = await fetchApi<{ available: boolean; metrics: Record<string, number | string>; error?: string }>(
        '/api/portfolio/performance',
        { method: 'POST', body: JSON.stringify({ equity_curve: curve }) },
      );
      setQsAvailable(res?.available !== false);
      setQsMetrics(res?.metrics || null);
      if (res?.error) setQsError(res.error);
    } catch (e) {
      setQsError(e instanceof Error ? e.message : '绩效计算失败');
    } finally {
      setQsLoading(false);
    }
  };

  // Walk-forward (样本外走查) state — reuses the strategy/symbol/capital above.
  const [wfScheme, setWfScheme] = useState<'anchored' | 'rolling'>('anchored');
  const [wfSplits, setWfSplits] = useState(5);
  const [wfRunning, setWfRunning] = useState(false);
  const [wfResult, setWfResult] = useState<WalkForwardData | null>(null);
  const [wfError, setWfError] = useState<string | null>(null);

  // Chip distribution (筹码分布) state — reuses the symbol selection above.
  const [chipRunning, setChipRunning] = useState(false);
  const [chipResult, setChipResult] = useState<ChipDistributionData | null>(null);
  const [chipError, setChipError] = useState<string | null>(null);

  // Strategy leaderboard (策略榜) state — reuses symbol/capital above.
  const [cmpRunning, setCmpRunning] = useState(false);
  const [cmpResult, setCmpResult] = useState<StrategyCompareData | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);
  const [cmpRankBy, setCmpRankBy] = useState<'sharpe_ratio' | 'total_return' | 'calmar_ratio'>('sharpe_ratio');

  // Experiment history (实验记录) state — persisted runs across sessions.
  const [expRows, setExpRows] = useState<ExperimentRow[]>([]);
  const [expLoading, setExpLoading] = useState(false);
  const [expError, setExpError] = useState<string | null>(null);
  const [expModeFilter, setExpModeFilter] = useState<string>('');
  const [expSelected, setExpSelected] = useState<Set<string>>(new Set());
  const [expTotal, setExpTotal] = useState(0);
  const [expRefresh, setExpRefresh] = useState(0);
  const [expCompareRows, setExpCompareRows] = useState<ExperimentRow[] | null>(null);

  // TDX formula editor (策略工坊) state.
  const [tdxFormula, setTdxFormula] = useState<string>(DEFAULT_TDX_FORMULA);
  const [tdxCompile, setTdxCompile] = useState<TdxCompileResult | null>(null);
  const [tdxCompiling, setTdxCompiling] = useState(false);
  const [tdxRunning, setTdxRunning] = useState(false);

  // Genetic-algorithm evolution (策略进化) state — reuses strategy/symbol/capital above.
  const [evoMetric, setEvoMetric] = useState<'sharpe_ratio' | 'calmar_ratio' | 'sortino_ratio' | 'total_return' | 'win_rate'>('sharpe_ratio');
  const [evoPop, setEvoPop] = useState(16);
  const [evoGens, setEvoGens] = useState(8);
  const [evoSeed, setEvoSeed] = useState(42);
  const [evoRunning, setEvoRunning] = useState(false);
  const [evoResult, setEvoResult] = useState<EvolveData | null>(null);
  const [evoError, setEvoError] = useState<string | null>(null);

  // Strategy catalogue (real)
  const strategiesAsync = useAsync<StrategyInfo[]>(
    () => fetchApi<{ strategies?: StrategyInfo[] } | StrategyInfo[]>('/api/quant/strategies').then((r) => {
      const list = Array.isArray(r) ? r : r?.strategies || [];
      return list;
    }),
    [],
  );
  const strategies = useMemo(() => strategiesAsync.data ?? [], [strategiesAsync.data]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('');

  useEffect(() => {
    if (!selectedStrategy && strategies.length) {
      setSelectedStrategy(strategies[0].id || strategies[0].name);
    }
  }, [strategies, selectedStrategy]);

  // Stock sync with workspace
  useEffect(() => subscribeStockSelected(({ stock }) => {
    setSelectedSymbol(stock.symbol);
    setSelectedStockName(stock.name);
  }), []);

  // Stock pool factor screening (real /api/factors per stock)
  const poolStocks = useMemo(() => parsePoolText(poolText), [poolText]);
  const [poolRows, setPoolRows] = useState<FactorRow[]>([]);
  const [poolLoading, setPoolLoading] = useState(false);
  const [poolSource, setPoolSource] = useState('');

  useEffect(() => {
    let cancelled = false;
    if (!poolStocks.length) {
      setPoolRows([]);
      setPoolSource('');
      return;
    }
    setPoolLoading(true);
    setPoolSource('正在计算真实截面因子...');
    Promise.allSettled(
      poolStocks.map((stock) =>
        fetchApi<FactorResponse>(
          `/api/factors/${encodeURIComponent(stripSymbolSuffix(stock.symbol))}?stock_name=${encodeURIComponent(stock.name)}&days=30`,
        ).then((payload) => ({ stock, payload })),
      ),
    ).then((results) => {
      if (cancelled) return;
      const rows: FactorRow[] = results.map((res, index) => {
        const stock = poolStocks[index];
        if (res.status === 'fulfilled') {
          const factors = res.value.payload.factors || {};
          const missing = res.value.payload.missing_dimensions || [];
          const degraded = res.value.payload.degraded_inputs || [];
          const quality = Math.max(0, 100 - missing.length * 20 - degraded.length * 10);
          return {
            stock,
            composite: factors.composite,
            momentum: factors.momentum,
            fund_flow: factors.fund_flow,
            quality,
            computed_at: res.value.payload.computed_at,
          };
        }
        return {
          stock,
          quality: 0,
          error: getErrorMessage(res.reason),
        };
      });
      setPoolRows(rows);
      setPoolLoading(false);
      const latest = rows.find((row) => row.computed_at)?.computed_at?.slice(0, 19).replace('T', ' ');
      setPoolSource(latest ? `真实截面因子 · 计算于 ${latest}` : '真实截面因子 · 已计算');
    });
    return () => {
      cancelled = true;
    };
  }, [poolStocks]);

  // Post-mortem compare data (real /api/backtest/*)
  const [stats, setStats] = useState<BacktestStats | null>(null);
  const [pending, setPending] = useState<PendingEval[]>([]);
  const [agentAccuracy, setAgentAccuracy] = useState<AgentAccuracy | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'compare') return;
    let cancelled = false;
    setCompareLoading(true);
    setCompareError(null);
    Promise.allSettled([
      fetchApi<BacktestStats>('/api/backtest/stats'),
      fetchApi<{ pending?: PendingEval[] }>('/api/backtest/pending').then((r) => r.pending || []),
      fetchApi<{ agents?: AgentAccuracy['agents'] }>('/api/backtest/agent-accuracy'),
    ]).then((results) => {
      if (cancelled) return;
      setCompareLoading(false);
      if (results[0].status === 'fulfilled') setStats(results[0].value);
      else setCompareError(getErrorMessage(results[0].reason));
      if (results[1].status === 'fulfilled') setPending(results[1].value);
      if (results[2].status === 'fulfilled') setAgentAccuracy({ agents: results[2].value.agents });
    });
    return () => {
      cancelled = true;
    };
  }, [activeTab]);

  const runTest = async () => {
    if (!selectedStrategy) {
      setActionMessage('请先在策略工坊选择一个策略。');
      return;
    }
    setRunning(true);
    setRunError(null);
    setResult(null);
    setActionMessage(`正在运行「${selectedStrategy}」对 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)}) 的真实回测...`);
    try {
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);
      const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<BacktestResultData>('/api/quant/backtest', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: initialCapital,
          params: {},
        }),
      });
      setResult(res);
      const perf = res.metrics || {};
      const tradeCount = perf.trade_count ?? 0;
      if (tradeCount === 0) {
        setActionMessage(
          `回测完成但 0 笔交易：策略未触发买卖信号，或当前本金（¥${initialCapital.toLocaleString()}）按 A 股 100 股整手买不进该标的。可尝试提高本金或更换标的。${res.summary?.data_source_label ? ' 数据来源：' + res.summary.data_source_label : ''}`,
        );
      } else {
        setActionMessage(
          `回测完成：${tradeCount} 笔交易，累计收益 ${formatPercent(perf.total_return)}，最大回撤 ${formatPercent(perf.max_drawdown)}。${res.summary?.data_source_label ? '数据来源：' + res.summary.data_source_label : ''}`,
        );
      }
    } catch (err) {
      const msg = getErrorMessage(err);
      setRunError(msg);
      setActionMessage(`回测失败：${msg}`);
    } finally {
      setRunning(false);
    }
  };

  const runWalkForward = async () => {
    if (!selectedStrategy) {
      setActionMessage('请先在策略工坊选择一个策略。');
      return;
    }
    setWfRunning(true);
    setWfError(null);
    setWfResult(null);
    setActionMessage(
      `正在对 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)}) 运行「${selectedStrategy}」的样本外走查...`,
    );
    try {
      // Walk-forward needs more history than a single backtest: n_splits+1 folds
      // of ≥20 trading bars each. Extend the lookback so the requested split
      // count actually fits (backend still degrades gracefully if not).
      const lookbackDays = Math.max(days, (wfSplits + 1) * 45);
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - lookbackDays);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<WalkForwardData>('/api/quant/walk-forward', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: initialCapital,
          params: {},
          n_splits: wfSplits,
          scheme: wfScheme,
        }),
      });
      setWfResult(res);
      const agg = res.aggregate;
      if (res.status === 'insufficient') {
        setActionMessage(`样本外走查样本不足：${res.note || '历史数据太短，无法切分窗口'}`);
      } else {
        setActionMessage(
          `走查完成：${res.n_windows ?? 0} 个样本外窗口，样本外胜率 ${agg?.pct_profitable_windows ?? 0}%，稳健性「${agg?.robustness ?? '--'}」。${res.data_source_label ? ' 数据来源：' + res.data_source_label : ''}`,
        );
      }
    } catch (err) {
      const msg = getErrorMessage(err);
      setWfError(msg);
      setActionMessage(`样本外走查失败：${msg}`);
    } finally {
      setWfRunning(false);
    }
  };

  const runChipDistribution = async () => {
    setChipRunning(true);
    setChipError(null);
    setChipResult(null);
    setActionMessage(`正在重建 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)}) 的筹码(成本)分布...`);
    try {
      // 筹码分布需要较长历史以稳定扩散,至少回看半年。
      const lookbackDays = Math.max(days, 180);
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - lookbackDays);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<ChipDistributionData>('/api/quant/chip-distribution', {
        method: 'POST',
        body: JSON.stringify({
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          price_levels: 100,
        }),
      });
      setChipResult(res);
      if (res.status === 'insufficient') {
        setActionMessage(`筹码分布样本不足：${res.note || '历史数据太短'}`);
      } else {
        setActionMessage(
          `筹码分布完成：获利盘 ${formatFactor(res.profit_ratio)}%，平均成本 ${res.avg_cost?.toFixed(2)}，${res.model === 'turnover' ? '真实换手率' : '量能代理'}建模。${res.data_source_label ? ' 数据来源：' + res.data_source_label : ''}`,
        );
      }
    } catch (err) {
      const msg = getErrorMessage(err);
      setChipError(msg);
      setActionMessage(`筹码分布失败：${msg}`);
    } finally {
      setChipRunning(false);
    }
  };

  const runEvolution = async () => {
    if (!selectedStrategy) {
      setActionMessage('请先在策略工坊选择一个策略。');
      return;
    }
    setEvoRunning(true);
    setEvoError(null);
    setEvoResult(null);
    setActionMessage(
      `正在对 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)}) 的「${selectedStrategy}」做遗传算法参数寻优...`,
    );
    try {
      // 进化需要足够长的历史样本作为适应度评估基底,至少回看一年。
      const lookbackDays = Math.max(days, 365);
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - lookbackDays);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<EvolveData>('/api/quant/evolve', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: initialCapital,
          params: {},
          param_space: {},
          population_size: evoPop,
          generations: evoGens,
          fitness_metric: evoMetric,
          seed: evoSeed,
        }),
      });
      setEvoResult(res);
      if (res.status === 'insufficient') {
        setActionMessage(`策略进化样本不足：${res.message || '历史数据太短，无法寻优'}`);
      } else if (res.status === 'degraded') {
        setActionMessage(`策略进化：${res.message || '该策略无可寻优的数值参数'}`);
      } else if (res.status === 'error') {
        setActionMessage(`策略进化失败：${res.message || '寻优无有效结果'}`);
      } else {
        const impNum = typeof res.improvement === 'number' ? res.improvement : null;
        const impStr = impNum === null ? '--' : `${impNum >= 0 ? '+' : ''}${impNum.toFixed(3)}`;
        const bestFit = typeof res.best?.fitness === 'number' ? res.best.fitness.toFixed(3) : '--';
        setActionMessage(
          `进化完成：最优 ${res.fitness_metric} = ${bestFit}（较默认 ${impStr}），${res.evaluations ?? 0} 次去重回测评估。${res.data_source_label ? ' 数据来源：' + res.data_source_label : ''}`,
        );
      }
    } catch (err) {
      const msg = getErrorMessage(err);
      setEvoError(msg);
      setActionMessage(`策略进化失败：${msg}`);
    } finally {
      setEvoRunning(false);
    }
  };

  // Load persisted experiments when the tab is active / filter / refresh changes.
  useEffect(() => {
    if (activeTab !== 'experiments') return;
    let cancelled = false;
    setExpLoading(true);
    setExpError(null);
    const q = expModeFilter ? `?mode=${encodeURIComponent(expModeFilter)}&limit=100` : '?limit=100';
    fetchApi<{ experiments?: ExperimentRow[]; total?: number }>(`/api/quant/experiments${q}`)
      .then((r) => {
        if (cancelled) return;
        setExpRows(r.experiments || []);
        setExpTotal(r.total || 0);
        setExpLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setExpError(getErrorMessage(e));
        setExpLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, expModeFilter, expRefresh]);

  const deleteExperiment = async (runId: string) => {
    try {
      await fetchApi(`/api/quant/experiments/${encodeURIComponent(runId)}`, { method: 'DELETE' });
      setExpSelected((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
      setExpCompareRows(null);
      setExpRefresh((n) => n + 1);
    } catch (err) {
      setExpError(getErrorMessage(err));
    }
  };

  const toggleExpSelect = (runId: string) => {
    setExpSelected((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else if (next.size < 4) next.add(runId);
      return next;
    });
  };

  const runExpCompare = async () => {
    if (expSelected.size < 2) return;
    try {
      const res = await fetchApi<{ items?: ExperimentRow[] }>('/api/quant/experiments/compare', {
        method: 'POST',
        body: JSON.stringify({ run_ids: Array.from(expSelected) }),
      });
      setExpCompareRows(res.items || []);
    } catch (err) {
      setExpError(getErrorMessage(err));
    }
  };

  const compileTdx = async () => {
    setTdxCompiling(true);
    try {
      const res = await fetchApi<TdxCompileResult>('/api/quant/tdx/compile', {
        method: 'POST',
        body: JSON.stringify({ formula: tdxFormula }),
      });
      setTdxCompile(res);
      setActionMessage(
        res.ok
          ? `公式编译通过：识别买入信号 ${(res.buy_signals || []).join('、') || '无'}、卖出信号 ${(res.sell_signals || []).join('、') || '无'}。`
          : `公式有 ${res.errors?.length ?? 0} 处错误，请查看编译结果。`,
      );
    } catch (err) {
      setTdxCompile({ ok: false, errors: [getErrorMessage(err)] });
    } finally {
      setTdxCompiling(false);
    }
  };

  const runTdxBacktest = async () => {
    setTdxRunning(true);
    setRunError(null);
    setActionMessage(`正在用 TDX 公式回测 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)})...`);
    try {
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<BacktestResultData>('/api/quant/backtest', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: 'tdx',
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: initialCapital,
          params: { formula: tdxFormula },
        }),
      });
      setResult(res);
      setActiveTab('overview');
      const tradeCount = res.metrics?.trade_count ?? 0;
      setActionMessage(
        tradeCount === 0
          ? 'TDX 回测完成但 0 笔交易：公式未触发买卖信号，或本金按 100 股整手买不进。可调整公式或提高本金。'
          : `TDX 回测完成：${tradeCount} 笔交易，累计收益 ${formatPercent(res.metrics?.total_return)}。已切到回测大厅查看净值曲线。`,
      );
    } catch (err) {
      const msg = getErrorMessage(err);
      setRunError(msg);
      setActionMessage(`TDX 回测失败：${msg}`);
    } finally {
      setTdxRunning(false);
    }
  };

  const runStrategyComparison = async () => {
    setCmpRunning(true);
    setCmpError(null);
    setCmpResult(null);
    setActionMessage(`正在对 ${selectedStockName}(${stripSymbolSuffix(selectedSymbol)}) 横向对比全部内置策略...`);
    try {
      const lookbackDays = Math.max(days, 120);
      const endDate = new Date();
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - lookbackDays);
      const fmt = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const res = await fetchApi<StrategyCompareData>('/api/quant/compare-strategies', {
        method: 'POST',
        body: JSON.stringify({
          symbol: stripSymbolSuffix(selectedSymbol),
          start_date: fmt(startDate),
          end_date: fmt(endDate),
          initial_capital: initialCapital,
          rank_by: cmpRankBy,
        }),
      });
      setCmpResult(res);
      const top = res.ranking?.[0];
      setActionMessage(
        `策略对比完成：评估 ${res.evaluated ?? 0} 个策略${top ? `，${cmpRankBy === 'total_return' ? '收益' : cmpRankBy === 'calmar_ratio' ? 'Calmar' : '夏普'}居首为「${top.strategy_id}」` : ''}。${res.data_source_label ? ' 数据来源：' + res.data_source_label : ''}`,
      );
    } catch (err) {
      const msg = getErrorMessage(err);
      setCmpError(msg);
      setActionMessage(`策略对比失败：${msg}`);
    } finally {
      setCmpRunning(false);
    }
  };

  const handlePoolImport = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === 'string' ? reader.result : '';
      setPoolText(text || DEFAULT_POOL_TEXT);
      setActionMessage(`已导入股票池文件「${file.name}」，真实因子结果会自动刷新。`);
    };
    reader.readAsText(file, 'utf-8');
    event.target.value = '';
  };

  const exportPool = async () => {
    let csvText = 'symbol,name,sector,composite,momentum,fund_flow,quality\n';
    csvText += poolRows
      .map((row) => `${row.stock.symbol},${row.stock.name},${row.stock.sector},${formatFactor(row.composite)},${formatFactor(row.momentum)},${formatFactor(row.fund_flow)},${row.quality}`)
      .join('\n');
    try {
      const headers = new Headers({ 'Content-Type': 'application/json' });
      if (LOCAL_API_TOKEN) {
        headers.set('X-AlphaScope-Local-Token', LOCAL_API_TOKEN);
      }
      const response = await fetch(`${API_BASE_URL}/api/quant/stock-pool/export`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ text: poolText }),
      });
      if (response.ok && response.headers.get('content-type')?.includes('text/csv')) {
        csvText = await response.text();
      }
    } catch {
      // Keep local CSV export usable when the API is unavailable.
    }
    const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'alphascope-stock-pool.csv';
    anchor.click();
    URL.revokeObjectURL(url);
    setActionMessage('已导出股票池 CSV（含真实截面因子），可用于复盘或导入其他量化工具。');
  };

  const equityData = useMemo(() => {
    if (!result?.equity_curve?.length) return [];
    return result.equity_curve.map((point, index) => ({
      index: index + 1,
      date: point.date || `D${index + 1}`,
      equity: point.equity ?? point.value ?? 0,
    }));
  }, [result]);

  const perf = result?.metrics;

  // Chip distribution chart data: price ascending so price increases upward.
  const chipChartData = useMemo(() => {
    if (!chipResult?.levels?.length) return [];
    return [...chipResult.levels]
      .sort((a, b) => a.price - b.price)
      .map((lvl) => ({
        price: lvl.price,
        priceLabel: lvl.price.toFixed(2),
        pct: lvl.pct,
        inProfit: typeof chipResult.current_price === 'number' && lvl.price <= chipResult.current_price,
      }));
  }, [chipResult]);

  const sortedPoolRows = useMemo(
    () => [...poolRows].sort((a, b) => (b.composite ?? -Infinity) - (a.composite ?? -Infinity)),
    [poolRows],
  );

  const stockOptions = useMemo(
    () => [persistedStock, ...STOCK_UNIVERSE].filter((stock, index, list) => (
      list.findIndex((item) => item.symbol === stock.symbol) === index
    )),
    [persistedStock],
  );

  // 进化收敛曲线: 逐代「最优 vs 平均」适应度。
  const evoChartData = useMemo(
    () => (evoResult?.history || []).map((h) => ({
      gen: `G${h.generation}`,
      best: typeof h.best_fitness === 'number' ? Number(h.best_fitness.toFixed(4)) : null,
      avg: typeof h.avg_fitness === 'number' ? Number(h.avg_fitness.toFixed(4)) : null,
    })),
    [evoResult],
  );

  const agentAccuracyEntries = Object.entries(agentAccuracy?.agents || {});

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.3 }}
      className="mx-auto flex h-full max-w-[1600px] flex-col p-6 lg:p-10"
    >
      <div className="relative z-10 mb-8 flex shrink-0 flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="flex items-center gap-3 text-3xl font-display font-medium text-white">
            <Cpu className="h-8 w-8 text-indigo-500" />
            量化策略引擎
            <span className="flex items-center gap-1.5 rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 align-middle font-mono text-[11px] tracking-widest text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.8)]" />
              真实回测
            </span>
          </h2>
          <p className="mt-2 text-sm font-mono tracking-wide text-neutral-400">调用后端 BacktestEngine 运行策略、股票池真实因子筛查与决策后验</p>
        </div>

        <div className="flex rounded-xl border border-white/5 bg-black/60 p-1.5">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                data-testid={`backtest-tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={cn('relative flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all', activeTab === tab.id ? 'text-white' : 'text-neutral-500 hover:text-neutral-300')}
              >
                {activeTab === tab.id && (
                  <motion.div layoutId="backtest-tab" className="absolute inset-0 rounded-lg border border-white/10 bg-white/10" />
                )}
                <Icon className="relative z-10 h-4 w-4" />
                <span className="relative z-10">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="relative z-10 flex-1 overflow-y-auto custom-scrollbar">
        <div className="mb-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-2 text-[11px] leading-relaxed text-rose-200/80">
          <ShieldAlert className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
          本页所有回测结果<strong className="font-medium text-rose-100"> 仅用于历史研究与策略逻辑验证，不代表未来收益，不构成任何投资建议</strong>。回测已计入佣金、印花税（卖方）、滑点等真实摩擦成本，详见下方「本次回测假设」。
        </div>
        <div className="mb-5 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3 text-xs text-indigo-100/80">
          {actionMessage}
        </div>
        <AnimatePresence mode="wait">
          {activeTab === 'overview' && (
            <motion.div key="overview" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">回测标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e) => {
                      const stock = stockOptions.find((item) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">策略</p>
                  <select
                    value={selectedStrategy}
                    onChange={(e) => setSelectedStrategy(e.target.value)}
                    className="mt-1 max-w-[180px] bg-transparent text-sm text-emerald-300 outline-none"
                  >
                    {strategies.length === 0 && <option value="">{strategiesAsync.loading ? '加载策略...' : '暂无策略'}</option>}
                    {strategies.map((strategy) => (
                      <option key={strategy.id || strategy.name} value={strategy.id || strategy.name} className="bg-[#0f0f15] text-neutral-200">
                        {strategy.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">回测天数</p>
                  <input
                    type="number"
                    min={30}
                    max={1000}
                    value={days}
                    onChange={(e) => setDays(Math.max(30, Math.min(1000, Number(e.target.value) || 120)))}
                    className="mt-1 w-20 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">初始资金</p>
                  <input
                    type="number"
                    min={10000}
                    value={initialCapital}
                    onChange={(e) => setInitialCapital(Math.max(10000, Number(e.target.value) || 1000000))}
                    className="mt-1 w-28 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <button
                  onClick={runTest}
                  disabled={running || !selectedStrategy}
                  className="flex items-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-600 px-8 py-2.5 text-xs font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.2)] transition-all hover:bg-indigo-500 disabled:opacity-50"
                >
                  {running ? <Activity className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {running ? '引擎计算中...' : '启动真实回测'}
                </button>
              </div>

              {runError && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  回测失败：{runError}（请确认该标的有足够行情数据，至少 30 条）
                </div>
              )}

              <div className="mb-8 grid grid-cols-1 gap-6 lg:grid-cols-4">
                <MetricCard label="累计收益" value={perf ? formatPercent(perf.total_return) : '--'} hint={perf ? `年化 ${formatPercent(perf.annual_return)}` : '运行回测后显示'} icon={TrendingUp} tone="rose" />
                <MetricCard label="最大回撤" value={perf ? formatPercent(perf.max_drawdown) : '--'} hint={perf ? `Calmar ${formatFactor(perf.calmar_ratio)}` : '运行回测后显示'} icon={ShieldAlert} tone="emerald" />
                <MetricCard label="胜率" value={perf ? `${formatFactor(perf.win_rate)}%` : '--'} hint={perf ? `共 ${perf.trade_count ?? 0} 笔交易` : '运行回测后显示'} icon={Flag} tone="indigo" />
                <MetricCard label="夏普比率" value={perf ? formatFactor(perf.sharpe_ratio) : '--'} hint={perf ? `Sortino ${formatFactor(perf.sortino_ratio)}` : '运行回测后显示'} icon={BarChart} />
              </div>

              {perf?.has_benchmark && (
                <div className="mb-8 grid grid-cols-1 gap-6 lg:grid-cols-4">
                  <MetricCard
                    label={`超额收益(${perf.benchmark_name || '基准'})`}
                    value={formatPercent(perf.excess_return)}
                    hint="策略总收益 − 基准总收益"
                    icon={TrendingUp}
                    tone={Number(perf.excess_return) >= 0 ? 'rose' : 'emerald'}
                  />
                  <MetricCard
                    label="信息比率"
                    value={formatFactor(perf.information_ratio)}
                    hint="年化超额 / 跟踪误差"
                    icon={BarChart}
                  />
                  <MetricCard label="Beta" value={formatFactor(perf.beta)} hint="相对基准的波动敏感度" icon={Activity} />
                  <MetricCard label="Alpha" value={formatFactor(perf.alpha)} hint="Jensen's alpha(年化)" icon={CheckCircle2} tone="indigo" />
                </div>
              )}

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
                <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-xl xl:col-span-2">
                  <h3 className="mb-6 border-b border-white/5 pb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">
                    净值曲线 {result ? `· ${result.strategy_id} / ${result.symbol}${result.summary?.data_source_label ? ' · ' + result.summary.data_source_label : ''}` : '· 待运行'}
                  </h3>
                  <div className="h-80 w-full">
                    {equityData.length ? (
                      <StableChartContainer>
                        <LineChart data={equityData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                          <XAxis dataKey="date" stroke="#737373" fontSize={11} tickLine={false} />
                          <YAxis stroke="#737373" fontSize={11} tickFormatter={(val) => `${(Number(val) / 1000).toFixed(0)}k`} />
                          <Tooltip contentStyle={{ backgroundColor: 'rgba(0,0,0,0.82)', borderColor: 'rgba(255,255,255,0.12)', borderRadius: '12px', fontSize: '12px' }} />
                          <ReferenceLine y={initialCapital} stroke="#737373" strokeDasharray="4 4" />
                          <Line type="monotone" dataKey="equity" name="策略净值" stroke="#f43f5e" strokeWidth={2.5} dot={false} animationDuration={800} animationEasing="ease-out" />
                        </LineChart>
                      </StableChartContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-neutral-500">选择标的与策略后点击「启动真实回测」生成净值曲线</div>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
                  <h3 className="mb-4 text-xs font-mono uppercase tracking-widest text-neutral-400">风控违规</h3>
                  {result?.risk_violations?.length ? (
                    result.risk_violations.map((viol, index) => (
                      <div key={index} className="mb-3 rounded-xl border border-rose-500/15 bg-rose-500/5 p-4">
                        <div className="mb-1 flex items-center gap-2 text-sm font-medium text-rose-200">
                          <ShieldAlert className="h-4 w-4" />
                          {viol.rule || `违规 ${index + 1}`}
                        </div>
                        <p className="text-xs leading-relaxed text-neutral-400">{viol.reason}{viol.date ? ` · ${viol.date}` : ''}</p>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 p-4 text-xs text-emerald-300">
                      <CheckCircle2 className="mb-1 h-4 w-4" />
                      {result ? '本次回测未触发风控违规。' : '运行回测后展示风控引擎违规记录。'}
                    </div>
                  )}
                </div>
              </div>

              {result && (
                <>
                  <div className="mb-6">
                    <AssumptionsCard assumptions={result.assumptions} />
                  </div>

                  {/* QuantStats 完整绩效报告(接出 performance_report) */}
                  <div className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="flex items-center gap-2 text-sm font-semibold text-neutral-100">
                          <Activity className="h-4 w-4 text-indigo-400" />
                          卖方级绩效报告(QuantStats)
                        </h3>
                        <p className="mt-1 text-[11px] text-neutral-500">
                          基于本次回测净值曲线,计算夏普/Sortino/卡玛/最大回撤/胜率等数十项专业指标。
                          <span className="text-neutral-600"> 绩效基于历史数据,不代表未来收益。</span>
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={computeQuantStats}
                        disabled={qsLoading || !result.equity_curve?.length}
                        className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-indigo-500/30 bg-indigo-500/15 px-3 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-40"
                      >
                        {qsLoading ? '计算中…' : qsMetrics ? '刷新绩效' : '生成绩效报告'}
                      </button>
                    </div>
                    {!qsAvailable && (
                      <p className="mt-3 text-xs text-amber-400">
                        quantstats 未安装,无法生成完整报告。可执行 <code className="font-mono">pip install quantstats</code> 启用。
                      </p>
                    )}
                    {qsError && <p className="mt-3 text-xs text-rose-400">{qsError}</p>}
                    {qsMetrics && (
                      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                        {Object.entries(qsMetrics)
                          .filter(([, v]) => v !== null && v !== undefined && v !== '' && !(typeof v === 'string' && v.trim() === ''))
                          .slice(0, 32)
                          .map(([k, v]) => (
                            <div key={k} className="rounded-lg border border-white/5 bg-black/30 px-3 py-2">
                              <p className="text-[10px] font-mono uppercase tracking-wide text-neutral-500">{k}</p>
                              <p className="mt-0.5 font-mono text-xs text-neutral-200">
                                {typeof v === 'number' ? v.toFixed(4).replace(/\.?0+$/, '') : String(v)}
                              </p>
                            </div>
                          ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <TradeTable trades={result.trades} />
                  </div>
                </>
              )}
            </motion.div>
          )}

          {activeTab === 'workshop' && (
            <motion.div key="workshop" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="min-h-[500px] overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                <div className="flex items-center justify-between border-b border-white/5 bg-black/40 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-medium text-white">
                    <Code2 className="h-4 w-4 text-indigo-400" />
                    通达信(TDX)公式编译器
                  </h3>
                  <span className="flex items-center gap-1.5 rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-mono text-emerald-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    可编译回测
                  </span>
                </div>
                <div className="p-5">
                  <textarea
                    value={tdxFormula}
                    onChange={(e) => setTdxFormula(e.target.value)}
                    spellCheck={false}
                    className="h-56 w-full resize-none rounded-xl border border-white/10 bg-[#050505] p-4 font-mono text-[13px] leading-relaxed text-emerald-200/90 outline-none focus:border-indigo-500/50"
                  />
                  <p className="mt-2 text-[10px] leading-relaxed text-neutral-600">
                    支持 CLOSE/OPEN/HIGH/LOW/VOL · MA/EMA/SMA/REF/CROSS/HHV/LLV/SUM/COUNT/MAX/MIN/ABS/IF/STD ·
                    赋值 := · 输出 : · ENTERLONG/EXITLONG(或 BUY/SELL)定义买卖。防未来函数,T+1 成交。
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      onClick={compileTdx}
                      disabled={tdxCompiling}
                      className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 py-2 text-xs text-neutral-200 hover:bg-white/[0.08] disabled:opacity-50"
                    >
                      {tdxCompiling ? <Activity className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                      编译校验
                    </button>
                    <button
                      onClick={runTdxBacktest}
                      disabled={tdxRunning}
                      className="flex items-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                    >
                      {tdxRunning ? <Activity className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5 fill-current" />}
                      直接回测（{stripSymbolSuffix(selectedSymbol)}）
                    </button>
                    <button
                      onClick={() => { setTdxFormula(DEFAULT_TDX_FORMULA); setTdxCompile(null); }}
                      className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-neutral-500 hover:text-neutral-300"
                    >
                      恢复示例
                    </button>
                  </div>

                  {tdxCompile && (
                    <div className={cn('mt-4 rounded-xl border p-4', tdxCompile.ok ? 'border-emerald-500/15 bg-emerald-500/[0.04]' : 'border-rose-500/20 bg-rose-500/[0.05]')}>
                      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
                        {tdxCompile.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <ShieldAlert className="h-4 w-4 text-rose-400" />}
                        <span className={tdxCompile.ok ? 'text-emerald-300' : 'text-rose-300'}>
                          {tdxCompile.ok ? '编译通过' : '编译有错误'}
                        </span>
                      </div>
                      {tdxCompile.ok && (
                        <div className="space-y-1 text-[11px] font-mono text-neutral-400">
                          <p>买入信号：<span className="text-indigo-300">{(tdxCompile.buy_signals || []).join('、') || '— 未定义'}</span></p>
                          <p>卖出信号：<span className="text-rose-300">{(tdxCompile.sell_signals || []).join('、') || '— 未定义'}</span></p>
                          <p>中间变量：<span className="text-neutral-300">{(tdxCompile.var_names || []).join('、') || '—'}</span></p>
                          <p>数据引用：<span className="text-neutral-300">{(tdxCompile.refs_used || []).join('、') || '—'}</span></p>
                        </div>
                      )}
                      {(tdxCompile.errors || []).map((e, i) => (
                        <p key={i} className="text-[11px] leading-relaxed text-rose-300/90">• {e}</p>
                      ))}
                      {(tdxCompile.warnings || []).map((w, i) => (
                        <p key={i} className="text-[11px] leading-relaxed text-amber-300/80">⚠ {w}</p>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="min-h-[500px] rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-xl">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-white">内置策略管理器</h3>
                  <button onClick={() => strategiesAsync.refresh()} className="text-xs font-medium text-indigo-400 hover:text-indigo-300">
                    {strategiesAsync.loading ? '加载中...' : '刷新'}
                  </button>
                </div>
                {strategiesAsync.error && (
                  <p className="mb-3 text-xs text-rose-300">策略加载失败：{strategiesAsync.error}</p>
                )}
                {strategies.map((strategy) => (
                  <div
                    key={strategy.id || strategy.name}
                    onClick={() => setSelectedStrategy(strategy.id || strategy.name)}
                    className={cn(
                      'mb-3 flex cursor-pointer items-start justify-between rounded-xl border p-4 transition-colors',
                      selectedStrategy === strategy.name ? 'border-indigo-500/40 bg-indigo-500/10' : 'border-white/5 bg-black/25 hover:border-white/15',
                    )}
                  >
                    <div>
                      <h4 className="text-sm font-medium text-neutral-200">{strategy.name}</h4>
                      <p className="mt-1 text-[11px] leading-relaxed text-neutral-500">{strategy.description || '内置量化策略'}</p>
                    </div>
                    <span className={cn('rounded-lg border px-2.5 py-1 text-xs', selectedStrategy === strategy.name ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300' : 'border-white/10 bg-black/30 text-neutral-500')}>
                      {selectedStrategy === strategy.name ? '已选用' : '可选'}
                    </span>
                  </div>
                ))}
                {strategies.length === 0 && !strategiesAsync.loading && (
                  <p className="text-xs text-neutral-500">暂无可用策略，请确认后端 /api/quant/strategies 可用。</p>
                )}
              </div>
            </motion.div>
          )}

          {activeTab === 'pool' && (
            <motion.div key="pool" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid grid-cols-1 gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
              <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-xl">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-white">股票池解析</h3>
                    <p className="mt-1 text-xs text-neutral-500">支持粘贴 BLK / CSV / 代码列表，自动识别 A 股标的。</p>
                  </div>
                  <input ref={fileInputRef} type="file" accept=".txt,.csv,.blk" onChange={handlePoolImport} className="hidden" />
                  <button data-testid="backtest-import-pool" onClick={() => fileInputRef.current?.click()} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 hover:bg-white/[0.06]">
                    <Upload className="h-4 w-4" />
                    导入文件
                  </button>
                </div>
                <textarea
                  value={poolText}
                  onChange={(event) => setPoolText(event.target.value)}
                  className="h-64 w-full resize-none rounded-xl border border-white/10 bg-black/40 p-4 font-mono text-xs leading-relaxed text-neutral-200 outline-none focus:border-indigo-500/50"
                />
                <div className="mt-4 grid grid-cols-3 gap-3 text-center text-xs">
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">识别标的</p>
                    <p className="mt-1 text-xl font-mono text-white">{poolStocks.length}</p>
                  </div>
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">最高综合因子</p>
                    <p className="mt-1 text-xl font-mono text-rose-400">{sortedPoolRows[0]?.composite != null ? formatFactor(sortedPoolRows[0].composite) : '--'}</p>
                  </div>
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">高完整度</p>
                    <p className="mt-1 text-xl font-mono text-emerald-400">{poolRows.filter((row) => row.quality >= 80).length}</p>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                <div className="flex items-center justify-between border-b border-white/5 bg-black/35 p-5">
                  <div>
                    <h3 className="text-sm font-semibold text-white">真实截面因子</h3>
                    <p className="mt-1 text-[11px] text-neutral-500">{poolSource || '逐标的调用 /api/factors 计算真实因子'}</p>
                  </div>
                  <button data-testid="backtest-export-pool" onClick={exportPool} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 hover:bg-white/[0.06]">
                    <Download className="h-4 w-4" />
                    导出股票池
                  </button>
                </div>
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="border-b border-white/5 bg-black/20 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                    <tr>
                      <th className="px-5 py-3">标的</th>
                      <th className="px-5 py-3">行业</th>
                      <th className="px-5 py-3 text-right">综合因子</th>
                      <th className="px-5 py-3 text-right">价格动量</th>
                      <th className="px-5 py-3 text-right">资金因子</th>
                      <th className="px-5 py-3 text-right">完整度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {poolLoading && (
                      <tr>
                        <td colSpan={6} className="px-5 py-8 text-center text-xs text-neutral-500">正在计算真实截面因子...</td>
                      </tr>
                    )}
                    {!poolLoading && sortedPoolRows.map((row) => (
                      <tr key={row.stock.symbol} className="border-b border-white/5 hover:bg-white/[0.025]">
                        <td className="px-5 py-3.5">
                          <p className="font-medium text-neutral-200">{row.stock.name}</p>
                          <p className="mt-1 font-mono text-[10px] text-indigo-300">{row.stock.symbol}</p>
                        </td>
                        <td className="px-5 py-3.5 text-neutral-400">{row.stock.sector}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-rose-400">{row.error ? '--' : formatFactor(row.composite)}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-300">{row.error ? '--' : formatFactor(row.momentum)}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-300">{row.error ? '--' : formatFactor(row.fund_flow)}</td>
                        <td className={cn('px-5 py-3.5 text-right font-mono', row.quality >= 80 ? 'text-emerald-400' : 'text-amber-300')}>{row.error ? <span className="text-rose-400">失败</span> : row.quality}</td>
                      </tr>
                    ))}
                    {!poolLoading && sortedPoolRows.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-5 py-8 text-center text-xs text-neutral-500">暂无识别标的，请在左侧填入股票代码。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}

          {activeTab === 'compare' && (
            <motion.div key="compare" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-6">
              <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
                <MetricCard label="已评估决策" value={stats ? `${stats.evaluated ?? 0}/${stats.total ?? 0}` : '--'} hint="后验验证统计" icon={CheckCircle2} tone="emerald" />
                <MetricCard label="买入准确率(5日)" value={stats?.buy_signals?.accuracy_5d != null ? `${formatFactor(stats.buy_signals.accuracy_5d)}%` : '--'} hint={stats?.buy_signals ? `${stats.buy_signals.count ?? 0} 个买入信号` : '尚无评估'} icon={TrendingUp} tone="indigo" />
                <MetricCard label="待评估" value={`${pending.length}`} hint="尚未到评估窗口的决策" icon={Activity} tone="amber" />
                <MetricCard label="参与 Agent" value={`${agentAccuracyEntries.length}`} hint="有后验准确率的 Agent 数" icon={BarChart} />
              </div>

              {compareError && (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
                  后验数据获取异常：{compareError}（若尚无已评估决策，属正常空状态）
                </div>
              )}

              <div className="overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                <div className="border-b border-white/5 bg-black/35 p-5">
                  <h3 className="text-sm font-semibold text-white">待评估决策明细</h3>
                  <p className="mt-1 text-xs text-neutral-500">来自 /api/backtest/pending，用于跟踪信号兑现进度。</p>
                </div>
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="border-b border-white/5 bg-black/20 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                    <tr>
                      <th className="px-5 py-3">决策 ID</th>
                      <th className="px-5 py-3">标的</th>
                      <th className="px-5 py-3">信号</th>
                      <th className="px-5 py-3 text-right">价格</th>
                      <th className="px-5 py-3 text-right">已过天数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compareLoading && (
                      <tr><td colSpan={5} className="px-5 py-8 text-center text-xs text-neutral-500">正在同步后验数据...</td></tr>
                    )}
                    {!compareLoading && pending.map((item) => (
                      <tr key={item.decision_id} className="border-b border-white/5 hover:bg-white/[0.025]">
                        <td className="px-5 py-3.5 font-mono text-neutral-500">{item.decision_id}</td>
                        <td className="px-5 py-3.5 font-mono text-indigo-300">{item.symbol}</td>
                        <td className="px-5 py-3.5 text-neutral-300">{item.signal}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-200">{item.price ?? '--'}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-400">{item.days_elapsed != null ? `${item.days_elapsed.toFixed(1)}` : '--'}</td>
                      </tr>
                    ))}
                    {!compareLoading && pending.length === 0 && (
                      <tr><td colSpan={5} className="px-5 py-8 text-center text-xs text-neutral-500">暂无待评估决策。运行分析并积累决策后会出现后验记录。</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}

          {activeTab === 'walkforward' && (
            <motion.div key="walkforward" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-indigo-500/15 bg-indigo-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-indigo-100/75">
                <GitBranch className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                样本外走查把历史切成顺序的「样本内(IS)+样本外(OOS)」窗口，逐窗用<strong className="font-medium text-indigo-50"> 同一策略 </strong>回测，看收益是<strong className="font-medium text-indigo-50"> 跨区间稳健 </strong>还是<strong className="font-medium text-indigo-50"> 集中在某一段运气</strong>(过拟合)。这是对回测大厅单段收益的稳健性体检。
              </div>

              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e) => {
                      const stock = stockOptions.find((item) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">策略</p>
                  <select
                    value={selectedStrategy}
                    onChange={(e) => setSelectedStrategy(e.target.value)}
                    className="mt-1 max-w-[180px] bg-transparent text-sm text-emerald-300 outline-none"
                  >
                    {strategies.length === 0 && <option value="">{strategiesAsync.loading ? '加载策略...' : '暂无策略'}</option>}
                    {strategies.map((strategy) => (
                      <option key={strategy.id || strategy.name} value={strategy.id || strategy.name} className="bg-[#0f0f15] text-neutral-200">
                        {strategy.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="mb-1 text-[10px] font-mono uppercase tracking-widest text-neutral-500">切分方案</p>
                  <div className="flex overflow-hidden rounded-lg border border-white/10">
                    {(['anchored', 'rolling'] as const).map((s) => (
                      <button
                        key={s}
                        onClick={() => setWfScheme(s)}
                        className={cn('px-3 py-1 text-xs transition-colors', wfScheme === s ? 'bg-indigo-600 text-white' : 'bg-transparent text-neutral-400 hover:text-neutral-200')}
                      >
                        {s === 'anchored' ? '锚定' : '滚动'}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">样本外窗口数</p>
                  <input
                    type="number"
                    min={2}
                    max={12}
                    value={wfSplits}
                    onChange={(e) => setWfSplits(Math.max(2, Math.min(12, Number(e.target.value) || 5)))}
                    className="mt-1 w-16 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <button
                  onClick={runWalkForward}
                  disabled={wfRunning || !selectedStrategy}
                  className="flex items-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-600 px-8 py-2.5 text-xs font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.2)] transition-all hover:bg-indigo-500 disabled:opacity-50"
                >
                  {wfRunning ? <Activity className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {wfRunning ? '走查计算中...' : '运行样本外走查'}
                </button>
              </div>

              {wfError && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  走查失败：{wfError}（样本外切分需要更长历史，建议至少 120 个交易日）
                </div>
              )}

              {wfResult && wfResult.status === 'insufficient' && (
                <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
                  {wfResult.note || '历史数据不足以做样本外切分。'}
                </div>
              )}

              {wfResult && wfResult.status !== 'insufficient' && wfResult.aggregate && (
                <>
                  <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-4">
                    <MetricCard
                      label="一致性评分"
                      value={`${formatFactor(wfResult.aggregate.consistency_score)}`}
                      hint="0-100 · 样本外越一致越高"
                      icon={Gauge}
                      tone={wfResult.aggregate.consistency_score >= 70 ? 'emerald' : wfResult.aggregate.consistency_score >= 45 ? 'amber' : 'rose'}
                    />
                    <MetricCard
                      label="样本外胜率"
                      value={`${formatFactor(wfResult.aggregate.pct_profitable_windows)}%`}
                      hint={`${wfResult.aggregate.profitable_windows}/${wfResult.aggregate.windows_evaluated} 个窗口为正`}
                      icon={Flag}
                      tone="indigo"
                    />
                    <MetricCard
                      label="样本外收益均值"
                      value={formatPercent(wfResult.aggregate.mean_oos_return)}
                      hint={`中位 ${formatPercent(wfResult.aggregate.median_oos_return)} · 离散 ${formatFactor(wfResult.aggregate.std_oos_return)}`}
                      icon={TrendingUp}
                      tone={wfResult.aggregate.mean_oos_return >= 0 ? 'rose' : 'emerald'}
                    />
                    <MetricCard
                      label="平均走查效率 WFE"
                      value={formatFactor(wfResult.aggregate.mean_wfe)}
                      hint="OOS 年化 / IS 年化 · 越接近 1 越稳"
                      icon={BarChart}
                    />
                  </div>

                  <div
                    className={cn(
                      'mb-6 rounded-xl border px-4 py-3 text-xs leading-relaxed',
                      wfResult.aggregate.robustness.includes('稳健') ? 'border-emerald-500/20 bg-emerald-500/[0.06] text-emerald-100/85'
                        : wfResult.aggregate.robustness.includes('脆弱') ? 'border-rose-500/20 bg-rose-500/[0.06] text-rose-100/85'
                        : 'border-amber-500/20 bg-amber-500/[0.06] text-amber-100/85',
                    )}
                  >
                    <strong className="font-medium">稳健性判定：{wfResult.aggregate.robustness}</strong>
                    <span className="text-neutral-400">
                      {' '}· {wfResult.scheme === 'rolling' ? '滚动' : '锚定'}方案 · {wfResult.n_windows} 个样本外窗口
                      {typeof wfResult.full_period?.total_return === 'number' && (
                        <> · 全样本累计收益 {formatPercent(wfResult.full_period.total_return)} vs 样本外收益均值 {formatPercent(wfResult.aggregate.mean_oos_return)}（差距越大越要警惕过拟合）</>
                      )}
                    </span>
                  </div>

                  <div className="mb-6 overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                    <div className="border-b border-white/5 bg-black/35 p-5">
                      <h3 className="text-sm font-semibold text-white">逐窗口样本外明细</h3>
                      <p className="mt-1 text-[11px] text-neutral-500">每个窗口先用样本内(IS)区间走完，再在紧邻的样本外(OOS)区间逐 bar 评估，OOS 收益以分界权益重新归一。</p>
                    </div>
                    <div className="max-h-[420px] overflow-auto custom-scrollbar">
                      <table className="w-full border-collapse text-left text-xs">
                        <thead className="sticky top-0 border-b border-white/5 bg-black/40 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                          <tr>
                            <th className="px-4 py-3">窗口</th>
                            <th className="px-4 py-3">样本内区间</th>
                            <th className="px-4 py-3">样本外区间</th>
                            <th className="px-4 py-3 text-right">IS收益</th>
                            <th className="px-4 py-3 text-right">OOS收益</th>
                            <th className="px-4 py-3 text-right">WFE</th>
                            <th className="px-4 py-3 text-right">OOS夏普</th>
                            <th className="px-4 py-3 text-right">OOS笔数</th>
                            <th className="px-4 py-3 text-center">结果</th>
                          </tr>
                        </thead>
                        <tbody className="font-mono text-neutral-300">
                          {(wfResult.windows || []).map((w) => (
                            <tr key={w.index} className="border-b border-white/5 hover:bg-white/[0.025]">
                              <td className="px-4 py-3 text-neutral-400">#{w.index + 1}</td>
                              <td className="px-4 py-3 text-[11px] text-neutral-500">{w.is_start_date} → {w.is_end_date}<span className="ml-1 text-neutral-600">({w.is_bars})</span></td>
                              <td className="px-4 py-3 text-[11px] text-indigo-300/80">{w.oos_start_date} → {w.oos_end_date}<span className="ml-1 text-neutral-600">({w.oos_bars})</span></td>
                              <td className="px-4 py-3 text-right text-neutral-400">{formatPercent(w.is_return)}</td>
                              <td className={cn('px-4 py-3 text-right', w.oos_return >= 0 ? 'text-rose-300' : 'text-emerald-300')}>{formatPercent(w.oos_return)}</td>
                              <td className="px-4 py-3 text-right text-neutral-300">{formatFactor(w.wfe)}</td>
                              <td className="px-4 py-3 text-right text-neutral-400">{formatFactor(w.oos_sharpe)}</td>
                              <td className="px-4 py-3 text-right text-neutral-400">{w.oos_trades}</td>
                              <td className="px-4 py-3 text-center">
                                <span className={cn('rounded px-1.5 py-0.5 text-[10px]', w.oos_profitable ? 'bg-rose-500/10 text-rose-300' : 'bg-emerald-500/10 text-emerald-300')}>
                                  {w.oos_profitable ? '盈利' : '亏损'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="mb-6">
                    <AssumptionsCard assumptions={wfResult.assumptions} />
                  </div>

                  {wfResult.disclaimer && (
                    <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-2.5 text-[11px] leading-relaxed text-rose-200/80">
                      <ShieldAlert className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                      {wfResult.disclaimer}
                    </div>
                  )}
                </>
              )}

              {!wfResult && !wfError && (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-white/5 bg-white/[0.02] text-xs text-neutral-500">
                  选择标的、策略与切分方案后点击「运行样本外走查」，评估策略在不同历史区间的稳健性。
                </div>
              )}
            </motion.div>
          )}
          {activeTab === 'evolution' && (
            <motion.div key="evolution" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-fuchsia-500/15 bg-fuchsia-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-fuchsia-100/75">
                <Dna className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                策略进化用<strong className="font-medium text-fuchsia-50"> 确定性遗传算法 </strong>(同种子同结果)在策略的<strong className="font-medium text-fuchsia-50"> 数值参数空间 </strong>里搜索更优组合,适应度=复用回测引擎跑一遍的绩效。注意:这是<strong className="font-medium text-rose-200"> 样本内寻优,极易过拟合 </strong>—— 样本内最优≠未来有效,务必对最优参数再做样本外走查验证。
              </div>

              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e) => {
                      const stock = stockOptions.find((item) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-fuchsia-300 outline-none"
                  >
                    {stockOptions.map((stock) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">策略</p>
                  <select
                    value={selectedStrategy}
                    onChange={(e) => setSelectedStrategy(e.target.value)}
                    className="mt-1 max-w-[160px] bg-transparent text-sm text-emerald-300 outline-none"
                  >
                    {strategies.length === 0 && <option value="">{strategiesAsync.loading ? '加载策略...' : '暂无策略'}</option>}
                    {strategies.map((strategy) => (
                      <option key={strategy.id || strategy.name} value={strategy.id || strategy.name} className="bg-[#0f0f15] text-neutral-200">
                        {strategy.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">适应度</p>
                  <select
                    value={evoMetric}
                    onChange={(e) => setEvoMetric(e.target.value as typeof evoMetric)}
                    className="mt-1 bg-transparent text-sm text-fuchsia-300 outline-none"
                  >
                    <option value="sharpe_ratio" className="bg-[#0f0f15]">夏普比率</option>
                    <option value="calmar_ratio" className="bg-[#0f0f15]">卡玛比率</option>
                    <option value="sortino_ratio" className="bg-[#0f0f15]">索提诺比率</option>
                    <option value="total_return" className="bg-[#0f0f15]">累计收益</option>
                    <option value="win_rate" className="bg-[#0f0f15]">胜率</option>
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">种群</p>
                  <input
                    type="number"
                    min={4}
                    max={40}
                    value={evoPop}
                    onChange={(e) => setEvoPop(Math.max(4, Math.min(40, Number(e.target.value) || 16)))}
                    className="mt-1 w-14 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">代数</p>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={evoGens}
                    onChange={(e) => setEvoGens(Math.max(1, Math.min(20, Number(e.target.value) || 8)))}
                    className="mt-1 w-14 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">随机种子</p>
                  <input
                    type="number"
                    value={evoSeed}
                    onChange={(e) => setEvoSeed(Number(e.target.value) || 0)}
                    className="mt-1 w-16 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <button
                  onClick={runEvolution}
                  disabled={evoRunning || !selectedStrategy}
                  className="flex items-center gap-2 rounded-lg border border-fuchsia-500/50 bg-fuchsia-600 px-8 py-2.5 text-xs font-medium text-white shadow-[0_0_20px_rgba(217,70,239,0.2)] transition-all hover:bg-fuchsia-500 disabled:opacity-50"
                >
                  {evoRunning ? <Activity className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {evoRunning ? '进化中...' : '运行参数寻优'}
                </button>
              </div>

              {evoError && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  策略进化失败：{evoError}（参数寻优需要较长历史，建议至少回看一年）
                </div>
              )}

              {evoResult && evoResult.status === 'insufficient' && (
                <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
                  {evoResult.message || '历史样本不足以寻优。'}
                </div>
              )}
              {evoResult && evoResult.status === 'degraded' && (
                <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
                  {evoResult.message || '该策略无可寻优的数值参数。'}
                </div>
              )}
              {evoResult && evoResult.status === 'error' && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  {evoResult.message || '寻优无有效结果。'}
                </div>
              )}

              {evoResult && evoResult.status === 'ok' && evoResult.best && (() => {
                const best = evoResult.best!;
                const imp = typeof evoResult.improvement === 'number' ? evoResult.improvement : null;
                const impStr = imp === null ? '--' : `${imp >= 0 ? '+' : ''}${imp.toFixed(3)}`;
                const metricLabel = EVO_METRIC_LABELS[evoResult.fitness_metric || ''] || evoResult.fitness_metric || '';
                const m = best.metrics || {};
                const bm = evoResult.baseline?.metrics || {};
                return (
                  <>
                    <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-4">
                      <MetricCard
                        label="最优适应度"
                        value={formatFactor(best.fitness ?? 0)}
                        hint={`指标 · ${metricLabel}`}
                        icon={Trophy}
                        tone="emerald"
                      />
                      <MetricCard
                        label="较默认提升"
                        value={impStr}
                        hint="最优 − 默认参数"
                        icon={TrendingUp}
                        tone={imp !== null && imp >= 0 ? 'rose' : 'emerald'}
                      />
                      <MetricCard
                        label="去重评估次数"
                        value={`${evoResult.evaluations ?? 0}`}
                        hint="实际回测调用数"
                        icon={Cpu}
                        tone="indigo"
                      />
                      <MetricCard
                        label="搜索规模"
                        value={`${evoResult.generations ?? 0}×${evoResult.population_size ?? 0}`}
                        hint="代数 × 种群"
                        icon={Dna}
                      />
                    </div>

                    <div className="mb-6 rounded-2xl border border-fuchsia-500/15 bg-fuchsia-500/[0.04] p-5">
                      <div className="mb-3 flex flex-wrap items-center gap-2">
                        <Trophy className="h-4 w-4 text-fuchsia-300" />
                        <h3 className="text-sm font-semibold text-white">最优参数</h3>
                        <span className="text-[11px] text-neutral-500">seed {evoResult.seed} · 可复现</span>
                      </div>
                      <div className="mb-3 flex flex-wrap gap-2">
                        {Object.entries(best.genome || {}).map(([k, v]) => (
                          <span key={k} className="rounded-lg border border-fuchsia-500/25 bg-black/30 px-3 py-1 text-xs font-mono text-fuchsia-200">
                            {k} = <strong className="text-white">{Number.isInteger(v) ? v : Number(v).toFixed(3)}</strong>
                          </span>
                        ))}
                      </div>
                      <div className="font-mono text-[11px] text-neutral-400">
                        该组合回测：收益 {formatPercent(m.total_return)} · 夏普 {formatFactor(m.sharpe_ratio)} · 回撤 {formatPercent(m.max_drawdown)} · 胜率 {formatFactor(m.win_rate)}% · {m.total_trades ?? 0}笔
                      </div>
                      {evoResult.baseline && (
                        <div className="mt-1 font-mono text-[11px] text-neutral-500">
                          默认参数对照：{metricLabel} {formatFactor(evoResult.baseline.fitness ?? 0)} · 收益 {formatPercent(bm.total_return)}
                        </div>
                      )}
                      <button
                        onClick={() => setActiveTab('walkforward')}
                        className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200 transition-colors hover:bg-emerald-500/20"
                      >
                        <GitBranch className="h-3.5 w-3.5" /> 去对最优参数做样本外走查验证
                      </button>
                    </div>

                    <div className="mb-6 rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-xl">
                      <h3 className="mb-1 text-sm font-semibold text-white">进化收敛曲线</h3>
                      <p className="mb-4 text-[11px] text-neutral-500">逐代「种群最优 vs 平均」适应度。最优单调不降(精英保留),平均抬升说明种群整体在向更优区域聚拢。</p>
                      <div className="h-64">
                        <StableChartContainer>
                          <LineChart data={evoChartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                            <XAxis dataKey="gen" stroke="#737373" fontSize={11} tickLine={false} />
                            <YAxis stroke="#737373" fontSize={11} />
                            <Tooltip contentStyle={{ backgroundColor: 'rgba(0,0,0,0.82)', borderColor: 'rgba(255,255,255,0.12)', borderRadius: '12px', fontSize: '12px' }} />
                            <Line type="monotone" dataKey="best" name="种群最优" stroke="#e879f9" strokeWidth={2.5} dot={false} animationDuration={700} />
                            <Line type="monotone" dataKey="avg" name="种群平均" stroke="#737373" strokeWidth={1.5} strokeDasharray="4 4" dot={false} animationDuration={700} />
                          </LineChart>
                        </StableChartContainer>
                      </div>
                    </div>

                    <div className="mb-6 overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                      <div className="border-b border-white/5 bg-black/35 p-5">
                        <h3 className="text-sm font-semibold text-white">逐代明细</h3>
                        <p className="mt-1 text-[11px] text-neutral-500">{evoResult.message}</p>
                      </div>
                      <div className="max-h-[360px] overflow-auto custom-scrollbar">
                        <table className="w-full border-collapse text-left text-xs">
                          <thead className="sticky top-0 border-b border-white/5 bg-black/40 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                            <tr>
                              <th className="px-4 py-3">代</th>
                              <th className="px-4 py-3 text-right">最优适应度</th>
                              <th className="px-4 py-3 text-right">平均适应度</th>
                              <th className="px-4 py-3">该代最优参数</th>
                            </tr>
                          </thead>
                          <tbody className="font-mono text-neutral-300">
                            {(evoResult.history || []).map((h) => (
                              <tr key={h.generation} className="border-b border-white/5 hover:bg-white/[0.025]">
                                <td className="px-4 py-3 text-neutral-400">G{h.generation}</td>
                                <td className="px-4 py-3 text-right text-fuchsia-300">{typeof h.best_fitness === 'number' ? h.best_fitness.toFixed(4) : '--'}</td>
                                <td className="px-4 py-3 text-right text-neutral-400">{typeof h.avg_fitness === 'number' ? h.avg_fitness.toFixed(4) : '--'}</td>
                                <td className="px-4 py-3 text-[11px] text-neutral-500">{formatGenome(h.best_genome)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {evoResult.disclaimer && (
                      <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-2.5 text-[11px] leading-relaxed text-rose-200/80">
                        <ShieldAlert className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                        {evoResult.disclaimer}
                      </div>
                    )}
                  </>
                );
              })()}

              {!evoResult && !evoError && (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-white/5 bg-white/[0.02] text-xs text-neutral-500">
                  选择标的、策略与适应度指标后点击「运行参数寻优」,用遗传算法在参数空间里搜索更优组合(同种子可复现)。
                </div>
              )}
            </motion.div>
          )}
          {activeTab === 'chips' && (
            <motion.div key="chips" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-amber-500/15 bg-amber-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-amber-100/75">
                <Coins className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                筹码分布用<strong className="font-medium text-amber-50"> 换手率扩散模型 </strong>重建当前持仓的<strong className="font-medium text-amber-50"> 成本结构</strong>：每天老筹码按换手衰减、新筹码按当日价格区间铺开，逐日累积。可读出获利盘比例、平均成本与筹码密集区。<strong className="font-medium text-amber-50"> 描述历史成本结构，不预测价格</strong>。
              </div>

              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e) => {
                      const stock = stockOptions.find((item) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">回看天数</p>
                  <input
                    type="number"
                    min={60}
                    max={1000}
                    value={days}
                    onChange={(e) => setDays(Math.max(60, Math.min(1000, Number(e.target.value) || 180)))}
                    className="mt-1 w-20 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <button
                  onClick={runChipDistribution}
                  disabled={chipRunning}
                  className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-600/80 px-8 py-2.5 text-xs font-medium text-white shadow-[0_0_20px_rgba(217,119,6,0.2)] transition-all hover:bg-amber-500 disabled:opacity-50"
                >
                  {chipRunning ? <Activity className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {chipRunning ? '重建筹码中...' : '重建筹码分布'}
                </button>
                {chipResult && chipResult.status === 'ok' && (
                  <span className={cn('rounded border px-2 py-1 text-[10px] font-mono', chipResult.model === 'turnover' ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/20 bg-amber-500/10 text-amber-300')}>
                    {chipResult.model === 'turnover' ? '真实换手率建模' : '量能代理建模'}
                  </span>
                )}
              </div>

              {chipError && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  筹码分布失败：{chipError}（需要足够历史行情，建议至少 60 个交易日）
                </div>
              )}

              {chipResult && chipResult.status === 'insufficient' && (
                <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
                  {chipResult.note || '历史数据不足以重建筹码分布。'}
                </div>
              )}

              {chipResult && chipResult.status === 'ok' && (
                <>
                  <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-4">
                    <MetricCard
                      label="获利盘比例"
                      value={`${formatFactor(chipResult.profit_ratio)}%`}
                      hint="成本低于现价的筹码占比"
                      icon={Flag}
                      tone={(chipResult.profit_ratio ?? 0) >= 50 ? 'rose' : 'emerald'}
                    />
                    <MetricCard
                      label="平均成本"
                      value={chipResult.avg_cost != null ? chipResult.avg_cost.toFixed(2) : '--'}
                      hint={`现价 ${chipResult.current_price != null ? chipResult.current_price.toFixed(2) : '--'}`}
                      icon={Coins}
                      tone="indigo"
                    />
                    <MetricCard
                      label="90% 集中度"
                      value={`${formatFactor(chipResult.concentration_90)}%`}
                      hint={`70% 集中度 ${formatFactor(chipResult.concentration_70)}% · 越小越集中`}
                      icon={Gauge}
                    />
                    <MetricCard
                      label="建模 K 线"
                      value={`${chipResult.bars_used ?? 0}`}
                      hint={chipResult.model === 'turnover' ? '真实换手率扩散' : '量能代理扩散'}
                      icon={Layers}
                      tone="amber"
                    />
                  </div>

                  <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
                    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-xl xl:col-span-2">
                      <div className="mb-4 flex items-center justify-between border-b border-white/5 pb-3">
                        <h3 className="text-xs font-mono uppercase tracking-widest text-neutral-400">
                          筹码分布 · {chipResult.symbol}
                        </h3>
                        <div className="flex items-center gap-3 text-[10px] text-neutral-500">
                          <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-rose-400" />获利盘</span>
                          <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" />套牢盘</span>
                        </div>
                      </div>
                      <div className="h-[460px] w-full">
                        {chipChartData.length ? (
                          <StableChartContainer>
                            <RBarChart data={chipChartData} layout="vertical" margin={{ top: 4, right: 12, bottom: 4, left: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                              <XAxis type="number" stroke="#737373" fontSize={10} tickLine={false} tickFormatter={(v) => `${Number(v).toFixed(1)}%`} />
                              <YAxis
                                type="category"
                                dataKey="priceLabel"
                                stroke="#737373"
                                fontSize={10}
                                width={52}
                                interval={Math.max(0, Math.floor(chipChartData.length / 14))}
                                tickLine={false}
                              />
                              <Tooltip
                                contentStyle={{ backgroundColor: 'rgba(0,0,0,0.82)', borderColor: 'rgba(255,255,255,0.12)', borderRadius: '12px', fontSize: '12px' }}
                                formatter={(value) => [`${Number(value).toFixed(2)}%`, '筹码占比']}
                                labelFormatter={(label) => `成本价 ${label}`}
                              />
                              <Bar dataKey="pct" radius={[0, 2, 2, 0]} animationDuration={600}>
                                {chipChartData.map((entry, index) => (
                                  <Cell key={index} fill={entry.inProfit ? '#fb7185' : '#34d399'} />
                                ))}
                              </Bar>
                            </RBarChart>
                          </StableChartContainer>
                        ) : (
                          <div className="flex h-full items-center justify-center text-xs text-neutral-500">无筹码数据</div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
                        <h3 className="mb-4 text-xs font-mono uppercase tracking-widest text-neutral-400">关键价位（成本聚集）</h3>
                        <div className="space-y-3 text-xs">
                          <div className="flex items-center justify-between rounded-lg border border-emerald-500/15 bg-emerald-500/5 px-3 py-2.5">
                            <span className="text-neutral-400">上方筹码密集价</span>
                            <span className="font-mono text-emerald-300">{chipResult.resistance_price ? chipResult.resistance_price.toFixed(2) : '--'}</span>
                          </div>
                          <div className="flex items-center justify-between rounded-lg border border-indigo-500/15 bg-indigo-500/5 px-3 py-2.5">
                            <span className="text-neutral-400">现价</span>
                            <span className="font-mono text-indigo-200">{chipResult.current_price != null ? chipResult.current_price.toFixed(2) : '--'}</span>
                          </div>
                          <div className="flex items-center justify-between rounded-lg border border-rose-500/15 bg-rose-500/5 px-3 py-2.5">
                            <span className="text-neutral-400">下方筹码密集价</span>
                            <span className="font-mono text-rose-300">{chipResult.support_price ? chipResult.support_price.toFixed(2) : '--'}</span>
                          </div>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
                        <h3 className="mb-4 text-xs font-mono uppercase tracking-widest text-neutral-400">筹码带</h3>
                        <div className="space-y-2 text-xs font-mono text-neutral-300">
                          <div className="flex items-center justify-between"><span className="text-neutral-500">70% 筹码带</span><span>{chipResult.range_70_low?.toFixed(2)} ~ {chipResult.range_70_high?.toFixed(2)}</span></div>
                          <div className="flex items-center justify-between"><span className="text-neutral-500">90% 筹码带</span><span>{chipResult.range_90_low?.toFixed(2)} ~ {chipResult.range_90_high?.toFixed(2)}</span></div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {chipResult.disclaimer && (
                    <div className="mt-6 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-2.5 text-[11px] leading-relaxed text-rose-200/80">
                      <ShieldAlert className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                      {chipResult.disclaimer}
                    </div>
                  )}
                </>
              )}

              {!chipResult && !chipError && (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-white/5 bg-white/[0.02] text-xs text-neutral-500">
                  选择标的后点击「重建筹码分布」，查看当前持仓成本结构与获利盘比例。
                </div>
              )}
            </motion.div>
          )}
          {activeTab === 'leaderboard' && (
            <motion.div key="leaderboard" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-indigo-500/15 bg-indigo-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-indigo-100/75">
                <Trophy className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                策略榜对当前标的<strong className="font-medium text-indigo-50"> 一次取数、跑完全部内置策略 </strong>并按所选指标排名,帮你快速看哪些策略在该标的历史上表现更好。<strong className="font-medium text-indigo-50"> 仅基于历史回测,不构成选股建议</strong>。
              </div>

              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e) => {
                      const stock = stockOptions.find((item) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="mb-1 text-[10px] font-mono uppercase tracking-widest text-neutral-500">排名指标</p>
                  <div className="flex overflow-hidden rounded-lg border border-white/10">
                    {([['sharpe_ratio', '夏普'], ['total_return', '累计收益'], ['calmar_ratio', 'Calmar']] as const).map(([key, label]) => (
                      <button
                        key={key}
                        onClick={() => setCmpRankBy(key)}
                        className={cn('px-3 py-1 text-xs transition-colors', cmpRankBy === key ? 'bg-indigo-600 text-white' : 'bg-transparent text-neutral-400 hover:text-neutral-200')}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <button
                  onClick={runStrategyComparison}
                  disabled={cmpRunning}
                  className="flex items-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-600 px-8 py-2.5 text-xs font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.2)] transition-all hover:bg-indigo-500 disabled:opacity-50"
                >
                  {cmpRunning ? <Activity className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
                  {cmpRunning ? '对比计算中...' : '一键对比全部策略'}
                </button>
              </div>

              {cmpError && (
                <div className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  策略对比失败：{cmpError}（请确认该标的有足够行情数据）
                </div>
              )}

              {cmpResult && cmpResult.ranking && (
                <>
                  <div className="mb-3 text-[11px] text-neutral-500">
                    评估 {cmpResult.evaluated ?? 0} 个内置策略 · 按{cmpRankBy === 'total_return' ? '累计收益' : cmpRankBy === 'calmar_ratio' ? 'Calmar' : '夏普比率'}降序
                    {cmpResult.skipped && cmpResult.skipped.length > 0 && <span> · 跳过模板策略 {cmpResult.skipped.join('、')}</span>}
                    {cmpResult.data_source_label && <span> · 数据来源：{cmpResult.data_source_label}</span>}
                  </div>
                  <div className="mb-6 overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                    <div className="max-h-[480px] overflow-auto custom-scrollbar">
                      <table className="w-full border-collapse text-left text-xs">
                        <thead className="sticky top-0 border-b border-white/5 bg-black/40 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                          <tr>
                            <th className="px-4 py-3">#</th>
                            <th className="px-4 py-3">策略</th>
                            <th className="px-4 py-3 text-right">累计收益</th>
                            <th className="px-4 py-3 text-right">年化</th>
                            <th className="px-4 py-3 text-right">最大回撤</th>
                            <th className="px-4 py-3 text-right">夏普</th>
                            <th className="px-4 py-3 text-right">Calmar</th>
                            <th className="px-4 py-3 text-right">胜率</th>
                            <th className="px-4 py-3 text-right">笔数</th>
                          </tr>
                        </thead>
                        <tbody className="font-mono text-neutral-300">
                          {cmpResult.ranking.map((row) => (
                            <tr key={row.strategy_id} className={cn('border-b border-white/5 hover:bg-white/[0.025]', row.rank === 1 && 'bg-amber-500/[0.05]')}>
                              <td className="px-4 py-3">
                                <span className={cn('inline-flex h-5 w-5 items-center justify-center rounded text-[10px]', row.rank === 1 ? 'bg-amber-500/20 text-amber-300' : row.rank && row.rank <= 3 ? 'bg-white/10 text-neutral-300' : 'text-neutral-500')}>
                                  {row.rank}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <span className="font-sans font-medium text-neutral-200">{row.strategy_name || row.strategy_id}</span>
                                {row.rank === 1 && <Trophy className="ml-1.5 inline h-3 w-3 text-amber-300" />}
                              </td>
                              <td className={cn('px-4 py-3 text-right', (row.total_return ?? 0) >= 0 ? 'text-rose-300' : 'text-emerald-300')}>{formatPercent(row.total_return)}</td>
                              <td className="px-4 py-3 text-right text-neutral-400">{formatPercent(row.annual_return)}</td>
                              <td className="px-4 py-3 text-right text-emerald-300/80">{formatPercent(row.max_drawdown)}</td>
                              <td className="px-4 py-3 text-right text-neutral-200">{formatFactor(row.sharpe_ratio)}</td>
                              <td className="px-4 py-3 text-right text-neutral-400">{formatFactor(row.calmar_ratio)}</td>
                              <td className="px-4 py-3 text-right text-neutral-400">{formatFactor(row.win_rate)}%</td>
                              <td className="px-4 py-3 text-right text-neutral-500">{row.trade_count ?? 0}</td>
                            </tr>
                          ))}
                          {cmpResult.ranking.length === 0 && (
                            <tr><td colSpan={9} className="px-4 py-8 text-center text-xs text-neutral-500">无可对比策略。</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="mb-6">
                    <AssumptionsCard assumptions={cmpResult.assumptions} />
                  </div>

                  {cmpResult.disclaimer && (
                    <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-2.5 text-[11px] leading-relaxed text-rose-200/80">
                      <ShieldAlert className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                      {cmpResult.disclaimer}
                    </div>
                  )}
                </>
              )}

              {!cmpResult && !cmpError && (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-white/5 bg-white/[0.02] text-xs text-neutral-500">
                  选择标的与排名指标后点击「一键对比全部策略」，生成该标的上的策略表现排行榜。
                </div>
              )}
            </motion.div>
          )}
          {activeTab === 'experiments' && (
            <motion.div key="experiments" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-indigo-500/15 bg-indigo-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-indigo-100/75">
                <Database className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                实验记录把回测/走查/筹码/策略榜的每次运行<strong className="font-medium text-indigo-50"> 落库持久化</strong>,跨会话可查、可调阅、可勾选<strong className="font-medium text-indigo-50"> 横向对比</strong>(最多 4 个)。共 {expTotal} 条记录(保留最近 300)。
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                {([['', '全部'], ['backtest', '回测'], ['walk_forward', '走查'], ['chip_distribution', '筹码'], ['strategy_compare', '策略榜']] as const).map(([key, label]) => (
                  <button
                    key={key || 'all'}
                    onClick={() => { setExpModeFilter(key); setExpSelected(new Set()); setExpCompareRows(null); }}
                    className={cn('rounded-lg border px-3 py-1.5 text-xs transition-colors', expModeFilter === key ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-200' : 'border-white/10 bg-black/30 text-neutral-400 hover:text-neutral-200')}
                  >
                    {label}
                  </button>
                ))}
                <div className="ml-auto flex items-center gap-2">
                  {expSelected.size >= 2 && (
                    <button onClick={runExpCompare} className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-600/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500">
                      <GitCompare className="h-3.5 w-3.5" />
                      对比选中 ({expSelected.size})
                    </button>
                  )}
                  {(expSelected.size > 0 || expCompareRows) && (
                    <button onClick={() => { setExpSelected(new Set()); setExpCompareRows(null); }} className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200">
                      清空选择
                    </button>
                  )}
                  <button onClick={() => setExpRefresh((n) => n + 1)} className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200">
                    刷新
                  </button>
                </div>
              </div>

              {expError && (
                <div className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-200">
                  实验记录读取异常：{expError}
                </div>
              )}

              {expCompareRows && expCompareRows.length > 0 && (
                <div className="mb-5 rounded-2xl border border-emerald-500/15 bg-emerald-500/[0.03] p-5 shadow-xl">
                  <h3 className="mb-4 flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-emerald-200/80">
                    <GitCompare className="h-4 w-4" />
                    横向对比 · {expCompareRows.length} 个实验
                  </h3>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {expCompareRows.map((row) => {
                      const meta = EXP_MODE_META[row.mode] || { label: row.mode, tone: 'text-neutral-300 border-white/15 bg-white/5' };
                      return (
                        <div key={row.run_id} className="rounded-xl border border-white/5 bg-black/30 p-4">
                          <div className="mb-2 flex items-center justify-between">
                            <span className={cn('rounded border px-2 py-0.5 text-[10px] font-mono', meta.tone)}>{meta.label}</span>
                            <span className="font-mono text-[10px] text-indigo-300">{row.symbol || '--'}</span>
                          </div>
                          <p className="text-[11px] leading-relaxed text-neutral-300">{formatExpSummary(row.mode, row.summary)}</p>
                          <p className="mt-2 font-mono text-[10px] text-neutral-600">{(row.created_at || '').slice(0, 19).replace('T', ' ')}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="border-b border-white/5 bg-black/35 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                    <tr>
                      <th className="px-4 py-3 w-8"></th>
                      <th className="px-4 py-3">时间</th>
                      <th className="px-4 py-3">类型</th>
                      <th className="px-4 py-3">标的</th>
                      <th className="px-4 py-3">策略</th>
                      <th className="px-4 py-3">关键指标</th>
                      <th className="px-4 py-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {expLoading && (
                      <tr><td colSpan={7} className="px-4 py-8 text-center text-xs text-neutral-500">正在读取实验记录...</td></tr>
                    )}
                    {!expLoading && expRows.map((row) => {
                      const meta = EXP_MODE_META[row.mode] || { label: row.mode, tone: 'text-neutral-300 border-white/15 bg-white/5' };
                      const selected = expSelected.has(row.run_id);
                      return (
                        <tr key={row.run_id} className={cn('border-b border-white/5 hover:bg-white/[0.025]', selected && 'bg-indigo-500/[0.06]')}>
                          <td className="px-4 py-3">
                            <input type="checkbox" checked={selected} onChange={() => toggleExpSelect(row.run_id)} className="h-3.5 w-3.5 accent-indigo-500" />
                          </td>
                          <td className="px-4 py-3 font-mono text-[11px] text-neutral-500">{(row.created_at || '').slice(0, 19).replace('T', ' ')}</td>
                          <td className="px-4 py-3"><span className={cn('rounded border px-2 py-0.5 text-[10px] font-mono', meta.tone)}>{meta.label}</span></td>
                          <td className="px-4 py-3 font-mono text-indigo-300">{row.symbol || '--'}</td>
                          <td className="px-4 py-3 text-neutral-400">{row.strategy_id || '--'}</td>
                          <td className="px-4 py-3 text-neutral-300">{formatExpSummary(row.mode, row.summary)}</td>
                          <td className="px-4 py-3 text-right">
                            <button onClick={() => deleteExperiment(row.run_id)} className="rounded p-1 text-neutral-500 transition-colors hover:bg-rose-500/10 hover:text-rose-300" title="删除">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {!expLoading && expRows.length === 0 && (
                      <tr><td colSpan={7} className="px-4 py-10 text-center text-xs text-neutral-500">暂无实验记录。运行回测 / 走查 / 筹码 / 策略榜后会自动落库于此。</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
