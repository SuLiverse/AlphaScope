import { ShieldAlert } from "lucide-react";
import { cn } from "../../lib/utils";
import type { BacktestAssumptions } from "./backtestTypes";

/** Render the backtest engine's friction assumptions so users can see exactly
 * what costs/limits were modelled (transparency / auditability). */
export function AssumptionsCard({ assumptions }: { assumptions?: BacktestAssumptions }) {
  if (!assumptions) return null;
  const pct = (v?: number) => (typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : '--');
  const rows: Array<{ label: string; value: string; on?: boolean }> = [
    { label: 'T+1 结算', value: assumptions.t_plus_1 ? '启用' : '关闭', on: assumptions.t_plus_1 },
    { label: '涨跌停封板过滤', value: assumptions.price_limit_filter ? `启用 · ±${((assumptions.price_limit_band ?? 0.1) * 100).toFixed(0)}%` : '关闭', on: assumptions.price_limit_filter },
    { label: '佣金（双边）', value: pct(assumptions.commission_rate) + (assumptions.commission_min ? ` · 最低 ¥${assumptions.commission_min}` : '') },
    { label: '印花税（卖出）', value: pct(assumptions.stamp_duty_rate) },
    { label: '滑点', value: pct(assumptions.slippage_rate) },
    { label: '成交价口径', value: assumptions.execution_price === 'open' ? '次日开盘（防未来函数）' : (assumptions.execution_price || '--') },
  ];
  return (
    <div className="rounded-2xl border border-amber-500/15 bg-amber-500/[0.04] p-5 shadow-xl">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-amber-200/80">
          <ShieldAlert className="h-4 w-4" />
          本次回测假设
        </h3>
        <span className="rounded border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono text-amber-300">真实摩擦成本</span>
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded-lg border border-white/5 bg-black/25 px-3 py-2">
            <p className="text-[10px] text-neutral-500">{row.label}</p>
            <p className={cn('mt-0.5 text-xs font-mono', row.on === false ? 'text-neutral-600' : 'text-neutral-200')}>{row.value}</p>
          </div>
        ))}
      </div>
      {assumptions.note && (
        <p className="mt-3 text-[10px] leading-relaxed text-neutral-500">{assumptions.note}</p>
      )}
    </div>
  );
}
