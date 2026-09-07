/** 首页：指数卡 → 广度/业种 → 雷达 → 决算 → 自选异动。 */

import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { marketApi, radarApi, earningsApi, watchlistApi } from '@/api/modules';
import type { IndexSummary } from '@/api/types';
import { ApiError } from '@/api/client';
import { usePolling } from '@/hooks/usePolling';
import { useNow } from '@/hooks/useNow';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import StaleStrip from '@/components/shared/StaleStrip';
import SessionLED from '@/components/shared/SessionLED';
import SectionCard from '@/components/shared/SectionCard';
import SoftBadge from '@/components/shared/SoftBadge';
import InsightLineChart, { type InsightScrub } from '@/components/charts/InsightLineChart';
import { CodeCell, DataThrough, SignalChip, StateChip } from '@/components/domain';
import { tokyoSession } from '@/lib/tokyoSession';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import { cn } from '@/lib/utils';

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
        title={error.code === 503 ? t('数据暂不可用') : t('加载失败')}
        description={error.message}
        action={<RetryButton onClick={onRetry} refreshing={refreshing} />}
      />
    );
  }
  if (isEmpty) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return (
    <>
      {error && <StaleStrip onRetry={onRetry} refreshing={refreshing} className="mx-4 mb-1 mt-2 md:mx-5" />}
      {children}
    </>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: number | null; tone: 'up' | 'down' | 'flat' }) {
  return (
    <div className="rounded-[9px] bg-paper-2/70 py-2.5 text-center">
      <p
        className={cn(
          'metric-value text-data-l tnum',
          value === null
            ? 'text-ink-400'
            : tone === 'up'
              ? 'text-up-700'
              : tone === 'down'
                ? 'text-down-700'
                : 'text-ink-500',
        )}
      >
        {value === null ? '—' : value}
      </p>
      <p className="mt-0.5 text-micro text-ink-400">{label}</p>
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
        {market.loading && !market.data ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} className="h-44" />
            ))}
          </div>
        ) : market.error && !market.data ? (
          <div className="card-surface">
            <EmptyState
              variant="error"
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
            <div className="stagger-in grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(market.data?.indices ?? []).map((index) => (
                <IndexInsightCard key={index.index_code} index={index} />
              ))}
            </div>
          </>
        )}
      </section>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <SectionCard title={t('市场广度')} to="/market" className="lg:col-span-1">
          <ListBody
            loading={market.loading && !market.data}
            error={market.error}
            refreshing={market.refreshing}
            onRetry={() => market.refresh()}
            isEmpty={!market.data}
            emptyTitle={t('暂无数据')}
            rows={6}
          >
            {market.data && (
              <div className="space-y-3 px-4 pb-4 md:px-5">
                <div className="grid grid-cols-3 gap-2">
                  <MiniStat label={t('上涨')} value={market.data.breadth.advancers} tone="up" />
                  <MiniStat label={t('下跌')} value={market.data.breadth.decliners} tone="down" />
                  <MiniStat label={t('平盘')} value={market.data.breadth.unchanged} tone="flat" />
                </div>
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
            emptyTitle={t('暂无数据')}
            emptyDescription={radar.data?.note ?? undefined}
            rows={8}
          >
            <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5">
              {events.map((event, index) => (
                <motion.div
                  key={event.event_id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.36, delay: index * 0.045, ease: [0.16, 1, 0.3, 1] }}
                >
                  <Link
                    to={`/stock/${event.display_code}`}
                    className="card-surface card-lift flex items-start justify-between gap-3 p-3"
                  >
                    <CodeCell displayCode={event.display_code} nameJa={event.name_ja} />
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <span className="flex items-center gap-1.5">
                        <SignalChip signal={event.signal_type} />
                        <StateChip state={event.state} />
                      </span>
                      <span className="font-mono text-body-s tnum text-ink-900">
                        {event.alert_priority !== null ? Math.round(event.alert_priority) : '—'}
                      </span>
                    </span>
                  </Link>
                </motion.div>
              ))}
            </div>
          </ListBody>
        </SectionCard>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard title={t('最近决算')} to="/earnings">
          <ListBody
            loading={earnings.loading && !earnings.data}
            error={earnings.error}
            refreshing={earnings.refreshing}
            onRetry={() => earnings.refresh()}
            isEmpty={(earnings.data?.items.length ?? 0) === 0}
            emptyTitle={t('暂无数据')}
          >
            <ul className="divide-y divide-line px-4 pb-2 md:px-5">
              {(earnings.data?.items ?? []).slice(0, 6).map((item) => (
                <li key={`${item.canonical_code}-${item.disclosed_date}-${item.period_type}`} className="flex items-center gap-3 py-2.5">
                  <CodeCell displayCode={item.display_code} nameJa={item.name_ja} to={`/stock/${item.display_code}`} />
                  <span className="ml-auto flex items-center gap-2 text-caption text-ink-500">
                    <span>{fmtDate(item.disclosed_date)}</span>
                    <SoftBadge>{item.period_type ?? '—'}</SoftBadge>
                    {item.forecast_direction === 'upward' && <span className="text-up-700">{t('上方修正')}</span>}
                    {item.forecast_direction === 'downward' && <span className="text-down-700">{t('下方修正')}</span>}
                  </span>
                </li>
              ))}
            </ul>
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
          >
            <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 pt-3 sm:grid-cols-2 md:px-5 md:pb-5">
              {movers.map((item, index) => (
                <motion.div
                  key={item.canonical_code}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.36, delay: index * 0.045, ease: [0.16, 1, 0.3, 1] }}
                >
                  <Link
                    to={`/stock/${item.display_code}`}
                    className="card-surface card-lift flex items-center justify-between gap-3 p-3"
                  >
                    <CodeCell displayCode={item.display_code} nameJa={item.name_ja} />
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <span className="font-mono text-body-s tnum text-ink-900">{fmtPrice(item.quote?.close)}</span>
                      <ChangeBadge value={item.quote?.change_pct} size="sm" />
                    </span>
                  </Link>
                </motion.div>
              ))}
            </div>
          </ListBody>
        </SectionCard>
      </div>
    </div>
  );
}

