import { useEffect, useMemo, useState } from 'react';
import type { ComponentType } from 'react';
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Briefcase, Landmark, Plus, RefreshCw, Search, ShieldCheck, Trash2, WalletCards } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '../lib/utils';
import { fetchApi } from '../lib/api';
import { findStockTarget, resolveStockTarget, STOCK_UNIVERSE, StockTarget } from '../lib/stocks';
import { getPersistedStock, subscribeWatchlistChanged } from '../lib/workspaceEvents';
import { StableChartContainer } from './StableChartContainer';

const PORTFOLIO_STORAGE_KEY = 'alphascope:research-portfolio-positions';
const SECTOR_LIMIT_PCT = 35;

interface ResearchPosition {
  symbol: string;
  name: string;
  sector: string;
  shares: number;
  cost: number;
  addedAt: string;
}

interface WatchlistItem {
  symbol: string;
  name?: string;
}

interface PriceBar {
  symbol: string;
  date: string;
  close: number;
  change_pct?: number;
  previous_close?: number;
  source?: string;
}

interface PositionRow extends ResearchPosition {
  price: number;
  marketValue: number;
  costValue: number;
  pnl: number;
  pnlPct: number;
  dailyPnl: number;
  weight: number;
  source: string;
  priceDate: string;
  risk: '低' | '中' | '高';
}

const currencyFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 2,
});

const allocationColors = ['#f43f5e', '#6366f1', '#14b8a6', '#64748b', '#f59e0b', '#06b6d4'];

function normalizeSymbol(value: string) {
  const raw = String(value || '').trim().toUpperCase();
  const code = raw.match(/\d{5,6}/)?.[0] || raw;
  if (!code) return '';
  if (raw.includes('.')) return raw;
  if (code.length === 5) return `${code}.HK`;
  if (/^(60|68|90)/.test(code)) return `${code}.SH`;
  if (/^(00|30|20)/.test(code)) return `${code}.SZ`;
  if (/^[48]/.test(code)) return `${code}.BJ`;
  return `${code}.SZ`;
}

function stripSymbolSuffix(symbol: string) {
  return String(symbol || '').trim().split('.')[0];
}

function readStoredPositions(): ResearchPosition[] {
  if (typeof window === 'undefined') return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PORTFOLIO_STORAGE_KEY) || '[]') as ResearchPosition[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item?.symbol && Number(item.shares) > 0 && Number(item.cost) > 0)
      .map((item) => ({
        ...item,
        symbol: normalizeSymbol(item.symbol),
        shares: Number(item.shares),
        cost: Number(item.cost),
        sector: item.sector || findStockTarget(item.symbol)?.sector || '未分类',
        addedAt: item.addedAt || new Date().toISOString(),
      }));
  } catch {
    return [];
  }
}

function writeStoredPositions(positions: ResearchPosition[]) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(PORTFOLIO_STORAGE_KEY, JSON.stringify(positions));
}

