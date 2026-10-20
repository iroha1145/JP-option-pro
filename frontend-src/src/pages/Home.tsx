/** 首页：指数卡 → 广度/业种 → 雷达 → 决算 → 自选异动。 */

import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router';
import { motion, useReducedMotion } from 'framer-motion';
import { marketApi, radarApi, earningsApi, watchlistApi } from '@/api/modules';
import type { EarningsRecentItem, IndexSummary, RadarEvent, WatchlistItem } from '@/api/types';
import { ApiError } from '@/api/client';
import { invalidateQueryPaths } from '@/api/queryRegistry';
import { useAccess } from '@/hooks/useAccess';
import { usePolling } from '@/hooks/usePolling';
import { useNow } from '@/hooks/useNow';
import { useTickFlash } from '@/hooks/useTickFlash';
import TickPrice from '@/components/shared/TickPrice';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import { SkeletonCard, SkeletonReveal, SkeletonRows } from '@/components/shared/Skeleton';
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
import { dateAnchorParts, fmtPctLevel, fmtPrice, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import { jstToday } from '@/components/earnings/types';
import { EASE_PAPER } from '@/lib/motion';
import { cn } from '@/lib/utils';

const EMPTY_INDICES: IndexSummary[] = [];

function staggerDelay(index: number): number {
  return Math.min(index * 0.02, 0.12);
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
    return <EmptyState image={emptyImage} title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <>
      {error && <StaleStrip onRetry={onRetry} refreshing={refreshing} className="mx-4 mb-1 mt-2 md:mx-5" />}
      {children}
    </>
  );
}

function SignalListSkeleton({ rows }: { rows: number }) {
  return <div className="mt-3 border-t border-line"><SkeletonRows rows={rows} /></div>;
}

