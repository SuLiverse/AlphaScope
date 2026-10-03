import React, { useEffect, useMemo, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  AreaChart,
  Area,
  RadialBarChart,
  RadialBar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts';
import { BarChart3 } from 'lucide-react';
import { fetchApi } from '../lib/api';
import type { AnalysisResult } from '../types';

// A 股配色:看多/买入红,看空/卖出绿,观望/中性琥珀,强调靛蓝。
const RED = '#f43f5e';
const GREEN = '#10b981';
const AMBER = '#f59e0b';
const INDIGO = '#818cf8';
const SKY = '#38bdf8';

const SIGNAL_LABEL: Record<string, string> = { BUY: '买入', SELL: '卖出', HOLD: '观望' };
const SIGNAL_COLOR: Record<string, string> = { BUY: RED, SELL: GREEN, HOLD: AMBER };

const FACTOR_LABEL: Record<string, string> = {
  mom_20: '20日动量',
  mom_60: '60日动量',
  vol_20: '20日波动',
  ma20_gap: 'MA20乖离',
  ma60_gap: 'MA60乖离',
  rsi_14: 'RSI',
  max_dd_60: '最大回撤',
  vol_ratio: '量比',
  dist_high_60: '距高点',
  range_pos_60: '区间位置',
};

interface PriceBar { date: string; close: number; volume?: number }
interface FactorVector { factors: Record<string, number | null> }
interface PatternCounts { bullish?: number; bearish?: number; neutral?: number }

const tooltipStyle = {
  contentStyle: { background: '#171717', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 },
  labelStyle: { color: '#a3a3a3' },
} as const;

function ChartCard({ title, subtitle, children, empty }: { title: string; subtitle?: string; children: React.ReactNode; empty?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg border border-white/[0.06] bg-black/20 p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-1">
        <h4 className="text-xs font-medium text-neutral-200">{title}</h4>
        {subtitle && <span className="text-[10px] text-neutral-600">{subtitle}</span>}
      </div>
      <div className="h-44 min-w-0">
        {empty ? (
          <div className="flex h-full items-center justify-center text-[11px] text-neutral-600">暂无数据</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 320, height: 176 }}>
            {children as any}
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

export function ReportCharts({ result, symbol, stockName }: { result: AnalysisResult; symbol: string; stockName?: string }) {
  const [prices, setPrices] = useState<PriceBar[]>([]);
  const [factors, setFactors] = useState<FactorVector | null>(null);
  const [patterns, setPatterns] = useState<PatternCounts | null>(null);
  const frozen = Boolean(result.research_version_id || result.research_snapshot?.cutoff_enforced || result.chart_snapshot);
  const chartSnapshot = result.chart_snapshot;

  // 补充数据(各自失败安全:任一失败仅该图占位,不影响其余)。
  useEffect(() => {
    if (frozen) {
      setPrices(chartSnapshot?.prices || []);
      setFactors(chartSnapshot ? { factors: chartSnapshot.factors } : null);
      setPatterns(null);
      return;
    }
    if (!symbol) return;
    let cancelled = false;
    const clean = symbol.replace(/\.(SH|SZ|HK|SS)$/i, '');

    fetchApi<{ bars: PriceBar[] }>(`/api/prices/${encodeURIComponent(clean)}?frequency=1d&limit=80`)
      .then((d) => !cancelled && setPrices(d.bars || []))
      .catch(() => !cancelled && setPrices([]));

    fetchApi<FactorVector>(`/api/factor-registry/symbol/${encodeURIComponent(clean)}`)
      .then((d) => !cancelled && setFactors(d))
      .catch(() => !cancelled && setFactors(null));

    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 200);
    const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    fetchApi<{ counts: PatternCounts }>('/api/quant/patterns', {
      method: 'POST',
      body: JSON.stringify({ symbol: clean, start_date: fmt(start), end_date: fmt(end), lookback: 60 }),
    })
      .then((d) => !cancelled && setPatterns(d.counts || null))
      .catch(() => !cancelled && setPatterns(null));

    return () => {
      cancelled = true;
    };
  }, [symbol, frozen, chartSnapshot]);

  // 1. Agent 信号分布
  const signalDist = useMemo(() => {
    const counts: Record<string, number> = { BUY: 0, SELL: 0, HOLD: 0 };
    Object.values(result.agents || {}).forEach((a) => {
      const s = (a.signal || 'HOLD').toUpperCase();
      counts[s] = (counts[s] || 0) + 1;
    });
    return Object.entries(counts).filter(([, v]) => v > 0).map(([k, v]) => ({ name: SIGNAL_LABEL[k] || k, value: v, key: k }));
  }, [result.agents]);

  // 2. Agent 置信度
  const confData = useMemo(
    () =>
      Object.entries(result.agents || {}).map(([key, a]) => ({
        name: a.name || key,
        confidence: Math.round((a.confidence || 0) * 100),
        signal: (a.signal || 'HOLD').toUpperCase(),
      })),
    [result.agents],
  );

  const debate = result.debate;

  // 3. 多空力量
  const strengthData = useMemo(
    () =>
      debate
        ? [
            { name: '多头', value: Math.round(debate.bull_strength || 0), fill: RED },
            { name: '空头', value: Math.round(debate.bear_strength || 0), fill: GREEN },
          ]
        : [],
    [debate],
  );

  // 4. 阵营分布
  const stanceData = useMemo(
    () =>
      debate
        ? [
            { name: '看多', value: debate.n_bull || 0, key: 'BUY' },
            { name: '看空', value: debate.n_bear || 0, key: 'SELL' },
            { name: '中性', value: debate.n_neutral || 0, key: 'HOLD' },
          ].filter((d) => d.value > 0)
        : [],
    [debate],
  );

  // 5. 共识度 gauge
  const consensusData = useMemo(
    () => (debate ? [{ name: '共识度', value: Math.round(debate.consensus_score || 0), fill: INDIGO }] : []),
    [debate],
  );

  // 6/7. 价格 + 成交量
  const priceData = useMemo(
    () => prices.map((b) => ({ date: (b.date || '').slice(5), close: b.close, volume: b.volume || 0 })),
    [prices],
  );

  // 8. 技术因子(原始值横向条形)
  const factorData = useMemo(() => {
    if (!factors?.factors) return [];
    return Object.entries(factors.factors)
      .filter(([, v]) => v !== null && v !== undefined && !Number.isNaN(Number(v)))
      .map(([k, v]) => ({ name: FACTOR_LABEL[k] || k, value: Number(v) }));
  }, [factors]);

  // 9. 形态信号
  const patternData = useMemo(
    () =>
      patterns
        ? [
            { name: '看涨', value: patterns.bullish || 0, fill: RED },
            { name: '看跌', value: patterns.bearish || 0, fill: GREEN },
            { name: '中性', value: patterns.neutral || 0, fill: AMBER },
          ]
        : [],
    [patterns],
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[11px] text-neutral-500">
        <BarChart3 className="h-3.5 w-3.5" />
        <span>{stockName || symbol} · {frozen ? '已保存的研究快照' : '多维图表分析'} · 不构成投资建议</span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {/* 1 */}
        <ChartCard title="Agent 信号分布" empty={signalDist.length === 0}>
          <PieChart>
            <Pie data={signalDist} dataKey="value" nameKey="name" innerRadius={32} outerRadius={58} paddingAngle={2}>
              {signalDist.map((d) => <Cell key={d.key} fill={SIGNAL_COLOR[d.key] || INDIGO} />)}
            </Pie>
            <Tooltip {...tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
          </PieChart>
        </ChartCard>

        {/* 2 */}
        <ChartCard title="各 Agent 置信度" empty={confData.length === 0}>
          <BarChart data={confData} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#737373' }} interval={0} angle={-20} textAnchor="end" height={42} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#737373' }} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="confidence" radius={[3, 3, 0, 0]}>
              {confData.map((d, i) => <Cell key={i} fill={SIGNAL_COLOR[d.signal] || INDIGO} />)}
            </Bar>
          </BarChart>
        </ChartCard>

        {/* 5 共识度 gauge */}
        <ChartCard title="多空共识度" subtitle={debate?.consensus} empty={consensusData.length === 0}>
          <RadialBarChart innerRadius="62%" outerRadius="100%" data={consensusData} startAngle={210} endAngle={-30}>
            <RadialBar background dataKey="value" cornerRadius={6} />
            <text x="50%" y="52%" textAnchor="middle" dominantBaseline="middle" fill="#e5e5e5" fontSize={20} fontWeight={600}>
              {consensusData[0]?.value ?? 0}
            </text>
            <Tooltip {...tooltipStyle} />
          </RadialBarChart>
        </ChartCard>

        {/* 3 */}
        <ChartCard title="多空力量对比" empty={strengthData.length === 0}>
          <BarChart data={strengthData} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#737373' }} />
            <YAxis tick={{ fontSize: 10, fill: '#737373' }} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {strengthData.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ChartCard>

        {/* 4 */}
        <ChartCard title="辩论阵营分布" empty={stanceData.length === 0}>
          <PieChart>
            <Pie data={stanceData} dataKey="value" nameKey="name" innerRadius={32} outerRadius={58} paddingAngle={2}>
              {stanceData.map((d) => <Cell key={d.key} fill={SIGNAL_COLOR[d.key] || INDIGO} />)}
            </Pie>
            <Tooltip {...tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
          </PieChart>
        </ChartCard>

        {/* 9 形态信号 */}
        <ChartCard title="K线形态信号" subtitle={frozen ? '未存档' : '近60日'} empty={patternData.every((d) => d.value === 0)}>
          <BarChart data={patternData} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#737373' }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: '#737373' }} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {patternData.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ChartCard>

        {/* 6 收盘走势 */}
        <ChartCard title="收盘走势" subtitle="近80日" empty={priceData.length === 0}>
          <AreaChart data={priceData} margin={{ top: 6, right: 8, bottom: 0, left: -10 }}>
            <defs>
              <linearGradient id="rcClose" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={INDIGO} stopOpacity={0.4} />
                <stop offset="100%" stopColor={INDIGO} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#737373' }} minTickGap={24} />
            <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10, fill: '#737373' }} />
            <Tooltip {...tooltipStyle} />
            <Area type="monotone" dataKey="close" stroke={INDIGO} strokeWidth={1.5} fill="url(#rcClose)" />
          </AreaChart>
        </ChartCard>

        {/* 7 成交量 */}
        <ChartCard title="成交量" subtitle="近80日" empty={priceData.length === 0}>
          <BarChart data={priceData} margin={{ top: 6, right: 8, bottom: 0, left: -2 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#737373' }} minTickGap={24} />
            <YAxis tick={{ fontSize: 9, fill: '#737373' }} width={42} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="volume" fill={SKY} opacity={0.55} />
          </BarChart>
        </ChartCard>

        {/* 8 技术因子 */}
        <ChartCard title="技术因子" subtitle="确定性量价度量" empty={factorData.length === 0}>
          <BarChart data={factorData} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 28 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis type="number" tick={{ fontSize: 9, fill: '#737373' }} />
            <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#737373' }} width={56} />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="value" radius={[0, 3, 3, 0]}>
              {factorData.map((d, i) => <Cell key={i} fill={d.value >= 0 ? RED : GREEN} />)}
            </Bar>
          </BarChart>
        </ChartCard>
      </div>
    </div>
  );
}
