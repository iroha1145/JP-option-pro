/**
 * ECharts 按需引入 + 全站统一工艺（design.md §6）
 * 发丝网格 / 毛玻璃 tooltip / 绘制动画 / 点阵面积 / 斜纹柱
 */
import * as echarts from 'echarts/core';
import { BarChart, CandlestickChart, CustomChart, LineChart, PieChart } from 'echarts/charts';
import {
  DataZoomComponent,
  DataZoomSliderComponent,
  GraphicComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ComposeOption } from 'echarts/core';
import type { BarSeriesOption, CandlestickSeriesOption, CustomSeriesOption, LineSeriesOption, PieSeriesOption } from 'echarts/charts';
import type {
  DataZoomComponentOption,
  GraphicComponentOption,
  GridComponentOption,
  MarkAreaComponentOption,
  MarkLineComponentOption,
  MarkPointComponentOption,
  TooltipComponentOption,
} from 'echarts/components';
import { CHART_MONO_FONT, CHART_TEXT_FONT } from './chartFonts.ts';
import { directionColors, getColorMode } from './colorPreference.ts';
import { getAppearance, type Appearance } from './themePreference.ts';

/* 2026-10-09 Arc 改版：图表表面色随界面改成纯灰（坐标字、网格、提示框），品牌与涨跌色不变。 */
const CHART_SURFACE = {
  light: {
    ink400: '#6E6E6E',
    ink300: '#C4C4C4',
    lineChart: '#F0F0F0',
    brand600: '#2E46E0',
    brand500: '#3B59F2',
    brand400: '#6B82FF',
    warn600: '#E8930C',
    ai600: '#0B7285',
    tooltipBg: '#FFFFFF',
    tooltipFg: '#525252',
    insightTooltipFg: '#383838',
    endpointRing: '#FFFFFF',
    axisPointer: 'rgba(17,17,17,.24)',
    stipple: 'rgba(46,70,224,.20)',
    stippleFill: 'rgba(46,70,224,.10)',
  },
  dark: {
    ink400: '#8F8F8F',
    ink300: '#4D4D4F',
    lineChart: '#222224',
    brand600: '#6B82FF',
    brand500: '#8B9CFF',
    brand400: '#A8B4FF',
    warn600: '#FACC15',
    ai600: '#4EC4D4',
    tooltipBg: '#161617',
    tooltipFg: '#C7C7C7',
    insightTooltipFg: '#F2F2F2',
    endpointRing: '#161617',
    axisPointer: 'rgba(242,242,242,.26)',
    stipple: 'rgba(107,130,255,.32)',
    stippleFill: 'rgba(107,130,255,.16)',
  },
} as const;

function surface(appearance: Appearance = getAppearance()) {
  return CHART_SURFACE[appearance];
}

echarts.use([
  LineChart, BarChart, CandlestickChart, PieChart, CustomChart,
  GridComponent, TooltipComponent, DataZoomComponent, DataZoomSliderComponent,
  MarkLineComponent, MarkPointComponent, MarkAreaComponent, GraphicComponent,
  CanvasRenderer,
]);

export { CHART_MONO_FONT };

export { echarts };

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | CandlestickSeriesOption
  | PieSeriesOption
  | CustomSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | DataZoomComponentOption
  | MarkLineComponentOption
  | MarkPointComponentOption
  | MarkAreaComponentOption
  | GraphicComponentOption
>;

/** echarts.init 返回的实例类型（供交互层 convertFromPixel/zr 事件使用） */
export type EChartsInstance = ReturnType<typeof echarts.init>;

/* ---------- 调色（与 CSS 变量一致；up/down 随涨跌色彩习惯） ---------- */
export const CH = {
  get ink400() { return surface().ink400; },
  get ink300() { return surface().ink300; },
  get lineChart() { return surface().lineChart; },
  get brand600() { return surface().brand600; },
  get brand500() { return surface().brand500; },
  get brand400() { return surface().brand400; },
  get up600() {
    return directionColors().up600;
  },
  get down600() {
    return directionColors().down600;
  },
  get warn600() { return surface().warn600; },
  get ai600() { return surface().ai600; },
  get tooltipBg() { return surface().tooltipBg; },
  get tooltipFg() { return surface().tooltipFg; },
  get insightTooltipFg() { return surface().insightTooltipFg; },
  get endpointRing() { return surface().endpointRing; },
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

export function withAlpha(hex: string, alpha: number): string {
  const raw = hex.replace('#', '');
  const value = Number.parseInt(raw, 16);
  if (!Number.isFinite(value)) return hex;
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

export function escapeTooltipText(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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
      itemStyle: { color, borderColor: CH.endpointRing, borderWidth: 2, shadowBlur: 10, shadowColor: hexRgba(color, 0.45) },
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
              borderColor: CH.endpointRing,
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
    backgroundColor: CH.tooltipBg,
    borderColor: 'var(--line)',
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: CH.tooltipFg, fontSize: 12, fontFamily: CHART_TEXT_FONT },
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
const stippleCanvases: Partial<Record<Appearance, HTMLCanvasElement>> = {};
export function stipplePattern(): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const appearance = getAppearance();
  if (stippleCanvases[appearance]) return stippleCanvases[appearance]!;
  const c = document.createElement('canvas');
  c.width = 6;
  c.height = 6;
  const ctx = c.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = surface().stipple;
  ctx.beginPath();
  ctx.arc(3, 3, 1.1, 0, Math.PI * 2);
  ctx.fill();
  stippleCanvases[appearance] = c;
  return c;
}

/** 点阵面积（stipple area）series 片段 */
export function stippleAreaStyle(): LineSeriesOption['areaStyle'] {
  const pattern = stipplePattern();
  return pattern
    ? { color: { image: pattern, repeat: 'repeat' } as unknown as string, opacity: 1 }
    : { color: surface().stippleFill };
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
   亚洲习惯下翻转符号，与显示设置 / CH.up600 共用同一快照。 */
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

/** Heat tiles have their own painted surface, independent of the page theme.
 * Use readable ink against that RGB surface, including colors between stops. */
export function heatTextColor(background: string): string {
  const match = background.match(/^rgb\((\d+),(\d+),(\d+)\)$/);
  if (!match) return CH.tooltipFg;
  const linear = match.slice(1).map((value) => {
    const channel = Number(value) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  const luminance = linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  const darkLuminance = ((17 / 255 + 0.055) / 1.055) ** 2.4;
  const darkContrast = (luminance + 0.05) / (darkLuminance + 0.05);
  const whiteContrast = 1.05 / (luminance + 0.05);
  if (Math.max(darkContrast, whiteContrast) < 4.5) return '#000000';
  return whiteContrast > darkContrast ? '#FFFFFF' : '#111111';
}

/** 强度分色阶（§6-5） */
export function strengthColor(score: number): string {
  if (score >= 85) return CH.up600;
  if (score >= 70) return CH.brand600;
  if (score >= 50) return CH.brand400;
  return CH.ink300;
}

export const upColor = (change: number) => (change >= 0 ? CH.up600 : CH.down600);
