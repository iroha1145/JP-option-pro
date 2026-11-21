/** 突破雷达 —— 版式照美国站「突破雷达」：页头与范围切换 → 状态带 → 数据覆盖 → 筛选面板
 *  → 排序说明 → 当日信号（首要大卡 8 栏 + 历史事件 4 栏）→ 其余信号小卡（同股合并、分批显示）。
 *  数据仍为收盘后日线扫描；盘中价只来自延迟报价叠加层。 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { quotesApi, radarApi, watchlistApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { useTickFlash } from '@/hooks/useTickFlash';
import TickPrice from '@/components/shared/TickPrice';
import Icon from '@/components/icons';
import { cn } from '@/lib/utils';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import FilterButton from '@/components/shared/FilterButton';
import MenuSelect from '@/components/shared/MenuSelect';
import PointerTooltip from '@/components/shared/PointerTooltip';
import SelectionViewport from '@/components/shared/SelectionViewport';
import { SkeletonCard } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough, SignalChip, StateChip } from '@/components/domain';
import HistoryRail from '@/components/radar/HistoryRail';
import LeadBigCard from '@/components/radar/LeadBigCard';
import SignalCards from '@/components/radar/SignalCards';
import { groupSignalsByStock } from '@/components/radar/groupSignals';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import StaleStrip from '@/components/shared/StaleStrip';
import SourceNote from '@/components/shared/SourceNote';
import { t } from '@/i18n/core';
import { fmtDate, fmtPrice, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import type { RadarEvent } from '@/api/types';
import '@/components/radar.css';

type StateGroup = 'active' | 'confirmed' | 'watching' | 'closed' | 'all';
type ViewMode = 'cards' | 'table';

const SCORE_CAPS = [
  { value: 0, label: t('不限') },
  { value: 65, label: t('65 分以上') },
  { value: 80, label: t('80 分以上') },
];

const GROUP_OPTIONS: { value: StateGroup; label: string }[] = [
  { value: 'active', label: t('已触发') },
  { value: 'confirmed', label: t('已确认') },
  { value: 'watching', label: t('观察中') },
  { value: 'closed', label: t('已失效') },
  { value: 'all', label: t('全部') },
];

const WATCH_SCOPE_OPTIONS = [
  { value: 'all', label: t('全部') },
  { value: 'watchlist', label: t('只看关注') },
];

const GROUP_STATES: Record<StateGroup, string | undefined> = {
  all: undefined,
  active: 'triggered,confirmed,holding,retesting,retest_held,reaccelerating,extended',
  confirmed: 'confirmed,holding,retest_held,reaccelerating',
  watching: 'discovered,watching',
  closed: 'failed,expired',
};

/** 接口单次最多返回的事件数；达到上限时如实标注，不把它当全量。 */
const FETCH_LIMIT = 200;

