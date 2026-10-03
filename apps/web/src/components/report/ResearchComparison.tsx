import { useState } from 'react';
import { ArrowRight, ExternalLink } from 'lucide-react';
import type { VersionChange, VersionComparison } from '../../lib/researchWorkspace';
import { researchFieldLabel, researchValue, safeResearchUrl } from '../../lib/researchPresentation';

function Value({ value, evidence }: { value: unknown; evidence?: boolean }) {
  if (evidence && value && typeof value === 'object' && !Array.isArray(value)) {
    const item = value as Record<string, string>;
    const url = safeResearchUrl(item.source_url);
    return <div className="space-y-2 text-sm"><p>{item.source || '来源未记录'} · {item.published_at || '日期未记录'}</p><p className="whitespace-pre-wrap break-words leading-7">{item.excerpt || item.preview || '原文摘录未保存'}</p>{url && <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sky-300"><ExternalLink className="h-3.5 w-3.5" />原文</a>}<p className="break-all text-xs text-neutral-500">{item.evidence_id}</p></div>;
  }
  return <p className="whitespace-pre-wrap break-words text-sm leading-7">{researchValue(value)}</p>;
}

function Change({ change, evidence }: { change: VersionChange; evidence?: boolean }) {
  const content = <div className="grid min-w-0 gap-4 py-3 sm:grid-cols-2">
    <div className="min-w-0 border-l-2 border-neutral-600 pl-3 text-neutral-400"><p className="mb-2 text-xs text-neutral-500">基准版本</p><Value value={change.before} evidence={evidence} /></div>
    <div className="min-w-0 border-l-2 border-sky-500 pl-3 text-neutral-200"><p className="mb-2 text-xs text-neutral-500">当前版本</p><Value value={change.after} evidence={evidence} /></div>
  </div>;
  const name = researchFieldLabel(change.field);
  if (evidence) {
    const item = (change.after || change.before) as Record<string, string> | null;
    return <details className="border-t border-white/10 py-3"><summary className="cursor-pointer break-words text-sm text-neutral-200">{item?.source || '来源未记录'} · {item?.published_at || '日期未记录'}<span className="ml-2 text-xs text-sky-300">{({ added: '新增', removed: '移除', changed: '更新', unchanged: '未变化' } as Record<string, string>)[change.status] || change.status}</span></summary>{content}</details>;
  }
  return <div className="border-t border-white/10 pt-3"><h5 className="break-words text-sm text-sky-300">{name}</h5>{content}</div>;
}

export function ResearchComparison({ comparison }: { comparison: VersionComparison }) {
  const [showUnchanged, setShowUnchanged] = useState(false);
  const changed = (items: VersionChange[]) => items.filter(item => item.status !== 'unchanged');
  return <div className="min-w-0 space-y-5">
    <p className="text-sm leading-7 text-neutral-200">{comparison.summary}</p>
    <section aria-label="结论变化" className="border-y border-white/10 py-4">
      <h4 className="flex items-center gap-2 text-sm font-semibold text-neutral-100">综合结论<ArrowRight className="h-4 w-4 text-sky-300" /><span className="font-normal text-neutral-400">{comparison.conclusion.changed ? '已变化' : '已记录结论一致'}</span></h4>
      <Change change={{ field: '结论', ...comparison.conclusion, status: comparison.conclusion.changed ? 'changed' : 'unchanged' }} />
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm text-neutral-300"><span>证据 {changed(comparison.evidence).length} 条变化</span><span>指标 {changed(comparison.metrics).length} 项变化</span><span>Agent {changed(comparison.agents).length} 项变化</span><span>已记录模型字段{changed(comparison.models).length ? '有变化' : '一致'}</span></div>
    </section>
    <div className="space-y-2 border-l-2 border-amber-400/60 pl-3">{comparison.warnings.map(w => <p key={w} className="text-sm leading-relaxed text-amber-200/80">{w}</p>)}</div>
    <label className="flex items-center gap-2 text-sm text-neutral-400"><input type="checkbox" checked={showUnchanged} onChange={e => setShowUnchanged(e.target.checked)} className="accent-sky-400" />显示无差异分组</label>
    {([
      ['研究条件', comparison.context], ['证据', comparison.evidence], ['指标', comparison.metrics],
      ['Agent 观点', comparison.agents], ['模型配置', comparison.models],
    ] as const).map(([label, items]) => {
      const rows = showUnchanged ? items : changed(items);
      if (!rows.length && !showUnchanged) return null;
      const content = <>{!rows.length && <p className="py-3 text-sm text-neutral-500">已记录字段无差异，不代表未记录的信息没有变化。</p>}{rows.map(row => <Change key={row.field} change={row} evidence={label === '证据'} />)}</>;
      return label === '模型配置' ? <details key={label} className="border-y border-white/10 py-3"><summary className="cursor-pointer text-sm text-neutral-200">{label} ({rows.length})</summary>{content}</details> : <section key={label}><h4 className="mb-3 text-sm font-semibold text-neutral-100">{label} ({rows.length})</h4>{content}</section>;
    })}
  </div>;
}
