import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Webhook,
  RefreshCcw,
  Plus,
  Trash2,
  Download,
  CheckCircle2,
  AlertTriangle,
  Wand2,
} from 'lucide-react';
import { fetchApi } from '../lib/api';

const FIELD_KEYS: Array<{ key: string; label: string; required: boolean }> = [
  { key: 'date', label: '日期', required: true },
  { key: 'open', label: '开盘', required: true },
  { key: 'high', label: '最高', required: true },
  { key: 'low', label: '最低', required: true },
  { key: 'close', label: '收盘', required: true },
  { key: 'volume', label: '成交量', required: false },
  { key: 'amount', label: '成交额', required: false },
  { key: 'symbol', label: '代码', required: false },
];

interface Source {
  id: string;
  name: string;
  url: string;
  symbol: string;
  method: string;
  headers?: Record<string, unknown> | null;
  records_path: string;
  field_map: Record<string, string>;
  last_refresh?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  bar_count: number;
}

interface TickFlowPreview {
  sample?: unknown;
  inferred_field_map?: Record<string, string>;
  record_count?: number;
}

const EMPTY: Source = {
  id: '',
  name: '',
  url: '',
  symbol: '',
  method: 'GET',
  headers: null,
  records_path: '',
  field_map: {},
  bar_count: 0,
};

