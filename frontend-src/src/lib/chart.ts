/**
 * ECharts 按需引入 + 全站统一工艺（design.md §6）
 * 发丝网格 / 毛玻璃 tooltip / 绘制动画 / 点阵面积 / 斜纹柱
 */
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, LineChart, PieChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ComposeOption } from 'echarts/core';
import type { BarSeriesOption, CandlestickSeriesOption, LineSeriesOption, PieSeriesOption } from 'echarts/charts';
import type {
  DataZoomComponentOption,
  GridComponentOption,
  MarkAreaComponentOption,
  MarkLineComponentOption,
  MarkPointComponentOption,
  TooltipComponentOption,
} from 'echarts/components';
import { directionColors, getColorMode } from './colorPreference.ts';

echarts.use([
  LineChart, BarChart, CandlestickChart, PieChart,
  GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent,
  MarkPointComponent, MarkAreaComponent,
  CanvasRenderer,
]);

export { echarts };

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | CandlestickSeriesOption
  | PieSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | DataZoomComponentOption
  | MarkLineComponentOption
  | MarkPointComponentOption
  | MarkAreaComponentOption
>;

/** echarts.init 返回的实例类型（供交互层 convertFromPixel/zr 事件使用） */
export type EChartsInstance = ReturnType<typeof echarts.init>;

/* ---------- 调色（与 CSS 变量一致；up/down 随涨跌色彩习惯） ---------- */
export const CH = {
  ink400: '#626F8B',
  ink300: '#B7BFD3',
  lineChart: '#EDF0F4',
  brand600: '#2E46E0',
  brand500: '#3B59F2',
  brand400: '#6B82FF',
  get up600() {
    return directionColors().up600;
  },
  get down600() {
    return directionColors().down600;
  },
  warn600: '#E8930C',
  ai600: '#0B7285',
};

/* ---------- 通用配置 ---------- */
/* 数据是读的：入场/更新动画统一 300ms cubicOut，range 切换不重复播长动画 */
export const baseAnimation = {
  animationDuration: 300,
  animationDurationUpdate: 300,
  animationEasing: 'cubicOut' as const,
  animationEasingUpdate: 'cubicOut' as const,
};

export function baseGrid(overrides: Partial<GridComponentOption> = {}): GridComponentOption {
  return { left: 8, right: 8, top: 12, bottom: 8, containLabel: true, ...overrides };
}

export function categoryAxis(labels: string[]) {
  return {
    type: 'category' as const,
    data: labels,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: CH.ink400, fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' },
  };
}

export function valueAxis(overrides: Record<string, unknown> = {}) {
  return {
    type: 'value' as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: CH.ink400, fontSize: 11, fontFamily: '"IBM Plex Mono", monospace' },
    splitLine: { lineStyle: { color: CH.lineChart, width: 1 } },
    ...overrides,
  };
}

function hexRgba(hex: string, alpha: number): string {
  const raw = hex.replace('#', '');
  const value = Number.parseInt(raw, 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

/** Beautiful UI Insight Cards：自上而下淡出的面积填充 */
export function insightAreaStyle(color: string = CH.brand600): LineSeriesOption['areaStyle'] {
  return {
    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: hexRgba(color, 0.24) },
      { offset: 0.72, color: hexRgba(color, 0.06) },
      { offset: 1, color: hexRgba(color, 0) },
    ]),
  };
}

export function insightLineColor(change?: number | null): string {
  if (change == null || !Number.isFinite(change) || change === 0) return CH.brand600;
  return change > 0 ? CH.up600 : CH.down600;
}

/** echarts 折线的 Insight Cards 工艺：渐变面积 + 圆角线 + 终点实心点 */
export function insightLineSeries(options: {
  data: Array<number | null>;
  color?: string;
  xAxisIndex?: number;
  yAxisIndex?: number;
  /** 默认样条；成交价这类「每个点都是真实成交」的序列传 false，避免曲线越过从未成交的价位 */
  smooth?: boolean | number;
}): LineSeriesOption {
  const color = options.color ?? CH.brand600;
  const lastIndex = options.data.length - 1;
  const lastValue = options.data[lastIndex];
  return {
    type: 'line',
    data: options.data,
    xAxisIndex: options.xAxisIndex,
    yAxisIndex: options.yAxisIndex,
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 9,
    smooth: options.smooth ?? 0.35,
    lineStyle: { color, width: 2.4, cap: 'round', join: 'round' },
    areaStyle: insightAreaStyle(color),
    emphasis: {
      scale: false,
      itemStyle: { color, borderColor: '#fff', borderWidth: 2, shadowBlur: 10, shadowColor: hexRgba(color, 0.45) },
    },
    markPoint:
      lastValue != null && Number.isFinite(lastValue)
        ? {
            silent: true,
            animation: false,
            symbol: 'circle',
            symbolSize: 8,
            itemStyle: {
              color,
              borderColor: '#FFFFFF',
              borderWidth: 2,
              shadowBlur: 8,
              shadowColor: hexRgba(color, 0.5),
            },
            data: [{ name: 'last', coord: [lastIndex, lastValue] }],
          }
        : undefined,
  };
}

