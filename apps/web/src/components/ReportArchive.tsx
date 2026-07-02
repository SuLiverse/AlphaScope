import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Archive,
  RefreshCw,
  Search,
  Trash2,
  TrendingUp,
  TrendingDown,
  X,
  Loader2,
  FileText,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { fetchApi } from '../lib/api';
import { cn } from '../lib/utils';

interface ArchiveStats {
  total: number;
  buy: number;
  sell: number;
  hold: number;
  stocks: number;
  latest: string | null;
  fallback_total?: number;
  distinct_combos?: number;
}

interface ArchiveItem {
  timestamp: string;
  date: string;
  time?: string;
  type?: string;
  stock_name: string;
  symbol: string;
  decision: string;
  buy?: number;
  sell?: number;
  hold?: number;
  avg_confidence?: number;
  chairman_excerpt?: string;
  combo_signature?: string;
  path: string;
  filename?: string;
  // 后验标签(archive_tagger 回填)
  ret_3d?: number;
  ret_5d?: number;
  ret_10d?: number;
  ret_20d?: number;
  hit_3d?: boolean;
  hit_5d?: boolean;
  hit_10d?: boolean;
  max_drawdown_10d?: number;
}

const DECISION_TONE = (decision: string) => {
  if (decision.includes('买入')) return 'text-rose-300 bg-rose-500/10 border-rose-500/20';
  if (decision.includes('卖出')) return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20';
  return 'text-neutral-300 bg-white/5 border-white/10';
};

const fmtPct = (n: number | undefined) =>
  n === undefined || n === null || Number.isNaN(n) ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

