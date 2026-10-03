import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const paddings = {
  none: '',
  sm: 'p-3',
  md: 'p-5',
  lg: 'p-6',
} as const;

const roundeds = {
  lg: 'rounded-lg',
  xl: 'rounded-xl',
  '2xl': 'rounded-2xl',
} as const;

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: keyof typeof paddings;
  rounded?: keyof typeof roundeds;
}

/** 玻璃风卡片容器：bg-surface + border-border-card，padding/rounded 可配。 */
export function Card({ padding = 'md', rounded = 'xl', className, children, ...rest }: CardProps) {
  return (
    <div
      className={cn('border border-border-card bg-surface', paddings[padding], roundeds[rounded], className)}
      {...rest}
    >
      {children}
    </div>
  );
}
