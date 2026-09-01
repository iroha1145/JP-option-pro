/**
 * Beautiful UI Insight Cards 折线：渐变面积 + 终点呼吸点 + 指针/键盘刮擦。
 * 数值按真实点线性连接（不平滑），避免行情被曲线美化。
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
  height?: number;
  /** 固定像素宽；缺省时撑满父级并随 ResizeObserver 重算 */
  width?: number;
  change?: number;
  tone?: 'auto' | 'brand' | 'up' | 'down';
  interactive?: boolean;
  /** 嵌在 Link 内时关掉，避免可聚焦控件套在锚点里 */
  focusable?: boolean;
  showLiveDot?: boolean;
  showCursorValue?: boolean;
  formatValue?: (value: number) => string;
  onScrub?: (point: InsightScrub | null) => void;
  className?: string;
  ariaLabel?: string;
}

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

export function insightStroke(tone: 'up' | 'down' | 'brand'): string {
  if (tone === 'up') return 'var(--up-600)';
  if (tone === 'down') return 'var(--down-600)';
  return 'var(--brand-600)';
}

function buildPath(values: number[], width: number, height: number, padX: number, padY: number) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const innerW = Math.max(width - padX * 2, 1);
  const innerH = Math.max(height - padY * 2, 1);
  const step = values.length > 1 ? innerW / (values.length - 1) : 0;
  const points = values.map((value, index) => ({
    x: padX + index * step,
    y: padY + (1 - (value - min) / span) * innerH,
  }));
  const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join('');
  const last = points[points.length - 1];
  const first = points[0];
  const area = `${line}L${last.x.toFixed(2)},${(height - 1).toFixed(2)}L${first.x.toFixed(2)},${(height - 1).toFixed(2)}Z`;
  return { points, line, area };
}

function pointFromClientX(clientX: number, rect: DOMRect, count: number, padX: number): number {
  if (count <= 1) return 0;
  const x = clientX - rect.left;
  const inner = Math.max(rect.width - padX * 2, 1);
  const ratio = (x - padX) / inner;
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}

const InsightLineChart = memo(function InsightLineChart({
  data,
  height = 72,
  width: fixedWidth,
  change,
  tone = 'auto',
  interactive = true,
  focusable = true,
  showLiveDot = true,
  showCursorValue = false,
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
  const values = useMemo(() => series.map((item) => item.value), [series]);
  const resolvedTone = tone === 'auto' ? insightTone(change) : tone;
  const color = insightStroke(resolvedTone);
  const padX = 8;
  const padY = 10;

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

  const geometry = useMemo(
    () => (values.length >= 2 && width > 0 ? buildPath(values, width, height, padX, padY) : null),
    [values, width, height],
  );

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
  const cursor = scrub && geometry ? geometry.points[scrub.index] : null;
  const liveText = scrub
    ? `${scrub.label ?? ''} ${formatValue ? formatValue(scrub.value) : scrub.value}`.trim()
    : ariaLabel ?? '';

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
            <linearGradient id={`ig-${rawId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.28" />
              <stop offset="70%" stopColor={color} stopOpacity="0.06" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <line
            x1={padX}
            x2={width - padX}
            y1={height - 0.5}
            y2={height - 0.5}
            stroke="var(--line)"
            strokeWidth="1"
          />
          <path d={geometry.area} fill={`url(#ig-${rawId})`} stroke="none" />
          <path
            ref={pathRef}
            d={geometry.line}
            fill="none"
            stroke={color}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="spark-draw"
            style={pathLen ? { strokeDasharray: pathLen, strokeDashoffset: pathLen } : undefined}
          />
          {showLiveDot && last && (
            <g>
              <circle
                className="insight-live-ring"
                cx={last.x}
                cy={last.y}
                r="4.5"
                fill="none"
                stroke={color}
                strokeWidth="1.25"
              />
              <circle cx={last.x} cy={last.y} r="3" fill={color} stroke="var(--card)" strokeWidth="1.5" />
            </g>
          )}
          {cursor && (
            <g>
              <line
                x1={cursor.x}
                x2={cursor.x}
                y1={4}
                y2={height - 2}
                stroke="var(--ink-300)"
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              <circle cx={cursor.x} cy={cursor.y} r="4.5" fill={color} stroke="var(--card)" strokeWidth="2" />
            </g>
          )}
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
          {scrub.label && <span className="ml-1 text-micro text-ink-400">{scrub.label.slice(5)}</span>}
        </div>
      )}
    </div>
  );
});

export default InsightLineChart;
