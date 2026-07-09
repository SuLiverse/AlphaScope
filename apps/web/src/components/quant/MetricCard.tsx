import type { ComponentType } from "react";
import { cn } from "../../lib/utils";

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  hint: string;
  icon: ComponentType<{ className?: string }>;
  tone?: 'rose' | 'emerald' | 'indigo' | 'neutral' | 'amber';
}) {
  const color = {
    rose: 'text-rose-400',
    emerald: 'text-emerald-400',
    indigo: 'text-indigo-300',
    neutral: 'text-neutral-300',
    amber: 'text-amber-300',
  }[tone];

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-xl">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">{label}</p>
        <Icon className={cn('h-4 w-4', color)} />
      </div>
      <h3 className="text-3xl font-mono font-medium text-white">{value}</h3>
      <p className={cn('mt-2 text-[11px] font-mono', color)}>{hint}</p>
    </div>
  );
}
