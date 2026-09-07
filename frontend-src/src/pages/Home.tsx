/** 首页：指数卡 → 广度/业种 → 雷达 → 决算 → 自选异动。 */

import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { marketApi, radarApi, earningsApi, watchlistApi } from '@/api/modules';
import type { EarningsRecentItem, IndexSummary, RadarEvent, WatchlistItem } from '@/api/types';
import { ApiError } from '@/api/client';
import { usePolling } from '@/hooks/usePolling';
import { useNow } from '@/hooks/useNow';
import { useTickFlash } from '@/hooks/useTickFlash';
import TickPrice from '@/components/shared/TickPrice';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import { SkeletonBlock, SkeletonCard, SkeletonReveal, SkeletonRows } from '@/components/shared/Skeleton';
import StaleStrip from '@/components/shared/StaleStrip';
import SessionLED from '@/components/shared/SessionLED';
import SectionCard from '@/components/shared/SectionCard';
import StrengthBar from '@/components/shared/StrengthBar';
import AdvanceDeclineBar from '@/components/shared/AdvanceDeclineBar';
import Sparkline from '@/components/charts/Sparkline';
import CodeMark from '@/components/shared/CodeMark';
import { CodeCell, DataThrough, SignalChip } from '@/components/domain';
import { tokyoSession } from '@/lib/tokyoSession';
import { t } from '@/i18n/core';
import { dateAnchorParts, fmtPct, fmtPrice, fmtRelative, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import { jstToday } from '@/components/earnings/types';
import { DUR_SECTION, EASE_PAPER } from '@/lib/motion';
import { cn } from '@/lib/utils';

const EMPTY_INDICES: IndexSummary[] = [];

function staggerDelay(index: number): number {
  return Math.min(index * 0.04, 0.3);
}

function snapshotNumber(snapshot: RadarEvent['snapshot'], key: string): number | null {
  const value = snapshot[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function RetryButton({ onClick, refreshing }: { onClick: () => void; refreshing: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={refreshing} className="btn-primary">
      {refreshing && <span className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
      {t('重试')}
    </button>
  );
}

function ListBody({
  loading,
  error,
  refreshing,
  onRetry,
  isEmpty,
  emptyTitle,
  emptyDescription,
  emptyExtra,
  emptyImage,
  rows = 6,
  skeleton,
  children,
}: {
  loading: boolean;
  error: ApiError | null;
  refreshing: boolean;
  onRetry: () => void;
  isEmpty: boolean;
  emptyTitle: string;
  emptyDescription?: string;
  emptyExtra?: ReactNode;
  emptyImage?: string;
  rows?: number;
  skeleton?: ReactNode;
  children: ReactNode;
}) {
  if (loading) {
    if (skeleton) return <>{skeleton}</>;
    return (
      <div className="pb-2">
        <SkeletonRows rows={rows} />
      </div>
    );
  }
  if (error && isEmpty) {
    return (
      <EmptyState
        variant="error"
        image={emptyImage}
        title={error.code === 503 ? t('数据暂不可用') : t('加载失败')}
        description={error.message}
        action={<RetryButton onClick={onRetry} refreshing={refreshing} />}
      />
    );
  }
  if (isEmpty) {
    return (
      <>
        <EmptyState image={emptyImage} title={emptyTitle} description={emptyDescription} />
        {emptyExtra}
      </>
    );
  }
  return (
    <>
      {error && <StaleStrip onRetry={onRetry} refreshing={refreshing} className="mx-4 mb-1 mt-2 md:mx-5" />}
      {children}
    </>
  );
}

function SignalGridSkeleton({ cards }: { cards: number }) {
  return (
    <div
      className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5"
      aria-hidden="true"
    >
      {Array.from({ length: cards }, (_, index) => (
        <div key={index} className="card-surface rounded-lg p-3">
          <div className="flex items-center gap-2">
            <SkeletonBlock className="size-6 rounded-sm" />
            <SkeletonBlock className="h-3 w-12" />
            <SkeletonBlock className="h-4 w-14 rounded-xs" />
            <SkeletonBlock className="ml-auto h-3 w-8" />
          </div>
          <div className="mt-2 flex items-center gap-2">
            <SkeletonBlock className="h-3 w-24" />
            <SkeletonBlock className="ml-auto h-3 w-12" />
          </div>
          <SkeletonBlock className="mt-2 h-1 w-full rounded-pill" />
        </div>
      ))}
    </div>
  );
}

function MoverGridSkeleton({ cards }: { cards: number }) {
  return (
    <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5" aria-hidden="true">
      {Array.from({ length: cards }, (_, index) => (
        <div key={index} className="card-surface rounded-lg p-4">
          <div className="flex items-center gap-2">
            <SkeletonBlock className="h-3 w-10" />
            <SkeletonBlock className="h-3 w-20" />
            <SkeletonBlock className="ml-auto h-4 w-14" />
          </div>
          <SkeletonBlock className="mt-3 h-7 w-24" />
        </div>
      ))}
    </div>
  );
}

export default function Home() {
  const market = usePolling(() => marketApi.overview(), 120_000);
  const radar = usePolling(() => radarApi.current(), 120_000);
  const earnings = usePolling(() => earningsApi.recent(7), 300_000);
  const watchlist = usePolling(() => watchlistApi.list(), 120_000);
  const now = useNow(30_000);
  const session = tokyoSession(now);
  const todayKey = jstToday();

  const events = useMemo(() => {
    const seen = new Set<string>();
    const rows = [];
    for (const event of radar.data?.events ?? []) {
      if (seen.has(event.canonical_code)) continue;
      seen.add(event.canonical_code);
      rows.push(event);
      if (rows.length === 8) break;
    }
    return rows;
  }, [radar.data]);

  const movers = useMemo(() => {
    const mag = (value: number | null | undefined) =>
      typeof value === 'number' && Number.isFinite(value) ? Math.abs(value) : -1;
    return [...(watchlist.data?.items ?? [])]
      .sort((a, b) => mag(b.quote?.change_pct) - mag(a.quote?.change_pct))
      .slice(0, 6);
  }, [watchlist.data]);
  const indices = market.data?.indices ?? EMPTY_INDICES;
  const indexFlashes = useTickFlash(indices, (row) => row.index_code, (row) => row.close ?? null);
  const moverFlashes = useTickFlash(movers, (row) => row.canonical_code, (row) => row.quote?.close ?? null);

  return (
    <div>
      <PageHeader
        section="01"
        eyebrow="OPTIX JAPAN · DAILY RESEARCH"
        title={t('首页')}
        description={t('指数、信号与自选的全景。')}
        meta={
          <>
            <SessionLED session={session} />
            {market.lastUpdatedAt && (
              <span className="font-mono text-caption text-ink-400 tnum">
                {t('更新')} {fmtTimeHHMMSS(market.lastUpdatedAt)}
              </span>
            )}
            <DataThrough date={market.data?.data_through} />
          </>
        }
      />

      <section className="mt-8" aria-label={t('指数概览')}>
        <SkeletonReveal
          loading={market.loading && !market.data}
          skeleton={
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:[grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
              {Array.from({ length: 6 }).map((_, index) => (
                <SkeletonCard key={index} className="h-24" />
              ))}
            </div>
          }
        >
          {market.error && !market.data ? (
            <div className="card-surface">
              <EmptyState
                variant="error"
                image="/empty-chart.svg"
                title={market.error.code === 503 ? t('数据暂不可用') : t('加载失败')}
                description={market.error.message}
                action={<RetryButton onClick={() => market.refresh()} refreshing={market.refreshing} />}
              />
            </div>
          ) : (
            <>
              {market.error && (
                <StaleStrip onRetry={() => market.refresh()} refreshing={market.refreshing} className="mb-3" />
              )}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:[grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
                {indices.map((index, cardIndex) => (
                  <IndexInsightCard
                    key={index.index_code}
                    index={index}
                    cardIndex={cardIndex}
                    flash={indexFlashes[index.index_code]}
                  />
                ))}
              </div>
            </>
          )}
        </SkeletonReveal>
      </section>

      <div className="mt-8 grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
        <SectionCard title={t('市场广度')} to="/market" className="lg:col-span-1">
          <ListBody
            loading={market.loading && !market.data}
            error={market.error}
            refreshing={market.refreshing}
            onRetry={() => market.refresh()}
            isEmpty={!market.data}
            emptyTitle={t('暂无数据')}
            emptyImage="/empty-chart.svg"
            rows={6}
          >
            {market.data && (
              <div className="space-y-3 px-4 pb-4 md:px-5">
                <AdvanceDeclineBar
                  advancers={market.data.breadth.advancers}
                  decliners={market.data.breadth.decliners}
                  unchanged={market.data.breadth.unchanged}
                />
                <div className="flex items-center justify-between border-t border-line pt-2 text-body-s">
                  <span className="text-ink-500">{t('年内新高')}</span>
                  <span className="font-mono tnum text-ink-900">{market.data.breadth.new_highs_252 ?? '—'}</span>
                </div>
                <div className="flex items-center justify-between text-body-s">
                  <span className="text-ink-500">{t('成交额')}</span>
                  <span className="font-mono tnum text-ink-900">{fmtYenCompact(market.data.breadth.total_turnover_value)}</span>
                </div>
                {market.data.short_selling ? (
                  <div className="flex items-center justify-between text-body-s">
                    <span className="text-ink-500">{t('市场空卖占比')}</span>
                    <span className="font-mono tnum text-ink-900">{fmtPct(market.data.short_selling.market_short_ratio)}</span>
                  </div>
                ) : null}
                <ol className="space-y-1 border-t border-line pt-2">
                  {market.data.sectors.slice(0, 6).map((sector) => (
                    <li key={sector.sector33_code} className="flex items-center justify-between text-body-s">
                      <span className="truncate text-ink-700">{sector.sector33_name}</span>
                      <ChangeBadge value={sector.median_return_1d} size="sm" />
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </ListBody>
        </SectionCard>

        <SectionCard title={t('雷达信号')} to="/radar" className="lg:col-span-2">
          <ListBody
            loading={radar.loading && !radar.data}
            error={radar.error}
            refreshing={radar.refreshing}
            onRetry={() => radar.refresh()}
            isEmpty={events.length === 0}
            emptyTitle={t('雷达仍在盯')}
            emptyDescription={radar.data?.note ?? t('新信号出现时会立刻出现在这里。')}
            emptyImage="/empty-radar.svg"
            emptyExtra={<SignalGridSkeleton cards={8} />}
            skeleton={<SignalGridSkeleton cards={8} />}
            rows={8}
          >
            <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5">
              {events.map((event, index) => (
                <RadarSignalCard key={event.event_id} event={event} index={index} />
              ))}
            </div>
          </ListBody>
        </SectionCard>
      </div>

      <div className="mt-8 grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <SectionCard title={t('最近决算')} to="/earnings">
          <ListBody
            loading={earnings.loading && !earnings.data}
            error={earnings.error}
            refreshing={earnings.refreshing}
            onRetry={() => earnings.refresh()}
            isEmpty={(earnings.data?.items.length ?? 0) === 0}
            emptyTitle={t('暂无数据')}
            emptyImage="/empty-chart.svg"
          >
            <div className="divide-y divide-line">
              {(earnings.data?.items ?? []).slice(0, 6).map((item) => (
                <EarningsAnchorRow key={`${item.canonical_code}-${item.disclosed_date}-${item.period_type}`} item={item} todayKey={todayKey} />
              ))}
            </div>
          </ListBody>
        </SectionCard>

        <SectionCard title={t('自选异动')} to="/watchlist">
          <ListBody
            loading={watchlist.loading && !watchlist.data}
            error={watchlist.error}
            refreshing={watchlist.refreshing}
            onRetry={() => watchlist.refresh()}
            isEmpty={movers.length === 0}
            emptyTitle={t('暂无自选')}
            emptyDescription={t('在筛选器中添加')}
            emptyImage="/empty-watchlist.svg"
            skeleton={<MoverGridSkeleton cards={6} />}
          >
            <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5">
              {movers.map((item, index) => (
                <WatchlistMoverCard
                  key={item.canonical_code}
                  item={item}
                  index={index}
                  flash={moverFlashes[item.canonical_code]}
                />
              ))}
            </div>
          </ListBody>
        </SectionCard>
      </div>
    </div>
  );
}

function IndexInsightCard({
  index,
  cardIndex,
  flash,
}: {
  index: IndexSummary;
  cardIndex: number;
  flash?: 'up' | 'down';
}) {
  const spark = index.sparkline.filter((value) => Number.isFinite(value));
  const change = index.change_pct ?? 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: Math.min(cardIndex * 0.045, 0.4) }}
    >
      <Link
        to={`/market?index=${encodeURIComponent(index.index_code)}`}
        className="card-surface card-hover card-glare flex flex-col gap-1 rounded-lg p-3"
        aria-label={`${index.name} ${t('趋势快照')}`}
      >
        <span className="truncate text-caption text-ink-500">{index.name}</span>
        <TickPrice flash={flash} className="metric-value text-data-l text-ink-900 tnum">
          {fmtPrice(index.close)}
        </TickPrice>
        <span className="flex items-end justify-between gap-2">
          <ChangeBadge value={index.change_pct} size="sm" />
          {spark.length > 1 && <Sparkline data={spark} width={64} height={20} change={change} />}
        </span>
      </Link>
    </motion.div>
  );
}

function RadarSignalCard({ event, index }: { event: RadarEvent; index: number }) {
  const close = snapshotNumber(event.snapshot, 'close');
  const ret5 = snapshotNumber(event.snapshot, 'return_5d');
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: staggerDelay(index) }}
    >
      <Link to={`/stock/${event.display_code}`} className="card-surface card-hover block rounded-lg p-3">
        <div className="flex items-center gap-2">
          <CodeMark code={event.display_code} size={24} />
          <span className="shrink-0 font-mono text-caption font-semibold text-ink-800">{event.display_code}</span>
          <span className="min-w-0 truncate">
            <SignalChip signal={event.signal_type} />
          </span>
          <span className="ml-auto shrink-0 text-micro text-ink-400">
            {fmtRelative(event.last_scanned_date || event.discovered_date)}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-caption text-ink-500">{event.name_ja ?? '—'}</span>
          <TickPrice className="shrink-0 font-mono text-caption text-ink-800 tnum">{fmtPrice(close)}</TickPrice>
          {ret5 !== null && (
            <span className="flex shrink-0 items-center gap-1">
              <span className="text-micro text-ink-400">{t('{n}日', { n: 5 })}</span>
              <ChangeBadge value={ret5} size="sm" />
            </span>
          )}
        </div>
        <div className="mt-2">
          <StrengthBar score={event.alert_priority} width={56} showScore />
        </div>
      </Link>
    </motion.div>
  );
}

function EarningsAnchorRow({ item, todayKey }: { item: EarningsRecentItem; todayKey: string }) {
  const date = item.disclosed_date ?? '';
  const anchor = dateAnchorParts(date);
  const isToday = date.slice(0, 10) === todayKey;
  return (
    <Link
      to={`/stock/${item.display_code}`}
      className="flex items-center gap-3 px-4 py-2.5 transition-colors duration-fast hover:bg-paper-2/70 focus-visible:bg-paper-2/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400/60 md:px-5"
    >
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
      <CodeCell displayCode={item.display_code} nameJa={item.name_ja} />
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        {item.forecast_direction === 'upward' && <span className="text-micro text-up-700">{t('上方修正')}</span>}
        {item.forecast_direction === 'downward' && <span className="text-micro text-down-700">{t('下方修正')}</span>}
        <span className="rounded-md bg-paper-2 px-2 py-1 text-micro text-ink-600">{item.period_type ?? '—'}</span>
      </span>
    </Link>
  );
}

function WatchlistMoverCard({
  item,
  index,
  flash,
}: {
  item: WatchlistItem;
  index: number;
  flash?: 'up' | 'down';
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: staggerDelay(index) }}
    >
      <Link to={`/stock/${item.display_code}`} className="card-surface card-hover block rounded-lg p-4">
        <div className="flex items-center gap-2">
          <CodeMark code={item.display_code} size={24} />
          <span className="shrink-0 font-mono text-caption font-semibold text-ink-800">{item.display_code}</span>
          <span className="min-w-0 flex-1 truncate text-caption text-ink-500">{item.name_ja ?? '—'}</span>
          <span className="flex shrink-0 items-center gap-1.5">
            <span className="text-micro text-ink-400">{t('当日')}</span>
            <ChangeBadge value={item.quote?.change_pct} size="sm" />
          </span>
        </div>
        <div className="mt-2 flex items-end justify-between gap-2">
          <TickPrice flash={flash} className="metric-value text-data-l text-ink-900 tnum">
            {fmtPrice(item.quote?.close)}
          </TickPrice>
          <span className="font-mono text-micro text-ink-400 tnum">{fmtYenCompact(item.quote?.turnover_value)}</span>
        </div>
      </Link>
    </motion.div>
  );
}
