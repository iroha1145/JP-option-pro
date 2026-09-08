/** 突破雷达 — 美版布局移植：Lead 大卡（K线+枢轴带）→ 信号卡片流 → 生命周期。
 *  数据仍为收盘后日线扫描，Lead 卡的 K 线按需拉取单只标的。 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { quotesApi, radarApi, stocksApi, watchlistApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { useTickFlash } from '@/hooks/useTickFlash';
import { useColorMode } from '@/hooks/useColorMode';
import TickPrice from '@/components/shared/TickPrice';
import PointerTooltip from '@/components/shared/PointerTooltip';
import PriorityRing from '@/components/shared/PriorityRing';
import Icon from '@/components/icons';
import { cn } from '@/lib/utils';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import FilterButton from '@/components/shared/FilterButton';
import SelectionViewport from '@/components/shared/SelectionViewport';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { CodeCell, DataThrough, RADAR_STATE_LABELS, ScoreBar, SignalChip, StateChip } from '@/components/domain';
import StrengthBar from '@/components/shared/StrengthBar';
import HistoryRail from '@/components/radar/HistoryRail';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import PriceScale from '@/components/radar/PriceScale';
import ScoreBarsMini from '@/components/radar/ScoreBarsMini';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import StaleStrip from '@/components/shared/StaleStrip';
import SoftBadge from '@/components/shared/SoftBadge';
import SourceNote from '@/components/shared/SourceNote';
import { RADAR_SCORE_HINTS } from '@/lib/indicatorHints';
import { DUR_SECTION, EASE_PAPER } from '@/lib/motion';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import type { RadarEvent, StockBar } from '@/api/types';
import '@/components/radar.css';

type StateGroup = 'active' | 'confirmed' | 'watching' | 'closed' | 'all';
type ViewMode = 'cards' | 'table';

const SCORE_CAPS = [
  { value: 0, label: t('不限') },
  { value: 65, label: t('65 分以上') },
  { value: 80, label: t('80 分以上') },
];

const GROUP_STATES: Record<StateGroup, string | undefined> = {
  all: undefined,
  active: 'triggered,confirmed,holding,retesting,retest_held,reaccelerating,extended',
  confirmed: 'confirmed,holding,retest_held,reaccelerating',
  watching: 'discovered,watching',
  closed: 'failed,expired',
};

export default function Radar() {
  const { isOwner } = useAccess();
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
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  useEffect(
    () => () => {
      if (locateTimer.current) window.clearTimeout(locateTimer.current);
    },
    [],
  );

  const query = usePolling(
    () => radarApi.current(GROUP_STATES[group] ? { states: GROUP_STATES[group], limit: 200 } : { limit: 200 }),
    120_000,
    [group],
  );
  const state = remoteState(query, (d) => d.events.length === 0);

  /* 夜間断面に遅延気配を重ねる（再スキャンではない）。答えたい問いは
     「昨夜の候補のうち、今ピボットを超えているのはどれか」。 */
  const overlay = usePolling(() => quotesApi.overlay('radar', 200), 60_000, []);
  const overlayRows = overlay.data?.enabled ? overlay.data.rows : {};
  const [onlyAbovePivot, setOnlyAbovePivot] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [onlyWatch, setOnlyWatch] = useState(false);
  const watchQ = usePolling(() => watchlistApi.list(), 120_000);
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

  const restEvents = useMemo(
    () => events.filter((event) => event.event_id !== lead?.event_id),
    [events, lead],
  );

  return (
    <div>
      <PageHeader
        section="04"
        eyebrow="BREAKOUT RADAR · POST-CLOSE SCAN"
        title={t('突破雷达')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <div className="flex items-center gap-3">
            <DataThrough date={query.data?.scan_date} />
            {query.lastUpdatedAt && (
              <span className="font-mono text-caption text-ink-400 tnum">
                {t('更新')} {fmtTimeHHMMSS(query.lastUpdatedAt)}
              </span>
            )}
            {isOwner && (
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
          </div>
        }
      />

      <div className="radar-filterbar mt-4 flex flex-wrap items-center gap-x-5 gap-y-3 pb-4">
        <Segmented<StateGroup>
          options={[
            { value: 'active', label: t('已触发') },
            { value: 'confirmed', label: t('已确认') },
            { value: 'watching', label: t('观察中') },
            { value: 'closed', label: t('已失效') },
            { value: 'all', label: t('全部') },
          ]}
          value={group}
          onChange={setGroup}
        />
        <div className="flex max-w-full flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-caption text-ink-500">
            <Icon name="filter-funnel" size={13} />
            {t('评分')}
          </span>
          <SelectionViewport>
            <div className="filter-group" role="group" aria-label={t('评分')}>
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
        {overlay.data?.enabled && (
          <PointerTooltip
            passthrough
            label={t('用延迟{n}分的盘中价与夜间枢轴比较', { n: overlay.data?.delayed_minutes ?? 15 })}
            width={240}
            contentClassName="p-2.5"
            content={
              <span className="text-micro leading-[16px] text-ink-600">
                {t('用延迟{n}分的盘中价与夜间枢轴比较', { n: overlay.data?.delayed_minutes ?? 15 })}
              </span>
            }
          >
            <button
              type="button"
              onClick={() => setOnlyAbovePivot((v) => !v)}
              className={cn(
                'flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-caption transition-colors',
                onlyAbovePivot
                  ? 'border-up-600/40 bg-up-50 text-up-700'
                  : 'border-line bg-card text-ink-600 hover:border-brand-400',
              )}
            >
              <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
              {t('盘中站上枢轴')}
              <span className="font-mono tnum">{overlay.data?.above_pivot_count ?? 0}</span>
            </button>
          </PointerTooltip>
        )}
        <span className="flex max-w-full flex-wrap items-center gap-1.5 sm:ml-auto">
          <Segmented
            options={[
              { value: 'all', label: t('全部') },
              { value: 'watchlist', label: t('只看自选') },
            ]}
            value={onlyWatch ? 'watchlist' : 'all'}
            onChange={(value) => setOnlyWatch(value === 'watchlist')}
            ariaLabel={t('查看范围')}
            className="max-w-full"
          />
          {watchFilterPending && (
            <span className="text-micro text-ink-400">
              {watchFailed ? t('自选读取失败 · 暂显示全部') : t('自选加载中 · 暂显示全部')}
            </span>
          )}
          <Segmented<ViewMode>
            options={[
              { value: 'cards', label: t('卡片') },
              { value: 'table', label: t('列表') },
            ]}
            value={view}
            onChange={setView}
          />
        </span>
      </div>

      <section className="mt-8" aria-label={t('当日信号')}>
        <div className="radar-section-heading mb-4 flex flex-wrap items-end justify-between gap-2 pb-1">
          <div>
            <p className="eyebrow">TODAY&apos;S SIGNALS</p>
            <h2 className="mt-1 text-h2 text-ink-900">{t('当日信号')}</h2>
          </div>
          <div className="text-right">
            <p className="font-mono text-caption text-ink-400 tnum">
              {t('{n} 个活跃', { n: events.length })}
              {onlyWatch && !watchFilterPending ? t(' · 只看自选') : ''}
            </p>
            {query.lastUpdatedAt && (
              <span className="font-mono text-micro text-ink-400 tnum">
                {t('更新')} {fmtTimeHHMMSS(query.lastUpdatedAt)}
              </span>
            )}
          </div>
        </div>

      {state === 'loading' ? (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(260px,5fr)]">
            <SkeletonCard className="h-[380px]" />
            <SkeletonCard className="h-[420px]" />
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <SkeletonCard className="h-[220px]" />
            <SkeletonCard className="h-[220px]" />
            <SkeletonCard className="h-[220px]" />
          </div>
        </>
      ) : state === 'error' ? (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(260px,5fr)]">
          <div className="card-surface">
            <EmptyState
              variant="error"
              image="/empty-radar.svg"
              title={t('加载失败')}
              description={String(query.error?.message ?? '')}
              action={<EmptyRetryButton onClick={() => query.refresh({ force: true })} refreshing={query.refreshing} />}
            />
          </div>
          <HistoryRail events={[]} filterKey={`${group}:${onlyAbovePivot}:${minScore}`} onPromoteLead={promoteLead} />
        </div>
      ) : state === 'empty' ? (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(260px,5fr)]">
          <div className="card-surface">
            <EmptyState
              image="/empty-radar.svg"
              title={t('雷达仍在盯')}
              description={query.data?.note ?? t('新信号出现时会立刻出现在这里。')}
            />
          </div>
          <HistoryRail events={events} filterKey={`${group}:${onlyAbovePivot}:${minScore}`} onPromoteLead={promoteLead} />
        </div>
      ) : (
        <>
          {state === 'stale' && (
            <StaleStrip onRetry={() => query.refresh()} refreshing={query.refreshing} />
          )}
          {lead && (
            <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(260px,5fr)]">
              <LeadBigCard
                event={lead}
                live={overlayRows[lead.event_id]}
                flash={flashes[lead.event_id]}
                locate={locateId === lead.event_id}
              />
              <HistoryRail events={events} filterKey={`${group}:${onlyAbovePivot}:${minScore}`} onPromoteLead={promoteLead} />
            </div>
          )}
          {restEvents.length > 0 && (
            <div className="radar-section-heading mb-3 mt-6 flex flex-wrap items-baseline justify-between gap-2 pb-2">
              <p className="text-body-s font-semibold text-ink-800">
                {t('其余信号')} · <span className="font-mono tnum">{restEvents.length}</span>
              </p>
              <p className="text-micro text-ink-400">{t('点击小卡设为首要信号 · 点击代码打开个股页')}</p>
            </div>
          )}
          {view === 'cards' ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {restEvents
                .map((event, index) => (
                  <motion.div
                    key={event.event_id}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: Math.min(index * 0.045, 0.5) }}
                  >
                    <EventCard
                      event={event}
                      live={overlayRows[event.event_id]}
                      flash={flashes[event.event_id]}
                      onSelect={() => promoteLead(event.event_id)}
                    />
                  </motion.div>
                ))}
            </div>
          ) : (
            <RadarTable
              events={events}
              flashes={flashes}
              overlay={overlayRows}
              onSelect={(event) => promoteLead(event.event_id)}
            />
          )}
        </>
      )}
      </section>
      <SourceNote className="mt-8" text={t('突破扫描结果 · 日线收盘后更新')} />
    </div>
  );
}

