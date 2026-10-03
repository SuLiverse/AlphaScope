import { Database, Files, CheckCheck } from 'lucide-react';
import { deriveDataIntegritySeverity } from '../../lib/analysisAdapter';
import type { AnalysisResult } from '../../types';

export interface ReviewProgress { reviewed: number; total: number }

export function ResearchStatusStrip({ result, progress }: { result: AnalysisResult; progress: ReviewProgress | null }) {
  const severity = deriveDataIntegritySeverity(result);
  const evidence = result.evidence_pool || [];
  const sourced = evidence.filter(item => Boolean(item.source?.trim())).length;
  const dated = evidence.filter(item => Boolean(item.published_at?.trim())).length;
  const labels = { green: '记录未报错', yellow: '部分降级', red: '严重降级', unknown: '状态未记录' };
  return <dl aria-label="研究状态" className="grid grid-cols-3 gap-3 border-y border-white/10 py-4">
    <div className="min-w-0"><dt className="flex items-center gap-1 text-xs text-neutral-400 sm:gap-2"><Database className="h-4 w-4 shrink-0" />数据采集</dt><dd className="mt-1 text-sm text-neutral-200">{labels[severity]}<span className="block text-xs text-neutral-500">{result.provider_traces.length} 条请求记录</span></dd></div>
    <div className="min-w-0"><dt className="flex items-center gap-1 text-xs text-neutral-400 sm:gap-2"><Files className="h-4 w-4 shrink-0" />证据快照</dt><dd className="mt-1 text-sm text-neutral-200">{evidence.length} 条已保存<span className="block text-xs text-neutral-500">来源 {sourced}/{evidence.length} · 日期 {dated}/{evidence.length}</span></dd></div>
    <div className="min-w-0"><dt className="flex items-center gap-1 text-xs text-neutral-400 sm:gap-2"><CheckCheck className="h-4 w-4 shrink-0" />人工复核</dt><dd className="mt-1 break-words text-sm text-neutral-200">{progress ? `${progress.reviewed}/${progress.total} 条已复核` : '未载入复核记录'}</dd></div>
  </dl>;
}
