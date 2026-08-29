import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const bar = 'rounded bg-surface-hover';

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'card' | 'list' | 'chart';
}

/**
 * 加载占位：variant = card/list/chart。
 * pulse 动画通过 motion-reduce:animate-none 尊重系统 prefers-reduced-motion。
 */
export function Skeleton({ variant = 'card', className, ...rest }: SkeletonProps) {
  return (
    <div
      data-variant={variant}
      aria-hidden="true"
      className={cn('animate-pulse motion-reduce:animate-none', className)}
      {...rest}
    >
      {variant === 'card' && (
        <div className="rounded-xl border border-border-card bg-surface p-5">
          <div className={cn(bar, 'h-4 w-1/3')} />
          <div className={cn(bar, 'mt-4 h-3 w-full')} />
          <div className={cn(bar, 'mt-2 h-3 w-2/3')} />
        </div>
      )}
      {variant === 'list' && (
        <div className="space-y-3">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="flex items-center gap-3">
              <div className={cn(bar, 'h-8 w-8 shrink-0 rounded-full')} />
              <div className="min-w-0 flex-1 space-y-2">
                <div className={cn(bar, 'h-3 w-1/2')} />
                <div className={cn(bar, 'h-3 w-3/4')} />
              </div>
            </div>
          ))}
        </div>
      )}
      {variant === 'chart' && (
        <div className="rounded-xl border border-border-card bg-surface p-5">
          <div className={cn(bar, 'h-4 w-1/4')} />
          <div className="mt-4 flex h-32 items-end gap-2">
            {['h-2/5', 'h-3/5', 'h-1/2', 'h-4/5', 'h-3/5', 'h-full'].map((height, index) => (
              <div key={index} className={cn(bar, 'min-w-0 flex-1', height)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
