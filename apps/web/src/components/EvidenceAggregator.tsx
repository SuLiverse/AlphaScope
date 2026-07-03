/**
 * 多源证据聚合可视化 — 调 /api/evidence/aggregate, 展示跨源交叉验证结果。
 *
 * 把「注册了但只算单源分」的证据能力, 升级为「多源并行采集 + 跨源去重 + 矛盾检测」
 * 的可视化面板: 来源徽章墙 / 置信度仪表 / 一致性标志 / 矛盾警告 / 按源着色的样本条目。
 * 失败安全: 端点不可用/无数据 → 友好提示, 不崩。
 */

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, Loader2, Search, ShieldCheck } from 'lucide-react';
import { motion } from 'motion/react';
import { fetchApi } from '../lib/api';
import { getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import { STOCK_UNIVERSE, formatStockLabel } from '../lib/stocks';
import { cn } from '../lib/utils';

interface AggregateItem {
  title: string;
  source: string;
  published_at?: string;
  sentiment?: number | null;
  url?: string;
}

interface AggregateResult {
  data_type: string;
  item_count: number;
  sources: string[];
  confidence: number;
  confirmed_by: number;
  contradictions: string[];
  is_high_confidence: boolean;
  is_multi_source: boolean;
  sample_items: AggregateItem[];
}

const DATA_TYPES = [
  { id: 'news', label: '新闻' },
  { id: 'reports', label: '研报' },
  { id: 'announcements', label: '公告' },
  { id: 'fund_flow', label: '资金流' },
];

// 按 source 名稳定着色(同一来源同色)
const SOURCE_COLORS = ['bg-indigo-500/15 text-indigo-300 border-indigo-500/30', 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', 'bg-amber-500/15 text-amber-300 border-amber-500/30', 'bg-sky-500/15 text-sky-300 border-sky-500/30', 'bg-rose-500/15 text-rose-300 border-rose-500/30', 'bg-violet-500/15 text-violet-300 border-violet-500/30'];

function sourceColorClass(source: string, map: Record<string, string>): string {
  if (!map[source]) {
    map[source] = SOURCE_COLORS[Object.keys(map).length % SOURCE_COLORS.length];
  }
  return map[source];
}

export function EvidenceAggregator() {
  const [stock, setStock] = useState(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const [dataType, setDataType] = useState('news');
  const [maxSources, setMaxSources] = useState(3);
  const [result, setResult] = useState<AggregateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const unsubscribe = subscribeStockSelected(({ stock: s }) => setStock(s));
    return unsubscribe;
  }, []);

  const run = useCallback(async () => {
    if (!stock?.symbol) return;
    setLoading(true);
    setError('');
    try {
      const sym = stock.symbol.replace(/\.(SH|SZ|BJ|SS|HK|US)$/i, '');
      const res = await fetchApi<AggregateResult>(
        `/api/evidence/aggregate?symbol=${encodeURIComponent(sym)}&data_type=${dataType}&max_sources=${maxSources}`,
      );
      setResult(res);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : '聚合失败');
    } finally {
      setLoading(false);
    }
  }, [stock, dataType, maxSources]);

  // 按来源着色映射(每次 result 变化重建)
  const colorMap: Record<string, string> = {};
  if (result) {
    result.sources.forEach((s) => sourceColorClass(s, colorMap));
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="mx-auto h-full max-w-6xl overflow-y-auto p-6 lg:p-10"
    >
      <div className="mb-6">
        <h2 className="flex items-center gap-2 text-2xl font-display font-medium text-white">
          <Database className="h-6 w-6 text-indigo-400" />
          多源证据聚合
        </h2>
        <p className="mt-1 text-sm text-neutral-400">
          并行查多个数据源,跨源去重 + 矛盾检测。多源一致 = 高置信;矛盾 = 需人工复核。
        </p>
      </div>

      {/* 控制栏 */}
      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border border-white/5 bg-white/[0.03] p-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-neutral-500">标的</span>
          <span className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-xs font-mono text-neutral-200">
            {formatStockLabel(stock)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-neutral-500">数据类型</span>
          <select
            value={dataType}
            onChange={(e) => setDataType(e.target.value)}
            className="h-8 rounded-lg border border-white/10 bg-black/40 px-2 text-xs text-neutral-200 outline-none"
          >
            {DATA_TYPES.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-neutral-500">最大源数</span>
          <input
            type="number"
            min={1}
            max={5}
            value={maxSources}
            onChange={(e) => setMaxSources(Math.max(1, Math.min(5, Number(e.target.value) || 3)))}
            className="h-8 w-16 rounded-lg border border-white/10 bg-black/40 px-2 text-xs text-neutral-200 outline-none"
          />
        </div>
        <button
          type="button"
          onClick={() => void run()}
          disabled={loading || !stock?.symbol}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/15 px-4 text-xs font-medium text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-40"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          {loading ? '聚合中…' : '开始聚合'}
        </button>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* 结果区 */}
      {result && (
        <div className="space-y-4">
          {result.item_count === 0 ? (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-6 text-center">
              <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-amber-400" />
              <p className="text-sm text-amber-200">本次聚合未采集到数据(无成功返回的源)</p>
              <p className="mt-1 text-xs text-amber-200/70">
                通常因数据源未就绪或缺凭证。请在「设置 → 数据源」配置 akshare/finnhub 等凭证,
                或换一个有数据的标的/类型。默认置信度 60% 是空数据基线,不代表真实证据强度。
              </p>
            </div>
          ) : (
            <>
          {/* 概览卡墙 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <OverviewCard label="采集条数" value={`${result.item_count}`} hint="跨源去重后总数" />
            <OverviewCard
              label="置信度"
              value={`${(result.confidence * 100).toFixed(0)}%`}
              hint={result.is_high_confidence ? '高置信(≥80%)' : '常规置信'}
              tone={result.is_high_confidence ? 'good' : 'neutral'}
            />
            <OverviewCard
              label="多源一致"
              value={`${result.confirmed_by} 源`}
              hint={result.is_multi_source ? '多源确认' : '单源/未交叉'}
              tone={result.is_multi_source ? 'good' : 'neutral'}
            />
            <OverviewCard
              label="矛盾点"
              value={`${result.contradictions.length}`}
              hint={result.contradictions.length > 0 ? '需人工复核' : '无矛盾'}
              tone={result.contradictions.length > 0 ? 'warn' : 'good'}
            />
          </div>

          {/* 来源徽章墙 */}
          {result.sources.length > 0 && (
            <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-4">
              <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">数据来源({result.sources.length})</h3>
              <div className="flex flex-wrap gap-2">
                {result.sources.map((s) => (
                  <span key={s} className={cn('rounded-md border px-2.5 py-1 text-[11px] font-mono', colorMap[s])}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 矛盾警告 */}
          {result.contradictions.length > 0 && (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-mono uppercase tracking-widest text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5" /> 检测到矛盾
              </h3>
              <ul className="space-y-1">
                {result.contradictions.map((c, i) => (
                  <li key={i} className="text-xs leading-relaxed text-amber-200/80">• {c}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 样本条目(按源着色) */}
          {result.sample_items.length > 0 ? (
            <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-4">
              <h3 className="mb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">
                样本条目(前 {result.sample_items.length},按源着色)
              </h3>
              <div className="space-y-2">
                {result.sample_items.map((it, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-lg border border-white/5 bg-black/20 p-3">
                    <span className={cn('mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-mono', sourceColorClass(it.source, colorMap))}>
                      {it.source || '?'}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs text-neutral-200">{it.title || '(无标题)'}</p>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-neutral-500">
                        {it.published_at && <span>{String(it.published_at).slice(0, 10)}</span>}
                        {typeof it.sentiment === 'number' && (
                          <span className={it.sentiment >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                            情绪 {it.sentiment >= 0 ? '+' : ''}{(it.sentiment * 100).toFixed(0)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-white/5 bg-white/[0.02] py-10 text-center">
              <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-neutral-700" />
              <p className="text-xs text-neutral-500">本次采集无样本条目(可能源未就绪或无命中)</p>
            </div>
          )}

          {/* 质量小结 */}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/5 bg-white/[0.02] p-4 text-xs text-neutral-400">
            {result.is_high_confidence && result.is_multi_source && (
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-emerald-300">
                <ShieldCheck className="h-3.5 w-3.5" /> 高置信且多源一致,证据可信度高
              </span>
            )}
            {!result.is_multi_source && (
              <span className="text-amber-300">⚠ 未达多源一致({result.confirmed_by} 源),建议补充来源交叉验证</span>
            )}
            <span className="ml-auto text-neutral-600">仅研究语义,不构成投资建议</span>
          </div>
            </>
          )}
        </div>
      )}

      {!result && !error && !loading && (
        <div className="rounded-2xl border border-white/5 bg-white/[0.02] py-16 text-center">
          <Database className="mx-auto mb-3 h-10 w-10 text-neutral-700" />
          <p className="text-sm text-neutral-500">选择标的与数据类型,点「开始聚合」</p>
          <p className="mt-1 text-xs text-neutral-600">系统会并行查多个数据源并交叉验证</p>
        </div>
      )}
    </motion.div>
  );
}

function OverviewCard({ label, value, hint, tone = 'neutral' }: { label: string; value: string; hint?: string; tone?: 'good' | 'warn' | 'neutral' }) {
  const toneClass = tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : 'text-white';
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
      <p className="text-[10px] font-mono uppercase tracking-wider text-neutral-500">{label}</p>
      <p className={cn('mt-1 text-2xl font-semibold', toneClass)}>{value}</p>
      {hint && <p className="mt-1 text-[10px] text-neutral-500">{hint}</p>}
    </div>
  );
}

export default EvidenceAggregator;