function IndexInsightCard({ index }: { index: IndexSummary }) {
  const [scrub, setScrub] = useState<InsightScrub | null>(null);
  const value = scrub?.value ?? index.close;
  const windowN = Math.max(index.sparkline.length, 1);
  const badgeValue =
    scrub && scrub.index > 0 && index.sparkline[scrub.index - 1]
      ? scrub.value / index.sparkline[scrub.index - 1] - 1
      : scrub
        ? null
        : index.change_pct;
  const first = index.sparkline[0];
  const lastValue = index.sparkline[index.sparkline.length - 1];
  const windowReturn = first && lastValue != null && index.sparkline.length > 1 ? lastValue / first - 1 : null;
  return (
    <Link to={`/market?index=${encodeURIComponent(index.index_code)}`} className="card-surface card-glare card-hover flex flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 pt-3">
        <span className="truncate text-caption text-ink-500">{index.name}</span>
        <SoftBadge>{t('快照')}</SoftBadge>
      </div>
      <div className="mt-2 border-t border-line px-2 pt-2">
        <InsightLineChart
          data={index.sparkline}
          height={72}
          change={index.change_pct ?? 0}
          interactive
          focusable={false}
          showLiveDot
          onScrub={setScrub}
          ariaLabel={`${index.name} ${t('趋势快照')}`}
        />
      </div>
      <div className="flex items-baseline justify-between gap-2 px-3 pb-3 pt-1">
        <span className="metric-value text-data-xl tnum text-ink-900">{fmtPrice(value)}</span>
        <span className="flex items-center gap-1.5">
          <ChangeBadge value={badgeValue} size="sm" />
          <span className="text-micro text-ink-400">
            {t('{n}日', { n: windowN })} {fmtPct(windowReturn)}
          </span>
        </span>
      </div>
    </Link>
  );
}
