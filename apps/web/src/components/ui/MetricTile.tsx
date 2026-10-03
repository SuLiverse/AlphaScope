import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

const sizes = {
  sm: 'px-3 py-2.5',
  md: 'px-4 py-3.5',
  lg: 'px-5 py-4',
} as const;

export interface MetricTileProps extends HTMLAttributes<HTMLDivElement> {
  /** 指标名（弱化档小字）。 */
  label: ReactNode;
  /** 指标值；undefined/null/'' 时渲染弱化占位 "——"，不再显示"暂无/待生成"类长文案。 */
  value?: ReactNode;
  /** 值下方的补充说明（可选，弱化档）。 */
  hint?: ReactNode;
  /** 值右侧的操作或图标位（可选）。 */
  aside?: ReactNode;
  /** 数值色调：涨/跌语义色。 */
  tone?: 'default' | 'up' | 'down' | 'brand';
  size?: keyof typeof sizes;
}

const toneClass = {
  default: 'text-neutral-100',
  up: 'text-tint-up',
  down: 'text-tint-down',
  brand: 'text-brand-light',
} as const;

/**
 * 指标瓦片：KPI 行的统一单元。
 * 详略约定——label 一行小字，value 一行大字（等宽数字），
 * 没有数据就安静地显示「——」，绝不在瓦片里放长文案或状态语义。
 */
export function MetricTile({ label, value, hint, aside, tone = 'default', size = 'md', className, children, ...rest }: MetricTileProps) {
  const empty = value === undefined || value === null || value === '';
  return (
    <div
      className={cn(
        'flex min-w-0 flex-col justify-between gap-1 rounded-xl border border-border-card bg-surface',
        sizes[size],
        className,
      )}
      {...rest}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs text-neutral-500">{label}</span>
        {aside && <span className="shrink-0 text-neutral-500">{aside}</span>}
      </div>
      <div className={cn('truncate text-xl font-semibold leading-7 tracking-tight', empty ? 'text-neutral-600' : toneClass[tone])}>
        {empty ? '——' : value}
      </div>
      {hint != null && <div className="truncate text-xs text-neutral-500">{hint}</div>}
      {children}
    </div>
  );
}
