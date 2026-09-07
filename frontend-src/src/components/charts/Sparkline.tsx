/**
 * 迷你 sparkline（design.md §6-4）
 * variant="line"：默认 48×20、1.5px 折线、涨跌着色、无轴；表格单元用。
 * variant="area"：卡片折线图——细线 + 极浅面积 + 小端点。
 * 小图保持真实观测点间的折线。两者都保留首绘 draw-line。
 */
import { memo, useId, useMemo } from 'react';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  change: number;
  variant?: 'line' | 'area';
  stretch?: boolean;
  className?: string;
}

type Pt = readonly [number, number];

function toPoints(data: number[], w: number, h: number, pad: number): Pt[] {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = (w - pad * 2) / (data.length - 1);
  return data.map((v, i) => [pad + i * step, h - pad - ((v - min) / span) * (h - pad * 2)] as const);
}

const straight = (pts: Pt[]): string =>
  pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join('');

const Sparkline = memo(function Sparkline({
  data,
  width = 48,
  height = 20,
  change,
  variant = 'line',
  stretch = false,
  className,
}: SparklineProps) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');
  const isArea = variant === 'area';
  const pad = isArea ? 5 : 2;
  const { line, area, last } = useMemo(() => {
    if (data.length < 2) return { line: '', area: '', last: null as Pt | null };
    const pts = toPoints(data, width, height, pad);
    const path = straight(pts);
    return {
      line: path,
      area: `${path}L${pts[pts.length - 1][0].toFixed(1)},${height}L${pts[0][0].toFixed(1)},${height}Z`,
      last: pts[pts.length - 1],
    };
  }, [data, width, height, pad]);

  const color = change > 0 ? 'var(--up-600)' : change < 0 ? 'var(--down-600)' : 'var(--ink-400)';

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={stretch ? 'none' : undefined}
      className={className}
      aria-hidden="true"
      role="presentation"
    >
      {isArea && (
        <defs>
          <linearGradient id={`fill-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.06" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {isArea && <path d={area} fill={`url(#fill-${id})`} stroke="none" />}
      <path
        d={line}
        pathLength={1}
        fill="none"
        stroke={color}
        strokeWidth={isArea ? 1.65 : 1.4}
        strokeOpacity="0.82"
        vectorEffect="non-scaling-stroke"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="spark-draw"
        style={{ strokeDasharray: 1, strokeDashoffset: 1, animationDuration: '500ms' }}
      />
      {isArea && last && (
        <circle cx={last[0]} cy={last[1]} r="1.9" fill={color} stroke="var(--card)" strokeWidth="1.25" />
      )}
    </svg>
  );
});

export default Sparkline;
