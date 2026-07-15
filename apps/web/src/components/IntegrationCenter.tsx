import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Boxes, RefreshCcw, ShieldCheck, ExternalLink, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { fetchApi } from '../lib/api';
import {
  normalizeParamSweepResult,
  type ParamSweepResult,
} from '../lib/integrationContracts';

// ====== types ======
interface CapabilitySpec {
  name: string;
  description: string;
}
interface IntegrationMetadata {
  name: string;
  category: string;
  mode: string;
  version: string;
  display_name: string;
  description: string;
  homepage: string | null;
  package: string | null;
  capabilities: CapabilitySpec[];
  license_name: string | null;
  license_safety: string;
  code_copy_allowed: boolean;
  allow_live_order: boolean;
  requires_evidence: boolean;
}
interface IntegrationHealth {
  name: string;
  status: string;
  message: string;
  last_check: string;
  degraded_reasons: string[];
}
interface IntegrationItem extends IntegrationMetadata {
  health: IntegrationHealth | null;
}
interface BoundaryOverview {
  flags: Record<string, boolean>;
  forbidden_symbol_names: string[];
  live_order_blocked: boolean;
  config_path: string;
}

// ====== display maps ======
const CATEGORY_LABEL: Record<string, string> = {
  backtest: '回测引擎',
  data: '数据源',
  factor: '因子 / ML',
  agent: 'Agent 团队',
  document: '文档 / RAG',
  ui: '可视化',
};

const LICENSE_LABEL: Record<string, { text: string; tone: string }> = {
  safe: { text: 'SAFE · 可融合', tone: 'text-emerald-300' },
  copyleft_risk: { text: 'COPILEFT · 仅外部进程', tone: 'text-amber-300' },
  noncommercial: { text: '非商业', tone: 'text-amber-300' },
  proprietary: { text: '商业 / BSL', tone: 'text-red-300' },
  unknown: { text: '未知', tone: 'text-neutral-400' },
};

const MODE_LABEL: Record<string, string> = {
  native: '内置',
  python_adapter: 'pip 可选依赖',
  external_process: '外部进程',
};

function formatMetric(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? '--' : value.toFixed(digits);
}

function formatProbability(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '--' : `${(value * 100).toFixed(1)}%`;
}

function formatPercentMetric(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '--' : `${value.toFixed(2)}%`;
}

function selectionBiasLabel(status: string) {
  if (status === 'insufficient') return '样本不足';
  if (status === 'error') return '计算失败';
  return '未核验';
}

