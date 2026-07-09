/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import type { ChangeEvent } from "react";
import type { StrategyInfo, TdxCompileResult } from "../backtestTypes";

import { stripSymbolSuffix } from "../../../lib/dataFetch";
import { motion } from "motion/react";
import {
  Activity,
  CheckCircle2,
  Code2,
  Play,
  ShieldAlert,
} from "lucide-react";
import { cn } from "../../../lib/utils";
import { DEFAULT_TDX_FORMULA } from "../backtestTypes";

export interface WorkshopTabProps {
  strategiesLoading: boolean;
  strategiesError?: string | null;
  onRefreshStrategies?: () => void;
  selectedSymbol: string;
  tdxFormula: string;
  setTdxFormula: (v: string) => void;
  tdxCompile: TdxCompileResult | null;
  setTdxCompile: (v: TdxCompileResult | null) => void;
  tdxCompiling: boolean;
  tdxRunning: boolean;
  strategies: StrategyInfo[];
  selectedStrategy: string;
  setSelectedStrategy: (id: string) => void;
  compileTdx: () => void | Promise<void>;
  runTdxBacktest: () => void | Promise<void>;
}

export function WorkshopTab({
  strategiesLoading,
  strategiesError,
  onRefreshStrategies,
  selectedSymbol,
  tdxFormula,
  setTdxFormula,
  tdxCompile,
  setTdxCompile,
  tdxCompiling,
  tdxRunning,
  strategies,
  selectedStrategy,
  setSelectedStrategy,
  compileTdx,
  runTdxBacktest,
}: WorkshopTabProps) {

  return (
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
                    onChange={(e: ChangeEvent<HTMLSelectElement | HTMLInputElement | HTMLTextAreaElement>) => setTdxFormula(e.target.value)}
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
                      {(tdxCompile.errors || []).map((e: any, i: any) => (
                        <p key={i} className="text-[11px] leading-relaxed text-rose-300/90">• {e}</p>
                      ))}
                      {(tdxCompile.warnings || []).map((w: any, i: any) => (
                        <p key={i} className="text-[11px] leading-relaxed text-amber-300/80">⚠ {w}</p>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="min-h-[500px] rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-xl">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-white">内置策略管理器</h3>
                  <button
                    type="button"
                    onClick={() => onRefreshStrategies?.()}
                    className="text-xs font-medium text-indigo-400 hover:text-indigo-300"
                  >
                    {strategiesLoading ? '加载中...' : '刷新'}
                  </button>
                </div>
                {strategiesError && (
                  <p className="mb-3 text-xs text-rose-300">策略加载失败：{strategiesError}</p>
                )}
                {strategies.map((strategy: StrategyInfo) => (
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
                {strategies.length === 0 && !strategiesLoading && (
                  <p className="text-xs text-neutral-500">暂无可用策略，请确认后端 /api/quant/strategies 可用。</p>
                )}
              </div>
            </motion.div>
  );
}
