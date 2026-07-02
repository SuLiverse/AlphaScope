import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Download, Loader2, RefreshCcw, ShieldAlert, Swords, Users } from 'lucide-react';
import { fetchApi } from '../lib/api';
import { downloadText } from '../lib/download';
import { getPersistedStock, subscribeStockSelected } from '../lib/workspaceEvents';
import type { StockTarget } from '../lib/stocks';

/**
 * 龙虎榜 / 游资席位面板(纯新增模块)。
 *
 * 随当前选中标的调用 GET /api/dragon-tiger/{symbol}(后端 M1:akshare 龙虎榜 + 游资席位库),
 * 展示机构 vs 游资净额博弈、上榜知名游资、近 30 日上榜明细。仅 A 股。不改动任何现有功能。
 */

interface InstVsYouzi {
  institutional_buy?: number;
  institutional_sell?: number;
  institutional_net?: number;
  youzi_buy?: number;
  youzi_sell?: number;
  youzi_net?: number;
}

interface DragonTigerData {
  code?: string;
  lhb_count_30d?: number;
  lhb_records?: Array<Record<string, any>>;
  matched_youzi?: string[];
  matched_youzi_detail?: Record<string, { tier?: string; style?: string; premium?: string; hits?: any[] }>;
  inst_vs_youzi?: InstVsYouzi;
  sector_lhb_top?: Array<Record<string, any>>;
  source?: string;
}

const TIER_LABEL: Record<string, string> = {
  legend: '殿堂级',
  new_gen: '新生代',
  regional: '区域帮派',
  new_2025: '2025 新晋',
};

