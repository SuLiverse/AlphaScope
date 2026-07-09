/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import type { AgentAccuracy, BacktestStats, PendingEval } from "../backtestTypes";

import { motion } from "motion/react";
import {
  Activity,
  BarChart,
  CheckCircle2,
  TrendingUp,
} from "lucide-react";
import { MetricCard } from "../MetricCard";
import { formatFactor } from "../backtestFormat";

type AgentAccuracyEntry = NonNullable<AgentAccuracy["agents"]>[string];

export interface CompareTabProps {
  stats: BacktestStats | null;
  pending: PendingEval[];
  compareLoading: boolean;
  compareError: string | null;
  agentAccuracyEntries: Array<[string, AgentAccuracyEntry]>;
}

export function CompareTab({
  stats,
  pending,
  compareLoading,
  compareError,
  agentAccuracyEntries,
}: CompareTabProps) {

  return (
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
                    {!compareLoading && pending.map((item: PendingEval) => (
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
  );
}
