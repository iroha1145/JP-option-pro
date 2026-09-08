/** 个股研究页 v2 — 卡片重排：
 *  行1: K线(8列, 高度固定) + 右侧紧凑栏(4列: 雷达/信用/技术指标)
 *  行2: 决算时间线(7列, 限高滚动) + 技术结构面板(5列)
 *  行3: 空卖报告 + 发表预定 (两列)
 *  K线叠加: 基底阻力带 markArea + 枢轴/失效位 markLine + 摆动点。 */

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, useParams } from 'react-router';
import { useNow } from '@/hooks/useNow';
import { useColorMode } from '@/hooks/useColorMode';
import SessionLED from '@/components/shared/SessionLED';
import { tokyoSession } from '@/lib/tokyoSession';
import { stocksApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { useTickFlash } from '@/hooks/useTickFlash';
import TickPrice from '@/components/shared/TickPrice';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { remoteState } from '@/hooks/remoteState';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import SourceNote from '@/components/shared/SourceNote';
import { InsightValue } from '@/components/shared/InsightCard';
import WatchlistToggle from '@/components/shared/WatchlistToggle';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import InfoHint from '@/components/shared/InfoHint';
import TickAnalyticsPanel from '@/components/charts/TickAnalyticsPanel';
import ShortBehaviorPanel from '@/components/domain/ShortBehaviorPanel';
import StockChart, { type ChartInterval, type ChartRange, type PriceMode } from '@/components/detail/StockChart';
import KeyStats from '@/components/detail/KeyStats';
import { CH, baseGrid, categoryAxis, glassTooltip, insightLineSeries, valueAxis } from '@/lib/chart';
import { DataThrough, ScoreBar, SignalChip, StateChip } from '@/components/domain';
import StrengthBar from '@/components/shared/StrengthBar';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import SoftBadge from '@/components/shared/SoftBadge';
import CodeMark from '@/components/shared/CodeMark';
import Icon from '@/components/icons';
import { RADAR_SCORE_HINTS, STRUCTURE_HINTS, TECHNICAL_HINTS, type ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { quoteSourceLabel } from '@/lib/quoteSource';
import { dateAnchorParts, fmtDate, fmtDateShort, fmtPct, fmtPrice, fmtShares, fmtTimeJst, fmtYenCompact } from '@/lib/format';
import { jstToday } from '@/components/earnings/types';
import { cn } from '@/lib/utils';
import type {
  FinancialSummaryView,
  IntradayChart,
  MarginInterestRow,
  ShortInterestSummary,
  ShortPositionRow,
  TechnicalStructure,
  TickView,
} from '@/api/types';

/** 用收盘/现价与涨跌比率还原绝对变动，不另编字段。 */
function yenChangeFromPct(price: number | null | undefined, changePct: number | null | undefined): number | null {
  if (price == null || changePct == null || !Number.isFinite(price) || !Number.isFinite(changePct)) return null;
  const denom = 1 + changePct;
  if (denom === 0) return null;
  return (price * changePct) / denom;
}

export default function StockDetail() {
  const { code = '' } = useParams();
  const navigate = useNavigate();
  const [range, setRange] = useState<ChartRange>('6m');
  const [interval, setInterval] = useState<ChartInterval>('1d');
  const [priceMode, setPriceMode] = useState<PriceMode>('adjusted');
  const overview = usePolling(() => stocksApi.overview(code), null, [code]);
  const chart = usePolling(() => stocksApi.chart(code, range), null, [code, range]);
  const [intradayPollMs, setIntradayPollMs] = useState<number | null>(null);
  const [tickPollMs, setTickPollMs] = useState<number | null>(null);
  const wantIntraday = interval !== '1d' && interval !== 'tick';
  const wantTicks = interval === 'tick';
  const intraday = usePolling(
    () =>
      wantIntraday
        ? stocksApi.intradayChart(code, interval as '1m' | '5m' | '60m')
        : Promise.resolve(null),
    wantIntraday ? intradayPollMs : null,
    [code, interval, wantIntraday],
  );
  const ticks = usePolling(
    () => (wantTicks ? stocksApi.tickView(code) : Promise.resolve(null)),
    wantTicks ? tickPollMs : null,
    [code, interval, wantTicks],
  );
  // Derive the poll cadence from the committed (generation-guarded) response instead
  // of setting state inside the fetcher: that avoided a stale in-flight response
  // clobbering the cadence for a newer selection.
  useEffect(() => {
    setIntradayPollMs(wantIntraday && intraday.data?.reason === 'fetching' ? 5_000 : null);
  }, [wantIntraday, intraday.data]);
  useEffect(() => {
    setTickPollMs(wantTicks && ticks.data?.reason === 'fetching' ? 8_000 : null);
  }, [wantTicks, ticks.data]);
  /* 遅延気配は 1 分ポーリング。J-Quants は場中に何も出さないので、
     「今いくらか」はこの非公式・15分遅延の値でしか埋められない。 */
  const live = usePolling(() => stocksApi.intradayQuotes([code]), 60_000, [code]);
  const { isOwner } = useAccess();
  const toast = useToast();
  const [fetchNote, setFetchNote] = useState<string | null>(null);
  const now = useNow(30_000);
  const session = tokyoSession(now);
  const watchlistToggle = code ? (
    <WatchlistToggle canonicalCode={code} displayCode={code} />
  ) : null;

  const state = remoteState(overview);
  const liveQuote = live.data?.enabled ? (live.data.quotes[Object.keys(live.data.quotes)[0]] ?? null) : null;
  const technical = overview.data?.technical ?? null;
  const headerQuote = useMemo(() => {
    const code = overview.data?.security.canonical_code;
    if (!code) return [];
    return [{ key: code, price: liveQuote?.price ?? overview.data?.quote.close ?? null }];
  }, [overview.data, liveQuote]);
  const headerFlashes = useTickFlash(headerQuote, (row) => row.key, (row) => row.price);
  const todayKey = jstToday();

  const goBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate('/watchlist', { replace: true });
  };
  const backButton = (
    <button
      type="button"
      onClick={goBack}
      className="inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-card px-3 py-1.5 text-caption font-medium text-ink-600 shadow-btn transition-colors duration-fast hover:bg-paper-2 hover:text-ink-800"
    >
      <Icon name="chevron-right" size={14} className="rotate-180" />
      {t('返回')}
    </button>
  );

  if (state === 'loading') {
    return (
      <div className="space-y-5" aria-busy="true">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {backButton}
            {watchlistToggle}
          </div>
          <span className="eyebrow">STOCK · {code}</span>
        </div>
        <SkeletonCard className="h-24" />
        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
          <SkeletonCard className="h-[420px] xl:col-span-8" />
          <div className="grid content-start gap-6 xl:col-span-4">
            <SkeletonCard className="h-48" />
            <SkeletonCard className="h-32" />
            <SkeletonCard className="h-32" />
            <SkeletonCard className="h-32" />
          </div>
        </div>
      </div>
    );
  }
  if (state === 'error' || !overview.data) {
    return (
      <div>
        <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {backButton}
            {watchlistToggle}
          </div>
          <span className="eyebrow">STOCK · {code}</span>
        </div>
        <section className="card-surface">
          <EmptyState
            variant="error"
            image="/empty-chart.svg"
            title={t('加载失败')}
            description={String(overview.error?.message ?? '')}
            action={<EmptyRetryButton onClick={() => overview.refresh({ force: true })} refreshing={overview.refreshing} />}
          />
        </section>
      </div>
    );
  }

  const data = overview.data;
  const security = data.security;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {backButton}
          <WatchlistToggle
            canonicalCode={security.canonical_code}
            displayCode={security.display_code}
          />
        </div>
        <span className="eyebrow">STOCK · {security.display_code}</span>
      </div>

      {/* ヘッダー：代码主读 + 名称次读，对齐美站 PriceHeader 节奏；不搬 Logo / 实时伪装。 */}
      <motion.header
        className="border-b border-line pb-3"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.48, ease: [0.16, 1, 0.3, 1] }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <CodeMark code={security.display_code} size={40} />
          <div className="min-w-0">
            <h1 className="flex flex-wrap items-baseline gap-x-2.5">
              <span className="font-display text-[22px] leading-[28px] font-bold text-ink-900">
                {security.display_code}
              </span>
              <span className="text-body-s text-ink-500">{security.name_ja ?? security.name_en ?? '—'}</span>
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <SessionLED session={session} />
              {security.sector33_name && <SoftBadge>{security.sector33_name}</SoftBadge>}
              {security.market_name && <SoftBadge>{security.market_name}</SoftBadge>}
              {security.scale_category && <SoftBadge>{security.scale_category}</SoftBadge>}
              {security.margin_name && <SoftBadge>{security.margin_name}</SoftBadge>}
              {security.active === 0 && (
                <SoftBadge tone="warn">
                  {t('上場廃止')} {security.delisted_date ?? ''}
                </SoftBadge>
              )}
            </div>
          </div>
          {data.radar_events[0] && (
            <div className="ml-auto text-right">
              <p className="eyebrow">
                {t('告警优先级')}
                <InfoHint hint={RADAR_SCORE_HINTS.优先级} side="bottom" align="end" size={12} className="ml-1" />
              </p>
              <StrengthBar score={data.radar_events[0].alert_priority} width={72} className="mt-1.5" />
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          {liveQuote ? (
            <div className="min-w-0">
              {/* 遅延気配を主表示にするが、必ず「遅延・非公式」と併記する。
                  公式の確定終値は隣に小さく残し、どちらの数字かを曖昧にしない。 */}
              <div
                className={cn(
                  'tick-flash rounded-xs',
                  headerFlashes[security.canonical_code] === 'up' && 'tick-flash-up',
                  headerFlashes[security.canonical_code] === 'down' && 'tick-flash-down',
                )}
              >
                <InsightValue
                  size="xl"
                  value={
                    <TickPrice flash={headerFlashes[security.canonical_code]}>
                      {fmtPrice(liveQuote.price)}
                    </TickPrice>
                  }
                  changePct={liveQuote.change_pct}
                  change={yenChangeFromPct(liveQuote.price, liveQuote.change_pct)}
                  basis={t('vs 昨收')}
                />
              </div>
              <span className="mt-0.5 flex items-center gap-1 text-micro text-warn-700">
                <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                {quoteSourceLabel(live.data).text}
                {liveQuote.as_of_epoch ? ` · ${fmtTimeJst(liveQuote.as_of_epoch)}` : ''}
              </span>
              <span className="mt-1 block font-mono text-micro tnum text-ink-400">
                {t('官方终值')} {fmtPrice(data.quote.close)} {data.quote.trade_date ?? ''}
              </span>
            </div>
          ) : (
            <div className="min-w-0">
              <div
                className={cn(
                  'tick-flash rounded-xs',
                  headerFlashes[security.canonical_code] === 'up' && 'tick-flash-up',
                  headerFlashes[security.canonical_code] === 'down' && 'tick-flash-down',
                )}
              >
                <InsightValue
                  size="xl"
                  value={
                    <TickPrice flash={headerFlashes[security.canonical_code]}>
                      {fmtPrice(data.quote.close)}
                    </TickPrice>
                  }
                  changePct={data.quote.change_pct}
                  change={yenChangeFromPct(data.quote.close, data.quote.change_pct)}
                  basis={t('vs 昨收')}
                />
              </div>
            </div>
          )}
          <p className="pb-1.5 text-right font-mono text-micro text-ink-500 tnum">
            {t('成交额')} {fmtYenCompact(data.quote.turnover_value)}
            {data.quote.volume != null ? ` · ${fmtShares(data.quote.volume)}${t('株')}` : ''}
          </p>
        </div>
        <DataThrough date={data.quote.trade_date} className="mt-2" />
      </motion.header>

      {/* 行1: K線 + 右侧紧凑栏 */}
      <div className="mt-8 grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
        <StockChart
          displayCode={security.display_code}
          interval={interval}
          onInterval={setInterval}
          range={range}
          onRange={setRange}
          priceMode={priceMode}
          onPriceMode={setPriceMode}
          bars={chart.data?.bars}
          barsLoading={chart.loading}
          overlays={technical?.chart_overlays}
          onRetry={() => chart.refresh({ force: true })}
        >
          {interval === 'tick' ? (
            <TickPane
              data={ticks.data ?? null}
              loading={ticks.loading}
              isOwner={isOwner}
              fetchNote={fetchNote}
              onFetch={async () => {
                try {
                  await workerApi.trigger('tick_fetch', { code: security.canonical_code });
                  toast.success(t('逐笔'), t('已提交，数据到达后刷新本页'));
                  setFetchNote(t('已提交，数据到达后刷新本页'));
                } catch (error) {
                  const message = String((error as Error).message ?? error);
                  toast.error(t('逐笔'), message);
                  setFetchNote(message);
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
                  toast.success(t('盘中'), t('已提交，数据到达后刷新本页'));
                  setFetchNote(t('已提交，数据到达后刷新本页'));
                } catch (error) {
                  const message = String((error as Error).message ?? error);
                  toast.error(t('盘中'), message);
                  setFetchNote(message);
                }
              }}
              onRefresh={() => intraday.refresh({ force: true })}
            />
          )}
        </StockChart>

        <div className="grid content-start gap-6 xl:col-span-4">
          <KeyStats code={code} quote={data.quote} />
          {/* 雷达 */}
          <section className="card-surface p-5">
            <p className="eyebrow">BREAKOUT RADAR</p>
            <h3 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('突破雷达')}</h3>
            {data.radar_events.length === 0 ? (
              <PanelEmpty image="/empty-radar.svg" title={t('暂无相关雷达事件')} />
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
          <section className="card-surface p-5">
            <p className="eyebrow">MARGIN</p>
            <h3 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('信用交易')}</h3>
            <MarginPanel rows={data.margin_interest} />
          </section>

          {/* 技术指标 */}
          <section className="card-surface p-5">
            <p className="eyebrow">TECHNICALS</p>
            <h3 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('技术指标')}</h3>
            <IndicatorGrid technical={technical} />
          </section>
        </div>
      </div>

      {/* 行2: 决算时间线 + 技术结构 */}
      <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
        <section className="card-surface p-5 xl:col-span-7">
          <p className="eyebrow">EARNINGS TIMELINE</p>
          <h2 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('决算时间线')}</h2>
          <div className="max-h-[360px] overflow-y-auto">
            <FinancialTable summaries={data.financials.summaries} />
          </div>
        </section>
        <section className="card-surface p-5 xl:col-span-5">
          <p className="eyebrow">CHART STRUCTURE</p>
          <h2 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('K线结构分析')}</h2>
          <StructurePanel technical={technical} />
        </section>
      </div>

      {/* 机构空卖行为：报告本身在下面的「空卖残高报告」，这里是行为分析 */}
      <section className="mt-6 card-surface p-5">
        <p className="eyebrow">SHORT BEHAVIOR</p>
        <h2 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('机构空卖行为')}</h2>
        <ShortBehaviorPanel code={security.canonical_code} />
      </section>

      {/* 行3: 空卖 + 发表预定 */}
      <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <section className="card-surface p-5">
          <p className="eyebrow">SHORT INTEREST</p>
          <h2 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('空卖残高报告')}</h2>
          <ShortPositionsPanel rows={data.short_positions} summary={data.short_interest} />
        </section>
        <section className="card-surface p-5">
          <p className="eyebrow">EARNINGS SCHEDULE</p>
          <h2 className="mb-4 mt-1.5 text-h3 text-ink-900">{t('发表预定')}</h2>
          {data.earnings.length === 0 ? (
            <PanelEmpty title={t('暂无数据')} />
          ) : (
            <ul>
              {data.earnings.slice(0, 4).map((item, index) => (
                <EarningsScheduleRow key={index} item={item} todayKey={todayKey} />
              ))}
            </ul>
          )}
        </section>
      </div>
      <SourceNote className="mt-8" text={t('官方终值来自日线；盘中价为延迟行情，不是实时伪装')} />
    </div>
  );
}

