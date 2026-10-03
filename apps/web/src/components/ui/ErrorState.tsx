import { AlertTriangle } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button } from './Button';

export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  title?: string;
  className?: string;
}

/** 错误状态：message 必选；传入 onRetry 时展示重试按钮。 */
export function ErrorState({ message, onRetry, title = '加载失败', className }: ErrorStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      <div className="max-w-sm rounded-xl border border-red-500/20 bg-red-500/10 p-5">
        <div className="flex items-center justify-center gap-2 text-sm font-medium text-red-100">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {title}
        </div>
        <p className="mt-2 text-sm text-red-100/70">{message}</p>
        {onRetry && (
          <div className="mt-4 flex justify-center">
            <Button variant="danger" size="sm" onClick={onRetry}>
              重试
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
