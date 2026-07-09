import React from 'react';
import { cn } from '../lib/utils';

/** 仅在真正使用本地合成/演示数据时展示，勿用于「真实行情但源降级」。 */
export function SyntheticDataBanner({
  className,
  testId = 'synthetic-data-banner',
}: {
  className?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn(
        'pointer-events-none absolute inset-x-5 top-4 z-20 flex justify-center',
        className,
      )}
    >
      <span className="rounded-md border border-amber-400/40 bg-amber-500/15 px-3 py-1.5 text-center font-mono text-[11px] font-medium tracking-wide text-amber-200 shadow-lg backdrop-blur-sm">
        本地预览 / 合成 K 线 · 非真实行情 · 不可用于投资决策
      </span>
    </div>
  );
}
