import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'motion/react';
import {
  Database,
  RefreshCcw,
  DownloadCloud,
  Filter,
  Play,
  Trash2,
  AlertTriangle,
  Plus,
  X,
} from 'lucide-react';
import { fetchApi } from '../lib/api';

const NUMERIC_FIELDS = ['close', 'open', 'high', 'low', 'volume', 'amount'];
const OPS = ['>', '>=', '<', '<=', '=', '!='];

interface LakeStatus {
  available: boolean;
  symbol_count: number;
  row_count: number;
  size_bytes: number;
  date_range: string[];
  disclaimer?: string;
}

interface ScreenRow {
  symbol: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

interface FilterRow {
  field: string;
  op: string;
  value: string;
}

const fmtBytes = (n: number) => {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${u[i]}`;
};

export const DataLakeManager: React.FC = () => {
  const [status, setStatus] = useState<LakeStatus | null>(null);
  const [symbolsText, setSymbolsText] = useState('');
  const [filters, setFilters] = useState<FilterRow[]>([{ field: 'close', op: '>', value: '' }]);
  const [orderBy, setOrderBy] = useState('close');
  const [descending, setDescending] = useState(true);
  const [screenRows, setScreenRows] = useState<ScreenRow[]>([]);
  const [sql, setSql] = useState('SELECT symbol, COUNT(*) AS bars, MAX(close) AS last_close FROM prices GROUP BY symbol ORDER BY bars DESC');
  const [queryRows, setQueryRows] = useState<Record<string, unknown>[]>([]);
  const [queryCols, setQueryCols] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    setError('');
    try {
      const data = await fetchApi<LakeStatus>('/api/datalake/status');
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取失败');
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const doIngest = async () => {
    const symbols = symbolsText.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (symbols.length === 0) {
      setError('请输入至少一个股票代码');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetchApi<{ ingested?: number; requested?: number }>('/api/datalake/ingest', {
        method: 'POST',
        body: JSON.stringify({ symbols }),
      });
      setNotice(`入湖完成:${res?.ingested ?? 0}/${res?.requested ?? symbols.length} 只成功`);
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : '入湖失败');
    } finally {
      setBusy(false);
    }
  };

  const doScreen = async () => {
    setBusy(true);
    setError('');
    try {
      const cleanFilters = filters
        .filter((f) => f.value.trim() !== '' && !Number.isNaN(Number(f.value)))
        .map((f) => ({ field: f.field, op: f.op, value: Number(f.value) }));
      const res = await fetchApi<{ rows?: ScreenRow[]; matched?: number }>('/api/datalake/screen', {
        method: 'POST',
        body: JSON.stringify({ filters: cleanFilters, order_by: orderBy, descending, limit: 200 }),
      });
      setScreenRows(res?.rows || []);
      setNotice(`筛选命中 ${res?.matched ?? 0} 只(基于历史行情,不构成选股建议)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '筛选失败');
    } finally {
      setBusy(false);
    }
  };

  const doQuery = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await fetchApi<{ columns?: string[]; rows?: Record<string, unknown>[]; row_count?: number }>('/api/datalake/query', {
        method: 'POST',
        body: JSON.stringify({ sql, limit: 500 }),
      });
      setQueryCols(res?.columns || []);
      setQueryRows(res?.rows || []);
      setNotice(`查询返回 ${res?.row_count ?? 0} 行`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '查询失败');
      setQueryRows([]);
      setQueryCols([]);
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm('确认清空整个数据湖?所有已入湖的行情数据将被删除,此操作不可撤销。')) {
      return;
    }
    setBusy(true);
    try {
      await fetchApi('/api/datalake/all', { method: 'DELETE' });
      setScreenRows([]);
      setQueryRows([]);
      await loadStatus();
      setNotice('已清空数据湖');
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空失败');
    } finally {
      setBusy(false);
    }
  };

  const updateFilter = (i: number, patch: Partial<FilterRow>) =>
    setFilters((prev) => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));

  return (
    <motion.div
      key="datalake"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex h-full flex-col gap-4 overflow-y-auto p-5"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
            <Database className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">数据湖 · DuckDB / Parquet</h1>
            <p className="text-xs text-neutral-500">行情列式物化 → 一条 SQL 跨标的批量扫描 / 选股 / 因子底座</p>
          </div>
        </div>
        <button type="button" onClick={() => void loadStatus()} className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]">
          <RefreshCcw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {error && <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-2.5 text-xs text-emerald-200">{notice}</div>}

      {status && !status.available && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            数据湖未启用:未检测到 <code className="rounded bg-black/30 px-1">duckdb</code>。请运行 <code className="rounded bg-black/30 px-1">pip install duckdb</code> 后重启后端。
            其余功能不受影响。
          </div>
        </div>
      )}

      {/* 状态卡 */}
      {status && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="已入湖标的" value={`${status.symbol_count}`} index={0} />
          <StatCard label="总行数" value={status.row_count.toLocaleString()} index={1} />
          <StatCard label="日期范围" value={status.date_range?.length ? `${status.date_range[0]} ~ ${status.date_range[1]}` : '—'} small index={2} />
          <StatCard label="占用空间" value={fmtBytes(status.size_bytes)} index={3} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 入湖 */}
        <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
            <DownloadCloud className="h-4 w-4 text-indigo-300" /> 行情入湖
          </h3>
          <textarea
            value={symbolsText}
            onChange={(e) => setSymbolsText(e.target.value)}
            rows={3}
            placeholder="输入股票代码,空格/逗号/换行分隔，如:600519 000001 600036"
            className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-indigo-400/40"
          />
          <div className="mt-2 flex items-center gap-2">
            <button type="button" disabled={busy || !status?.available} onClick={() => void doIngest()} className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-3 py-2 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-50">
              <DownloadCloud className="h-3.5 w-3.5" /> 取数入湖
            </button>
            <button type="button" disabled={busy || !status?.symbol_count} onClick={() => void clearAll()} className="flex items-center gap-1.5 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-300 hover:bg-red-500/15 disabled:opacity-50">
              <Trash2 className="h-3.5 w-3.5" /> 清空
            </button>
          </div>
        </div>

        {/* 批量筛选 */}
        <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
            <Filter className="h-4 w-4 text-indigo-300" /> 批量筛选(每标的最新一根)
          </h3>
          <div className="flex flex-col gap-2">
            {filters.map((f, i) => (
              <div key={i} className="flex items-center gap-2">
                <select value={f.field} onChange={(e) => updateFilter(i, { field: e.target.value })} className={selectCls}>
                  {NUMERIC_FIELDS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <select value={f.op} onChange={(e) => updateFilter(i, { op: e.target.value })} className={selectCls}>
                  {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <input value={f.value} onChange={(e) => updateFilter(i, { value: e.target.value })} placeholder="数值" className={`${selectCls} flex-1`} />
                <button type="button" onClick={() => setFilters((p) => p.filter((_, idx) => idx !== i))} className="text-neutral-500 hover:text-red-400">
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
            <button type="button" onClick={() => setFilters((p) => [...p, { field: 'volume', op: '>', value: '' }])} className="flex w-fit items-center gap-1 text-[11px] text-indigo-300 hover:text-indigo-200">
              <Plus className="h-3 w-3" /> 加条件
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <span className="text-[11px] text-neutral-500">排序</span>
            <select value={orderBy} onChange={(e) => setOrderBy(e.target.value)} className={selectCls}>
              {NUMERIC_FIELDS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <button type="button" onClick={() => setDescending((d) => !d)} className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-neutral-300">
              {descending ? '降序 ↓' : '升序 ↑'}
            </button>
            <button type="button" disabled={busy || !status?.available} onClick={() => void doScreen()} className="ml-auto flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-3 py-1.5 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-50">
              <Play className="h-3.5 w-3.5" /> 运行筛选
            </button>
          </div>
        </div>
      </div>

      {/* 筛选结果 */}
      {screenRows.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="rounded-xl border border-white/[0.06] bg-black/20 p-4"
        >
          <h3 className="mb-3 text-sm font-medium text-neutral-200">筛选结果 · {screenRows.length} 只</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-neutral-500">
                  {['代码', '日期', '开', '高', '低', '收', '量', '额'].map((h) => <th key={h} className="py-2 pr-3 font-normal">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {screenRows.map((r) => (
                  <tr key={r.symbol} className="border-b border-white/[0.03] text-neutral-300">
                    <td className="py-1.5 pr-3 font-medium text-neutral-200">{r.symbol}</td>
                    <td className="py-1.5 pr-3 text-neutral-400">{r.date}</td>
                    <td className="py-1.5 pr-3">{r.open}</td>
                    <td className="py-1.5 pr-3">{r.high}</td>
                    <td className="py-1.5 pr-3">{r.low}</td>
                    <td className="py-1.5 pr-3 text-rose-300">{r.close}</td>
                    <td className="py-1.5 pr-3 text-neutral-400">{r.volume}</td>
                    <td className="py-1.5 pr-3 text-neutral-400">{r.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      )}

      {/* 只读 SQL */}
      <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
          <Play className="h-4 w-4 text-indigo-300" /> 只读 SQL(表名 prices,仅 SELECT)
        </h3>
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={3}
          className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 font-mono text-[11px] text-neutral-200 outline-none focus:border-indigo-400/40"
        />
        <button type="button" disabled={busy || !status?.available} onClick={() => void doQuery()} className="mt-2 flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-3 py-1.5 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-50">
          <Play className="h-3.5 w-3.5" /> 运行查询
        </button>
        {queryCols.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-3 overflow-x-auto"
          >
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-neutral-500">
                  {queryCols.map((c) => <th key={c} className="py-2 pr-3 font-normal">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {queryRows.map((r, i) => (
                  <tr key={i} className="border-b border-white/[0.03] text-neutral-300">
                    {queryCols.map((c) => <td key={c} className="py-1.5 pr-3">{String(r[c] ?? '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </motion.div>
        )}
      </div>

      <p className="pb-2 text-[11px] leading-relaxed text-neutral-600">
        数据湖为历史行情的列式副本,批量筛选描述「过去满足条件的标的」,既不预测也不构成选股建议。SQL 仅允许只读查询。
      </p>
    </motion.div>
  );
};

const selectCls = 'rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-neutral-200 outline-none focus:border-indigo-400/40';

const StatCard: React.FC<{ label: string; value: string; small?: boolean; index?: number }> = ({ label, value, small, index = 0 }) => (
  <motion.div
    initial={{ opacity: 0, y: 6 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay: index * 0.05, duration: 0.25 }}
    className="rounded-xl border border-white/[0.06] bg-black/20 p-3"
  >
    <div className="text-[11px] text-neutral-500">{label}</div>
    <div className={`mt-1 font-semibold text-neutral-200 ${small ? 'text-xs' : 'text-lg'}`}>{value}</div>
  </motion.div>
);
