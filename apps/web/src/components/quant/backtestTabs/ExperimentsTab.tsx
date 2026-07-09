/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import { motion } from "motion/react";
import {
  Database,
  GitCompare,
  Trash2,
} from "lucide-react";
import { cn } from "../../../lib/utils";
import { EXP_MODE_META } from "../backtestTypes";
import { formatExpSummary } from "../backtestFormat";

export function ExperimentsTab(props: {
  // Parent state/handlers bag (extract-without-rewrite)
  [key: string]: any;
}) {
  const {
    setExpSelected,
    expRows,
    expLoading,
    expError,
    expModeFilter,
    setExpModeFilter,
    expSelected,
    expTotal,
    setExpRefresh,
    expCompareRows,
    setExpCompareRows,
    runExpCompare,
    deleteExperiment,
    toggleExpSelect
  } = props;

  return (
            <motion.div key="experiments" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
              <div className="mb-5 rounded-xl border border-indigo-500/15 bg-indigo-500/[0.04] px-4 py-3 text-[11px] leading-relaxed text-indigo-100/75">
                <Database className="mr-1 inline h-3.5 w-3.5 align-text-bottom" />
                实验记录把回测/走查/筹码/策略榜的每次运行<strong className="font-medium text-indigo-50"> 落库持久化</strong>,跨会话可查、可调阅、可勾选<strong className="font-medium text-indigo-50"> 横向对比</strong>(最多 4 个)。共 {expTotal} 条记录(保留最近 300)。
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                {([['', '全部'], ['backtest', '回测'], ['walk_forward', '走查'], ['chip_distribution', '筹码'], ['strategy_compare', '策略榜']] as const).map(([key, label]: any) => (
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
                  <button onClick={() => setExpRefresh((n: any) => n + 1)} className="rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200">
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
                    {expCompareRows.map((row: any) => {
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
                    {!expLoading && expRows.map((row: any) => {
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
  );
}
