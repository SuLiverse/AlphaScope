import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Download,
  Eye,
  FileImage,
  ImagePlus,
  LineChart as LineChartIcon,
  RefreshCw,
  SearchCheck,
  Settings2,
  Sparkles,
  Upload,
} from 'lucide-react';
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cn } from '../lib/utils';
import { STOCK_UNIVERSE, StockTarget, findStockTarget, formatStockLabel } from '../lib/stocks';
import { dispatchStockSelected, getPersistedStock, subscribeStockSelected, subscribeSettingsChanged } from '../lib/workspaceEvents';
import { fetchApi } from '../lib/api';
import {
  buildModelOptions,
  getModelKey,
  getRouteSelection,
  loadAiModelRoutesFromApi,
  loadLocalAiModelRoutes,
  ModelOption,
  ModelProvider,
} from '../lib/aiModelRouting';
import { StableChartContainer } from './StableChartContainer';
import { ThemedSelect } from './ThemedSelect';
import { LightweightKLine, type KLineMarker } from './LightweightKLine';

type ChartTab = 'vision' | 'kline';
type Indicator = 'macd' | 'rsi';

interface KLinePoint {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  wickRange: [number, number];
  volume: number;
  amount?: number;
  change: number;
  changePct: number;
  amplitude?: number;
  turnover?: number;
  source?: string;
  frequency?: string;
  fetchedAt?: number;
  up: boolean;
  ma5: number;
  ma20: number;
  macd: number;
  rsi: number;
}

interface VisionSource {
  id: string;
  title: string;
  ticker: string;
  url?: string;
  kind: 'generated' | 'uploaded';
  confidence: number;
  description: string;
  signals: string[];
  assessment: string;
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
  turnover?: number;
  amplitude?: number;
  change_pct?: number;
  previous_close?: number;
  source?: string;
  fetched_at?: number;
}

// ---- K-line pattern recognition contract (backend/quant/patterns.py) ----
interface PatternItem {
  name: string;
  category: string;
  direction: string; // bullish | bearish | neutral
  date: string;
  index: number;
  detail: string;
}

interface PatternData {
  status: string;
  symbol: string;
  bars_used: number;
  patterns: PatternItem[];
  counts: Record<string, number>;
  note?: string;
  disclaimer?: string;
  data_source_label?: string;
}

interface PriceSeriesResponse {
  symbol: string;
  frequency: string;
  bars: PriceBar[];
  total: number;
  degraded?: boolean;
  source_status?: string;
}

interface VisionReportResponse {
  report?: string;
  ticker?: string;
  is_chart?: boolean;
}

interface ChatResponse {
  content?: string;
  provider?: string;
  model?: string;
}

interface UploadedImagePayload {
  base64: string;
  mimeType: string;
  fileName: string;
}

const formatNumber = (value: number, digits = 2) => value.toFixed(digits);

function stripSymbolSuffix(symbol: string) {
  return String(symbol || '').trim().split('.')[0];
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

function formatModelOption(option?: ModelOption) {
  if (!option) return '未配置';
  return `${option.providerName} / ${option.modelId}`;
}

function getKLinePriceDomain(data: KLinePoint[], fallback: number): [number, number] {
  const values = data.flatMap((point) => [
    point.open,
    point.close,
    point.high,
    point.low,
    point.ma5,
    point.ma20,
  ]).filter((value) => Number.isFinite(value));
  const baseValues = values.length ? values : [fallback || 1];
  const min = Math.min(...baseValues);
  const max = Math.max(...baseValues);
  const range = Math.max(max - min, Math.abs(max) * 0.01, 1);
  const padding = Math.max(range * 0.08, 0.01);
  return [Math.max(0, min - padding), max + padding];
}

function formatAxisDate(value: string) {
  const text = String(value || '');
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(5, 10);
  if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(text)) return text.slice(5, 16);
  return text;
}

