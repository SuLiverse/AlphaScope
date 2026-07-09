import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Cpu, ShieldAlert } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "../lib/utils";
import { STOCK_UNIVERSE } from "../lib/stocks";
import { API_BASE_URL, LOCAL_API_TOKEN, fetchApi } from "../lib/api";
import { getPersistedStock, subscribeStockSelected } from "../lib/workspaceEvents";
import { getErrorMessage, stripSymbolSuffix, useAsync } from "../lib/dataFetch";
import { lookbackRange } from "../lib/quantDates";
import { previewResultNote, useQuantPreviewOptIn } from "../lib/quantPreview";
import { QuantPreviewCheckbox } from "./quant/QuantPreviewCheckbox";
import {
  OverviewTab,
  WorkshopTab,
  PoolTab,
  CompareTab,
  WalkForwardTab,
  EvolutionTab,
  ChipsTab,
  LeaderboardTab,
  ExperimentsTab,
} from "./quant/backtestTabs";
import {
  TABS,
  type TabID,
  type BacktestResultData,
  type StrategyInfo,
  type WalkForwardData,
  type ChipDistributionData,
  type StrategyCompareData,
  type EvolveData,
  type ExperimentRow,
  type FactorResponse,
  type FactorRow,
  type BacktestStats,
  type PendingEval,
  type AgentAccuracy,
  type TdxCompileResult,
  DEFAULT_TDX_FORMULA,
} from "./quant/backtestTypes";
import {
  DEFAULT_POOL_TEXT,
  parsePoolText,
  formatFactor,
  formatPercent,
} from "./quant/backtestFormat";

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
  const { allowPreviewData, setAllowPreviewData, previewBody } = useQuantPreviewOptIn(false);
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
      const range = lookbackRange(days);
      const res = await fetchApi<BacktestResultData>('/api/quant/backtest', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          initial_capital: initialCapital,
          params: {},
          ...previewBody,
        }),
      });
      setResult(res);
      const perf = res.metrics || {};
      const tradeCount = perf.trade_count ?? 0;
      const previewNote = previewResultNote(res);
      if (tradeCount === 0) {
        setActionMessage(
          `回测完成但 0 笔交易：策略未触发买卖信号，或当前本金（¥${initialCapital.toLocaleString()}）按 A 股 100 股整手买不进该标的。可尝试提高本金或更换标的。${res.summary?.data_source_label ? ' 数据来源：' + res.summary.data_source_label : ''}${previewNote}`,
        );
      } else {
        setActionMessage(
          `回测完成：${tradeCount} 笔交易，累计收益 ${formatPercent(perf.total_return)}，最大回撤 ${formatPercent(perf.max_drawdown)}。${res.summary?.data_source_label ? '数据来源：' + res.summary.data_source_label : ''}${previewNote}`,
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
      const range = lookbackRange(Math.max(days, (wfSplits + 1) * 45));
      const res = await fetchApi<WalkForwardData>('/api/quant/walk-forward', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          initial_capital: initialCapital,
          params: {},
          n_splits: wfSplits,
          scheme: wfScheme,
          ...previewBody,
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
      const range = lookbackRange(Math.max(days, 180));
      const res = await fetchApi<ChipDistributionData>('/api/quant/chip-distribution', {
        method: 'POST',
        body: JSON.stringify({
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          price_levels: 100,
          ...previewBody,
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
      const range = lookbackRange(Math.max(days, 365));
      const res = await fetchApi<EvolveData>('/api/quant/evolve', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: selectedStrategy,
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          initial_capital: initialCapital,
          params: {},
          param_space: {},
          population_size: evoPop,
          generations: evoGens,
          fitness_metric: evoMetric,
          seed: evoSeed,
          ...previewBody,
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
    if (!window.confirm(`确认删除实验记录 ${runId}?此操作不可撤销。`)) {
      return;
    }
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
      const range = lookbackRange(days);
      const res = await fetchApi<BacktestResultData>('/api/quant/backtest', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: 'tdx',
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          initial_capital: initialCapital,
          params: { formula: tdxFormula },
          ...previewBody,
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
      const range = lookbackRange(Math.max(days, 120));
      const res = await fetchApi<StrategyCompareData>('/api/quant/compare-strategies', {
        method: 'POST',
        body: JSON.stringify({
          symbol: stripSymbolSuffix(selectedSymbol),
          ...range,
          initial_capital: initialCapital,
          rank_by: cmpRankBy,
          ...previewBody,
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
          <QuantPreviewCheckbox
            checked={allowPreviewData}
            onChange={setAllowPreviewData}
            hint="允许演示样例行情（无真实行情时才用合成数据；默认关闭，勾选后结果会标注「本地样例」）"
          />
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
            <OverviewTab
              selectedSymbol={selectedSymbol}
              setSelectedSymbol={setSelectedSymbol}
              setSelectedStockName={setSelectedStockName}
              days={days}
              setDays={setDays}
              initialCapital={initialCapital}
              setInitialCapital={setInitialCapital}
              running={running}
              result={result}
              runError={runError}
              qsMetrics={qsMetrics}
              qsAvailable={qsAvailable}
              qsLoading={qsLoading}
              qsError={qsError}
              computeQuantStats={computeQuantStats}
              strategies={strategies}
              selectedStrategy={selectedStrategy}
              setSelectedStrategy={setSelectedStrategy}
              runTest={runTest}
              equityData={equityData}
              perf={perf}
              stockOptions={stockOptions}
            
              strategiesAsync={strategiesAsync}
            />
          )}

          {activeTab === 'workshop' && (
            <WorkshopTab
              selectedSymbol={selectedSymbol}
              tdxFormula={tdxFormula}
              setTdxFormula={setTdxFormula}
              tdxCompile={tdxCompile}
              setTdxCompile={setTdxCompile}
              tdxCompiling={tdxCompiling}
              tdxRunning={tdxRunning}
              strategies={strategies}
              selectedStrategy={selectedStrategy}
              setSelectedStrategy={setSelectedStrategy}
              compileTdx={compileTdx}
              runTdxBacktest={runTdxBacktest}
            
              strategiesAsync={strategiesAsync}
            />
          )}

          {activeTab === 'pool' && (
            <PoolTab
              fileInputRef={fileInputRef}
              poolText={poolText}
              setPoolText={setPoolText}
              poolLoading={poolLoading}
              poolSource={poolSource}
              handlePoolImport={handlePoolImport}
              exportPool={exportPool}
              sortedPoolRows={sortedPoolRows}
            
              poolStocks={poolStocks}
            
              poolRows={poolRows}
            />
          )}

          {activeTab === 'compare' && (
            <CompareTab
              stats={stats}
              pending={pending}
              compareLoading={compareLoading}
              compareError={compareError}
              agentAccuracyEntries={agentAccuracyEntries}
            />
          )}

          {activeTab === 'walkforward' && (
            <WalkForwardTab
              selectedSymbol={selectedSymbol}
              setSelectedSymbol={setSelectedSymbol}
              setSelectedStockName={setSelectedStockName}
              wfScheme={wfScheme}
              setWfScheme={setWfScheme}
              wfSplits={wfSplits}
              setWfSplits={setWfSplits}
              wfRunning={wfRunning}
              wfResult={wfResult}
              wfError={wfError}
              strategies={strategies}
              selectedStrategy={selectedStrategy}
              setSelectedStrategy={setSelectedStrategy}
              runWalkForward={runWalkForward}
              stockOptions={stockOptions}
            
              strategiesAsync={strategiesAsync}
            />
          )}
          {activeTab === 'evolution' && (
            <EvolutionTab
              setActiveTab={setActiveTab}
              selectedSymbol={selectedSymbol}
              setSelectedSymbol={setSelectedSymbol}
              setSelectedStockName={setSelectedStockName}
              evoMetric={evoMetric}
              setEvoMetric={setEvoMetric}
              evoPop={evoPop}
              setEvoPop={setEvoPop}
              evoGens={evoGens}
              setEvoGens={setEvoGens}
              evoSeed={evoSeed}
              setEvoSeed={setEvoSeed}
              evoRunning={evoRunning}
              evoResult={evoResult}
              evoError={evoError}
              strategies={strategies}
              selectedStrategy={selectedStrategy}
              setSelectedStrategy={setSelectedStrategy}
              runEvolution={runEvolution}
              stockOptions={stockOptions}
              evoChartData={evoChartData}
            
              strategiesAsync={strategiesAsync}
            />
          )}
          {activeTab === 'chips' && (
            <ChipsTab
              selectedSymbol={selectedSymbol}
              setSelectedSymbol={setSelectedSymbol}
              setSelectedStockName={setSelectedStockName}
              days={days}
              setDays={setDays}
              chipRunning={chipRunning}
              chipResult={chipResult}
              chipError={chipError}
              runChipDistribution={runChipDistribution}
              chipChartData={chipChartData}
              stockOptions={stockOptions}
            />
          )}
          {activeTab === 'leaderboard' && (
            <LeaderboardTab
              selectedSymbol={selectedSymbol}
              setSelectedSymbol={setSelectedSymbol}
              setSelectedStockName={setSelectedStockName}
              cmpRunning={cmpRunning}
              cmpResult={cmpResult}
              cmpError={cmpError}
              cmpRankBy={cmpRankBy}
              setCmpRankBy={setCmpRankBy}
              runStrategyComparison={runStrategyComparison}
              stockOptions={stockOptions}
            />
          )}
          {activeTab === 'experiments' && (
            <ExperimentsTab
              expRows={expRows}
              expLoading={expLoading}
              expError={expError}
              expModeFilter={expModeFilter}
              setExpModeFilter={setExpModeFilter}
              expSelected={expSelected}
              expTotal={expTotal}
              setExpRefresh={setExpRefresh}
              expCompareRows={expCompareRows}
              setExpCompareRows={setExpCompareRows}
              runExpCompare={runExpCompare}
              deleteExperiment={deleteExperiment}
              toggleExpSelect={toggleExpSelect}
            
              setExpSelected={setExpSelected}
            />
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