const fmtDate = (v?: string | null) => {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export const TickFlowManager: React.FC = () => {
  const [sources, setSources] = useState<Source[]>([]);
  const [editing, setEditing] = useState<Source | null>(null);
  const [headersText, setHeadersText] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<TickFlowPreview | null>(null);

  const load = useCallback(async () => {
    setError('');
    try {
      const data = await fetchApi<{ sources: Source[] }>('/api/tickflow/sources');
      setSources(data.sources || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取失败');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const startNew = () => {
    setEditing({ ...EMPTY });
    setHeadersText('');
    setPreview(null);
    setNotice('');
  };

  const startEdit = (s: Source) => {
    setEditing({ ...s, field_map: { ...s.field_map } });
    setHeadersText(s.headers ? JSON.stringify(s.headers, null, 2) : '');
    setPreview(null);
    setNotice('');
  };

  const parseHeaders = (): Record<string, unknown> | null => {
    if (!headersText.trim()) return null;
    try {
      return JSON.parse(headersText);
    } catch {
      throw new Error('请求头不是合法 JSON');
    }
  };

  const doPreview = async () => {
    if (!editing) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetchApi<TickFlowPreview>('/api/tickflow/preview', {
        method: 'POST',
        body: JSON.stringify({
          url: editing.url,
          method: editing.method,
          headers: parseHeaders(),
          records_path: editing.records_path,
        }),
      });
      setPreview(res);
      // 把推断的字段映射填入(仅填空缺项)
      if (res?.inferred_field_map) {
        setEditing((prev) =>
          prev
            ? {
                ...prev,
                field_map: { ...res.inferred_field_map, ...prev.field_map },
              }
            : prev,
        );
      }
      setNotice(`试抓到 ${res?.record_count ?? 0} 条记录,已推断字段映射(可手动调整)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '预览失败');
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const doSave = async () => {
    if (!editing) return;
    setBusy(true);
    setError('');
    try {
      const cleanMap: Record<string, string> = {};
      Object.entries(editing.field_map).forEach(([k, v]) => {
        if (v !== undefined && v !== null && String(v).trim() !== '') cleanMap[k] = String(v).trim();
      });
      await fetchApi('/api/tickflow/sources', {
        method: 'POST',
        body: JSON.stringify({ ...editing, headers: parseHeaders(), field_map: cleanMap }),
      });
      setEditing(null);
      setPreview(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const doRefresh = async (s: Source) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetchApi<{ bar_count?: number; date_range?: string[] }>(`/api/tickflow/sources/${encodeURIComponent(s.id)}/refresh`, { method: 'POST' });
      setNotice(`「${s.name}」拉取成功:${res?.bar_count ?? 0} 根 K 线 (${(res?.date_range || []).join(' ~ ')})`);
      await load();
    } catch (err) {
      setError(`「${s.name}」拉取失败:${err instanceof Error ? err.message : '未知错误'}`);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (s: Source) => {
    if (!window.confirm(`确认删除自定义数据源「${s.name || s.id}」?此操作不可撤销。`)) {
      return;
    }
    setBusy(true);
    try {
      await fetchApi(`/api/tickflow/sources/${encodeURIComponent(s.id)}`, { method: 'DELETE' });
      if (editing?.id === s.id) setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      key="tickflow"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex h-full flex-col gap-4 p-5"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
            <Webhook className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">自定义数据表 · TickFlow</h1>
            <p className="text-xs text-neutral-500">配置外部 HTTP/JSON 行情接口 → 字段映射 → 拉取入查询面(与上传 CSV 并列)</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void load()} className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]">
            <RefreshCcw className="h-3.5 w-3.5" /> 刷新
          </button>
          <button type="button" onClick={startNew} className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-3 py-1.5 text-xs text-indigo-200 transition-colors hover:bg-indigo-500/25">
            <Plus className="h-3.5 w-3.5" /> 新建源
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-2.5 text-xs text-emerald-200">{notice}</div>}

      <div className="flex min-h-0 flex-1 gap-4">
        {/* 源列表 */}
        <div className="flex w-72 flex-shrink-0 flex-col gap-2 overflow-y-auto">
          {sources.length === 0 && (
            <div className="rounded-xl border border-white/[0.06] bg-black/20 px-3 py-8 text-center text-xs text-neutral-500">
              暂无自定义源。点「新建源」配置一个 HTTP/JSON 行情接口。
            </div>
          )}
          {sources.map((s, idx) => {
            const ok = s.last_status === 'ok';
            const err = s.last_status === 'error';
            return (
              <motion.div
                key={s.id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.04, duration: 0.25 }}
                className={`rounded-xl border p-3 ${editing?.id === s.id ? 'border-indigo-400/30 bg-indigo-500/10' : 'border-white/[0.06] bg-black/20'}`}
              >
                <div className="flex items-center justify-between">
                  <button type="button" onClick={() => startEdit(s)} className="text-left text-sm font-medium text-neutral-200 hover:text-indigo-300">
                    {s.name}
                  </button>
                  {ok && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                  {err && <AlertTriangle className="h-4 w-4 text-amber-400" />}
                </div>
                <div className="mt-1 truncate text-[11px] text-neutral-500">{s.symbol || '—'} · {s.bar_count} 根 · {fmtDate(s.last_refresh)}</div>
                {err && s.last_error && <div className="mt-1 truncate text-[11px] text-amber-400/80">{s.last_error}</div>}
                <div className="mt-2 flex gap-1.5">
                  <button type="button" disabled={busy} onClick={() => void doRefresh(s)} className="flex items-center gap-1 rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50">
                    <Download className="h-3 w-3" /> 拉取
                  </button>
                  <button type="button" disabled={busy} onClick={() => void doDelete(s)} className="flex items-center gap-1 rounded border border-red-500/20 bg-red-500/5 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/15 disabled:opacity-50">
                    <Trash2 className="h-3 w-3" /> 删除
                  </button>
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* 编辑表单 */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            {!editing ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="flex h-full items-center justify-center text-sm text-neutral-500"
              >
                选择左侧源编辑,或「新建源」
              </motion.div>
            ) : (
              <motion.div
                key="form"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.25 }}
                className="flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-black/20 p-4"
              >
              <div className="grid grid-cols-2 gap-3">
                <Field label="名称">
                  <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className={inputCls} placeholder="我的K线源" />
                </Field>
                <Field label="股票代码">
                  <input value={editing.symbol} onChange={(e) => setEditing({ ...editing, symbol: e.target.value })} className={inputCls} placeholder="600519" />
                </Field>
              </div>
              <Field label="接口 URL(可用 {symbol} 占位符)">
                <input value={editing.url} onChange={(e) => setEditing({ ...editing, url: e.target.value })} className={inputCls} placeholder="https://api.example.com/kline/{symbol}" />
              </Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="方法">
                  <select value={editing.method} onChange={(e) => setEditing({ ...editing, method: e.target.value })} className={inputCls}>
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                  </select>
                </Field>
                <Field label="记录路径(点路径)">
                  <input value={editing.records_path} onChange={(e) => setEditing({ ...editing, records_path: e.target.value })} className={inputCls} placeholder="data.klines" />
                </Field>
                <div className="flex items-end">
                  <button type="button" disabled={busy || !editing.url} onClick={() => void doPreview()} className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-sky-500/25 bg-sky-500/10 px-3 py-2 text-xs text-sky-200 hover:bg-sky-500/20 disabled:opacity-50">
                    <Wand2 className="h-3.5 w-3.5" /> 试抓并推断映射
                  </button>
                </div>
              </div>
              <Field label="请求头(可选 JSON)">
                <textarea value={headersText} onChange={(e) => setHeadersText(e.target.value)} rows={2} className={`${inputCls} font-mono`} placeholder='{"Authorization": "Bearer ..."}' />
              </Field>

              {/* 字段映射 */}
              <div>
                <div className="mb-2 text-xs text-neutral-400">字段映射(远端字段名 / 数组下标 → 标准列)</div>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  {FIELD_KEYS.map((f) => (
                    <Field key={f.key} label={`${f.label}${f.required ? ' *' : ''}`}>
                      <input
                        value={editing.field_map[f.key] ?? ''}
                        onChange={(e) => setEditing({ ...editing, field_map: { ...editing.field_map, [f.key]: e.target.value } })}
                        className={inputCls}
                        placeholder={f.key}
                      />
                    </Field>
                  ))}
                </div>
              </div>

              {preview?.sample != null && (
                <div className="rounded-lg border border-white/[0.06] bg-black/30 p-3">
                  <div className="mb-1 text-[11px] text-neutral-500">样本记录(首条)</div>
                  <pre className="max-h-32 overflow-auto text-[11px] text-neutral-400">{JSON.stringify(preview.sample, null, 2)}</pre>
                </div>
              )}

              <div className="flex gap-2 pt-1">
                <button type="button" disabled={busy} onClick={() => void doSave()} className="rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-4 py-2 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-50">
                  保存
                </button>
                <button type="button" onClick={() => setEditing(null)} className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs text-neutral-300 hover:bg-white/10">
                  取消
                </button>
              </div>
            </motion.div>
          )}
          </AnimatePresence>
          <p className="mt-3 pb-2 text-[11px] leading-relaxed text-neutral-600">
            网络仅在「试抓 / 拉取」时发生且失败安全(失败不清空已有缓存)。拉取的数据明确标注来源 `http_json` / 用户自配,
            绝不冒充内置在线源;入库后仅供历史查询与回测,不预测、不构成投资建议。
          </p>
        </div>
      </div>
    </motion.div>
  );
};

const inputCls =
  'w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-indigo-400/40';

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="flex flex-col gap-1">
    <span className="text-[11px] text-neutral-500">{label}</span>
    {children}
  </label>
);
