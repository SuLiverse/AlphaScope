/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import type { ChangeEvent } from "react";
import type { StockTarget } from "../../../lib/stocks";
import type { EvolveData, StrategyInfo, TabID } from "../backtestTypes";

import { motion } from "motion/react";
import {
  Activity,
  Cpu,
  Dna,
  GitBranch,
  Play,
  ShieldAlert,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { MetricCard } from "../MetricCard";
import { StableChartContainer } from "../../StableChartContainer";
import { EVO_METRIC_LABELS } from "../backtestTypes";
import { formatPercent, formatFactor, formatGenome } from "../backtestFormat";

export interface EvolutionTabProps {
  strategiesLoading: boolean;
  setActiveTab: (tab: TabID) => void;
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
  setSelectedStockName: (name: string) => void;
  evoMetric: string;
  setEvoMetric: (v: any) => void;
  evoPop: number;
  setEvoPop: (n: number) => void;
  evoGens: number;
  setEvoGens: (n: number) => void;
  evoSeed: number;
  setEvoSeed: (n: number) => void;
  evoRunning: boolean;
  evoResult: EvolveData | null;
  evoError: string | null;
  strategies: StrategyInfo[];
  selectedStrategy: string;
  setSelectedStrategy: (id: string) => void;
  runEvolution: () => void | Promise<void>;
  stockOptions: StockTarget[];
  evoChartData: Array<{ gen: string; best: number | null; avg: number | null }>;
}

export function EvolutionTab({
  strategiesLoading,
  setActiveTab,
  selectedSymbol,
  setSelectedSymbol,
  setSelectedStockName,
  evoMetric,
  setEvoMetric,
  evoPop,
  setEvoPop,
  evoGens,
  setEvoGens,
  evoSeed,
  setEvoSeed,
  evoRunning,
  evoResult,
  evoError,
  strategies,
  selectedStrategy,
  setSelectedStrategy,
  runEvolution,
  stockOptions,
  evoChartData,
}: EvolutionTabProps) {

  return (
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => {
                      const stock = stockOptions.find((item: StockTarget) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-fuchsia-300 outline-none"
                  >
                    {stockOptions.map((stock: StockTarget) => (
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setSelectedStrategy(e.target.value)}
                    className="mt-1 max-w-[160px] bg-transparent text-sm text-emerald-300 outline-none"
                  >
                    {strategies.length === 0 && <option value="">{strategiesLoading ? '加载策略...' : '暂无策略'}</option>}
                    {strategies.map((strategy: StrategyInfo) => (
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setEvoMetric(e.target.value as typeof evoMetric)}
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setEvoPop(Math.max(4, Math.min(40, Number(e.target.value) || 16)))}
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setEvoGens(Math.max(1, Math.min(20, Number(e.target.value) || 8)))}
                    className="mt-1 w-14 bg-transparent text-sm text-neutral-200 outline-none"
                  />
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">随机种子</p>
                  <input
                    type="number"
                    value={evoSeed}
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setEvoSeed(Number(e.target.value) || 0)}
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
                        {Object.entries(best.genome || {}).map(([k, v]: any) => (
                          <span key={k} className="rounded-lg border border-fuchsia-500/25 bg-black/30 px-3 py-1 text-xs font-mono text-fuchsia-200">
                            {k} = <strong className="text-white">{Number.isInteger(v as number) ? String(v) : Number(v).toFixed(3)}</strong>
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
                            {(evoResult.history || []).map((h: any) => (
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
  );
}
