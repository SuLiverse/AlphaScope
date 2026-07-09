/**
 * Workbench pure helpers, types, and period config (extracted from Workbench.tsx).
 */
import { Zap, Clock, LineChart as LineChartIcon, Settings2 } from "lucide-react";


export interface WorkbenchChartPoint {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  wickRange: [number, number];
  ma5: number;
  ma10: number;
  ma20: number;
  volume: number;
  amount?: number;
  change: number;
  changePct: number;
  up: boolean;
  source?: string;
  frequency?: string;
}

export interface PriceBar {
  symbol: string;
  date: string;
  market?: string;
  frequency?: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount?: number;
  change_pct?: number;
  previous_close?: number;
  source?: string;
}

export interface PriceSeriesResponse {
  symbol: string;
  frequency: string;
  bars: PriceBar[];
  total: number;
  degraded?: boolean;
  source_status?: string;
}

export type KlinePeriod = '分时' | '日K' | '周K' | '月K' | '年K' | '自定义';
export type CustomKlineFrequency = 'intraday' | '1d' | '1w' | '1mo' | '1y';

export interface PeriodConfig {
  points: number;
  frequency: CustomKlineFrequency;
  limit: number;
  stepDays: number;
  stepMinutes?: number;
  label: string;
  axisPeriod: Exclude<KlinePeriod, '自定义'>;
}

export const PERIOD_BUTTONS: KlinePeriod[] = ['分时', '日K', '周K', '月K', '年K', '自定义'];

export const CUSTOM_FREQUENCY_OPTIONS: Array<{ value: CustomKlineFrequency; label: string }> = [
  { value: 'intraday', label: '分时' },
  { value: '1d', label: '日K' },
  { value: '1w', label: '周K' },
  { value: '1mo', label: '月K' },
  { value: '1y', label: '年K' },
];

export const CUSTOM_LIMIT_OPTIONS: Record<CustomKlineFrequency, Array<{ value: string; label: string }>> = {
  intraday: [
    { value: '60', label: '60分' },
    { value: '120', label: '120分' },
    { value: '240', label: '240分' },
  ],
  '1d': [
    { value: '60', label: '60日' },
    { value: '120', label: '120日' },
    { value: '250', label: '250日' },
    { value: '500', label: '500日' },
  ],
  '1w': [
    { value: '26', label: '26周' },
    { value: '52', label: '52周' },
    { value: '104', label: '104周' },
    { value: '156', label: '156周' },
  ],
  '1mo': [
    { value: '24', label: '24月' },
    { value: '60', label: '60月' },
    { value: '120', label: '120月' },
  ],
  '1y': [
    { value: '5', label: '5年' },
    { value: '10', label: '10年' },
    { value: '20', label: '20年' },
  ],
};

export const CUSTOM_FREQUENCY_CONFIG: Record<CustomKlineFrequency, Omit<PeriodConfig, 'points' | 'limit' | 'label'>> = {
  intraday: { frequency: 'intraday', stepDays: 0, stepMinutes: 5, axisPeriod: '分时' },
  '1d': { frequency: '1d', stepDays: 1, axisPeriod: '日K' },
  '1w': { frequency: '1w', stepDays: 7, axisPeriod: '周K' },
  '1mo': { frequency: '1mo', stepDays: 30, axisPeriod: '月K' },
  '1y': { frequency: '1y', stepDays: 365, axisPeriod: '年K' },
};

export function getCustomLimitOptions(frequency: CustomKlineFrequency) {
  return CUSTOM_LIMIT_OPTIONS[frequency] ?? CUSTOM_LIMIT_OPTIONS['1d'];
}

export function getCustomLimitNumber(frequency: CustomKlineFrequency, value: string) {
  const options = getCustomLimitOptions(frequency);
  const fallback = Number(options[1]?.value ?? options[0]?.value ?? 120);
  const parsed = Number(value);
  return options.some((option) => option.value === value) && Number.isFinite(parsed)
    ? parsed
    : fallback;
}