export function ReportArchive() {
  const [items, setItems] = useState<ArchiveItem[]>([]);
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [deleteMsg, setDeleteMsg] = useState('');
  const [query, setQuery] = useState('');
  const [decisionFilter, setDecisionFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [selected, setSelected] = useState<ArchiveItem | null>(null);
  const [reportText, setReportText] = useState('');
  const [loadingReport, setLoadingReport] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMsg, setBackfillMsg] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set('stock', query.trim());
      if (decisionFilter) params.set('decision', decisionFilter);
      if (typeFilter) params.set('type', typeFilter);
      params.set('limit', '200');
      const [listRes, statsRes] = await Promise.all([
        fetchApi<{ reports: ArchiveItem[]; total: number }>(`/api/archive?${params.toString()}`),
        fetchApi<ArchiveStats>('/api/archive/stats'),
      ]);
      setItems(listRes?.reports || []);
      setStats(statsRes || null);
    } catch (e) {
      setItems([]);
      setStats(null);
      setLoadError(e instanceof Error ? e.message : '加载归档报告失败');
    } finally {
      setLoading(false);
    }
  }, [query, decisionFilter, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const openReport = async (item: ArchiveItem) => {
    setSelected(item);
    setLoadingReport(true);
    setReportText('');
    try {
      const res = await fetchApi<{ path: string; content: string }>(
        `/api/archive/report/${encodeURIComponent(item.path)}`,
      );
      setReportText(res?.content || '(空报告)');
    } catch {
      setReportText('报告加载失败');
    } finally {
      setLoadingReport(false);
    }
  };

  const deleteReport = async (item: ArchiveItem) => {
    if (!window.confirm(`确认删除 ${item.stock_name}(${item.symbol}) ${item.date} 的报告?`)) return;
    try {
      await fetchApi(`/api/archive/report/${encodeURIComponent(item.path)}`, { method: 'DELETE' });
      if (selected?.path === item.path) setSelected(null);
      setDeleteMsg('');
      await load();
    } catch (e) {
      setDeleteMsg(`删除失败:${e instanceof Error ? e.message : '未知错误'}`);
    }
  };

  const runBackfill = async () => {
    setBackfilling(true);
    setBackfillMsg('');
    try {
      const res = await fetchApi<{ tagged: number; skipped: number; errors: number }>(
        '/api/archive/backfill',
        { method: 'POST' },
      );
      setBackfillMsg(`回填完成:新增标签 ${res?.tagged ?? 0} 条 / 跳过 ${res?.skipped ?? 0} / 待补 ${res?.errors ?? 0}`);
      await load();
    } catch (e) {
      setBackfillMsg(e instanceof Error ? e.message : '后验回填失败');
    } finally {
      setBackfilling(false);
    }
  };

  const hitBadge = (label: string, hit?: boolean) => {
    if (hit === undefined) return null;
    return (
      <span
        className={cn(
          'rounded px-1.5 py-0.5 text-[10px] font-mono',
          hit ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300',
        )}
        title={`${label}后验命中`}
      >
        {label}{hit ? '✓' : '✗'}
      </span>
    );
  };

  const statCards = useMemo(() => {
    if (!stats) return [];
    return [
      { label: '归档报告', value: stats.total, tone: 'indigo' as const },
      { label: '建议买入', value: stats.buy, tone: 'rose' as const },
      { label: '建议卖出', value: stats.sell, tone: 'emerald' as const },
      { label: '建议观望', value: stats.hold, tone: 'neutral' as const },
      { label: '覆盖股票', value: stats.stocks, tone: 'sky' as const },
      {
        label: '模型组合',
        value: stats.distinct_combos ?? 0,
        tone: 'amber' as const,
      },
    ];
  }, [stats]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto h-full max-w-7xl overflow-y-auto p-6 lg:p-10"
    >
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-3 text-2xl font-display font-medium text-neutral-100">
            <Archive className="h-6 w-6 text-indigo-500" />
            研究存档中心
          </h2>
          <p className="mt-2 text-sm text-neutral-500">
            研报全文归档、按标的检索、3/5/10/20 日后验涨跌命中、模型组合横向统计。
          </p>
        </div>
        <button
          type="button"
          onClick={runBackfill}
          disabled={backfilling}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-neutral-200 transition-colors hover:bg-white/[0.08] disabled:opacity-40"
          title="为所有归档报告回填后验收益与命中标签"
        >
          {backfilling ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          回填后验标签
        </button>
      </div>

      {backfillMsg && (
        <p className="mb-4 text-xs text-neutral-400">{backfillMsg}</p>
      )}

      {/* 统计卡片 */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {statCards.map((s) => (
          <div
            key={s.label}
            className={cn(
              'rounded-xl border bg-white/[0.03] p-4',
              s.tone === 'indigo' && 'border-indigo-500/20',
              s.tone === 'rose' && 'border-rose-500/20',
              s.tone === 'emerald' && 'border-emerald-500/20',
              s.tone === 'sky' && 'border-sky-500/20',
              s.tone === 'amber' && 'border-amber-500/20',
              s.tone === 'neutral' && 'border-white/10',
            )}
          >
            <p className="text-[10px] uppercase tracking-widest text-neutral-500">{s.label}</p>
            <p className="mt-1 font-mono text-2xl text-neutral-100">{s.value}</p>
          </div>
        ))}
      </div>

      {/* 筛选栏 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-600" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void load()}
            placeholder="按股票名称或代码搜索…"
            className="h-10 w-full rounded-lg border border-white/10 bg-black/35 pl-9 pr-3 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-indigo-400/50"
          />
        </div>
        <select
          value={decisionFilter}
          onChange={(e) => setDecisionFilter(e.target.value)}
          className="h-10 rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-200 outline-none"
        >
          <option value="">全部决策</option>
          <option value="买入">建议买入</option>
          <option value="卖出">建议卖出</option>
          <option value="观望">建议观望</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="h-10 rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-200 outline-none"
        >
          <option value="">全部类型</option>
          <option value="agent">Agent 分析</option>
          <option value="roundtable">圆桌纪要</option>
          <option value="frontend_report">前端研报</option>
        </select>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-10 items-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-500/15 px-3 text-sm text-indigo-200 hover:bg-indigo-500/25"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          查询
        </button>
      </div>

      {/* 报告列表 */}
      <div className="space-y-2">
        {loadError && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2">
            <span className="text-xs text-rose-300">加载失败:{loadError}</span>
            <button
              type="button"
              onClick={() => void load()}
              className="ml-auto text-[11px] text-rose-200 underline-offset-2 hover:underline"
            >
              重试
            </button>
          </div>
        )}
        {deleteMsg && (
          <p className="mb-3 text-xs text-rose-400">{deleteMsg}</p>
        )}
        {loading ? (
          <p className="py-12 text-center text-sm text-neutral-500">加载中…</p>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-white/5 bg-white/[0.02] py-16 text-center">
            <FileText className="mx-auto mb-3 h-10 w-10 text-neutral-700" />
            <p className="text-sm text-neutral-500">
              {loadError ? '加载失败,请重试' : '暂无归档报告'}
            </p>
            {!loadError && (
              <p className="mt-1 text-xs text-neutral-600">
                生成研究报告或圆桌分析后,结果会自动归档到此
              </p>
            )}
          </div>
        ) : (
          items.map((item) => {
            const ret = item.ret_5d;
            const hasRet = ret !== undefined && ret !== null;
            return (
              <div
                key={item.path}
                className="group flex cursor-pointer items-center gap-4 rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-colors hover:border-indigo-500/30 hover:bg-white/[0.04]"
                onClick={() => void openReport(item)}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-neutral-100">
                      {item.stock_name}
                    </span>
                    <span className="font-mono text-[11px] text-neutral-500">{item.symbol}</span>
                    <span
                      className={cn(
                        'rounded border px-1.5 py-0.5 text-[10px]',
                        DECISION_TONE(item.decision || ''),
                      )}
                    >
                      {item.decision || '未知'}
                    </span>
                    {item.type && (
                      <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-neutral-500">
                        {item.type === 'roundtable' ? '圆桌' : item.type === 'agent' ? 'Agent' : item.type}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-1 text-xs text-neutral-500">
                    {item.chairman_excerpt || '(无摘要)'}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-neutral-600">
                    <span>{item.date} {item.time || ''}</span>
                    <span>· 置信度 {(item.avg_confidence ?? 0).toFixed(0)}%</span>
                    {item.combo_signature && (
                      <span className="font-mono">· {item.combo_signature.slice(0, 30)}</span>
                    )}
                    {hasRet && (
                      <span
                        className={cn(
                          'inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono',
                          ret! >= 0 ? 'bg-rose-500/10 text-rose-300' : 'bg-emerald-500/10 text-emerald-300',
                        )}
                        title="5 日后验涨跌"
                      >
                        {ret! >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                        5日 {fmtPct(ret)}
                      </span>
                    )}
                    {hitBadge('3日', item.hit_3d)}
                    {hitBadge('5日', item.hit_5d)}
                    {hitBadge('10日', item.hit_10d)}
                    {item.max_drawdown_10d !== undefined && (
                      <span className="rounded bg-rose-500/10 px-1.5 py-0.5 font-mono text-rose-300/80" title="10 日最大回撤">
                        回撤 {item.max_drawdown_10d.toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteReport(item);
                  }}
                  className="shrink-0 rounded-lg p-2 text-neutral-600 opacity-0 transition-opacity hover:bg-rose-500/10 hover:text-rose-400 group-hover:opacity-100"
                  title="删除"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* 报告详情抽屉 */}
      <AnimatePresence>
        {selected && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[200] flex justify-end bg-black/60"
            onClick={() => setSelected(null)}
          >
            <motion.div
              initial={{ x: 40 }}
              animate={{ x: 0 }}
              exit={{ x: 40 }}
              onClick={(e) => e.stopPropagation()}
              className="flex h-full w-full max-w-2xl flex-col border-l border-white/10 bg-[#0b0c12]"
            >
              <div className="flex items-center justify-between border-b border-white/5 p-4">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-neutral-100">
                    {selected.stock_name} ({selected.symbol})
                  </h3>
                  <p className="text-[11px] text-neutral-500">
                    {selected.date} {selected.time || ''} · {selected.decision}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded-md p-1.5 text-neutral-500 hover:bg-white/5 hover:text-neutral-300"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-5">
                {loadingReport ? (
                  <p className="text-sm text-neutral-500">加载中…</p>
                ) : (
                  <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-neutral-300">
                    {reportText}
                  </pre>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default ReportArchive;