export default function Home() {
  const { canManageWatchlist, principalKey } = useAccess();
  const market = usePolling(() => marketApi.overview(), 120_000);
  const radar = usePolling(() => radarApi.current(), 120_000);
  const earnings = usePolling(() => earningsApi.recent(7), 300_000);
  const watchlist = usePolling(
    () => canManageWatchlist ? watchlistApi.list() : Promise.resolve<Awaited<ReturnType<typeof watchlistApi.list>>>({ items: [] }),
    120_000, [canManageWatchlist], { identity: principalKey },
  );
  const refreshMarket = () => {
    invalidateQueryPaths(['/market/overview'], { reload: true });
    market.refresh({ force: true });
  };
  const refreshRadar = () => {
    invalidateQueryPaths(['/radar/current'], { reload: true });
    radar.refresh({ force: true });
  };
  const refreshEarnings = () => {
    invalidateQueryPaths(['/earnings/recent'], { reload: true });
    earnings.refresh({ force: true });
  };
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
        title={t('首页')}
        meta={
          <>
            <SessionLED session={session} />
            {market.lastUpdatedAt && (
              <span className="tnum text-caption text-ink-400">
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
            <div className="index-summary-grid grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
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
                action={<RetryButton onClick={refreshMarket} refreshing={market.refreshing} />}
              />
            </div>
          ) : (
            <>
              {market.error && (
                <StaleStrip onRetry={refreshMarket} refreshing={market.refreshing} className="mb-3" />
              )}
              {indices.length === 0 && <div className="card-surface"><EmptyState image="/empty-chart.svg" title={t('暂无数据')} /></div>}
              <div className="index-summary-grid grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
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

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <SectionCard title={t('市场广度')} to="/market" className="lg:col-span-1">
          <ListBody
            loading={market.loading && !market.data}
            error={market.error}
            refreshing={market.refreshing}
            onRetry={refreshMarket}
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
                  <span className="metric-value tnum text-ink-900">{market.data.breadth.new_highs_252 ?? '—'}</span>
                </div>
                <div className="flex items-center justify-between text-body-s">
                  <span className="text-ink-500">{t('成交额')}</span>
                  <span className="metric-value tnum text-ink-900">{fmtYenCompact(market.data.breadth.total_turnover_value)}</span>
                </div>
                <div className="flex items-center justify-between text-body-s">
                    <span className="text-ink-500">{t('市场空卖占比')}</span>
                    <span className="metric-value tnum text-ink-900">{fmtPctLevel(market.data.short_selling?.market_short_ratio)}</span>
                </div>
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

        <SectionCard title={t('雷达信号')} to="/radar" className="order-first lg:order-none lg:col-span-2">
          <ListBody
            loading={radar.loading && !radar.data}
            error={radar.error}
            refreshing={radar.refreshing}
            onRetry={refreshRadar}
            isEmpty={events.length === 0}
            emptyTitle={radar.data?.scan_date ? t('暂无突破信号') : t('等待扫描结果')}
            emptyDescription={radar.data?.note ? t(radar.data.note) : t('日线扫描完成后更新信号。')}
            emptyImage="/empty-radar.svg"
            skeleton={<SignalListSkeleton rows={8} />}
            rows={8}
          >
            <div className="mt-3 divide-y divide-line border-t border-line">
              {events.map((event, index) => (
                <RadarSignalCard key={event.event_id} event={event} index={index} />
              ))}
            </div>
          </ListBody>
        </SectionCard>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <SectionCard title={t('近期财报')} to="/earnings">
          <ListBody
            loading={earnings.loading && !earnings.data}
            error={earnings.error}
            refreshing={earnings.refreshing}
            onRetry={refreshEarnings}
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

        <SectionCard title={t('关注动态')} to="/watchlist" className="lg:col-span-2">
          {!canManageWatchlist ? (
            <EmptyState
              image="/empty-watchlist.svg"
              title={t('登录后可以把关注股票保存在账号里')}
              description={t('与美股版共用账号，关注列表可跨设备查看')}
              action={<Link to="/login" className="btn-primary">{t('去登录 / 注册')}</Link>}
            />
          ) : <ListBody
            loading={watchlist.loading && !watchlist.data}
            error={watchlist.error}
            refreshing={watchlist.refreshing}
            onRetry={() => watchlist.refresh()}
            isEmpty={movers.length === 0}
            emptyTitle={t('暂无关注')}
            emptyDescription={t('打开股票详情，点击加入关注')}
            emptyImage="/empty-watchlist.svg"
            skeleton={<SignalListSkeleton rows={6} />}
          >
            <div className="mt-3 divide-y divide-line border-t border-line">
              {movers.map((item, index) => (
                <WatchlistMoverCard
                  key={item.canonical_code}
                  item={item}
                  index={index}
                  flash={moverFlashes[item.canonical_code]}
                />
              ))}
            </div>
          </ListBody>}
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
  const reduceMotion = useReducedMotion();
  const spark = index.sparkline.filter((value) => Number.isFinite(value));
  const change = index.change_pct ?? 0;
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER, delay: Math.min(cardIndex * 0.02, 0.12) }}
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
  const reduceMotion = useReducedMotion();
  const close = snapshotNumber(event.snapshot, 'close');
  const ret5 = snapshotNumber(event.snapshot, 'return_5d');
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER, delay: staggerDelay(index) }}
    >
      <Link to={`/stock/${event.display_code}`} className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors duration-150 hover:bg-paper-2/70 focus-visible:bg-paper-2/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400/60 md:px-5">
        <div className="flex min-w-0 flex-1 basis-40 items-center gap-2">
          <CodeMark code={event.display_code} size={28} />
          <div className="min-w-0">
            <p className="text-body-s font-semibold text-ink-900 tnum">{event.display_code}</p>
            <p className="truncate text-caption text-ink-500">{event.name_ja ?? '—'}</p>
          </div>
        </div>
        <div className="flex min-w-0 flex-1 basis-28 flex-col items-start gap-1">
          <SignalChip signal={event.signal_type} />
          <span className="text-micro text-ink-400">{t('数据截至')} {event.last_scanned_date || event.discovered_date || '—'}</span>
        </div>
        <div className="ml-auto flex shrink-0 flex-col items-end gap-1">
          <TickPrice className="text-body-s font-semibold text-ink-900 tnum">{fmtPrice(close)}</TickPrice>
          <span className="flex items-center gap-1 text-micro text-ink-400">
            {t('{n}日', { n: 5 })}<ChangeBadge value={ret5} size="sm" />
          </span>
        </div>
        <div className="hidden w-20 shrink-0 sm:block">
          <span className="text-micro text-ink-400">{t('告警优先级')}</span>
          <StrengthBar score={event.alert_priority} width={56} showScore className="mt-1" />
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
        <span className={cn('block tnum text-body-s font-semibold tnum', isToday ? 'text-brand-700' : 'text-ink-900')}>
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
  item, index, flash,
}: {
  item: WatchlistItem;
  index: number;
  flash?: 'up' | 'down';
}) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER, delay: staggerDelay(index) }}>
      <Link to={`/stock/${item.display_code}`} className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors duration-150 hover:bg-paper-2/70 focus-visible:bg-paper-2/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400/60 md:px-5">
        <CodeMark code={item.display_code} size={28} />
        <div className="min-w-0 flex-1 basis-20">
          <span className="text-body-s font-semibold text-ink-900 tnum">{item.display_code}</span>
          <p className="truncate text-caption text-ink-500">{item.name_ja ?? '—'}</p>
        </div>
        <div className="flex flex-1 basis-24 flex-col gap-1 text-micro text-ink-400">
          <span>{t('成交额')} {fmtYenCompact(item.quote?.turnover_value)}</span>
          <span>{t('数据截至')} {item.quote?.trade_date ?? '—'}</span>
        </div>
        <div className="ml-auto flex shrink-0 flex-col items-end gap-1">
          <TickPrice flash={flash} className="text-body-s font-semibold text-ink-900 tnum">{fmtPrice(item.quote?.close)}</TickPrice>
          <span className="flex items-center gap-1 text-micro text-ink-400">{t('当日')}<ChangeBadge value={item.quote?.change_pct} size="sm" /></span>
        </div>
      </Link>
    </motion.div>
  );
}