export const generateKlineData = (
  points: number,
  basePrice: number = 1500,
  stepDays = 1,
  stepMinutes = 0,
): WorkbenchChartPoint[] => {
  let currentPrice = basePrice;
  const volatility = Math.max(0.25, Math.min(10, basePrice * 0.012));
  const volumeBase = Math.max(80000, basePrice * 2800);
  const startDate = new Date();
  startDate.setSeconds(0, 0);
  if (stepMinutes > 0) {
    startDate.setTime(startDate.getTime() - (points - 1) * stepMinutes * 60_000);
  } else {
    startDate.setDate(startDate.getDate() - (points - 1) * stepDays);
  }
  const raw = Array.from({ length: points }).map((_, i) => {
    const open = currentPrice;
    const close = Math.max(0.1, currentPrice + (Math.random() * volatility * 2 - volatility));
    const high = Math.max(open, close) + Math.random() * volatility * 0.8;
    const low = Math.max(0.1, Math.min(open, close) - Math.random() * volatility * 0.8);
    const date = new Date(startDate);
    if (stepMinutes > 0) {
      date.setTime(startDate.getTime() + i * stepMinutes * 60_000);
    } else {
      date.setDate(startDate.getDate() + i * stepDays);
    }
    currentPrice = close;
    return {
      date: stepMinutes > 0
        ? `${date.toISOString().slice(0, 10)} ${date.toTimeString().slice(0, 5)}`
        : date.toISOString().slice(0, 10),
      open: Number(open.toFixed(2)),
      close: Number(close.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      wickRange: [Number(low.toFixed(2)), Number(high.toFixed(2))] as [number, number],
      volume: volumeBase + Math.random() * volumeBase * 1.8,
      change: Number((close - open).toFixed(2)),
      changePct: Number((((close - open) / open) * 100).toFixed(2)),
      up: close >= open,
    };
  });
  return raw.map((item, index) => {
    const slice5 = raw.slice(Math.max(0, index - 4), index + 1);
    const slice10 = raw.slice(Math.max(0, index - 9), index + 1);
    const slice20 = raw.slice(Math.max(0, index - 19), index + 1);
    return {
      ...item,
      ma5: Number((slice5.reduce((sum, point) => sum + point.close, 0) / slice5.length).toFixed(2)),
      ma10: Number((slice10.reduce((sum, point) => sum + point.close, 0) / slice10.length).toFixed(2)),
      ma20: Number((slice20.reduce((sum, point) => sum + point.close, 0) / slice20.length).toFixed(2)),
      source: 'local-preview',
    };
  });
};

export type MetricTone = 'rose' | 'emerald' | 'indigo' | 'amber' | 'neutral';

export interface MetricCard {
  label: string;
  value: string;
  detail: string;
  tone: MetricTone;
}

export interface PanelNewsItem {
  time: string;
  title: string;
  desc?: string;
  source: string;
  detail: string;
}

export interface FinancialPeriod {
  period?: string;
  revenue_yi?: number;
  net_profit_yi?: number;
  gross_margin_pct?: number;
  roe_pct?: number;
  debt_ratio_pct?: number;
  yoy_revenue_pct?: number;
  yoy_net_profit_pct?: number;
}

export interface FundamentalsResponse {
  symbol: string;
  stock_name?: string;
  industry?: string;
  financial_periods?: FinancialPeriod[];
  valuation?: Record<string, number | string>;
  fundamental_score?: Record<string, number | string>;
  degraded?: boolean;
  source_status?: string;
  error?: string;
}

export interface FundFlowSummary {
  recent_days?: number;
  main_total_yi?: number;
  super_total_yi?: number;
  large_total_yi?: number;
  medium_total_yi?: number;
  small_total_yi?: number;
  last_date?: string;
  last_main_yi?: number;
  last_main_pct?: number;
  inflow_days?: number;
  outflow_days?: number;
}

export interface FundFlowResponse {
  symbol: string;
  summary?: FundFlowSummary;
  records?: Array<Record<string, number | string>>;
  degraded?: boolean;
  source?: string;
  source_status?: string;
  error?: string;
  cached_at?: string;
}

export interface FactorResponse {
  symbol: string;
  stock_name?: string;
  computed_at?: string;
  factors?: Record<string, number>;
  sample_counts?: Record<string, number>;
  degraded_inputs?: string[];
  missing_dimensions?: string[];
  signals?: Array<Record<string, number | string | boolean>>;
}

export interface NewsResponseItem {
  title?: string;
  summary?: string;
  source?: string;
  published_at?: string;
  event_type?: string;
  sentiment?: number;
  importance?: number;
}

export interface NewsListResponse {
  news?: NewsResponseItem[];
  total?: number;
  degraded?: boolean;
  source_status?: string;
  error?: string;
}

export const LOADING_FINANCE_CARDS: MetricCard[] = [
  { label: '营业收入', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: '归母净利', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: '毛利率', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: 'ROE', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
];

export const LOADING_FUND_CARDS: MetricCard[] = [
  { label: '近5日主力', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '当日主力', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '超大单', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '大单', value: '--', detail: '正在同步资金流', tone: 'neutral' },
];

export const LOADING_QUANT_CARDS: MetricCard[] = [
  { label: '综合因子', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '价格动量', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '资金因子', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '样本完整度', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
];

export const ANALYSIS_MODES = [
  { id: 'auto', label: '自动模式', desc: '先快速预筛，信号强时直接给结论，分歧时自动升级深度分析' },
  { id: 'standard', label: '标准分析', desc: '基本面、资金、技术面综合研判（多 Agent 会签）' },
  { id: 'deep', label: '深度分析', desc: '买方深度调研 + 全维度专家团 + Critic 反证 + 主席总结（最完整）' },
] as const;

export type AnalysisModeId = typeof ANALYSIS_MODES[number]['id'];

export type PanelTabId = 'news' | 'finance' | 'funds' | 'quant';

export interface ChatResponse {
  conversation_id: string;
  mode: string;
  content: string;
  provider?: string;
  model?: string;
  detected_intent?: string;
  auto_routed?: boolean;
  error?: boolean;
}

export const PANEL_TABS: Array<{ id: PanelTabId; label: string; icon: typeof Zap }> = [
  { id: 'news', label: '实时资讯', icon: Zap },
  { id: 'finance', label: '核心财务', icon: Clock },
  { id: 'funds', label: '主力资金', icon: LineChartIcon },
  { id: 'quant', label: '量化因子', icon: Settings2 },
];

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error || '未知错误');
}

export function formatMessageHtml(content: string) {
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<span class="text-white font-medium">$1</span>')
    .replace(/\n/g, '<br/>');
}

export function stripSymbolSuffix(symbol: string) {
  return String(symbol || '').trim().split('.')[0];
}

export function formatAxisDate(value: string, period = '日K') {
  const text = String(value || '');
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (!match) return text;
  const [, year, month, day, hour, minute] = match;
  if (period === '分时') {
    return hour && minute ? `${hour}:${minute}` : `${month}-${day}`;
  }
  if (period === '月K') {
    return `${year}-${month}`;
  }
  if (period === '年K') {
    return year;
  }
  return `${month}-${day}`;
}

export function getMinimumPeriodBars(period: string) {
  if (period === '1y' || period === '年K') return 2;
  if (period === '1mo' || period === '月K') return 6;
  if (period === '1w' || period === '周K') return 12;
  return 2;
}

export function shouldShowMovingAverage(period: string, dataLength: number, windowSize: number) {
  if (period === '1y' || period === '年K' || period === '1mo' || period === '月K' || period === '1w' || period === '周K') {
    return dataLength >= windowSize;
  }
  return dataLength >= 2;
}

export function formatPricePayloadMessage(payload: PriceSeriesResponse, periodLabel: string) {
  if (payload.source_status === 'short_history') {
    return `${periodLabel}样本不足，仅显示上市以来可用K线`;
  }
  if (payload.degraded) {
    return '行情源降级，使用可用缓存';
  }
  return '真实行情已同步';
}

export function formatPrice(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatVolume(value?: number) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return Math.round(number).toLocaleString('zh-CN');
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function formatYi(value?: number, digits = 1) {
  if (!isFiniteNumber(value)) return '--';
  return `${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}亿`;
}

export function formatSignedYi(value?: number, digits = 2) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}亿`;
}

export function formatPercent(value?: number, digits = 1) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
}

export function formatFactorValue(value?: number) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(3)}`;
}

