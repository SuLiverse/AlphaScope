import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Bot, Maximize2, RefreshCw, Send, Zap, Clock, LineChart as LineChartIcon, Settings2, Sparkles, ChevronDown, ImagePlus } from 'lucide-react';
import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Cell, Tooltip } from 'recharts';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { ChatMessage } from '../types';
import { STOCK_UNIVERSE, StockTarget, findStockTarget, formatStockLabel, resolveStockTarget } from '../lib/stocks';
import { getPersistedStock, subscribeStockSelected, subscribeSettingsChanged } from '../lib/workspaceEvents';
import { fetchApi, API_BASE_URL, API_KEY, LOCAL_API_TOKEN } from '../lib/api';
import {
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  ModelProvider,
} from '../lib/aiModelRouting';
import { ThemedSelect } from './ThemedSelect';
import { StableChartContainer } from './StableChartContainer';
// 专业 K 线懒加载, 把 lightweight-charts 拆出主包(Workbench 是默认页, 仍是首屏并行加载的独立分块)。
const LightweightKLine = lazy(() => import('./LightweightKLine').then((m) => ({ default: m.LightweightKLine })));

interface WorkbenchChartPoint {
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

interface PriceBar {
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

interface PriceSeriesResponse {
  symbol: string;
  frequency: string;
  bars: PriceBar[];
  total: number;
  degraded?: boolean;
  source_status?: string;
}

type KlinePeriod = '分时' | '日K' | '周K' | '月K' | '年K' | '自定义';
type CustomKlineFrequency = 'intraday' | '1d' | '1w' | '1mo' | '1y';

interface PeriodConfig {
  points: number;
  frequency: CustomKlineFrequency;
  limit: number;
  stepDays: number;
  stepMinutes?: number;
  label: string;
  axisPeriod: Exclude<KlinePeriod, '自定义'>;
}

const PERIOD_BUTTONS: KlinePeriod[] = ['分时', '日K', '周K', '月K', '年K', '自定义'];

const CUSTOM_FREQUENCY_OPTIONS: Array<{ value: CustomKlineFrequency; label: string }> = [
  { value: 'intraday', label: '分时' },
  { value: '1d', label: '日K' },
  { value: '1w', label: '周K' },
  { value: '1mo', label: '月K' },
  { value: '1y', label: '年K' },
];

const CUSTOM_LIMIT_OPTIONS: Record<CustomKlineFrequency, Array<{ value: string; label: string }>> = {
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

const CUSTOM_FREQUENCY_CONFIG: Record<CustomKlineFrequency, Omit<PeriodConfig, 'points' | 'limit' | 'label'>> = {
  intraday: { frequency: 'intraday', stepDays: 0, stepMinutes: 5, axisPeriod: '分时' },
  '1d': { frequency: '1d', stepDays: 1, axisPeriod: '日K' },
  '1w': { frequency: '1w', stepDays: 7, axisPeriod: '周K' },
  '1mo': { frequency: '1mo', stepDays: 30, axisPeriod: '月K' },
  '1y': { frequency: '1y', stepDays: 365, axisPeriod: '年K' },
};

function getCustomLimitOptions(frequency: CustomKlineFrequency) {
  return CUSTOM_LIMIT_OPTIONS[frequency] ?? CUSTOM_LIMIT_OPTIONS['1d'];
}

function getCustomLimitNumber(frequency: CustomKlineFrequency, value: string) {
  const options = getCustomLimitOptions(frequency);
  const fallback = Number(options[1]?.value ?? options[0]?.value ?? 120);
  const parsed = Number(value);
  return options.some((option) => option.value === value) && Number.isFinite(parsed)
    ? parsed
    : fallback;
}

const generateKlineData = (
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

type MetricTone = 'rose' | 'emerald' | 'indigo' | 'amber' | 'neutral';

interface MetricCard {
  label: string;
  value: string;
  detail: string;
  tone: MetricTone;
}

interface PanelNewsItem {
  time: string;
  title: string;
  desc?: string;
  source: string;
  detail: string;
}

interface FinancialPeriod {
  period?: string;
  revenue_yi?: number;
  net_profit_yi?: number;
  gross_margin_pct?: number;
  roe_pct?: number;
  debt_ratio_pct?: number;
  yoy_revenue_pct?: number;
  yoy_net_profit_pct?: number;
}

interface FundamentalsResponse {
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

interface FundFlowSummary {
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

interface FundFlowResponse {
  symbol: string;
  summary?: FundFlowSummary;
  records?: Array<Record<string, number | string>>;
  degraded?: boolean;
  source?: string;
  source_status?: string;
  error?: string;
  cached_at?: string;
}

interface FactorResponse {
  symbol: string;
  stock_name?: string;
  computed_at?: string;
  factors?: Record<string, number>;
  sample_counts?: Record<string, number>;
  degraded_inputs?: string[];
  missing_dimensions?: string[];
  signals?: Array<Record<string, number | string | boolean>>;
}

interface NewsResponseItem {
  title?: string;
  summary?: string;
  source?: string;
  published_at?: string;
  event_type?: string;
  sentiment?: number;
  importance?: number;
}

interface NewsListResponse {
  news?: NewsResponseItem[];
  total?: number;
  degraded?: boolean;
  source_status?: string;
  error?: string;
}

const LOADING_FINANCE_CARDS: MetricCard[] = [
  { label: '营业收入', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: '归母净利', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: '毛利率', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
  { label: 'ROE', value: '--', detail: '正在同步财务摘要', tone: 'neutral' },
];

const LOADING_FUND_CARDS: MetricCard[] = [
  { label: '近5日主力', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '当日主力', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '超大单', value: '--', detail: '正在同步资金流', tone: 'neutral' },
  { label: '大单', value: '--', detail: '正在同步资金流', tone: 'neutral' },
];

const LOADING_QUANT_CARDS: MetricCard[] = [
  { label: '综合因子', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '价格动量', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '资金因子', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
  { label: '样本完整度', value: '--', detail: '正在计算量化因子', tone: 'neutral' },
];

const ANALYSIS_MODES = [
  { id: 'auto', label: '自动模式', desc: '先快速预筛，信号强时直接给结论，分歧时自动升级深度分析' },
  { id: 'standard', label: '标准分析', desc: '基本面、资金、技术面综合研判（多 Agent 会签）' },
  { id: 'deep', label: '深度分析', desc: '买方深度调研 + 全维度专家团 + Critic 反证 + 主席总结（最完整）' },
] as const;

type AnalysisModeId = typeof ANALYSIS_MODES[number]['id'];

type PanelTabId = 'news' | 'finance' | 'funds' | 'quant';

interface ChatResponse {
  conversation_id: string;
  mode: string;
  content: string;
  provider?: string;
  model?: string;
  detected_intent?: string;
  auto_routed?: boolean;
  error?: boolean;
}

const PANEL_TABS: Array<{ id: PanelTabId; label: string; icon: typeof Zap }> = [
  { id: 'news', label: '实时资讯', icon: Zap },
  { id: 'finance', label: '核心财务', icon: Clock },
  { id: 'funds', label: '主力资金', icon: LineChartIcon },
  { id: 'quant', label: '量化因子', icon: Settings2 },
];

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error || '未知错误');
}

function formatMessageHtml(content: string) {
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<span class="text-white font-medium">$1</span>')
    .replace(/\n/g, '<br/>');
}

function stripSymbolSuffix(symbol: string) {
  return String(symbol || '').trim().split('.')[0];
}

function formatAxisDate(value: string, period = '日K') {
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

function getMinimumPeriodBars(period: string) {
  if (period === '1y' || period === '年K') return 2;
  if (period === '1mo' || period === '月K') return 6;
  if (period === '1w' || period === '周K') return 12;
  return 2;
}

function shouldShowMovingAverage(period: string, dataLength: number, windowSize: number) {
  if (period === '1y' || period === '年K' || period === '1mo' || period === '月K' || period === '1w' || period === '周K') {
    return dataLength >= windowSize;
  }
  return dataLength >= 2;
}

function formatPricePayloadMessage(payload: PriceSeriesResponse, periodLabel: string) {
  if (payload.source_status === 'short_history') {
    return `${periodLabel}样本不足，仅显示上市以来可用K线`;
  }
  if (payload.degraded) {
    return '行情源降级，使用可用缓存';
  }
  return '真实行情已同步';
}

function formatPrice(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatVolume(value?: number) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return Math.round(number).toLocaleString('zh-CN');
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function formatYi(value?: number, digits = 1) {
  if (!isFiniteNumber(value)) return '--';
  return `${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}亿`;
}

function formatSignedYi(value?: number, digits = 2) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}亿`;
}

function formatPercent(value?: number, digits = 1) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
}

function formatFactorValue(value?: number) {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(3)}`;
}

function toneForSigned(value?: number): MetricTone {
  if (!isFiniteNumber(value) || Math.abs(value) < 0.0001) return 'neutral';
  return value > 0 ? 'rose' : 'emerald';
}

function toneForQuality(value?: number): MetricTone {
  if (!isFiniteNumber(value)) return 'neutral';
  if (value >= 70) return 'rose';
  if (value >= 45) return 'indigo';
  return 'amber';
}

function metricToneClass(tone: MetricTone) {
  return {
    rose: 'text-rose-500 drop-shadow-[0_0_10px_rgba(244,63,94,0.22)]',
    emerald: 'text-emerald-500 drop-shadow-[0_0_10px_rgba(16,185,129,0.22)]',
    indigo: 'text-indigo-300 drop-shadow-[0_0_10px_rgba(129,140,248,0.22)]',
    amber: 'text-amber-300 drop-shadow-[0_0_10px_rgba(251,191,36,0.18)]',
    neutral: 'text-neutral-300',
  }[tone];
}

function sourceStatusLabel(sourceStatus?: string, degraded?: boolean) {
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

function formatNewsTime(value?: string) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  const month = String(parsed.getMonth() + 1).padStart(2, '0');
  const day = String(parsed.getDate()).padStart(2, '0');
  const hour = String(parsed.getHours()).padStart(2, '0');
  const minute = String(parsed.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${minute}`;
}

function emptyCards(reason: string): MetricCard[] {
  return [
    { label: '数据状态', value: '暂无', detail: reason, tone: 'amber' },
    { label: '来源', value: '--', detail: reason, tone: 'neutral' },
    { label: '日期', value: '--', detail: reason, tone: 'neutral' },
    { label: '建议', value: '刷新', detail: '点击行情刷新按钮后会重新拉取信息源', tone: 'indigo' },
  ];
}

function buildFinanceCards(payload?: FundamentalsResponse): MetricCard[] {
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

function buildFundFlowCards(payload?: FundFlowResponse): MetricCard[] {
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

function buildQuantCards(payload?: FactorResponse): MetricCard[] {
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

function buildNewsItems(payload?: NewsListResponse): PanelNewsItem[] {
  return (payload?.news || []).slice(0, 6).map((item) => ({
    time: formatNewsTime(item.published_at),
    title: item.title || '未命名资讯',
    desc: item.summary || (item.event_type ? `事件类型：${item.event_type}` : undefined),
    source: item.source || 'news',
    detail: `${item.source || 'news'} · ${item.published_at || '未知时间'}`,
  }));
}

function getWorkbenchPriceDomain(data: WorkbenchChartPoint[], fallback: number): [number, number] {
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

function enrichWorkbenchData(rawBars: PriceBar[]): WorkbenchChartPoint[] {
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

function getFloatingTooltipStyle(
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

function WorkbenchChartTooltip({ active, payload, label, coordinate, viewBox }: any) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as WorkbenchChartPoint;
  const isUp = data.change >= 0;
  return (
    <div
      style={getFloatingTooltipStyle(coordinate, viewBox, { width: 150, height: 58 })}
      className="w-[150px] rounded-md border border-indigo-400/20 bg-[#090a10] px-2.5 py-1.5 text-[10px] text-neutral-300 shadow-[0_8px_18px_rgba(0,0,0,0.28)]"
    >
      <div className="flex items-center justify-between gap-3 font-mono">
        <span className="truncate text-neutral-200">{label}</span>
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '+' : ''}{data.changePct.toFixed(2)}%
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between border-t border-white/5 pt-1 font-mono">
        <span className="text-neutral-500">量</span>
        <span className="text-neutral-100">{formatVolume(data.volume)}</span>
      </div>
    </div>
  );
}

function CompactWorkbenchTooltip({ active, payload, label, coordinate, viewBox }: any) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as WorkbenchChartPoint;
  const isUp = data.change >= 0;
  return (
    <div
      style={getFloatingTooltipStyle(coordinate, viewBox, { width: 150, height: 58 })}
      className="w-[150px] rounded-md border border-indigo-400/20 bg-[#090a10] px-2.5 py-1.5 text-[10px] text-neutral-300 shadow-[0_8px_18px_rgba(0,0,0,0.28)]"
    >
      <div className="flex items-center justify-between gap-3 font-mono">
        <span className="truncate text-neutral-200">{label}</span>
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '+' : ''}{data.changePct.toFixed(2)}%
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between border-t border-white/5 pt-1 font-mono">
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '涨' : '跌'} {isUp ? '+' : ''}{data.change.toFixed(2)}
        </span>
        <span className="text-neutral-100">{formatPrice(data.close)}</span>
      </div>
    </div>
  );
}

function WorkbenchCandlestick(props: any) {
  const { x, y, width, height, payload } = props;
  const point = payload as WorkbenchChartPoint | undefined;
  if (!point) return null;

  const color = point.close >= point.open ? '#f43f5e' : '#10b981';
  const slotX = Number(x || 0);
  const slotWidth = Math.max(Number(width || 0), 1);
  const cx = slotX + slotWidth / 2;
  const yStart = Number(y || 0);
  const yEnd = yStart + Number(height || 0);
  const wickTop = Math.min(yStart, yEnd);
  const wickBottom = Math.max(yStart, yEnd);
  const wickHeight = Math.max(wickBottom - wickTop, 1);
  const high = Number(point.high);
  const low = Number(point.low);
  const priceToY = (price: number) => {
    if (!Number.isFinite(high) || !Number.isFinite(low) || high <= low) {
      return wickTop + wickHeight / 2;
    }
    const clamped = Math.max(low, Math.min(high, price));
    return wickTop + ((high - clamped) / (high - low)) * wickHeight;
  };
  const yOpen = priceToY(point.open);
  const yClose = priceToY(point.close);
  const rectHeight = Math.max(Math.abs(yOpen - yClose), 1.5);
  const rectY = Math.max(wickTop, Math.min(Math.min(yOpen, yClose), wickBottom - rectHeight));
  const bodyWidth = Math.max(3, Math.min(slotWidth * 0.72, 9));

  return (
    <g>
      <line x1={cx} y1={wickTop} x2={cx} y2={wickBottom} stroke={color} strokeWidth={1.2} strokeLinecap="round" />
      <rect
        x={cx - bodyWidth / 2}
        y={rectY}
        width={bodyWidth}
        height={rectHeight}
        fill={color}
        fillOpacity={0.9}
        stroke={color}
        strokeWidth={1}
        rx={0.75}
      />
    </g>
  );
}

function getPeriodConfig(
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

function getPeriodTestId(period: string) {
  if (period === '分时') return 'workbench-period-intraday';
  if (period === '周K') return 'workbench-period-weekly';
  if (period === '月K') return 'workbench-period-monthly';
  if (period === '年K') return 'workbench-period-yearly';
  if (period === '自定义') return 'workbench-period-custom';
  return 'workbench-period-daily';
}

interface WorkbenchProps {
  onOpenModelSettings?: () => void;
}

export function Workbench({ onOpenModelSettings }: WorkbenchProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previousChartPeriodKeyRef = useRef<string | undefined>(undefined);
  const [currentStock, setCurrentStock] = useState<StockTarget>(() => getPersistedStock() ?? STOCK_UNIVERSE[0]);
  const [activePeriod, setActivePeriod] = useState<KlinePeriod>('日K');
  const [customFrequency, setCustomFrequency] = useState<CustomKlineFrequency>('1d');
  const [customLimit, setCustomLimit] = useState('120');
  const [activePanelTab, setActivePanelTab] = useState<PanelTabId>('news');
  const [chartData, setChartData] = useState(() => generateKlineData(40, currentStock.startPrice));
  // K 线渲染模式:专业(Lightweight Charts)↔ 经典(recharts 自绘)。只增不替。
  const [klineRenderer, setKlineRenderer] = useState<'pro' | 'classic'>('pro');
  const [analysisMode, setAnalysisMode] = useState<AnalysisModeId>('standard');
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [autoEvidence, setAutoEvidence] = useState(true);
  const [strictRisk, setStrictRisk] = useState(true);
  const [lastUploadedFile, setLastUploadedFile] = useState('');
  const [chatProviders, setChatProviders] = useState<ModelProvider[]>([]);
  const [selectedChatModelKey, setSelectedChatModelKey] = useState('');
  const [conversationId, setConversationId] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatStatus, setChatStatus] = useState('正在读取系统设置中的模型配置...');
  const [latestQuote, setLatestQuote] = useState<WorkbenchChartPoint | undefined>();
  const [hoveredChartPoint, setHoveredChartPoint] = useState<WorkbenchChartPoint | undefined>();
  const [priceStatus, setPriceStatus] = useState<'loading' | 'live' | 'degraded'>('loading');
  const [priceMessage, setPriceMessage] = useState('正在同步行情...');
  const [priceRefreshKey, setPriceRefreshKey] = useState(0);
  const [financeCards, setFinanceCards] = useState<MetricCard[]>(LOADING_FINANCE_CARDS);
  const [fundFlowCards, setFundFlowCards] = useState<MetricCard[]>(LOADING_FUND_CARDS);
  const [quantCards, setQuantCards] = useState<MetricCard[]>(LOADING_QUANT_CARDS);
  const [stockNews, setStockNews] = useState<PanelNewsItem[]>([]);
  const [infoStatus, setInfoStatus] = useState<Record<PanelTabId, string>>({
    news: '正在同步当前标的资讯...',
    finance: '正在同步基本面数据...',
    funds: '正在同步主力资金...',
    quant: '正在计算量化因子...',
  });
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'agent',
      agentName: 'System',
      content: `欢迎使用研策中枢 AlphaScope 多 Agent 分析工作台。当前标的：**${currentStock.name}** (${currentStock.symbol})。请选择分析模式并输入问题。`,
      timestamp: new Date().toISOString(),
    }
  ]);
  const [input, setInput] = useState('');
  const fallbackPrice = currentStock.startPrice;
  const selectedMode = ANALYSIS_MODES.find((mode) => mode.id === analysisMode) ?? ANALYSIS_MODES[0];
  const chatModelOptions = useMemo(() => buildModelOptions(chatProviders, 'chat'), [chatProviders]);
  const selectedChatModel = useMemo(
    () => chatModelOptions.find((option) => option.key === selectedChatModelKey) ?? chatModelOptions[0],
    [chatModelOptions, selectedChatModelKey],
  );
  const customLimitOptions = useMemo(() => getCustomLimitOptions(customFrequency), [customFrequency]);
  const activePeriodConfig = useMemo(
    () => getPeriodConfig(activePeriod, customFrequency, customLimit),
    [activePeriod, customFrequency, customLimit],
  );
  const activePeriodLabel = activePeriodConfig.label;
  const axisPeriod = activePeriodConfig.axisPeriod;
  const canSendChat = Boolean(input.trim() && selectedChatModel && !chatLoading);
  const chartLastPoint = chartData[chartData.length - 1];
  const lastChartPoint = activePeriodConfig.frequency === 'intraday' ? (latestQuote ?? chartLastPoint) : chartLastPoint;
  const displayPrice = lastChartPoint?.close ?? fallbackPrice;
  const displayChange = lastChartPoint?.changePct ?? 0;
  const displayIsUp = displayChange >= 0;
  const isPeriodDataTooShort = chartData.length > 0 && chartData.length < getMinimumPeriodBars(activePeriodConfig.frequency);
  const chartStats = useMemo(() => {
    const lastPoint = chartData[chartData.length - 1];
    const ma5 = lastPoint?.ma5 ?? fallbackPrice;
    const ma10 = lastPoint?.ma10 ?? fallbackPrice;
    const ma20 = lastPoint?.ma20 ?? fallbackPrice;
    const values = chartData.flatMap((point) => [point.high, point.low, point.ma5, point.ma10, point.ma20]);
    const validValues = values.filter((value) => Number.isFinite(value));
    const max = validValues.length ? Math.max(...validValues) : fallbackPrice;
    const min = validValues.length ? Math.min(...validValues) : fallbackPrice;
    const volume = lastPoint?.volume ?? 0;
    return {
      ma5,
      ma10,
      ma20,
      high: max,
      low: min,
      volume,
    };
  }, [chartData, fallbackPrice]);
  const priceDomain = useMemo(
    () => getWorkbenchPriceDomain(chartData, fallbackPrice),
    [chartData, fallbackPrice],
  );
  const priceSourceLabel = priceStatus === 'live'
    ? `${lastChartPoint?.source || 'provider'} · ${lastChartPoint?.date || ''}`
    : priceMessage;
  const chartSourceLabel = isPeriodDataTooShort
    ? `${activePeriodLabel}样本不足，仅显示上市以来可用K线`
    : priceSourceLabel;
  const displayChartPoint = hoveredChartPoint ?? lastChartPoint;
  const displayChartPointUp = (displayChartPoint?.change ?? 0) >= 0;
  const showMa5Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 5);
  const showMa10Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 10);
  const showMa20Line = shouldShowMovingAverage(activePeriodConfig.frequency, chartData.length, 20);

  const handleChartMouseMove = (state: any) => {
    const point = state?.activePayload?.find((item: any) => item?.payload)?.payload as WorkbenchChartPoint | undefined;
    if (point) setHoveredChartPoint(point);
  };
  const handlePanelTabChange = (tabId: PanelTabId) => {
    setActivePanelTab(tabId);
  };

  const handlePanelItemSelect = (title: string, detail: string) => {
    appendSystemMessage(`已选中 **${currentStock.name}** 的信息卡片：**${title}**。\n${detail}\n\n下一步建议：把该信息与公告、价格行为、资金流和证据链进行交叉核验。`);
  };

  const appendSystemMessage = (content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `system-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        role: 'agent',
        agentName: 'System',
        content,
        timestamp: new Date().toISOString(),
      },
    ]);
  };

  const [providersReloadKey, setProvidersReloadKey] = useState(0);
  useEffect(() => {
    const unsub = subscribeSettingsChanged(() => setProvidersReloadKey((k) => k + 1));
    return unsub;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadChatProviders() {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const providers = result.providers || [];
        const options = buildModelOptions(providers, 'chat');
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        const chatRoute = getRouteSelection(routes, providers, 'chat');
        const routeKey = getModelKey(chatRoute);
        setChatProviders(providers);
        setSelectedChatModelKey((current) => (
          current && options.some((option) => option.key === current)
            ? current
            : routeKey && options.some((option) => option.key === routeKey)
              ? routeKey
              : options[0]
                ? options[0].key
              : ''
        ));
        setChatStatus(
          options.length
            ? `已连接系统设置 Provider，共 ${options.length} 个可用聊天模型`
            : '没有可用聊天模型，请先到系统设置添加 Provider 并获取模型列表',
        );
      } catch (error) {
        if (cancelled) return;
        setChatProviders([]);
        setSelectedChatModelKey('');
        setChatStatus(`模型配置读取失败：${getErrorMessage(error)}`);
      }
    }

    loadChatProviders();
    return () => {
      cancelled = true;
    };
  }, [providersReloadKey]);

  useEffect(() => {
    return subscribeStockSelected(({ stock }) => {
      const resolved = stock.resolved || stock.source === 'backend'
        ? stock
        : findStockTarget(stock.symbol) ?? stock;
      setCurrentStock(resolved);
      setMessages((prev) => [
        ...prev.map((msg) => msg.id === 'welcome'
          ? {
              ...msg,
              content: `欢迎使用研策中枢 AlphaScope 多 Agent 分析工作台。当前标的：**${resolved.name}** (${resolved.symbol})。请选择分析模式并输入问题。`,
            }
          : msg),
        {
          id: `stock-${Date.now()}`,
          role: 'agent',
          agentName: 'System',
          content: `已切换研究标的：**${resolved.name}** (${resolved.symbol})。行情、资金与多 Agent 分析上下文已同步。`,
          timestamp: new Date().toISOString(),
        },
      ]);
    });
  }, []);

  useEffect(() => {
    if (currentStock.resolved || currentStock.source === 'backend') return;
    let cancelled = false;
    const code = stripSymbolSuffix(currentStock.symbol);
    void resolveStockTarget(code).then((resolved) => {
      if (cancelled || !resolved) return;
      if (resolved.symbol !== currentStock.symbol || resolved.name !== currentStock.name || resolved.source !== currentStock.source || resolved.resolved !== currentStock.resolved) {
        setCurrentStock(resolved);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [currentStock]);

  useEffect(() => {
    if (customLimitOptions.some((option) => option.value === customLimit)) return;
    setCustomLimit(customLimitOptions[1]?.value ?? customLimitOptions[0]?.value ?? '120');
  }, [customLimit, customLimitOptions]);

  useEffect(() => {
    let cancelled = false;
    const period = activePeriodConfig;
    const fallback = generateKlineData(period.points, currentStock.startPrice, period.stepDays, period.stepMinutes ?? 0);
    const chartPeriodKey = [
      currentStock.symbol,
      period.frequency,
      period.limit,
      period.points,
      period.stepDays,
      period.stepMinutes ?? 0,
    ].join('|');
    if (previousChartPeriodKeyRef.current !== chartPeriodKey) {
      previousChartPeriodKeyRef.current = chartPeriodKey;
      setChartData(fallback);
      setHoveredChartPoint(undefined);
      if (period.frequency !== 'intraday') {
        setLatestQuote(undefined);
      }
    }

    async function loadPrices() {
      setPriceStatus('loading');
      setPriceMessage('正在同步真实行情...');
      try {
        const symbol = encodeURIComponent(stripSymbolSuffix(currentStock.symbol));
        const payload = await fetchApi<PriceSeriesResponse>(
          `/api/prices/${symbol}?frequency=${period.frequency}&limit=${period.limit}`,
        );
        if (cancelled) return;
        const nextData = payload.bars?.length ? enrichWorkbenchData(payload.bars) : fallback;
        let nextQuote = nextData[nextData.length - 1];
        if (period.frequency === 'intraday') {
          try {
            const latest = await fetchApi<PriceBar>(`/api/prices/${symbol}/latest`);
            if (!cancelled && latest?.close) {
              nextQuote = enrichWorkbenchData([latest])[0];
              nextQuote.changePct = Number((latest.change_pct || nextQuote.changePct || 0).toFixed(2));
              setLatestQuote(nextQuote);
            }
          } catch {
            if (!cancelled) setLatestQuote(nextQuote);
          }
        } else {
          setLatestQuote(undefined);
        }
        if (cancelled) return;
        setChartData(nextData);
        if (payload.bars?.length) {
          setPriceStatus(payload.degraded ? 'degraded' : 'live');
          setPriceMessage(formatPricePayloadMessage(payload, activePeriodLabel));
        } else {
          setPriceStatus('degraded');
          setPriceMessage('行情源暂无数据，已切换本地预览');
          setLatestQuote(undefined);
        }
      } catch (error) {
        if (cancelled) return;
        setChartData(fallback);
        setLatestQuote(undefined);
        setPriceStatus('degraded');
        setPriceMessage(error instanceof Error ? error.message : '行情获取失败，已切换本地预览');
      }
    }

    void loadPrices();
    return () => {
      cancelled = true;
    };
  }, [activePeriodConfig, activePeriodLabel, currentStock, priceRefreshKey]);

  useEffect(() => {
    let cancelled = false;
    const symbol = encodeURIComponent(stripSymbolSuffix(currentStock.symbol));
    const stockName = encodeURIComponent(currentStock.name);

    setFinanceCards(LOADING_FINANCE_CARDS);
    setFundFlowCards(LOADING_FUND_CARDS);
    setQuantCards(LOADING_QUANT_CARDS);
    setStockNews([]);
    setInfoStatus({
      news: `正在同步 ${currentStock.name} 的资讯...`,
      finance: `正在同步 ${currentStock.name} 的基本面...`,
      funds: `正在同步 ${currentStock.name} 的主力资金...`,
      quant: `正在计算 ${currentStock.name} 的量化因子...`,
    });

    async function loadInformationPanels() {
      const [newsResult, fundamentalsResult, fundFlowResult, factorResult] = await Promise.allSettled([
        fetchApi<NewsListResponse>(`/api/news?symbol=${symbol}&limit=6`),
        fetchApi<FundamentalsResponse>(`/api/fundamentals/${symbol}`),
        fetchApi<FundFlowResponse>(`/api/fund-flow/${symbol}?days=30`),
        fetchApi<FactorResponse>(`/api/factors/${symbol}?stock_name=${stockName}&days=30`),
      ]);

      if (cancelled) return;

      if (newsResult.status === 'fulfilled') {
        const items = buildNewsItems(newsResult.value);
        setStockNews(items);
        setInfoStatus((prev) => ({
          ...prev,
          news: items.length
            ? `${sourceStatusLabel(newsResult.value.source_status, newsResult.value.degraded)} · ${items.length} 条资讯`
            : `${sourceStatusLabel(newsResult.value.source_status || 'empty', true)} · 当前标的暂无可用资讯`,
        }));
      } else {
        setStockNews([]);
        setInfoStatus((prev) => ({
          ...prev,
          news: `资讯源不可用：${getErrorMessage(newsResult.reason)}`,
        }));
      }

      if (fundamentalsResult.status === 'fulfilled') {
        const payload = fundamentalsResult.value;
        setFinanceCards(buildFinanceCards(payload));
        const period = payload.financial_periods?.[0]?.period;
        setInfoStatus((prev) => ({
          ...prev,
          finance: `${sourceStatusLabel(payload.source_status, payload.degraded)}${period ? ` · 报告期 ${period}` : ''}`,
        }));
      } else {
        setFinanceCards(emptyCards(getErrorMessage(fundamentalsResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          finance: `基本面源不可用：${getErrorMessage(fundamentalsResult.reason)}`,
        }));
      }

      if (fundFlowResult.status === 'fulfilled') {
        const payload = fundFlowResult.value;
        setFundFlowCards(buildFundFlowCards(payload));
        const lastDate = payload.summary?.last_date;
        setInfoStatus((prev) => ({
          ...prev,
          funds: `${sourceStatusLabel(payload.source_status, payload.degraded)} · ${payload.source || 'eastmoney'}${lastDate ? ` · ${lastDate}` : ''}`,
        }));
      } else {
        setFundFlowCards(emptyCards(getErrorMessage(fundFlowResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          funds: `资金源不可用：${getErrorMessage(fundFlowResult.reason)}`,
        }));
      }

      if (factorResult.status === 'fulfilled') {
        const payload = factorResult.value;
        setQuantCards(buildQuantCards(payload));
        const degradedText = payload.degraded_inputs?.length
          ? ` · 降级输入 ${payload.degraded_inputs.join(', ')}`
          : '';
        setInfoStatus((prev) => ({
          ...prev,
          quant: `近30日因子 · ${payload.computed_at?.slice(0, 19).replace('T', ' ') || '已计算'}${degradedText}`,
        }));
      } else {
        setQuantCards(emptyCards(getErrorMessage(factorResult.reason)));
        setInfoStatus((prev) => ({
          ...prev,
          quant: `因子计算失败：${getErrorMessage(factorResult.reason)}`,
        }));
      }
    }

    void loadInformationPanels();
    return () => {
      cancelled = true;
    };
  }, [currentStock, priceRefreshKey]);

  const handlePeriodChange = (period: KlinePeriod) => {
    setActivePeriod(period);
  };

  const handleModeChange = (mode: AnalysisModeId) => {
    const nextMode = ANALYSIS_MODES.find((item) => item.id === mode) ?? ANALYSIS_MODES[0];
    setAnalysisMode(mode);
    setModeMenuOpen(false);
    appendSystemMessage(`分析模式已切换为 **${nextMode.label}**。\n${nextMode.desc}。`);
  };

  const handleRefreshChart = () => {
    setPriceRefreshKey((value) => value + 1);
    appendSystemMessage(`已刷新 **${currentStock.name}** (${currentStock.symbol}) 的${activePeriodLabel}行情，并同步更新均线、成交量与资金标签。`);
  };

  const handleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        appendSystemMessage('已退出全屏研究模式。');
      } else {
        await document.documentElement.requestFullscreen();
        appendSystemMessage('已进入全屏研究模式，适合进行盘中盯盘或投研展示。');
      }
    } catch {
      appendSystemMessage('当前浏览器未允许全屏切换，请检查浏览器权限或手动使用 F11。');
    }
  };

  const handleUploadContext = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      appendSystemMessage(`正在上传 **${file.name}** 到知识库，请稍候...`);
      const formData = new FormData();
      formData.append('file', file);
      const headers = new Headers();
      if (API_KEY) {
        headers.set('X-API-Key', API_KEY);
      }
      if (LOCAL_API_TOKEN) {
        headers.set('X-AlphaScope-Local-Token', LOCAL_API_TOKEN);
      }

      const response = await fetch(`${API_BASE_URL}/api/knowledge/upload`, {
        method: 'POST',
        headers,
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error || `HTTP ${response.status} ${response.statusText}`);
      }

      const uploadedName = payload?.data?.filename || file.name;
      setLastUploadedFile(uploadedName);
      appendSystemMessage(`已上传并索引：**${uploadedName}**。\n${payload?.message || '文件上传并处理成功'}`);
    } catch (error) {
      appendSystemMessage(`知识库上传失败：**${file.name}**\n${getErrorMessage(error)}`);
    } finally {
      event.target.value = '';
    }
  };

