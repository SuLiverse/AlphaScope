import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export type StatusTone = 'neutral' | 'info' | 'warn' | 'danger' | 'success' | 'up' | 'down';

const tones: Record<StatusTone, { dot: string; text: string; shell: string }> = {
  neutral: { dot: 'bg-neutral-500', text: 'text-neutral-400', shell: 'border-border-strong bg-surface-raised' },
  info: { dot: 'bg-tint-info', text: 'text-indigo-200/90', shell: 'border-brand/30 bg-brand/10' },
  warn: { dot: 'bg-tint-warn', text: 'text-amber-200/90', shell: 'border-amber-500/20 bg-amber-500/10' },
  danger: { dot: 'bg-tint-up', text: 'text-red-200/90', shell: 'border-red-500/25 bg-red-500/10' },
  success: { dot: 'bg-tint-down', text: 'text-emerald-200/90', shell: 'border-emerald-500/25 bg-emerald-500/10' },
  up: { dot: 'bg-tint-up', text: 'text-tint-up', shell: 'border-transparent bg-transparent' },
  down: { dot: 'bg-tint-down', text: 'text-tint-down', shell: 'border-transparent bg-transparent' },
};

export interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone;
  /** 是否显示前置圆点；up/down 语义色默认不带底色仅显示文字。 */
  dot?: boolean;
  /** 加载中时圆点呼吸闪烁。 */
  pulse?: boolean;
  children: ReactNode;
}

/**
 * 状态徽章：界面里所有「连接状态 / 数据来源 / 降级提示」的统一出口。
 * 目标是把技术性错误（Failed to fetch 之类）收进人话 + 分级视觉，
 * 默认 tone=neutral 弱存在感，不要让状态噪音抢主数据的注意力。
 */
export function StatusChip({ tone = 'neutral', dot = true, pulse = false, className, children, ...rest }: StatusChipProps) {
  const t = tones[tone];
  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 truncate rounded-md border px-2 py-0.5 text-xs leading-5',
        t.shell,
        t.text,
        className,
      )}
      {...rest}
    >
      {dot && (
        <span
          aria-hidden
          className={cn('h-1.5 w-1.5 shrink-0 rounded-full', t.dot, pulse && 'animate-pulse')}
        />
      )}
      <span className="truncate">{children}</span>
    </span>
  );
}