export function toneForSigned(value?: number): MetricTone {
  if (!isFiniteNumber(value) || Math.abs(value) < 0.0001) return 'neutral';
  return value > 0 ? 'rose' : 'emerald';
}

export function toneForQuality(value?: number): MetricTone {
  if (!isFiniteNumber(value)) return 'neutral';
  if (value >= 70) return 'rose';
  if (value >= 45) return 'indigo';
  return 'amber';
}

export function metricToneClass(tone: MetricTone) {
  return {
    rose: 'text-rose-500 drop-shadow-[0_0_10px_rgba(244,63,94,0.22)]',
    emerald: 'text-emerald-500 drop-shadow-[0_0_10px_rgba(16,185,129,0.22)]',
    indigo: 'text-indigo-300 drop-shadow-[0_0_10px_rgba(129,140,248,0.22)]',
    amber: 'text-amber-300 drop-shadow-[0_0_10px_rgba(251,191,36,0.18)]',
    neutral: 'text-neutral-300',
  }[tone];
}

export function sourceStatusLabel(sourceStatus?: string, degraded?: boolean) {
  if (degraded) {
    if (sourceStatus === 'cache') return '缓存数据';
    if (sourceStatus === 'timeout') return '数据源超时';
    if (sourceStatus === 'empty') return '暂无数据';
    if (sourceStatus === 'unavailable') return '数据源不可用';
    return `降级：${sourceStatus || 'unknown'}`;
  }
  if (!sourceStatus || sourceStatus === 'ok') return '真实数据';
  return sourceStatus;
}

