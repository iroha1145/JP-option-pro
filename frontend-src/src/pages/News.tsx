/** 新闻催化剂桌面 — 对齐美版信息设计：
 *  信息流（过滤+热点条+重要度+AI状态） / 个股影响 / 经济日历 / 数据源。 */

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { newsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonBlock, SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import CodeMark from '@/components/shared/CodeMark';
import InfoHint from '@/components/shared/InfoHint';
import PointerTooltip from '@/components/shared/PointerTooltip';
import HorizontalScroller from '@/components/shared/HorizontalScroller';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import Switch from '@/components/shared/Switch';
import AnalysisIcon from '@/components/shared/AnalysisIcon';
import PulseDot from '@/components/shared/PulseDot';
import FilterButton from '@/components/shared/FilterButton';
import SelectionViewport from '@/components/shared/SelectionViewport';
import SourceNote from '@/components/shared/SourceNote';
import Icon from '@/components/icons';
import { NEWS_HINTS } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { explanationLines } from '@/lib/explainText';
import { fmtDate, fmtDateShort, fmtJstDateTime, fmtJstTime, fmtRelative, fmtTimeHHMMSS } from '@/lib/format';
import { DUR_SECTION, EASE_PAPER } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type {
  EconEvent,
  NewsFeedState,
  NewsHotspotGroup,
  NewsItem,
  NewsSecurityRow,
  NewsStatus,
} from '@/api/types';

type Tab = 'feed' | 'stocks' | 'econ' | 'sources';

/** 値は API に渡す絞り込みキー（後端 `classify.CATEGORY_RULES` の日本語 taxonomy）。
 *  **表示のときだけ `t()` を通す** —— ここで訳した文字列を送ると何も引っかからない。 */
const CATEGORY_FILTERS = ['決算', '業績予想修正', 'M&A・TOB', '自社株買い', '配当', '日銀・金利', '規制・政策'];

export default function News() {
  const [tab, setTab] = useState<Tab>('feed');
  const [hours, setHours] = useState<24 | 72 | 168>(72);
  const [category, setCategory] = useState<string | null>(null);
  const [onlySecurities, setOnlySecurities] = useState(false);

  const feed = usePolling(
    () => newsApi.feed({ hours, category: category ?? undefined, only_securities: onlySecurities }),
    300_000,
    [hours, category, onlySecurities],
  );
  const hotspots = usePolling(() => newsApi.hotspots(hours), 300_000, [hours]);
  const securities = usePolling(() => newsApi.securities(hours), 300_000, [hours]);
  const econ = usePolling(() => newsApi.econCalendar(), 3_600_000);
  const status = usePolling(() => newsApi.status(), 300_000);

  const feedState = remoteState(feed, (d) => d.items.length === 0);
  const [refreshingNews, setRefreshingNews] = useState(false);

  const onRefreshNews = useCallback(() => {
    if (refreshingNews) return;
    setRefreshingNews(true);
    status.refresh({ force: true });
    hotspots.refresh({ force: true });
    if (tab === 'feed') feed.refresh({ force: true });
    if (tab === 'stocks') securities.refresh({ force: true });
    if (tab === 'econ') econ.refresh({ force: true });
    window.setTimeout(() => setRefreshingNews(false), 800);
  }, [econ, feed, hotspots, refreshingNews, securities, status, tab]);

  return (
    <div className="space-y-5">
      <PageHeader
        section="07"
        eyebrow="NEWS & CATALYSTS · JAPAN EQUITIES"
        title={t('新闻')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <>
            <StatusStrip status={status.data ?? null} />
            {status.lastUpdatedAt && (
              <span className="font-mono text-caption text-ink-400 tnum">
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

      <StatusHero status={status.data ?? null} loading={status.loading && !status.data} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented<Tab>
          options={[
            { value: 'feed', label: t('信息流') },
            { value: 'stocks', label: t('个股影响') },
            { value: 'econ', label: t('经济日历') },
            { value: 'sources', label: t('数据源') },
          ]}
          value={tab}
          onChange={setTab}
        />
        {(tab === 'feed' || tab === 'stocks') && (
          <Segmented<'24' | '72' | '168'>
            options={[
              { value: '24', label: '24h' },
              { value: '72', label: '72h' },
              { value: '168', label: '7d' },
            ]}
            value={String(hours) as '24' | '72' | '168'}
            onChange={(value) => setHours(Number(value) as 24 | 72 | 168)}
          />
        )}
      </div>

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
                onToggle={() => setOnlySecurities((v) => !v)}
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
                  <button type="button" onClick={() => feed.refresh({ force: true })} className="btn-primary">
                    {t('重试')}
                  </button>
                }
              />
            </section>
          ) : feedState === 'empty' ? (
            <section className="card-surface">
              <EmptyState image="/empty-news.svg" title={t('暂无数据')} description={feed.data?.note_ja ?? ''} />
            </section>
          ) : (
            <ul className="card-surface divide-y divide-line overflow-hidden">
              {feed.data!.items.map((item, index) => (
                <NewsRow key={item.news_id} item={item} index={index} />
              ))}
            </ul>
          )}
        </>
      )}

      {tab === 'stocks' && <StocksImpactPanel rows={securities.data?.rows ?? []} loading={securities.loading} />}

      {tab === 'econ' && (
        <EconCalendarPanel
          events={econ.data?.events ?? []}
          note={econ.data?.coverage_note_ja}
          loading={econ.loading}
        />
      )}

      {tab === 'sources' && <SourcesPanel status={status.data ?? null} loading={status.loading} />}
    </div>
  );
}

