/**
 * Extracted Backtesting tab panel (behavior-preserving move).
 */
import type { ChangeEvent } from "react";
import type React from "react";
import type { StockTarget } from "../../../lib/stocks";
import type { FactorRow } from "../backtestTypes";

import { motion } from "motion/react";
import {
  Download,
  Upload,
} from "lucide-react";
import { cn } from "../../../lib/utils";
import { formatFactor } from "../backtestFormat";

export interface PoolTabProps {
  poolRows: FactorRow[];
  poolStocks: StockTarget[];
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  poolText: string;
  setPoolText: (v: string) => void;
  poolLoading: boolean;
  poolSource: string;
  handlePoolImport: (e: ChangeEvent<HTMLInputElement>) => void;
  exportPool: () => void | Promise<void>;
  sortedPoolRows: FactorRow[];
}

export function PoolTab({
  poolRows,
  poolStocks,
  fileInputRef,
  poolText,
  setPoolText,
  poolLoading,
  poolSource,
  handlePoolImport,
  exportPool,
  sortedPoolRows,
}: PoolTabProps) {

  return (
            <motion.div key="pool" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid grid-cols-1 gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
              <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-xl">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-white">股票池解析</h3>
                    <p className="mt-1 text-xs text-neutral-500">支持粘贴 BLK / CSV / 代码列表，自动识别 A 股标的。</p>
                  </div>
                  <input ref={fileInputRef} type="file" accept=".txt,.csv,.blk" onChange={handlePoolImport} className="hidden" />
                  <button data-testid="backtest-import-pool" onClick={() => fileInputRef.current?.click()} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 hover:bg-white/[0.06]">
                    <Upload className="h-4 w-4" />
                    导入文件
                  </button>
                </div>
                <textarea
                  value={poolText}
                  onChange={(event) => setPoolText(event.target.value)}
                  className="h-64 w-full resize-none rounded-xl border border-white/10 bg-black/40 p-4 font-mono text-xs leading-relaxed text-neutral-200 outline-none focus:border-indigo-500/50"
                />
                <div className="mt-4 grid grid-cols-3 gap-3 text-center text-xs">
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">识别标的</p>
                    <p className="mt-1 text-xl font-mono text-white">{poolStocks.length}</p>
                  </div>
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">最高综合因子</p>
                    <p className="mt-1 text-xl font-mono text-rose-400">{sortedPoolRows[0]?.composite != null ? formatFactor(sortedPoolRows[0].composite) : '--'}</p>
                  </div>
                  <div className="rounded-xl bg-black/25 p-3">
                    <p className="text-[10px] text-neutral-500">高完整度</p>
                    <p className="mt-1 text-xl font-mono text-emerald-400">{poolRows.filter((row: any) => row.quality >= 80).length}</p>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-xl">
                <div className="flex items-center justify-between border-b border-white/5 bg-black/35 p-5">
                  <div>
                    <h3 className="text-sm font-semibold text-white">真实截面因子</h3>
                    <p className="mt-1 text-[11px] text-neutral-500">{poolSource || '逐标的调用 /api/factors 计算真实因子'}</p>
                  </div>
                  <button data-testid="backtest-export-pool" onClick={exportPool} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 hover:bg-white/[0.06]">
                    <Download className="h-4 w-4" />
                    导出股票池
                  </button>
                </div>
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="border-b border-white/5 bg-black/20 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                    <tr>
                      <th className="px-5 py-3">标的</th>
                      <th className="px-5 py-3">行业</th>
                      <th className="px-5 py-3 text-right">综合因子</th>
                      <th className="px-5 py-3 text-right">价格动量</th>
                      <th className="px-5 py-3 text-right">资金因子</th>
                      <th className="px-5 py-3 text-right">完整度</th>
                    </tr>
                  </thead>
                  <tbody>
                    {poolLoading && (
                      <tr>
                        <td colSpan={6} className="px-5 py-8 text-center text-xs text-neutral-500">正在计算真实截面因子...</td>
                      </tr>
                    )}
                    {!poolLoading && sortedPoolRows.map((row: any) => (
                      <tr key={row.stock.symbol} className="border-b border-white/5 hover:bg-white/[0.025]">
                        <td className="px-5 py-3.5">
                          <p className="font-medium text-neutral-200">{row.stock.name}</p>
                          <p className="mt-1 font-mono text-[10px] text-indigo-300">{row.stock.symbol}</p>
                        </td>
                        <td className="px-5 py-3.5 text-neutral-400">{row.stock.sector}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-rose-400">{row.error ? '--' : formatFactor(row.composite)}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-300">{row.error ? '--' : formatFactor(row.momentum)}</td>
                        <td className="px-5 py-3.5 text-right font-mono text-neutral-300">{row.error ? '--' : formatFactor(row.fund_flow)}</td>
                        <td className={cn('px-5 py-3.5 text-right font-mono', row.quality >= 80 ? 'text-emerald-400' : 'text-amber-300')}>{row.error ? <span className="text-rose-400">失败</span> : row.quality}</td>
                      </tr>
                    ))}
                    {!poolLoading && sortedPoolRows.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-5 py-8 text-center text-xs text-neutral-500">暂无识别标的，请在左侧填入股票代码。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
  );
}