const fmtMoney = (n?: number) => {
  if (n === undefined || n === null) return '—';
  const v = Number(n);
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)} 亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)} 万`;
  return `${v.toFixed(0)}`;
};

export function DragonTiger() {
  const [stock, setStock] = useState<StockTarget | null>(() => getPersistedStock() ?? null);
  const [data, setData] = useState<DragonTigerData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [trap, setTrap] = useState<{
    trap_level?: string;
    trap_score?: number | null;
    signals_hit?: string;
    signals_hit_count?: number;
    recommendation?: string;
    signals_hit_detail?: Array<{ name: string }>;
  } | null>(null);
  const [trapLoading, setTrapLoading] = useState(false);

  useEffect(() => subscribeStockSelected(({ stock: s }) => setStock(s)), []);

  const load = (symbol: string) => {
    setLoading(true);
    setError('');
    void fetchApi<DragonTigerData>(`/api/dragon-tiger/${encodeURIComponent(symbol)}`)
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
    void fetchApi<DragonTigerData>(`/api/dragon-tiger/${encodeURIComponent(stock.symbol)}`)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅按 symbol 变化重新加载
  }, [stock?.symbol]);

  const iv = data?.inst_vs_youzi;
  // 龙虎榜为 A 股特有;仅当明确是港股时判为不适用,market 未知则按 A 股尝试(后端会返回空)
  const isNonA = stock && stock.market === '港股';
  const noRecords = data && (data.lhb_count_30d ?? 0) === 0;

  const exportMd = () => {
    if (!data) return;
    const lines: string[] = [
      `# 龙虎榜/游资报告 · ${stock?.name ?? ''} (${stock?.symbol ?? ''})`,
      '',
      `- 近30日上榜: ${data.lhb_count_30d ?? 0} 次`,
      `- 机构净额: ${fmtMoney(iv?.institutional_net)}(买 ${fmtMoney(iv?.institutional_buy)} / 卖 ${fmtMoney(iv?.institutional_sell)})`,
      `- 游资净额: ${fmtMoney(iv?.youzi_net)}(买 ${fmtMoney(iv?.youzi_buy)} / 卖 ${fmtMoney(iv?.youzi_sell)})`,
      '',
    ];
    const youzi = Object.entries(data.matched_youzi_detail ?? {});
    if (youzi.length) {
      lines.push(
        '## 上榜知名游资',
        ...youzi.map(([nick, info]) => `- ${nick}${info.tier ? `(${TIER_LABEL[info.tier] ?? info.tier})` : ''}${info.style ? ` · ${info.style}` : ''}`),
        '',
      );
    }
    lines.push('> 游资席位来自公开龙虎榜匹配,仅供研究参考,不构成投资建议。');
    downloadText(`alphascope-dragontiger-${stock?.symbol ?? 'report'}.md`, lines.join('\n'));
  };

  const scanTrap = () => {
    if (!stock) return;
    setTrapLoading(true);
    setTrap(null);
    void fetchApi<{
      trap_level?: string;
      trap_score?: number | null;
      signals_hit?: string;
      signals_hit_count?: number;
      recommendation?: string;
      signals_hit_detail?: Array<{ name: string }>;
    }>(
      `/api/dragon-tiger/${encodeURIComponent(stock.symbol)}/trap?name=${encodeURIComponent(stock.name ?? stock.symbol)}`,
    )
      .then((d) => setTrap(d))
      .catch(() => setTrap({ trap_level: '⚪ 扫描失败', recommendation: '杀猪盘扫描失败(可能未配置网络搜索)。' }))
      .finally(() => setTrapLoading(false));
  };

  return (
    <motion.div
      key="dragon_tiger"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-auto max-w-5xl px-4 sm:px-6 py-6"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-500/15 text-rose-300 shadow-lg shadow-rose-500/20 ring-1 ring-rose-500/20">
            <Swords className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-neutral-100">龙虎榜 · 机构 vs 游资</h1>
            <p className="text-[12px] text-neutral-500">
              {stock ? `${stock.name} (${stock.symbol})` : '在顶部搜索框选择一只 A 股'}
            </p>
          </div>
        </div>
        {stock && (
          <div className="flex items-center gap-2">
            {data && !isNonA && !noRecords && (
              <button
                type="button"
                onClick={exportMd}
                className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-[12px] text-neutral-300 transition-colors hover:bg-white/[0.06]"
              >
                <Download className="h-3.5 w-3.5" /> 导出 .md
              </button>
            )}
            {!isNonA && (
              <button
                type="button"
                onClick={scanTrap}
                disabled={trapLoading}
                className="flex items-center gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-[12px] text-amber-300 transition-colors hover:bg-amber-500/15 disabled:opacity-50"
              >
                {trapLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldAlert className="h-3.5 w-3.5" />}
                杀猪盘检测
              </button>
            )}
            <button
              type="button"
              onClick={() => load(stock.symbol)}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-1.5 text-[12px] text-neutral-300 transition-colors hover:bg-white/[0.06] disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
              刷新
            </button>
          </div>
        )}
      </div>

      {trap && (
        <div className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-amber-200">杀猪盘检测:{trap.trap_level}</span>
            <span className="text-[12px] text-neutral-400">命中 {trap.signals_hit ?? `${trap.signals_hit_count ?? 0}/8`}</span>
          </div>
          <p className="mt-1 text-[12px] text-neutral-400">{trap.recommendation}</p>
          {trap.signals_hit_detail && trap.signals_hit_detail.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {trap.signals_hit_detail.map((sgl, i) => (
                <span key={i} className="rounded border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                  {sgl.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {!stock && (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-10 text-center text-sm text-neutral-500">
          <Swords className="mx-auto mb-3 h-8 w-8 text-neutral-600" />
          选择一只 A 股,查看其龙虎榜席位、知名游资动向与机构/游资资金博弈。
        </div>
      )}

      {stock && loading && !data && (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-rose-300">
          <Loader2 className="h-5 w-5 animate-spin" /> 正在拉取 {stock.name} 龙虎榜…
        </div>
      )}

      {stock && error && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          请求失败:{error.slice(0, 200)}
        </div>
      )}

      {data && !loading && (
        <div className="space-y-4">
          {isNonA ? (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-8 text-center text-sm text-neutral-500">
              龙虎榜为 A 股特有数据,当前标的({stock?.market})暂不适用。
            </div>
          ) : noRecords ? (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-8 text-center text-sm text-neutral-500">
              近 30 日无龙虎榜上榜记录。
            </div>
          ) : (
            <>
              {/* 机构 vs 游资 净额 */}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
                  <div className="text-[11px] uppercase tracking-widest text-neutral-500">机构净额</div>
                  <div className={`mt-1 font-mono text-xl ${(iv?.institutional_net ?? 0) >= 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
                    {fmtMoney(iv?.institutional_net)}
                  </div>
                  <div className="mt-1 text-[11px] text-neutral-500">买 {fmtMoney(iv?.institutional_buy)} · 卖 {fmtMoney(iv?.institutional_sell)}</div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
                  <div className="text-[11px] uppercase tracking-widest text-neutral-500">游资净额</div>
                  <div className={`mt-1 font-mono text-xl ${(iv?.youzi_net ?? 0) >= 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
                    {fmtMoney(iv?.youzi_net)}
                  </div>
                  <div className="mt-1 text-[11px] text-neutral-500">买 {fmtMoney(iv?.youzi_buy)} · 卖 {fmtMoney(iv?.youzi_sell)}</div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-white/[0.01] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-500/30 hover:shadow-lg hover:shadow-indigo-500/10">
                  <div className="text-[11px] uppercase tracking-widest text-neutral-500">近30日上榜</div>
                  <div className="mt-1 font-mono text-xl text-neutral-100">{data.lhb_count_30d} 次</div>
                  <div className="mt-1 text-[11px] text-neutral-500">{data.matched_youzi?.length ?? 0} 个知名游资在场</div>
                </div>
              </div>

              {/* 上榜知名游资 */}
              {data.matched_youzi_detail && Object.keys(data.matched_youzi_detail).length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <h3 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-neutral-200">
                    <Users className="h-4 w-4 text-rose-300" /> 上榜知名游资
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(data.matched_youzi_detail).map(([nick, info]) => (
                      <div key={nick} className="rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-rose-200">{nick}</span>
                          {info.tier && (
                            <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9px] text-neutral-400">
                              {TIER_LABEL[info.tier] ?? info.tier}
                            </span>
                          )}
                        </div>
                        {info.style && <div className="mt-0.5 text-[11px] text-neutral-500">{info.style}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 上榜明细 */}
              {data.lhb_records && data.lhb_records.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <h3 className="mb-2 text-sm font-medium text-neutral-200">上榜席位明细(近 30 日)</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[11px]">
                      <thead>
                        <tr className="text-left text-neutral-600">
                          <th className="py-1 pr-3 font-normal">营业部</th>
                          <th className="py-1 pr-3 text-right font-normal">买入</th>
                          <th className="py-1 pr-3 text-right font-normal">卖出</th>
                          <th className="py-1 text-right font-normal">上榜日</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.lhb_records.slice(0, 20).map((r, i) => (
                          <tr key={i} className="border-t border-white/[0.04]">
                            <td className="max-w-[280px] truncate py-1 pr-3 text-neutral-300">
                              {r['营业部名称'] ?? r['交易营业部名称'] ?? '—'}
                            </td>
                            <td className="py-1 pr-3 text-right font-mono text-rose-300/90">{fmtMoney(Number(r['买入金额'] ?? r['买入额'] ?? 0))}</td>
                            <td className="py-1 pr-3 text-right font-mono text-emerald-300/90">{fmtMoney(Number(r['卖出金额'] ?? r['卖出额'] ?? 0))}</td>
                            <td className="py-1 text-right font-mono text-neutral-500">{r['上榜日'] ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {data.sector_lhb_top && data.sector_lhb_top.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                  <h3 className="mb-2 text-sm font-medium text-neutral-200">近月活跃龙虎榜个股(板块参考)</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {data.sector_lhb_top.slice(0, 12).map((r, i) => {
                      const nm = r['名称'] ?? r['股票简称'] ?? '';
                      const code = r['代码'] ?? r['股票代码'] ?? '';
                      const cnt = r['上榜次数'] ?? r['次数'];
                      return (
                        <span key={i} className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-neutral-300">
                          {nm}
                          {code ? ` ${code}` : ''}
                          {cnt != null ? ` · ${cnt}次` : ''}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              <p className="text-[10px] leading-relaxed text-neutral-600">
                游资席位来自公开龙虎榜匹配,可能存在席位变更/重名;机构识别基于"机构专用"标识。仅供研究参考,不构成投资建议。
              </p>
            </>
          )}
        </div>
      )}
    </motion.div>
  );
}