function formatCurrency(value: number) {
  return currencyFormatter.format(Number.isFinite(value) ? value : 0);
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${numberFormatter.format(value)}%`;
}

function riskLevel(weight: number, pnlPct: number): PositionRow['risk'] {
  if (weight >= 25 || pnlPct <= -15) return '高';
  if (weight >= 12 || pnlPct <= -8) return '中';
  return '低';
}

function riskTone(risk: PositionRow['risk']) {
  if (risk === '高') return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
  if (risk === '中') return 'border-amber-500/20 bg-amber-500/10 text-amber-300';
  return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
}

async function fetchLatestPrice(symbol: string): Promise<PriceBar | null> {
  const code = encodeURIComponent(stripSymbolSuffix(symbol));
  try {
    return await fetchApi<PriceBar>(`/api/prices/${code}/latest`);
  } catch {
    try {
      const series = await fetchApi<{ bars: PriceBar[] }>(`/api/prices/${code}?limit=1`);
      return series.bars?.[0] || null;
    } catch {
      return null;
    }
  }
}

function SummaryCard({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint: string;
  tone: 'rose' | 'emerald' | 'indigo' | 'neutral';
  icon: ComponentType<{ className?: string }>;
}) {
  const color = {
    rose: 'text-rose-400',
    emerald: 'text-emerald-400',
    indigo: 'text-indigo-300',
    neutral: 'text-neutral-300',
  }[tone];

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-lg">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">{label}</h3>
        <Icon className={cn('h-5 w-5', color)} />
      </div>
      <h2 className="text-3xl font-mono font-medium text-neutral-100">{value}</h2>
      <p className={cn('mt-2 text-[11px] font-mono', color)}>{hint}</p>
    </div>
  );
}

export function Portfolio() {
  const [positions, setPositions] = useState<ResearchPosition[]>(() => readStoredPositions());
  const [quotes, setQuotes] = useState<Record<string, PriceBar | null>>({});
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [loadingPrices, setLoadingPrices] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [formError, setFormError] = useState('');
  const [syncMsg, setSyncMsg] = useState('');
  const [draft, setDraft] = useState({
    symbol: '',
    name: '',
    sector: '',
    shares: '100',
    cost: '',
  });
  const [activeStock] = useState<StockTarget | undefined>(() => {
    try {
      return getPersistedStock();
    } catch {
      return undefined;
    }
  });

  useEffect(() => {
    writeStoredPositions(positions);
  }, [positions]);

  // 后端持久化:启动时从 SQLite 载入并合并(本地为缓存,后端为真实源)
  useEffect(() => {
    let cancelled = false;
    void fetchApi<{ items: ResearchPosition[] }>('/api/portfolio/positions')
      .then((data) => {
        if (cancelled) return;
        const remote = (data?.items || []).filter((p) => p?.symbol && Number(p.shares) > 0);
        if (!remote.length) return;
        setPositions((prev) => {
          const bySymbol = new Map<string, ResearchPosition>();
          // 远端优先(真实源),本地补缺
          for (const p of remote) {
            const ts = Number((p as { added_at?: number }).added_at || 0);
            bySymbol.set(p.symbol, {
              symbol: p.symbol,
              name: p.name || '',
              sector: p.sector || '',
              shares: Number(p.shares),
              cost: Number(p.cost),
              addedAt: ts ? new Date(ts * 1000).toISOString() : p.addedAt || '',
            });
          }
          for (const p of prev) {
            if (!bySymbol.has(p.symbol)) bySymbol.set(p.symbol, p);
          }
          return Array.from(bySymbol.values()).sort(
            (a, b) => (b.addedAt || '').localeCompare(a.addedAt || ''),
          );
        });
      })
      .catch(() => {
        /* 后端不可用时静默,继续用本地缓存 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const [watchlistReloadKey, setWatchlistReloadKey] = useState(0);
  useEffect(() => subscribeWatchlistChanged(() => setWatchlistReloadKey((k) => k + 1)), []);

  // 组合优化(接出 portfolio_optimizer);绩效报告在回测页用真实净值曲线调用
  const [optimizeResult, setOptimizeResult] = useState<Record<string, number> | null>(null);
  const [optimizeMeta, setOptimizeMeta] = useState<{ optimizer: string; method: string; degraded: boolean } | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [optError, setOptError] = useState('');

  const runOptimize = async (method: string) => {
    const symbols = rows.map((r) => stripSymbolSuffix(r.symbol));
    if (symbols.length < 2) {
      setOptError('组合优化需要至少 2 个持仓');
      return;
    }
    setOptimizing(true);
    setOptError('');
    try {
      const res = await fetchApi<{
        weights: Record<string, number>;
        optimizer: string;
        method: string;
        degraded: boolean;
        error?: string;
      }>('/api/portfolio/optimize', {
        method: 'POST',
        body: JSON.stringify({ symbols, method, days: 120 }),
      });
      setOptimizeResult(res?.weights || null);
      setOptimizeMeta({ optimizer: res?.optimizer || '', method: res?.method || method, degraded: !!res?.degraded });
      if (res?.error) setOptError(res.error);
    } catch (e) {
      setOptError(e instanceof Error ? e.message : '组合优化失败');
    } finally {
      setOptimizing(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    async function loadWatchlist() {
      try {
        const result = await fetchApi<{ items: WatchlistItem[] }>('/api/watchlist');
        if (!cancelled) setWatchlist(result.items || []);
      } catch {
        if (!cancelled) setWatchlist([]);
      }
    }
    void loadWatchlist();
    return () => {
      cancelled = true;
    };
  }, [watchlistReloadKey]);

  useEffect(() => {
    if (draft.symbol || !activeStock) return;
    setDraft((prev) => ({
      ...prev,
      symbol: activeStock.symbol,
      name: activeStock.name,
      sector: activeStock.sector,
    }));
  }, [activeStock, draft.symbol]);

  useEffect(() => {
    let cancelled = false;
    async function loadPrices() {
      if (!positions.length) {
        setQuotes({});
        return;
      }
      setLoadingPrices(true);
      const entries = await Promise.all(
        positions.map(async (position) => [position.symbol, await fetchLatestPrice(position.symbol)] as const),
      );
      if (!cancelled) {
        setQuotes(Object.fromEntries(entries));
        setLoadingPrices(false);
      }
    }
    void loadPrices();
    return () => {
      cancelled = true;
    };
  }, [positions, refreshKey]);

  const rows = useMemo<PositionRow[]>(() => {
    const baseRows = positions.map((position) => {
      const quote = quotes[position.symbol];
      const price = Number(quote?.close || position.cost || 0);
      const marketValue = position.shares * price;
      const costValue = position.shares * position.cost;
      const pnl = marketValue - costValue;
      const pnlPct = costValue > 0 ? (pnl / costValue) * 100 : 0;
      const previousClose = Number(quote?.previous_close || 0);
      const dayChangePct = Number(quote?.change_pct || 0);
      const prevPrice = previousClose > 0 ? previousClose : price / (1 + dayChangePct / 100);
      const dailyPnl = Number.isFinite(prevPrice) && prevPrice > 0 ? (price - prevPrice) * position.shares : 0;
      return {
        ...position,
        price,
        marketValue,
        costValue,
        pnl,
        pnlPct,
        dailyPnl,
        weight: 0,
        source: quote?.source || '待同步',
        priceDate: quote?.date || '',
        risk: '低' as PositionRow['risk'],
      };
    });
    const total = baseRows.reduce((sum, row) => sum + row.marketValue, 0);
    return baseRows.map((row) => {
      const weight = total > 0 ? (row.marketValue / total) * 100 : 0;
      return {
        ...row,
        weight,
        risk: riskLevel(weight, row.pnlPct),
      };
    });
  }, [positions, quotes]);

  const totals = useMemo(() => {
    const totalAssets = rows.reduce((sum, row) => sum + row.marketValue, 0);
    const totalCost = rows.reduce((sum, row) => sum + row.costValue, 0);
    const dailyPnl = rows.reduce((sum, row) => sum + row.dailyPnl, 0);
    const totalPnl = totalAssets - totalCost;
    const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
    const winners = rows.filter((row) => row.pnl >= 0).length;
    const maxRiskUse = rows.reduce((max, row) => Math.max(max, row.weight), 0);
    return { totalAssets, totalCost, dailyPnl, totalPnl, totalPnlPct, winners, maxRiskUse };
  }, [rows]);

  const allocationData = useMemo(() => {
    const grouped = new Map<string, number>();
    rows.forEach((row) => grouped.set(row.sector || '未分类', (grouped.get(row.sector || '未分类') || 0) + row.marketValue));
    return Array.from(grouped.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([name, value], index) => ({ name, value, color: allocationColors[index % allocationColors.length] }));
  }, [rows]);

  const riskBuckets = useMemo(() => (
    allocationData.map((item) => ({
      bucket: item.name,
      exposure: totals.totalAssets > 0 ? Number(((item.value / totals.totalAssets) * 100).toFixed(2)) : 0,
      limit: SECTOR_LIMIT_PCT,
    }))
  ), [allocationData, totals.totalAssets]);

  const riskNotes = useMemo(() => {
    const notes: string[] = [];
    const overLimit = riskBuckets.filter((item) => item.exposure > item.limit);
    if (overLimit.length) notes.push(`${overLimit[0].bucket} 暴露 ${overLimit[0].exposure}% 超过 ${SECTOR_LIMIT_PCT}%`);
    const stale = rows.filter((row) => !row.priceDate || row.source === '待同步');
    if (stale.length) notes.push(`${stale.length} 只持仓价格未同步`);
    const highRisk = rows.filter((row) => row.risk === '高');
    if (highRisk.length) notes.push(`${highRisk.length} 只持仓触发高风险阈值`);
    if (!notes.length) notes.push(rows.length ? '当前研究组合未触发行业上限和单仓高风险阈值' : '暂无持仓');
    return notes;
  }, [riskBuckets, rows]);

  const prefillStock = async (stock: StockTarget | WatchlistItem) => {
    const symbol = normalizeSymbol(stock.symbol);
    const local = findStockTarget(symbol);
    const quote = await fetchLatestPrice(symbol);
    setDraft({
      symbol,
      name: stock.name || local?.name || '',
      sector: local?.sector || '',
      shares: draft.shares || '100',
      cost: quote?.close ? String(quote.close) : draft.cost,
    });
    setFormError('');
  };

  const addPosition = async () => {
    setFormError('');
    const normalizedSymbol = normalizeSymbol(draft.symbol);
    if (!normalizedSymbol) {
      setFormError('请输入股票代码');
      return;
    }
    const shares = Number(draft.shares);
    if (!Number.isFinite(shares) || shares <= 0) {
      setFormError('数量必须大于 0');
      return;
    }
    let resolved: StockTarget | undefined;
    try {
      resolved = await resolveStockTarget(normalizedSymbol);
    } catch {
      resolved = findStockTarget(normalizedSymbol);
    }
    const quote = Number(draft.cost) > 0 ? null : await fetchLatestPrice(normalizedSymbol);
    const cost = Number(draft.cost) > 0 ? Number(draft.cost) : Number(quote?.close || 0);
    if (!Number.isFinite(cost) || cost <= 0) {
      setFormError('成本价为空，且现价同步失败');
      return;
    }
    const next: ResearchPosition = {
      symbol: resolved?.symbol || normalizedSymbol,
      name: draft.name.trim() || resolved?.name || normalizedSymbol,
      sector: draft.sector.trim() || resolved?.sector || findStockTarget(normalizedSymbol)?.sector || '未分类',
      shares,
      cost,
      addedAt: new Date().toISOString(),
    };
    setPositions((prev) => {
      const others = prev.filter((item) => item.symbol !== next.symbol);
      return [next, ...others];
    });
    // 同步到后端持久化(失败静默,本地仍保留)
    void fetchApi('/api/portfolio/positions', {
      method: 'POST',
      body: JSON.stringify({
        symbol: next.symbol,
        name: next.name,
        sector: next.sector,
        shares: next.shares,
        cost: next.cost,
      }),
    }).catch(() => {});
    setDraft((prev) => ({ ...prev, symbol: '', name: '', sector: '', cost: '' }));
  };

  const removePosition = (symbol: string) => {
    if (!window.confirm(`确认从研究组合移除 ${symbol}?`)) {
      return;
    }
    setPositions((prev) => prev.filter((item) => item.symbol !== symbol));
    void fetchApi(`/api/portfolio/positions/${encodeURIComponent(symbol)}`, {
      method: 'DELETE',
    }).catch((e) => {
      // 本地已乐观删除(尊重既有设计), 但后端同步失败时需告知:
      // 否则刷新后会"凭空恢复", 用户不知删除其实没落库。
      setSyncMsg(
        `⚠ ${symbol} 本地已移除, 但后端同步失败(${e instanceof Error ? e.message : '网络错误'}), 刷新后会恢复。请检查后端或重试。`,
      );
    });
  };

  const quickStocks = [
    ...(activeStock ? [activeStock] : []),
    ...watchlist.map((item) => ({ symbol: normalizeSymbol(item.symbol), name: item.name || normalizeSymbol(item.symbol) })),
    ...STOCK_UNIVERSE.slice(0, 6),
  ].filter((item, index, list) => item.symbol && list.findIndex((candidate) => candidate.symbol === item.symbol) === index);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="mx-auto h-full max-w-7xl overflow-y-auto p-6 lg:p-10"
    >
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="flex items-center gap-3 text-2xl font-display font-medium text-neutral-100">
            <Briefcase className="h-6 w-6 text-indigo-500" />
            组合与风控总览
          </h2>
          <p className="mt-2 text-sm font-mono text-neutral-500">研究组合持仓、真实行情估值、行业暴露与风险阈值。</p>
        </div>
        <button
          type="button"
          onClick={() => setRefreshKey((value) => value + 1)}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-neutral-200 transition-colors hover:bg-white/[0.08]"
        >
          <RefreshCw className={cn('h-4 w-4', loadingPrices && 'animate-spin')} />
          刷新价格
        </button>
      </div>

      <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-4">
        <div className="relative overflow-hidden rounded-2xl border border-rose-500/20 bg-gradient-to-br from-rose-950/45 via-indigo-950/20 to-black/30 p-6 shadow-xl md:col-span-2">
          <div className="pointer-events-none absolute right-0 top-0 p-3 text-rose-300 opacity-15">
            <WalletCards className="h-28 w-28 stroke-[0.5]" />
          </div>
          <h3 className="relative z-10 text-[10px] font-mono uppercase tracking-widest text-rose-300">组合市值</h3>
          <h2 className="relative z-10 mt-4 text-4xl font-mono font-medium text-white">{formatCurrency(totals.totalAssets)}</h2>
          <p className={cn('relative z-10 mt-3 flex items-center gap-1 text-xs font-mono', totals.dailyPnl >= 0 ? 'text-rose-300' : 'text-emerald-300')}>
            {totals.dailyPnl >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            今日浮动 {formatCurrency(totals.dailyPnl)} / 累计 {formatPercent(totals.totalPnlPct)}
          </p>
        </div>
        <SummaryCard label="持仓数量" value={String(rows.length)} hint={`${totals.winners} 只盈利 / ${Math.max(0, rows.length - totals.winners)} 只回撤`} tone="emerald" icon={Landmark} />
        <SummaryCard label="最大行业占用" value={`${totals.maxRiskUse.toFixed(0)}%`} hint={`单行业上限 ${SECTOR_LIMIT_PCT}%`} tone={totals.maxRiskUse > SECTOR_LIMIT_PCT ? 'rose' : 'indigo'} icon={ShieldCheck} />
      </div>

      {/* 组合优化器(接出 portfolio_optimizer: skfolio/riskfolio/pypfopt) */}
      <div className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-neutral-100">
              <ShieldCheck className="h-4 w-4 text-indigo-400" />
              组合权重优化(研究草案)
            </h3>
            <p className="mt-1 text-[11px] leading-relaxed text-neutral-500">
              基于近 120 交易日收益,用 skfolio / riskfolio / pypfopt 计算建议权重。
              <span className="text-neutral-600"> 仅作研究参考,不构成投资建议,不自动下单。</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => runOptimize('max_sharpe')}
              disabled={optimizing || rows.length < 2}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-indigo-500/30 bg-indigo-500/15 px-3 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-40"
            >
              {optimizing ? '计算中…' : '最大夏普'}
            </button>
            <button
              type="button"
              onClick={() => runOptimize('min_variance')}
              disabled={optimizing || rows.length < 2}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-xs text-neutral-300 hover:bg-white/[0.08] disabled:opacity-40"
            >
              最小方差
            </button>
            <button
              type="button"
              onClick={() => runOptimize('equal_weight')}
              disabled={optimizing || rows.length < 2}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-xs text-neutral-300 hover:bg-white/[0.08] disabled:opacity-40"
            >
              等权基准
            </button>
          </div>
        </div>
        {optError && <p className="mt-3 text-xs text-rose-400">{optError}</p>}
        {optimizeResult && optimizeMeta && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className="rounded-md bg-white/5 px-2 py-1 font-mono text-neutral-300">
                引擎: {optimizeMeta.optimizer || '—'}
              </span>
              <span className="rounded-md bg-white/5 px-2 py-1 font-mono text-neutral-400">
                方法: {optimizeMeta.method}
              </span>
              {optimizeMeta.degraded && (
                <span className="rounded-md bg-amber-500/10 px-2 py-1 font-mono text-amber-300">
                  降级(数据不足或优化库缺失,已回退等权)
                </span>
              )}
            </div>
            <div className="space-y-1.5">
              {Object.entries(optimizeResult).map(([sym, w]) => (
                <div key={sym} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 font-mono text-[11px] text-neutral-400">{sym}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-sky-400"
                      style={{ width: `${Math.max(2, Math.min(100, Number(w) * 100))}%` }}
                    />
                  </div>
                  <span className="w-14 shrink-0 text-right font-mono text-[11px] text-neutral-300">
                    {(Number(w) * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="mb-6 rounded-2xl border border-white/5 bg-white/[0.04] p-5 shadow-lg">
        <div className="grid gap-3 lg:grid-cols-[1.1fr_1fr_0.7fr_0.7fr_auto]">
          <label className="min-w-0">
            <span className="mb-1 block text-[10px] font-mono uppercase tracking-widest text-neutral-500">代码</span>
            <input
              value={draft.symbol}
              onChange={(event) => setDraft((prev) => ({ ...prev, symbol: event.target.value }))}
              placeholder="600519 或 600519.SH"
              className="h-10 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-indigo-400/50"
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-[10px] font-mono uppercase tracking-widest text-neutral-500">名称</span>
            <input
              value={draft.name}
              onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
              placeholder="自动解析"
              className="h-10 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-indigo-400/50"
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-[10px] font-mono uppercase tracking-widest text-neutral-500">数量</span>
            <input
              value={draft.shares}
              onChange={(event) => setDraft((prev) => ({ ...prev, shares: event.target.value }))}
              inputMode="decimal"
              className="h-10 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-indigo-400/50"
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-[10px] font-mono uppercase tracking-widest text-neutral-500">成本</span>
            <input
              value={draft.cost}
              onChange={(event) => setDraft((prev) => ({ ...prev, cost: event.target.value }))}
              inputMode="decimal"
              placeholder="留空取现价"
              className="h-10 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-indigo-400/50"
            />
          </label>
          <button
            type="button"
            onClick={addPosition}
            className="mt-5 inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-indigo-400/30 bg-indigo-500/15 px-4 text-sm font-medium text-indigo-100 transition-colors hover:bg-indigo-500/25"
          >
            <Plus className="h-4 w-4" />
            加入
          </button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Search className="h-4 w-4 text-neutral-600" />
          {quickStocks.slice(0, 9).map((stock) => (
            <button
              key={stock.symbol}
              type="button"
              onClick={() => prefillStock(stock)}
              className="rounded-full border border-white/10 bg-black/25 px-3 py-1 text-[11px] text-neutral-400 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
            >
              {stock.name || stock.symbol}
            </button>
          ))}
        </div>
        {formError && <div className="mt-3 text-xs text-rose-300">{formError}</div>}
        {syncMsg && (
          <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
            {syncMsg}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-lg">
          <h3 className="mb-6 border-b border-white/5 pb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">资产配置</h3>
          {allocationData.length ? (
            <div className="flex h-72 items-center">
              <StableChartContainer className="h-full w-[52%]">
                <PieChart>
                  <Pie data={allocationData} cx="50%" cy="50%" innerRadius={62} outerRadius={86} paddingAngle={4} dataKey="value" stroke="none" animationDuration={800} animationEasing="ease-out">
                    {allocationData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: '#171717', borderColor: '#262626', borderRadius: '8px', fontSize: '12px' }}
                    itemStyle={{ color: '#e5e5e5' }}
                    formatter={(value) => formatCurrency(Number(value))}
                  />
                </PieChart>
              </StableChartContainer>
              <div className="ml-4 flex-1">
                {allocationData.map((item) => (
                  <div key={item.name} className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="text-neutral-400">{item.name}</span>
                    </div>
                    <span className="font-mono text-xs text-neutral-200">{formatCurrency(item.value)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex h-72 items-center justify-center rounded-xl border border-dashed border-white/10 text-sm text-neutral-500">
              暂无持仓
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-white/5 bg-white/[0.04] p-6 shadow-lg">
          <h3 className="mb-6 border-b border-white/5 pb-3 text-xs font-mono uppercase tracking-widest text-neutral-400">行业风险暴露</h3>
          {riskBuckets.length ? (
            <div className="h-72">
              <StableChartContainer>
                <BarChart data={riskBuckets} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="bucket" stroke="#737373" fontSize={11} />
                  <YAxis stroke="#737373" fontSize={11} />
                  <RechartsTooltip contentStyle={{ backgroundColor: '#171717', borderColor: '#262626', borderRadius: '8px', fontSize: '12px' }} formatter={(value) => `${Number(value)}%`} />
                  <Bar dataKey="limit" name="上限" fill="#334155" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="exposure" name="当前暴露" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </StableChartContainer>
            </div>
          ) : (
            <div className="flex h-72 items-center justify-center rounded-xl border border-dashed border-white/10 text-sm text-neutral-500">
              暂无行业暴露
            </div>
          )}
        </div>

        <div className="overflow-hidden rounded-2xl border border-white/5 bg-white/[0.04] shadow-lg lg:col-span-2">
          <div className="flex items-center justify-between border-b border-white/5 bg-black/40 p-5">
            <h3 className="text-xs font-mono uppercase tracking-widest text-neutral-400">核心持仓</h3>
            <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[11px] text-emerald-200">
              价格来自行情 API
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left text-xs">
              <thead className="border-b border-white/5 bg-black/20 font-mono text-[10px] uppercase tracking-widest text-neutral-500">
                <tr>
                  <th className="px-5 py-3">标的</th>
                  <th className="px-5 py-3">行业</th>
                  <th className="px-5 py-3 text-right">权重</th>
                  <th className="px-5 py-3 text-right">数量</th>
                  <th className="px-5 py-3 text-right">成本</th>
                  <th className="px-5 py-3 text-right">现价</th>
                  <th className="px-5 py-3 text-right">浮盈亏</th>
                  <th className="px-5 py-3 text-right">风险</th>
                  <th className="px-5 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td className="px-5 py-8 text-center text-neutral-500" colSpan={9}>暂无持仓</td>
                  </tr>
                )}
                {rows.map((position) => (
                  <tr key={position.symbol} className="border-b border-white/5 hover:bg-white/[0.025]">
                    <td className="px-5 py-3.5">
                      <p className="font-medium text-neutral-200">{position.name}</p>
                      <p className="mt-1 font-mono text-[10px] text-indigo-300">{position.symbol}</p>
                      <p className="mt-1 font-mono text-[10px] text-neutral-600">{position.source} {position.priceDate}</p>
                    </td>
                    <td className="px-5 py-3.5 text-neutral-400">{position.sector}</td>
                    <td className="px-5 py-3.5 text-right font-mono text-neutral-300">{position.weight.toFixed(2)}%</td>
                    <td className="px-5 py-3.5 text-right font-mono text-neutral-400">{numberFormatter.format(position.shares)}</td>
                    <td className="px-5 py-3.5 text-right font-mono text-neutral-400">¥{numberFormatter.format(position.cost)}</td>
                    <td className="px-5 py-3.5 text-right font-mono text-neutral-200">¥{numberFormatter.format(position.price)}</td>
                    <td className={cn('px-5 py-3.5 text-right font-mono font-medium', position.pnl >= 0 ? 'text-rose-400' : 'text-emerald-400')}>
                      {formatCurrency(position.pnl)}
                      <span className="ml-2 text-[10px] opacity-70">{formatPercent(position.pnlPct)}</span>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <span className={cn('rounded-full border px-2 py-1 text-[10px]', riskTone(position.risk))}>
                        {position.risk}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <button
                        type="button"
                        onClick={() => removePosition(position.symbol)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/25 text-neutral-500 transition-colors hover:border-rose-400/40 hover:text-rose-300"
                        title="移出组合"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4 text-xs leading-relaxed text-amber-100/80 lg:col-span-2">
          <div className="mb-2 flex items-center gap-2 font-medium text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            风险检查
          </div>
          <div className="flex flex-wrap gap-2">
            {riskNotes.map((note) => (
              <span key={note} className="rounded-full border border-amber-400/20 bg-black/20 px-3 py-1 font-mono text-[11px] text-amber-100/80">
                {note}
              </span>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
