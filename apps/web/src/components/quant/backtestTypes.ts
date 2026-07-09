/**
 * Backtesting 页面类型与 Tab 常量。
 */
import type { ComponentType } from "react";
import type { StockTarget } from "../../lib/stocks";
import {
  Activity,
  Code2,
  Coins,
  Database,
  Dna,
  GitBranch,
  History,
  Layers,
  Trophy,
} from "lucide-react";

export type TabID = 'overview' | 'workshop' | 'leaderboard' | 'walkforward' | 'evolution' | 'chips' | 'experiments' | 'pool' | 'compare';

export const TABS: Array<{ id: TabID; label: string; icon: ComponentType<{ className?: string }> }> = [
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
export const EXP_MODE_META: Record<string, { label: string; tone: string }> = {
  backtest: { label: '回测', tone: 'text-indigo-300 border-indigo-500/30 bg-indigo-500/10' },
  walk_forward: { label: '走查', tone: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10' },
  chip_distribution: { label: '筹码', tone: 'text-amber-300 border-amber-500/30 bg-amber-500/10' },
  strategy_compare: { label: '策略榜', tone: 'text-rose-300 border-rose-500/30 bg-rose-500/10' },
  evolution: { label: '进化', tone: 'text-fuchsia-300 border-fuchsia-500/30 bg-fuchsia-500/10' },
};

// 进化适应度指标中文名。
export const EVO_METRIC_LABELS: Record<string, string> = {
  sharpe_ratio: '夏普比率',
  calmar_ratio: '卡玛比率',
  sortino_ratio: '索提诺比率',
  total_return: '累计收益',
  annualized_return: '年化收益',
  profit_factor: '盈亏比',
  win_rate: '胜率',
};

export interface PerformanceMetrics {
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

export interface TradeRecord {
  symbol?: string;
  side?: string;
  shares?: number;
  price?: number;
  commission?: number;
  pnl?: number;
  timestamp?: string;
}

export interface RiskViolation {
  rule?: string;
  reason?: string;
  date?: string;
}

/** Backtest engine friction assumptions (T+1 / stamp duty / slippage / etc.).
 * Mirrors backend/quant/engine.py BacktestEngine._assumptions(). */
export interface BacktestAssumptions {
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

export interface BacktestEquityPoint {
  date?: string;
  equity?: number;
  value?: number;
}

export interface BacktestSummary {
  data_source?: string;
  data_source_label?: string;
  bar_count?: number;
  trade_count?: number;
  risk_violation_count?: number;
  start_date?: string;
  end_date?: string;
}

export interface BacktestResultData {
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
  degraded?: boolean;
  data_source?: string;
  is_preview?: boolean;
}

export interface StrategyInfo {
  id: string;
  name: string;
  description?: string;
  default_params?: Record<string, unknown>;
}

// ---- Walk-forward contract (backend/quant/walk_forward.py to_dict) ----

export interface WalkForwardWindow {
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

export interface WalkForwardAggregate {
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

export interface WalkForwardData {
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

export interface ChipLevel {
  price: number;
  pct: number;
}

export interface ChipDistributionData {
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

export interface StrategyCompareRow {
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

export interface StrategyCompareData {
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

export interface ExperimentRow {
  run_id: string;
  mode: string;
  symbol?: string;
  strategy_id?: string;
  created_at?: string;
  summary?: Record<string, number | string>;
}

// ---- TDX compile contract (backend/quant/tdx_compiler.py to_dict) ----

export interface TdxCompileResult {
  ok: boolean;
  errors?: string[];
  warnings?: string[];
  var_names?: string[];
  buy_signals?: string[];
  sell_signals?: string[];
  refs_used?: string[];
  statement_count?: number;
}

export const DEFAULT_TDX_FORMULA = `DIFF:=EMA(CLOSE,12)-EMA(CLOSE,26);
DEA:=EMA(DIFF,9);
MACD:2*(DIFF-DEA);
ENTERLONG:CROSS(DIFF,DEA) AND MACD>0;
EXITLONG:CROSS(DEA,DIFF);`;

// ---- Genetic-algorithm evolution contract (backend/quant/evolution.py to_dict) ----

export interface EvolveIndividual {
  genome: Record<string, number>;
  params: Record<string, number>;
  fitness: number | null;
  metrics: Record<string, number>;
}

export interface EvolveGenStat {
  generation: number;
  best_fitness: number | null;
  avg_fitness: number | null;
  best_genome: Record<string, number>;
}

export interface EvolveData {
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

export interface FactorResponse {
  symbol: string;
  stock_name?: string;
  computed_at?: string;
  factors?: Record<string, number>;
  sample_counts?: Record<string, number>;
  degraded_inputs?: string[];
  missing_dimensions?: string[];
  signals?: Array<Record<string, number | string | boolean>>;
}

export interface FactorRow {
  stock: StockTarget;
  composite?: number;
  momentum?: number;
  fund_flow?: number;
  quality: number;
  computed_at?: string;
  error?: string;
}

export interface BacktestStats {
  total?: number;
  evaluated?: number;
  message?: string;
  buy_signals?: { count?: number; accuracy_5d?: number };
  sell_signals?: { count?: number };
  hold_signals?: { count?: number };
}

export interface PendingEval {
  decision_id?: string;
  symbol?: string;
  signal?: string;
  price?: number;
  days_elapsed?: number;
}

export interface AgentAccuracy {
  agents?: Record<string, { accuracy?: number; total_decisions?: number; avg_return?: number }>;
}
