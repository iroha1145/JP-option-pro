/** 突破雷达 — 美版布局移植：Lead 大卡（K线+枢轴带）→ 信号卡片流 → 生命周期。
 *  数据仍为收盘后日线扫描，Lead 卡的 K 线按需拉取单只标的。 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { quotesApi, radarApi, stocksApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { cn } from '@/lib/utils';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { CodeCell, DataThrough, RADAR_STATE_LABELS, ScoreBar, SignalChip, StateChip } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import type { RadarEvent, StockBar } from '@/api/types';

type StateGroup = 'active' | 'confirmed' | 'watching' | 'closed' | 'all';
type ViewMode = 'cards' | 'table';

const GROUP_STATES: Record<StateGroup, string | undefined> = {
  all: undefined,
  active: 'triggered,confirmed,holding,retesting,retest_held,reaccelerating,extended',
  confirmed: 'confirmed,holding,retest_held,reaccelerating',
  watching: 'discovered,watching',
  closed: 'failed,expired',
};

export default function Radar() {
  const { isOwner } = useAccess();
  const [group, setGroup] = useState<StateGroup>('active');
  const [view, setView] = useState<ViewMode>('cards');
  const [leadId, setLeadId] = useState<string | null>(null);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

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

  const events = useMemo(() => {
    const all = query.data?.events ?? [];
    if (!onlyAbovePivot) return all;
    return all.filter((event) => overlayRows[event.event_id]?.above_pivot);
  }, [query.data, onlyAbovePivot, overlayRows]);

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
  }, [group]);

  return (
    <div className="space-y-6">
      <PageHeader
        section="03"
        eyebrow="BREAKOUT RADAR · POST-CLOSE SCAN"
        title={t('突破雷达')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <div className="flex items-center gap-3">
            <DataThrough date={query.data?.scan_date} />
            {isOwner && (
              <button
                type="button"
                className="rounded-md border border-line bg-card px-2.5 py-1 text-caption text-ink-600 hover:bg-brand-50"
                onClick={async () => {
                  try {
                    await workerApi.trigger('radar_refresh');
                    setRefreshNote(t('已提交'));
                  } catch (error) {
                    setRefreshNote(String((error as Error).message ?? error));
                  }
                }}
              >
                {t('重算雷达')}
              </button>
            )}
            {refreshNote && <span className="text-caption text-ink-400">{refreshNote}</span>}
          </div>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
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
        {overlay.data?.enabled && (
          <button
            type="button"
            onClick={() => setOnlyAbovePivot((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-caption transition-colors',
              onlyAbovePivot
                ? 'border-up-600/40 bg-up-50 text-up-700'
                : 'border-line bg-card text-ink-600 hover:border-brand-400',
            )}
            title={t('用延迟{n}分的盘中价与夜间枢轴比较', { n: overlay.data?.delayed_minutes ?? 15 })}
          >
            <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
            {t('盘中站上枢轴')}
            <span className="font-mono tnum">{overlay.data?.above_pivot_count ?? 0}</span>
          </button>
        )}
        <Segmented<ViewMode>
          options={[
            { value: 'cards', label: t('卡片') },
            { value: 'table', label: t('列表') },
          ]}
          value={view}
          onChange={setView}
        />
      </div>

      {state === 'loading' ? (
        <>
          <SkeletonCard className="h-80" />
          <SkeletonRows rows={6} />
        </>
      ) : state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(query.error?.message ?? '')} />
      ) : state === 'empty' ? (
        <EmptyState title={t('暂无数据')} description={query.data?.note ?? ''} />
      ) : (
        <>
          {lead && <LeadBigCard event={lead} />}
          {view === 'cards' ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {events
                .filter((event) => event.event_id !== lead?.event_id)
                .map((event) => (
                  <EventCard
                    key={event.event_id}
                    event={event}
                    live={overlayRows[event.event_id]}
                    onSelect={() => {
                      setLeadId(event.event_id);
                      window.scrollTo({ top: 0, behavior: 'smooth' });
                    }}
                  />
                ))}
            </div>
          ) : (
            <RadarTable events={events} onSelect={(event) => {
              setLeadId(event.event_id);
              window.scrollTo({ top: 0, behavior: 'smooth' });
            }} />
          )}
        </>
      )}
    </div>
  );
}

/* ---------------- Lead 大卡（美版 LeadBigCard 対応） ---------------- */

