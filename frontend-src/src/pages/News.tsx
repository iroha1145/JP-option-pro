/** 新闻原文、关联股票和采集状态。 */

import { useCallback, useMemo, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { motion, useReducedMotion } from 'framer-motion';
import { newsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonBlock, SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import CodeMark from '@/components/shared/CodeMark';
import InfoHint from '@/components/shared/InfoHint';
import HorizontalScroller from '@/components/shared/HorizontalScroller';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import Switch from '@/components/shared/Switch';
import FilterButton from '@/components/shared/FilterButton';
import SelectionViewport from '@/components/shared/SelectionViewport';
import SourceNote from '@/components/shared/SourceNote';
import Icon from '@/components/icons';
import { NEWS_HINTS } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { explanationLines } from '@/lib/explainText';
import { fmtJstDateShort, fmtJstDateTime, fmtJstTime, fmtRelative, fmtTimeHHMMSS } from '@/lib/format';
import { EASE_PAPER } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type {
  NewsFeedState,
  NewsHotspotGroup,
  NewsItem,
  NewsSecurityRow,
  NewsStatus,
} from '@/api/types';

type Tab = 'feed' | 'stocks' | 'sources';

/** 値は API に渡す絞り込みキー（後端 `classify.CATEGORY_RULES` の日本語 taxonomy）。
 *  **表示のときだけ `t()` を通す** —— ここで訳した文字列を送ると何も引っかからない。 */
const CATEGORY_FILTERS = ['決算', '業績予想修正', 'M&A・TOB', '自社株買い', '配当', '日銀・金利', '規制・政策'];
const TABS: Tab[] = ['feed', 'stocks', 'sources'];
const HOURS = [24, 72, 168] as const;

function parseNewsSearch(sp: URLSearchParams): {
  tab: Tab;
  hours: 24 | 72 | 168;
  category: string | null;
  onlySecurities: boolean;
} {
  const rawTab = sp.get('tab');
  const tab = TABS.includes(rawTab as Tab) ? (rawTab as Tab) : 'feed';
  const rawHours = Number(sp.get('window'));
  const hours = (HOURS as readonly number[]).includes(rawHours) ? (rawHours as 24 | 72 | 168) : 72;
  const cat = sp.get('cls');
  const category = cat && CATEGORY_FILTERS.includes(cat) ? cat : null;
  return { tab, hours, category, onlySecurities: sp.get('sec') === '1' };
}

export default function News() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { tab, hours, category, onlySecurities } = useMemo(
    () => parseNewsSearch(searchParams),
    [searchParams],
  );
  const syncUrl = useCallback(
    (next: Partial<{ tab: Tab; hours: 24 | 72 | 168; category: string | null; onlySecurities: boolean }>) => {
      const current = parseNewsSearch(searchParams);
      const nextTab = next.tab ?? current.tab;
      const nextHours = next.hours ?? current.hours;
      const nextCategory = next.category !== undefined ? next.category : current.category;
      const nextOnly = next.onlySecurities ?? current.onlySecurities;
      const params = new URLSearchParams();
      if (nextTab !== 'feed') params.set('tab', nextTab);
      if (nextHours !== 72) params.set('window', String(nextHours));
      if (nextCategory) params.set('cls', nextCategory);
      if (nextOnly) params.set('sec', '1');
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const setTab = useCallback((value: Tab) => syncUrl({ tab: value }), [syncUrl]);
  const setHours = useCallback((value: 24 | 72 | 168) => syncUrl({ hours: value }), [syncUrl]);
  const setCategory = useCallback((value: string | null) => syncUrl({ category: value }), [syncUrl]);

  const feed = usePolling(
    () => newsApi.feed({ hours, category: category ?? undefined, only_securities: onlySecurities }),
    300_000,
    [hours, category, onlySecurities],
    { identity: `news-feed:${hours}:${category ?? 'all'}:${onlySecurities}` },
  );
  const hotspots = usePolling(() => newsApi.hotspots(hours), 300_000, [hours], { identity: `news-hotspots:${hours}` });
  const securities = usePolling(() => newsApi.securities(hours), 300_000, [hours], { identity: `news-securities:${hours}` });
  const status = usePolling(() => newsApi.status(), 300_000);

  const feedState = remoteState(feed, (d) => d.items.length === 0);
  const refreshingNews = status.refreshing || hotspots.refreshing
    || (tab === 'feed' && feed.refreshing)
    || (tab === 'stocks' && securities.refreshing);

  const onRefreshNews = useCallback(() => {
    if (refreshingNews) return;
    status.refresh({ force: true });
    hotspots.refresh({ force: true });
    if (tab === 'feed') feed.refresh({ force: true });
    if (tab === 'stocks') securities.refresh({ force: true });
  }, [feed, hotspots, refreshingNews, securities, status, tab]);

  return (
    <div>
      <PageHeader
        title={t('新闻')}
        description={t('查看新闻原文与关联股票')}
        meta={
          <>
            <StatusStrip status={status.data ?? null} />
            {status.lastUpdatedAt && (
              <span className="tnum text-caption text-ink-400">
                {t('更新')} {fmtTimeHHMMSS(status.lastUpdatedAt)}
              </span>
            )}
            <ForceRefreshButton
              onClick={onRefreshNews}
              spinning={refreshingNews}
              label={t('刷新新闻')}
              title={t('刷新新闻')}
            />
          </>
        }
      />

      {status.error && status.data && (
        <StaleStrip onRetry={() => status.refresh()} refreshing={status.refreshing} className="mt-4" />
      )}

      <div className="mt-8 flex min-w-0 flex-wrap items-center justify-between gap-2">
        <Segmented<Tab>
          options={[
            { value: 'feed', label: t('信息流') },
            { value: 'stocks', label: t('关联个股') },
            { value: 'sources', label: t('数据源') },
          ]}
          value={tab}
          onChange={setTab}
        />
        {(tab === 'feed' || tab === 'stocks') && (
          <Segmented<'24' | '72' | '168'>
            options={[
              { value: '24', label: t('近 24 小时') },
              { value: '72', label: t('近 3 天') },
              { value: '168', label: t('近 7 天') },
            ]}
            value={String(hours) as '24' | '72' | '168'}
            onChange={(value) => setHours(Number(value) as 24 | 72 | 168)}
          />
        )}
      </div>

      <div className="mt-4 space-y-5">
      {tab === 'feed' && (
        <>
          {feedState === 'stale' && (
            <StaleStrip onRetry={() => feed.refresh()} refreshing={feed.refreshing} />
          )}
          <div className="flex flex-wrap items-center gap-2">
            <SelectionViewport>
              <div className="filter-group" role="group" aria-label={t('类别')}>
                <FilterButton active={category === null} onClick={() => setCategory(null)}>
                  {t('全部')}
                </FilterButton>
                {CATEGORY_FILTERS.map((item) => (
                  <FilterButton
                    key={item}
                    active={category === item}
                    onClick={() => setCategory(category === item ? null : item)}
                  >
                    {t(item)}
                  </FilterButton>
                ))}
              </div>
            </SelectionViewport>
            <label className="ml-auto flex items-center gap-2 text-caption text-ink-600">
              <Switch
                checked={onlySecurities}
                onToggle={() => syncUrl({ onlySecurities: !onlySecurities })}
                label={t('仅看关联个股')}
                size="sm"
              />
              {t('仅看关联个股')}
            </label>
            <span className="text-caption text-ink-400">
              {t('共')} {feed.data?.items.length ?? '—'} {t('条')}
            </span>
          </div>

          <HotspotStrip
            groups={hotspots.data?.groups ?? []}
            loading={hotspots.loading && !hotspots.data}
            error={hotspots.error}
            onRetry={() => hotspots.refresh()}
            refreshing={hotspots.refreshing}
          />

          {feedState === 'loading' ? (
            <section className="card-surface overflow-hidden">
              <FeedSkeleton rows={8} />
            </section>
          ) : feedState === 'error' ? (
            <section className="card-surface">
              <EmptyState
                variant="error"
                image="/empty-news.svg"
                title={t('加载失败')}
                description={String(feed.error?.message ?? '')}
                action={
                  <EmptyRetryButton onClick={() => feed.refresh({ force: true })} refreshing={feed.refreshing} />
                }
              />
            </section>
          ) : feedState === 'empty' || (feedState === 'stale' && feed.data?.items.length === 0) ? (
            <section className="card-surface">
              <EmptyState image="/empty-news.svg" title={t('暂无数据')} description={feed.data?.note_ja ?? ''} />
            </section>
          ) : (
            <ul className="card-surface divide-y divide-line overflow-hidden">
              {feed.data!.items.map((item, index) => (
                <NewsRow key={item.news_id} item={item} index={index} animate={index < 24} />
              ))}
            </ul>
          )}
        </>
      )}

      {tab === 'stocks' && (
        <NewsPanelState error={securities.error} hasData={Boolean(securities.data)} onRetry={() => securities.refresh()} refreshing={securities.refreshing}>
          <StocksImpactPanel rows={securities.data?.rows ?? []} loading={securities.loading} />
        </NewsPanelState>
      )}

      {tab === 'sources' && (
        <NewsPanelState error={status.data ? null : status.error} hasData={Boolean(status.data)} onRetry={() => status.refresh()} refreshing={status.refreshing}>
          <div className="space-y-4">
            <StatusHero status={status.data ?? null} loading={status.loading && !status.data} />
            <SourcesPanel status={status.data ?? null} loading={status.loading} />
          </div>
        </NewsPanelState>
      )}
      </div>
    </div>
  );
}

/* ---------------- 状态条 ---------------- */

function NewsPanelState({
  error, hasData, onRetry, refreshing, children,
}: {
  error: { message: string } | null;
  hasData: boolean;
  onRetry: () => void;
  refreshing: boolean;
  children: ReactNode;
}) {
  if (error && !hasData) {
    return (
      <section className="card-surface">
        <EmptyState variant="error" image="/empty-news.svg" title={t('加载失败')} description={error.message}
          action={<EmptyRetryButton onClick={onRetry} refreshing={refreshing} />} />
      </section>
    );
  }
  return <>{error && <StaleStrip onRetry={onRetry} refreshing={refreshing} />}{children}</>;
}

function StatusStrip({ status }: { status: NewsStatus | null }) {
  if (!status) return null;
  const feedsOk = status.feeds.filter((feed) => !feed.last_error_code && feed.last_fetched_at).length;
  return (
    <span className="flex items-center gap-3 text-caption text-ink-500">
      <span>
        {t('数据源')} {feedsOk}/{status.feeds.length}
      </span>
    </span>
  );
}

function HeroCell({ label, index, children }: { label: string; index: number; children: ReactNode }) {
  return (
    <div
      className={cn(
        'min-w-0 border-line px-4 py-4 sm:px-5',
        index > 0 && 'border-t sm:border-l sm:border-t-0',
      )}
    >
      <p className="eyebrow">{label}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function StatusLed({
  tone,
  pulse = false,
}: {
  tone: 'brand' | 'warn' | 'muted';
  pulse?: boolean;
}) {
  const bg = {
    brand: 'bg-brand-600',
    warn: 'bg-warn-600',
    muted: 'bg-ink-400',
  }[tone];
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', bg, pulse && 'animate-led-pulse')}
      aria-hidden="true"
    />
  );
}

function StatusHero({ status, loading }: { status: NewsStatus | null; loading: boolean }) {
  const reduceMotion = useReducedMotion();
  const feedsOk = status?.feeds.filter((feed) => !feed.last_error_code && feed.last_fetched_at).length ?? 0;
  const lastFetch = status?.feeds
    .map((feed) => feed.last_fetched_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  const sourceTone: 'brand' | 'warn' | 'muted' = !status
    ? 'muted'
    : feedsOk === status.feeds.length && status.feeds.length > 0
      ? 'brand'
      : 'warn';
  return (
    <motion.section
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER }}
      aria-label={t('数据源')}
      className="card-surface"
    >
      <div className="grid grid-cols-1 sm:grid-cols-3">
        <HeroCell label={t('数据源')} index={0}>
          {loading ? (
            <div className="space-y-2">
              <SkeletonBlock className="h-5 w-24 max-w-full" />
              <SkeletonBlock className="h-2.5 w-16" />
            </div>
          ) : (
            <>
              <p className="flex items-center gap-2 metric-value text-data-m text-ink-900 tnum">
                <StatusLed tone={sourceTone} pulse={sourceTone === 'brand'} />
                {status ? `${feedsOk}/${status.feeds.length}` : '—'}
              </p>
              <p className="mt-1 text-micro text-ink-400">
                {t('上次采集')} {fmtRelative(lastFetch)}
              </p>
            </>
          )}
        </HeroCell>
        <HeroCell label={t('最近采集')} index={1}>
          {loading ? (
            <SkeletonBlock className="h-5 w-28" />
          ) : (
            <p className="text-body-s text-ink-900 tnum">{lastFetch ? fmtJstDateTime(lastFetch) : '—'}</p>
          )}
        </HeroCell>
        <HeroCell label={t('采集窗口')} index={2}>
          {loading ? (
            <SkeletonBlock className="h-5 w-14" />
          ) : (
            <p className="metric-value text-data-m text-ink-900 tnum">
              {status ? t('{n} 小时', { n: status.window_hours }) : '—'}
            </p>
          )}
        </HeroCell>
      </div>
      <details className="group border-t border-line px-4 py-1 sm:px-5">
        <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 text-caption text-ink-500 marker:content-none [&::-webkit-details-marker]:hidden">
          {t('数据说明')}
          <Icon
            name="chevron-down"
            size={14}
            className="shrink-0 transition-transform duration-fast group-open:rotate-180 motion-reduce:transition-none"
          />
        </summary>
        <SourceNote
          className="border-0 pb-3 pt-1"
          text={t('新闻按原始语言展示，标题与摘要来自新闻源。关联个股依据代码与名称匹配，重要度依据规则评分。')}
        />
      </details>
    </motion.section>
  );
}

function FeedSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="t-skel" data-state="loading" aria-hidden="true">
      <div className="t-skel-skeleton is-pulsing divide-y divide-line">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex min-h-[60px] gap-3 px-4 py-[18px] sm:px-5">
            <div className="flex w-11 shrink-0 flex-col items-center">
              <SkeletonBlock className="h-3 w-8" />
              <SkeletonBlock className="mt-1.5 hidden w-[2px] flex-1 sm:block" />
            </div>
            <div className="min-w-0 flex-1">
              <SkeletonBlock className="h-2.5 w-28" />
              <SkeletonBlock className="mt-2 h-4 w-3/4" />
              <SkeletonBlock className="mt-2 h-3 w-full" />
              <div className="mt-2.5 flex gap-2">
                <SkeletonBlock className="h-4 w-10" />
                <SkeletonBlock className="h-4 w-14" />
                <SkeletonBlock className="h-4 w-16" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const JST_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo' });

function TimeCol({ iso }: { iso: string | null }) {
  if (!iso) {
    return (
      <div className="flex w-11 shrink-0 flex-col items-center pt-0.5">
        <span className="tnum text-[11px] leading-[14px] text-ink-400">—</span>
      </div>
    );
  }
  const sameDay = JST_DAY.format(new Date(iso)) === JST_DAY.format(new Date());
  return (
    <div className="flex w-11 shrink-0 flex-col items-center pt-0.5">
      <span className="tnum text-[11px] leading-[14px] text-ink-400">
        {sameDay ? fmtJstTime(iso) : fmtJstDateShort(iso)}
      </span>
      <span className="mt-1.5 hidden w-[2px] flex-1 rounded-full bg-line sm:block" aria-hidden="true" />
    </div>
  );
}

/* ---------------- 信息流 ---------------- */

function ImportanceBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <SoftBadge>—</SoftBadge>;
  }
  const tone = value >= 75 ? 'warn' : value >= 55 ? 'brand' : 'neutral';
  return (
    <InfoHint hint={NEWS_HINTS.importance} side="bottom" size={11}>
      <SoftBadge tone={tone}>{Math.round(value)}</SoftBadge>
    </InfoHint>
  );
}

function HotspotStrip({
  groups,
  loading,
  error,
  onRetry,
  refreshing = false,
}: {
  groups: NewsHotspotGroup[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  refreshing?: boolean;
}) {
  return (
    <section aria-label={t('热点主题')}>
      <h3 className="mb-2 mt-1 text-h3 text-ink-900">{t('热点主题')}</h3>
      {Boolean(error) && groups.length > 0 && <StaleStrip onRetry={onRetry} refreshing={refreshing} className="mb-2" />}
      {loading ? (
        <HorizontalScroller className="mt-1" scrollerClassName="pb-1" label={t('热点主题带，可横向滚动')}>
          <div className="flex gap-2">
            {Array.from({ length: 3 }, (_, index) => (
              <SkeletonCard key={index} className="h-28 min-w-[220px] max-w-[260px] shrink-0" />
            ))}
          </div>
        </HorizontalScroller>
      ) : error && groups.length === 0 ? (
        <section className="card-surface">
          <EmptyState
            size="compact"
            variant="error"
            image="/empty-news.svg"
            title={t('加载失败')}
            action={
              <EmptyRetryButton onClick={onRetry} refreshing={refreshing} />
            }
          />
        </section>
      ) : groups.length === 0 ? (
        <section className="card-surface">
          <EmptyState size="compact" image="/empty-news.svg" title={t('当前窗口暂无热点分组')} />
        </section>
      ) : (
        <HorizontalScroller className="mt-1" scrollerClassName="pb-1" label={t('热点主题带，可横向滚动')}>
          <div className="flex gap-2">
            {groups.map((group, index) => (
              <HotspotCard key={group.canonical_code} group={group} index={index} />
            ))}
          </div>
        </HorizontalScroller>
      )}
    </section>
  );
}

function HotspotCard({ group, index }: { group: NewsHotspotGroup; index: number }) {
  const reduceMotion = useReducedMotion();
  const heat = Math.max(0, Math.min(100, group.max_importance ?? 0));
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER, delay: Math.min(index * 0.02, 0.12) }}
    >
    <Link
      to={`/stock/${group.display_code}`}
      className="card-surface card-hover flex min-w-[220px] max-w-[260px] shrink-0 flex-col gap-1.5 p-3"
    >
      <span className="flex items-center gap-1.5">
        <CodeMark code={group.display_code} size={22} />
        <span className="tnum text-caption font-semibold text-brand-700">{group.display_code}</span>
        <span className="min-w-0 truncate text-caption text-ink-700">{group.name_ja ?? '—'}</span>
        <span className="ml-auto">
          <ImportanceBadge value={group.max_importance} />
        </span>
      </span>
      <span className="line-clamp-2 text-caption text-ink-600">{group.latest?.title ?? '—'}</span>
      <span className="strength-track flex h-1 overflow-hidden rounded-pill" aria-label={`${t('热度')} ${heat}`}>
        <span className="block h-full rounded-pill bg-warn-600" style={{ width: `${heat}%` }} />
      </span>
      <span className="flex items-center gap-1.5 text-micro text-ink-400">
        <span>{group.item_count} {t('条')}</span>
        {group.categories.slice(0, 2).map((cat) => (
          <SoftBadge key={cat}>{t(cat)}</SoftBadge>
        ))}
      </span>
    </Link>
    </motion.div>
  );
}

