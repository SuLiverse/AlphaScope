/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import { motion } from "motion/react";
import {
  Activity,
  BarChart,
  Flag,
  Gauge,
  GitBranch,
  Play,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { cn } from "../../../lib/utils";
import { MetricCard } from "../MetricCard";
import { AssumptionsCard } from "../AssumptionsCard";
import { formatPercent, formatFactor } from "../backtestFormat";

export function WalkForwardTab(props: {
  // Parent state/handlers bag (extract-without-rewrite)
  [key: string]: any;
}) {
  const {
    strategiesAsync,
    selectedSymbol,
    setSelectedSymbol,
    setSelectedStockName,
    wfScheme,
    setWfScheme,
    wfSplits,
    setWfSplits,
    wfRunning,
    wfResult,
    wfError,
    strategies,
    selectedStrategy,
    setSelectedStrategy,
    runWalkForward,
    stockOptions
  } = props;

  return (
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
                  <p className="mb-1 text-[10px] font-mono uppercase tracking-widest text-neutral-500">切分方案</p>
                  <div className="flex overflow-hidden rounded-lg border border-white/10">
                    {(['anchored', 'rolling'] as const).map((s: any) => (
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
                    onChange={(e: any) => setWfSplits(Math.max(2, Math.min(12, Number(e.target.value) || 5)))}
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
                          {(wfResult.windows || []).map((w: any) => (
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
  );
}
