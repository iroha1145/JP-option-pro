/** 个股研究页 v2 — 卡片重排：
 *  行1: K线(8列, 高度固定) + 右侧紧凑栏(4列: 雷达/信用/技术指标)
 *  行2: 决算时间线(7列, 限高滚动) + 技术结构面板(5列)
 *  行3: 空卖报告 + 发表预定 (两列)
 *  K线叠加: 基底阻力带 markArea + 枢轴/失效位 markLine + 摆动点。 */

import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { stocksApi, watchlistApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import InfoHint from '@/components/shared/InfoHint';
import TickAnalyticsPanel from '@/components/charts/TickAnalyticsPanel';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { DataThrough, ScoreBar, SignalChip, StateChip } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { STRUCTURE_HINTS, TECHNICAL_HINTS, type ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtTimeJst, fmtYenCompact } from '@/lib/format';
import type {
  FinancialSummaryView,
  IntradayChart,
  MarginInterestRow,
  ShortPositionRow,
  TechnicalStructure,
  TickView,
} from '@/api/types';

type Range = '3m' | '6m' | '1y' | '3y' | '10y';
type PriceMode = 'adjusted' | 'raw';
type Interval = '1d' | '60m' | '5m' | '1m' | 'tick';

export default function StockDetail() {
  const { code = '' } = useParams();
  const [range, setRange] = useState<Range>('6m');
  const [interval, setInterval] = useState<Interval>('1d');
  const [priceMode, setPriceMode] = useState<PriceMode>('adjusted');
  const overview = usePolling(() => stocksApi.overview(code), null, [code]);
  const chart = usePolling(() => stocksApi.chart(code, range), null, [code, range]);
  const [intradayPollMs, setIntradayPollMs] = useState<number | null>(null);
  const [tickPollMs, setTickPollMs] = useState<number | null>(null);
  const wantIntraday = interval !== '1d' && interval !== 'tick';
  const wantTicks = interval === 'tick';
  const intraday = usePolling(
    async () => {
      if (!wantIntraday) {
        setIntradayPollMs(null);
        return null;
      }
      const data = await stocksApi.intradayChart(code, interval as '1m' | '5m' | '60m');
      setIntradayPollMs(data?.reason === 'fetching' ? 5_000 : null);
      return data;
    },
    wantIntraday ? intradayPollMs : null,
    [code, interval, wantIntraday],
  );
  const ticks = usePolling(
    async () => {
      if (!wantTicks) {
        setTickPollMs(null);
        return null;
      }
      const data = await stocksApi.tickView(code);
      setTickPollMs(data?.reason === 'fetching' ? 8_000 : null);
      return data;
    },
    wantTicks ? tickPollMs : null,
    [code, interval, wantTicks],
  );
  /* 遅延気配は 1 分ポーリング。J-Quants は場中に何も出さないので、
     「今いくらか」はこの非公式・15分遅延の値でしか埋められない。 */
  const live = usePolling(() => stocksApi.intradayQuotes([code]), 60_000, [code]);
  const { isOwner } = useAccess();
  const [watchNote, setWatchNote] = useState<string | null>(null);
  const [fetchNote, setFetchNote] = useState<string | null>(null);

  const state = remoteState(overview);
  const liveQuote = live.data?.enabled ? (live.data.quotes[Object.keys(live.data.quotes)[0]] ?? null) : null;
  const technical = overview.data?.technical ?? null;

  const chartOption = useMemo(() => {
    const bars = chart.data?.bars ?? [];
    if (bars.length === 0) return null;
    const pick = (
      bar: (typeof bars)[number],
      adj: 'adj_open' | 'adj_high' | 'adj_low' | 'adj_close',
      raw: 'open' | 'high' | 'low' | 'close',
    ) => (priceMode === 'adjusted' ? (bar[adj] ?? bar[raw]) : bar[raw]);
    const dates = bars.map((bar) => bar.trade_date);
    const shortDates = dates.map((date) => date.slice(2));
    const candles = bars.map((bar) => [
      pick(bar, 'adj_open', 'open'),
      pick(bar, 'adj_close', 'close'),
      pick(bar, 'adj_low', 'low'),
      pick(bar, 'adj_high', 'high'),
    ]);
    const turnover = bars.map((bar) => bar.turnover_value);

    const overlays = technical?.chart_overlays;
    const markLines: Record<string, unknown>[] = [];
    const markPoints: ({ name: string } & Record<string, unknown>)[] = [];
    if (priceMode === 'adjusted' && overlays) {
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
            color: CH.up600, color0: CH.down600,
            borderColor: CH.up600, borderColor0: CH.down600,
          },
          markLine: { symbol: 'none', animation: false, data: markLines },
          markPoint: { animation: false, data: markPoints },
          ...(priceMode === 'adjusted'
          && overlays?.resistance_high != null
          && overlays?.resistance_low != null
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
          type: 'bar' as const,
          data: turnover,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: { color: CH.brand400, opacity: 0.4 },
        },
      ],
    };
  }, [chart.data, priceMode, technical]);

  if (state === 'loading') {
    return <SkeletonCard className="mt-6 h-96" />;
  }
  if (state === 'error' || !overview.data) {
    return (
      <EmptyState
        variant="error"
        title={t('加载失败')}
        description={String(overview.error?.message ?? '')}
        className="mt-12"
      />
    );
  }

  const data = overview.data;
  const security = data.security;

  return (
    <div className="space-y-5">
      {/* ヘッダー */}
      <header className="border-b border-line pb-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-brand-50 px-2 py-1 font-mono text-h3 font-bold text-brand-700">
            {security.display_code}
          </span>
          <h1 className="font-display text-display-m text-ink-900">{security.name_ja ?? security.name_en ?? '—'}</h1>
          {security.active === 0 && (
            <span className="rounded-sm bg-down-50 px-1.5 py-0.5 text-micro text-down-700">
              {t('上場廃止')} {security.delisted_date ?? ''}
            </span>
          )}
          {isOwner && (
            <button
              type="button"
              className="ml-auto rounded-md border border-line bg-card px-2.5 py-1 text-caption text-ink-600 hover:bg-brand-50"
              onClick={async () => {
                try {
                  const result = await watchlistApi.add(security.canonical_code);
                  setWatchNote(result.created ? '✓' : '★');
                } catch {
                  setWatchNote('—');
                }
              }}
            >
              {watchNote ?? `+ ${t('加入自选')}`}
            </button>
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-ink-500">
          <span>{security.market_name ?? '—'}</span>
          <span>{security.sector33_name ?? '—'}</span>
          {security.scale_category && <span>{security.scale_category}</span>}
          {security.margin_name && <span>{security.margin_name}</span>}
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-4">
          {liveQuote ? (
            <>
              {/* 遅延気配を主表示にするが、必ず「遅延・非公式」と併記する。
                  公式の確定終値は隣に小さく残し、どちらの数字かを曖昧にしない。 */}
              <span className="flex flex-col">
                <span className="flex items-baseline gap-2">
                  <span className="font-mono text-display-l tnum text-ink-900">{fmtPrice(liveQuote.price)}</span>
                  <ChangeBadge value={liveQuote.change_pct} />
                </span>
                <span className="mt-0.5 flex items-center gap-1 text-micro text-warn-700">
                  <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                  {t('延迟{n}分 · 非官方源', { n: live.data?.delayed_minutes ?? 15 })}
                  {liveQuote.as_of_epoch ? ` · ${fmtTimeJst(liveQuote.as_of_epoch)}` : ''}
                </span>
              </span>
              <span className="flex flex-col text-caption text-ink-400">
                <span className="font-mono tnum text-ink-600">{fmtPrice(data.quote.close)}</span>
                <span>{t('官方终值')} {data.quote.trade_date ?? ''}</span>
              </span>
            </>
          ) : (
            <>
              <span className="font-mono text-display-l tnum text-ink-900">{fmtPrice(data.quote.close)}</span>
              <ChangeBadge value={data.quote.change_pct} />
            </>
          )}
          <span className="text-body-s text-ink-500">
            {t('成交额')} <span className="font-mono tnum">{fmtYenCompact(data.quote.turnover_value)}</span>
          </span>
          <DataThrough date={data.quote.trade_date} className="ml-auto" />
        </div>
      </header>

      {/* 行1: K線 + 右侧紧凑栏 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <section className="card-surface rounded-lg p-3 xl:col-span-8">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="flex flex-wrap items-center gap-2">
              <Segmented<Interval>
                options={[
                  { value: '1d', label: t('日K') },
                  { value: '60m', label: t('60分') },
                  { value: '5m', label: t('5分') },
                  { value: '1m', label: t('1分') },
                  { value: 'tick', label: t('逐笔') },
                ]}
                value={interval}
                onChange={setInterval}
              />
              {interval === '1d' && (
                <Segmented<Range>
                  options={(['3m', '6m', '1y', '3y', '10y'] as Range[]).map((value) => ({ value, label: value.toUpperCase() }))}
                  value={range}
                  onChange={setRange}
                />
              )}
            </span>
            <span className="flex items-center gap-2">
              <span className="flex items-center gap-1 text-caption text-ink-400">
                {t('图例')}
                <InfoHint hint={STRUCTURE_HINTS.chart_overlays} align="end" />
              </span>
              {interval === '1d' && (
                <Segmented<PriceMode>
                  options={[
                    { value: 'adjusted', label: t('复权') },
                    { value: 'raw', label: t('不复权') },
                  ]}
                  value={priceMode}
                  onChange={setPriceMode}
                />
              )}
            </span>
          </div>
          {interval === '1d' ? (
            chartOption ? (
              <ReactECharts className="h-72 w-full" option={chartOption} ariaLabel={`${security.display_code} chart`} />
            ) : chart.loading ? (
              <SkeletonCard className="h-72" />
            ) : (
              <EmptyState title={t('暂无数据')} />
            )
          ) : interval === 'tick' ? (
            <TickPane
              data={ticks.data ?? null}
              loading={ticks.loading}
              isOwner={isOwner}
              fetchNote={fetchNote}
              onFetch={async () => {
                try {
                  await workerApi.trigger('tick_fetch', { code: security.canonical_code });
                  setFetchNote(t('已提交，数据到达后刷新本页'));
                } catch (error) {
                  setFetchNote(String((error as Error).message ?? error));
                }
              }}
              onRefresh={() => ticks.refresh({ force: true })}
            />
          ) : (
            <IntradayPane
              data={intraday.data ?? null}
              loading={intraday.loading}
              isOwner={isOwner}
              fetchNote={fetchNote}
              onFetch={async () => {
                try {
                  await workerApi.trigger('intraday_fetch', { code: security.canonical_code });
                  setFetchNote(t('已提交，数据到达后刷新本页'));
                } catch (error) {
                  setFetchNote(String((error as Error).message ?? error));
                }
              }}
              onRefresh={() => intraday.refresh({ force: true })}
            />
          )}
        </section>

        <div className="grid content-start gap-4 xl:col-span-4">
          {/* 雷达 */}
          <section className="card-surface rounded-lg p-3">
            <h2 className="mb-2 text-body font-medium text-ink-900">{t('突破雷达')}</h2>
            {data.radar_events.length === 0 ? (
              <p className="text-caption text-ink-400">{t('暂无相关雷达事件')}</p>
            ) : (
              <ul className="space-y-1.5">
                {data.radar_events.slice(0, 3).map((event) => (
                  <li key={event.event_id} className="flex flex-wrap items-center gap-1.5 text-caption">
                    <SignalChip signal={event.signal_type} />
                    <StateChip state={event.state} />
                    <span className="ml-auto text-ink-500">
                      {fmtDate(event.discovered_date)} · {fmtPrice(event.pivot_price)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 信用交易 */}
          <section className="card-surface rounded-lg p-3">
            <h2 className="mb-2 text-body font-medium text-ink-900">{t('信用交易')}</h2>
            <MarginPanel rows={data.margin_interest} />
          </section>

          {/* 技术指标 */}
          <section className="card-surface rounded-lg p-3">
            <h2 className="mb-2 text-body font-medium text-ink-900">{t('技术指标')}</h2>
            <IndicatorGrid technical={technical} />
          </section>
        </div>
      </div>

      {/* 行2: 决算时间线 + 技术结构 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <section className="card-surface rounded-lg p-4 xl:col-span-7">
          <h2 className="mb-3 text-h3 text-ink-900">{t('决算时间线')}</h2>
          <div className="max-h-[360px] overflow-y-auto">
            <FinancialTable summaries={data.financials.summaries} />
          </div>
        </section>
        <section className="card-surface rounded-lg p-4 xl:col-span-5">
          <h2 className="mb-3 text-h3 text-ink-900">{t('K线结构分析')}</h2>
          <StructurePanel technical={technical} />
        </section>
      </div>

      {/* 行3: 空卖 + 发表预定 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="card-surface rounded-lg p-4">
          <h2 className="mb-3 text-h3 text-ink-900">{t('空卖残高报告')}</h2>
          <ShortPositionsPanel rows={data.short_positions} />
        </section>
        <section className="card-surface rounded-lg p-4">
          <h2 className="mb-3 text-h3 text-ink-900">{t('发表预定')}</h2>
          {data.earnings.length === 0 ? (
            <p className="text-body-s text-ink-400">{t('暂无数据')}</p>
          ) : (
            <ul className="divide-y divide-line">
              {data.earnings.slice(0, 4).map((item, index) => (
                <li key={index} className="flex items-center justify-between py-1.5 text-body-s">
                  <span className="text-ink-700">{String(item.fiscal_quarter ?? '—')}</span>
                  <span className="font-mono tnum text-ink-900">
                    {item.announcement_date ? fmtDate(String(item.announcement_date)) : t('未定')}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

/* ---------------- 盘中K线（1分/5分/60分） ---------------- */

function IntradayPane({
  data,
  loading,
  isOwner,
  fetchNote,
  onFetch,
  onRefresh,
}: {
  data: IntradayChart | null;
  loading: boolean;
  isOwner: boolean;
  fetchNote: string | null;
  onFetch: () => void;
  onRefresh: () => void;
}) {
  const option = useMemo(() => {
    const bars = data?.bars ?? [];
    if (bars.length === 0) return null;
    const labels = bars.map((bar) => `${bar.trade_date.slice(5)} ${bar.bar_time}`);
    const candles = bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]);
    const turnover = bars.map((bar) => bar.turnover_value);
    return {
      grid: [
        baseGrid({ top: 8, bottom: '24%', left: 4, right: 48 }),
        baseGrid({ top: '80%', bottom: 2, left: 4, right: 48 }),
      ],
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: [
        { ...categoryAxis(labels), gridIndex: 0 },
        { ...categoryAxis(labels), gridIndex: 1, axisLabel: { show: false } },
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
            color: CH.up600, color0: CH.down600,
            borderColor: CH.up600, borderColor0: CH.down600,
          },
        },
        {
          type: 'bar' as const,
          data: turnover,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: { color: CH.brand400, opacity: 0.4 },
        },
      ],
    };
  }, [data]);

  if (loading && !data) return <SkeletonCard className="h-72" />;
  if (data && data.available && option) {
    return (
      <div>
        <ReactECharts className="h-72 w-full" option={option} ariaLabel="intraday chart" />
        <p className="mt-1 text-right text-micro text-ink-400">
          {t('分钟数据为未复权原始价')} · {(data.days ?? []).length} {t('个交易日')} ·{' '}
          {t('数据截至')} {data.data_through ?? '—'}
        </p>
      </div>
    );
  }
  const planBlocked = data?.reason === 'plan_not_included';
  const empty = data?.reason === 'empty';
  return (
    <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-md bg-paper-2">
      <p className="max-w-md px-6 text-center text-body-s text-ink-600">
        {planBlocked
          ? t('分钟线需要 J-Quants 分足加购（当前订阅未包含）')
          : data?.reason === 'fetching'
            ? t('正在取得分钟数据，请稍候刷新')
            : empty
              ? t('已取得，但没有可显示的分钟数据')
              : t('该股票的分钟数据尚未取得')}
      </p>
      {data?.note_ja && <p className="max-w-md px-6 text-center text-caption text-ink-400">{data.note_ja}</p>}
      {isOwner && !planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-body-s font-medium text-white"
        >
          {t('取得最近5个交易日的分钟数据')}
        </button>
      )}
      {isOwner && planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md border border-line px-3 py-1.5 text-caption text-ink-500 hover:bg-brand-50"
          title={t('重新检测订阅状态')}
        >
          {t('重新检测订阅状态')}
        </button>
      )}
      <span className="flex items-center gap-2">
        {fetchNote && <span className="text-caption text-ink-400">{fetchNote}</span>}
        <button type="button" onClick={onRefresh} className="text-caption text-brand-700 hover:underline">
          {t('刷新')}
        </button>
      </span>
    </div>
  );
}

/* ---------------- 逐笔（ティック・歩み値） ---------------- */

function TickPane({
  data,
  loading,
  isOwner,
  fetchNote,
  onFetch,
  onRefresh,
}: {
  data: TickView | null;
  loading: boolean;
  isOwner: boolean;
  fetchNote: string | null;
  onFetch: () => void;
  onRefresh: () => void;
}) {
  const option = useMemo(() => {
    const points = data?.points ?? [];
    if (points.length === 0) return null;
    const labels = points.map((point) => point.t);
    return {
      /* 服务端已间引到 ≤1200 点；关动画保证低端机切标签页零卡顿 */
      animation: false,
      grid: [
        baseGrid({ top: 8, bottom: '24%', left: 4, right: 48 }),
        baseGrid({ top: '80%', bottom: 2, left: 4, right: 48 }),
      ],
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: [
        { ...categoryAxis(labels), gridIndex: 0 },
        { ...categoryAxis(labels), gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { ...valueAxis({ scale: true, position: 'right' }), gridIndex: 0 },
        { ...valueAxis(), gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      series: [
        {
          type: 'line' as const,
          data: points.map((point) => point.price),
          xAxisIndex: 0,
          yAxisIndex: 0,
          showSymbol: false,
          lineStyle: { width: 1.2, color: CH.brand600 },
          areaStyle: { color: CH.brand400, opacity: 0.08 },
        },
        {
          type: 'bar' as const,
          data: points.map((point) => point.volume),
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: { color: CH.brand400, opacity: 0.4 },
        },
      ],
    };
  }, [data]);

  if (loading && !data) return <SkeletonCard className="h-72" />;
  if (data && data.available && option) {
    return (
      <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_232px]">
        <div className="min-w-0">
          <ReactECharts className="h-72 w-full" option={option} ariaLabel="tick chart" />
          <p className="mt-1 text-right text-micro text-ink-400">
            {data.trade_date} · {data.tick_count.toLocaleString()} {t('笔')} ·{' '}
            {t('约 {n} 秒/点', { n: data.bucket_seconds ?? 1 })}
            {data.truncated ? ` · ${t('已达单日行数上限，尾部截断')}` : ''} ·{' '}
            {t('逐笔为未复权原始价')}
          </p>
        </div>
        <aside className="min-w-0">
          <p className="mb-1 flex items-baseline justify-between text-caption text-ink-500">
            {t('歩み值 · 最近 {n} 笔', { n: data.tape.length })}
            <button type="button" onClick={onRefresh} className="text-micro text-brand-700 hover:underline">
              {t('刷新')}
            </button>
          </p>
          <div className="max-h-72 overflow-y-auto overscroll-contain rounded-md border border-line bg-paper-2">
            <table className="w-full border-collapse font-mono text-micro tnum">
              <tbody>
                {data.tape.map((row, index) => (
                  <tr key={`${row.time}-${index}`} className="border-b border-line/60 last:border-b-0">
                    <td className="px-2 py-1 text-ink-400">{row.time}</td>
                    <td
                      className={cnTick(row.direction)}
                    >
                      {row.price != null ? fmtPrice(row.price) : '—'}
                    </td>
                    <td className="px-2 py-1 text-right text-ink-500">
                      {row.volume != null ? row.volume.toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
      <TickAnalyticsPanel analytics={data.analytics} />
      </div>
    );
  }
  const planBlocked = data?.reason === 'plan_not_included';
  const fetching = data?.reason === 'fetching';
  const empty = data?.reason === 'empty';
  return (
    <div className="flex h-72 flex-col items-center justify-center gap-3 rounded-md bg-paper-2">
      <p className="max-w-md px-6 text-center text-body-s text-ink-600">
        {planBlocked
          ? t('逐笔需要 J-Quants Tick 加购（刚购买时，API 侧生效可能有延迟）')
          : fetching
            ? t('正在取得逐笔数据（全市场日次文件约 50MB，稍候刷新）')
            : empty
              ? t('已取得，但没有可显示的逐笔数据（可能尚未配信）')
              : t('该股票的逐笔数据尚未取得')}
      </p>
      {data?.note_ja && <p className="max-w-md px-6 text-center text-caption text-ink-400">{data.note_ja}</p>}
      {isOwner && !planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-body-s font-medium text-white"
        >
          {t('取得最近交易日的逐笔数据')}
        </button>
      )}
      {isOwner && planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md border border-line px-3 py-1.5 text-caption text-ink-500 hover:bg-brand-50"
          title={t('重新检测订阅状态')}
        >
          {t('重新检测订阅状态')}
        </button>
      )}
      <span className="flex items-center gap-2">
        {fetchNote && <span className="text-caption text-ink-400">{fetchNote}</span>}
        <button type="button" onClick={onRefresh} className="text-caption text-brand-700 hover:underline">
          {t('刷新')}
        </button>
      </span>
    </div>
  );
}

/** 歩み值行的价格着色：红涨绿跌（日本/中华圈惯例，全站禁止反转） */
function cnTick(direction: 'up' | 'down' | 'flat'): string {
  const base = 'px-2 py-1 text-right font-medium';
  if (direction === 'up') return `${base} text-up-600`;
  if (direction === 'down') return `${base} text-down-600`;
  return `${base} text-ink-600`;
}

/* ---------------- 技术结构面板（美版算法输出） ---------------- */

function StructurePanel({ technical }: { technical: TechnicalStructure | null }) {
  if (!technical) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  const pa = technical.price_action;
  const vpm = technical.vol_price;
  const base = technical.base;
  return (
    <div className="space-y-3">
      {/* 市场结构 */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="flex items-center gap-1 text-caption text-ink-500">
            {t('市场结构（HH/HL）')}
            <InfoHint hint={STRUCTURE_HINTS.market_structure} />
          </span>
          <span className="text-caption font-medium text-ink-800">{t(pa.structure_label)}</span>
        </div>
        <ScoreBar label="价格行为" score={pa.score} />
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {pa.pattern_labels.map((label) => (
            <span key={label} className="rounded-pill border border-line bg-card px-2 py-0.5 text-micro text-ink-600">{t(label)}</span>
          ))}
          {pa.spring && (
            <span className="inline-flex items-center gap-1 rounded-pill bg-up-50 px-2 py-0.5 text-micro text-up-700">
              {t('Spring 假跌破回收')}
              <InfoHint hint={STRUCTURE_HINTS.spring} size={11} />
            </span>
          )}
          {pa.upthrust && (
            <span className="inline-flex items-center gap-1 rounded-pill bg-down-50 px-2 py-0.5 text-micro text-down-700">
              {t('Upthrust 假突破')}
              <InfoHint hint={STRUCTURE_HINTS.upthrust} size={11} />
            </span>
          )}
        </div>
        <dl className="mt-2 grid grid-cols-2 gap-1.5 text-caption">
          <StructFact label="摆动阻力" value={`${fmtPrice(pa.resistance)}（${pa.resistance_dist_pct !== null ? `${pa.resistance_dist_pct > 0 ? '+' : ''}${pa.resistance_dist_pct}%` : '—'}）`} />
          <StructFact label="摆动支撑" value={`${fmtPrice(pa.support)}（${pa.support_dist_pct !== null ? `${pa.support_dist_pct > 0 ? '+' : ''}${pa.support_dist_pct}%` : '—'}）`} />
        </dl>
      </div>

      {/* 基底 */}
      <div className="border-t border-line pt-2.5">
        <div className="mb-1 flex items-center justify-between">
          <span className="flex items-center gap-1 text-caption text-ink-500">
            {t('基底检测（枢轴聚类）')}
            <InfoHint hint={STRUCTURE_HINTS.base_detection} />
          </span>
          <span className="text-caption font-medium text-ink-800">
            {base ? t('{n} 次触碰 · 质量 {q}', { n: base.resistance_touches ?? '—', q: base.quality !== null ? Math.round((base.quality ?? 0) * 100) : '—' }) : t('未检测到完成基底')}
          </span>
        </div>
        {base && (
          <dl className="grid grid-cols-2 gap-1.5 text-caption">
            <StructFact label="阻力带" value={`${fmtPrice(base.resistance_low)} – ${fmtPrice(base.resistance_high)}`} />
            <StructFact label="失效位" value={fmtPrice(base.invalidation_price)} />
            <StructFact label="基底区间" value={`${fmtDate(base.base_start)} → ${fmtDate(base.base_end)}`} />
            <StructFact label="支撑下沿" value={fmtPrice(base.support_low)} />
          </dl>
        )}
      </div>

      {/* 量价一致 */}
      <div className="border-t border-line pt-2.5">
        <div className="mb-1 flex items-center justify-between">
          <span className="flex items-center gap-1 text-caption text-ink-500">
            {t('量价一致（努力/结果）')}
            <InfoHint hint={STRUCTURE_HINTS.vol_price} />
          </span>
          <span className="rounded-pill bg-ai-50 px-2 py-0.5 text-micro font-medium text-ai-600">{t(vpm.setup_label)}</span>
        </div>
        <dl className="grid grid-cols-3 gap-1.5 text-caption">
          <StructFact label="努力" value={vpm.effort !== null ? `${vpm.effort.toFixed(2)}x` : '—'} />
          <StructFact label="结果" value={vpm.result !== null ? `${vpm.result.toFixed(2)}x` : '—'} />
          <StructFact label="假突破风险" value={`${vpm.false_breakout_risk > 0 ? '+' : ''}${vpm.false_breakout_risk}`} />
        </dl>
        {vpm.tags.length > 0 && (
          <p className="mt-1.5 text-micro text-ink-400">{vpm.tags.map((tag) => t(tag)).join(' · ')}</p>
        )}
      </div>
    </div>
  );
}

function IndicatorGrid({ technical }: { technical: TechnicalStructure | null }) {
  if (!technical) return <p className="text-caption text-ink-400">{t('暂无数据')}</p>;
  const tech = technical.technicals;
  return (
    <dl className="grid grid-cols-3 gap-1.5">
      <MiniStat
        label="RSI 14"
        value={tech.rsi14 !== null ? tech.rsi14.toFixed(1) : '—'}
        hint={TECHNICAL_HINTS.rsi14}
      />
      <MiniStat
        label="MACD 动向"
        value={tech.macd.direction_pct !== null ? `${tech.macd.direction_pct > 0 ? '+' : ''}${tech.macd.direction_pct.toFixed(2)}%` : '—'}
        hint={TECHNICAL_HINTS.macd}
      />
      <MiniStat
        label="趋势效率"
        value={tech.trend_efficiency_63d !== null ? tech.trend_efficiency_63d.toFixed(2) : '—'}
        hint={TECHNICAL_HINTS.trend_efficiency}
      />
      <MiniStat
        label="MA50 斜率"
        value={tech.ma50_slope_pct_21d !== null ? `${tech.ma50_slope_pct_21d > 0 ? '+' : ''}${tech.ma50_slope_pct_21d.toFixed(1)}%` : '—'}
        hint={TECHNICAL_HINTS.ma50_slope}
      />
      <MiniStat
        label="区间位置"
        value={tech.range_position_60d !== null ? fmtPct(tech.range_position_60d, 0) : '—'}
        hint={TECHNICAL_HINTS.range_position}
      />
      <MiniStat
        label="波动稳定"
        value={tech.return_stability_20d !== null ? fmtPct(tech.return_stability_20d, 1) : '—'}
        hint={TECHNICAL_HINTS.return_stability}
      />
    </dl>
  );
}

function StructFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-paper-2 px-2 py-1">
      {/* label は msgid（呼び出し側は中文原文を渡す）—— ここで必ず訳す */}
      <dt className="text-micro text-ink-400">{t(label)}</dt>
      <dd className="font-mono text-caption tnum text-ink-800">{value}</dd>
    </div>
  );
}

/* ---------------- 既存パネル（コンパクト化） ---------------- */

function FinancialTable({ summaries }: { summaries: FinancialSummaryView[] }) {
  const columns: Column<FinancialSummaryView>[] = [
    {
      key: 'date', title: t('发表预定'), width: '96px',
      render: (row) => <span className="font-mono text-caption tnum text-ink-700">{fmtDate(row.disclosed_date)}</span>,
    },
    {
      key: 'period', title: t('决算种别'),
      render: (row) => (
        <span className="flex items-center gap-1">
          <span className="rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">
            {row.fiscal_year_end?.slice(0, 7) ?? '—'} {row.period_type ?? ''}
          </span>
          <span className="text-micro text-ink-400">{row.is_consolidated ? t('连结') : t('单体')}</span>
        </span>
      ),
    },
    {
      key: 'sales', title: t('销售额'), align: 'right',
      render: (row) => <span className="font-mono text-caption tnum">{fmtYenCompact(row.sales ?? row.nc_sales)}</span>,
    },
    {
      key: 'op', title: t('营业利益'), align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum">{fmtYenCompact(row.operating_profit ?? row.nc_operating_profit)}</span>
      ),
    },
    {
      key: 'np', title: t('纯利益'), align: 'right',
      render: (row) => <span className="font-mono text-caption tnum">{fmtYenCompact(row.net_profit)}</span>,
    },
    {
      key: 'forecast', title: `${t('会社预想')}·OP`, align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum text-ink-500">{fmtYenCompact(row.forecast_operating_profit)}</span>
      ),
    },
  ];
  if (summaries.length === 0) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  return (
    <DataTable columns={columns} rows={summaries} rowKey={(row) => `${row.disclosed_date}-${row.disclosure_number}`} rowHeight={44} />
  );
}

function MarginPanel({ rows }: { rows: MarginInterestRow[] }) {
  if (rows.length === 0) return <p className="text-caption text-ink-400">{t('暂无数据')}</p>;
  const latest = rows[rows.length - 1];
  const ratio =
    latest.long_total !== null && latest.short_total !== null && latest.short_total > 0
      ? latest.long_total / latest.short_total
      : null;
  return (
    <div className="space-y-1.5">
      <dl className="grid grid-cols-3 gap-1.5">
        <MiniStat label={t('信用买残')} value={fmtYenCompact(latest.long_total, 0)} />
        <MiniStat label={t('信用卖残')} value={fmtYenCompact(latest.short_total, 0)} />
        <MiniStat label={t('信用倍率')} value={ratio !== null ? `${ratio.toFixed(2)}x` : '—'} />
      </dl>
      <p className="text-right text-micro text-ink-400">
        {t('数据截至')} {fmtDate(latest.application_date)}（週次）
      </p>
    </div>
  );
}

function ShortPositionsPanel({ rows }: { rows: ShortPositionRow[] }) {
  if (rows.length === 0) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  return (
    <ul className="divide-y divide-line">
      {rows.slice(0, 5).map((row, index) => (
        <li key={index} className="flex items-center justify-between gap-2 py-1.5 text-body-s">
          <span className="min-w-0 truncate text-ink-700">{row.holder_name ?? '—'}</span>
          <span className="shrink-0 font-mono tnum text-ink-900">{fmtPct(row.short_position_ratio, 2)}</span>
          <span className="shrink-0 text-micro text-ink-400">{fmtDate(row.calculated_date)}</span>
        </li>
      ))}
    </ul>
  );
}

function MiniStat({ label, value, hint }: { label: string; value: string; hint?: ScoreHint }) {
  return (
    <div className="rounded-md bg-paper-2 px-1.5 py-1.5 text-center">
      <div className="truncate font-mono text-body-s tnum text-ink-900">{value}</div>
      <div className="flex items-center justify-center gap-0.5 text-micro text-ink-400">
        {/* label は msgid（呼び出し側は中文原文）—— ここで訳さないと三言語とも中文のまま */}
        <span className="truncate" title={t(label)}>{t(label)}</span>
        {hint && <InfoHint hint={hint} size={11} side="bottom" />}
      </div>
    </div>
  );
}
