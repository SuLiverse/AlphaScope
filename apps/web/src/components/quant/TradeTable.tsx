import { cn } from "../../lib/utils";
import type { TradeRecord } from "./backtestTypes";

/** Trade blotter — renders the `trades` field that was typed but never shown. */
export function TradeTable({ trades }: { trades?: TradeRecord[] }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
        <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">交易明细</h3>
        <p className="text-xs text-neutral-500">本次回测无成交记录。</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-xl">
      <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">交易明细 · 共 {trades.length} 笔</h3>
      <div className="max-h-72 overflow-auto custom-scrollbar">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-black/40 text-[10px] uppercase tracking-wider text-neutral-500">
            <tr>
              <th className="px-2 py-2 font-medium">时间</th>
              <th className="px-2 py-2 font-medium">方向</th>
              <th className="px-2 py-2 text-right font-medium">数量</th>
              <th className="px-2 py-2 text-right font-medium">成交价</th>
              <th className="px-2 py-2 text-right font-medium">佣金</th>
              <th className="px-2 py-2 text-right font-medium">盈亏</th>
            </tr>
          </thead>
          <tbody className="font-mono text-neutral-300">
            {trades.map((t, i) => (
              <tr key={i} className="border-t border-white/5">
                <td className="px-2 py-1.5 text-neutral-500">{t.timestamp || '--'}</td>
                <td className="px-2 py-1.5">
                  <span className={cn('rounded px-1.5 py-0.5 text-[10px]', t.side === 'buy' ? 'bg-rose-500/10 text-rose-300' : 'bg-emerald-500/10 text-emerald-300')}>
                    {t.side === 'buy' ? '买入' : '卖出'}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right">{t.shares ?? '--'}</td>
                <td className="px-2 py-1.5 text-right">{t.price != null ? t.price.toFixed(2) : '--'}</td>
                <td className="px-2 py-1.5 text-right text-neutral-500">{t.commission != null ? t.commission.toFixed(2) : '--'}</td>
                <td className={cn('px-2 py-1.5 text-right', (t.pnl ?? 0) >= 0 ? 'text-rose-300' : 'text-emerald-300')}>
                  {t.pnl != null ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2) : '--'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
