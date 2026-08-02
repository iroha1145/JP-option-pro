/** 突破雷达：收盘后全市场扫描结果 + 生命周期过滤 + 事件评分详情。 */

import { useMemo, useState } from 'react';
import { radarApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough, RADAR_STATE_LABELS, ScoreBar, SignalChip, StateChip } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import type { RadarEvent } from '@/api/types';

type StateGroup = 'active' | 'confirmed' | 'watching' | 'closed' | 'all';

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
  const [selected, setSelected] = useState<RadarEvent | null>(null);
  const query = usePolling(
    () => radarApi.current(GROUP_STATES[group] ? { states: GROUP_STATES[group], limit: 200 } : { limit: 200 }),
    120_000,
    [group],
  );
  const state = remoteState(query, (d) => d.events.length === 0);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const columns = useMemo<Column<RadarEvent>[]>(
    () => [
      {
        key: 'code',
        title: t('代码'),
        width: '30%',
        render: (row) => <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />,
      },
      {
        key: 'signal',
        title: t('信号'),
        render: (row) => <SignalChip signal={row.signal_type} />,
      },
      {
        key: 'state',
        title: t('状态'),
        render: (row) => <StateChip state={row.state} />,
      },
      {
        key: 'pivot',
        title: t('枢轴价'),
        align: 'right',
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.pivot_price)}</span>,
      },
      {
        key: 'close',
        title: t('收盘'),
        align: 'right',
        render: (row) => (
          <span className="font-mono text-body-s tnum">{fmtPrice(row.snapshot.close as number | null)}</span>
        ),
      },
      {
        key: 'turnover',
        title: t('成交额'),
        align: 'right',
        sortable: true,
        sortValue: (row) => (row.snapshot.turnover_today as number | null) ?? -1,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">
            {fmtYenCompact(row.snapshot.turnover_today as number | null)}
          </span>
        ),
      },
      {
        key: 'discovered',
        title: t('发现日'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.discovered_date,
        render: (row) => <span className="text-caption text-ink-500">{fmtDate(row.discovered_date)}</span>,
      },
      {
        key: 'priority',
        title: t('优先级'),
        align: 'right',
        sortable: true,
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

      {state === 'loading' ? (
        <SkeletonRows rows={10} />
      ) : state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(query.error?.message ?? '')} />
      ) : state === 'empty' ? (
        <EmptyState title={t('暂无数据')} description={query.data?.note ?? ''} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <DataTable
              columns={columns}
              rows={query.data?.events ?? []}
              rowKey={(row) => row.event_id}
              rowHeight={44}
              defaultSort={{ key: 'priority', desc: true }}
              onRowClick={(row) => setSelected(row)}
            />
          </div>
          <aside className="card-surface h-fit rounded-lg p-4 xl:sticky xl:top-20">
            {selected ? (
              <EventDetail event={selected} />
            ) : (
              <p className="py-8 text-center text-body-s text-ink-400">{t('详情')} — {t('打开')}</p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function EventDetail({ event }: { event: RadarEvent }) {
  const scores = event.scores ?? {};
  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-2">
        <CodeCell displayCode={event.display_code} nameJa={event.name_ja} to={`/stock/${event.display_code}`} />
        <StateChip state={event.state} />
      </header>
      <dl className="grid grid-cols-2 gap-2 text-body-s">
        <Fact label={t('信号')} value={<SignalChip signal={event.signal_type} />} />
        <Fact label={t('枢轴价')} value={fmtPrice(event.pivot_price)} mono />
        <Fact label={t('发现日')} value={fmtDate(event.discovered_date)} />
        <Fact
          label={t('距52周高点')}
          value={fmtPct(event.snapshot.pct_from_high_252 as number | null)}
          mono
        />
      </dl>
      <div className="space-y-1.5 border-t border-line pt-3">
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
        <ScoreBar label="数据置信度" score={scores.data_confidence ?? null} />
      </div>
      {event.transitions && event.transitions.length > 0 && (
        <div className="border-t border-line pt-3">
          <h3 className="mb-1.5 text-caption font-medium text-ink-500">{t('生命周期')}</h3>
          <ol className="space-y-1 text-caption text-ink-600">
            {event.transitions.slice(-6).map((transition, index) => (
              <li key={index} className="flex items-center gap-2">
                <span className="font-mono tnum text-ink-400">{fmtDate(transition.date)}</span>
                <span>{t(RADAR_STATE_LABELS[transition.to] ?? transition.to)}</span>
                <span className="truncate text-ink-300">{transition.reason}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function Fact({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-md bg-paper-2 px-2 py-1.5">
      <dt className="text-micro text-ink-400">{label}</dt>
      <dd className={mono ? 'font-mono tnum text-ink-900' : 'text-ink-900'}>{value}</dd>
    </div>
  );
}