function NewsRow({ item, index, animate = true }: { item: NewsItem; index: number; animate?: boolean }) {
  const reduceMotion = useReducedMotion();
  const title = item.original_title ?? '—';
  return (
    <motion.li
      initial={animate && !reduceMotion ? { opacity: 0, y: 8 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE_PAPER, delay: animate ? Math.min(index * 0.02, 0.12) : 0 }}
      className="flex gap-3 px-4 py-5 sm:px-5"
    >
      <TimeCol iso={item.published_at} />
      <article className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-micro text-ink-400">
          <span className="font-medium text-ink-600">{item.source ?? '—'}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={item.published_at ?? undefined} className="tnum">{fmtRelative(item.published_at)}</time>
          <span className="ml-auto"><ImportanceBadge value={item.importance} /></span>
        </p>
        <h3 className="mt-2 text-[16px] font-semibold leading-6 text-ink-900">
          {item.source_url ? (
            <a href={item.source_url} target="_blank" rel="noreferrer" className="rounded-xs underline-offset-4 hover:text-brand-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/60">
              {title}
              <Icon name="arrow-up-right" size={13} className="ml-1.5 inline-block text-ink-400" />
              <span className="sr-only">{t('原文')}</span>
            </a>
          ) : title}
        </h3>
        {item.original_summary && <p className="mt-2 line-clamp-3 text-body-s leading-relaxed text-ink-600">{item.original_summary}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {(item.categories ?? []).slice(0, 3).map((cat) => <SoftBadge key={cat}>{t(cat)}</SoftBadge>)}
          {item.securities.map((security) => (
            <Link key={security.canonical_code} to={`/stock/${security.display_code}`}>
              <SoftBadge tone="brand" className="hover:underline">
                <span className="tnum">{security.display_code}</span>
                {security.name_ja ? ` ${security.name_ja}` : ''}
              </SoftBadge>
            </Link>
          ))}
        </div>
        <details className="group mt-3 border-t border-line pt-2 text-caption text-ink-500">
          <summary className="flex min-h-8 cursor-pointer list-none items-center gap-1.5 rounded-xs marker:content-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/60 [&::-webkit-details-marker]:hidden">
            <Icon name="chevron-down" size={13} className="transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
            {t('新闻详情')}
          </summary>
          <div className="space-y-2 pb-1 pt-1">
            {item.original_summary && <p className="leading-relaxed text-ink-600">{item.original_summary}</p>}
            {(item.importance_reason_items?.length ?? item.importance_reasons?.length ?? 0) > 0 && (
              <p>{t('重要度依据')}: {explanationLines(item.importance_reason_items, item.importance_reasons).join(' · ')}</p>
            )}
            <p>{t('发布')}: {fmtJstDateTime(item.published_at)} · {t('语言')}: {item.source_language ?? '—'}
              {item.market_relevance === 'market' && <span> · {t('市场级新闻')}</span>}
            </p>
            {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline">{t('原文')}<Icon name="arrow-up-right" size={12} /></a>}
          </div>
        </details>
      </article>
    </motion.li>
  );
}

/* ---------------- 个股影响 ---------------- */

function StocksImpactPanel({ rows, loading }: { rows: NewsSecurityRow[]; loading: boolean }) {
  const columns = useMemo<Column<NewsSecurityRow>[]>(
    () => [
      {
        key: 'code',
        title: t('代码'),
        width: '30%',
        render: (row) => (
          <Link to={`/stock/${row.display_code}`} className="flex min-w-0 items-center gap-2 hover:underline">
            <span className="rounded-md bg-brand-50 px-1.5 py-0.5 tnum text-body-s font-semibold text-brand-700">
              {row.display_code}
            </span>
            <span className="min-w-0 truncate text-body-s text-ink-800">{row.name_ja ?? '—'}</span>
          </Link>
        ),
      },
      {
        key: 'count',
        title: t('新闻数'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.news_count,
        render: (row) => <span className="tnum text-body-s">{row.news_count}</span>,
      },
      {
        key: 'importance',
        title: t('最高重要度'),
        hint: <InfoHint hint={NEWS_HINTS.importance} side="bottom" size={11} />,
        align: 'right',
        sortable: true,
        sortValue: (row) => row.max_importance ?? -1,
        render: (row) => <ImportanceBadge value={row.max_importance} />,
      },
      {
        key: 'categories',
        title: t('主要类别'),
        render: (row) => (
          <span className="flex flex-wrap gap-1">
            {row.categories.map((cat) => (
              <SoftBadge key={cat}>{t(cat)}</SoftBadge>
            ))}
          </span>
        ),
      },
      {
        key: 'latest',
        title: t('最新标题'),
        width: '30%',
        render: (row) => <span className="line-clamp-1 text-caption text-ink-600">{row.latest?.title ?? '—'}</span>,
      },
    ],
    [],
  );
  if (loading && rows.length === 0) return <SkeletonRows rows={8} />;
  if (rows.length === 0) {
    return (
      <section className="card-surface">
        <EmptyState image="/empty-news.svg" title={t('暂无数据')} />
      </section>
    );
  }
  return <DataTable columns={columns} rows={rows} rowKey={(row) => row.canonical_code} rowHeight={44} />;
}

/* ---------------- 数据源 ---------------- */

function feedHost(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function feedHealth(feed: NewsFeedState): { tone: 'brand' | 'warn' | 'neutral'; label: string } {
  if (feed.last_error_code) return { tone: 'warn', label: t('异常') };
  if (feed.last_fetched_at) return { tone: 'brand', label: t('正常') };
  return { tone: 'neutral', label: t('未采集') };
}

function SourcesPanel({ status, loading }: { status: NewsStatus | null; loading: boolean }) {
  const reduceMotion = useReducedMotion();
  if (loading && !status) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <SkeletonCard key={index} />
        ))}
      </div>
    );
  }
  if (!status || status.feeds.length === 0) {
    return (
      <section className="card-surface">
        <EmptyState image="/empty-news.svg" title={t('暂无数据')} />
      </section>
    );
  }
  return (
    <div className="space-y-4">
      <motion.div
        initial={reduceMotion ? false : 'hidden'}
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.02 } } }}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
      >
        {status.feeds.map((feed) => {
          const health = feedHealth(feed);
          return (
            <motion.section
              key={feed.feed_url}
              variants={{
                hidden: { opacity: 0, y: 8 },
                show: { opacity: 1, y: 0, transition: { duration: 0.22, ease: EASE_PAPER } },
              }}
              className="card-surface p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-micro text-ink-400">{t('新闻源')}</p>
                  <h3 className="mt-1 truncate text-h3 text-ink-900">{feedHost(feed.feed_url)}</h3>
                  <p className="mt-0.5 truncate tnum text-micro text-ink-400">{feed.feed_url}</p>
                </div>
                <SoftBadge tone={health.tone}>
                  <span
                    className={cn(
                      'inline-block size-1.5 rounded-full',
                      health.tone === 'brand' ? 'bg-brand-600' : health.tone === 'warn' ? 'bg-warn-600' : 'bg-ink-300',
                    )}
                    aria-hidden
                  />
                  {health.label}
                </SoftBadge>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-center">
                <div>
                  <p className="metric-value text-data-l text-ink-900 tnum">{feed.items_seen.toLocaleString('ja-JP')}</p>
                  <p className="mt-0.5 text-micro text-ink-400">{t('累计')}</p>
                </div>
                <div>
                  <p className="tnum text-data-l text-ink-900">
                    {feed.last_fetched_at ? fmtRelative(feed.last_fetched_at) : '—'}
                  </p>
                  <p className="mt-0.5 text-micro text-ink-400">{t('最近取得')}</p>
                </div>
              </div>
              {feed.last_error_code && (
                <p className="mt-3 border-t border-line pt-2.5 tnum text-micro text-down-700">{feed.last_error_code}</p>
              )}
            </motion.section>
          );
        })}
      </motion.div>
      <p className="text-micro text-ink-400">
        {t('实体目录')}: {status.entity_aliases.toLocaleString('ja-JP')} · {t('同步间隔')}: {status.sync_seconds}s
      </p>
    </div>
  );
}
