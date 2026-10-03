import { useEffect, useRef, useState } from 'react';
import { FolderOpen, Loader2, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { fetchApi } from '../../lib/api';
import {
  LAST_WORKSPACE_KEY, WORKSPACE_API, VERSION_LABELS, saveResearchDraft,
  type ResearchDraft, type ResearchMaterial, type ResearchVersion, type Workspace,
} from '../../lib/researchWorkspace';

const inputClass = 'w-full min-w-0 rounded-md border border-white/15 bg-neutral-950 px-2 py-2 text-xs text-neutral-200 outline-none focus:border-emerald-400';
const toolClass = 'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-neutral-300 hover:bg-white/10 disabled:opacity-40';

interface Props {
  draft: ResearchDraft;
  workspaceId: string;
  versionId: string;
  busy: boolean;
  refreshKey: number;
  onSaved: (workspaceId: string) => void;
  onRestore: (workspace: Workspace, version?: ResearchVersion) => void;
  onNew: () => void;
  onMaterials: (materials: ResearchMaterial[]) => void;
  onStarted: (taskId: string, versionId: string) => void;
  beforeRetry?: () => boolean;
}

export function ResearchWorkspacePanel(props: Props) {
  const { workspaceId, refreshKey, versionId, busy } = props;
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const restored = useRef(false);
  const requestSeq = useRef(0);
  const callbacks = useRef(props);
  callbacks.current = props;

  useEffect(() => {
    let cancelled = false;
    fetchApi<{ workspaces: Workspace[] }>(WORKSPACE_API).then(async (data) => {
      if (cancelled) return;
      setWorkspaces(data.workspaces);
      if (!restored.current) {
        restored.current = true;
        const last = localStorage.getItem(LAST_WORKSPACE_KEY);
        if (!workspaceId && last && data.workspaces.some(w => w.id === last)) {
          const saved = await fetchApi<Workspace>(`${WORKSPACE_API}/${last}`);
          const latest = saved.versions[0];
          const version = latest ? await fetchApi<ResearchVersion>(`${WORKSPACE_API}/versions/${latest.id}`) : undefined;
          if (!cancelled) callbacks.current.onRestore(saved, version);
        }
      }
    }).catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [workspaceId, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    if (!workspaceId) { setWorkspace(null); return; }
    fetchApi<Workspace>(`${WORKSPACE_API}/${workspaceId}`).then((data) => {
      if (!cancelled) setWorkspace(data);
    }).catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [workspaceId, refreshKey]);

  async function open(id: string, selectedVersion?: string) {
    const seq = ++requestSeq.current;
    setPending(true); setError(''); setMessage('');
    try {
      const saved = await fetchApi<Workspace>(`${WORKSPACE_API}/${id}`);
      const vid = selectedVersion || saved.versions[0]?.id;
      const version = vid ? await fetchApi<ResearchVersion>(`${WORKSPACE_API}/versions/${vid}`) : undefined;
      if (seq === requestSeq.current) props.onRestore(selectedVersion && version ? { ...saved, draft: version.input } : saved, version);
    } catch (e) { if (seq === requestSeq.current) setError((e as Error).message); }
    finally { if (seq === requestSeq.current) setPending(false); }
  }

  async function save() {
    setPending(true); setError('');
    try {
      const saved = await saveResearchDraft(props.draft, workspaceId);
      props.onSaved(saved.id); setWorkspace(saved); setMessage('草稿已保存');
    } catch (e) { setError((e as Error).message); }
    finally { setPending(false); }
  }

  async function retry() {
    if (props.beforeRetry && !props.beforeRetry()) return;
    setPending(true); setError('');
    try {
      const data = await fetchApi<{ task_id: string; version_id: string }>('/api/analysis/async', {
        method: 'POST', body: JSON.stringify({ stock_symbol: props.draft.stock_symbol, workspace_id: workspaceId, retry_from: versionId }),
      });
      props.onStarted(data.task_id, data.version_id);
    } catch (e) { setError((e as Error).message); }
    finally { setPending(false); }
  }

  const current = workspace?.versions.find(v => v.id === versionId);
  function updateMaterial(index: number, field: keyof ResearchMaterial, value: string | null) {
    props.onMaterials(props.draft.materials.map((m, i) => i === index ? { ...m, [field]: value } : m));
  }

  return <section className="grid shrink-0 min-w-0 items-center gap-3 border-y border-white/10 py-3 text-xs lg:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)]">
    <div className="flex items-center gap-2">
      <FolderOpen className="h-4 w-4 text-emerald-400" />
      <h3 className="flex-1 font-semibold text-neutral-100">研究工作区</h3>
      {pending && <Loader2 className="h-4 w-4 animate-spin" />}
      <button type="button" title="保存研究草稿" aria-label="保存研究草稿" disabled={busy || pending} onClick={() => void save()} className={toolClass}><Save className="h-4 w-4" /></button>
      <button type="button" title="新建研究" aria-label="新建研究" disabled={busy || pending} onClick={() => { props.onNew(); setMessage(''); setError(''); }} className={toolClass}><Plus className="h-4 w-4" /></button>
    </div>
    <select aria-label="研究工作区" value={workspaceId} disabled={busy || pending} onChange={e => { if (e.target.value) void open(e.target.value); }} className={inputClass}>
      <option value="">未保存的研究</option>
      {workspaces.map(w => <option key={w.id} value={w.id}>{w.draft.stock_name || w.draft.stock_symbol} · {w.draft.research_question || '未命名研究'}</option>)}
      {workspaceId && !workspaces.some(w => w.id === workspaceId) && <option value={workspaceId}>{props.draft.stock_name} · 当前研究</option>}
    </select>
    {!!workspace?.versions.length && <select aria-label="报告版本" value={versionId} disabled={busy || pending} onChange={e => void open(workspaceId, e.target.value)} className={inputClass}>
      <option value="" disabled>选择报告版本</option>
      {workspace.versions.map(v => <option key={v.id} value={v.id}>V{v.number} · {VERSION_LABELS[v.status]} · {new Date(v.created_at).toLocaleString()}</option>)}
    </select>}
    {current && ['failed', 'cancelled'].includes(current.status) && <div className="space-y-2 border-l-2 border-amber-400 pl-3 lg:col-span-3">
      <p className="break-words text-amber-300">{current.stage === 'market' ? '行情采集未完成' : '研究分析未完成'}</p>
      <p className="break-words text-neutral-400">{current.error || '任务已取消'}</p>
      <button type="button" onClick={() => void retry()} disabled={busy || pending} className="inline-flex items-center gap-2 text-emerald-300 disabled:opacity-40"><RotateCcw className="h-4 w-4" />重试失败步骤</button>
    </div>}
    <details className="min-w-0 lg:col-span-3">
      <summary className="cursor-pointer py-1 text-neutral-300">研究资料 ({props.draft.materials.length})</summary>
      <div className="mt-2 max-h-64 space-y-3 overflow-y-auto">
        {props.draft.materials.map((material, index) => <fieldset key={index} disabled={busy || pending} className="space-y-2 border-t border-white/10 pt-3">
          <div className="flex gap-1"><input aria-label={`资料 ${index + 1} 标题`} placeholder="资料标题" maxLength={300} value={material.title} onChange={e => updateMaterial(index, 'title', e.target.value)} className={inputClass} /><button type="button" title="删除资料" aria-label={`删除资料 ${index + 1}`} className={toolClass} onClick={() => props.onMaterials(props.draft.materials.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></button></div>
          <input aria-label={`资料 ${index + 1} 原文链接`} type="url" placeholder="原文链接" maxLength={2000} value={material.source_url} onChange={e => updateMaterial(index, 'source_url', e.target.value)} className={inputClass} />
          <input aria-label={`资料 ${index + 1} 日期`} type="date" value={material.published_at || ''} onChange={e => updateMaterial(index, 'published_at', e.target.value || null)} className={`${inputClass} [color-scheme:dark]`} />
          <textarea aria-label={`资料 ${index + 1} 原文摘录`} placeholder="原文摘录" rows={3} maxLength={12000} value={material.excerpt} onChange={e => updateMaterial(index, 'excerpt', e.target.value)} className={inputClass} />
          {props.draft.as_of && (!material.published_at || material.published_at > props.draft.as_of) && <p className="text-amber-300">日期缺失或晚于截止日，本次分析将排除此资料。</p>}
        </fieldset>)}
        <button type="button" disabled={busy || pending || props.draft.materials.length >= 30} onClick={() => props.onMaterials([...props.draft.materials, { title: '', source_url: '', published_at: null, excerpt: '' }])} className="inline-flex items-center gap-1 text-emerald-300 disabled:opacity-40"><Plus className="h-4 w-4" />添加资料</button>
      </div>
    </details>
    {message && <p role="status" className="text-emerald-300">{message}</p>}
    {error && <p role="alert" className="break-words text-rose-300">{error}</p>}
  </section>;
}
