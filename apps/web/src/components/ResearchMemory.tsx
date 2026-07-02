import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  History,
  RefreshCcw,
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowRight,
  Trash2,
  ShieldAlert,
  Activity,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { fetchApi } from '../lib/api';

// A 股配色:看多红 / 看空绿 / 观望琥珀。
const SIGNAL_META: Record<string, { color: string; chip: string; icon: React.ReactNode }> = {
  买入: { color: '#f43f5e', chip: 'border-rose-500/25 bg-rose-500/10 text-rose-300', icon: <TrendingUp className="h-3.5 w-3.5" /> },
  卖出: { color: '#10b981', chip: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300', icon: <TrendingDown className="h-3.5 w-3.5" /> },
  观望: { color: '#f59e0b', chip: 'border-amber-500/25 bg-amber-500/10 text-amber-300', icon: <Minus className="h-3.5 w-3.5" /> },
};

const signalMeta = (s?: string) =>
  (s && SIGNAL_META[s]) || { color: '#a3a3a3', chip: 'border-white/10 bg-white/5 text-neutral-300', icon: <Minus className="h-3.5 w-3.5" /> };

const DIRECTION_CHIP: Record<string, string> = {
  转积极: 'border-rose-500/25 bg-rose-500/10 text-rose-300',
  转谨慎: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  横盘: 'border-white/10 bg-white/5 text-neutral-300',
  调整: 'border-white/10 bg-white/5 text-neutral-300',
};

interface SymbolRow {
  symbol: string;
  name: string;
  count: number;
  latest_date: string;
  latest_signal: string;
  latest_confidence: number;
}

interface Snapshot {
  snapshot_id: string;
  symbol: string;
  name: string;
  created_at: string;
  signal: string;
  confidence: number;
  buy: number;
  sell: number;
  hold: number;
  consensus: string;
  consensus_score: number;
  divergence: string;
  risk_vetoed: boolean;
  data_status: string;
  close: number;
  mode: string;
}

interface ChangePoint {
  from: string;
  to: string;
  from_date: string;
  to_date: string;
  confidence_from: number;
  confidence_to: number;
  direction: string;
}

interface Timeline {
  symbol: string;
  name: string;
  snapshots: Snapshot[];
  changes: ChangePoint[];
  summary: {
    count: number;
    latest_signal: string;
    latest_confidence: number;
    first_date: string;
    latest_date: string;
    signal_distribution: Record<string, number>;
    change_count: number;
    avg_confidence: number;
  };
}

const fmtDate = (v?: string) => {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

const fmtDay = (v?: string) => {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v.slice(5, 10);
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
};

export const ResearchMemory: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<string>('');
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadSymbols = useCallback(async () => {
    setError('');
    try {
      const data = await fetchApi<{ symbols: SymbolRow[]; total: number }>('/api/research-memory/symbols');
      setSymbols(data.symbols || []);
      setTotal(data.total || 0);
      setSelected((prev) => prev || (data.symbols && data.symbols[0] ? data.symbols[0].symbol : ''));
    } catch (err) {
      setError(err instanceof Error ? err.message : '研究记忆读取失败');
    }
  }, []);

  const loadTimeline = useCallback(async (symbol: string) => {
    if (!symbol) {
      setTimeline(null);
      return;
    }
    setLoading(true);
    try {
      const data = await fetchApi<Timeline>(`/api/research-memory/timeline/${encodeURIComponent(symbol)}`);
      setTimeline(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '时间线读取失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSymbols();
  }, [loadSymbols]);

  useEffect(() => {
    if (selected) void loadTimeline(selected);
  }, [selected, loadTimeline]);

  const handleDeleteSymbol = async (symbol: string) => {
    if (!window.confirm(`确认清空 ${symbol} 的全部研究记忆?所有历史快照将被删除,此操作不可撤销。`)) {
      return;
    }
    try {
      await fetchApi(`/api/research-memory/symbol/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
      setSelected('');
      setTimeline(null);
      await loadSymbols();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  const chartData = useMemo(
    () =>
      (timeline?.snapshots || []).map((s) => ({
        date: fmtDay(s.created_at),
        confidence: Number(s.confidence) || 0,
        signal: s.signal,
        close: Number(s.close) || 0,
      })),
    [timeline],
  );

  return (
    <motion.div
      key="research-memory"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex h-full flex-col gap-4 p-5"
    >
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
            <History className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">研究记忆</h1>
            <p className="text-xs text-neutral-500">同一股票的研究结论随时间变化轨迹 · 共 {total} 条快照</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadSymbols()}
          className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]"
        >
          <RefreshCcw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">{error}</div>
      )}

      <div className="flex min-h-0 flex-1 gap-4">
        {/* 左:股票列表 */}
        <div className="flex w-56 flex-shrink-0 flex-col gap-1.5 overflow-y-auto rounded-xl border border-white/[0.06] bg-black/20 p-2">
          {symbols.length === 0 && (
            <div className="px-2 py-8 text-center text-xs text-neutral-500">
              暂无研究记忆。<br />运行一次「对话式研究 / 研究报告生成」后,结论会自动记入这里。
            </div>
          )}
          {symbols.map((s, idx) => {
            const meta = signalMeta(s.latest_signal);
            const active = s.symbol === selected;
            return (
              <motion.button
                key={s.symbol}
                type="button"
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.04, duration: 0.25 }}
                onClick={() => setSelected(s.symbol)}
                className={`flex flex-col gap-1 rounded-lg border px-3 py-2 text-left transition-colors ${
                  active ? 'border-indigo-400/30 bg-indigo-500/10' : 'border-transparent bg-white/[0.02] hover:bg-white/[0.05]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-neutral-200">{s.symbol}</span>
                  <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${meta.chip}`}>
                    {meta.icon}
                    {s.latest_signal}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span className="truncate">{s.name || '—'}</span>
                  <span>{s.count} 次 · {fmtDay(s.latest_date)}</span>
                </div>
              </motion.button>
            );
          })}
        </div>

        {/* 右:时间线 */}
        <div className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto">
          <AnimatePresence mode="wait">
          {!timeline ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex h-full items-center justify-center text-sm text-neutral-500"
            >
              {loading ? '加载中…' : '选择左侧股票查看研究记忆'}
            </motion.div>
          ) : (
            <motion.div
              key="timeline"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="flex flex-col gap-4"
            >
              {/* 总结卡 */}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <StatCard label="研究次数" value={`${timeline.summary.count}`} sub={`${fmtDay(timeline.summary.first_date)} 起`} index={0} />
                <StatCard
                  label="最新结论"
                  value={timeline.summary.latest_signal || '—'}
                  valueColor={signalMeta(timeline.summary.latest_signal).color}
                  sub={fmtDate(timeline.summary.latest_date)}
                  index={1}
                />
                <StatCard label="结论变化" value={`${timeline.summary.change_count} 次`} sub="信号转折点" index={2} />
                <StatCard label="平均置信度" value={`${timeline.summary.avg_confidence}`} sub={`最新 ${timeline.summary.latest_confidence}`} index={3} />
              </div>

              {/* 结论变化轨迹 */}
              <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="flex items-center gap-2 text-sm font-medium text-neutral-200">
                    <Activity className="h-4 w-4 text-indigo-300" /> 结论变化轨迹
                  </h3>
                  <button
                    type="button"
                    onClick={() => void handleDeleteSymbol(timeline.symbol)}
                    className="flex items-center gap-1 rounded border border-red-500/20 bg-red-500/5 px-2 py-1 text-[11px] text-red-300 transition-colors hover:bg-red-500/15"
                  >
                    <Trash2 className="h-3 w-3" /> 清空本股记忆
                  </button>
                </div>
                {timeline.changes.length === 0 ? (
                  <p className="text-xs text-neutral-500">结论保持一致,暂无转折。</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {timeline.changes.map((c, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ delay: i * 0.05, duration: 0.25 }}
                        className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-xs"
                      >
                        <span className="text-neutral-500">{fmtDay(c.from_date)}</span>
                        <span style={{ color: signalMeta(c.from).color }}>{c.from}</span>
                        <ArrowRight className="h-3 w-3 text-neutral-600" />
                        <span style={{ color: signalMeta(c.to).color }}>{c.to}</span>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] ${DIRECTION_CHIP[c.direction] || DIRECTION_CHIP.调整}`}>
                          {c.direction}
                        </span>
                      </motion.div>
                    ))}
                  </div>
                )}
              </div>

              {/* 置信度趋势 */}
              {chartData.length > 1 && (
                <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
                  <h3 className="mb-3 text-sm font-medium text-neutral-200">置信度趋势</h3>
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#737373' }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#737373' }} />
                        <Tooltip
                          contentStyle={{ background: '#171717', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }}
                          labelStyle={{ color: '#a3a3a3' }}
                        />
                        <Line type="monotone" dataKey="confidence" stroke="#818cf8" strokeWidth={2} dot={{ r: 3 }} name="置信度" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* 快照表 */}
              <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4">
                <h3 className="mb-3 text-sm font-medium text-neutral-200">历史快照</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-left text-neutral-500">
                        <th className="py-2 pr-3 font-normal">时间</th>
                        <th className="py-2 pr-3 font-normal">结论</th>
                        <th className="py-2 pr-3 font-normal">置信度</th>
                        <th className="py-2 pr-3 font-normal">多空裁决</th>
                        <th className="py-2 pr-3 font-normal">分歧</th>
                        <th className="py-2 pr-3 font-normal">风控</th>
                        <th className="py-2 pr-3 font-normal">收盘</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...timeline.snapshots].reverse().map((s) => {
                        const meta = signalMeta(s.signal);
                        return (
                          <tr key={s.snapshot_id} className="border-b border-white/[0.03] text-neutral-300">
                            <td className="py-2 pr-3 text-neutral-400">{fmtDate(s.created_at)}</td>
                            <td className="py-2 pr-3">
                              <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 ${meta.chip}`}>
                                {meta.icon}
                                {s.signal}
                              </span>
                            </td>
                            <td className="py-2 pr-3">{s.confidence || '—'}</td>
                            <td className="py-2 pr-3">
                              {s.consensus || '—'}
                              {s.consensus_score ? <span className="text-neutral-600"> ({s.consensus_score})</span> : null}
                            </td>
                            <td className="py-2 pr-3 text-neutral-400">{s.divergence || '—'}</td>
                            <td className="py-2 pr-3">
                              {s.risk_vetoed ? (
                                <span className="inline-flex items-center gap-1 text-red-300">
                                  <ShieldAlert className="h-3 w-3" /> 否决
                                </span>
                              ) : (
                                <span className="text-neutral-600">通过</span>
                              )}
                            </td>
                            <td className="py-2 pr-3 text-neutral-400">{s.close || '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </motion.div>
          )}
          </AnimatePresence>

          <p className="pb-2 text-[11px] leading-relaxed text-neutral-600">
            研究记忆仅记录与回看历史分析结论的变化,描述「过去如何判断」,不预测未来、不构成任何投资建议。
          </p>
        </div>
      </div>
    </motion.div>
  );
};

const StatCard: React.FC<{ label: string; value: string; sub?: string; valueColor?: string; index?: number }> = ({
  label,
  value,
  sub,
  valueColor,
  index = 0,
}) => (
  <motion.div
    initial={{ opacity: 0, y: 6 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay: index * 0.05, duration: 0.25 }}
    className="rounded-xl border border-white/[0.06] bg-black/20 p-3"
  >
    <div className="text-[11px] text-neutral-500">{label}</div>
    <div className="mt-1 text-lg font-semibold" style={{ color: valueColor || '#e5e5e5' }}>
      {value}
    </div>
    {sub && <div className="mt-0.5 text-[10px] text-neutral-600">{sub}</div>}
  </motion.div>
);
