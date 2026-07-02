import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';

/**
 * 专业 K 线渲染器 (TradingView Lightweight Charts)。
 *
 * 相比 recharts 自绘蜡烛,提供真·缩放/平移/十字光标/价格刻度对齐,适合密集 K 线。
 * 作为「交互K线」页的**专业渲染模式**接入,与原 recharts「经典」模式并存(只增不替)。
 *
 * 输入沿用既有 KLinePoint 形状(date/open/high/low/close + 可选 ma5/ma20),无需新取数。
 * A 股配色:涨红 / 跌绿。
 */

export interface KLineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
}

export interface KLineMarker {
  date: string;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
  text: string;
}

interface Props {
  data: KLineBar[];
  /** 总开关(向后兼容):未单独指定 showMa5/showMa20 时控制两条均线。 */
  showMA?: boolean;
  /** 细粒度均线开关(覆盖 showMA)。 */
  showMa5?: boolean;
  showMa10?: boolean;
  showMa20?: boolean;
  /** 可选:在对应 K 线上打形态标记(箭头/圆点)。 */
  markers?: KLineMarker[];
}

const UP = '#f43f5e'; // 涨红
const DOWN = '#10b981'; // 跌绿

/** 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM' → UTC 秒(lightweight-charts 要求时间唯一且升序)。 */
function toTime(date: string): UTCTimestamp {
  const ms = Date.parse(date.replace(' ', 'T'));
  return Math.floor((Number.isNaN(ms) ? 0 : ms) / 1000) as UTCTimestamp;
}

export function LightweightKLine({ data, showMA = true, showMa5, showMa10, showMa20, markers }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const ma5Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const ma10Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const ma20Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const legendRef = useRef<HTMLDivElement | null>(null);

  // 建图一次(挂载时)。autoSize 让图表自适应容器宽高。
  // 注意: 本组件常以 React.lazy 挂载(Suspense), 首帧容器宽度可能为 0 / 布局未稳定。
  // autoSize 的 ResizeObserver 首次回调与紧随其后的 setData + fitContent 存在时序竞争,
  // 若 fitContent 在 0 宽度下拟合, 所有蜡烛会被压成一团(首帧堆叠)。
  // 故: ① 建图时显式读容器 clientWidth/clientHeight 作初始尺寸; ② fitContent 延迟到 rAF。
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;

    const chart = createChart(el, {
      autoSize: true,
      width: el.clientWidth || undefined,
      height: el.clientHeight || undefined,
      layout: {
        background: { type: ColorType.Solid, color: 'rgba(0,0,0,0)' },
        textColor: '#a3a3a3',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: false, secondsVisible: false },
    });

    const candle = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    const ma5 = chart.addLineSeries({ color: '#facc15', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma10 = chart.addLineSeries({ color: '#818cf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma20 = chart.addLineSeries({ color: '#38bdf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

    chartRef.current = chart;
    candleRef.current = candle;
    ma5Ref.current = ma5;
    ma10Ref.current = ma10;
    ma20Ref.current = ma20;

    // 十字光标移动时在左上角显示该根 K 线的 OHLC。
    chart.subscribeCrosshairMove((param) => {
      const legend = legendRef.current;
      if (!legend) return;
      const c = param.seriesData.get(candle) as CandlestickData | undefined;
      if (!c) {
        legend.textContent = '';
        return;
      }
      const up = c.close >= c.open;
      legend.textContent = `开 ${c.open}　高 ${c.high}　低 ${c.low}　收 ${c.close}　${up ? '▲' : '▼'}`;
      legend.style.color = up ? UP : DOWN;
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      ma5Ref.current = null;
      ma10Ref.current = null;
      ma20Ref.current = null;
    };
  }, []);

  // 数据变化时刷新(去重 + 升序;均线仅取有限正值,避免预热段 NaN)。
  useEffect(() => {
    const candle = candleRef.current;
    const chart = chartRef.current;
    if (!candle || !chart) return;

    const seen = new Map<number, CandlestickData>();
    const byTime = new Map<number, KLineBar>();
    for (const b of data || []) {
      const t = toTime(b.date);
      seen.set(t, { time: t as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
      byTime.set(t, b);
    }
    const candles = [...seen.values()].sort((a, b) => (a.time as number) - (b.time as number));

    const m5: LineData[] = [];
    const m10: LineData[] = [];
    const m20: LineData[] = [];
    for (const c of candles) {
      const t = c.time as number;
      const b = byTime.get(t);
      if (!b) continue;
      if (typeof b.ma5 === 'number' && Number.isFinite(b.ma5) && b.ma5 > 0) m5.push({ time: t as UTCTimestamp, value: b.ma5 });
      if (typeof b.ma10 === 'number' && Number.isFinite(b.ma10) && b.ma10 > 0) m10.push({ time: t as UTCTimestamp, value: b.ma10 });
      if (typeof b.ma20 === 'number' && Number.isFinite(b.ma20) && b.ma20 > 0) m20.push({ time: t as UTCTimestamp, value: b.ma20 });
    }

    // 细粒度开关优先;未指定则回退到 showMA 总开关(ma10 默认关)。
    const ma5On = showMa5 ?? showMA;
    const ma10On = showMa10 ?? false;
    const ma20On = showMa20 ?? showMA;

    candle.setData(candles);
    ma5Ref.current?.setData(ma5On ? m5 : []);
    ma10Ref.current?.setData(ma10On ? m10 : []);
    ma20Ref.current?.setData(ma20On ? m20 : []);
    // 延迟到下一帧再 fitContent: 让浏览器完成布局、autoSize 的 ResizeObserver
    // 回调把宽度修正到位, 避免在 0/错宽度下拟合导致首帧堆叠。
    const raf = requestAnimationFrame(() => chart.timeScale().fitContent());
    return () => cancelAnimationFrame(raf);
  }, [data, showMA, showMa5, showMa10, showMa20]);

  // 形态标记(可选):在对应 K 线上打箭头/圆点(时间须升序)。
  useEffect(() => {
    const candle = candleRef.current;
    if (!candle) return;
    const ms: SeriesMarker<Time>[] = (markers || [])
      .map((m) => ({
        time: toTime(m.date) as Time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));
    candle.setMarkers(ms);
  }, [markers]);

  return (
    <div className="relative h-full w-full" style={{ minHeight: 220 }}>
      <div ref={legendRef} className="pointer-events-none absolute left-2 top-1.5 z-10 font-mono text-[10px]" />
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}
