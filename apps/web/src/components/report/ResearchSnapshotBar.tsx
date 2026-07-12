import { CalendarClock, Database, Fingerprint } from 'lucide-react';

import { ResearchSnapshot } from '../../types';

interface Props {
  snapshot?: ResearchSnapshot;
}

export function ResearchSnapshotBar({ snapshot }: Props) {
  if (!snapshot) return null;

  return (
    <section className="mb-3 rounded-lg border border-white/[0.07] bg-black/20 px-4 py-3" aria-label="研究数据快照">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-neutral-400">
        <span className="inline-flex items-center gap-1.5">
          <CalendarClock className="h-3.5 w-3.5 text-sky-300" />
          截止 {snapshot.effective_as_of || '未指定'}
          <span className={snapshot.cutoff_enforced ? 'text-emerald-300' : 'text-amber-300'}>
            {snapshot.cutoff_enforced ? '已锁定' : '动态'}
          </span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Database className="h-3.5 w-3.5 text-emerald-300" />
          行情 {snapshot.price_data_date || '未知'} · 证据 {snapshot.evidence_count} 条
        </span>
        <span className="inline-flex items-center gap-1.5 font-mono text-neutral-500">
          <Fingerprint className="h-3.5 w-3.5" />
          {snapshot.snapshot_id || 'no-snapshot-id'}
        </span>
      </div>
      {snapshot.research_question && (
        <p className="mt-2 border-t border-white/[0.05] pt-2 text-xs leading-relaxed text-neutral-300">
          {snapshot.research_question}
        </p>
      )}
      {snapshot.warnings.length > 0 && (
        <p className="mt-2 text-[10px] leading-relaxed text-amber-300/80">{snapshot.warnings[0]}</p>
      )}
    </section>
  );
}
