/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import { motion } from "motion/react";
import {
  Activity,
  BarChart,
  CheckCircle2,
  Flag,
  Play,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";
import { MetricCard } from "../MetricCard";
import { AssumptionsCard } from "../AssumptionsCard";
import { TradeTable } from "../TradeTable";
import { StableChartContainer } from "../../StableChartContainer";
import { formatPercent, formatFactor } from "../backtestFormat";

export function OverviewTab(props: {
  // Parent state/handlers bag (extract-without-rewrite)
  [key: string]: any;
}) {
  const {
    strategiesAsync,
    selectedSymbol,
    setSelectedSymbol,
    setSelectedStockName,
    days,
    setDays,
    initialCapital,
    setInitialCapital,
    running,
    result,
    runError,
    qsMetrics,
    qsAvailable,
    qsLoading,
    qsError,
    computeQuantStats,
    strategies,
    selectedStrategy,
    setSelectedStrategy,
    runTest,
    equityData,
    perf,
    stockOptions
  } = props;

  return (
            <motion.div key="overview" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-6 flex flex-wrap items-end gap-3">
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">回测标的</p>
                  <select
                    value={selectedSymbol}
                    onChange={(e: any) => {
                      const stock = stockOptions.find((item: any) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock: any) => (
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
                    onChange={(e: any) => setSelectedStrategy(e.target.value)}
                    className="mt-1 max-w-[180px] bg-transparent text-sm text-emerald-300 outline-none"
                  >
                    {strategies.length === 0 && <option value="">{strategiesAsync.loading ? '加载策略...' : '暂无策略'}</option>}
                    {strategies.map((strategy: any) => (
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
                    onChange={(e: any) => setDays(Math.max(30, Math.min(1000, Number(e.target.value) || 120)))}
                    className="mt-1 w-20 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">初始资金</p>
                  <input
                    type="number"
                    min={10000}
                    value={initialCapital}
                    onChange={(e: any) => setInitialCapital(Math.max(10000, Number(e.target.value) || 1000000))}
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
                    result.risk_violations.map((viol: any, index: any) => (
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
                          .filter(([, v]: any) => v !== null && v !== undefined && v !== '' && !(typeof v === 'string' && v.trim() === ''))
                          .slice(0, 32)
                          .map(([k, v]: any) => (
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
  );
}
