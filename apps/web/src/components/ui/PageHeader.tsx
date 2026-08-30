import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** 页面主标题（必带）。 */
  title: ReactNode;
  /** 一句话说明（可选；超过一句的说明放区块内，不要堆在页头）。 */
  description?: ReactNode;
  /** 标题前的图标或徽标。 */
  icon?: ReactNode;
  /** 页头轻量徽章（如「真实回测」）。 */
  badge?: ReactNode;
  /** 动作区：主 CTA 放第一个，次级操作靠后；超过 3 个动作请收敛进菜单。 */
  actions?: ReactNode;
}

/**
 * 页头：所有模块页统一的标题行。
 * 版式契约——标题左、动作右；描述只有一行且为弱化档；
 * 动作区主次靠按钮变体区分（primary 实心只允许一个）。
 */
export function PageHeader({ title, description, icon, badge, actions, className, ...rest }: PageHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-x-6 gap-y-3', className)} {...rest}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 shrink-0 text-brand-light">{icon}</div>}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="truncate text-xl font-semibold tracking-tight text-neutral-50">{title}</h1>
            {badge}
          </div>
          {description && (
            <p className="mt-1 line-clamp-1 text-sm text-neutral-500" title={typeof description === 'string' ? description : undefined}>
              {description}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
