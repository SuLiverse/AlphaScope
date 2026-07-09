/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import type { ChangeEvent } from "react";
import type { StockTarget } from "../../../lib/stocks";
import type { StrategyCompareData } from "../backtestTypes";

import { motion } from "motion/react";
import {
  Activity,
  Play,
  ShieldAlert,
  Trophy,
} from "lucide-react";
import { cn } from "../../../lib/utils";
import { AssumptionsCard } from "../AssumptionsCard";
import { formatPercent, formatFactor } from "../backtestFormat";

export interface LeaderboardTabProps {
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
  setSelectedStockName: (name: string) => void;
  cmpRunning: boolean;
  cmpResult: StrategyCompareData | null;
  cmpError: string | null;
  cmpRankBy: 'sharpe_ratio' | 'total_return' | 'calmar_ratio';
  setCmpRankBy: (v: 'sharpe_ratio' | 'total_return' | 'calmar_ratio') => void;
  runStrategyComparison: () => void | Promise<void>;
  stockOptions: StockTarget[];
}

export function LeaderboardTab({
  selectedSymbol,
  setSelectedSymbol,
  setSelectedStockName,
  cmpRunning,
  cmpResult,
  cmpError,
  cmpRankBy,
  setCmpRankBy,
  runStrategyComparison,
  stockOptions,
}: LeaderboardTabProps) {

  return (
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => {
                      const stock = stockOptions.find((item: StockTarget) => item.symbol === e.target.value);
                      if (stock) {
                        setSelectedSymbol(stock.symbol);
                        setSelectedStockName(stock.name);
                      }
                    }}
                    className="mt-1 bg-transparent text-sm text-indigo-300 outline-none"
                  >
                    {stockOptions.map((stock: StockTarget) => (
                      <option key={stock.symbol} value={stock.symbol} className="bg-[#0f0f15] text-neutral-200">
                        {stock.name} ({stock.symbol})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="rounded-xl border border-white/5 bg-black/40 px-4 py-2.5">
                  <p className="mb-1 text-[10px] font-mono uppercase tracking-widest text-neutral-500">排名指标</p>
                  <div className="flex overflow-hidden rounded-lg border border-white/10">
                    {([['sharpe_ratio', '夏普'], ['total_return', '累计收益'], ['calmar_ratio', 'Calmar']] as const).map(([key, label]: any) => (
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
                          {cmpResult.ranking.map((row: any) => (
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
  );
}
