import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, CheckCheck, ExternalLink, GitCompareArrows, Loader2, Save, X } from 'lucide-react';
import { fetchApi } from '../../lib/api';
import { cn } from '../../lib/utils';
import {
  WORKSPACE_API, REVIEW_LABELS, type ClaimReview, type EvidenceRelation, type ResearchClaim,
  type ResearchVersion, type ReviewStatus, type VersionComparison, type Workspace,
} from '../../lib/researchWorkspace';
import type { EvidencePoolItem } from '../../types';
import { ResearchComparison } from './ResearchComparison';
import type { ReviewProgress } from './ResearchStatusStrip';
import { safeResearchUrl } from '../../lib/researchPresentation';

const controlClass = 'w-full min-w-0 rounded-md border border-white/15 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 outline-none focus:border-emerald-400';
const blankReview = (): ClaimReview => ({ status: 'needs_evidence', reason: '', revised_text: '', evidence_relations: {}, revision: 0, created_at: '' });
const EMPTY_HISTORY: ClaimReview[] = [];

function ClaimEditor({ version, claim, onSaved, onDirtyChange, hasNext }: {
  version: ResearchVersion; claim: ResearchClaim; onSaved: (review: ClaimReview, next: boolean) => void;
  onDirtyChange: (dirty: boolean) => void; hasNext: boolean;
}) {
  const history = version.reviews[claim.id] || EMPTY_HISTORY;
  const [review, setReview] = useState<ClaimReview>(() => history[0] || blankReview());
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const changed = JSON.stringify(review) !== JSON.stringify(history[0] || blankReview());
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    onDirtyChange(saving || changed);
    if (changed) setMessage('');
  }, [changed, saving, onDirtyChange]);
  const evidence = (version.result?.evidence_pool || []) as EvidencePoolItem[];
  const cited = new Set([...claim.evidence_ids, ...claim.agent_evidence_ids]);
  const orderedEvidence = [...evidence].sort((a, b) => Number(cited.has(b.evidence_id)) - Number(cited.has(a.evidence_id)));

  async function save(next = false) {
    setSaving(true); setError(''); setMessage('');
    try {
      const saved = await fetchApi<ClaimReview>(`${WORKSPACE_API}/versions/${version.id}/claims/${claim.id}`, {
        method: 'PUT', body: JSON.stringify({ ...review, expected_revision: review.revision }),
      });
      if (!mounted.current) { onSaved(saved, false); return; }
      setReview(saved); onDirtyChange(false); onSaved(saved, next); setMessage('复核已保存');
    } catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setSaving(false); }
  }

  return <div className="min-w-0 space-y-4">
    <p className="text-xs text-neutral-500">{claim.agent_name} · 原始论断</p>
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-neutral-100">{claim.text}</p>
    <fieldset disabled={saving} className="space-y-3">
      <label className="block text-xs text-neutral-400">复核结论
        <select aria-label="复核结论" value={review.status} onChange={e => setReview({ ...review, status: e.target.value as ReviewStatus })} className={`${controlClass} mt-1`}>
          {Object.entries(REVIEW_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
      </label>
      <label className="block text-xs text-neutral-400">复核理由
        <textarea aria-label="复核理由" value={review.reason} maxLength={4000} rows={3} onChange={e => setReview({ ...review, reason: e.target.value })} className={`${controlClass} mt-1`} />
      </label>
      <label className="block text-xs text-neutral-400">修订后的结论（可选）
        <textarea aria-label="修订后的结论" value={review.revised_text} maxLength={4000} rows={2} onChange={e => setReview({ ...review, revised_text: e.target.value })} className={`${controlClass} mt-1`} />
      </label>
      <h4 className="text-xs font-semibold text-neutral-200">证据与反证</h4>
      {!orderedEvidence.length && <p className="text-xs text-amber-300">此版本没有证据快照，原文与日期待补充。</p>}
      {orderedEvidence.map(item => {
        const url = safeResearchUrl(item.source_url);
        return <div key={item.evidence_id} className="space-y-2 border-t border-white/10 py-3">
          <div className="flex flex-wrap items-center gap-2 break-all text-xs text-neutral-400">
            <span>{item.source || '来源未记录'}</span><span>{item.published_at || '日期未记录'}</span>
            {claim.evidence_ids.includes(item.evidence_id) && <span className="text-emerald-300">论断引用</span>}
            {!claim.evidence_ids.includes(item.evidence_id) && cited.has(item.evidence_id) && <span className="text-amber-300">Agent 引用，未定位到此论断</span>}
            {url && <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sky-300"><ExternalLink className="h-3 w-3" />原文</a>}
          </div>
          <p className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-7 text-neutral-300">{item.excerpt || item.preview || '原文摘录未保存'}</p>
          <select aria-label={`证据 ${item.evidence_id} 与论断的关系`} value={review.evidence_relations[item.evidence_id] || 'unclassified'} onChange={e => setReview({ ...review, evidence_relations: { ...review.evidence_relations, [item.evidence_id]: e.target.value as EvidenceRelation } })} className={controlClass}>
            <option value="unclassified">未分类</option><option value="supports">支持证据</option><option value="opposes">反对证据</option>
          </select>
        </div>;
      })}
      <div className="sticky bottom-0 flex flex-wrap gap-2 border-t border-white/10 bg-neutral-950 py-3">
        <button type="button" onClick={() => void save()} disabled={!review.reason.trim() || saving} className="inline-flex h-10 items-center gap-2 rounded-md bg-emerald-700 px-3 text-sm text-white disabled:opacity-40">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存复核</button>
        <button type="button" onClick={() => void save(true)} disabled={!review.reason.trim() || saving || !hasNext} className="inline-flex h-10 items-center gap-2 rounded-md border border-white/15 px-3 text-sm text-neutral-200 disabled:opacity-40">保存并下一条<ArrowRight className="h-4 w-4" /></button>
        {changed && !saving && <span className="self-center text-xs text-amber-300">未保存</span>}
      </div>
    </fieldset>
    {message && <p role="status" className="text-xs text-emerald-300">{message}</p>}
    {error && <p role="alert" className="break-words text-xs text-rose-300">{error}</p>}
    {!!history.length && <details><summary className="cursor-pointer text-xs text-neutral-400">复核记录 ({history.length})</summary><ol className="mt-2 space-y-3">{history.map(row => <li key={row.revision} className="border-t border-white/10 pt-2 text-xs text-neutral-400"><p>#{row.revision} · {REVIEW_LABELS[row.status]} · {new Date(row.created_at).toLocaleString()}</p><p className="mt-1 whitespace-pre-wrap break-words">{row.reason}</p>{row.revised_text && <p className="mt-1 whitespace-pre-wrap break-words text-neutral-200">{row.revised_text}</p>}</li>)}</ol></details>}
  </div>;
}

export function ResearchReviewPanel({ versionId, view, visible = true, onDirtyChange, onProgress, onVersion }: {
  versionId: string; view?: 'review' | 'compare'; visible?: boolean;
  onDirtyChange?: (dirty: boolean) => void; onProgress?: (progress: ReviewProgress) => void;
  onVersion?: (version: ResearchVersion) => void;
}) {
  const [version, setVersion] = useState<ResearchVersion | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [activeClaim, setActiveClaim] = useState('');
  const [internalTab, setTab] = useState<'review' | 'compare'>('review');
  const tab = view || internalTab;
  const [filter, setFilter] = useState('all');
  const [baseline, setBaseline] = useState('');
  const [comparison, setComparison] = useState<VersionComparison | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const dirty = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const claimList = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onDirtyChange, onProgress, onVersion });
  callbacks.current = { onDirtyChange, onProgress, onVersion };

  function markDirty(value: boolean) {
    dirty.current = value;
    callbacks.current.onDirtyChange?.(value);
  }
  function selectClaim(id: string) {
    if (id === activeClaim) return;
    if (dirty.current && !window.confirm('复核尚未保存，放弃修改？')) return;
    markDirty(false);
    if (id && !dialog.current?.contains(document.activeElement)) lastTrigger.current = document.activeElement as HTMLElement;
    if (!id) dialog.current?.close();
    setActiveClaim(id);
    if (!id) {
      const currentButton = Array.from(claimList.current?.querySelectorAll('button') || []).find(button => button.dataset.claimId === activeClaim);
      (currentButton || (lastTrigger.current?.isConnected ? lastTrigger.current : claimList.current))?.focus();
    }
  }

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty.current) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); callbacks.current.onDirtyChange?.(false); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(''); setComparison(null); setActiveClaim(''); setVersion(null); setWorkspace(null); setBaseline('');
    dirty.current = false; callbacks.current.onDirtyChange?.(false);
    fetchApi<ResearchVersion>(`${WORKSPACE_API}/versions/${versionId}`).then(async data => {
      const saved = await fetchApi<Workspace>(`${WORKSPACE_API}/${data.workspace_id}`);
      if (cancelled) return;
      setVersion(data); setWorkspace(saved);
      callbacks.current.onVersion?.(data);
      setBaseline(saved.versions.find(v => v.status === 'success' && v.number < data.number)?.id || '');
    }).catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [versionId]);

  useEffect(() => {
    let cancelled = false;
    setComparison(null); setComparing(false);
    if (!visible || tab !== 'compare' || !baseline || !version || version.id !== versionId) return;
    setComparing(true); setError('');
    fetchApi<VersionComparison>(`${WORKSPACE_API}/${version.workspace_id}/compare?before=${baseline}&after=${versionId}`)
      .then(data => { if (!cancelled) setComparison(data); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setComparing(false); });
    return () => { cancelled = true; };
  }, [baseline, tab, version, versionId, visible]);

  useEffect(() => {
    if (version?.id === versionId) callbacks.current.onProgress?.({ reviewed: version.claims.filter(c => version.reviews[c.id]?.length).length, total: version.claims.length });
  }, [version, versionId]);

  useEffect(() => {
    const element = dialog.current;
    if (!element || !activeClaim) return;
    const media = window.matchMedia('(min-width: 768px)');
    const sync = () => {
      element.close();
      if (!visible || tab !== 'review') return;
      if (media.matches) element.setAttribute('open', '');
      else element.showModal();
    };
    sync(); media.addEventListener('change', sync);
    return () => { media.removeEventListener('change', sync); element.close(); };
  }, [activeClaim, visible, tab]);

  const claim = version?.claims.find(c => c.id === activeClaim);
  const reviewed = version ? version.claims.filter(c => version.reviews[c.id]?.length).length : 0;
  const filtered = version?.claims.filter(c => filter === 'all' || (filter === 'unreviewed' ? !version.reviews[c.id]?.length : Object.values(version.reviews[c.id]?.[0]?.evidence_relations || {}).includes('opposes'))) || [];
  const index = filtered.findIndex(c => c.id === activeClaim);
  const nextClaim = filtered[index + 1];
  return <section className="min-w-0 py-5" aria-label="研究复核内容">
    {!view && <div role="tablist" aria-label="研究复核" className="mb-4 flex flex-wrap gap-4">
      <button role="tab" aria-selected={tab === 'review'} onClick={() => setTab('review')} className={cn('inline-flex items-center gap-2 border-b-2 pb-2 text-sm', tab === 'review' ? 'border-emerald-400 text-emerald-300' : 'border-transparent text-neutral-400')}><CheckCheck className="h-4 w-4" />逐条复核 {reviewed}/{version?.claims.length || 0}</button>
      <button role="tab" aria-selected={tab === 'compare'} onClick={() => setTab('compare')} className={cn('inline-flex items-center gap-2 border-b-2 pb-2 text-sm', tab === 'compare' ? 'border-sky-400 text-sky-300' : 'border-transparent text-neutral-400')}><GitCompareArrows className="h-4 w-4" />报告差异</button>
    </div>}
    {error && <p role="alert" className="mb-3 break-words text-xs text-rose-300">{error}</p>}
    {loading && <p role="status" className="text-sm text-neutral-400">正在载入研究版本...</p>}
    {!loading && version && <div hidden={tab !== 'review'}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="论断筛选" className="flex border-b border-white/15">
          {([['all', '全部'], ['unreviewed', '未复核'], ['opposed', '存在反证']] as const).map(([key, label]) => <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)} className={cn('min-h-10 border-b-2 px-3 text-sm', filter === key ? 'border-emerald-400 text-emerald-300' : 'border-transparent text-neutral-400')}>{label}</button>)}
        </div><p className="text-xs text-neutral-500">{reviewed}/{version.claims.length} 条已复核</p>
      </div>
      {!version.claims.length && <p className="text-sm text-neutral-400">此版本没有可复核的 Agent 论断。</p>}
      {!!version.claims.length && !filtered.length && <p className="text-sm text-neutral-400">没有符合筛选条件的论断。</p>}
      <div className="grid min-w-0 items-start gap-5 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div ref={claimList} tabIndex={-1} className="max-h-[65vh] overflow-y-auto divide-y divide-white/10">
        {filtered.map(item => {
          const latest = version.reviews[item.id]?.[0];
          return <button type="button" key={item.id} data-claim-id={item.id} aria-pressed={activeClaim === item.id} onClick={() => selectClaim(item.id)} className={cn('block w-full border-l-2 px-3 py-4 text-left text-sm transition-colors hover:bg-white/5', activeClaim === item.id ? 'border-emerald-400 bg-emerald-400/5 text-emerald-200' : 'border-transparent text-neutral-300')}>
            <span className="mb-1 flex flex-wrap gap-2 text-[11px] text-neutral-500"><span>{item.agent_name}</span><span className={latest ? 'text-amber-300' : ''}>{latest ? REVIEW_LABELS[latest.status] : '未复核'}</span></span>
            <span className="block whitespace-pre-wrap break-words leading-relaxed">{latest?.revised_text || item.text}</span>
          </button>;
        })}
      </div>
      {claim ? <dialog ref={dialog} aria-label="论断复核" onCancel={e => { e.preventDefault(); selectClaim(''); }} className="fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto bg-neutral-950 p-4 text-neutral-200 backdrop:bg-black/70 md:static md:m-0 md:h-auto md:max-h-[75vh] md:w-full md:min-w-0 md:border-l md:border-white/10 md:pl-5">
        <div className="mb-4 flex items-center justify-between gap-2 border-b border-white/10 pb-3">
          <h4 className="text-sm font-semibold">论断复核</h4>
          <div className="flex gap-1">
            <button type="button" title="上一条" aria-label="上一条" disabled={index <= 0} onClick={() => selectClaim(filtered[index - 1].id)} className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10 disabled:opacity-30"><ArrowLeft className="h-4 w-4" /></button>
            <button type="button" title="下一条" aria-label="下一条" disabled={!nextClaim} onClick={() => selectClaim(nextClaim.id)} className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10 disabled:opacity-30"><ArrowRight className="h-4 w-4" /></button>
            <button type="button" title="关闭复核" aria-label="关闭复核" onClick={() => selectClaim('')} className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <ClaimEditor key={`${version.id}:${claim.id}`} version={version} claim={claim} onDirtyChange={markDirty} hasNext={!!nextClaim} onSaved={(saved, next) => {
          setVersion(current => current?.id === version.id ? { ...current, reviews: { ...current.reviews, [claim.id]: [saved, ...(current.reviews[claim.id] || [])] } } : current);
          if (next && nextClaim) { markDirty(false); setActiveClaim(nextClaim.id); dialog.current?.scrollTo?.(0, 0); }
        }} />
      </dialog> : <p className="hidden border-l border-white/10 p-5 text-sm text-neutral-500 md:block">尚未选中论断</p>}
      </div>
    </div>}
    {!loading && tab === 'compare' && <div className="space-y-4">
      <label className="block text-xs text-neutral-400">基准版本<select aria-label="基准版本" value={baseline} onChange={e => setBaseline(e.target.value)} className={`${controlClass} mt-1`}>
        {!baseline && <option value="">没有更早的已完成版本</option>}
        {workspace?.versions.filter(v => v.status === 'success' && v.number < (version?.number || 0)).map(v => <option value={v.id} key={v.id}>V{v.number} · {new Date(v.created_at).toLocaleString()}</option>)}
      </select></label>
      {comparing && <p className="text-xs text-neutral-400">正在对比...</p>}
      {comparison && <ResearchComparison comparison={comparison} />}
    </div>}
  </section>;
}
