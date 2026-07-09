/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import { motion } from "motion/react";
import {
  Activity,
  Coins,
  Flag,
  Gauge,
  Layers,
  Play,
  ShieldAlert,
} from "lucide-react";
import { Bar, BarChart as RBarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "../../../lib/utils";
import { MetricCard } from "../MetricCard";
import { StableChartContainer } from "../../StableChartContainer";
import { formatFactor } from "../backtestFormat";

export function ChipsTab(props: {
  // Parent state/handlers bag (extract-without-rewrite)
  [key: string]: any;
}) {
  const {
    selectedSymbol,
    setSelectedSymbol,
    setSelectedStockName,
    days,
    setDays,
    chipRunning,
    chipResult,
    chipError,
    runChipDistribution,
    chipChartData,
    stockOptions
  } = props;

  return (
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
                  <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">回看天数</p>
                  <input
                    type="number"
                    min={60}
                    max={1000}
                    value={days}
                    onChange={(e: any) => setDays(Math.max(60, Math.min(1000, Number(e.target.value) || 180)))}
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
                                {chipChartData.map((entry: any, index: any) => (
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
  );
}