function HealthBadge({ status }: { status: string }) {
  const map: Record<string, { icon: React.ReactNode; text: string; tone: string }> = {
    healthy: { icon: <CheckCircle2 className="h-3.5 w-3.5" />, text: '可用', tone: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20' },
    degraded: { icon: <AlertTriangle className="h-3.5 w-3.5" />, text: '降级', tone: 'text-amber-300 bg-amber-500/10 border-amber-500/20' },
    unavailable: { icon: <XCircle className="h-3.5 w-3.5" />, text: '未装', tone: 'text-neutral-400 bg-white/[0.03] border-white/10' },
    down: { icon: <XCircle className="h-3.5 w-3.5" />, text: '异常', tone: 'text-red-300 bg-red-500/10 border-red-500/20' },
  };
  const m = map[status] || map.unavailable;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium ${m.tone}`}>
      {m.icon}
      {m.text}
    </span>
  );
}

export const IntegrationCenter: React.FC = () => {
  const [items, setItems] = useState<IntegrationItem[]>([]);
  const [boundary, setBoundary] = useState<BoundaryOverview | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sweepSymbol, setSweepSymbol] = useState('600519');
  const [sweepBusy, setSweepBusy] = useState(false);
  const [sweepResult, setSweepResult] = useState<ParamSweepResult | null>(null);
  const [sweepError, setSweepError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [listResult, boundaryResult] = await Promise.allSettled([
        fetchApi<{ integrations: IntegrationItem[]; count: number }>('/api/integrations'),
        fetchApi<BoundaryOverview>('/api/integrations/boundary'),
      ]);
      const errors: string[] = [];
      if (listResult.status === 'fulfilled') {
        setItems(listResult.value.integrations || []);
      } else {
        setItems([]);
        errors.push(listResult.reason instanceof Error ? listResult.reason.message : '集成列表读取失败');
      }
      if (boundaryResult.status === 'fulfilled') {
        setBoundary(boundaryResult.value);
      } else {
        setBoundary(null);
        errors.push(boundaryResult.reason instanceof Error ? boundaryResult.reason.message : '交易边界读取失败');
      }
      setError(errors.join('；'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取集成中心失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 按类别分组
  const byCategory = items.reduce<Record<string, IntegrationItem[]>>((acc, it) => {
    (acc[it.category] ||= []).push(it);
    return acc;
  }, {});
  const categoryOrder = ['backtest', 'data', 'factor', 'agent', 'document', 'ui'];

  return (
    <motion.div
      key="integration-center"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="flex h-full flex-col gap-4 overflow-y-auto p-5"
    >
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
            <Boxes className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">集成中心 · Integration Registry</h1>
            <p className="text-xs text-neutral-500">外部开源项目通过统一 adapter 协议接入, 全部 allow_live_order=False</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06] disabled:opacity-50"
        >
          <RefreshCcw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">{error}</div>
      )}

      {/* 交易边界概览 */}
      {boundary && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-4"
        >
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-300" />
            <h3 className="text-sm font-medium text-neutral-100">交易边界 · No-Live-Order</h3>
            {boundary.live_order_blocked ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">
                <CheckCircle2 className="h-3 w-3" /> 已阻断实盘下单
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300">
                <AlertTriangle className="h-3 w-3" /> 边界异常
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-neutral-400 md:grid-cols-4">
            {Object.entries(boundary.flags).map(([k, v]) => (
              <div key={k} className="flex items-center gap-1.5">
                <span className={v ? 'text-emerald-400' : 'text-neutral-500'}>{v ? '✓' : '✗'}</span>
                <code className="text-neutral-300">{k}</code>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-neutral-500">
            禁止符号名 (源码扫描): {boundary.forbidden_symbol_names.join(' / ')}
          </p>
        </motion.div>
      )}

      {/* adapter 列表, 按类别分组 */}
      {categoryOrder.map((cat) => {
        const group = byCategory[cat];
        if (!group || group.length === 0) return null;
        return (
          <div key={cat}>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
              {CATEGORY_LABEL[cat] || cat} · {group.length}
            </h2>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {group.map((it, idx) => {
                const lic = LICENSE_LABEL[it.license_safety] || LICENSE_LABEL.unknown;
                return (
                  <motion.div
                    key={it.name}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.04, duration: 0.25 }}
                    className="flex flex-col gap-2.5 rounded-xl border border-white/[0.06] bg-black/20 p-3.5"
                  >
                    {/* 标题行 */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-semibold text-neutral-100">{it.display_name || it.name}</span>
                          <code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-neutral-400">{it.name}</code>
                          {it.allow_live_order === false && (
                            <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">no-live</span>
                          )}
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-[11px] text-neutral-500">{it.description}</p>
                      </div>
                      {it.health && <HealthBadge status={it.health.status} />}
                    </div>

                    {/* 健康 message */}
                    {it.health?.message && (
                      <p className="rounded-md bg-white/[0.02] px-2 py-1.5 text-[11px] text-neutral-400">{it.health.message}</p>
                    )}

                    {/* 能力列表 */}
                    {it.capabilities.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {it.capabilities.map((c) => (
                          <span key={c.name} className="rounded border border-indigo-400/20 bg-indigo-500/10 px-1.5 py-0.5 text-[10px] text-indigo-200">
                            {c.name}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* 元信息 */}
                    <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/[0.04] pt-2 text-[10px] text-neutral-500">
                      <span>{MODE_LABEL[it.mode] || it.mode}</span>
                      <span>v{it.version}</span>
                      <span className={lic.tone}>{lic.text}</span>
                      {it.license_name && <code className="text-neutral-500">{it.license_name}</code>}
                      {it.requires_evidence && <span className="text-sky-300">需证据</span>}
                      {it.homepage && (
                        <a href={it.homepage} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-0.5 text-neutral-400 hover:text-neutral-200">
                          主页 <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* 空状态 */}
      {items.length === 0 && !error && !loading && (
        <div className="rounded-xl border border-white/[0.06] bg-black/20 p-8 text-center text-xs text-neutral-500">
          暂无已注册的 adapter
        </div>
      )}

      {/* vectorbt 参数扫描 */}
      <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/[0.04] p-4">
        <h3 className="mb-2 text-sm font-medium text-neutral-100">vectorbt 快速参数扫描</h3>
        <p className="mb-3 text-[11px] text-neutral-500">
          服务端取行情 + 网格扫描; 结果附 DSR 选择偏差校正。需 pip install vectorbt。不模拟完整 A 股摩擦。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={sweepSymbol}
            onChange={(e) => setSweepSymbol(e.target.value)}
            className="h-9 w-32 rounded-lg border border-white/10 bg-black/30 px-3 text-xs text-neutral-100"
            placeholder="代码"
          />
          <button
            type="button"
            disabled={sweepBusy}
            onClick={async () => {
              setSweepBusy(true);
              setSweepError('');
              setSweepResult(null);
              try {
                const data = await fetchApi<unknown>('/api/integrations/vectorbt/param-sweep', {
                  method: 'POST',
                  body: JSON.stringify({
                    symbol: sweepSymbol.trim(),
                    days: 250,
                    param_grid: { fast: [5, 10, 20], slow: [30, 60] },
                    top_n: 10,
                  }),
                });
                setSweepResult(normalizeParamSweepResult(data));
              } catch (err) {
                setSweepError(err instanceof Error ? err.message : '扫描失败');
              } finally {
                setSweepBusy(false);
              }
            }}
            className="h-9 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-3 text-xs text-indigo-100 disabled:opacity-50"
          >
            {sweepBusy ? '扫描中…' : '运行 MA 网格扫描'}
          </button>
        </div>
        {sweepError && <p className="mt-2 text-[11px] text-red-300">{sweepError}</p>}
        {sweepResult && (
          <div className="mt-3 overflow-hidden rounded-lg border border-white/5 bg-black/30">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 px-3 py-2 text-[11px]">
              <div className="flex items-center gap-2">
                <span
                  className={
                    sweepResult.status === 'ok'
                      ? 'text-emerald-300'
                      : sweepResult.status === 'empty'
                        ? 'text-neutral-400'
                        : 'text-amber-300'
                  }
                >
                  {sweepResult.status === 'ok'
                    ? '扫描完成'
                    : sweepResult.status === 'empty'
                      ? '无有效组合'
                      : '结果降级'}
                </span>
                <span className="text-neutral-500">
                  {sweepResult.returned} 条结果 · {sweepResult.n_trials} 次有效尝试
                </span>
              </div>
              <span className="font-mono text-neutral-500">排序 {sweepResult.metric}</span>
            </div>
            {sweepResult.results.length > 0 ? (
              <div className="max-h-72 overflow-auto">
                <table className="w-full min-w-[46rem] border-collapse text-left text-[11px]">
                  <thead className="sticky top-0 bg-neutral-950 text-neutral-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">#</th>
                      <th className="px-3 py-2 font-medium">Fast / Slow</th>
                      <th className="px-3 py-2 font-medium">收益</th>
                      <th className="px-3 py-2 font-medium">Sharpe</th>
                      <th className="px-3 py-2 font-medium">PSR</th>
                      <th className="px-3 py-2 font-medium">DSR</th>
                      <th className="px-3 py-2 font-medium">最大回撤</th>
                      <th className="px-3 py-2 font-medium">样本</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-neutral-300">
                    {sweepResult.results.map((row, index) => (
                      <tr key={`${row.params.fast ?? 'f'}-${row.params.slow ?? 's'}-${index}`}>
                        <td className="px-3 py-2 font-mono text-neutral-500">{index + 1}</td>
                        <td className="px-3 py-2 font-mono">{row.params.fast ?? '--'} / {row.params.slow ?? '--'}</td>
                        <td className="px-3 py-2 font-mono">{formatPercentMetric(row.metrics.total_return)}</td>
                        <td className="px-3 py-2 font-mono">{formatMetric(row.metrics.sharpe, 3)}</td>
                        <td className="px-3 py-2 font-mono text-sky-200">
                          {row.selection_bias_status === 'ok'
                            ? formatProbability(row.probabilistic_sharpe)
                            : selectionBiasLabel(row.selection_bias_status)}
                        </td>
                        <td className="px-3 py-2 font-mono text-indigo-200">
                          {row.selection_bias_status === 'ok'
                            ? formatProbability(row.deflated_sharpe)
                            : selectionBiasLabel(row.selection_bias_status)}
                        </td>
                        <td className="px-3 py-2 font-mono">{formatPercentMetric(row.metrics.max_drawdown)}</td>
                        <td className="px-3 py-2 font-mono text-neutral-500">{row.observations || '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="px-3 py-6 text-center text-xs text-neutral-500">当前网格没有可展示的有效回测结果。</p>
            )}
            {sweepResult.disclaimer && (
              <p className="border-t border-white/5 px-3 py-2 text-[10px] leading-relaxed text-neutral-500">
                {sweepResult.disclaimer}
              </p>
            )}
          </div>
        )}
      </div>

      {/* 免责 */}
      <p className="mt-2 text-[10px] leading-relaxed text-neutral-600">
        集成中心仅展示外部项目接入状态与交易边界。所有 adapter 全程研究语义, 不连接真实券商、不自动下单;
        输出须经证据 + 风控 + 人工确认, 不构成投资建议。
      </p>
    </motion.div>
  );
};