function mulberry32(seed: number) {
  return () => {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seedFromSymbol(symbol: string) {
  return symbol.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function generateKLineData(stock: StockTarget, points = 48): KLinePoint[] {
  const random = mulberry32(seedFromSymbol(stock.symbol));
  const raw: Omit<KLinePoint, 'ma5' | 'ma20' | 'macd' | 'rsi'>[] = [];
  let open = stock.startPrice;
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - (points - 1));

  for (let i = 0; i < points; i++) {
    const drift = stock.market === 'A股' ? 0.002 : 0.001;
    const swing = (random() - 0.47) * stock.startPrice * 0.035;
    const close = Math.max(0.5, open * (1 + drift) + swing);
    const high = Math.max(open, close) + random() * stock.startPrice * 0.014;
    const low = Math.max(0.1, Math.min(open, close) - random() * stock.startPrice * 0.014);
    const volume = 120000 + Math.round(random() * 950000);
    const date = new Date(startDate);
    date.setDate(startDate.getDate() + i);

    raw.push({
      date: formatLocalDate(date),
      open: Number(open.toFixed(2)),
      close: Number(close.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      wickRange: [Number(low.toFixed(2)), Number(high.toFixed(2))] as [number, number],
      volume,
      change: Number((close - open).toFixed(2)),
      changePct: Number((((close - open) / open) * 100).toFixed(2)),
      source: 'local-preview',
      up: close >= open,
    });
    open = close;
  }

  let ema12 = raw[0].close;
  let ema26 = raw[0].close;
  let dea = 0;

  return raw.map((item, index) => {
    const slice5 = raw.slice(Math.max(0, index - 4), index + 1);
    const slice20 = raw.slice(Math.max(0, index - 19), index + 1);
    const ma5 = slice5.reduce((sum, point) => sum + point.close, 0) / slice5.length;
    const ma20 = slice20.reduce((sum, point) => sum + point.close, 0) / slice20.length;

    if (index > 0) {
      ema12 = item.close * (2 / 13) + ema12 * (11 / 13);
      ema26 = item.close * (2 / 27) + ema26 * (25 / 27);
    }
    const dif = ema12 - ema26;
    dea = index === 0 ? dif : dif * (2 / 10) + dea * (8 / 10);

    const gains = raw.slice(Math.max(1, index - 13), index + 1).map((point, i, arr) => {
      const prev = i === 0 ? raw[Math.max(0, index - arr.length)] : arr[i - 1];
      return Math.max(0, point.close - prev.close);
    });
    const losses = raw.slice(Math.max(1, index - 13), index + 1).map((point, i, arr) => {
      const prev = i === 0 ? raw[Math.max(0, index - arr.length)] : arr[i - 1];
      return Math.max(0, prev.close - point.close);
    });
    const avgGain = gains.reduce((sum, value) => sum + value, 0) / Math.max(1, gains.length);
    const avgLoss = losses.reduce((sum, value) => sum + value, 0) / Math.max(1, losses.length);
    const rsi = avgLoss === 0 ? 78 : 100 - (100 / (1 + avgGain / avgLoss));

    return {
      ...item,
      ma5: Number(ma5.toFixed(2)),
      ma20: Number(ma20.toFixed(2)),
      macd: Number(((dif - dea) * 2).toFixed(2)),
      rsi: Number(rsi.toFixed(2)),
    };
  });
}

function enrichKLineData(rawBars: PriceBar[]): KLinePoint[] {
  const bars = [...rawBars].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  let ema12 = 0;
  let ema26 = 0;
  let dea = 0;
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
    const slice20 = bars.slice(Math.max(0, index - 19), index + 1);
    const ma5 = slice5.reduce((sum, point) => sum + Number(point.close || 0), 0) / Math.max(1, slice5.length);
    const ma20 = slice20.reduce((sum, point) => sum + Number(point.close || 0), 0) / Math.max(1, slice20.length);

    if (index === 0) {
      ema12 = close;
      ema26 = close;
      dea = 0;
    } else {
      ema12 = close * (2 / 13) + ema12 * (11 / 13);
      ema26 = close * (2 / 27) + ema26 * (25 / 27);
    }
    const dif = ema12 - ema26;
    dea = index === 0 ? dif : dif * (2 / 10) + dea * (8 / 10);

    const window = bars.slice(Math.max(1, index - 13), index + 1);
    let gainSum = 0;
    let lossSum = 0;
    window.forEach((point, offset) => {
      const prev = bars[Math.max(0, index - window.length + offset)];
      const delta = Number(point.close || 0) - Number(prev.close || 0);
      gainSum += Math.max(0, delta);
      lossSum += Math.max(0, -delta);
    });
    const avgGain = gainSum / Math.max(1, window.length);
    const avgLoss = lossSum / Math.max(1, window.length);
    const rsi = avgLoss === 0 ? 78 : 100 - (100 / (1 + avgGain / avgLoss));

    return {
      date: String(bar.date || ''),
      open: Number(open.toFixed(2)),
      close: Number(close.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      wickRange: [Number(low.toFixed(2)), Number(high.toFixed(2))],
      volume: Number(bar.volume || 0),
      amount: Number(bar.amount || 0),
      change: Number(change.toFixed(2)),
      changePct: Number(changePct.toFixed(2)),
      amplitude: typeof bar.amplitude === 'number' ? Number(bar.amplitude.toFixed(2)) : undefined,
      turnover: typeof bar.turnover === 'number' ? Number(bar.turnover.toFixed(2)) : undefined,
      source: bar.source,
      fetchedAt: bar.fetched_at,
      up: close >= base,
      ma5: Number(ma5.toFixed(2)),
      ma20: Number(ma20.toFixed(2)),
      macd: Number(((dif - dea) * 2).toFixed(2)),
      rsi: Number(rsi.toFixed(2)),
    };
  });
}

function buildVisionSource(
  stock: StockTarget,
  kind: VisionSource['kind'] = 'generated',
  url?: string,
  fileName?: string,
  chartData: KLinePoint[] = [],
): VisionSource {
  const latest = chartData[chartData.length - 1];
  const prior = chartData[Math.max(0, chartData.length - 2)];
  const hasLiveData = Boolean(latest && latest.source !== 'local-preview');
  const changeText = latest
    ? `${latest.changePct >= 0 ? '+' : ''}${formatNumber(latest.changePct)}%`
    : '待获取';
  return {
    id: `${kind}-${stock.symbol}-${fileName ?? 'kline'}`,
    title: kind === 'uploaded'
      ? `自定义上传图像「${fileName}」`
      : `${stock.name} ${stock.symbol} ${hasLiveData ? '真实行情K线' : '本地预览K线'}`,
    ticker: stock.symbol,
    url,
    kind,
    confidence: kind === 'uploaded' ? 82 : hasLiveData ? 90 : 62,
    description: kind === 'uploaded'
      ? `当前诊断对象为用户上传截图「${fileName}」，标的上下文绑定 ${stock.name} ${stock.symbol}，不会改用右侧选中股票的生成图。`
      : `${stock.name} ${stock.symbol} 当前使用${hasLiveData ? `行情源 ${latest?.source || 'provider'} 的K线数据` : '本地预览数据'}，最新收盘 ${latest ? formatPrice(latest.close) : '--'}，涨跌幅 ${changeText}。`,
    signals: [
      latest ? `最新K线：${latest.date} 收盘 ${formatPrice(latest.close)}，涨跌 ${latest.change >= 0 ? '+' : ''}${formatNumber(latest.change)} / ${changeText}` : '等待行情数据刷新后再输出价格信号',
      latest && prior ? `上一交易日收盘 ${formatPrice(prior.close)}，成交量 ${formatVolume(latest.volume)}` : '上传截图会优先解析图片本身，行情只作为交叉核验',
      stock.market === 'A股' ? '涨跌停、换手率与主题热度会影响次日情绪' : '港股标的需额外关注汇率与南向资金',
    ],
    assessment: kind === 'uploaded'
      ? `本次诊断以上传截图为准，并附带 ${stock.name} (${stock.symbol}) 的行情上下文做交叉检查；如果截图中的标的与当前选择不同，请先切换标的后再诊断。`
      : `${stock.name} 当前更适合做研究辅助判断：先核验价格、资金流和公告，再决定是否进入交易计划。本页面不构成投资建议。`,
  };
}

function getFloatingTooltipStyle(
  coordinate?: { x?: number; y?: number },
  viewBox?: { x?: number; y?: number; width?: number; height?: number },
  size: { width: number; height: number } = { width: 188, height: 188 },
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

function CustomTooltip({ active, payload, label, coordinate, viewBox }: any) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as KLinePoint;
  const isUp = data.change >= 0;
  return (
    <div
      style={getFloatingTooltipStyle(coordinate, viewBox, { width: 150, height: 58 })}
      className="w-[150px] rounded-md border border-indigo-400/20 bg-[#090a10] px-2.5 py-1.5 text-[10px] text-neutral-300 shadow-[0_8px_18px_rgba(0,0,0,0.28)]"
    >
      <div className="flex items-center justify-between gap-3 font-mono">
        <span className="truncate text-neutral-200">{label}</span>
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '+' : ''}{formatNumber(data.changePct)}%
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between border-t border-white/5 pt-1 font-mono">
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '涨' : '跌'} {isUp ? '+' : ''}{formatNumber(data.change)}
        </span>
        <span className="text-neutral-100">{formatPrice(data.close)}</span>
      </div>
    </div>
  );
}

function CompactKLineTooltip({ active, payload, label, coordinate, viewBox }: any) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload as KLinePoint;
  const isUp = data.change >= 0;
  return (
    <div
      style={getFloatingTooltipStyle(coordinate, viewBox, { width: 150, height: 58 })}
      className="w-[150px] rounded-md border border-indigo-400/20 bg-[#090a10] px-2.5 py-1.5 text-[10px] text-neutral-300 shadow-[0_8px_18px_rgba(0,0,0,0.28)]"
    >
      <div className="flex items-center justify-between gap-3 font-mono">
        <span className="truncate text-neutral-200">{label}</span>
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '+' : ''}{formatNumber(data.changePct)}%
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between border-t border-white/5 pt-1 font-mono">
        <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
          {isUp ? '涨' : '跌'} {isUp ? '+' : ''}{formatNumber(data.change)}
        </span>
        <span className="text-neutral-100">{formatPrice(data.close)}</span>
      </div>
    </div>
  );
}