export default function Radar() {
  const { canRefreshPublicData, canManageWatchlist, principalKey } = useAccess();
  const toast = useToast();
  const [group, setGroup] = useState<StateGroup>('active');
  const [view, setView] = useState<ViewMode>('cards');
  const [leadId, setLeadId] = useState<string | null>(null);
  const [locateId, setLocateId] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const locateTimer = useRef<number | null>(null);

  const promoteLead = (id: string) => {
    setLeadId(id);
    setLocateId(id);
    if (locateTimer.current) window.clearTimeout(locateTimer.current);
    locateTimer.current = window.setTimeout(() => setLocateId(null), 2000);
  };

  useEffect(
    () => () => {
      if (locateTimer.current) window.clearTimeout(locateTimer.current);
    },
    [],
  );

  const query = usePolling(
    () => radarApi.current(GROUP_STATES[group] ? { states: GROUP_STATES[group], limit: FETCH_LIMIT } : { limit: FETCH_LIMIT }),
    120_000,
    [group],
    { identity: group },
  );
  const state = remoteState(query, (d) => d.events.length === 0);

  /* 夜間断面に遅延気配を重ねる（再スキャンではない）。答えたい問いは
     「昨夜の候補のうち、今ピボットを超えているのはどれか」。 */
  const overlay = usePolling(() => quotesApi.overlay('radar', 200), 60_000, []);
  const overlayRows = useMemo(() => overlay.data?.enabled ? overlay.data.rows : {}, [overlay.data]);
  const [onlyAbovePivot, setOnlyAbovePivot] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [onlyWatch, setOnlyWatch] = useState(false);
  const watchQ = usePolling(
    () => canManageWatchlist ? watchlistApi.list() : Promise.resolve<Awaited<ReturnType<typeof watchlistApi.list>>>({ items: [] }),
    120_000, [canManageWatchlist], { identity: principalKey },
  );
  const watchCodes = useMemo(
    () => new Set((watchQ.data?.items ?? []).map((item) => item.canonical_code)),
    [watchQ.data],
  );
  const watchFailed = Boolean(watchQ.error && !watchQ.data);
  const watchFilterPending = onlyWatch && ((watchQ.loading && !watchQ.data) || watchFailed);

  const events = useMemo(() => {
    const all = query.data?.events ?? [];
    return all.filter((event) => {
      if (minScore > 0 && (event.alert_priority ?? -1) < minScore) return false;
      if (onlyAbovePivot && !overlayRows[event.event_id]?.above_pivot) return false;
      if (onlyWatch && !watchFilterPending && !watchCodes.has(event.canonical_code)) return false;
      return true;
    });
  }, [query.data, onlyAbovePivot, overlayRows, minScore, onlyWatch, watchFilterPending, watchCodes]);
  const flashRows = useMemo(
    () =>
      events.map((event) => ({
        id: event.event_id,
        price: overlayRows[event.event_id]?.live_price ?? (event.snapshot.close as number | null),
      })),
    [events, overlayRows],
  );
  const flashes = useTickFlash(flashRows, (row) => row.id, (row) => row.price);

  // Lead = 明示選択 or 優先度トップ。フィルタ変更で選択が消えたら先頭へ戻す。
  const lead = useMemo(() => {
    if (leadId) {
      const picked = events.find((event) => event.event_id === leadId);
      if (picked) return picked;
    }
    return events[0] ?? null;
  }, [events, leadId]);

  useEffect(() => {
    setLeadId(null);
  }, [group, minScore, onlyWatch]);

  /* 首要卡那只股票的其他信号挂在首要卡上；其余股票按股票合并成小卡。 */
  const leadSiblings = useMemo(
    () => (lead ? events.filter((event) => event.canonical_code === lead.canonical_code && event.event_id !== lead.event_id) : []),
    [events, lead],
  );
  const restGroups = useMemo(
    () => groupSignalsByStock(events.filter((event) => event.canonical_code !== lead?.canonical_code)),
    [events, lead],
  );
  const restSignalCount = useMemo(
    () => restGroups.reduce((sum, item) => sum + 1 + item.others.length, 0),
    [restGroups],
  );
  const stockCount = useMemo(() => new Set(events.map((event) => event.canonical_code)).size, [events]);
  const remoteCount = query.data?.events.length ?? 0;
  const filteredEmpty =
    (state === 'ready' || state === 'stale') && remoteCount > 0 && events.length === 0;
  const clearLocalFilters = () => {
    setMinScore(0);
    setOnlyAbovePivot(false);
    setOnlyWatch(false);
  };
  const filterKey = `${group}:${onlyAbovePivot}:${minScore}`;
  const cardsKey = `${filterKey}:${onlyWatch}:${watchFilterPending}`;

  /* 「更多筛选」折叠时的一行摘要：写明当前生效的全部条件。 */
  const filterSummary: [string, string][] = [
    [t('查看范围'), onlyWatch ? t('只看关注') : t('全部')],
    [t('状态'), GROUP_OPTIONS.find((option) => option.value === group)?.label ?? ''],
    [t('评分'), SCORE_CAPS.find((cap) => cap.value === minScore)?.label ?? ''],
    ...(onlyAbovePivot ? [[t('盘中站上枢轴'), t('已启用')] as [string, string]] : []),
  ];

  const historyRail = (
    <HistoryRail events={events} filterKey={filterKey} onPromoteLead={promoteLead} />
  );
  const overlayOn = Boolean(overlay.data?.enabled);

  return (
    <div className="page-stack">
      <PageHeader
        section="screener"
        title={t('突破雷达')}
        meta={
          <>
            <Segmented
              options={WATCH_SCOPE_OPTIONS}
              value={onlyWatch ? 'watchlist' : 'all'}
              onChange={(value) => setOnlyWatch(value === 'watchlist')}
              ariaLabel={t('查看范围')}
              className="max-w-full flex-wrap"
            />
            {watchFilterPending && (
              <span className="text-caption text-ink-400">
                {watchFailed ? t('关注读取失败 · 暂显示全部') : t('关注加载中 · 暂显示全部')}
              </span>
            )}
          </>
        }
      />

      {/* 状态带：日本站只有收盘后扫描，没有扫描服务与下次扫描；只写接口真有的信息。 */}
      <div className="radar-status paper-panel grid min-w-0 grid-cols-2 gap-4 p-4 sm:gap-6 sm:p-6 xl:grid-cols-4">
        <div className="col-span-2 min-w-0 space-y-3 xl:col-span-1">
          <span className="inline-flex items-center gap-2 text-body-s text-ink-700">
            <span className={cn('size-2 shrink-0 rounded-full', query.data ? 'bg-ok-600' : 'bg-ink-300')} aria-hidden="true" />
            {t('收盘后扫描日线，追踪价格突破与形态变化')}
          </span>
        </div>
        <dl className="min-w-0 space-y-2 text-caption">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <dt className="text-ink-400">{t('数据截至')}</dt>
            <dd className="tnum text-ink-700">{fmtDate(query.data?.scan_date)}</dd>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <dt className="text-ink-400">{t('更新')}</dt>
            <dd className="tnum text-ink-700">{query.lastUpdatedAt ? fmtTimeHHMMSS(query.lastUpdatedAt) : '—'}</dd>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <dt className="text-ink-400">{t('活跃信号')}</dt>
            <dd className="tnum text-ink-700">
              {query.data ? remoteCount : '—'}
              {remoteCount >= FETCH_LIMIT && <span className="ml-1 text-ink-400">{t('（单次最多 {n} 条）', { n: FETCH_LIMIT })}</span>}
            </dd>
          </div>
        </dl>
        <dl className="min-w-0 space-y-2 text-caption">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <dt className="text-ink-400">{t('盘中报价')}</dt>
            <dd className="text-ink-700">
              {!overlay.data ? '—' : overlayOn
                ? t('延迟约 {n} 分钟', { n: overlay.data.delayed_minutes ?? 15 })
                : t('未叠加')}
            </dd>
          </div>
        </dl>
        <dl className="min-w-0 space-y-2 text-caption">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <dt className="text-ink-400">{t('涉及股票')}</dt>
            <dd className="tnum text-ink-700">{query.data ? t('{n} 只', { n: new Set(query.data.events.map((event) => event.canonical_code)).size }) : '—'}</dd>
          </div>
        </dl>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-500">
        <DataThrough date={query.data?.scan_date} className="min-w-0 max-w-full [&_[data-soft-badge]]:whitespace-normal" />
        {overlayOn && overlay.data?.source_detail && (
          <span className="text-ink-400">{t('盘中报价')} {overlay.data.source_detail}</span>
        )}
      </div>

      {/* 状态收成一个下拉；评分门槛收进「更多筛选」，折叠时一行摘要写明全部条件。 */}
      <div className="radar-filterbar paper-panel flex min-w-0 flex-wrap items-center gap-x-5 gap-y-4 p-5 sm:p-6">
        <div className="flex max-w-full flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-caption text-ink-500">
            <Icon name="filter-funnel" size={13} />
            {t('状态')}
          </span>
          <MenuSelect<StateGroup> ariaLabel={t('状态')} value={group} onChange={setGroup} options={GROUP_OPTIONS} />
        </div>
        {overlayOn && (
          <PointerTooltip
            passthrough
            label={t('用延迟{n}分的盘中价与夜间枢轴比较', { n: overlay.data?.delayed_minutes ?? 15 })}
            width={240}
            contentClassName="p-2.5"
            content={
              <span className="text-micro text-ink-600">
                {t('用延迟{n}分的盘中价与夜间枢轴比较', { n: overlay.data?.delayed_minutes ?? 15 })}
              </span>
            }
          >
            <button
              type="button"
              onClick={() => setOnlyAbovePivot((v) => !v)}
              aria-pressed={onlyAbovePivot}
              className="control-button mobile-control-target"
            >
              <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
              {t('盘中站上枢轴')}
              <span className="tnum">{overlay.data?.above_pivot_count ?? 0}</span>
            </button>
          </PointerTooltip>
        )}
        <span className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Segmented<ViewMode>
            options={[
              { value: 'cards', label: t('卡片') },
              { value: 'table', label: t('列表') },
            ]}
            value={view}
            onChange={setView}
          />
          {query.lastUpdatedAt && (
            <span className="tnum text-micro text-ink-400">{t('更新')} {fmtTimeHHMMSS(query.lastUpdatedAt)}</span>
          )}
          {canRefreshPublicData && (
            <ForceRefreshButton
              onClick={async () => {
                if (rescanning) return;
                setRescanning(true);
                try {
                  await workerApi.trigger('radar_refresh');
                  toast.success(t('重算雷达'), t('已提交'));
                  query.refresh({ force: true });
                } catch (error) {
                  toast.error(t('重算雷达'), String((error as Error).message ?? error));
                } finally {
                  setRescanning(false);
                }
              }}
              spinning={rescanning}
              label={t('重算雷达')}
              title={t('重算雷达')}
            />
          )}
        </span>
        <details className="group/more basis-full border-t border-line/70 pt-3">
          <summary className="disclosure-trigger flex min-h-11 cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 rounded-lg py-1 text-caption text-ink-500 outline-none transition-colors duration-fast hover:text-ink-800 focus-visible:ring-2 focus-visible:ring-brand-600 [&::-webkit-details-marker]:hidden">
            <span className="inline-flex shrink-0 items-center gap-2 text-ink-700">
              {t('更多筛选')}
              <Icon name="chevron-down" size={13} className="text-ink-400 transition-transform group-open/more:rotate-180" />
            </span>
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-micro">
              {filterSummary.map(([name, value]) => (
                <span key={name}>
                  <span className="text-ink-400">{name}</span> <span className="text-ink-700">{value}</span>
                </span>
              ))}
            </span>
          </summary>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3 pt-3">
            <div className="flex max-w-full flex-wrap items-center gap-2">
              <span className="text-caption text-ink-500">{t('评分')}</span>
              <SelectionViewport>
                <div className="filter-group flex-wrap" role="group" aria-label={t('评分')}>
                  {SCORE_CAPS.map((cap) => (
                    <FilterButton
                      key={cap.value}
                      active={minScore === cap.value}
                      onClick={() => setMinScore(cap.value)}
                      aria-label={t('评分{label}', { label: cap.label })}
                    >
                      {cap.label}
                    </FilterButton>
                  ))}
                </div>
              </SelectionViewport>
            </div>
          </div>
        </details>
      </div>
      <p className="min-w-0 text-caption text-ink-500">
        {t('按告警优先级从高到低排列；同一只股票的多条信号合并为一张卡。')}
      </p>

      <section className="min-w-0" aria-label={t('当日信号')}>
        <div className="radar-section-heading mb-5 flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-h2 text-ink-900">{t('当日信号')}</h2>
          <p className="tnum text-caption text-ink-400">
            {t('{n} 个活跃', { n: events.length })}
            {events.length > 0 ? ` · ${t('{n} 只', { n: stockCount })}` : ''}
            {onlyWatch && !watchFilterPending ? t(' · 只看关注') : ''}
          </p>
        </div>

      {state === 'loading' ? (
        <>
          <div className="page-grid items-start">
            <SkeletonCard className="h-[460px] lg:col-span-8" />
            <SkeletonCard className="h-[560px] lg:col-span-4" />
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <SkeletonCard className="h-[280px]" />
            <SkeletonCard className="h-[280px]" />
            <SkeletonCard className="h-[280px]" />
          </div>
        </>
      ) : state === 'error' ? (
        <div className="page-grid items-start">
          <div className="card-surface min-w-0 lg:col-span-8">
            <EmptyState
              variant="error"
              image="/empty-radar.svg"
              title={t('加载失败')}
              description={String(query.error?.message ?? '')}
              action={<EmptyRetryButton onClick={() => query.refresh({ force: true })} refreshing={query.refreshing} />}
            />
          </div>
          <div className="min-w-0 lg:col-span-4"><HistoryRail events={[]} filterKey={filterKey} onPromoteLead={promoteLead} /></div>
        </div>
      ) : state === 'empty' ? (
        <div className="page-grid items-start">
          <div className="card-surface min-w-0 lg:col-span-8">
            <EmptyState
              image="/empty-radar.svg"
              title={t('雷达仍在盯')}
              description={query.data?.note ?? t('新信号出现时会立刻出现在这里。')}
            />
          </div>
          <div className="min-w-0 lg:col-span-4">{historyRail}</div>
        </div>
      ) : (
        <div className="space-y-6">
          {state === 'stale' && (
            <StaleStrip onRetry={() => query.refresh()} refreshing={query.refreshing} />
          )}
          {filteredEmpty && (
            <div className="card-surface" data-testid="radar-filter-empty">
              <EmptyState
                image="/empty-radar.svg"
                title={t('当前条件无命中')}
                description={t('尝试放宽条件，或移除部分过滤器')}
                action={
                  <EmptyRetryButton
                    onClick={clearLocalFilters}
                    label={t('清除过滤')}
                  />
                }
              />
            </div>
          )}
          {lead && (
            <div className="page-grid items-start">
              <div className="min-w-0 lg:col-span-8">
                <LeadBigCard
                  key={lead.event_id}
                  event={lead}
                  siblings={leadSiblings}
                  live={overlayRows[lead.event_id]}
                  flash={flashes[lead.event_id]}
                  locate={locateId === lead.event_id}
                  onPromote={promoteLead}
                />
              </div>
              <div className="min-w-0 lg:col-span-4">
                <div className="self-start lg:sticky lg:top-20">{historyRail}</div>
              </div>
            </div>
          )}
          {!filteredEmpty && view === 'cards' ? (
            restGroups.length > 0 && (
              <div>
                <div className="radar-section-heading mb-3 flex flex-wrap items-baseline justify-between gap-2 pb-2">
                  <p className="text-body-s font-medium text-ink-800">
                    {t('其余信号')} · <span className="tnum">{t('{stocks} 只股票 · {signals} 条信号', { stocks: restGroups.length, signals: restSignalCount })}</span>
                  </p>
                  <p className="text-micro text-ink-400">{t('点击小卡设为首要信号 · 点击代码打开个股页')}</p>
                </div>
                <SignalCards
                  key={cardsKey}
                  groups={restGroups}
                  overlay={overlayRows}
                  flashes={flashes}
                  onPromote={promoteLead}
                />
              </div>
            )
          ) : !filteredEmpty ? (
            <RadarTable
              events={events}
              flashes={flashes}
              overlay={overlayRows}
              onSelect={(event) => promoteLead(event.event_id)}
            />
          ) : null}
        </div>
      )}
      </section>
      <SourceNote text={t('突破扫描结果 · 日线收盘后更新')} />
    </div>
  );
}