function PanelEmpty({ title, image = '/empty-chart.svg' }: { title: string; image?: string }) {
  return <EmptyState size="compact" image={image} title={title} />;
}

function EarningsScheduleRow({ item, todayKey }: { item: Record<string, unknown>; todayKey: string }) {
  const date = item.announcement_date ? String(item.announcement_date) : '';
  const quarter = item.fiscal_quarter ? String(item.fiscal_quarter) : '—';
  const anchor = dateAnchorParts(date);
  const isToday = date.slice(0, 10) === todayKey;
  return (
    <li className="flex min-h-[60px] items-center gap-3 px-1 py-[14px] transition-colors duration-fast hover:bg-paper-2/70">
      <span
        className={cn(
          'w-11 shrink-0 rounded-[9px] py-1.5 text-center',
          isToday ? 'bg-brand-50' : 'bg-paper-2/80',
        )}
      >
        <span className={cn('block font-mono text-body-s font-semibold tnum', isToday ? 'text-brand-700' : 'text-ink-900')}>
          {anchor ? anchor.day : '—'}
        </span>
        <span className="block text-micro text-ink-400">{anchor?.monthShort ?? ''}</span>
      </span>
      <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">{quarter}</span>
      <span className="shrink-0 font-mono text-caption tnum text-ink-500">
        {date ? fmtDate(date) : t('未定')}
      </span>
    </li>
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
  const colorMode = useColorMode();
  const option = useMemo(() => {
    void colorMode;
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
  }, [colorMode, data]);

  if (loading && !data) return <SkeletonCard className="h-[360px]" />;
  if (data && data.available && option) {
    return (
      <div>
        <ReactECharts className="h-[360px] w-full" option={option} ariaLabel="intraday chart" />
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
    <div className="flex h-[360px] flex-col items-center justify-center gap-3 rounded-md bg-paper-2">
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
          className="rounded-md bg-brand-600 px-3 py-1.5 text-body-s font-medium text-white shadow-btn-hi transition-[filter] hover:brightness-105"
        >
          {t('取得最近5个交易日的分钟数据')}
        </button>
      )}
      {isOwner && planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md border border-line px-3 py-1.5 text-caption text-ink-500 hover:bg-brand-50"
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
          ...insightLineSeries({
            data: points.map((point) => point.price),
            color: CH.brand600,
            xAxisIndex: 0,
            yAxisIndex: 0,
            smooth: false,
          }),
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

  if (loading && !data) return <SkeletonCard className="h-[360px]" />;
  if (data && data.available && option) {
    return (
      <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_232px]">
        <div className="min-w-0">
          <ReactECharts className="h-[360px] w-full" option={option} ariaLabel="tick chart" />
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
    <div className="flex h-[360px] flex-col items-center justify-center gap-3 rounded-md bg-paper-2">
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
          className="rounded-md bg-brand-600 px-3 py-1.5 text-body-s font-medium text-white shadow-btn-hi transition-[filter] hover:brightness-105"
        >
          {t('取得最近交易日的逐笔数据')}
        </button>
      )}
      {isOwner && planBlocked && (
        <button
          type="button"
          onClick={onFetch}
          className="rounded-md border border-line px-3 py-1.5 text-caption text-ink-500 hover:bg-brand-50"
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
  if (!technical) return <PanelEmpty title={t('暂无数据')} />;
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
            <SoftBadge key={label}>{t(label)}</SoftBadge>
          ))}
          {pa.spring && (
            <SoftBadge tone="up">
              {t('Spring 假跌破回收')}
              <InfoHint hint={STRUCTURE_HINTS.spring} size={11} />
            </SoftBadge>
          )}
          {pa.upthrust && (
            <SoftBadge tone="down">
              {t('Upthrust 假突破')}
              <InfoHint hint={STRUCTURE_HINTS.upthrust} size={11} />
            </SoftBadge>
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
          <SoftBadge tone="ai">{t(vpm.setup_label)}</SoftBadge>
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
  if (!technical) return <PanelEmpty title={t('暂无数据')} />;
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
          <SoftBadge>
            {row.fiscal_year_end?.slice(0, 7) ?? '—'} {row.period_type ?? ''}
          </SoftBadge>
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
  if (summaries.length === 0) return <PanelEmpty title={t('暂无数据')} />;
  return (
    <DataTable columns={columns} rows={summaries} rowKey={(row) => `${row.disclosed_date}-${row.disclosure_number}`} rowHeight={44} />
  );
}

function MarginPanel({ rows }: { rows: MarginInterestRow[] }) {
  if (rows.length === 0) return <PanelEmpty title={t('暂无数据')} />;
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
        {t('数据截至')} {fmtDate(latest.application_date)}（{t('週次')}）
      </p>
    </div>
  );
}

function ShortPositionsPanel({
  rows,
  summary,
}: {
  rows: ShortPositionRow[];
  summary: ShortInterestSummary | null;
}) {
  if (rows.length === 0) return <PanelEmpty title={t('暂无数据')} />;

  const changes = summary?.changes ?? [];
  const KIND_LABEL: Record<string, string> = {
    new: '新規',
    increased: '増',
    decreased: '減',
    below_threshold: '義務消失',
    closed: '解消',
    unknown: '状态未知',
  };
  // ラベルの色は **株にとっての向き**（赤=買い方に有利／緑=売り方に有利）。
  // 新しい売り方が出た＝弱気で緑、義務消失・解消＝買い戻し済みで赤。
  // 増減は隣の変化幅がすでに符号で色を持っているので、ここは無彩色にする
  // （同じことを二度色で言わない）。
  const KIND_TONE: Record<string, string> = {
    new: 'text-down-600',
    below_threshold: 'text-up-600',
    closed: 'text-up-600',
  };

  return (
    <div className="space-y-3">
      {summary && (
        <div className="rounded-md bg-paper-2 px-3 py-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-micro text-ink-400">{t('报告义务中合计')}</span>
            <span className="font-mono text-data-m text-ink-900 tnum">
              {summary.reporting_total != null ? `${(summary.reporting_total * 100).toFixed(2)}%` : '—'}
            </span>
            {summary.reporting_shares != null && (
              <span className="font-mono text-caption tnum text-ink-500">
                {fmtShares(summary.reporting_shares)}
                {t('株')}
              </span>
            )}
            <span className="text-micro text-ink-400">
              {t('{n}家', { n: summary.reporting_holders })}
            </span>
            {summary.change != null && (
              <span
                className={`font-mono text-caption tnum ${
                  summary.change > 0 ? 'text-up-600' : summary.change < 0 ? 'text-down-600' : 'text-ink-400'
                }`}
              >
                {t('2周')} {summary.change > 0 ? '+' : summary.change < 0 ? '−' : '±'}
                {Math.abs(summary.change * 100).toFixed(2)}%
              </span>
            )}
          </div>
          {/* 閾値割れは「その値以下のどこか」で実際は不明。合計に足さない。 */}
          {(summary.below_threshold_holders > 0 || summary.closed_holders > 0) && (
            <p className="mt-1 text-micro text-ink-400">
              {t('另有 {b} 家跌破{th}%（实际持仓不再披露）· {c} 家已解消', {
                b: summary.below_threshold_holders,
                th: (summary.reporting_threshold * 100).toFixed(1),
                c: summary.closed_holders,
              })}
            </p>
          )}
        </div>
      )}

      {changes.length > 0 ? (
        <div>
          <p className="mb-1 text-micro text-ink-400">
            {t('2周内全部变化')}
            {summary?.baseline_date ? `（${fmtDate(summary.baseline_date)} ~）` : ''}
          </p>
          {/* 1 行 2 段。横に 5 列並べると「義務消失」が折り返して行の高さが
              暴れるので、名前・区分・日付を上段、水準・株数・変化を下段に置く。 */}
          <ul>
            {changes.map((row, index) => (
              <li
                key={index}
                className="flex min-h-[60px] items-start gap-3 px-1 py-[14px] transition-colors duration-fast hover:bg-paper-2/70"
              >
                <div className="flex w-11 shrink-0 flex-col items-center self-stretch pt-0.5">
                  <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">
                    {fmtDateShort(row.calculated_date)}
                  </span>
                  <span className="mt-1.5 hidden w-[2px] flex-1 rounded-full bg-line sm:block" aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-body-s text-ink-700">{row.holder_name ?? '—'}</span>
                    <span className={`shrink-0 whitespace-nowrap text-micro ${KIND_TONE[row.kind] ?? 'text-ink-400'}`}>
                      {t(KIND_LABEL[row.kind] ?? '')}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-caption tnum">
                    <span className="text-ink-900">
                      {row.ratio != null ? `${(row.ratio * 100).toFixed(2)}%` : '—'}
                    </span>
                    {row.shares != null && (
                      <span className="text-ink-500">
                        {fmtShares(row.shares)}
                        {t('株')}
                      </span>
                    )}
                    <span
                      className={
                        row.delta == null
                          ? 'text-ink-400'
                          : row.delta > 0
                            ? 'text-up-600'
                            : row.delta < 0
                              ? 'text-down-600'
                              : 'text-ink-400'
                      }
                    >
                      {row.delta != null
                        ? `${row.delta > 0 ? '+' : row.delta < 0 ? '−' : '±'}${Math.abs(row.delta * 100).toFixed(2)}%`
                        : '—'}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <PanelEmpty title={t('2周内没有新的残高报告')} />
      )}
    </div>
  );
}

function MiniStat({ label, value, hint }: { label: string; value: string; hint?: ScoreHint }) {
  return (
    <div className="rounded-md bg-paper-2 px-1.5 py-1.5 text-center">
      <div className="truncate font-mono text-body-s tnum text-ink-900">{value}</div>
      <div className="flex items-center justify-center gap-0.5 text-micro text-ink-400">
        {/* label は msgid（呼び出し側は中文原文）—— ここで訳さないと三言語とも中文のまま */}
        <PointerTooltip
          label={t(label)}
          width={140}
          contentClassName="p-2"
          content={<span className="text-micro text-ink-600">{t(label)}</span>}
        >
          <span className="truncate">{t(label)}</span>
        </PointerTooltip>
        {hint && <InfoHint hint={hint} size={11} side="bottom" />}
      </div>
    </div>
  );
}
