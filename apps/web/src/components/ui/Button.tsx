import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const variants = {
  primary: 'border-brand/50 bg-brand/15 text-indigo-200 hover:bg-brand/25',
  ghost: 'border-border-strong text-neutral-200 hover:bg-surface-hover',
  danger: 'border-red-500/20 bg-red-500/10 text-red-200 hover:bg-red-500/20',
} as const;

const sizes = {
  sm: 'rounded-lg px-2.5 py-1.5 text-xs',
  md: 'rounded-xl px-3 py-2 text-sm',
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

/** 统一样式按钮：variant = primary/ghost/danger，size = sm/md；继承 button 原生 props。 */
export function Button({ variant = 'primary', size = 'md', type = 'button', className, children, ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