  const handleSend = async () => {
    const prompt = input.trim();
    if (!prompt || chatLoading) return;

    if (!selectedChatModel) {
      appendSystemMessage('当前没有可用聊天模型。请先到系统设置中添加 Provider、检查连通性并获取模型列表。');
      return;
    }

    const now = Date.now();
    const userMsg: ChatMessage = {
      id: `user-${now}`,
      role: 'user',
      content: prompt,
      timestamp: new Date().toISOString(),
    };
    const pendingId = `assistant-pending-${now}`;
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: 'agent',
      agentName: `${selectedChatModel.providerName}/${selectedChatModel.modelId}`,
      content: `正在调用真实模型：**${selectedChatModel.providerName} / ${selectedChatModel.modelId}**\n\n已注入当前标的、行情沙盘、资金和分析模式上下文。`,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setInput('');
    setChatLoading(true);
    setChatStatus(`正在调用 ${selectedChatModel.providerName} / ${selectedChatModel.modelId}...`);

    try {
      const result = await fetchApi<ChatResponse>('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          conversation_id: conversationId || undefined,
          message: prompt,
          mode: 'free',
          stock_symbol: currentStock.symbol,
          stock_name: currentStock.name,
          provider: selectedChatModel.providerId,
          model: selectedChatModel.modelId,
          context: {
            close: displayPrice,
            day_change: displayChange,
            period_change: displayChange,
            ma5: Number(chartStats.ma5.toFixed(2)),
            ma20: Number(chartStats.ma20.toFixed(2)),
            ma60: Number(chartStats.ma20.toFixed(2)),
            fund_dir: fundFlowCards.map((item) => `${item.label}: ${item.value}`).join('；'),
            fundamentals: financeCards.map((item) => `${item.label}: ${item.value} (${item.detail})`).join('；'),
            factor_context: quantCards.map((item) => `${item.label}: ${item.value} (${item.detail})`).join('；'),
            data_date: new Date().toLocaleDateString('zh-CN'),
            analysis_mode: selectedMode.label,
            auto_evidence: autoEvidence,
            strict_risk: strictRisk,
          },
        }),
      });

