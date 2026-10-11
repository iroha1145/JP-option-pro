/** 指数收盘价：沿用美股 CTA 历史图的线条、图台与游标，不引入仓位口径。 */
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from './ReactECharts';
import type { useChartCursor } from './useChartCursor';
import { baseAnimation, CH, echarts, escapeTooltipText, glassTooltip, withAlpha, type ChartOption } from '@/lib/chart';
import { CHART_TEXT_FONT } from '@/lib/chartFonts';
import { useAppearance } from '@/hooks/useAppearance';
import { fmtPrice } from '@/lib/format';
import { t } from '@/i18n/core';

export interface IndexTrendPoint { value: number; label: string }

function trendOption(points: IndexTrendPoint[], narrow: boolean, dark: boolean): ChartOption {
  const color = CH.brand500;
  const last = points[points.length - 1];
  // 只标约 5 个日期，窄屏减为约 3 个；按图台实际宽度判断。
  const tickStep = Math.max(1, Math.ceil(points.length / (narrow ? 3 : 5)));
  return {
    ...baseAnimation,
    grid: { left: 8, right: 14, top: 12, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((point) => point.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: CH.ink400, fontSize: 10, fontFamily: CHART_TEXT_FONT,
        interval: tickStep - 1, hideOverlap: true, formatter: (date: string) => date.slice(5),
      },
    },
    yAxis: {
      type: 'value', scale: true, position: 'right', splitNumber: 4,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: CH.ink400, fontSize: 10, fontFamily: CHART_TEXT_FONT, formatter: (value: number) => fmtPrice(value) },
      splitLine: { lineStyle: { color: CH.lineChart, width: 1 } },
    },
    tooltip: glassTooltip({
      confine: true,
      padding: [9, 12],
      textStyle: { color: CH.insightTooltipFg, fontSize: 12, fontFamily: CHART_TEXT_FONT },
      axisPointer: { type: 'line', snap: true, lineStyle: { color: dark ? 'rgba(242,242,242,.26)' : 'rgba(17,17,17,.24)', width: 1 } },
      position: (point: number[], _params: unknown, _dom: unknown, _rect: unknown, size: { contentSize: number[]; viewSize: number[] }) => [
        Math.max(0, Math.min(point[0] - size.contentSize[0] / 2, size.viewSize[0] - size.contentSize[0])), 6,
      ],
      formatter: (params: unknown) => {
        const index = (params as { dataIndex: number }[])[0]?.dataIndex;
        const point = points[index];
        if (!point) return '';
        return `<div style="color:${CH.ink400};font-size:11px;margin-bottom:4px">${escapeTooltipText(point.label)}</div>` +
          `<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:8px;height:8px;border-radius:50%;background:${color}"></span>` +
          `<span style="color:${CH.ink400}">${escapeTooltipText(t('收盘'))}</span><strong>${escapeTooltipText(fmtPrice(point.value))}</strong></span>`;
      },
    }),
    series: [{
      type: 'line', name: t('收盘'), data: points.map((point) => point.value),
      showSymbol: false, symbol: 'circle', symbolSize: 6,
      // 每一点都是实际收盘价；直线连接保留真实峰谷，避免平滑产生虚构价位。
      smooth: false,
      lineStyle: {
        width: 1.8, cap: 'round', join: 'round',
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: withAlpha(color, 0) }, { offset: 0.14, color }, { offset: 1, color },
        ]),
      },
      itemStyle: { color, borderColor: CH.endpointRing, borderWidth: 1.5 },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: withAlpha(color, 0.08) }, { offset: 1, color: withAlpha(color, 0) },
      ]) },
      markPoint: {
        symbol: 'circle', symbolSize: 6, silent: true, label: { show: false },
        itemStyle: { color, borderColor: CH.endpointRing, borderWidth: 1.5 },
        data: [{ coord: [points.length - 1, last.value] }],
      },
      markLine: {
        symbol: 'none', silent: true,
        data: [{ yAxis: last.value, lineStyle: { color: withAlpha(color, 0.45), width: 1, type: [5, 5] }, label: { show: false } }],
      },
      z: 3,
    }],
  } as ChartOption;
}

export default function IndexTrendChart({ points, cursor, name }: {
  points: IndexTrendPoint[];
  cursor: ReturnType<typeof useChartCursor>;
  name: string;
}) {
  const appearance = useAppearance();
  const ref = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = (width: number) => setNarrow(width < 280);
    update(el.clientWidth);
    const observer = new ResizeObserver(([entry]) => update(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const option = useMemo(() => trendOption(points, narrow, appearance === 'dark'), [points, narrow, appearance]);
  const point = points[cursor.index ?? points.length - 1];
  return (
    <div className="insight-frame min-w-0 rounded-lg border border-line bg-card-warm p-2">
      <div className="mb-1 flex min-h-6 items-center gap-2 px-1">
        <span className="min-w-0 truncate text-micro text-ink-400">{t('收盘')} · {fmtPrice(point.value)}</span>
        <span className="ml-auto shrink-0 text-micro text-ink-400 tnum">{point.label}</span>
      </div>
      <div {...cursor.sliderProps} ref={ref} aria-label={`${name} ${t('趋势快照')}`} className="h-56 min-w-0 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-brand-600">
        <ReactECharts option={option} onInit={cursor.onInit} prepareOption={cursor.prepareOption} onOptionApplied={cursor.onOptionApplied} ariaLabel={`${name} ${t('收盘')}`} />
      </div>
    </div>
  );
}