function LeadBigCard({ event }: { event: RadarEvent }) {
  const chart = usePolling(
    () => stocksApi.chart(event.canonical_code, '6m'),
    null,
    [event.canonical_code],
  );
  const scores = event.scores ?? {};
  const structure = event.structure ?? null;

  return (
    <section className="card-surface overflow-hidden rounded-xl">
      <div className="grid grid-cols-1 gap-0 lg:grid-cols-3">
        {/* 左 2/3: ヘッダー + K線 */}
        <div className="border-line p-4 lg:col-span-2 lg:border-r">
          <header className="mb-2 flex flex-wrap items-center gap-2">
            <CodeCell displayCode={event.display_code} nameJa={event.name_ja} to={`/stock/${event.display_code}`} />
            <SignalChip signal={event.signal_type} />
            <StateChip state={event.state} />
            <span className="ml-auto flex items-baseline gap-1.5">
              <span className="text-micro text-ink-400">{t('优先级')}</span>
              <span className="font-mono text-display-m tnum text-ink-900">
                {event.alert_priority !== null ? Math.round(event.alert_priority) : '—'}
              </span>
            </span>
          </header>
          <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-500">
            <span>{event.sector33_name ?? '—'} · {event.market_name ?? '—'}</span>
            <span>{t('发现日')} {fmtDate(event.discovered_date)}</span>
            <span>
              {t('枢轴价')} <span className="font-mono tnum text-ink-800">{fmtPrice(event.pivot_price)}</span>
            </span>
            <span>
              {t('收盘')} <span className="font-mono tnum text-ink-800">{fmtPrice(event.snapshot.close as number | null)}</span>
            </span>
            <span>
              {t('成交额')} <span className="font-mono tnum text-ink-800">{fmtYenCompact(event.snapshot.turnover_today as number | null)}</span>
            </span>
          </div>
          {chart.data && chart.data.bars.length > 0 ? (
            <LeadChart bars={chart.data.bars} event={event} />
          ) : (
            <SkeletonCard className="h-64" />
          )}
          {/* 構造タグ行（価格行動 + 量価一致） */}
          {structure && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {structure.structure_label && (
                <Tag tone="brand">{structure.structure_label}</Tag>
              )}
              {structure.setup_label && <Tag tone="ai">{t(structure.setup_label)}</Tag>}
              {(structure.pattern_labels ?? []).map((label) => (
                <Tag key={label} tone="neutral">{t(label)}</Tag>
              ))}
              {structure.spring && <Tag tone="up">{t('Spring 假跌破回收')}</Tag>}
              {structure.upthrust && <Tag tone="down">{t('Upthrust 假突破')}</Tag>}
            </div>
          )}
        </div>

        {/* 右 1/3: スコア + ライフサイクル */}
        <div className="flex flex-col gap-3 p-4">
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
          {event.transitions && event.transitions.length > 0 && (
            <div className="border-t border-line pt-2.5">
              <h3 className="mb-1.5 text-caption font-medium text-ink-500">{t('生命周期')}</h3>
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
          <Link
            to={`/stock/${event.display_code}`}
            className="mt-auto rounded-md border border-line py-1.5 text-center text-body-s text-brand-700 hover:bg-brand-50"
          >
            {t('个股研究')} →
          </Link>
        </div>
      </div>
    </section>
  );
}

function LeadChart({ bars, event }: { bars: StockBar[]; event: RadarEvent }) {
  const option = useMemo(() => {
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
  }, [bars, event]);
  return <ReactECharts className="h-64 w-full" option={option} ariaLabel={`${event.display_code} lead chart`} />;
}

/* ---------------- イベントカード ---------------- */

function EventCard({ event, onSelect, live }: {
  event: RadarEvent;
  onSelect: () => void;
  live?: { live_price: number; pivot_distance_pct?: number; above_pivot?: boolean };
}) {
  const quality = event.scores?.breakout_quality?.score ?? null;
  const structure = event.structure ?? null;
  /* 遅延気配なので必ず「遅延」と分かる見た目にする。スコアは夜間のまま。 */
  const above = live?.above_pivot === true;
  return (
    <button
      type="button"
      onClick={onSelect}
      className="card-surface card-hover flex flex-col gap-2 rounded-lg p-3 text-left"
    >
      <div className="flex items-center gap-2">
        <CodeCell displayCode={event.display_code} nameJa={event.name_ja} />
        <span className="ml-auto font-mono text-data-l tnum text-ink-900">
          {event.alert_priority !== null ? Math.round(event.alert_priority) : '—'}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <SignalChip signal={event.signal_type} />
        <StateChip state={event.state} />
        {structure?.setup_label && <Tag tone="ai">{t(structure.setup_label)}</Tag>}
        {above && (
          <span className="inline-flex items-center gap-1 rounded-pill bg-up-50 px-2 py-0.5 text-micro font-medium text-up-700">
            <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
            {t('盘中站上枢轴')}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-1 text-caption">
        {live ? (
          <CardFact
            label={t('盘中价')}
            value={`${fmtPrice(live.live_price)}${
              live.pivot_distance_pct != null ? ` (${fmtPct(live.pivot_distance_pct)})` : ''
            }`}
          />
        ) : (
          <CardFact label={t('收盘')} value={fmtPrice(event.snapshot.close as number | null)} />
        )}
        <CardFact label={t('枢轴价')} value={fmtPrice(event.pivot_price)} />
        <CardFact label={t('成交额')} value={fmtYenCompact(event.snapshot.turnover_today as number | null)} />
      </div>
      <div className="flex items-center gap-2 text-micro text-ink-400">
        <span>{t('综合质量')} {quality !== null ? Math.round(quality) : '—'}</span>
        <span>·</span>
        <span>{t('距52周高点')} {fmtPct(event.snapshot.pct_from_high_252 as number | null)}</span>
        <span className="ml-auto">{fmtDate(event.discovered_date)}</span>
      </div>
    </button>
  );
}

function CardFact({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-md bg-paper-2 px-1.5 py-1">
      <span className="block text-micro text-ink-400">{label}</span>
      <span className="font-mono text-body-s tnum text-ink-800">{value}</span>
    </span>
  );
}

function Tag({ children, tone }: { children: React.ReactNode; tone: 'brand' | 'ai' | 'up' | 'down' | 'neutral' }) {
  const tones = {
    brand: 'bg-brand-50 text-brand-700',
    ai: 'bg-ai-50 text-ai-600',
    up: 'bg-up-50 text-up-700',
    down: 'bg-down-50 text-down-700',
    neutral: 'border border-line bg-card text-ink-600',
  };
  return (
    <span className={`inline-flex items-center rounded-pill px-2 py-0.5 text-micro ${tones[tone]}`}>{children}</span>
  );
}

/* ---------------- 列表視圖 ---------------- */

function RadarTable({ events, onSelect }: { events: RadarEvent[]; onSelect: (event: RadarEvent) => void }) {
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
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.snapshot.close as number | null)}</span>,
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
    [],
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
