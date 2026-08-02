/** 决算日历：发表预定（J-Quants 覆盖限制如实标注）+ 最近开示。 */

import { useState } from 'react';
import { earningsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import SourceNote from '@/components/shared/SourceNote';
import { CodeCell, DataThrough } from '@/components/domain';
import { t } from '@/i18n/core';
import { fmtDate, fmtYenCompact } from '@/lib/format';
import type { EarningsCalendarItem, EarningsRecentItem } from '@/api/types';

type Tab = 'upcoming' | 'recent';

export default function Earnings() {
  const [tab, setTab] = useState<Tab>('upcoming');
  const upcoming = usePolling(() => earningsApi.calendar(), 300_000);
  const recent = usePolling(() => earningsApi.recent(10), 300_000);

  const upcomingColumns: Column<EarningsCalendarItem>[] = [
    {
      key: 'date',
      title: t('发表预定'),
      width: '110px',
      sortable: true,
      sortValue: (row) => row.announcement_date ?? '9999',
      render: (row) => (
        <span className="font-mono text-body-s tnum text-ink-800">
          {row.announcement_date ? fmtDate(row.announcement_date) : t('未定')}
        </span>
      ),
    },
    {
      key: 'code',
      title: t('代码'),
      width: '30%',
      render: (row) => <CodeCell displayCode={row.display_code} nameJa={row.company_name} to={`/stock/${row.display_code}`} />,
    },
    {
      key: 'quarter',
      title: t('决算种别'),
      render: (row) => <span className="text-caption text-ink-600">{row.fiscal_quarter ?? '—'}</span>,
    },
    {
      key: 'fy',
      title: t('财年'),
      render: (row) => <span className="text-caption text-ink-500">{row.fiscal_year_end ?? '—'}</span>,
    },
    {
      key: 'sector',
      title: t('行业'),
      render: (row) => <span className="text-caption text-ink-500">{row.sector_name ?? '—'}</span>,
    },
    {
      key: 'watch',
      title: '★',
      align: 'center',
      width: '48px',
      render: (row) => (row.in_watchlist ? <span className="text-warn-600">★</span> : null),
    },
  ];

  const recentColumns: Column<EarningsRecentItem>[] = [
    {
      key: 'date',
      title: t('发表预定'),
      width: '120px',
      sortable: true,
      sortValue: (row) => `${row.disclosed_date ?? ''}${row.disclosed_time ?? ''}`,
      render: (row) => (
        <span className="font-mono text-body-s tnum text-ink-800">
          {fmtDate(row.disclosed_date)}
          <span className="ml-1 text-micro text-ink-400">{row.disclosed_time?.slice(0, 5) ?? ''}</span>
        </span>
      ),
    },
    {
      key: 'code',
      title: t('代码'),
      width: '26%',
      render: (row) => <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />,
    },
    {
      key: 'period',
      title: t('决算种别'),
      render: (row) => (
        <span className="flex items-center gap-1.5">
          <span className="rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">{row.period_type ?? '—'}</span>
          {row.is_forecast_revision && (
            <span className="rounded-sm bg-warn-50 px-1.5 py-0.5 text-micro text-warn-700">{t('业绩预想修正')}</span>
          )}
        </span>
      ),
    },
    {
      key: 'sales',
      title: t('销售额'),
      align: 'right',
      render: (row) => <span className="font-mono text-body-s tnum">{fmtYenCompact(row.sales)}</span>,
    },
    {
      key: 'op',
      title: t('营业利益'),
      align: 'right',
      render: (row) => <span className="font-mono text-body-s tnum">{fmtYenCompact(row.operating_profit)}</span>,
    },
    {
      key: 'np',
      title: t('纯利益'),
      align: 'right',
      render: (row) => <span className="font-mono text-body-s tnum">{fmtYenCompact(row.net_profit)}</span>,
    },
    {
      key: 'forecast',
      title: t('会社预想'),
      align: 'right',
      render: (row) => (
        <span className="flex items-center justify-end gap-1.5">
          <span className="font-mono text-body-s tnum text-ink-600">{fmtYenCompact(row.forecast_operating_profit)}</span>
          {row.forecast_direction === 'upward' && <span className="text-micro text-up-700">{t('上方修正')}</span>}
          {row.forecast_direction === 'downward' && <span className="text-micro text-down-700">{t('下方修正')}</span>}
        </span>
      ),
    },
    {
      key: 'watch',
      title: '★',
      align: 'center',
      width: '44px',
      render: (row) => (row.in_watchlist ? <span className="text-warn-600">★</span> : null),
    },
  ];

  const activeQuery = tab === 'upcoming' ? upcoming : recent;
  const state = remoteState(activeQuery as never, (d: { items: unknown[] }) => d.items.length === 0);

  return (
    <div className="space-y-6">
      <PageHeader
        section="06"
        eyebrow="EARNINGS · DISCLOSURE FLOW"
        title={t('决算日历')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<DataThrough date={recent.data?.items[0]?.disclosed_date} />}
      />
      <Segmented<Tab>
        options={[
          { value: 'upcoming', label: t('发表预定') },
          { value: 'recent', label: t('最近决算') },
        ]}
        value={tab}
        onChange={setTab}
      />
      {state === 'loading' ? (
        <SkeletonRows rows={10} />
      ) : state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(activeQuery.error?.message ?? '')} />
      ) : tab === 'upcoming' ? (
        <>
          {upcoming.data && upcoming.data.items.length === 0 ? (
            <EmptyState title={t('暂无数据')} />
          ) : (
            <DataTable
              columns={upcomingColumns}
              rows={upcoming.data?.items ?? []}
              rowKey={(row) => `${row.canonical_code}-${row.fiscal_quarter}-${row.fiscal_year_end}`}
              rowHeight={44}
              defaultSort={{ key: 'date', desc: false }}
            />
          )}
          {upcoming.data?.coverage_note && <SourceNote text={upcoming.data.coverage_note} />}
        </>
      ) : recent.data && recent.data.items.length === 0 ? (
        <EmptyState title={t('暂无数据')} />
      ) : (
        <DataTable
          columns={recentColumns}
          rows={recent.data?.items ?? []}
          rowKey={(row) => `${row.canonical_code}-${row.disclosed_date}-${row.period_type}-${row.type_of_document}`}
          rowHeight={44}
        />
      )}
    </div>
  );
}
