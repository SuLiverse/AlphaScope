/**
 * Workbench chart tooltip / candlestick (extracted from Workbench.tsx).
 */
import { formatVolume, formatPrice, getFloatingTooltipStyle, type WorkbenchChartPoint } from "./support";

export function WorkbenchChartTooltip({ active, payload, label, coordinate, viewBox }: any) {
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

export function CompactWorkbenchTooltip({ active, payload, label, coordinate, viewBox }: any) {
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

export function WorkbenchCandlestick(props: any) {
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


