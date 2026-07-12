import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { ResearchTrust } from '../../types';
import { cn } from '../../lib/utils';

interface Props {
  trust?: ResearchTrust;
}

const METRICS: Array<{ key: keyof ResearchTrust['metrics']; label: string }> = [
  { key: 'coverage', label: '证据覆盖' },
  { key: 'source_completeness', label: '来源完整' },
  { key: 'date_completeness', label: '日期完整' },
  { key: 'freshness', label: '时效性' },
  { key: 'source_quality', label: '来源质量' },
  { key: 'source_diversity', label: '交叉验证' },
];

const TONES: Record<ResearchTrust['grade'], { border: string; text: string; bar: string; background: string }> = {
  high: {
    border: 'border-emerald-500/25',
    text: 'text-emerald-300',
    bar: 'bg-emerald-400',
    background: 'bg-emerald-500/[0.06]',
  },
  medium: {
    border: 'border-sky-500/25',
    text: 'text-sky-300',
    bar: 'bg-sky-400',
    background: 'bg-sky-500/[0.06]',
  },
  low: {
    border: 'border-amber-500/25',
    text: 'text-amber-300',
    bar: 'bg-amber-400',
    background: 'bg-amber-500/[0.06]',
  },
  insufficient: {
    border: 'border-rose-500/25',
    text: 'text-rose-300',
    bar: 'bg-rose-400',
    background: 'bg-rose-500/[0.06]',
  },
};

export function ResearchTrustPanel({ trust }: Props) {
  if (!trust) return null;

  const tone = TONES[trust.grade] ?? TONES.insufficient;
  const score = Math.min(100, Math.max(0, Number(trust.score) || 0));
  const hasWarnings = trust.warnings.length > 0;

  return (
    <section className={cn('mb-6 rounded-lg border p-4', tone.border, tone.background)} aria-label="研究可信度">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border', tone.border, tone.text)}>
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="text-sm font-semibold text-neutral-100">研究可信度</h3>
              <span className={cn('text-xs font-medium', tone.text)}>{trust.label}</span>
            </div>
            <p className="mt-1 text-[11px] text-neutral-500">
              {trust.evidence_count} 条证据 · {trust.source_count} 个独立来源 · 评分仅衡量可审计性
            </p>
          </div>
        </div>
        <div className={cn('font-mono text-2xl font-semibold tabular-nums', tone.text)}>
          {score}<span className="ml-1 text-xs text-neutral-500">/ 100</span>
        </div>
      </div>

      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-black/40">
        <div className={cn('h-full rounded-full transition-[width]', tone.bar)} style={{ width: `${score}%` }} />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
        {METRICS.map(({ key, label }) => {
          const value = Math.min(1, Math.max(0, Number(trust.metrics[key]) || 0));
          return (
            <div key={key} className="min-w-0">
              <dt className="truncate text-[10px] text-neutral-500">{label}</dt>
              <dd className="mt-0.5 font-mono text-xs font-medium tabular-nums text-neutral-200">
                {(value * 100).toFixed(0)}%
              </dd>
            </div>
          );
        })}
      </dl>

      {hasWarnings ? (
        <div className="mt-4 border-t border-white/[0.06] pt-3">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            需要复核
          </div>
          <ul className="space-y-1 text-[11px] leading-relaxed text-neutral-400">
            {trust.warnings.slice(0, 4).map((warning) => <li key={warning.code}>- {warning.message}</li>)}
          </ul>
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-1.5 border-t border-white/[0.06] pt-3 text-[10px] text-emerald-300/80">
          <CheckCircle2 className="h-3.5 w-3.5" />
          未发现显著的来源、日期或交叉验证缺口
        </div>
      )}
    </section>
  );
}
