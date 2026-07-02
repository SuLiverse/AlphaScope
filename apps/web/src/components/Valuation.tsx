import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Calculator, Download, Loader2, RefreshCcw, TrendingUp } from 'lucide-react';
import { fetchApi } from '../lib/api';
import { downloadText } from '../lib/download';
import { getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import type { StockTarget } from '../lib/stocks';

/**
 * 估值建模面板(纯新增模块)。
 *
 * 随当前选中标的调用 GET /api/valuation/{symbol}(后端 backend/valuation 的 DCF/Comps/LBO),
 * 展示三法摘要 + DCF 明细 + 敏感性表 + Comps/LBO 关键结论。不改动任何现有功能。
 */

interface CostlessNumber {
  [k: string]: any;
}

interface ValuationData {
  symbol: string;
  degraded?: boolean;
  features?: CostlessNumber;
  summary?: {
    dcf_intrinsic_per_share?: number;
    dcf_safety_margin_pct?: number;
    dcf_verdict?: string;
    lbo_irr_pct?: number;
    lbo_verdict?: string;
    comps_verdict?: string;
  };
  dcf?: {
    intrinsic_per_share?: number;
    current_price?: number;
    safety_margin_pct?: number;
    verdict?: string;
    enterprise_value_yi?: number;
    equity_value_yi?: number;
    tv_pct_of_ev?: number;
    wacc_breakdown?: { wacc?: number; cost_of_equity?: number; after_tax_kd?: number };
    methodology_log?: string[];
    sensitivity_table?: { wacc_axis?: string[]; g_axis?: string[]; values_per_share?: number[][]; center_cell?: number };
  };
  lbo?: {
    entry_ev_yi?: number;
    exit_ev_yi?: number;
    moic?: number;
    irr_pct?: number;
    leverage_turns?: number;
    verdict?: string;
  };
  comps?: {
    valuation_verdict?: string;
    note?: string;
    peer_stats?: Record<string, { median?: number; mean?: number; n?: number }>;
    target_percentile?: Record<string, number>;
    implied_price?: { via_median_pe?: number; via_median_pb?: number };
    peers?: any[];
  };
}

const pct = (n?: number) => (n === undefined || n === null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`);
const yi = (n?: number) => (n === undefined || n === null ? '—' : `${n.toFixed(1)} 亿`);

export function Valuation() {
  const [stock, setStock] = useState<StockTarget | null>(() => getPersistedStock() ?? null);
  const [data, setData] = useState<ValuationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [g1, setG1] = useState('');
  const [tg, setTg] = useState('');
  const [betaIn, setBetaIn] = useState('');

  useEffect(() => {
    return subscribeStockSelected(({ stock: s }) => setStock(s));
  }, []);

  const buildValuationUrl = (symbol: string) => {
    const params = new URLSearchParams();
    const g = parseFloat(g1);
    if (!Number.isNaN(g)) params.set('stage1_growth', String(g / 100));
    const t = parseFloat(tg);
    if (!Number.isNaN(t)) params.set('terminal_g', String(t / 100));
    const b = parseFloat(betaIn);
    if (!Number.isNaN(b)) params.set('beta', String(b));
    const qs = params.toString();
    return `/api/valuation/${encodeURIComponent(symbol)}${qs ? `?${qs}` : ''}`;
  };

  const load = (symbol: string) => {
    setLoading(true);
    setError('');
    void fetchApi<ValuationData>(buildValuationUrl(symbol))
      .then((d) => setData(d))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!stock?.symbol) return;
    // cancelled 守卫: 快速切标的时旧请求晚返回不覆盖新数据(竞态)
    let cancelled = false;
    setLoading(true);
    setError('');
    void fetchApi<ValuationData>(buildValuationUrl(stock.symbol))
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅按 symbol 变化重新估值
  }, [stock?.symbol]);

  const s = data?.summary;
  const dcf = data?.dcf;
  const lbo = data?.lbo;
  const comps = data?.comps;

  const exportMd = () => {
    if (!data) return;
    const lines: string[] = [
      `# 估值报告 · ${stock?.name ?? ''} (${stock?.symbol ?? ''})`,
      '',
      '## 三法摘要',
      `- DCF 内在价值: ¥${s?.dcf_intrinsic_per_share ?? '—'}(安全边际 ${pct(s?.dcf_safety_margin_pct)})${s?.dcf_verdict ?? ''}`,
      `- LBO: ${lbo?.irr_pct ?? '—'}% IRR · MOIC ${lbo?.moic ?? '—'}x · ${s?.lbo_verdict ?? lbo?.verdict ?? ''}`,
      `- 同业对比: ${s?.comps_verdict ?? '—'}`,
      '',
    ];
    if (dcf?.methodology_log?.length) {
      lines.push('## DCF 推导', ...dcf.methodology_log.map((x, i) => `${i + 1}. ${x}`), '');
    }
    lines.push('> 估值为模型估算,基于公开数据与默认假设,不构成投资建议。');
    downloadText(`alphascope-valuation-${stock?.symbol ?? 'report'}.md`, lines.join('\n'));
  };

  return (
    <motion.div
      key="valuation"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-5xl px-4 sm:px-6 py-6"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-300 shadow-lg shadow-indigo-500/20 ring-1 ring-indigo-500/20">
            <Calculator className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">估值建模 · DCF / Comps / LBO</h1>
            <p className="text-[12px] text-neutral-500">
              {stock ? `${stock.name} (${stock.symbol})` : '在顶部搜索框选择一只股票'}
            </p>
          </div>
        </div>
        {stock && (
          <div className="flex items-center gap-2">
            {data && (
              <button
                type="button"
                onClick={exportMd}
                className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-[12px] text-neutral-300 transition-colors hover:bg-white/[0.06]"
              >
                <Download className="h-3.5 w-3.5" /> 导出 .md
              </button>
            )}
            <button
              type="button"
              onClick={() => load(stock.symbol)}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-[12px] text-neutral-300 transition-colors hover:bg-white/[0.06] disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
              重新估算
            </button>
          </div>
        )}
      </div>

      {stock && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
          <span className="text-[11px] text-neutral-500">情景假设(留空=默认):</span>
          <label className="text-[11px] text-neutral-500">
            一阶段增速%
            <input
              value={g1}
              onChange={(e) => setG1(e.target.value)}
              placeholder="10"
              inputMode="decimal"
              className="ml-1 w-16 rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 font-mono text-neutral-200 focus:border-indigo-500/50 focus:outline-none"
            />
          </label>
          <label className="text-[11px] text-neutral-500">
            永续增速%
            <input
              value={tg}
              onChange={(e) => setTg(e.target.value)}
              placeholder="2.5"
              inputMode="decimal"
              className="ml-1 w-16 rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 font-mono text-neutral-200 focus:border-indigo-500/50 focus:outline-none"
            />
          </label>
          <label className="text-[11px] text-neutral-500">
            Beta
            <input
              value={betaIn}
              onChange={(e) => setBetaIn(e.target.value)}
              placeholder="1.0"
              inputMode="decimal"
              className="ml-1 w-16 rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 font-mono text-neutral-200 focus:border-indigo-500/50 focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => load(stock.symbol)}
            disabled={loading}
            className="rounded-lg bg-indigo-500/80 px-3 py-1 text-[12px] text-white transition-colors hover:bg-indigo-500 disabled:opacity-50"
          >
            应用
          </button>
        </div>
      )}

      {!stock && (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-10 text-center text-sm text-neutral-500">
          <TrendingUp className="mx-auto mb-3 h-8 w-8 text-neutral-600" />
          选择标的后,将基于其财务数据运行 DCF / 同业对比 / LBO 三种机构级估值。
        </div>
      )}

      {stock && loading && !data && (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-indigo-300">
          <Loader2 className="h-5 w-5 animate-spin" /> 正在估算 {stock.name}…
        </div>
      )}

      {stock && error && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          估值请求失败:{error.slice(0, 200)}
        </div>
      )}

      {data && (
        <div className="space-y-4">
          {data.degraded && (
            <div className="rounded-lg border border-amber-500/15 bg-amber-500/[0.07] px-3 py-2 text-[11px] text-amber-300/90">
              基础财务数据不足,以下为基于可得数据与默认假设的估算,仅供参考。
            </div>
          )}

          {/* 三法摘要 */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
              <div className="text-[11px] uppercase tracking-widest text-neutral-500">DCF 内在价值</div>
              <div className="mt-1 font-mono text-2xl text-neutral-100">
                ¥{s?.dcf_intrinsic_per_share?.toFixed(2) ?? '—'}
              </div>
              <div className="mt-1 text-[12px] text-neutral-400">安全边际 {pct(s?.dcf_safety_margin_pct)}</div>
              <div className="mt-1 text-[12px] text-indigo-300">{s?.dcf_verdict ?? '—'}</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
              <div className="text-[11px] uppercase tracking-widest text-neutral-500">LBO 交叉验证</div>
              <div className="mt-1 font-mono text-2xl text-neutral-100">{lbo?.irr_pct?.toFixed(1) ?? '—'}% IRR</div>
              <div className="mt-1 text-[12px] text-neutral-400">MOIC {lbo?.moic?.toFixed(2) ?? '—'}x · {lbo?.leverage_turns ?? '—'}x 杠杆</div>
              <div className="mt-1 text-[12px] text-indigo-300">{s?.lbo_verdict ?? lbo?.verdict ?? '—'}</div>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
              <div className="text-[11px] uppercase tracking-widest text-neutral-500">同业对比</div>
              <div className="mt-1 text-sm text-neutral-200">{s?.comps_verdict ?? comps?.note ?? '—'}</div>
              {comps?.peer_stats?.pe?.median !== undefined && (
                <div className="mt-1 text-[12px] text-neutral-400">
                  同业 PE 中位 {comps.peer_stats.pe.median} · 分位 {comps?.target_percentile?.pe ?? '—'}%
                </div>
              )}
            </div>
          </div>

          {/* DCF 明细 */}
          {dcf && (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <h3 className="mb-3 text-sm font-medium text-neutral-200">DCF 推导</h3>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12px] sm:grid-cols-3">
                <Metric label="WACC" value={dcf.wacc_breakdown?.wacc !== undefined ? `${(dcf.wacc_breakdown.wacc * 100).toFixed(2)}%` : '—'} />
                <Metric label="股权成本" value={dcf.wacc_breakdown?.cost_of_equity !== undefined ? `${(dcf.wacc_breakdown.cost_of_equity * 100).toFixed(2)}%` : '—'} />
                <Metric label="企业价值 EV" value={yi(dcf.enterprise_value_yi)} />
                <Metric label="股权价值" value={yi(dcf.equity_value_yi)} />
                <Metric label="终值占比" value={dcf.tv_pct_of_ev !== undefined ? `${dcf.tv_pct_of_ev}%` : '—'} />
                <Metric label="当前价" value={dcf.current_price !== undefined ? `¥${dcf.current_price}` : '—'} />
              </div>
              {dcf.methodology_log && dcf.methodology_log.length > 0 && (
                <ol className="mt-3 space-y-1 border-t border-white/5 pt-3 text-[11px] text-neutral-400">
                  {dcf.methodology_log.map((step, i) => (
                    <li key={i} className="leading-relaxed">{step}</li>
                  ))}
                </ol>
              )}
              {/* 敏感性表 */}
              {dcf.sensitivity_table?.values_per_share && (
                <div className="mt-3 overflow-x-auto border-t border-white/5 pt-3">
                  <div className="mb-1 text-[11px] text-neutral-500">敏感性:每股内在价值(行 WACC × 列 永续增长 g)</div>
                  <table className="text-[11px]">
                    <thead>
                      <tr>
                        <th className="px-2 py-1 text-neutral-600">WACC＼g</th>
                        {dcf.sensitivity_table.g_axis?.map((g) => (
                          <th key={g} className="px-2 py-1 font-mono text-neutral-500">{g}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dcf.sensitivity_table.values_per_share.map((row, ri) => (
                        <tr key={ri}>
                          <td className="px-2 py-1 font-mono text-neutral-500">{dcf.sensitivity_table?.wacc_axis?.[ri]}</td>
                          {row.map((v, ci) => (
                            <td
                              key={ci}
                              className={`px-2 py-1 text-center font-mono ${ri === 2 && ci === 2 ? 'rounded bg-indigo-500/20 text-indigo-200' : 'text-neutral-300'}`}
                            >
                              {v}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <p className="text-[10px] leading-relaxed text-neutral-600">
            估值为模型估算,基于公开财务数据与默认假设(A股:无风险利率≈2.5%、ERP≈6%、税率25%),不构成投资建议。
          </p>
        </div>
      )}
    </motion.div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-neutral-500">{label}</span>
      <span className="font-mono text-neutral-200">{value}</span>
    </div>
  );
}
