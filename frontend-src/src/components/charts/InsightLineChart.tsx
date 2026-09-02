/**
 * Beautiful UI Insight Cards 折线（对照 beautifului.dev 截图）：
 * 样条曲线、左淡右实、终点白圈、虚线基准、浅网格、可选对照线。
 * 刮擦仍落在真实数据点上，读数不走曲线插值。
 *
 * 对照线只表达「相对走势」：按首个共同点重定基到主序列的尺度后再画。
 * 不这样做的话 TOPIX(≈4200) 与グロース(≈1000) 共用一条绝对轴，主线会被压成直线。
 */
import {
  memo,
  useCallback,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { cn } from '@/lib/utils';

export type InsightDatum = { value: number; label?: string };

export type InsightScrub = {
  index: number;
  value: number;
  label?: string;
  x: number;
  y: number;
};

export interface InsightLineChartProps {
  data: Array<number | InsightDatum>;
  compare?: Array<number | InsightDatum>;
  height?: number;
  width?: number;
  change?: number;
  tone?: 'auto' | 'brand' | 'up' | 'down';
  compareTone?: 'brand' | 'ai';
  interactive?: boolean;
  focusable?: boolean;
  showLiveDot?: boolean;
  showCursorValue?: boolean;
  showGrid?: boolean;
  showAxis?: boolean;
  showFill?: boolean;
  strokeWidth?: number;
  formatValue?: (value: number) => string;
  onScrub?: (point: InsightScrub | null) => void;
  className?: string;
  ariaLabel?: string;
}

type Pt = { x: number; y: number };

export function normalizeInsightSeries(data: Array<number | InsightDatum>): InsightDatum[] {
  const out: InsightDatum[] = [];
  for (const item of data) {
    if (typeof item === 'number') {
      if (Number.isFinite(item)) out.push({ value: item });
      continue;
    }
    if (item && Number.isFinite(item.value)) out.push(item);
  }
  return out;
}

export function insightTone(change?: number): 'up' | 'down' | 'brand' {
  if (change == null || !Number.isFinite(change) || change === 0) return 'brand';
  return change > 0 ? 'up' : 'down';
}

export function insightStroke(tone: 'up' | 'down' | 'brand' | 'ai'): string {
  if (tone === 'up') return 'var(--up-600)';
  if (tone === 'down') return 'var(--down-600)';
  if (tone === 'ai') return 'var(--ai-600)';
  return 'var(--brand-600)';
}

/** Catmull-Rom → 三次贝塞尔，曲线过点（刮擦点与曲线一致） */
function splinePath(points: Pt[]): string {
  if (points.length === 0) return '';
  if (points.length === 1) return `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  let d = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += `C${c1x.toFixed(2)},${c1y.toFixed(2)},${c2x.toFixed(2)},${c2y.toFixed(2)},${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
  }
  return d;
}

function plotPoints(
  values: number[],
  width: number,
  height: number,
  padX: number,
  padY: number,
  min: number,
  span: number,
): Pt[] {
  const innerW = Math.max(width - padX * 2, 1);
  const innerH = Math.max(height - padY * 2, 1);
  const step = values.length > 1 ? innerW / (values.length - 1) : 0;
  return values.map((value, index) => ({
    x: padX + index * step,
    y: padY + (1 - (value - min) / span) * innerH,
  }));
}

function alignCompare(primary: InsightDatum[], compare: InsightDatum[]): Array<number | null> {
  if (compare.length === 0) return [];
  const byLabel = new Map<string, number>();
  for (const item of compare) {
    if (item.label) byLabel.set(item.label, item.value);
  }
  if (byLabel.size > 0 && primary.some((item) => item.label)) {
    return primary.map((item) => (item.label != null ? (byLabel.get(item.label) ?? null) : null));
  }
  if (compare.length === primary.length) return compare.map((item) => item.value);
  return primary.map((_, index) => {
    const mapped = Math.round((index / Math.max(primary.length - 1, 1)) * (compare.length - 1));
    return compare[mapped]?.value ?? null;
  });
}

/** 把对照序列按首个共同点缩放到主序列尺度（只画相对走势，对照线没有读数） */
function rebaseCompare(primary: number[], compare: Array<number | null>): Array<number | null> {
  for (let index = 0; index < Math.min(primary.length, compare.length); index++) {
    const base = compare[index];
    const anchor = primary[index];
    if (base == null || base === 0 || anchor == null) continue;
    const factor = anchor / base;
    return compare.map((value) => (value == null ? null : value * factor));
  }
  return compare;
}

function pointFromClientX(clientX: number, rect: DOMRect, count: number, padX: number): number {
  if (count <= 1) return 0;
  const x = clientX - rect.left;
  const inner = Math.max(rect.width - padX * 2, 1);
  const ratio = (x - padX) / inner;
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}

function axisTick(label: string | undefined): string {
  if (!label) return '';
  return label.length >= 10 ? label.slice(5) : label;
}

const InsightLineChart = memo(function InsightLineChart({
  data,
  compare,
  height = 72,
  width: fixedWidth,
  change,
  tone = 'auto',
  compareTone = 'brand',
  interactive = true,
  focusable = true,
  showLiveDot = true,
  showCursorValue = false,
  showGrid = false,
  showAxis = false,
  showFill = false,
  strokeWidth,
  formatValue,
  onScrub,
  className,
  ariaLabel,
}: InsightLineChartProps) {
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, '');
  const wrapRef = useRef<HTMLDivElement>(null);
  const pathRef = useRef<SVGPathElement>(null);
  const [width, setWidth] = useState(0);
  const [pathLen, setPathLen] = useState(0);
  const [scrub, setScrub] = useState<InsightScrub | null>(null);

  const series = useMemo(() => normalizeInsightSeries(data), [data]);
  const compareSeries = useMemo(() => (compare ? normalizeInsightSeries(compare) : []), [compare]);
  const values = useMemo(() => series.map((item) => item.value), [series]);
  const compareValues = useMemo(
    () => rebaseCompare(values, alignCompare(series, compareSeries)),
    [values, series, compareSeries],
  );
  const resolvedTone = tone === 'auto' ? insightTone(change) : tone;
  const color = insightStroke(resolvedTone);
  const compareColor = insightStroke(compareTone);
  const lineWidth = strokeWidth ?? (height >= 140 ? 2.6 : 2.15);
  const axisH = showAxis ? 16 : 0;
  const padX = showAxis ? 10 : 8;
  const padY = height >= 140 ? 16 : 10;
  const plotH = height - axisH;

  useLayoutEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const apply = (next: number) => {
      const rounded = Math.max(0, Math.round(next));
      setWidth((prev) => (prev === rounded ? prev : rounded));
    };
    apply(fixedWidth ?? node.clientWidth);
    if (fixedWidth) return;
    const observer = new ResizeObserver((entries) => apply(entries[0]?.contentRect.width ?? 0));
    observer.observe(node);
    return () => observer.disconnect();
  }, [fixedWidth]);

  const geometry = useMemo(() => {
    if (values.length < 2 || width <= 0) return null;
    const pooled = [...values, ...compareValues.filter((value): value is number => value != null)];
    const min = Math.min(...pooled);
    const max = Math.max(...pooled);
    const span = max - min || 1;
    const points = plotPoints(values, width, plotH, padX, padY, min, span);
    const innerW = Math.max(width - padX * 2, 1);
    const innerH = Math.max(plotH - padY * 2, 1);
    const step = values.length > 1 ? innerW / (values.length - 1) : 0;
    const comparePoints: Pt[] = [];
    for (let index = 0; index < compareValues.length; index++) {
      const value = compareValues[index];
      if (value == null) continue;
      comparePoints.push({
        x: padX + index * step,
        y: padY + (1 - (value - min) / span) * innerH,
      });
    }
    const line = splinePath(points);
    const last = points[points.length - 1];
    const first = points[0];
    const area = `${line}L${last.x.toFixed(2)},${(plotH - 1).toFixed(2)}L${first.x.toFixed(2)},${(plotH - 1).toFixed(2)}Z`;
    const compareLine = comparePoints.length >= 2 ? splinePath(comparePoints) : '';
    return { points, comparePoints, line, compareLine, area, min, max, span };
  }, [values, compareValues, width, plotH, padX, padY]);

  useLayoutEffect(() => {
    if (!pathRef.current || !geometry) {
      setPathLen(0);
      return;
    }
    setPathLen(pathRef.current.getTotalLength());
  }, [geometry]);

  const publish = useCallback(
    (next: InsightScrub | null) => {
      setScrub(next);
      onScrub?.(next);
    },
    [onScrub],
  );

  const moveToIndex = useCallback(
    (index: number) => {
      if (!geometry) return;
      const point = geometry.points[index];
      const item = series[index];
      if (!point || !item) return;
      publish({ index, value: item.value, label: item.label, x: point.x, y: point.y });
    },
    [geometry, publish, series],
  );

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!interactive || !geometry) return;
    const rect = event.currentTarget.getBoundingClientRect();
    moveToIndex(pointFromClientX(event.clientX, rect, series.length, padX));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!interactive || series.length < 2) return;
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const current = scrub?.index ?? series.length - 1;
    const next = event.key === 'ArrowLeft' ? current - 1 : current + 1;
    moveToIndex(Math.max(0, Math.min(series.length - 1, next)));
  };

  const last = geometry?.points[geometry.points.length - 1];
  const compareLast = geometry?.comparePoints[geometry.comparePoints.length - 1];
  const cursor = scrub && geometry ? geometry.points[scrub.index] : null;
  const liveText = scrub
    ? `${scrub.label ?? ''} ${formatValue ? formatValue(scrub.value) : scrub.value}`.trim()
    : ariaLabel ?? '';
  const axisMarks = showAxis && series.length
    ? [
        { x: padX, text: axisTick(series[0]?.label) },
        { x: width / 2, text: axisTick(series[Math.floor((series.length - 1) / 2)]?.label) },
        { x: Math.max(width - padX, padX), text: axisTick(series[series.length - 1]?.label) },
      ]
    : [];

  return (
    <div
      ref={wrapRef}
      className={cn('insight-chart relative w-full', interactive && 'insight-chart-interactive', className)}
      style={{ height, width: fixedWidth }}
      onPointerMove={onPointerMove}
      onPointerLeave={() => {
        if (interactive) publish(null);
      }}
      onKeyDown={onKeyDown}
      tabIndex={interactive && focusable ? 0 : undefined}
      role={interactive && focusable ? 'slider' : 'img'}
      aria-orientation={interactive && focusable ? 'horizontal' : undefined}
      aria-label={ariaLabel}
      aria-valuemin={interactive && focusable ? 0 : undefined}
      aria-valuemax={interactive && focusable ? Math.max(series.length - 1, 0) : undefined}
      aria-valuenow={interactive && focusable ? (scrub?.index ?? series.length - 1) : undefined}
      aria-valuetext={interactive && focusable ? liveText || undefined : undefined}
    >
      {geometry && (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="block">
          <defs>
            <linearGradient id={`fade-${rawId}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#fff" stopOpacity="0" />
              <stop offset="16%" stopColor="#fff" stopOpacity="0.28" />
              <stop offset="48%" stopColor="#fff" stopOpacity="0.85" />
              <stop offset="100%" stopColor="#fff" stopOpacity="1" />
            </linearGradient>
            <mask id={`mask-${rawId}`} maskUnits="userSpaceOnUse">
              <rect x="0" y="0" width={width} height={plotH} fill={`url(#fade-${rawId})`} />
            </mask>
            <linearGradient id={`fill-${rawId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.16" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
            <filter id={`glow-${rawId}`} x="-20%" y="-40%" width="140%" height="180%">
              <feGaussianBlur stdDeviation="2.1" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {showGrid &&
            [0.25, 0.5, 0.75].map((ratio) => {
              const y = padY + ratio * Math.max(plotH - padY * 2, 1);
              return (
                <line
                  key={ratio}
                  x1={padX}
                  x2={width - padX}
                  y1={y}
                  y2={y}
                  stroke="var(--line-chart)"
                  strokeWidth="1"
                  strokeDasharray="3 5"
                />
              );
            })}

          {last && (
            <line
              x1={padX}
              x2={width - padX}
              y1={last.y}
              y2={last.y}
              stroke={color}
              strokeWidth="1"
              strokeDasharray="4 5"
              strokeOpacity="0.38"
            />
          )}
          {compareLast && (
            <line
              x1={padX}
              x2={width - padX}
              y1={compareLast.y}
              y2={compareLast.y}
              stroke={compareColor}
              strokeWidth="1"
              strokeDasharray="4 5"
              strokeOpacity="0.32"
            />
          )}

          <g mask={`url(#mask-${rawId})`}>
            {showFill && <path d={geometry.area} fill={`url(#fill-${rawId})`} stroke="none" />}
            {geometry.compareLine && (
              <path
                d={geometry.compareLine}
                fill="none"
                stroke={compareColor}
                strokeWidth={Math.max(lineWidth - 0.4, 1.6)}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
            <path
              d={geometry.line}
              fill="none"
              stroke={color}
              strokeWidth={lineWidth + 4}
              strokeLinecap="round"
              strokeOpacity="0.16"
              filter={`url(#glow-${rawId})`}
            />
            <path
              ref={pathRef}
              d={geometry.line}
              fill="none"
              stroke={color}
              strokeWidth={lineWidth}
              strokeLinecap="round"
              strokeLinejoin="round"
              className="spark-draw"
              style={pathLen ? { strokeDasharray: pathLen, strokeDashoffset: pathLen } : undefined}
            />
          </g>

          {showLiveDot && compareLast && (
            <circle cx={compareLast.x} cy={compareLast.y} r="3.4" fill={compareColor} stroke="var(--card)" strokeWidth="2" />
          )}
          {showLiveDot && last && (
            <g>
              <circle cx={last.x} cy={last.y} r="5.2" fill={color} fillOpacity="0.18" />
              <circle cx={last.x} cy={last.y} r="3.6" fill={color} stroke="var(--card)" strokeWidth="2" />
            </g>
          )}
          {cursor && (
            <g>
              <line
                x1={cursor.x}
                x2={cursor.x}
                y1={4}
                y2={plotH - 2}
                stroke="var(--ink-300)"
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              <circle cx={cursor.x} cy={cursor.y} r="4.6" fill={color} stroke="var(--card)" strokeWidth="2" />
            </g>
          )}
          {axisMarks.map((mark) => (
            <text
              key={`${mark.x}-${mark.text}`}
              x={mark.x}
              y={height - 3}
              textAnchor={mark.x <= padX + 1 ? 'start' : mark.x >= width - padX - 1 ? 'end' : 'middle'}
              fill="var(--ink-400)"
              fontSize="10"
              fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            >
              {mark.text}
            </text>
          ))}
        </svg>
      )}
      {showCursorValue && scrub && width > 0 && (
        <div
          className="insight-cursor-pill pointer-events-none absolute -translate-x-1/2 rounded-md px-1.5 py-0.5"
          style={{ left: Math.min(Math.max(scrub.x, 36), width - 36), top: 2 }}
        >
          <span className="font-mono text-micro tnum text-ink-800">
            {formatValue ? formatValue(scrub.value) : scrub.value.toLocaleString('ja-JP')}
          </span>
          {scrub.label && <span className="ml-1 text-micro text-ink-400">{axisTick(scrub.label)}</span>}
        </div>
      )}
    </div>
  );
});

export default InsightLineChart;
