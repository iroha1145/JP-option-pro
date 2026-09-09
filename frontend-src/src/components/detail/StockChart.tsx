/** 个股日线：日本站工具条 + 美国站智能画线 / 多副图 / 图层菜单。
 *  盘中/逐笔仍走 children；面积与不复权保持原行为，不画分析图层。 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import EmptyState from '@/components/shared/EmptyState';
import InfoHint from '@/components/shared/InfoHint';
import Segmented from '@/components/shared/Segmented';
import MenuSelect from '@/components/shared/MenuSelect';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { STRUCTURE_HINTS } from '@/lib/indicatorHints';
import {
  CH,
  CHART_MONO_FONT,
  baseAnimation,
  baseGrid,
  categoryAxis,
  escapeTooltipText,
  glassTooltip,
  insightLineColor,
  insightLineSeries,
  valueAxis,
  withAlpha,
  type ChartOption,
  type EChartsInstance,
} from '@/lib/chart';
import { DUR_FAST, DUR_UI, EASE_PAPER } from '@/lib/motion';
import { useColorMode } from '@/hooks/useColorMode';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtPrice, fmtShares, fmtYenCompact } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { StockBar, TechnicalStructure } from '@/api/types';
import IndicatorReadouts from './chart-indicators/IndicatorReadouts';
import {
  formatIndicatorValue,
  indicatorLayout,
  selectIndicatorPanes,
  type IndicatorView,
} from './chart-indicators/layout.ts';
import {
  analysisGate,
  barFingerprint,
  filterOverlays,
  filterPanes,
  labelBudget,
  mapChartAnalysis,
} from './chart-drawings/analysis/mapBundle.ts';
import { detectSmartLines, selectSmartOverlays, withChartIndices } from './chart-drawings/analysis/smartLines.ts';
import { prepareStructuralOverlays } from './chart-drawings/analysis/structuralOverlays.ts';
import { detectPriceGaps } from './chart-drawings/analysis/priceGaps.ts';
import { overlaysToMarks, overlaysToSeries, panesToOption } from './chart-drawings/analysis/overlaysToMarks.ts';
import { loadLayerSettings, saveLayerSettings, type LayerSettings } from './chart-drawings/analysis/settings.ts';
import AnalysisLegend from './chart-drawings/AnalysisLegend';
import LayerMenu from './chart-drawings/LayerMenu';
import { clippedLineSeries, isClippedLine } from './chart-drawings/clippedLines';
import { barKeyOf } from './chart-drawings/projection.ts';
import { insideZoom, zoomFromOption, type ZoomWindow } from './chart-drawings/zoom.ts';

export type ChartInterval = '1d' | '60m' | '5m' | '1m' | 'tick';
export type ChartRange = '3m' | '6m' | '1y' | '3y' | '10y';
export type PriceMode = 'adjusted' | 'raw';
type ChartStyle = 'candle' | 'area';

type AnalysisBar = {
  t: string;
  key: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  closed: true;
};

function pickPrice(
  bar: StockBar,
  mode: PriceMode,
  adj: 'adj_open' | 'adj_high' | 'adj_low' | 'adj_close',
  raw: 'open' | 'high' | 'low' | 'close',
): number | null {
  return mode === 'adjusted' ? (bar[adj] ?? bar[raw]) : bar[raw];
}

function movingAverage(values: Array<number | null>, period: number): Array<number | null> {
  return values.map((_, index) => {
    if (index < period - 1) return null;
    let sum = 0;
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const value = values[cursor];
      if (value == null || !Number.isFinite(value)) return null;
      sum += value;
    }
    return sum / period;
  });
}

function toAnalysisBars(rows: StockBar[], mode: PriceMode): AnalysisBar[] {
  const out: AnalysisBar[] = [];
  for (const bar of rows) {
    const o = pickPrice(bar, mode, 'adj_open', 'open');
    const h = pickPrice(bar, mode, 'adj_high', 'high');
    const l = pickPrice(bar, mode, 'adj_low', 'low');
    const c = pickPrice(bar, mode, 'adj_close', 'close');
    if (c == null || !Number.isFinite(c) || c <= 0) continue;
    const open = o ?? c;
    const high = h ?? c;
    const low = l ?? c;
    if (![open, high, low].every((value) => Number.isFinite(value) && value > 0)) continue;
    if (high < low || c > high * 1.0001 || c < low * 0.9999) continue;
    out.push({
      t: bar.trade_date,
      key: bar.trade_date,
      o: open,
      h: high,
      l: low,
      c,
      v: Math.max(0, (mode === 'adjusted' ? bar.adj_volume : bar.volume) ?? 0),
      closed: true,
    });
  }
  return out;
}

function barsForFingerprint(bundleDates: string[], bars: AnalysisBar[]): AnalysisBar[] {
  const byDate = new Map(bars.map((bar) => [bar.t.slice(0, 10), bar]));
  const rows: AnalysisBar[] = [];
  for (const day of bundleDates) {
    const bar = byDate.get(day);
    if (!bar) return [];
    rows.push(bar);
  }
  return rows;
}

function autoPatternName(kind: string, subtype?: string | null): string | null {
  if (kind === 'support_trend') return subtype === 'horizontal' ? t('水平支撑') : subtype === 'falling' ? t('下降支撑') : t('上升支撑');
  if (kind === 'resistance_trend') return subtype === 'horizontal' ? t('水平阻力') : subtype === 'rising' ? t('上升阻力') : t('下降阻力');
  if (kind === 'channel') return subtype === 'horizontal' ? t('水平通道') : subtype === 'falling' ? t('下降通道') : t('上升通道');
  if (kind === 'triangle') {
    if (subtype === 'ascending') return t('上升三角形');
    if (subtype === 'descending') return t('下降三角形');
    return t('对称三角形');
  }
  if (kind === 'wedge') return subtype === 'falling' ? t('下降楔形') : t('上升楔形');
  if (kind === 'box') return t('水平箱体');
  return null;
}

function toggleButtonCls(active: boolean): string {
  return cn(
    'min-h-8 rounded-xs border px-2 py-0.5 text-micro outline-none transition-colors duration-fast',
    active
      ? 'border-brand-400 bg-brand-50 text-brand-700 shadow-chip'
      : 'border-line text-ink-400 hover:text-ink-600 focus-visible:text-ink-600',
  );
}

function OverlayLegend({
  style,
  overlays,
  showOverlays,
}: {
  style: ChartStyle;
  overlays?: TechnicalStructure['chart_overlays'] | null;
  showOverlays: boolean;
}) {
  const chip = (symbol: ReactNode, label: string) => (
    <span className="inline-flex items-center gap-1">
      {symbol}
      <span>{label}</span>
    </span>
  );
  const hasBase = Boolean(
    showOverlays && overlays?.resistance_high != null && overlays?.resistance_low != null,
  );
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-400">
      <span className="inline-flex items-center gap-1 text-ink-500">
        {t('图例')}
        <InfoHint hint={STRUCTURE_HINTS.chart_overlays} align="start" size={12} />
      </span>
      {style === 'area' ? (
        <span>{t('面积图不叠加阻力带与均线')}</span>
      ) : (
        <>
          {hasBase
            && chip(
              <span className="inline-block h-2 w-4 rounded-xs bg-brand-400/30" aria-hidden />,
              t('阻力带（整理区上沿）'),
            )}
          {hasBase
            && chip(
              <span className="inline-block h-0 w-4 border-t border-dotted border-down-600" aria-hidden />,
              t('失效位'),
            )}
          {chip(<span aria-hidden className="text-warn-600" style={{ fontSize: 8 }}>▼</span>, t('确认摆动高点'))}
          {chip(<span aria-hidden className="text-ai-600" style={{ fontSize: 8 }}>▲</span>, t('确认摆动低点'))}
          {chip(
            <span className="inline-block h-0 w-4 border-t border-dashed border-brand-500" aria-hidden />,
            t('MA20 · 最近 20 根常规时段收盘的均线'),
          )}
        </>
      )}
    </p>
  );
}

function legacyCandleOption(
  rows: StockBar[],
  priceMode: PriceMode,
  overlays: TechnicalStructure['chart_overlays'] | null | undefined,
): ChartOption {
  const dates = rows.map((bar) => bar.trade_date);
  const shortDates = dates.map((date) => date.slice(2));
  const closes = rows.map((bar) => pickPrice(bar, priceMode, 'adj_close', 'close'));
  const candles = rows.map((bar) => [
    pickPrice(bar, priceMode, 'adj_open', 'open'),
    pickPrice(bar, priceMode, 'adj_close', 'close'),
    pickPrice(bar, priceMode, 'adj_low', 'low'),
    pickPrice(bar, priceMode, 'adj_high', 'high'),
  ]);
  const turnover = rows.map((bar) => bar.turnover_value);
  const ma20 = movingAverage(closes, 20);
  const markLines: Record<string, unknown>[] = [];
  const markPoints: ({ name: string } & Record<string, unknown>)[] = [];
  const showOverlays = priceMode === 'adjusted' && overlays;
  if (showOverlays) {
    if (overlays.invalidation_price != null) {
      markLines.push({
        yAxis: overlays.invalidation_price,
        lineStyle: { color: CH.down600, type: 'dotted', width: 1 },
        label: { formatter: t('失效位'), position: 'insideEndBottom', color: CH.down600, fontSize: 10 },
      });
    }
    const markSwing = (points: { trade_date: string; price: number | null }[], isHigh: boolean) => {
      for (const point of points.slice(-3)) {
        const index = dates.indexOf(point.trade_date);
        if (index >= 0 && point.price != null) {
          markPoints.push({
            name: isHigh ? 'swing-high' : 'swing-low',
            coord: [index, point.price],
            symbol: 'triangle',
            symbolRotate: isHigh ? 180 : 0,
            symbolSize: 8,
            itemStyle: { color: isHigh ? CH.warn600 : CH.ai600 },
            label: { show: false },
          });
        }
      }
    };
    markSwing(overlays.swing_highs ?? [], true);
    markSwing(overlays.swing_lows ?? [], false);
  }
  return {
    ...baseAnimation,
    grid: [
      baseGrid({ top: 8, bottom: '24%', left: 4, right: 48 }),
      baseGrid({ top: '80%', bottom: 2, left: 4, right: 48 }),
    ],
    tooltip: glassTooltip({ trigger: 'axis' }),
    xAxis: [
      { ...categoryAxis(shortDates), gridIndex: 0 },
      { ...categoryAxis(shortDates), gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { ...valueAxis({ scale: true, position: 'right' }), gridIndex: 0 },
      { ...valueAxis(), gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      {
        type: 'candlestick' as const,
        data: candles,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: CH.up600,
          color0: CH.down600,
          borderColor: CH.up600,
          borderColor0: CH.down600,
        },
        markLine: { symbol: 'none', animation: false, data: markLines },
        markPoint: { animation: false, data: markPoints },
        ...(showOverlays && overlays.resistance_high != null && overlays.resistance_low != null
          ? {
              markArea: {
                silent: true,
                itemStyle: { color: CH.brand400, opacity: 0.08 },
                data: [
                  [{ yAxis: overlays.resistance_low }, { yAxis: overlays.resistance_high }] as [
                    { yAxis: number },
                    { yAxis: number },
                  ],
                ],
              },
            }
          : {}),
      },
      {
        type: 'line' as const,
        data: ma20,
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { color: CH.brand500, width: 1.2, type: 'dashed' as const },
        tooltip: { show: false },
      },
      {
        type: 'bar' as const,
        data: turnover,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: { color: CH.brand400, opacity: 0.4 },
      },
    ],
  } as ChartOption;
}

export default function StockChart({
  displayCode,
  ticker,
  interval,
  onInterval,
  range,
  onRange,
  priceMode,
  onPriceMode,
  bars,
  barsLoading,
  overlays,
  analysis,
  onRetry,
  children,
}: {
  displayCode: string;
  ticker?: string;
  interval: ChartInterval;
  onInterval: (value: ChartInterval) => void;
  range: ChartRange;
  onRange: (value: ChartRange) => void;
  priceMode: PriceMode;
  onPriceMode: (value: PriceMode) => void;
  bars?: StockBar[];
  barsLoading: boolean;
  overlays?: TechnicalStructure['chart_overlays'] | null;
  analysis?: TechnicalStructure['chart_analysis'] | Record<string, unknown> | null;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  const [style, setStyle] = useState<ChartStyle>('candle');
  const [smartDrawingEnabled, setSmartDrawingEnabled] = useState(true);
  const [indicatorView, setIndicatorView] = useState<IndicatorView>('single');
  const [selectedIndicator, setSelectedIndicator] = useState('macd');
  const [layersOpen, setLayersOpen] = useState(false);
  const [narrowIndicators, setNarrowIndicators] = useState(false);
  const [chartInst, setChartInst] = useState<EChartsInstance | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef<{ scope: string; window: ZoomWindow } | null>(null);
  const colorMode = useColorMode();
  const { username, isOwner, isCustomer } = useAccess();
  const identityKey = isCustomer && username ? `account:${username}` : isOwner ? 'owner' : 'anonymous';
  const [layersIdentity, setLayersIdentity] = useState(identityKey);
  const [layerSettings, setLayerSettings] = useState<LayerSettings>(() => loadLayerSettings(identityKey));
  if (layersIdentity !== identityKey) {
    setLayersIdentity(identityKey);
    setLayerSettings(loadLayerSettings(identityKey));
  }
  const persistLayers = (next: LayerSettings) => {
    setLayerSettings(next);
    saveLayerSettings(layersIdentity, next);
  };
  const daily = interval === '1d';
  const rows = bars ?? [];
  const analysisBars = useMemo(() => toAnalysisBars(rows, priceMode), [rows, priceMode]);
  const analysisBundle = useMemo(() => mapChartAnalysis(analysis ?? null), [analysis]);
  const gatedBars = useMemo(
    () => (analysisBundle ? barsForFingerprint(analysisBundle.dates, analysisBars) : []),
    [analysisBundle, analysisBars],
  );
  const visibleFingerprint = gatedBars.length ? barFingerprint(gatedBars) : null;
  const gateReason = analysisGate(analysisBundle, {
    range: '1d',
    adjustment: 'adjusted',
    ticker: ticker || analysisBundle?.ticker || '',
    dataThrough: analysisBundle?.dataThrough,
    barCount: gatedBars.length || null,
    lastClose: gatedBars.length ? gatedBars[gatedBars.length - 1]?.c ?? null : null,
    fingerprint: visibleFingerprint,
  });
  const analysisOk = daily && style === 'candle' && priceMode === 'adjusted' && gateReason === 'ok';
  const chartKeys = useMemo(() => analysisBars.map((bar) => barKeyOf(bar, '1d')), [analysisBars]);
  const smartBars = useMemo(
    () => withChartIndices(gatedBars.map((bar) => ({ ...bar, key: bar.key })), chartKeys),
    [gatedBars, chartKeys],
  );
  const smartProposals = useMemo(() => {
    if (!analysisOk || !smartDrawingEnabled
      || !layerSettings.enabled.some((id) => id === 'auto_patterns' || id === 'support_resistance')) return [];
    return detectSmartLines(smartBars);
  }, [analysisOk, smartDrawingEnabled, smartBars, layerSettings.enabled]);
  const gapProposals = useMemo(() => {
    if (!analysisOk || !layerSettings.enabled.includes('gaps')) return [];
    return detectPriceGaps(smartBars, '1d');
  }, [analysisOk, smartBars, layerSettings.enabled]);
  const visibleOverlays = useMemo(() => {
    if (!analysisOk || !analysisBundle) return [];
    if (!smartDrawingEnabled) {
      const filtered = filterOverlays([...analysisBundle.overlays, ...gapProposals], layerSettings);
      const gaps = filtered.filter((row) => row.kind === 'gap')
        .sort((a, b) => b.displayPriority - a.displayPriority || a.id.localeCompare(b.id, 'en')).slice(0, 4);
      return [...filtered.filter((row) => row.kind !== 'gap'), ...gaps];
    }
    const candidates = filterOverlays(
      prepareStructuralOverlays([...analysisBundle.overlays, ...smartProposals, ...gapProposals], smartBars),
      { ...layerSettings, maxPatterns: 64 },
    );
    return selectSmartOverlays(candidates, smartBars, layerSettings.maxPatterns);
  }, [analysisOk, analysisBundle, layerSettings, smartDrawingEnabled, smartProposals, smartBars, gapProposals]);
  const visiblePanes = useMemo(() => {
    if (!analysisOk || !analysisBundle) return [];
    return filterPanes(analysisBundle.indicatorPanes, layerSettings);
  }, [analysisOk, analysisBundle, layerSettings]);
  const visibleLabels = useMemo(
    () => labelBudget(visibleOverlays, layerSettings),
    [visibleOverlays, layerSettings],
  );
  const extraMarks = useMemo(() => {
    if (!analysisOk || !analysisBars.length) return { lines: [], points: [], areas: [], polygons: [] };
    const prices = analysisBars.flatMap((bar) => [bar.h, bar.l]);
    return overlaysToMarks(visibleOverlays, {
      bars: analysisBars,
      range: '1d',
      xMin: 0,
      xMax: analysisBars.length - 1,
      yMin: Math.min(...prices),
      yMax: Math.max(...prices),
    }, autoPatternName, new Set(visibleLabels.map((item) => item.id)));
  }, [analysisOk, analysisBars, visibleOverlays, visibleLabels]);
  const analysisOption = useMemo(() => {
    const showMa20 = layerSettings.enabled.includes('ma20');
    const extraMa = (analysisOk
      ? overlaysToSeries(visibleOverlays, analysisBars, '1d')
      : []
    )
      .filter((line) => line.id !== 'ma20')
      .map((line) => ({ name: line.name, data: line.data }));
    const limited = selectIndicatorPanes(visiblePanes, indicatorView, selectedIndicator);
    const panes = analysisOk && style === 'candle'
      ? panesToOption(limited, analysisBars, '1d')
      : [];
    return {
      showMa20: style === 'candle' && showMa20,
      extraMa: style === 'candle' ? extraMa : [],
      panes,
      layout: indicatorLayout(420, panes.length, narrowIndicators),
    };
  }, [analysisOk, analysisBars, style, visibleOverlays, visiblePanes, layerSettings, indicatorView, selectedIndicator, narrowIndicators]);

  const zoomScope = `${ticker ?? displayCode}|${range}|${priceMode}|${style}`;
  useEffect(() => { zoomRef.current = null; }, [zoomScope]);
  useEffect(() => {
    const chart = chartInst;
    if (!chart || chart.isDisposed()) return;
    const handler = () => {
      if (chart.isDisposed()) return;
      const next = zoomFromOption(chart.getOption() as { dataZoom?: { startValue?: unknown; endValue?: unknown }[] }, analysisBars.length);
      if (next) zoomRef.current = { scope: zoomScope, window: next };
    };
    chart.on('datazoom', handler);
    return () => {
      if (!chart.isDisposed()) chart.off('datazoom', handler);
    };
  }, [chartInst, analysisBars.length, zoomScope]);

  useEffect(() => {
    const node = plotRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      setNarrowIndicators(entry.contentRect.width < 520);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const option = useMemo((): ChartOption | null => {
    void colorMode;
    if (!daily || rows.length === 0) return null;
    const closes = rows.map((bar) => pickPrice(bar, priceMode, 'adj_close', 'close'));
    const first = closes.find((value) => value != null);
    const last = [...closes].reverse().find((value) => value != null);
    const change = first != null && last != null ? last - first : null;
    if (style === 'area') {
      return {
        grid: baseGrid({ top: 8, bottom: 8, left: 4, right: 48 }),
        tooltip: glassTooltip({ trigger: 'axis' }),
        xAxis: categoryAxis(rows.map((bar) => bar.trade_date.slice(2))),
        yAxis: valueAxis({ scale: true, position: 'right' }),
        series: [
          insightLineSeries({
            data: closes,
            color: insightLineColor(change),
            smooth: false,
          }),
        ],
      } as ChartOption;
    }
    if (!analysisOk) return legacyCandleOption(rows, priceMode, overlays);

    const labels = analysisBars.map((bar) => bar.t.slice(2));
    const candleData = analysisBars.map((bar) => ({ value: [bar.o, bar.c, bar.l, bar.h] }));
    const volData = analysisBars.map((bar) => ({
      value: bar.v,
      itemStyle: { color: withAlpha(bar.c >= bar.o ? CH.up600 : CH.down600, 0.4) },
    }));
    const ma20 = movingAverage(analysisBars.map((bar) => bar.c), 20);
    const panes = analysisOption.panes;
    const grids = analysisOption.layout.grids;
    const railSeries = clippedLineSeries(extraMarks.lines);
    const marks = {
      lines: extraMarks.lines.filter((line) => !isClippedLine(line)),
      points: extraMarks.points,
      areas: extraMarks.areas,
    };
    const polygons = extraMarks.polygons ?? [];
    const fillSeries = polygons.length
      ? {
          type: 'custom' as const,
          name: 'drawing-fills',
          clip: true,
          silent: true,
          xAxisIndex: 0,
          yAxisIndex: 0,
          z: 2,
          data: polygons,
          renderItem: (params: { dataIndex: number }, api: { coord: (value: number[]) => number[] }) => {
            const poly = polygons[params.dataIndex];
            if (!poly) return;
            return {
              type: 'polygon',
              shape: { points: poly.vertices.map((vertex) => api.coord([vertex.x, vertex.y])) },
              style: { fill: poly.color, opacity: poly.opacity },
              silent: true,
            };
          },
        }
      : null;
    const paneSeries = panes.flatMap((pane, paneIndex) => {
      const axis = paneIndex + 2;
      return pane.series.map((row, seriesIndex) => ({
        type: row.type === 'bar' ? ('bar' as const) : ('line' as const),
        name: row.name,
        xAxisIndex: axis,
        yAxisIndex: axis,
        data: row.data,
        showSymbol: false,
        connectNulls: true,
        barMaxWidth: 8,
        lineStyle: {
          color: seriesIndex === 0 ? CH.brand500 : seriesIndex === 1 ? CH.ai600 : CH.ink400,
          width: 1,
        },
        itemStyle: row.type === 'bar' ? { color: CH.ink400 } : undefined,
        tooltip: { show: true },
        z: 2,
      }));
    });
    return {
      ...baseAnimation,
      axisPointer: { link: [{ xAxisIndex: 'all' as const }] },
      grid: grids,
      dataZoom: insideZoom(analysisBars.length, grids.map((_, index) => index), zoomRef.current?.scope === zoomScope ? zoomRef.current.window : null),
      xAxis: grids.map((_, index) => ({
        type: 'category' as const,
        gridIndex: index,
        data: labels,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: index === grids.length - 1
          ? { color: CH.ink400, fontSize: 11, fontFamily: CHART_MONO_FONT, hideOverlap: true }
          : { show: false },
      })),
      yAxis: grids.map((_, index) => {
        const pane = index >= 2 ? panes[index - 2] : null;
        return {
          type: 'value' as const,
          gridIndex: index,
          scale: pane?.yMin == null && pane?.yMax == null,
          min: pane?.yMin,
          max: pane?.yMax,
          position: 'right' as const,
          axisLine: { show: false },
          axisTick: { show: false },
          splitNumber: index === 0 ? 5 : 3,
          axisLabel: index === 0
            ? { color: CH.ink400, fontSize: 11, fontFamily: CHART_MONO_FONT }
            : { color: CH.ink400, fontSize: 10, fontFamily: CHART_MONO_FONT, hideOverlap: true, formatter: formatIndicatorValue, margin: 8 },
          splitLine: index === 0
            ? { lineStyle: { color: CH.lineChart, width: 1 } }
            : { show: false },
        };
      }),
      tooltip: glassTooltip({
        trigger: 'axis',
        axisPointer: {
          type: 'cross' as const,
          lineStyle: { color: CH.ink300, width: 1, type: [3, 3] as number[] },
          crossStyle: { color: CH.ink300, width: 1, type: [3, 3] as number[] },
        },
        formatter: (params: unknown) => {
          const list = params as { seriesType?: string; dataIndex: number }[];
          const idx = list.find((row) => row.seriesType === 'candlestick')?.dataIndex ?? list[0]?.dataIndex ?? 0;
          const bar = analysisBars[idx];
          if (!bar) return '';
          const chg = bar.c - bar.o;
          const color = chg >= 0 ? CH.up600 : CH.down600;
          const row = (key: string, value: string) =>
            `<div style="display:flex;justify-content:space-between;gap:16px"><span style="color:#6F7B9E">${escapeTooltipText(key)}</span><span>${value}</span></div>`;
          return (
            `<div style="font-family:${CHART_MONO_FONT};font-size:12px;line-height:19px;min-width:150px">` +
            `<div style="color:#6F7B9E;margin-bottom:2px">${bar.t}</div>` +
            row(t('开'), fmtPrice(bar.o)) +
            row(t('高'), fmtPrice(bar.h)) +
            row(t('低'), fmtPrice(bar.l)) +
            row(t('收'), `<b style="color:${color}">${fmtPrice(bar.c)}</b>`) +
            row(t('量'), fmtShares(bar.v)) +
            panes.flatMap((pane) => pane.series.map((series) => {
              const value = series.data[idx];
              if (value == null) return '';
              return row(series.name, formatIndicatorValue(value));
            })).join('') +
            `</div>`
          );
        },
      }),
      series: [
        {
          type: 'candlestick' as const,
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: candleData,
          itemStyle: {
            color: CH.up600,
            color0: CH.down600,
            borderColor: CH.up600,
            borderColor0: CH.down600,
            borderWidth: 1,
          },
          barMaxWidth: 14,
          markLine: marks.lines.length ? { symbol: 'none', silent: true, data: marks.lines } : undefined,
          markPoint: marks.points.length ? { symbol: 'circle', symbolSize: 7, silent: true, data: marks.points } : undefined,
          markArea: marks.areas.length ? { silent: true, data: marks.areas } : undefined,
          z: 3,
        },
        ...(analysisOption.showMa20 ? [{
          type: 'line' as const,
          name: 'MA20',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma20,
          showSymbol: false,
          connectNulls: true,
          lineStyle: { color: CH.brand500, width: 1.5, type: [4, 4] as number[] },
          tooltip: { show: false },
          z: 4,
        }] : []),
        ...analysisOption.extraMa.map((line) => ({
          type: 'line' as const,
          name: line.name,
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: line.data,
          showSymbol: false,
          connectNulls: true,
          lineStyle: { color: CH.ink400, width: 1, type: [4, 4] as number[] },
          tooltip: { show: false },
          z: 4,
        })),
        {
          type: 'bar' as const,
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volData,
          barMaxWidth: 12,
          tooltip: { show: false },
          z: 2,
        },
        ...paneSeries.map((series, index) => {
          const paneMeta = panes.find((_, paneIndex) => {
            const start = panes.slice(0, paneIndex).reduce((sum, pane) => sum + pane.series.length, 0);
            return index >= start && index < start + panes[paneIndex].series.length;
          });
          const paneIndex = panes.findIndex((pane) => pane === paneMeta);
          const isFirstOfPane = paneMeta
            ? index === panes.slice(0, paneIndex).reduce((sum, pane) => sum + pane.series.length, 0)
            : false;
          return {
            ...series,
            markLine: isFirstOfPane && paneMeta?.markLines?.length
              ? {
                  symbol: 'none',
                  silent: true,
                  data: paneMeta.markLines.map((value) => ({
                    yAxis: value,
                    lineStyle: { color: CH.ink300, width: 1, type: [4, 4] as number[] },
                    label: { show: false },
                  })),
                }
              : undefined,
          };
        }),
        ...(fillSeries ? [fillSeries] : []),
        ...(railSeries ? [railSeries] : []),
      ],
    } as ChartOption;
  }, [analysisBars, analysisOk, analysisOption, colorMode, daily, extraMarks, overlays, priceMode, rows, style, zoomScope]);

  const prepareOption = useCallback((next: ChartOption): ChartOption => {
    const saved = zoomRef.current;
    if (!saved || saved.scope !== zoomScope || !Array.isArray(next.dataZoom)) return next;
    const restored = insideZoom(analysisBars.length, [], saved.window)?.[0];
    if (!restored) return next;
    return {
      ...next,
      dataZoom: next.dataZoom.map((row) => ({
        ...row, startValue: restored.startValue, endValue: restored.endValue,
      })),
    };
  }, [analysisBars.length, zoomScope]);

  const chartHeight = analysisOk ? analysisOption.layout.height : 420;

  return (
    <section
      className="card-surface p-5 xl:col-span-8"
      aria-label={t('{code} K线图', { code: displayCode })}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <Segmented<ChartInterval>
            options={[
              { value: '1d', label: t('日K') },
              { value: '60m', label: t('60分') },
              { value: '5m', label: t('5分') },
              { value: '1m', label: t('1分') },
              { value: 'tick', label: t('逐笔') },
            ]}
            value={interval}
            onChange={onInterval}
          />
          {daily && (
            <Segmented<ChartRange>
              options={(['3m', '6m', '1y', '3y', '10y'] as ChartRange[]).map((value) => ({
                value,
                label: value.toUpperCase(),
              }))}
              value={range}
              onChange={onRange}
              className="[&_button]:font-mono [&_button]:text-micro"
            />
          )}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {daily && (
            <Segmented<ChartStyle>
              options={[
                { value: 'candle', label: t('K 线') },
                { value: 'area', label: t('面积') },
              ]}
              value={style}
              onChange={setStyle}
            />
          )}
          {daily && (
            <Segmented<PriceMode>
              options={[
                { value: 'adjusted', label: t('复权') },
                { value: 'raw', label: t('不复权') },
              ]}
              value={priceMode}
              onChange={onPriceMode}
            />
          )}
        </span>
      </div>
      {daily && style === 'candle' && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-pressed={smartDrawingEnabled}
            disabled={!analysisOk || !layerSettings.enabled.some((id) => id === 'auto_patterns' || id === 'support_resistance')}
            title={t('根据已收盘 K 线识别支撑、阻力和形态，并合并相近线条')}
            onClick={() => setSmartDrawingEnabled((value) => !value)}
            className={cn(toggleButtonCls(smartDrawingEnabled), 'disabled:cursor-not-allowed disabled:opacity-50')}
          >
            {t('智能画线')}
          </button>
          <button
            type="button"
            aria-pressed={layersOpen}
            onClick={() => setLayersOpen(true)}
            className={toggleButtonCls(layersOpen)}
          >
            {t('算法与图层')}
          </button>
          {priceMode === 'raw' && (
            <span className="text-micro text-ink-400">{t('不复权视图不叠加算法线与副图')}</span>
          )}
        </div>
      )}
      {daily && style === 'area' && (
        <p className="mt-2 text-micro text-ink-400">{t('面积图不支持副图与均线叠加')}</p>
      )}
      {daily && analysisOk && (
        <div className="mt-2 flex flex-wrap items-center gap-2" data-indicator-controls>
          <span className="text-micro text-ink-500">{t('副图')}</span>
          {visiblePanes.length > 0 ? (
            <>
              <Segmented
                ariaLabel={t('副图显示方式')}
                options={[
                  { value: 'single' as const, label: t('单项切换') },
                  { value: 'all' as const, label: t('全部展开') },
                ]}
                value={indicatorView}
                onChange={setIndicatorView}
              />
              {indicatorView === 'single' && visiblePanes.length > 1 && (
                <MenuSelect
                  ariaLabel={t('选择副图指标')}
                  value={analysisOption.panes[0]?.id ?? selectedIndicator}
                  options={visiblePanes.map((pane) => ({ value: pane.id, label: t(pane.label) }))}
                  onChange={setSelectedIndicator}
                  className="min-w-0 max-w-full"
                />
              )}
            </>
          ) : (
            <span className="text-micro text-ink-400">{t('未启用指标副图')}</span>
          )}
        </div>
      )}
      {daily && (analysisOk
        ? <AnalysisLegend overlays={visibleOverlays} smartEnabled={smartDrawingEnabled} />
        : <OverlayLegend style={style} overlays={overlays} showOverlays={priceMode === 'adjusted'} />)}
      <div className="relative mt-3" ref={plotRef} style={daily ? { height: chartHeight } : undefined}>
        {daily ? (
          <AnimatePresence mode="wait">
            {barsLoading ? (
              <motion.div
                key="skeleton"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: DUR_FAST } }}
                className="absolute inset-0 flex flex-col gap-2"
                aria-hidden="true"
              >
                <SkeletonBlock className="h-[62%] w-full rounded-md border border-line-chart" />
                <SkeletonBlock className="h-[18%] w-full rounded-md border border-line-chart" />
              </motion.div>
            ) : !option ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: DUR_FAST } }}
                className="absolute inset-0 overflow-auto"
              >
                <EmptyState
                  image="/empty-chart.svg"
                  title={t('K 线暂不可用')}
                  description={t('{code} · {range}数据暂不可用，其他周期仍可切换', {
                    code: displayCode,
                    range: range.toUpperCase(),
                  })}
                  action={
                    onRetry ? (
                      <button type="button" onClick={onRetry} className="btn-primary">
                        {t('重试')}
                      </button>
                    ) : undefined
                  }
                  className="py-6"
                />
              </motion.div>
            ) : (
              <motion.div
                key={`${range}-${style}-${priceMode}-${analysisOk ? 'analysis' : 'legacy'}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { duration: DUR_UI, ease: EASE_PAPER } }}
                exit={{ opacity: 0, transition: { duration: DUR_FAST } }}
                className="absolute inset-0"
              >
                <ReactECharts
                  className="h-full w-full"
                  option={option}
                  onInit={setChartInst}
                  prepareOption={prepareOption}
                  ariaLabel={`${displayCode} chart`}
                />
                {analysisOk && (
                  <IndicatorReadouts
                    chart={chartInst}
                    bars={analysisBars}
                    range="1d"
                    panes={analysisOption.panes}
                    layout={analysisOption.layout}
                  />
                )}
              </motion.div>
            )}
          </AnimatePresence>
        ) : (
          children
        )}
      </div>
      {daily && analysisOk && (
        <p className="mt-2 text-micro text-ink-400">
          {t('成交额')} {fmtYenCompact(rows.at(-1)?.turnover_value)}
          {style === 'candle' ? ` · ${t('副图按已收盘复权日线计算')}` : ''}
        </p>
      )}
      <LayerMenu
        open={layersOpen}
        onClose={() => setLayersOpen(false)}
        settings={layerSettings}
        onChange={persistLayers}
        mode={style}
      />
    </section>
  );
}