export function formatNewsTime(value?: string) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  const month = String(parsed.getMonth() + 1).padStart(2, '0');
  const day = String(parsed.getDate()).padStart(2, '0');
  const hour = String(parsed.getHours()).padStart(2, '0');
  const minute = String(parsed.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${minute}`;
}

export function emptyCards(reason: string): MetricCard[] {
  return [
    { label: '数据状态', value: '暂无', detail: reason, tone: 'amber' },
    { label: '来源', value: '--', detail: reason, tone: 'neutral' },
    { label: '日期', value: '--', detail: reason, tone: 'neutral' },
    { label: '建议', value: '刷新', detail: '点击行情刷新按钮后会重新拉取信息源', tone: 'indigo' },
  ];
}

export function buildFinanceCards(payload?: FundamentalsResponse): MetricCard[] {
  const latest = payload?.financial_periods?.[0];
  if (!latest) {
    return emptyCards(payload?.error || '基本面接口没有返回当前标的财务摘要');
  }
  const period = latest.period || '最新报告期';
  const score = Number(payload?.fundamental_score?.total_score ?? payload?.fundamental_score?.score ?? NaN);
  return [
    {
      label: '营业收入',
      value: formatYi(latest.revenue_yi),
      detail: `${period} · 营收同比 ${formatPercent(latest.yoy_revenue_pct)}`,
      tone: toneForSigned(latest.yoy_revenue_pct),
    },
    {
      label: '归母净利',
      value: formatYi(latest.net_profit_yi),
      detail: `${period} · 净利同比 ${formatPercent(latest.yoy_net_profit_pct)}`,
      tone: toneForSigned(latest.yoy_net_profit_pct),
    },
    {
      label: '毛利率',
      value: formatPercent(latest.gross_margin_pct),
      detail: `${period} · 来自财务摘要`,
      tone: isFiniteNumber(latest.gross_margin_pct) ? 'rose' : 'neutral',
    },
    {
      label: 'ROE',
      value: formatPercent(latest.roe_pct),
      detail: isFiniteNumber(score) ? `基本面评分 ${score.toFixed(0)}` : `${period} · 资产负债率 ${formatPercent(latest.debt_ratio_pct)}`,
      tone: isFiniteNumber(score) ? toneForQuality(score) : toneForSigned(latest.roe_pct),
    },
  ];
}

export function buildFundFlowCards(payload?: FundFlowResponse): MetricCard[] {
  const summary = payload?.summary;
  if (!summary) {
    return emptyCards(payload?.error || '资金流接口没有返回当前标的资金数据');
  }
  const recentDays = summary.recent_days || 5;
  const trend = `${summary.inflow_days || 0} 日流入 / ${summary.outflow_days || 0} 日流出`;
  const lastDate = summary.last_date || '最近交易日';
  return [
    {
      label: `近${recentDays}日主力`,
      value: formatSignedYi(summary.main_total_yi),
      detail: `${trend} · ${payload?.source || 'eastmoney'}`,
      tone: toneForSigned(summary.main_total_yi),
    },
    {
      label: '当日主力',
      value: formatSignedYi(summary.last_main_yi),
      detail: `${lastDate} · 净占比 ${formatPercent(summary.last_main_pct, 2)}`,
      tone: toneForSigned(summary.last_main_yi),
    },
    {
      label: '超大单',
      value: formatSignedYi(summary.super_total_yi),
      detail: `近${recentDays}日超大单净额`,
      tone: toneForSigned(summary.super_total_yi),
    },
    {
      label: '大单',
      value: formatSignedYi(summary.large_total_yi),
      detail: `近${recentDays}日大单净额`,
      tone: toneForSigned(summary.large_total_yi),
    },
  ];
}

export function buildQuantCards(payload?: FactorResponse): MetricCard[] {
  const factors = payload?.factors || {};
  if (!payload || !Object.keys(factors).length) {
    return emptyCards('量化因子接口没有返回可用结果');
  }
  const counts = payload.sample_counts || {};
  const missing = payload.missing_dimensions || [];
  const degraded = payload.degraded_inputs || [];
  const qualityScore = Math.max(
    0,
    100 - missing.length * 20 - degraded.length * 10,
  );
  const sampleText = `新闻 ${counts.news || 0} / 事件 ${counts.events || 0} / 研报 ${counts.reports || 0}`;
  return [
    {
      label: '综合因子',
      value: formatFactorValue(factors.composite),
      detail: `加权新闻、事件、评级、资金与动量 · ${payload.computed_at?.slice(0, 10) || '最新'}`,
      tone: toneForSigned(factors.composite),
    },
    {
      label: '价格动量',
      value: formatFactorValue(factors.momentum),
      detail: '基于近端价格涨跌幅与成交量变化',
      tone: toneForSigned(factors.momentum),
    },
    {
      label: '资金因子',
      value: formatFactorValue(factors.fund_flow),
      detail: degraded.includes('fund_flow') ? '资金源降级，因子可信度降低' : '基于主力资金近5日趋势',
      tone: toneForSigned(factors.fund_flow),
    },
    {
      label: '样本完整度',
      value: `${qualityScore}`,
      detail: missing.length ? `${sampleText} · 缺失 ${missing.join(', ')}` : sampleText,
      tone: toneForQuality(qualityScore),
    },
  ];
}

export function buildNewsItems(payload?: NewsListResponse): PanelNewsItem[] {
  return (payload?.news || []).slice(0, 6).map((item) => ({
    time: formatNewsTime(item.published_at),
    title: item.title || '未命名资讯',
    desc: item.summary || (item.event_type ? `事件类型：${item.event_type}` : undefined),
    source: item.source || 'news',
    detail: `${item.source || 'news'} · ${item.published_at || '未知时间'}`,
  }));
}

export function getWorkbenchPriceDomain(data: WorkbenchChartPoint[], fallback: number): [number, number] {
  const values = data.flatMap((point) => [
    point.open,
    point.close,
    point.high,
    point.low,
    point.ma5,
    point.ma10,
    point.ma20,
  ]).filter((value) => Number.isFinite(value));
  const baseValues = values.length ? values : [fallback || 1];
  const min = Math.min(...baseValues);
  const max = Math.max(...baseValues);
  const range = Math.max(max - min, Math.abs(max) * 0.01, 1);
  const padding = Math.max(range * 0.08, 0.01);
  return [Math.max(0, min - padding), max + padding];
}

export function enrichWorkbenchData(rawBars: PriceBar[]): WorkbenchChartPoint[] {
  const bars = [...rawBars].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return bars.map((bar, index) => {
    const open = Number(bar.open || 0);
    const close = Number(bar.close || 0);
    const high = Number(bar.high || Math.max(open, close));
    const low = Number(bar.low || Math.min(open, close));
    const previousClose = index > 0
      ? Number(bars[index - 1].close || open)
      : Number(bar.previous_close || 0) || (
        typeof bar.change_pct === 'number' && Number.isFinite(bar.change_pct) && bar.change_pct !== -100
          ? close / (1 + bar.change_pct / 100)
          : open
      );
    const base = previousClose || open || close || 1;
    const change = close - base;
    const changePct = typeof bar.change_pct === 'number' && Number.isFinite(bar.change_pct)
      ? bar.change_pct
      : (change / base) * 100;
    const slice5 = bars.slice(Math.max(0, index - 4), index + 1);
    const slice10 = bars.slice(Math.max(0, index - 9), index + 1);
    const slice20 = bars.slice(Math.max(0, index - 19), index + 1);

    return {
      date: String(bar.date || ''),
      open: Number(open.toFixed(2)),
      close: Number(close.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      wickRange: [Number(low.toFixed(2)), Number(high.toFixed(2))],
      ma5: Number((slice5.reduce((sum, point) => sum + Number(point.close || 0), 0) / Math.max(1, slice5.length)).toFixed(2)),
      ma10: Number((slice10.reduce((sum, point) => sum + Number(point.close || 0), 0) / Math.max(1, slice10.length)).toFixed(2)),
      ma20: Number((slice20.reduce((sum, point) => sum + Number(point.close || 0), 0) / Math.max(1, slice20.length)).toFixed(2)),
      volume: Number(bar.volume || 0),
      amount: Number(bar.amount || 0),
      change: Number(change.toFixed(2)),
      changePct: Number(changePct.toFixed(2)),
      up: close >= base,
      source: bar.source,
      frequency: bar.frequency,
    };
  });
}

export function getFloatingTooltipStyle(
  coordinate?: { x?: number; y?: number },
  viewBox?: { x?: number; y?: number; width?: number; height?: number },
  size: { width: number; height: number } = { width: 188, height: 168 },
) {
  if (typeof coordinate?.x !== 'number' || typeof coordinate?.y !== 'number') {
    return { transform: 'translate(-50%, calc(-100% - 12px))' };
  }

  const { width } = size;
  const edgePadding = 12;
  const chartLeft = Number(viewBox?.x ?? 0);
  const chartRight = chartLeft + Number(viewBox?.width ?? 0);
  const nearLeft = coordinate.x - width / 2 < chartLeft + edgePadding;
  const nearRight = chartRight > chartLeft && coordinate.x + width / 2 > chartRight - edgePadding;
  const shiftX = nearLeft ? '8px' : nearRight ? 'calc(-100% - 8px)' : '-50%';
  const shiftY = 'calc(-100% - 12px)';

  return { transform: `translate(${shiftX}, ${shiftY})` };
}

export function getPeriodConfig(
  period: KlinePeriod,
  customFrequency: CustomKlineFrequency = '1d',
  customLimit = '120',
): PeriodConfig {
  if (period === '自定义') {
    const base = CUSTOM_FREQUENCY_CONFIG[customFrequency];
    const limit = getCustomLimitNumber(customFrequency, customLimit);
    return {
      ...base,
      points: limit,
      limit,
      label: `自定义${base.axisPeriod}`,
    };
  }
  if (period === '分时') return { points: 60, frequency: 'intraday', limit: 120, stepDays: 0, stepMinutes: 5, label: '分时', axisPeriod: '分时' };
  if (period === '周K') return { points: 104, frequency: '1w', limit: 156, stepDays: 7, label: '周K', axisPeriod: '周K' };
  if (period === '月K') return { points: 60, frequency: '1mo', limit: 120, stepDays: 30, label: '月K', axisPeriod: '月K' };
  if (period === '年K') return { points: 12, frequency: '1y', limit: 20, stepDays: 365, label: '年K', axisPeriod: '年K' };
  return { points: 40, frequency: '1d', limit: 80, stepDays: 1, label: '日K', axisPeriod: '日K' };
}

export function getPeriodTestId(period: string) {
  if (period === '分时') return 'workbench-period-intraday';
  if (period === '周K') return 'workbench-period-weekly';
  if (period === '月K') return 'workbench-period-monthly';
  if (period === '年K') return 'workbench-period-yearly';
  if (period === '自定义') return 'workbench-period-custom';
  return 'workbench-period-daily';
}

export interface WorkbenchProps {
  onOpenModelSettings?: () => void;
}