/* ---------------- 状态条 ---------------- */

function StatusStrip({ status }: { status: NewsStatus | null }) {
  if (!status) return null;
  const feedsOk = status.feeds.filter((feed) => !feed.last_error_code && feed.last_fetched_at).length;
  return (
    <span className="flex items-center gap-3 text-caption text-ink-500">
      <span>
        {t('数据源')} {feedsOk}/{status.feeds.length}
      </span>
      <SoftBadge tone={status.ai.enabled ? 'ai' : 'neutral'}>
        {status.ai.enabled ? <PulseDot className="bg-ai-600" size={7} /> : <AnalysisIcon size={13} />}
        AI {status.ai.enabled ? t('已启用') : t('未启用')}
      </SoftBadge>
    </span>
  );
}

function HeroCell({ label, index, children }: { label: string; index: number; children: ReactNode }) {
  return (
    <div
      className={cn(
        'min-w-0 border-line px-4 py-4 sm:px-5',
        index >= 2 && 'border-t xl:border-t-0',
        index % 2 === 1 && 'border-l',
        index === 2 && 'xl:border-l',
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
  const feedsOk = status?.feeds.filter((feed) => !feed.last_error_code && feed.last_fetched_at).length ?? 0;
  const lastFetch = status?.feeds
    .map((feed) => feed.last_fetched_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  const queued = status ? Object.values(status.ai.queue).reduce((sum, value) => sum + value, 0) : 0;
  const sourceTone: 'brand' | 'warn' | 'muted' = !status
    ? 'muted'
    : feedsOk === status.feeds.length && status.feeds.length > 0
      ? 'brand'
      : 'warn';
  return (
    <motion.section
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER }}
      aria-label={t('数据源')}
      className="card-surface"
    >
      <div className="grid grid-cols-2 xl:grid-cols-4">
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
        <HeroCell label="AI" index={1}>
          {loading ? (
            <SkeletonBlock className="h-5 w-28 max-w-full" />
          ) : (
            <SoftBadge tone={status?.ai.enabled ? 'ai' : 'neutral'} size="md">
              {status?.ai.enabled || queued > 0 ? (
                <PulseDot className="bg-ai-600" size={7} />
              ) : (
                <AnalysisIcon size={14} />
              )}
              <span>{status?.ai.enabled ? t('已启用') : t('未启用')}</span>
            </SoftBadge>
          )}
        </HeroCell>
        <HeroCell label={t('分析队列')} index={2}>
          {loading ? (
            <SkeletonBlock className="h-5 w-16" />
          ) : (
            <p className="metric-value text-data-m text-ink-900 tnum">{status ? queued : '—'}</p>
          )}
        </HeroCell>
        <HeroCell label={t('采集窗口')} index={3}>
          {loading ? (
            <SkeletonBlock className="h-5 w-14" />
          ) : (
            <p className="metric-value text-data-m text-ink-900 tnum">
              {status ? `${status.window_hours}h` : '—'}
            </p>
          )}
        </HeroCell>
      </div>
      <details className="group border-t border-line px-4 py-1 sm:px-5">
        <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 text-caption text-ink-500 marker:content-none [&::-webkit-details-marker]:hidden">
          {t('数据与分析说明')}
          <Icon
            name="chevron-down"
            size={14}
            className="shrink-0 transition-transform duration-fast group-open:rotate-180 motion-reduce:transition-none"
          />
        </summary>
        <SourceNote
          className="border-0 pb-3 pt-1"
          text={t('新闻来自已配置的 RSS 源；每条标注原始来源；滞后表示上次采集时间；AI 状态与队列来自本站翻译管线')}
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
        <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">—</span>
      </div>
    );
  }
  const sameDay = JST_DAY.format(new Date(iso)) === JST_DAY.format(new Date());
  return (
    <div className="flex w-11 shrink-0 flex-col items-center pt-0.5">
      <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">
        {sameDay ? fmtJstTime(iso) : fmtDateShort(iso.slice(0, 10))}
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

function AnalysisStateChip({ state }: { state: NewsItem['analysis_state'] }) {
  if (state === 'completed' || !state) return null;
  const map: Record<string, { label: string; tone: 'brand' | 'warn' | 'neutral' }> = {
    pending: { label: t('分析排队中'), tone: 'brand' },
    failed: { label: t('分析失败'), tone: 'warn' },
    disabled: { label: t('AI 未启用'), tone: 'neutral' },
    none: { label: t('未分析'), tone: 'neutral' },
  };
  const item = map[state];
  if (!item) return null;
  return <SoftBadge tone={item.tone}>{item.label}</SoftBadge>;
}

function HotspotStrip({
  groups,
  loading,
  error,
  onRetry,
}: {
  groups: NewsHotspotGroup[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <section aria-label={t('热点主题')}>
      <p className="eyebrow">HOT THEMES</p>
      <h3 className="mb-2 mt-1 text-h3 text-ink-900">{t('热点主题')}</h3>
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
              <button type="button" onClick={onRetry} className="btn-primary">
                {t('重试')}
              </button>
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
  const heat = Math.max(0, Math.min(100, group.max_importance ?? 0));
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.48, ease: EASE_PAPER, delay: Math.min(index * 0.05, 0.4) }}
    >
    <Link
      to={`/stock/${group.display_code}`}
      className="card-surface card-hover flex min-w-[220px] max-w-[260px] shrink-0 flex-col gap-1.5 p-3"
    >
      <span className="flex items-center gap-1.5">
        <CodeMark code={group.display_code} size={22} />
        <span className="font-mono text-caption font-semibold text-brand-700">{group.display_code}</span>
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

function NewsRow({ item, index }: { item: NewsItem; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const title = item.translated_title_ja ?? item.original_title ?? '—';
  const toggle = () => setExpanded((value) => !value);
  return (
    <motion.li
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE_PAPER, delay: Math.min(index * 0.03, 0.3) }}
      className="group relative flex gap-3 px-4 py-[18px] transition-colors duration-fast hover:bg-paper-2/70 sm:px-5"
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        aria-label={title}
        className="absolute inset-0 z-0 focus-visible:bg-paper-2/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400/60"
      />
      <TimeCol iso={item.published_at} />
      <div
        className="relative z-10 min-w-0 flex-1 cursor-pointer"
        onClick={(event) => {
          const target = event.target as Element;
          if (target.closest('button, a, [role="button"], input, select, textarea')) return;
          if (window.getSelection()?.toString()) return;
          toggle();
        }}
      >
        <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-micro text-ink-400">
          <span className="font-medium text-ink-500">{item.source ?? '—'}</span>
          <span aria-hidden="true">·</span>
          <span className="font-mono tnum">{fmtRelative(item.published_at)}</span>
          <span className="ml-auto">
            <ImportanceBadge value={item.importance} />
          </span>
        </p>
        <h3 className="mt-1.5 text-[15px] font-semibold leading-[22px] text-ink-900">
          <span className="bg-[linear-gradient(currentColor,currentColor)] bg-[length:0%_1px] bg-left-bottom bg-no-repeat transition-[background-size,color] duration-200 group-hover:bg-[length:100%_1px] group-hover:text-brand-600">
            {title}
          </span>
        </h3>
        {item.translated_title_ja && item.original_title && item.translated_title_ja !== item.original_title && (
          <p className="mt-0.5 truncate text-caption text-ink-400">{item.original_title}</p>
        )}
        {item.summary_ja && <p className="mt-1 line-clamp-2 text-body-s text-ink-500">{item.summary_ja}</p>}

        {item.analysis_zh && (
          <div className="mt-2 rounded-md bg-ai-50 p-2.5 text-body-s text-ink-800">
            <span className="mr-1.5 rounded-sm bg-ai-600 px-1 py-0.5 text-micro font-bold text-white">{t('中文分析')}</span>
            {item.analysis_zh.headline && <strong className="mr-1">{item.analysis_zh.headline}</strong>}
            {item.analysis_zh.impact}
            {(item.analysis_zh.affected?.length ?? 0) > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {item.analysis_zh.affected!.map((affected) => {
                  const code =
                    affected.code.endsWith('0') && affected.code.length === 5
                      ? affected.code.slice(0, 4)
                      : affected.code;
                  const chip = (
                    <Link to={`/stock/${code}`}>
                      <SoftBadge className="font-mono hover:bg-brand-50 hover:text-brand-700">{code}</SoftBadge>
                    </Link>
                  );
                  return affected.reason_zh ? (
                    <PointerTooltip
                      key={affected.code}
                      passthrough
                      label={affected.reason_zh}
                      content={<span className="text-micro leading-[16px] text-ink-600">{affected.reason_zh}</span>}
                    >
                      {chip}
                    </PointerTooltip>
                  ) : (
                    <span key={affected.code}>{chip}</span>
                  );
                })}
              </div>
            )}
          </div>
        )}

        <div className="mt-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-micro text-ink-400">
          {(item.categories ?? []).slice(0, 3).map((cat) => (
            <SoftBadge key={cat}>{t(cat)}</SoftBadge>
          ))}
          {item.securities.map((security) => (
            <Link key={security.canonical_code} to={`/stock/${security.display_code}`}>
              <SoftBadge tone="brand" className="font-mono hover:underline">
                {security.display_code}
                {security.name_ja ? ` ${security.name_ja}` : ''}
              </SoftBadge>
            </Link>
          ))}
          <AnalysisStateChip state={item.analysis_state} />
          {item.source_url && (
            <a href={item.source_url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">
              {t('原文')}
            </a>
          )}
        </div>

        {expanded && (
          <div className="mt-2 space-y-1.5 border-t border-line pt-2 text-caption text-ink-500">
            {item.original_summary && <p className="text-ink-600">{item.original_summary}</p>}
            {(item.importance_reason_items?.length ?? item.importance_reasons?.length ?? 0) > 0 && (
              <p>
                {t('重要度依据')}:{' '}
                {explanationLines(item.importance_reason_items, item.importance_reasons).join(' · ')}
              </p>
            )}
            <p>
              {t('发布')}: {fmtJstDateTime(item.published_at)} · {t('语言')}: {item.source_language}
              {item.market_relevance === 'market' && <span> · {t('市场级新闻')}</span>}
            </p>
          </div>
        )}
      </div>
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
            <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
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
        render: (row) => <span className="font-mono text-body-s tnum">{row.news_count}</span>,
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
        key: 'ai',
        title: t('AI 分析'),
        align: 'right',
        render: (row) =>
          row.ai ? (
            <span className="font-mono text-caption text-ink-600 tnum">
              {t('已分析')} {row.ai.analyzed}
            </span>
          ) : (
            <span className="text-micro text-ink-300">{t('未分析')}</span>
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

/* ---------------- 经济日历 ---------------- */

function EconCalendarPanel({ events, note, loading }: { events: EconEvent[]; note?: string; loading: boolean }) {
  if (loading && events.length === 0) {
    return (
      <section className="card-surface overflow-hidden">
        <FeedSkeleton rows={8} />
      </section>
    );
  }
  if (events.length === 0) {
    return (
      <section className="card-surface">
        <EmptyState image="/empty-news.svg" title={t('暂无数据')} />
      </section>
    );
  }
  const grouped = new Map<string, EconEvent[]>();
  for (const event of events) {
    const list = grouped.get(event.date) ?? [];
    list.push(event);
    grouped.set(event.date, list);
  }
  return (
    <div className="space-y-3">
      {note && <p className="text-caption text-ink-400">{note}</p>}
      {Array.from(grouped.entries()).map(([date, dayEvents]) => (
        <section key={date} className="card-surface overflow-hidden">
          <div className="flex items-baseline gap-2 border-b border-line px-4 py-3 sm:px-5">
            <p className="eyebrow">ECON · JST</p>
            <h3 className="flex items-baseline gap-2">
              <span className="font-mono text-body font-semibold tnum text-ink-900">{fmtDate(date)}</span>
              <span className="text-micro text-ink-400">{weekdayJa(date)}</span>
            </h3>
          </div>
          <ul>
            {dayEvents.map((event, index) => (
              <li
                key={index}
                className="group relative flex min-h-[60px] gap-3 px-4 py-[18px] transition-colors duration-fast hover:bg-paper-2/70 sm:px-5"
              >
                <TimeColClock time={event.time_jst} />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-micro text-ink-400">
                    <EconImportanceDot importance={event.importance} />
                    <span className="font-medium text-ink-500">{event.organizer}</span>
                    <SoftBadge>{t(event.category)}</SoftBadge>
                    {!event.confirmed && (
                      event.note ? (
                        <PointerTooltip
                          passthrough
                          label={event.note}
                          content={<span className="text-micro leading-[16px] text-ink-600">{event.note}</span>}
                        >
                          <SoftBadge tone="warn">{t('目安')}</SoftBadge>
                        </PointerTooltip>
                      ) : (
                        <SoftBadge tone="warn">{t('目安')}</SoftBadge>
                      )
                    )}
                    {event.source_url && (
                      <a href={event.source_url} target="_blank" rel="noreferrer" className="ml-auto text-brand-700 hover:underline">
                        {t('出处')}
                      </a>
                    )}
                  </p>
                  <h3 className="mt-1.5 text-[15px] font-semibold leading-[22px] text-ink-900">
                    <span className="bg-[linear-gradient(currentColor,currentColor)] bg-[length:0%_1px] bg-left-bottom bg-no-repeat transition-[background-size,color] duration-200 group-hover:bg-[length:100%_1px] group-hover:text-brand-600">
                      {event.name_ja}
                    </span>
                  </h3>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function TimeColClock({ time }: { time: string }) {
  return (
    <div className="flex w-11 shrink-0 flex-col items-center pt-0.5">
      <span className="font-mono text-[11px] leading-[14px] text-ink-400 tnum">{time || '—'}</span>
      <span className="mt-1.5 hidden w-[2px] flex-1 rounded-full bg-line sm:block" aria-hidden="true" />
    </div>
  );
}

function EconImportanceDot({ importance }: { importance: string }) {
  const tone = importance === 'high' ? 'bg-warn-600' : importance === 'medium' ? 'bg-brand-500' : 'bg-ink-300';
  const label = importance === 'high' ? t('高') : importance === 'medium' ? t('中') : t('低');
  return (
    <span className="flex w-8 shrink-0 items-center gap-1">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden />
      <span className="text-micro text-ink-400">{label}</span>
    </span>
  );
}

function weekdayJa(isoDate: string): string {
  // 正午 JST = 03:00 UTC 同日 → getUTCDay がそのまま JST の曜日。閲覧者 TZ 非依存。
  const parsed = new Date(`${isoDate}T12:00:00+09:00`);
  if (Number.isNaN(parsed.getTime())) return '';
  const days = ['日', '月', '火', '水', '木', '金', '土'];
  return `(${days[parsed.getUTCDay()]})`;
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
  if (loading && !status) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <SkeletonCard key={index} />
        ))}
      </div>
    );
  }
  if (!status) {
    return (
      <section className="card-surface">
        <EmptyState image="/empty-news.svg" title={t('暂无数据')} />
      </section>
    );
  }
  return (
    <div className="space-y-4">
      <motion.div
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.05 } } }}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
      >
        {status.feeds.map((feed) => {
          const health = feedHealth(feed);
          return (
            <motion.section
              key={feed.feed_url}
              variants={{
                hidden: { opacity: 0, y: 14 },
                show: { opacity: 1, y: 0, transition: { duration: 0.48, ease: EASE_PAPER } },
              }}
              className="card-surface p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="eyebrow">RSS</p>
                  <h3 className="mt-1 truncate text-h3 text-ink-900">{feedHost(feed.feed_url)}</h3>
                  <p className="mt-0.5 truncate font-mono text-micro text-ink-400">{feed.feed_url}</p>
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
                  <p className="font-mono text-data-l text-ink-900 tnum">
                    {feed.last_fetched_at ? fmtRelative(feed.last_fetched_at) : '—'}
                  </p>
                  <p className="mt-0.5 text-micro text-ink-400">{t('最近取得')}</p>
                </div>
              </div>
              {feed.last_error_code && (
                <p className="mt-3 border-t border-line pt-2.5 font-mono text-micro text-down-700">{feed.last_error_code}</p>
              )}
            </motion.section>
          );
        })}
        <motion.section
          variants={{
            hidden: { opacity: 0, y: 14 },
            show: { opacity: 1, y: 0, transition: { duration: 0.48, ease: EASE_PAPER } },
          }}
          className="card-surface p-5"
        >
          <p className="eyebrow">AI PIPELINE</p>
          <h3 className="mb-2 mt-1 flex items-center gap-1.5 text-h3 text-ink-900">
            <AnalysisIcon size={16} className="text-ai-600" />
            AI {t('管道')}
          </h3>
          <dl className="space-y-1.5 text-body-s">
            <div className="flex justify-between">
              <dt className="text-ink-500">{t('状态')}</dt>
              <dd className={status.ai.enabled ? 'text-ai-600' : 'text-ink-400'}>
                {status.ai.enabled ? t('已启用') : t('未启用')}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-500">{t('翻译目标语言')}</dt>
              <dd className="font-mono text-ink-800">{status.ai.translation_target}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-500">{t('分析语言')}</dt>
              <dd className="font-mono text-ink-800">{status.ai.analysis_language}</dd>
            </div>
            {Object.keys(status.ai.queue).length > 0 && (
              <div className="flex justify-between">
                <dt className="text-ink-500">{t('任务队列')}</dt>
                <dd className="font-mono text-caption tnum text-ink-700">
                  {Object.entries(status.ai.queue).map(([key, count]) => `${key}:${count}`).join(' ')}
                </dd>
              </div>
            )}
          </dl>
          {status.ai.note_ja && <p className="mt-2 rounded-md bg-paper-2 p-2 text-caption text-ink-500">{status.ai.note_ja}</p>}
        </motion.section>
      </motion.div>
      <p className="text-micro text-ink-400">
        {t('实体目录')}: {status.entity_aliases.toLocaleString('ja-JP')} · {t('同步间隔')}: {status.sync_seconds}s
      </p>
    </div>
  );
}