/* ---------------- Lead 大卡（美版 LeadBigCard 対応） ---------------- */

function LeadBigCard({
  event,
  live,
  flash,
  locate = false,
}: {
  event: RadarEvent;
  live?: { live_price: number; pivot_distance_pct?: number; above_pivot?: boolean };
  flash?: 'up' | 'down';
  locate?: boolean;
}) {
  const chart = usePolling(
    () => stocksApi.chart(event.canonical_code, '6m'),
    null,
    [event.canonical_code],
  );
  const scores = event.scores ?? {};
  const structure = event.structure ?? null;
  const invalidation = structure?.base?.invalidation_price ?? null;

  return (
    <motion.article
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER }}
      aria-label={t('{code} 首要信号大卡', { code: event.display_code })}
      className={cn('radar-lead-card card-surface p-5', locate && 'bk-locate')}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <SignalChip signal={event.signal_type} />
        <StateChip state={event.state} />
        <span className="radar-chip radar-chip-neutral">
          {event.sector33_name ?? '—'} · {event.market_name ?? '—'}
        </span>
        <span className="font-mono text-micro text-ink-400 tnum">{t('发现日')} {fmtDate(event.discovered_date)}</span>
        <span className="radar-chip radar-chip-brand ml-auto">
          <Icon name="radar" size={12} />
          {t('首要信号')}
        </span>
      </div>

      <h3 className="mt-2.5 font-display text-display-m text-ink-900">
        {event.name_ja ?? '—'}{' '}
        <Link
          to={`/stock/${event.display_code}`}
          className="text-brand-600 underline-offset-4 transition-colors hover:text-brand-700 hover:underline"
        >
          {event.display_code}
        </Link>
      </h3>

      <div className="mt-3">
        <p className="mb-1 text-micro text-ink-400">{t('日线 · 最多 30 个交易日')}</p>
        {chart.loading && !chart.data ? (
          <SkeletonCard className="h-[150px]" />
        ) : chart.data && chart.data.bars.length > 0 ? (
          <div className="radar-mini-chart relative h-[120px] overflow-hidden rounded-md bg-card-warm sm:h-[150px]">
            <LeadChart bars={chart.data.bars.slice(-30)} event={event} />
          </div>
        ) : (
          <div className="radar-mini-chart relative flex h-[120px] items-center justify-center overflow-hidden rounded-md bg-card-warm sm:h-[150px]">
            <img src="/empty-chart.svg" alt="" className="h-12 w-auto opacity-90" loading="lazy" />
          </div>
        )}
      </div>

      {structure && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {structure.structure_label && <SoftBadge tone="brand">{t(structure.structure_label)}</SoftBadge>}
          {structure.setup_label && <SoftBadge tone="ai">{t(structure.setup_label)}</SoftBadge>}
          {(structure.pattern_labels ?? []).map((label) => (
            <SoftBadge key={label}>{t(label)}</SoftBadge>
          ))}
          {structure.spring && <SoftBadge tone="up">{t('Spring 假跌破回收')}</SoftBadge>}
          {structure.upthrust && <SoftBadge tone="down">{t('Upthrust 假突破')}</SoftBadge>}
        </div>
      )}

      <div className="mt-3 flex flex-col gap-2.5 sm:flex-row sm:items-stretch">
        <div className="grid flex-1 grid-cols-1 gap-2.5 sm:grid-cols-3">
          <div className="radar-value-cell px-3 py-2.5">
            <p className="text-micro text-ink-400">{live ? t('盘中价') : t('当前价')}</p>
            <p className="mt-0.5">
              <TickPrice flash={flash} className="font-mono text-data-l text-ink-900">
                {fmtPrice(live?.live_price ?? (event.snapshot.close as number | null))}
              </TickPrice>
            </p>
          </div>
          <div className="radar-value-cell px-3 py-2.5">
            <p className="flex items-center gap-1 text-micro text-ink-400">
              <span className="radar-reference-glyph radar-reference-trigger" aria-hidden />
              {t('突破枢轴')}
            </p>
            <p className="mt-0.5 font-mono text-data-l text-ink-900 tnum">{fmtPrice(event.pivot_price)}</p>
          </div>
          <div className="radar-value-cell px-3 py-2.5">
            <p className="flex items-center gap-1 text-micro text-ink-400">
              <span className="radar-reference-glyph radar-reference-invalid" aria-hidden />
              {t('失效位置')}
            </p>
            <p className="mt-0.5 font-mono text-data-l text-ink-900 tnum">{fmtPrice(invalidation)}</p>
          </div>
        </div>
        <div className="radar-value-cell radar-priority-cell flex flex-col items-center justify-center gap-1.5 px-3 py-1.5">
          <PriorityRing
            score={event.alert_priority}
            label={t('告警优先级')}
            hint={RADAR_SCORE_HINTS.优先级}
            emptyLabel={t('告警优先级数据不足')}
          />
        </div>
      </div>
      <PriceScale
        className="mt-3"
        large
        invalidation={invalidation}
        trigger={event.trigger_price ?? event.pivot_price}
        current={live?.live_price ?? (event.snapshot.close as number | null)}
        flash={flash}
      />

      <div className="mt-4 grid grid-cols-1 gap-4 border-t border-line pt-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <section aria-label={t('分项评分')}>
          <p className="eyebrow mb-2">{t('分项评分')}</p>
          <div className="space-y-1.5">
            <ScoreBar label="综合质量" score={scores.breakout_quality?.score ?? null} />
            <ScoreBar label="趋势质量" score={scores.trend_quality?.score ?? null} />
            <ScoreBar label="基底质量" score={scores.base_quality?.score ?? null} />
            <ScoreBar label="突破确认" score={scores.breakout_confirmation?.score ?? null} />
            <ScoreBar label="相对强度" score={scores.relative_strength?.score ?? null} />
            <ScoreBar label="量能" score={scores.participation?.score ?? null} />
            <ScoreBar label="流动性" score={scores.liquidity?.score ?? null} />
            <ScoreBar label="市场契合" score={scores.market_fit ?? null} />
            <ScoreBar label="行业契合" score={scores.sector_fit ?? null} />
            <ScoreBar label="追高风险" score={scores.chase_risk ?? null} />
            <ScoreBar label="拥挤度" score={scores.crowding_risk ?? null} />
          </div>
        </section>
        <div className="flex flex-col gap-3">
          {event.transitions && event.transitions.length > 0 && (
            <div>
              <p className="eyebrow mb-1.5">{t('生命周期')}</p>
              <ol className="space-y-1 text-caption text-ink-600">
                {event.transitions.slice(-5).map((transition, index) => (
                  <li key={index} className="flex items-center gap-2">
                    <span className="font-mono tnum text-ink-400">{fmtDate(transition.date)}</span>
                    <span>{t(RADAR_STATE_LABELS[transition.to] ?? transition.to)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          <p className="text-caption text-ink-500">
            {t('成交额')} <span className="font-mono tnum text-ink-800">{fmtYenCompact(event.snapshot.turnover_today as number | null)}</span>
          </p>
          <Link
            to={`/stock/${event.display_code}`}
            className="mt-auto flex items-center justify-center gap-1.5 rounded-md bg-brand-600 px-3.5 py-2 text-caption font-medium text-white shadow-btn-hi transition-[transform,background-color] duration-fast hover:bg-brand-700 active:scale-[0.98]"
          >
            {t('打开研究页')}
            <Icon name="arrow-up-right" size={13} />
          </Link>
        </div>
      </div>
    </motion.article>
  );
}

function LeadChart({ bars, event }: { bars: StockBar[]; event: RadarEvent }) {
  const colorMode = useColorMode();
  const option = useMemo(() => {
    void colorMode;
    const dates = bars.map((bar) => bar.trade_date.slice(5));
    const candles = bars.map((bar) => [
      bar.adj_open ?? bar.open,
      bar.adj_close ?? bar.close,
      bar.adj_low ?? bar.low,
      bar.adj_high ?? bar.high,
    ]);
    const markLines: Record<string, unknown>[] = [];
    if (event.pivot_price !== null) {
      markLines.push({
        yAxis: event.pivot_price,
        lineStyle: { color: CH.brand600, type: 'dashed', width: 1.2 },
        label: { formatter: `${t('枢轴价')} ${fmtPrice(event.pivot_price)}`, position: 'insideEndTop', color: CH.brand600, fontSize: 10 },
      });
    }
    const base = event.structure?.base;
    if (base?.invalidation_price != null) {
      markLines.push({
        yAxis: base.invalidation_price,
        lineStyle: { color: CH.down600, type: 'dotted', width: 1 },
        label: { formatter: t('失效位'), position: 'insideEndBottom', color: CH.down600, fontSize: 10 },
      });
    }
    return {
      grid: baseGrid({ top: 10, bottom: 4, left: 4, right: 44 }),
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: categoryAxis(dates),
      yAxis: valueAxis({ scale: true, position: 'right' }),
      series: [
        {
          type: 'candlestick' as const,
          data: candles,
          itemStyle: {
            color: CH.up600, color0: CH.down600,
            borderColor: CH.up600, borderColor0: CH.down600,
          },
          markLine: {
            symbol: 'none',
            data: markLines,
            animation: false,
          },
          ...(base?.resistance_high != null && base?.resistance_low != null
            ? {
                markArea: {
                  silent: true,
                  itemStyle: { color: CH.brand400, opacity: 0.08 },
                  data: [
                    [{ yAxis: base.resistance_low }, { yAxis: base.resistance_high }] as [
                      { yAxis: number },
                      { yAxis: number },
                    ],
                  ],
                },
              }
            : {}),
        },
      ],
    };
  }, [bars, colorMode, event]);
  return <ReactECharts className="h-full w-full" option={option} ariaLabel={`${event.display_code} lead chart`} />;
}

/* ---------------- イベントカード ---------------- */

function EventCard({ event, onSelect, live, flash }: {
  event: RadarEvent;
  onSelect: () => void;
  live?: { live_price: number; pivot_distance_pct?: number; above_pivot?: boolean };
  flash?: 'up' | 'down';
}) {
  const structure = event.structure ?? null;
  /* 遅延気配なので必ず「遅延」と分かる見た目にする。スコアは夜間のまま。 */
  const above = live?.above_pivot === true;
  const current = live?.live_price ?? (event.snapshot.close as number | null);
  return (
    <article className="relative h-full w-full">
      <button
        type="button"
        onClick={onSelect}
        aria-label={t('{code} 雷达信号卡', { code: event.display_code })}
        className="absolute inset-0 z-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30"
      />
      <div
        className="radar-signal-card card-surface card-lift relative z-10 flex h-full cursor-pointer flex-col"
        onClick={(click) => {
          const target = click.target as Element;
          if (target.closest('button, a, summary, [role="button"]')) return;
          if (window.getSelection()?.toString()) return;
          onSelect();
        }}
      >
      <div className="flex items-center gap-2">
        <CodeCell displayCode={event.display_code} nameJa={event.name_ja} />
        <span className="ml-auto font-mono text-data-l tnum text-ink-900">
          {event.alert_priority !== null ? Math.round(event.alert_priority) : '—'}
        </span>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <SignalChip signal={event.signal_type} />
        <StateChip state={event.state} />
        {structure?.setup_label && <SoftBadge tone="ai">{t(structure.setup_label)}</SoftBadge>}
        {above && (
          <SoftBadge tone="up">
            <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
            {t('盘中站上枢轴')}
          </SoftBadge>
        )}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-1 text-caption">
        {live ? (
          <CardFact
            label={t('盘中价')}
            value={
              <TickPrice flash={flash} className="font-mono text-body-s text-ink-800">
                {fmtPrice(live.live_price)}
                {live.pivot_distance_pct != null ? ` (${fmtPct(live.pivot_distance_pct)})` : ''}
              </TickPrice>
            }
          />
        ) : (
          <CardFact
            label={t('收盘')}
            value={
              <TickPrice flash={flash} className="font-mono text-body-s text-ink-800">
                {fmtPrice(event.snapshot.close as number | null)}
              </TickPrice>
            }
          />
        )}
        <CardFact label={t('枢轴价')} value={fmtPrice(event.pivot_price)} />
        <CardFact label={t('成交额')} value={fmtYenCompact(event.snapshot.turnover_today as number | null)} />
      </div>
      <PriceScale
        className="mt-2"
        invalidation={structure?.base?.invalidation_price}
        trigger={event.trigger_price ?? event.pivot_price}
        current={current}
        flash={flash}
      />
      <details className="radar-disclosure mt-3">
        <summary>
          <span>{t('评分套组')}</span>
          <Icon name="chevron-down" size={14} className="radar-disclosure-arrow" />
        </summary>
        <ScoreBarsMini event={event} className="pb-3 pt-1" />
      </details>
      <div className="radar-card-footer mt-auto flex items-center justify-between gap-3 pt-3">
        <StrengthBar score={event.scores?.relative_strength?.score ?? event.alert_priority} width={64} />
        <span className="font-mono text-micro text-ink-400 tnum">{fmtDate(event.discovered_date)}</span>
      </div>
      </div>
    </article>
  );
}

function CardFact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <span>
      <span className="block text-micro text-ink-400">{label}</span>
      <span className="font-mono text-body-s tnum text-ink-800">{value}</span>
    </span>
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
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.pivot_price)}</span>,
      },
      {
        key: 'close', title: t('收盘'), align: 'right',
        render: (row) => (
          <TickPrice flash={flashes[row.event_id]} className="font-mono text-body-s text-ink-900">
            {fmtPrice(overlay[row.event_id]?.live_price ?? (row.snapshot.close as number | null))}
          </TickPrice>
        ),
      },
      {
        key: 'turnover', title: t('成交额'), align: 'right', sortable: true,
        sortValue: (row) => (row.snapshot.turnover_today as number | null) ?? -1,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">
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
          <span className="font-mono text-data-m tnum text-ink-900">
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
