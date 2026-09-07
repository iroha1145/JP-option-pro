/** 个股日线壳：对齐 option-pro KlineChart 的工具条 / 色块图例 / 高度。
 *  不搬绘图工具、回撤尺、智能画线、副图图层、期权或公司 Logo。 */

import { useMemo, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import EmptyState from '@/components/shared/EmptyState';
import InfoHint from '@/components/shared/InfoHint';
import Segmented from '@/components/shared/Segmented';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { STRUCTURE_HINTS } from '@/lib/indicatorHints';
import { CH, baseGrid, categoryAxis, glassTooltip, insightLineColor, insightLineSeries, valueAxis, type ChartOption } from '@/lib/chart';
import { DUR_FAST, DUR_UI, EASE_PAPER } from '@/lib/motion';
import { useColorMode } from '@/hooks/useColorMode';
import { t } from '@/i18n/core';
import type { StockBar, TechnicalStructure } from '@/api/types';

export type ChartInterval = '1d' | '60m' | '5m' | '1m' | 'tick';
export type ChartRange = '3m' | '6m' | '1y' | '3y' | '10y';
export type PriceMode = 'adjusted' | 'raw';
type ChartStyle = 'candle' | 'area';

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

export default function StockChart({
  displayCode,
  interval,
  onInterval,
  range,
  onRange,
  priceMode,
  onPriceMode,
  bars,
  barsLoading,
  overlays,
  onRetry,
  children,
}: {
  displayCode: string;
  interval: ChartInterval;
  onInterval: (value: ChartInterval) => void;
  range: ChartRange;
  onRange: (value: ChartRange) => void;
  priceMode: PriceMode;
  onPriceMode: (value: PriceMode) => void;
  bars?: StockBar[];
  barsLoading: boolean;
  overlays?: TechnicalStructure['chart_overlays'] | null;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  const [style, setStyle] = useState<ChartStyle>('candle');
  const colorMode = useColorMode();
  const daily = interval === '1d';

  const option = useMemo((): ChartOption | null => {
    void colorMode;
    const rows = bars ?? [];
    if (!daily || rows.length === 0) return null;
    const dates = rows.map((bar) => bar.trade_date);
    const shortDates = dates.map((date) => date.slice(2));
    const closes = rows.map((bar) => pickPrice(bar, priceMode, 'adj_close', 'close'));
    const first = closes.find((value) => value != null);
    const last = [...closes].reverse().find((value) => value != null);
    const change = first != null && last != null ? last - first : null;

    if (style === 'area') {
      return {
        grid: baseGrid({ top: 8, bottom: 8, left: 4, right: 48 }),
        tooltip: glassTooltip({ trigger: 'axis' }),
        xAxis: categoryAxis(shortDates),
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
  }, [bars, colorMode, daily, overlays, priceMode, style]);

  return (
    <section
      className="card-surface p-5 xl:col-span-8"
      aria-label={t('{code} K线图', { code: displayCode })}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-2">
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
      {daily && (
        <OverlayLegend style={style} overlays={overlays} showOverlays={priceMode === 'adjusted'} />
      )}
      <div className="relative mt-3" style={daily ? { height: 420 } : undefined}>
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
                key={`${range}-${style}-${priceMode}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1, transition: { duration: DUR_UI, ease: EASE_PAPER } }}
                exit={{ opacity: 0, transition: { duration: DUR_FAST } }}
                className="absolute inset-0"
              >
                <ReactECharts
                  className="h-full w-full"
                  option={option}
                  ariaLabel={`${displayCode} chart`}
                />
              </motion.div>
            )}
          </AnimatePresence>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