/** 图表 hover 小窗：白底、细边、克制阴影（与美版 cloud-chart-tooltip 同口径） */
export function glassTooltip(overrides: Record<string, unknown> = {}) {
  return {
    trigger: 'axis' as const,
    transitionDuration: 0,
    className: 'cloud-chart-tooltip',
    backgroundColor: '#FFFFFF',
    borderColor: 'var(--line)',
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: '#3D4A68', fontSize: 12, fontFamily: 'Inter, sans-serif' },
    extraCssText:
      'box-shadow:var(--popover-shadow);border-radius:9px;font-variant-numeric:tabular-nums;transition:opacity 140ms ease-out;',
    axisPointer: {
      type: 'line' as const,
      snap: true,
      lineStyle: { color: CH.ink300, width: 1, type: [3, 3] as number[] },
    },
    ...overrides,
  };
}

/* ---------- 点阵面积图 pattern（§6-2） ---------- */
let stippleCanvas: HTMLCanvasElement | null = null;
export function stipplePattern(): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  if (stippleCanvas) return stippleCanvas;
  const c = document.createElement('canvas');
  c.width = 6;
  c.height = 6;
  const ctx = c.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = 'rgba(46,70,224,.20)';
  ctx.beginPath();
  ctx.arc(3, 3, 1.1, 0, Math.PI * 2);
  ctx.fill();
  stippleCanvas = c;
  return c;
}

/** 点阵面积（stipple area）series 片段 */
export function stippleAreaStyle(): LineSeriesOption['areaStyle'] {
  const pattern = stipplePattern();
  return pattern
    ? { color: { image: pattern, repeat: 'repeat' } as unknown as string, opacity: 1 }
    : { color: 'rgba(46,70,224,.10)' };
}

/* ---------- 斜纹柱 decal（§6-3） ---------- */
export function hatchDecal(color = CH.brand600) {
  return {
    symbol: 'rect',
    symbolSize: 1,
    rotation: Math.PI / 4,
    dashArrayX: [1, 0] as [number, number],
    dashArrayY: [1.2, 4] as [number, number],
    color,
    symbolKeepAspect: true,
  };
}

/* ---------- 涨跌热力色阶（§1.7 连续映射） ----------
   色阶两端是「涨/跌」不是固定绿/红。基表按西方习惯（绿涨红跌）；
   亚洲习惯下翻转符号，与 ColorModeSwitcher / CH.up600 共用同一快照。 */
const HEAT_STOPS: { pct: number; rgb: [number, number, number] }[] = [
  { pct: -3, rgb: [214, 53, 59] },
  { pct: -1.5, rgb: [240, 131, 127] },
  { pct: 0, rgb: [241, 239, 232] },
  { pct: 1.5, rgb: [124, 207, 169] },
  { pct: 3, rgb: [14, 159, 110] },
];

export function heatColor(pct: number): string {
  const signed = getColorMode() === 'asian' ? -pct : pct;
  const clamped = Math.max(-3, Math.min(3, signed));
  for (let i = 0; i < HEAT_STOPS.length - 1; i++) {
    const a = HEAT_STOPS[i];
    const b = HEAT_STOPS[i + 1];
    if (clamped >= a.pct && clamped <= b.pct) {
      const t = (clamped - a.pct) / (b.pct - a.pct);
      const mix = a.rgb.map((v, k) => Math.round(v + (b.rgb[k] - v) * t));
      return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
    }
  }
  return 'rgb(241,239,232)';
}

/** 强度分色阶（§6-5） */
export function strengthColor(score: number): string {
  if (score >= 85) return CH.up600;
  if (score >= 70) return CH.brand600;
  if (score >= 50) return CH.brand400;
  return CH.ink300;
}

export const upColor = (change: number) => (change >= 0 ? CH.up600 : CH.down600);