/* ---------------- 列表視圖 ---------------- */

function RadarTable({
  events,
  onSelect,
  flashes,
  overlay,
}: {
  events: RadarEvent[];
  onSelect: (event: RadarEvent) => void;
  flashes: Record<string, 'up' | 'down'>;
  overlay: Record<string, { live_price: number }>;
}) {
  const columns = useMemo<Column<RadarEvent>[]>(
    () => [
      {
        key: 'code', title: t('代码'), width: '28%',
        render: (row) => <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />,
      },
      { key: 'signal', title: t('信号'), render: (row) => <SignalChip signal={row.signal_type} /> },
      { key: 'state', title: t('状态'), render: (row) => <StateChip state={row.state} /> },
      {
        key: 'pivot', title: t('枢轴价'), align: 'right',
        render: (row) => <span className="tnum text-body-s">{fmtPrice(row.pivot_price)}</span>,
      },
      {
        key: 'close', title: t('收盘'), align: 'right',
        render: (row) => (
          <TickPrice flash={flashes[row.event_id]} className="tnum text-body-s text-ink-900">
            {fmtPrice(overlay[row.event_id]?.live_price ?? (row.snapshot.close as number | null))}
          </TickPrice>
        ),
      },
      {
        key: 'turnover', title: t('成交额'), align: 'right', sortable: true,
        sortValue: (row) => (row.snapshot.turnover_today as number | null) ?? -1,
        render: (row) => (
          <span className="tnum text-body-s text-ink-600">
            {fmtYenCompact(row.snapshot.turnover_today as number | null)}
          </span>
        ),
      },
      {
        key: 'discovered', title: t('发现日'), align: 'right', sortable: true,
        sortValue: (row) => row.discovered_date,
        render: (row) => <span className="text-caption text-ink-500">{fmtDate(row.discovered_date)}</span>,
      },
      {
        key: 'priority', title: t('优先级'), align: 'right', sortable: true,
        sortValue: (row) => row.alert_priority ?? -1,
        render: (row) => (
          <span className="tnum text-data-m text-ink-900">
            {row.alert_priority !== null ? Math.round(row.alert_priority) : '—'}
          </span>
        ),
      },
    ],
    [flashes, overlay],
  );
  return (
    <DataTable
      columns={columns}
      rows={events}
      rowKey={(row) => row.event_id}
      rowHeight={44}
      defaultSort={{ key: 'priority', desc: true }}
      onRowClick={onSelect}
    />
  );
}