      if (result.conversation_id) {
        setConversationId(result.conversation_id);
      }

      const responseProvider = result.provider || selectedChatModel.providerId;
      const responseModel = result.model || selectedChatModel.modelId;
      const modelLine = `模型调用：**${responseProvider} / ${responseModel}**`;
      const content = result.content?.trim()
        ? `${modelLine}\n\n${result.content.trim()}`
        : `${modelLine}\n\n模型没有返回内容。请检查该 Provider 的模型权限、余额或 Base URL。`;

      setMessages((prev) => prev.map((msg) => (
        msg.id === pendingId
          ? {
              ...msg,
              agentName: `${responseProvider}/${responseModel}`,
              content,
              timestamp: new Date().toISOString(),
            }
          : msg
      )));
      setChatStatus(`上次调用成功：${responseProvider} / ${responseModel}`);
    } catch (error) {
      const message = getErrorMessage(error);
      setMessages((prev) => prev.map((msg) => (
        msg.id === pendingId
          ? {
              ...msg,
              agentName: '模型调用失败',
              content: `模型调用失败：${message}\n\n这不是模拟回复。请检查系统设置中的 Provider、Base URL、API Key、模型名称和网络连通性。`,
              timestamp: new Date().toISOString(),
            }
          : msg
      )));
      setChatStatus(`模型调用失败：${message}`);
    } finally {
      setChatLoading(false);
    }
  };
  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="mx-auto max-w-[1600px] p-6 text-neutral-300 lg:p-8"
    >
      {/* Top Header */}
      <div className="relative z-10 mb-8 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="mb-3 flex min-w-0 flex-wrap items-center gap-3 text-2xl font-medium tracking-tight text-white sm:text-3xl">
            {currentStock.name}
            <span className="shrink-0 rounded border border-white/10 bg-white/[0.04] px-2.5 py-1 font-mono text-xs font-medium tracking-wider text-neutral-300">{currentStock.symbol}</span>
          </h1>
          <div className={cn('flex min-w-0 flex-wrap items-baseline gap-3', displayIsUp ? 'text-rose-500' : 'text-emerald-500')}>
            <span className={cn('font-mono text-3xl font-medium tracking-tight sm:text-4xl', displayIsUp ? 'drop-shadow-[0_0_15px_rgba(244,63,94,0.3)]' : 'drop-shadow-[0_0_15px_rgba(16,185,129,0.25)]')}>
              {formatPrice(displayPrice)}
            </span>
            <span className={cn('flex items-center rounded border px-2 py-0.5 font-mono text-sm font-medium', displayIsUp ? 'border-rose-500/20 bg-rose-500/10 text-rose-500' : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500')}>
              <span className="rotate-45 mr-1 text-lg leading-none">{displayIsUp ? '↗' : '↘'}</span>{displayIsUp ? '+' : ''}{displayChange.toFixed(2)}%
            </span>
            <span className={cn('max-w-[22rem] truncate rounded border px-2 py-0.5 align-middle font-mono text-[10px]', priceStatus === 'live' ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/20 bg-amber-500/10 text-amber-300')}>
              {priceStatus === 'loading' ? '同步中' : priceSourceLabel}
            </span>
          </div>
        </div>

        <div className="grid w-full grid-cols-2 gap-3 sm:grid-cols-4 md:w-auto md:max-w-[48rem]">
          {financeCards.slice(0, 4).map((item, i) => (
            <div key={`${item.label}-${i}`} title={item.detail} className="flex min-w-0 flex-col rounded-xl border border-white/5 bg-white/[0.03] px-4 py-3 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:bg-white/[0.05]">
              <span className="mb-1.5 truncate text-xs text-neutral-500">{item.label}</span>
              <span className={cn("truncate text-sm font-mono font-medium tracking-wide", metricToneClass(item.tone))}>
                {item.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8 relative z-10">
        {/* Left Column: Chart & Info */}
        <div className="xl:col-span-2 flex flex-col gap-8">
          {/* Chart Panel */}
          <div className="flex h-[500px] min-h-0 flex-col overflow-hidden rounded-2xl border border-white/5 bg-white/[0.04] shadow-2xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-white/[0.01] px-5 py-4">
              <div className="flex items-center gap-3">
                 <h2 className="font-semibold text-neutral-200">行情走势</h2>
                 <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-[pulse_2s_ease-in-out_infinite] shadow-[0_0_5px_rgba(16,185,129,0.5)]"></span>
                 <span className="hidden max-w-[18rem] truncate rounded border border-white/10 bg-black/30 px-2 py-0.5 font-mono text-[10px] text-neutral-500 sm:inline">
                   {priceStatus === 'loading' ? '正在同步行情' : chartSourceLabel}
                 </span>
              </div>
              <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRefreshChart}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/40 text-neutral-400 transition-colors hover:bg-white/[0.05] hover:text-neutral-200"
                title="刷新行情"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', priceStatus === 'loading' && 'animate-spin')} />
              </button>
              <div className="flex flex-wrap rounded-lg border border-white/5 bg-black/40 p-1 shadow-inner">
                {PERIOD_BUTTONS.map((period) => (
                  <button 
                    key={period}
                    data-testid={getPeriodTestId(period)}
                    onClick={() => handlePeriodChange(period)}
                    className={cn(
                      "px-3 py-1.5 text-xs rounded-md font-medium transition-all cursor-pointer sm:px-5",
                      activePeriod === period ? "bg-white/10 text-white shadow-sm border border-white/10" : "text-neutral-500 hover:text-neutral-300 border border-transparent"
                    )}
                  >
                    {period}
                  </button>
                ))}
              </div>
              {activePeriod === '自定义' && (
                <div className="flex items-center gap-2 rounded-lg border border-white/5 bg-black/40 p-1 shadow-inner">
                  <ThemedSelect
                    value={customFrequency}
                    options={CUSTOM_FREQUENCY_OPTIONS}
                    onChange={(value) => setCustomFrequency(value as CustomKlineFrequency)}
                    ariaLabel="自定义K线粒度"
                    testId="workbench-custom-frequency"
                    className="w-[86px]"
                    buttonClassName="h-8 rounded-md border-transparent bg-transparent px-2 text-xs"
                    menuClassName="text-xs"
                    align="right"
                  />
                  <ThemedSelect
                    value={customLimit}
                    options={customLimitOptions}
                    onChange={setCustomLimit}
                    ariaLabel="自定义K线窗口"
                    testId="workbench-custom-limit"
                    className="w-[86px]"
                    buttonClassName="h-8 rounded-md border-transparent bg-transparent px-2 text-xs"
                    menuClassName="text-xs"
                    align="right"
                  />
                </div>
              )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/5 bg-black/20 px-5 py-3 font-mono text-[11px]">
               <span className={cn('flex items-center gap-2', showMa5Line ? 'text-yellow-500/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa5Line ? 'bg-yellow-500/90' : 'bg-neutral-700')}></div>MA5: {showMa5Line ? formatPrice(chartStats.ma5) : '--'}</span>
               <span className={cn('flex items-center gap-2', showMa10Line ? 'text-indigo-400/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa10Line ? 'bg-indigo-400/90' : 'bg-neutral-700')}></div>MA10: {showMa10Line ? formatPrice(chartStats.ma10) : '--'}</span>
               <span className={cn('flex items-center gap-2', showMa20Line ? 'text-emerald-400/90' : 'text-neutral-600')}><div className={cn('h-0.5 w-2', showMa20Line ? 'bg-emerald-400/90' : 'bg-neutral-700')}></div>MA20: {showMa20Line ? formatPrice(chartStats.ma20) : '--'}</span>
               <div className="flex rounded-md border border-white/5 bg-black/30 p-0.5" title="K线渲染模式">
                 {([['pro', '专业'], ['classic', '经典']] as Array<['pro' | 'classic', string]>).map(([mode, label]) => (
                   <button
                     key={mode}
                     onClick={() => setKlineRenderer(mode)}
                     className={cn('rounded px-2 py-0.5 text-[10px]', klineRenderer === mode ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
                   >
                     {label}
                   </button>
                 ))}
               </div>
               {displayChartPoint && (
                 <span className="min-w-0 truncate rounded border border-white/10 bg-white/[0.03] px-2 py-1 text-neutral-400">
                   {displayChartPoint.date} · 收 {formatPrice(displayChartPoint.close)} · <span className={displayChartPointUp ? 'text-rose-400' : 'text-emerald-400'}>{displayChartPointUp ? '+' : ''}{displayChartPoint.changePct.toFixed(2)}%</span>
                 </span>
               )}
               {isPeriodDataTooShort && (
                 <span className="min-w-0 truncate rounded border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-amber-300">
                   {activePeriodLabel}样本不足：仅 {chartData.length} 根，可能是新股或行情源历史较短
                 </span>
               )}
               <span className="text-neutral-500 sm:ml-auto">VOL: {formatVolume(chartStats.volume)}</span>
            </div>

            {/* Chart Area */}
            <motion.div
              key={`kline-${currentStock.symbol}-${activePeriodConfig?.label}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, ease: 'easeOut' }}
              className="relative h-[360px] min-h-[320px] bg-black/40 p-5"
            >
               <div className="pointer-events-none absolute right-6 top-6 text-[10px] font-mono text-neutral-600">{formatPrice(chartStats.high)}</div>
               <div className="pointer-events-none absolute right-6 bottom-24 text-[10px] font-mono text-neutral-600">{formatPrice(chartStats.low)}</div>

             <div className="h-[calc(100%-72px)] min-h-[240px]">
               {klineRenderer === 'pro' ? (
                 <Suspense fallback={<div className="flex h-full items-center justify-center text-xs text-neutral-600">专业K线加载中…</div>}>
                   <LightweightKLine data={chartData} showMa5={showMa5Line} showMa10={showMa10Line} showMa20={showMa20Line} />
                 </Suspense>
               ) : (
               <StableChartContainer>
                 <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }} onMouseMove={handleChartMouseMove}>
                   <CartesianGrid stroke="#ffffff" strokeOpacity={0.03} strokeDasharray="4 4" vertical={false} />
                   <XAxis dataKey="date" tickFormatter={(value) => formatAxisDate(String(value), axisPeriod)} hide />
                   <YAxis domain={priceDomain} hide />
                   <Tooltip
                     content={<CompactWorkbenchTooltip />}
                     offset={0}
                     allowEscapeViewBox={{ x: true, y: true }}
                     wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                     cursor={{ stroke: '#818cf8', strokeOpacity: 0.32, strokeWidth: 1 }}
                   />
                   {/* K线蜡烛点数多、逐点 rAF 重排最贵 -> 关闭逐点动画，
                       整图由外层 motion.div 的 GPU opacity/transform 一次性淡入 */}
                   <Bar dataKey="wickRange" barSize={9} shape={<WorkbenchCandlestick />} isAnimationActive={false}>
                      {chartData.map((entry, index) => (
                        <Cell key={`candle-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} />
                      ))}
                   </Bar>
                   {showMa5Line && <Line type="monotone" dataKey="ma5" stroke="#eab308" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                   {showMa10Line && <Line type="monotone" dataKey="ma10" stroke="#818cf8" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                   {showMa20Line && <Line type="monotone" dataKey="ma20" stroke="#34d399" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                 </ComposedChart>
               </StableChartContainer>
               )}
             </div>

             <div className="h-[72px]">
               <StableChartContainer>
                 <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                   <XAxis dataKey="date" tickFormatter={(value) => formatAxisDate(String(value), axisPeriod)} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" minTickGap={22} />
                   <Tooltip
                     content={<WorkbenchChartTooltip />}
                     offset={0}
                     allowEscapeViewBox={{ x: true, y: true }}
                     wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                     cursor={{ fill: 'rgba(129,140,248,0.08)' }}
                   />
                   {/* 成交量柱：点数中等，用 recharts 默认 400ms 动画即可，够快也够顺 */}
                   <Bar dataKey="volume" barSize={4} radius={[2, 2, 0, 0]}>
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-vol-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} fillOpacity={0.4} />
                      ))}
                   </Bar>
                 </ComposedChart>
               </StableChartContainer>
             </div>
            </motion.div>
          </div>
        </div>

        {/* Bottom News/Facts Panel */}
        <div className="bg-white/[0.04] border border-white/5 rounded-2xl overflow-hidden shadow-2xl flex flex-col h-[380px]">
           <div className="flex items-center gap-8 px-6 border-b border-white/5 bg-white/[0.01] pt-1">
             {PANEL_TABS.map((tab) => (
               <button 
                 key={tab.id} 
                 type="button"
                 data-testid={`workbench-info-tab-${tab.id}`}
                 onClick={() => handlePanelTabChange(tab.id)}
                 className={cn(
                 "flex items-center gap-2 py-4 text-xs font-medium border-b-2 transition-colors relative focus:outline-none focus:ring-2 focus:ring-indigo-500/40",
                 activePanelTab === tab.id ? "border-indigo-400 text-indigo-400" : "border-transparent text-neutral-500 hover:text-neutral-300"
               )}>
                 <tab.icon className={cn("w-4 h-4", activePanelTab === tab.id ? "text-indigo-400 drop-shadow-[0_0_5px_rgba(129,140,248,0.5)]" : "text-neutral-600")} />
                 {tab.label}
                 {activePanelTab === tab.id && (
                    <motion.div 
                      layoutId="activeTabIndicator"
                      className="absolute bottom-[-2px] left-0 right-0 h-[2px] bg-indigo-400 shadow-[0_0_10px_rgba(129,140,248,0.8)]"
                    />
                 )}
               </button>
             ))}
           </div>
           <div className="border-b border-white/5 bg-black/30 px-5 py-2 text-[10px] font-mono text-neutral-500">
             {infoStatus[activePanelTab]}
           </div>
           <div className="flex-1 overflow-y-auto p-4 bg-black/40 custom-scrollbar">
             <AnimatePresence mode="wait">
               {activePanelTab === 'news' && (
                 <motion.div 
                   key="news"
                   initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
                 >
                   {stockNews.length === 0 && (
                     <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-100/80">
                       当前标的暂无可用资讯。可在新闻聚合页按股票名称或代码拉取外部新闻；本面板不会再用模板新闻替代真实结果。
                     </div>
                   )}
                   {stockNews.map((news, i) => (
                     <button
                       key={`${news.time}-${news.title}`}
                       type="button"
                       data-testid={`workbench-news-item-${i}`}
                       onClick={() => handlePanelItemSelect(news.title, `${news.detail}。该资讯已关联 ${formatStockLabel(currentStock)}。`)}
                       className="w-full px-4 py-3 text-left border-b border-white/5 hover:bg-white/[0.02] transition-colors cursor-pointer group focus:outline-none focus:bg-indigo-500/[0.04]"
                     >
                       <div className="flex gap-4">
                         <div className="text-[10px] font-mono text-neutral-500 group-hover:text-neutral-400 mt-1 flex items-center gap-2">
                            {news.time}
                         </div>
                         <div className="flex-1">
                           <div className="flex items-center gap-2 mb-1.5">
                             <span className="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20 text-[9px] font-mono uppercase">
                               {news.source}
                             </span>
                             <div className="w-1.5 h-1.5 rounded-full bg-white/10"></div>
                           </div>
                           <h4 className="text-sm text-neutral-200 font-medium leading-relaxed group-hover:text-indigo-300 transition-colors">{news.title}</h4>
                           {news.desc && <p className="text-xs text-neutral-500 mt-1.5 leading-relaxed">{news.desc}</p>}
                         </div>
                       </div>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'finance' && (
                 <motion.div key="finance" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
              {financeCards.map((item, i) => (
                     <button
                       key={item.label}
                       type="button"
                       data-testid={`workbench-finance-card-${i}`}
                       onClick={() => handlePanelItemSelect(item.label, `当前值 ${item.value}。${item.detail}。请结合 ${currentStock.name} 最新财报、行业均值和估值假设复核。`)}
                       className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                       <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>
                         {item.value}
                       </span>
                       <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'funds' && (
                 <motion.div key="funds" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
                   {fundFlowCards.map((item, i) => (
                     <button
                       key={item.label}
                       type="button"
                       data-testid={`workbench-funds-card-${i}`}
                       onClick={() => handlePanelItemSelect(item.label, `${item.label} 当前为 ${item.value}。${item.detail}。资金项需要和换手率、价格方向、龙虎榜/两融数据交叉验证。`)}
                       className="bg-white/[0.03] border border-white/5 p-4 rounded-xl flex flex-col justify-center hover:bg-white/[0.05] transition-colors text-left focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="text-xs text-neutral-500 mb-2">{item.label}</span>
                       <span className={cn("text-2xl font-mono font-medium", metricToneClass(item.tone))}>
                         {item.value}
                       </span>
                       <span className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-neutral-500">{item.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}

               {activePanelTab === 'quant' && (
                 <motion.div key="quant" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="grid h-full grid-cols-2 gap-4 p-4">
                   {quantCards.map((factor, i) => (
                     <button
                       key={factor.label}
                       type="button"
                       data-testid={`workbench-quant-card-${i}`}
                       onClick={() => handlePanelItemSelect(factor.label, `${factor.detail}。该因子当前只作为研究辅助，不构成投资建议。`)}
                       className="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-4 text-left text-indigo-200 transition-colors hover:bg-indigo-500/15 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                     >
                       <span className="block text-[10px] font-mono uppercase tracking-widest text-indigo-300/70">{factor.label}</span>
                       <span className={cn("mt-2 block text-2xl font-mono font-semibold", metricToneClass(factor.tone))}>{factor.value}</span>
                       <span className="mt-2 block text-[11px] leading-relaxed text-indigo-100/65">{factor.detail}</span>
                     </button>
                   ))}
                 </motion.div>
               )}
             </AnimatePresence>
           </div>
        </div>
      </div>

      {/* Right AI Engine Panel */}
      {/* 注意: 此面板不能用 overflow-hidden — 模式选择菜单 (absolute top-8) 会向下弹出
          被 overflow-hidden 裁切, 导致主页「切换不了分析模式」。glow 的 blur 轻微外溢可接受。 */}
      <div className="bg-white/[0.04] border border-white/5 rounded-2xl shadow-[0_8px_30px_rgb(0,0,0,0.12)] flex flex-col h-[912px] sticky top-8 relative">
        {/* Glow effect at top */}
        <div className="absolute top-0 left-0 right-0 h-32 bg-indigo-500/10 blur-[50px] pointer-events-none rounded-2xl overflow-hidden"></div>

        <div className="px-5 py-4 border-b border-white/5 flex justify-between items-center bg-white/[0.01] relative z-30">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600/20 to-indigo-400/20 flex items-center justify-center border border-indigo-400/20 shadow-[0_0_15px_rgba(99,102,241,0.15)]">
              <Sparkles className="w-4 h-4 text-indigo-400" />
            </div>
            <h2 className="font-semibold text-neutral-200 tracking-wide">AI 分析引擎</h2>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                data-testid="workbench-analysis-mode"
                onClick={() => setModeMenuOpen((open) => !open)}
                className="flex items-center gap-1.5 px-2 py-1 text-[11px] rounded border border-white/10 bg-black/40 text-neutral-400 hover:text-white transition-colors"
              >
                <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full shadow-[0_0_5px_rgba(99,102,241,0.5)]"></div>
                {selectedMode.label}
                <ChevronDown className="w-3 h-3 ml-1" />
              </button>
              <AnimatePresence>
                {modeMenuOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: -4, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    className="absolute right-0 top-8 z-50 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#101010] shadow-2xl"
                  >
                    {ANALYSIS_MODES.map((mode) => (
                      <button
                        key={mode.id}
                        type="button"
                        data-testid={`workbench-mode-${mode.id}`}
                        onClick={() => handleModeChange(mode.id)}
                        className={cn(
                          "w-full px-3 py-3 text-left transition-colors",
                          analysisMode === mode.id ? "bg-indigo-500/10" : "hover:bg-white/[0.04]"
                        )}
                      >
                        <span className="block text-xs font-medium text-neutral-100">{mode.label}</span>
                        <span className="mt-1 block text-[10px] leading-relaxed text-neutral-500">{mode.desc}</span>
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <button data-testid="workbench-refresh-chart" onClick={handleRefreshChart} className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors" title="刷新行情沙盘">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <button data-testid="workbench-fullscreen" onClick={handleFullscreen} className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors" title="切换全屏">
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button
              data-testid="workbench-open-model-settings"
              onClick={onOpenModelSettings}
              className="p-1.5 hover:bg-white/5 rounded-md text-neutral-500 transition-colors"
              title="模型路由设置"
            >
              <Bot className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar z-10">
          <AnimatePresence>
            {messages.map(msg => (
              <motion.div 
                key={msg.id} 
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
                className="flex gap-3"
              >
                {msg.role !== 'user' ? (
                  <div className="min-w-0 flex-1 mr-4">
                     <div className="bg-white/[0.06] border border-white/[0.05] rounded-xl rounded-tl-sm p-4 text-sm text-neutral-300 leading-relaxed shadow-[0_4px_15px_rgba(0,0,0,0.1)]">
                       <p dangerouslySetInnerHTML={{ __html: formatMessageHtml(msg.content) }} />
                     </div>
                  </div>
                ) : (
                  <div className="min-w-0 flex-1 ml-12">
                     <div className="bg-gradient-to-br from-indigo-500/25 to-indigo-600/15 border border-indigo-500/30 text-indigo-50 rounded-xl rounded-tr-sm p-4 text-sm leading-relaxed shadow-[0_4px_15px_rgba(99,102,241,0.05)]">
                       {msg.content}
                     </div>
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            transition={{ delay: 1 }} 
            className="flex justify-center my-4 relative z-10"
          >
             <span className="text-[10px] font-mono text-neutral-500 bg-black/60 px-3 py-1 rounded-full border border-white/5">
               [系统] 已切换至 {formatStockLabel(currentStock)}
             </span>
          </motion.div>
        </div>
        
        <div className="p-4 border-t border-white/5 bg-black/40 relative z-10">
          <div className="mb-3 rounded-xl border border-white/10 bg-white/[0.025] px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2 text-xs text-neutral-300">
                <Bot className="h-4 w-4 shrink-0 text-indigo-300" />
                <span className="shrink-0 font-medium text-neutral-100">真实模型</span>
                <span className="truncate font-mono text-[11px] text-neutral-500">{chatStatus}</span>
              </div>
              <button
                type="button"
                onClick={onOpenModelSettings}
                className="rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-[10px] text-neutral-400 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
              >
                设置
              </button>
              <ThemedSelect
                data-testid="workbench-chat-model-select"
                value={selectedChatModel?.key || ''}
                onChange={setSelectedChatModelKey}
                disabled={!chatModelOptions.length || chatLoading}
                className="min-w-[220px]"
                buttonClassName="h-8 rounded-lg bg-black/50 px-2 text-xs"
                menuClassName="text-xs"
                options={chatModelOptions.length ? chatModelOptions.map((option) => ({
                  value: option.key,
                  label: `${option.providerName} / ${option.modelId}${option.vision ? ' · 视觉' : ''}`,
                  badge: option.vision ? <span className="rounded-full bg-indigo-400/10 px-1.5 py-0.5 text-[9px] text-indigo-200">视觉</span> : undefined,
                })) : [{ value: '', label: '请先在系统设置获取模型列表', disabled: true }]}
              />
            </div>
          </div>
          <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden shadow-inner focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/50 transition-all">
            <textarea 
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={`对 ${currentStock.name} 提出分析需求...`} 
              className="w-full bg-transparent p-4 text-sm focus:outline-none text-neutral-200 placeholder:text-neutral-500 resize-none h-24 custom-scrollbar"
            />
            <div className="flex justify-between items-center px-3 pb-3">
              <div className="flex gap-1.5">
                <input ref={fileInputRef} type="file" accept="image/*,.pdf,.txt,.md,.csv" onChange={handleUploadContext} className="hidden" />
                <button
                  data-testid="workbench-upload-context"
                  onClick={() => fileInputRef.current?.click()}
                  title="多模态分析 (上传 K 线截图或本地研报)"
                  className="p-1.5 text-neutral-500 hover:text-indigo-400 hover:bg-indigo-500/10 rounded-md transition-colors"
                >
                  <ImagePlus className="w-4.5 h-4.5" />
                </button>
                <button
                  data-testid="workbench-analysis-settings"
                  onClick={() => setSettingsOpen((open) => !open)}
                  title="分析配置"
                  className="p-1.5 text-neutral-500 hover:text-neutral-300 rounded-md hover:bg-white/5 transition-colors"
                >
                  <Settings2 className="w-4.5 h-4.5" />
                </button>
              </div>
              <div className="flex items-center gap-4 text-[10px] font-mono text-neutral-500">
                <span>ENTER 发送 • SHIFT+ENTER 换行</span>
                <button 
                  onClick={handleSend}
                  disabled={!canSendChat}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 text-white rounded-lg border border-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.4)] transition-all",
                    canSendChat ? "bg-indigo-600 hover:bg-indigo-500" : "cursor-not-allowed bg-neutral-800 text-neutral-500 border-white/10 shadow-none"
                  )}
                >
                  {chatLoading ? '调用中' : '发送'}
                  {chatLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>
          <AnimatePresence>
            {settingsOpen && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                className="mt-3 rounded-xl border border-white/10 bg-black/35 p-3 text-xs text-neutral-400"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="font-medium text-neutral-200">本次分析配置</span>
                  <span className="font-mono text-[10px] text-indigo-300">{selectedMode.label}</span>
                </div>
                <label className="mb-2 flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-white/[0.03] px-3 py-2">
                  <span>自动附带证据链引用</span>
                  <input type="checkbox" checked={autoEvidence} onChange={() => setAutoEvidence((value) => !value)} />
                </label>
                <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg bg-white/[0.03] px-3 py-2">
                  <span>风险事件优先进入摘要</span>
                  <input type="checkbox" checked={strictRisk} onChange={() => setStrictRisk((value) => !value)} />
                </label>
                {lastUploadedFile && (
                  <p className="mt-3 rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-2 text-[11px] text-indigo-100/80">
                    已加载材料：{lastUploadedFile}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