function KLineHoverStrip({ point, mode }: { point?: KLinePoint; mode: string }) {
  if (!point) return null;
  const isUp = point.change >= 0;

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px]">
      <span className="rounded border border-white/10 bg-white/[0.03] px-2 py-1 text-neutral-400">{mode}</span>
      <span className="text-neutral-300">{point.date}</span>
      <span className="text-neutral-500">收盘 <span className="text-neutral-100">{formatPrice(point.close)}</span></span>
      <span className={isUp ? 'text-rose-400' : 'text-emerald-400'}>
        {isUp ? '+' : ''}{formatNumber(point.change)} / {isUp ? '+' : ''}{formatNumber(point.changePct)}%
      </span>
      <span className="text-neutral-500">高 {formatPrice(point.high)}</span>
      <span className="text-neutral-500">低 {formatPrice(point.low)}</span>
    </div>
  );
}

function Candlestick(props: any) {
  const { x, y, width, height, payload } = props;
  const point = payload as KLinePoint | undefined;
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

interface MultimodalChartProps {
  onOpenModelSettings?: () => void;
}

export function MultimodalChart({ onOpenModelSettings }: MultimodalChartProps) {
  const initialStock = getPersistedStock() ?? STOCK_UNIVERSE[0];
  const [selectedStock, setSelectedStock] = useState<StockTarget>(initialStock);
  const [activeTab, setActiveTab] = useState<ChartTab>('vision');
  const [indicator, setIndicator] = useState<Indicator>('macd');
  const [showMA, setShowMA] = useState(true);
  // K 线渲染模式:专业(Lightweight Charts,真缩放/十字光标)↔ 经典(recharts 自绘)。
  const [klineRenderer, setKlineRenderer] = useState<'pro' | 'classic'>('pro');
  // 形态识别(确定性 K 线形态)。
  const [patternData, setPatternData] = useState<PatternData | null>(null);
  const [showPatterns, setShowPatterns] = useState(true);
  const [isDiagnosticRunning, setIsDiagnosticRunning] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadedUrl, setUploadedUrl] = useState<string | undefined>();
  const [uploadedImage, setUploadedImage] = useState<UploadedImagePayload | undefined>();
  const [chartData, setChartData] = useState<KLinePoint[]>(() => generateKLineData(initialStock));
  const [latestQuote, setLatestQuote] = useState<KLinePoint | undefined>();
  const [hoveredKLinePoint, setHoveredKLinePoint] = useState<KLinePoint | undefined>();
  const [priceStatus, setPriceStatus] = useState<'loading' | 'live' | 'degraded'>('loading');
  const [priceMessage, setPriceMessage] = useState('正在获取行情...');
  const [visionSource, setVisionSource] = useState<VisionSource>(() => buildVisionSource(initialStock));
  const [visionReport, setVisionReport] = useState('');
  const [visionError, setVisionError] = useState('');
  const [visionModels, setVisionModels] = useState<ModelOption[]>([]);
  const [reasoningModels, setReasoningModels] = useState<ModelOption[]>([]);
  const [selectedVisionModelKey, setSelectedVisionModelKey] = useState('');
  const [selectedReasoningModelKey, setSelectedReasoningModelKey] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 订阅回调需读最新 chartData/uploadedImage, 但不能让它们进 subscribe 的 deps
  // (否则每次行情刷新都 unsubscribe→resubscribe, 窗口期事件丢失)。用 ref 在 render 同步。
  const chartDataRef = useRef(chartData);
  chartDataRef.current = chartData;
  const uploadedFileNameRef = useRef(uploadedImage?.fileName);
  uploadedFileNameRef.current = uploadedImage?.fileName;

  const selectedVisionModel = useMemo(
    () => visionModels.find((model) => model.key === selectedVisionModelKey) ?? visionModels[0],
    [selectedVisionModelKey, visionModels],
  );
  const selectedReasoningModel = useMemo(
    () => reasoningModels.find((model) => model.key === selectedReasoningModelKey) ?? reasoningModels[0],
    [reasoningModels, selectedReasoningModelKey],
  );
  const selectableStocks = useMemo(
    () => [selectedStock, ...STOCK_UNIVERSE].filter((stock, index, list) => (
      list.findIndex((item) => item.symbol === stock.symbol) === index
    )),
    [selectedStock],
  );
  const lastPoint = latestQuote ?? chartData[chartData.length - 1] ?? generateKLineData(selectedStock, 1)[0];
  const firstPoint = chartData[0] ?? lastPoint;
  const rangeReturn = firstPoint?.open ? ((lastPoint.close - firstPoint.open) / firstPoint.open) * 100 : 0;
  const chartSourceLabel = priceStatus === 'live'
    ? `${lastPoint.source || 'provider'} · ${lastPoint.date}`
    : priceMessage;
  const quoteLabel = latestQuote && latestQuote.frequency === 'intraday'
    ? `分时最新 · ${latestQuote.date}`
    : chartSourceLabel;
  const displayHoverPoint = hoveredKLinePoint ?? lastPoint;

  const handleKLineMouseMove = (state: any) => {
    const point = state?.activePayload?.find((item: any) => item?.payload)?.payload as KLinePoint | undefined;
    if (point) setHoveredKLinePoint(point);
  };

  const priceDomain = useMemo(
    () => getKLinePriceDomain(chartData, selectedStock.startPrice),
    [chartData, selectedStock.startPrice],
  );

  useEffect(() => {
    return subscribeStockSelected(({ stock }) => {
      const resolved = stock.resolved || stock.source === 'backend'
        ? stock
        : findStockTarget(stock.symbol) ?? stock;
      setSelectedStock(resolved);
      // 读 ref 而非闭包变量, 避免 chartData/uploadedImage 进 deps 导致频繁 resubscribe
      setVisionSource((current) => buildVisionSource(resolved, current.kind, current.url, uploadedFileNameRef.current, chartDataRef.current));
      setShowResult(false);
      setActiveTab('vision');
    });
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadPrices() {
      setPriceStatus('loading');
      setPriceMessage('正在获取真实行情...');
      const fallback = generateKLineData(selectedStock);
      try {
        const payload = await fetchApi<PriceSeriesResponse>(
          `/api/prices/${encodeURIComponent(stripSymbolSuffix(selectedStock.symbol))}?frequency=1d&limit=80`,
        );
        if (cancelled) return;
        const nextData = payload.bars?.length ? enrichKLineData(payload.bars) : fallback;
        let nextQuote = nextData[nextData.length - 1];
        try {
          const latest = await fetchApi<PriceBar>(`/api/prices/${encodeURIComponent(stripSymbolSuffix(selectedStock.symbol))}/latest`);
          if (!cancelled && latest?.close) {
            nextQuote = enrichKLineData([latest])[0];
            nextQuote.changePct = Number((latest.change_pct || 0).toFixed(2));
            setLatestQuote(nextQuote);
          }
        } catch {
          if (!cancelled) {
            setLatestQuote(nextQuote);
          }
        }
        if (cancelled) return;
        setChartData(nextData);
        if (payload.bars?.length) {
          setPriceStatus(payload.degraded ? 'degraded' : 'live');
          setPriceMessage(payload.degraded ? '行情源降级，使用可用缓存' : '真实行情已同步');
        } else {
          setPriceStatus('degraded');
          setPriceMessage('行情源暂无数据，已切换本地预览');
        }
        setVisionSource((current) => buildVisionSource(selectedStock, current.kind, current.url, uploadedImage?.fileName, nextData));
      } catch (error) {
        if (cancelled) return;
        setLatestQuote(undefined);
        setChartData(fallback);
        setPriceStatus('degraded');
        setPriceMessage(error instanceof Error ? error.message : '行情获取失败，已切换本地预览');
        setVisionSource((current) => buildVisionSource(selectedStock, current.kind, current.url, uploadedImage?.fileName, fallback));
      }
    }

    void loadPrices();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅按 selectedStock 重载行情;不随 uploadedImage 变化重拉
  }, [selectedStock]);

  // 形态识别:换标的时拉取确定性 K 线形态(失败安全,失败则清空不报错)。
  useEffect(() => {
    let cancelled = false;
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 200);
    const fmt = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    fetchApi<PatternData>('/api/quant/patterns', {
      method: 'POST',
      body: JSON.stringify({
        symbol: stripSymbolSuffix(selectedStock.symbol),
        start_date: fmt(start),
        end_date: fmt(end),
        lookback: 60,
      }),
    })
      .then((data) => {
        if (!cancelled) setPatternData(data);
      })
      .catch(() => {
        if (!cancelled) setPatternData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedStock]);

  // 形态 → 图表标记(每个日期取最近一个;看涨红箭头在下、看跌绿箭头在上)。
  const patternMarkers = useMemo<KLineMarker[]>(() => {
    if (!showPatterns || !patternData?.patterns?.length) return [];
    const byDate = new Map<string, PatternItem>();
    for (const p of patternData.patterns) {
      if (p.date && !byDate.has(p.date)) byDate.set(p.date, p);
    }
    return [...byDate.values()].map((p) => {
      const bull = p.direction === 'bullish';
      const bear = p.direction === 'bearish';
      return {
        date: p.date,
        position: bull ? 'belowBar' : bear ? 'aboveBar' : 'inBar',
        color: bull ? '#f43f5e' : bear ? '#10b981' : '#a3a3a3',
        shape: bull ? 'arrowUp' : bear ? 'arrowDown' : 'circle',
        text: p.name,
      } as KLineMarker;
    });
  }, [patternData, showPatterns]);

  const [visionModelsReloadKey, setVisionModelsReloadKey] = useState(0);
  useEffect(() => subscribeSettingsChanged(() => setVisionModelsReloadKey((k) => k + 1)), []);

  useEffect(() => {
    let cancelled = false;
    async function loadModels() {
      try {
        const result = await fetchApi<{ providers: ModelProvider[] }>('/api/settings/providers');
        if (cancelled) return;
        const nextProviders = result.providers || [];
        const routes = await loadAiModelRoutesFromApi().catch(() => loadLocalAiModelRoutes());
        if (cancelled) return;
        const models = buildModelOptions(nextProviders, 'vision');
        const chatModels = buildModelOptions(nextProviders, 'chat');
        const visionRoute = getRouteSelection(routes, nextProviders, 'vision_extract');
        const reasoningRoute = getRouteSelection(routes, nextProviders, 'vision_reasoning');
        const visionRouteKey = getModelKey(visionRoute);
        const reasoningRouteKey = getModelKey(reasoningRoute);
        setVisionModels(models);
        setReasoningModels(chatModels);
        setSelectedVisionModelKey((current) => (
          current && models.some((model) => model.key === current)
            ? current
            : visionRouteKey && models.some((model) => model.key === visionRouteKey)
              ? visionRouteKey
              : models[0]
                ? models[0].key
              : ''
        ));
        setSelectedReasoningModelKey((current) => (
          current && chatModels.some((model) => model.key === current)
            ? current
            : reasoningRouteKey && chatModels.some((model) => model.key === reasoningRouteKey)
              ? reasoningRouteKey
              : chatModels[0]
                ? chatModels[0].key
                : ''
        ));
      } catch {
        if (!cancelled) {
          setVisionModels([]);
          setReasoningModels([]);
          setSelectedVisionModelKey('');
          setSelectedReasoningModelKey('');
        }
      }
    }
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [visionModelsReloadKey]);

  useEffect(() => {
    if (uploadedUrl) {
      return () => URL.revokeObjectURL(uploadedUrl);
    }
    return undefined;
  }, [uploadedUrl]);

  useEffect(() => {
    if (!isDiagnosticRunning) return;

    const timer = window.setInterval(() => {
      setProgress((prev) => {
        if (prev >= 88) return 88;
        return Math.min(88, prev + 12);
      });
    }, 220);

    return () => window.clearInterval(timer);
  }, [isDiagnosticRunning]);

  const selectStock = (stock: StockTarget) => {
    setSelectedStock(stock);
    setVisionSource((current) => buildVisionSource(stock, current.kind, current.url, uploadedImage?.fileName, chartData));
    setShowResult(false);
    setVisionReport('');
    setVisionError('');
    dispatchStockSelected(stock, 'chart');
  };

  const runReasoningAnalysis = async (sourceText: string, sourceKind: 'uploaded' | 'kline') => {
    if (!selectedReasoningModel) {
      return [
        sourceText,
        '',
        '未配置推理分析模型，以上只包含基础解析结果。请到系统设置 > 模型路由中配置“多模态推理分析”。',
      ].join('\n');
    }

    const chartSnapshot = chartData.slice(-12).map((point) => (
      `${point.date}: 开${formatPrice(point.open)} 收${formatPrice(point.close)} 高${formatPrice(point.high)} 低${formatPrice(point.low)} 涨跌${point.changePct >= 0 ? '+' : ''}${formatNumber(point.changePct)}% 量${formatVolume(point.volume)}`
    )).join('\n');

    const result = await fetchApi<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        message: [
          '你是严谨的证券投研分析师。请基于图像解析结果和行情上下文，输出一份克制、可核验的多模态诊断报告。',
          '不要把截图识别结果当作已验证事实；需要标注不确定性、反证条件和需要核验的数据。',
          '',
          `诊断类型：${sourceKind === 'uploaded' ? '用户上传图片' : '行情K线数据'}`,
          `标的：${formatStockLabel(selectedStock)}`,
          `最新行情：${lastPoint.date} 收盘 ${formatPrice(lastPoint.close)}，涨跌幅 ${lastPoint.changePct >= 0 ? '+' : ''}${formatNumber(lastPoint.changePct)}%，来源 ${lastPoint.source || quoteLabel}`,
          `区间收益：${rangeReturn >= 0 ? '+' : ''}${formatNumber(rangeReturn)}%`,
          '',
          '图像/数据解析结果：',
          sourceText,
          '',
          '最近K线摘要：',
          chartSnapshot,
          '',
          '请输出：1. 核心结论；2. 关键证据；3. 风险与反证；4. 后续核验动作。',
        ].join('\n'),
        mode: 'free',
        stock_symbol: selectedStock.symbol,
        stock_name: selectedStock.name,
        provider: selectedReasoningModel.providerId,
        model: selectedReasoningModel.modelId,
        context: {
          close: lastPoint.close,
          day_change: lastPoint.changePct,
          period_change: rangeReturn,
          data_date: lastPoint.date,
          multimodal_source: sourceKind,
        },
      }),
    });

    const content = result.content?.trim();
    return content
      ? `推理模型：${result.provider || selectedReasoningModel.providerId} / ${result.model || selectedReasoningModel.modelId}\n\n${content}`
      : `${sourceText}\n\n推理模型没有返回内容，请检查该模型权限、余额或 Base URL。`;
  };

  const startDiagnosis = async () => {
    setProgress(0);
    setShowResult(false);
    setVisionReport('');
    setVisionError('');
    setIsDiagnosticRunning(true);
    try {
      if (uploadedImage) {
        if (!selectedVisionModel) {
          setVisionReport([
            `已绑定上传截图「${uploadedImage.fileName}」。`,
            '',
            '当前系统设置里没有可用的视觉模型，所以没有伪造 AI 识别结论。请在系统设置中添加带视觉能力的模型后重新诊断。',
            '',
            `标的上下文：${formatStockLabel(selectedStock)}，最新价 ${formatPrice(lastPoint.close)}，涨跌幅 ${lastPoint.changePct >= 0 ? '+' : ''}${formatNumber(lastPoint.changePct)}%。`,
          ].join('\n'));
        } else {
          const result = await fetchApi<VisionReportResponse>('/api/vision/report', {
            method: 'POST',
            body: JSON.stringify({
              image_base64: uploadedImage.base64,
              mime_type: uploadedImage.mimeType,
              vendor: selectedVisionModel.providerId,
              model: selectedVisionModel.modelId,
              ticker: stripSymbolSuffix(selectedStock.symbol),
              user_context: [
                `当前前端选择标的: ${formatStockLabel(selectedStock)}`,
                `上传文件: ${uploadedImage.fileName}`,
                `最新行情: ${lastPoint.date} 收盘 ${formatPrice(lastPoint.close)} 涨跌幅 ${lastPoint.changePct >= 0 ? '+' : ''}${formatNumber(lastPoint.changePct)}%`,
                `行情源: ${lastPoint.source || quoteLabel}`,
              ].join('\n'),
            }),
          });
          const visualReport = result.report || '视觉模型没有返回结构化报告。';
          setVisionReport(await runReasoningAnalysis(visualReport, 'uploaded'));
        }
      } else {
        const localReport = [
          `## ${selectedStock.name} (${selectedStock.symbol}) K线诊断`,
          '',
          `数据源：${quoteLabel}`,
          `最新时间：${lastPoint.date}`,
          `最新收盘：${formatPrice(lastPoint.close)}`,
          `涨跌：${lastPoint.change >= 0 ? '+' : ''}${formatNumber(lastPoint.change)} / ${lastPoint.changePct >= 0 ? '+' : ''}${formatNumber(lastPoint.changePct)}%`,
          `区间收益：${rangeReturn >= 0 ? '+' : ''}${formatNumber(rangeReturn)}%`,
          '',
          priceStatus === 'live'
            ? '当前结论基于后端行情源返回的真实 K 线数据。'
            : '当前行情源不可用或为空，页面已明确切换到本地预览数据，请不要把该结果当作实时行情。'
        ].join('\n');
        setVisionReport(await runReasoningAnalysis(localReport, 'kline'));
      }
    } catch (error) {
      setVisionError(error instanceof Error ? error.message : String(error || '视觉诊断失败'));
      setVisionReport('视觉诊断调用失败，未生成替代结论。请检查视觉模型配置、余额或网络连通性。');
    } finally {
      setProgress(100);
      setIsDiagnosticRunning(false);
      setShowResult(true);
    }
  };

  const handleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (uploadedUrl) {
      URL.revokeObjectURL(uploadedUrl);
    }

    const objectUrl = URL.createObjectURL(file);
    setUploadedUrl(objectUrl);
    setUploadedImage(undefined);
    setVisionSource(buildVisionSource(selectedStock, 'uploaded', objectUrl, file.name, chartData));
    setActiveTab('vision');
    setShowResult(false);
    setVisionReport('');
    setVisionError('');
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || '');
      const base64 = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
      setUploadedImage({
        base64,
        mimeType: file.type || 'image/png',
        fileName: file.name,
      });
      setVisionSource(buildVisionSource(selectedStock, 'uploaded', objectUrl, file.name, chartData));
    };
    reader.onerror = () => {
      setVisionError('上传图片读取失败，请重新选择图片。');
    };
    reader.readAsDataURL(file);
    event.target.value = '';
  };

  const handleRefreshPrices = () => {
    const fallback = generateKLineData(selectedStock);
    setChartData(fallback);
    setSelectedStock({ ...selectedStock });
    setShowResult(false);
    setVisionReport('');
  };

  const useGeneratedKline = () => {
    if (uploadedUrl) {
      URL.revokeObjectURL(uploadedUrl);
      setUploadedUrl(undefined);
    }
    setUploadedImage(undefined);
    setVisionReport('');
    setVisionError('');
    setVisionSource(buildVisionSource(selectedStock, 'generated', undefined, undefined, chartData));
    setShowResult(false);
  };

  const saveDiagnosis = () => {
    const record = {
      stock: selectedStock,
      source: visionSource,
      savedAt: new Date().toISOString(),
    };
    window.localStorage.setItem('alphascope:last-vision-diagnosis', JSON.stringify(record));
    setSaveMessage('诊断记录已保存到本地预览缓存。');
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="flex h-full max-w-[1600px] flex-col overflow-hidden p-6 text-neutral-300 lg:p-8"
    >
      <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="flex items-center gap-3 text-2xl font-display font-medium text-white">
            <LineChartIcon className="h-6 w-6 text-indigo-400" />
            K线 / 多模态解析端
          </h2>
          <p className="mt-1.5 text-xs font-mono text-neutral-500">
            顶部搜索会同步到本页；上传截图会按图片本身诊断，交互K线优先使用后端真实行情并显示来源。
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <ThemedSelect
            data-testid="chart-stock-select"
            value={selectedStock.symbol}
            onChange={(value) => {
              const stock = selectableStocks.find((item) => item.symbol === value);
              if (stock) selectStock(stock);
            }}
            className="min-w-[210px]"
            buttonClassName="h-9 bg-black/50 px-3 text-xs font-mono focus-visible:border-indigo-500/50"
            menuClassName="font-mono text-xs"
            options={selectableStocks.map((stock) => ({
              value: stock.symbol,
              label: formatStockLabel(stock),
            }))}
          />
          <div className="flex rounded-xl border border-white/5 bg-white/[0.02] p-1">
            <button
              type="button"
              data-testid="chart-tab-vision"
              onClick={() => setActiveTab('vision')}
              className={cn('rounded-lg px-4 py-1.5 text-xs font-medium transition-all', activeTab === 'vision' ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
            >
              图像诊断
            </button>
            <button
              type="button"
              data-testid="chart-tab-kline"
              onClick={() => setActiveTab('kline')}
              className={cn('rounded-lg px-4 py-1.5 text-xs font-medium transition-all', activeTab === 'kline' ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
            >
              交互K线
            </button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(360px,1fr)]">
        <div className="min-h-0 overflow-hidden rounded-2xl border border-white/5 bg-white/[0.015]">
          <AnimatePresence mode="wait">
            {activeTab === 'vision' ? (
              <motion.div
                key="vision"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 8 }}
                className="flex h-full min-h-0 flex-col"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-black/30 px-5 py-4">
                  <div>
                    <p className="text-xs font-semibold text-neutral-200">{visionSource.title}</p>
                    <p data-testid="chart-current-stock-label" className="mt-1 text-[10px] font-mono text-neutral-500">
                      当前标的：{formatStockLabel(selectedStock)} · {selectedStock.sector} · {chartSourceLabel}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <input ref={fileInputRef} type="file" accept="image/*" onChange={handleUpload} className="hidden" />
                    <button
                      data-testid="chart-upload-image"
                      onClick={() => fileInputRef.current?.click()}
                      className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]"
                    >
                      <Upload className="h-4 w-4" />
                      上传K线截图
                    </button>
                    <button
                      data-testid="chart-use-generated"
                      onClick={useGeneratedKline}
                      className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]"
                    >
                      <RefreshCw className="h-4 w-4" />
                      使用行情K线
                    </button>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-black/45 px-5 py-2.5">
                  <span data-testid="chart-source-badge" className="min-w-0 truncate font-mono text-[10px] text-neutral-400">
                    {visionSource.kind === 'uploaded' ? `用户上传 · ${uploadedImage?.fileName || '读取中'}` : chartSourceLabel} · {selectedStock.symbol}
                  </span>
                  {!visionSource.url && <KLineHoverStrip point={displayHoverPoint} mode="指针行情" />}
                  {priceStatus !== 'live' && !visionSource.url && (
                    <span className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-100">
                      {priceMessage}
                    </span>
                  )}
                </div>

                <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black/60 p-5">
                  <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.018)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.018)_1px,transparent_1px)] bg-[size:24px_24px]" />
                  {visionSource.url ? (
                    <img
                      data-testid="chart-upload-preview"
                      src={visionSource.url}
                      alt={visionSource.title}
                      className="relative z-10 max-h-full max-w-full rounded-xl border border-white/10 object-contain shadow-2xl"
                    />
                  ) : (
                    <div data-testid="chart-generated-kline" className="relative z-10 h-full min-h-[360px] w-full rounded-xl border border-white/10 bg-[#070707] p-4">
                      <StableChartContainer>
                        <ComposedChart
                          data={chartData}
                          margin={{ top: 10, right: 18, left: -12, bottom: 18 }}
                          onMouseMove={handleKLineMouseMove}
                        >
                          <CartesianGrid stroke="#ffffff" strokeOpacity={0.04} vertical={false} />
                          <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" minTickGap={18} />
                          <YAxis domain={priceDomain} tickFormatter={(value) => formatPrice(Number(value))} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" />
                          <Tooltip
                            content={<CompactKLineTooltip />}
                            offset={0}
                            allowEscapeViewBox={{ x: true, y: true }}
                            wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                            cursor={{ stroke: '#818cf8', strokeOpacity: 0.32, strokeWidth: 1 }}
                          />
                          <Bar dataKey="wickRange" barSize={9} shape={<Candlestick />} isAnimationActive={false}>
                            {chartData.map((entry, index) => (
                              <Cell key={`vision-candle-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} />
                            ))}
                          </Bar>
                          {showMA && <Line type="monotone" dataKey="ma5" stroke="#facc15" strokeWidth={1.4} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                          {showMA && <Line type="monotone" dataKey="ma20" stroke="#38bdf8" strokeWidth={1.4} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                        </ComposedChart>
                      </StableChartContainer>
                    </div>
                  )}

                  {isDiagnosticRunning && (
                    <motion.div
                      initial={{ y: -180 }}
                      animate={{ y: [-180, 180, -180] }}
                      transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
                      className="absolute left-0 right-0 z-20 h-0.5 bg-gradient-to-r from-transparent via-indigo-400 to-transparent shadow-[0_0_20px_rgba(129,140,248,0.9)]"
                    />
                  )}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/5 bg-black/35 px-5 py-4">
                  <p className="max-w-2xl text-xs leading-relaxed text-neutral-400">{visionSource.description}</p>
                  <button
                    data-testid="chart-start-vision"
                    onClick={startDiagnosis}
                    disabled={isDiagnosticRunning || (visionSource.kind === 'uploaded' && !uploadedImage)}
                    className={cn(
                      'flex items-center gap-2 rounded-xl border px-5 py-2.5 text-xs font-semibold transition-all',
                      isDiagnosticRunning
                        ? 'border-indigo-500/20 bg-indigo-950/40 text-indigo-300'
                        : 'border-indigo-500 bg-indigo-600 text-white shadow-[0_0_18px_rgba(99,102,241,0.25)] hover:bg-indigo-500'
                    )}
                  >
                    <Sparkles className="h-4 w-4" />
                    {isDiagnosticRunning ? `解析中 ${progress}%` : visionSource.kind === 'uploaded' ? '诊断上传截图' : '生成K线诊断'}
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="kline"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 8 }}
                className="flex h-full min-h-0 flex-col"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 bg-black/30 px-5 py-4">
                  <div>
                    <p data-testid="chart-kline-stock-label" className="text-xs font-semibold text-neutral-200">{formatStockLabel(selectedStock)} 量价沙盘</p>
                    <p className="mt-1 text-[10px] font-mono text-neutral-500">区间收益 {rangeReturn >= 0 ? '+' : ''}{formatNumber(rangeReturn)}% · 最新价 {formatPrice(lastPoint.close)} · {quoteLabel}</p>
                  </div>
                  <div className="flex items-center gap-4">
                    <button
                      type="button"
                      onClick={handleRefreshPrices}
                      className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[10px] text-neutral-300 transition-colors hover:bg-white/[0.06]"
                      title="刷新行情"
                    >
                      <RefreshCw className={cn('h-3.5 w-3.5', priceStatus === 'loading' && 'animate-spin')} />
                      刷新行情
                    </button>
                    <label className="flex cursor-pointer items-center gap-2 text-xs text-neutral-400">
                      <input type="checkbox" checked={showMA} onChange={() => setShowMA((value) => !value)} />
                      显示均线
                    </label>
                    <div className="flex rounded-lg border border-white/5 bg-black/30 p-0.5" title="K线渲染模式">
                      {([['pro', '专业'], ['classic', '经典']] as Array<['pro' | 'classic', string]>).map(([mode, label]) => (
                        <button
                          key={mode}
                          onClick={() => setKlineRenderer(mode)}
                          className={cn('rounded px-3 py-1 text-[10px]', klineRenderer === mode ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="flex rounded-lg border border-white/5 bg-black/30 p-0.5">
                      {(['macd', 'rsi'] as Indicator[]).map((item) => (
                        <button
                          key={item}
                          onClick={() => setIndicator(item)}
                          className={cn('rounded px-3 py-1 text-[10px] font-mono uppercase', indicator === item ? 'bg-white/10 text-white' : 'text-neutral-500 hover:text-neutral-300')}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="flex min-h-0 flex-1 flex-col bg-black/45 p-4">
                  <div className="mb-3 flex min-h-[34px] items-center justify-between rounded-lg border border-white/5 bg-black/35 px-3 py-2">
                    <KLineHoverStrip point={displayHoverPoint} mode="指针行情" />
                    <span className="hidden font-mono text-[10px] text-neutral-600 sm:inline">鼠标移过图表查看该根K线</span>
                  </div>

                  {patternData && patternData.status === 'ok' && patternData.patterns.length > 0 && (
                    <div className="mb-3 rounded-lg border border-white/5 bg-black/35 px-3 py-2">
                      <div className="mb-1.5 flex items-center justify-between">
                        <div className="flex items-center gap-2 text-[11px] font-medium text-neutral-300">
                          <span>形态识别</span>
                          <span className="text-rose-400">{patternData.counts.bullish ?? 0} 看涨</span>
                          <span className="text-emerald-400">{patternData.counts.bearish ?? 0} 看跌</span>
                          <span className="text-neutral-500">{patternData.counts.neutral ?? 0} 中性</span>
                        </div>
                        <label className="flex cursor-pointer items-center gap-1.5 text-[10px] text-neutral-400">
                          <input type="checkbox" checked={showPatterns} onChange={() => setShowPatterns((v) => !v)} />
                          图上标记
                        </label>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {patternData.patterns.slice(0, 14).map((p, i) => {
                          const bull = p.direction === 'bullish';
                          const bear = p.direction === 'bearish';
                          return (
                            <span
                              key={`${p.date}-${p.name}-${i}`}
                              title={`${p.date} · ${p.detail}`}
                              className={cn(
                                'rounded border px-1.5 py-0.5 text-[10px]',
                                bull
                                  ? 'border-rose-500/25 bg-rose-500/10 text-rose-300'
                                  : bear
                                    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                                    : 'border-white/10 bg-white/5 text-neutral-400',
                              )}
                            >
                              {p.name}
                            </span>
                          );
                        })}
                      </div>
                      {patternData.disclaimer && (
                        <p className="mt-1.5 text-[9px] leading-relaxed text-neutral-600">{patternData.disclaimer}</p>
                      )}
                    </div>
                  )}
                  {/* K线蜡烛逐点动画重排贵 -> 关闭，整图由 motion 一次性 GPU 淡入 */}
                  <motion.div
                    key={`mkline-${selectedStock?.symbol ?? 'k'}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.45, ease: 'easeOut' }}
                    className="flex min-h-0 flex-1 flex-col"
                  >
                  <div className="min-h-0 flex-1">
                    {klineRenderer === 'pro' ? (
                      <LightweightKLine data={chartData} showMA={showMA} markers={patternMarkers} />
                    ) : (
                    <StableChartContainer>
                      <ComposedChart
                        data={chartData}
                        margin={{ top: 10, right: 18, left: -12, bottom: 18 }}
                        onMouseMove={handleKLineMouseMove}
                      >
                        <CartesianGrid stroke="#ffffff" strokeOpacity={0.04} vertical={false} />
                        <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" minTickGap={18} />
                        <YAxis domain={priceDomain} tickFormatter={(value) => formatPrice(Number(value))} tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" />
                        <Tooltip
                          content={<CompactKLineTooltip />}
                          offset={0}
                          allowEscapeViewBox={{ x: true, y: true }}
                          wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                          cursor={{ stroke: '#818cf8', strokeOpacity: 0.32, strokeWidth: 1 }}
                        />
                        <Bar dataKey="wickRange" barSize={9} shape={<Candlestick />} isAnimationActive={false}>
                          {chartData.map((entry, index) => (
                            <Cell key={`kline-candle-${index}`} fill={entry.up ? '#f43f5e' : '#10b981'} />
                          ))}
                        </Bar>
                        {showMA && <Line type="monotone" dataKey="ma5" stroke="#facc15" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                        {showMA && <Line type="monotone" dataKey="ma20" stroke="#38bdf8" strokeWidth={1.5} dot={false} activeDot={false} animationDuration={800} animationEasing="ease-out" />}
                      </ComposedChart>
                    </StableChartContainer>
                    )}
                  </div>
                  <div className="my-3 h-px bg-white/5" />
                  <div className="h-28">
                    <StableChartContainer>
                      <ComposedChart data={chartData} margin={{ top: 4, right: 18, left: -12, bottom: 0 }}>
                        <CartesianGrid stroke="#ffffff" strokeOpacity={0.04} vertical={false} />
                        <XAxis dataKey="date" hide />
                        <YAxis tick={{ fill: '#737373', fontSize: 10 }} stroke="#222" />
                        <Tooltip
                          content={<CustomTooltip />}
                          offset={0}
                          allowEscapeViewBox={{ x: true, y: true }}
                          wrapperStyle={{ pointerEvents: 'none', zIndex: 30, outline: 'none' }}
                          cursor={{ fill: 'rgba(129,140,248,0.08)' }}
                        />
                        {indicator === 'macd' ? (
                          <Bar dataKey="macd" barSize={4}>
                            {chartData.map((entry, index) => (
                              <Cell key={index} fill={entry.macd >= 0 ? '#f43f5e' : '#10b981'} fillOpacity={0.75} />
                            ))}
                          </Bar>
                        ) : (
                          <Line type="monotone" dataKey="rsi" stroke="#a78bfa" strokeWidth={1.5} dot={false} animationDuration={800} animationEasing="ease-out" />
                        )}
                        {indicator === 'rsi' && <ReferenceLine y={70} stroke="#f43f5e" strokeOpacity={0.35} strokeDasharray="3 3" />}
                        {indicator === 'rsi' && <ReferenceLine y={30} stroke="#10b981" strokeOpacity={0.35} strokeDasharray="3 3" />}
                      </ComposedChart>
                    </StableChartContainer>
                  </div>
                </motion.div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] p-5">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-500/20 bg-indigo-500/10">
              <Eye className="h-4 w-4 text-indigo-300" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-neutral-100">多模态诊断报告</h3>
              <p className="text-[10px] font-mono uppercase tracking-wider text-neutral-500">图像识别与量价归因</p>
            </div>
          </div>

          <div className="mb-4 space-y-2 rounded-xl border border-white/5 bg-black/20 p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-500">模型路由</span>
              <button
                type="button"
                onClick={onOpenModelSettings}
                className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-neutral-400 transition-colors hover:border-indigo-400/40 hover:text-indigo-200"
              >
                <Settings2 className="h-3.5 w-3.5" />
                设置
              </button>
            </div>
            <label className="block">
              <span className="mb-1 block text-[10px] text-neutral-500">图片解析模型</span>
              <ThemedSelect
                data-testid="chart-vision-model-select"
                value={selectedVisionModel?.key || ''}
                onChange={setSelectedVisionModelKey}
                disabled={!visionModels.length}
                buttonClassName="h-9 rounded-lg bg-black/50 px-2 text-[11px] focus-visible:border-indigo-500/50"
                menuClassName="text-xs"
                options={visionModels.length ? visionModels.map((model) => ({
                  value: model.key,
                  label: formatModelOption(model),
                  badge: <span className="rounded-full bg-indigo-400/10 px-1.5 py-0.5 text-[9px] text-indigo-200">视觉</span>,
                })) : [{ value: '', label: '暂无视觉模型，请到设置中标记视觉能力', disabled: true }]}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[10px] text-neutral-500">推理分析模型</span>
              <ThemedSelect
                data-testid="chart-reasoning-model-select"
                value={selectedReasoningModel?.key || ''}
                onChange={setSelectedReasoningModelKey}
                disabled={!reasoningModels.length}
                buttonClassName="h-9 rounded-lg bg-black/50 px-2 text-[11px] focus-visible:border-indigo-500/50"
                menuClassName="text-xs"
                options={reasoningModels.length ? reasoningModels.map((model) => ({
                  value: model.key,
                  label: formatModelOption(model),
                })) : [{ value: '', label: '暂无推理模型', disabled: true }]}
              />
            </label>
          </div>

          <div className="mb-4 grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-xl border border-white/5 bg-black/25 p-3">
              <p className="mb-1 text-[10px] text-neutral-500">解析标的</p>
              <p className="font-semibold text-neutral-200">{selectedStock.name}</p>
              <p className="mt-1 font-mono text-[10px] text-indigo-300">{selectedStock.symbol}</p>
            </div>
            <div className="rounded-xl border border-white/5 bg-black/25 p-3">
              <p className="mb-1 text-[10px] text-neutral-500">数据形态</p>
              <p className="font-semibold text-neutral-200">{visionSource.kind === 'uploaded' ? '上传截图' : priceStatus === 'live' ? '真实行情K线' : '本地预览K线'}</p>
              <p className={cn('mt-1 font-mono text-[10px]', priceStatus === 'live' || visionSource.kind === 'uploaded' ? 'text-emerald-300' : 'text-amber-300')}>
                {visionSource.kind === 'uploaded' ? `图片 ${uploadedImage ? '已读取' : '读取中'}` : chartSourceLabel}
              </p>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto pr-1 custom-scrollbar">
            <AnimatePresence mode="wait">
              {isDiagnosticRunning && (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex min-h-[320px] flex-col items-center justify-center gap-4 text-center"
                >
                  <div className="relative flex h-16 w-16 items-center justify-center">
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
                      className="absolute inset-0 rounded-full border-2 border-indigo-500/20 border-t-indigo-400"
                    />
                    <FileImage className="h-6 w-6 text-indigo-300" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-neutral-100">正在解析图像与量价结构</p>
                    <p className="mt-1 text-[11px] text-neutral-500">扫描趋势线、成交量、均线、指标背离与异常波动</p>
                  </div>
                </motion.div>
              )}

              {!isDiagnosticRunning && showResult && (
                <motion.div data-testid="chart-diagnosis-result" key="result" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                  <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
                    <p className="mb-1 text-[10px] font-mono uppercase tracking-widest text-indigo-300">诊断结论</p>
                    <h4 className="text-sm font-semibold text-white">{visionSource.title}</h4>
                    <div
                      className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-neutral-300"
                      dangerouslySetInnerHTML={{
                        __html: (visionReport || visionSource.assessment)
                          .replace(/&/g, '&amp;')
                          .replace(/</g, '&lt;')
                          .replace(/>/g, '&gt;')
                          .replace(/\*\*(.*?)\*\*/g, '<span class="font-semibold text-white">$1</span>')
                          .replace(/^##\s*(.*)$/gm, '<span class="block pt-1 text-sm font-semibold text-white">$1</span>')
                          .replace(/\n/g, '<br/>'),
                      }}
                    />
                    {visionError && (
                      <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] text-amber-100">{visionError}</p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <p className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">识别信号</p>
                    {visionSource.signals.map((signal) => (
                      <div key={signal} className="flex gap-2.5 rounded-lg border border-white/5 bg-black/25 p-3 text-xs text-neutral-300">
                        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-300" />
                        <span>{signal}</span>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-relaxed text-amber-100/80">
                    AI 图像诊断只作为研究辅助。若要进入交易决策，请继续核验实时行情、公告、资金流与风险事件。
                  </div>

                  <button data-testid="chart-save-diagnosis" onClick={saveDiagnosis} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-neutral-300 transition-colors hover:bg-white/[0.06]">
                    <Download className="h-3.5 w-3.5" />
                    保存诊断记录
                  </button>
                  {saveMessage && (
                    <p className="text-[11px] text-emerald-300">{saveMessage}</p>
                  )}
                </motion.div>
              )}

              {!isDiagnosticRunning && !showResult && (
                <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex min-h-[320px] flex-col items-center justify-center gap-4 text-center text-neutral-500">
                  <ImagePlus className="h-9 w-9 text-neutral-600" />
                  <div>
                    <p className="text-sm text-neutral-300">选择标的、上传截图或使用行情K线后开始解析</p>
                    <p className="mt-1 max-w-sm text-[11px] leading-relaxed">
                      上传截图会优先诊断图片本身；交互K线会优先使用后端真实行情，并在不可用时明确显示预览降级。
                    </p>
                  </div>
                  <div data-testid="chart-sync-badge" className="flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[11px] text-emerald-300">
                    <SearchCheck className="h-3.5 w-3.5" />
                    当前同步：{formatStockLabel(selectedStock)}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/5 pt-4 text-center text-[10px] font-mono text-neutral-500">
            <div className="rounded-lg bg-black/20 p-2">
              <Activity className="mx-auto mb-1 h-3.5 w-3.5 text-rose-400" />
              涨跌幅 {rangeReturn >= 0 ? '+' : ''}{formatNumber(rangeReturn)}%
            </div>
            <div className="rounded-lg bg-black/20 p-2">
              <BarChart3 className="mx-auto mb-1 h-3.5 w-3.5 text-indigo-300" />
              样本 {chartData.length} 条
            </div>
            <div className="rounded-lg bg-black/20 p-2">
              <Sparkles className="mx-auto mb-1 h-3.5 w-3.5 text-emerald-300" />
              可追踪
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
