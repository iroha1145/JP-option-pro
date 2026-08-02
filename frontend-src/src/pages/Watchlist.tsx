/** 自选股：报价 + 备注 + 重点标记（写操作仅所有者）。 */

import { useMemo, useState } from 'react';
import { watchlistApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtPrice, fmtYenCompact } from '@/lib/format';
import type { WatchlistItem } from '@/api/types';

export default function Watchlist() {
  const { isOwner } = useAccess();
  const query = usePolling(() => watchlistApi.list(), 120_000);
  const state = remoteState(query, (d) => d.items.length === 0);
  const [busy, setBusy] = useState<string | null>(null);

  const columns = useMemo<Column<WatchlistItem>[]>(() => {
    const base: Column<WatchlistItem>[] = [
      {
        key: 'code',
        title: t('代码'),
        width: '30%',
        render: (row) => (
          <span className="flex items-center gap-1.5">
            {row.marked_important && <span className="text-warn-600">★</span>}
            <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />
          </span>
        ),
      },
      {
        key: 'sector',
        title: t('行业'),
        render: (row) => <span className="text-caption text-ink-500">{row.sector33_name ?? '—'}</span>,
      },
      {
        key: 'close',
        title: t('收盘'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.close ?? Number.NEGATIVE_INFINITY,
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.quote?.close)}</span>,
      },
      {
        key: 'change',
        title: t('涨跌'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.change_pct ?? Number.NEGATIVE_INFINITY,
        render: (row) => <ChangeBadge value={row.quote?.change_pct} size="sm" />,
      },
      {
        key: 'turnover',
        title: t('成交额'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.turnover_value ?? -1,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">{fmtYenCompact(row.quote?.turnover_value)}</span>
        ),
      },
      {
        key: 'note',
        title: t('备注'),
        render: (row) => <span className="truncate text-caption text-ink-500">{row.note ?? '—'}</span>,
      },
    ];
    if (isOwner) {
      base.push({
        key: 'actions',
        title: '',
        align: 'right',
        render: (row) => (
          <span className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              disabled={busy === row.canonical_code}
              className="rounded-md border border-line px-2 py-0.5 text-micro text-ink-500 hover:bg-brand-50"
              onClick={async (event) => {
                event.stopPropagation();
                setBusy(row.canonical_code);
                try {
                  await watchlistApi.update(row.canonical_code, {
                    marked_important: !row.marked_important,
                  });
                  query.refresh({ force: true });
                } finally {
                  setBusy(null);
                }
              }}
            >
              ★
            </button>
            <button
              type="button"
              disabled={busy === row.canonical_code}
              className="rounded-md border border-line px-2 py-0.5 text-micro text-down-700 hover:bg-down-50"
              onClick={async (event) => {
                event.stopPropagation();
                setBusy(row.canonical_code);
                try {
                  await watchlistApi.remove(row.canonical_code);
                  query.refresh({ force: true });
                } finally {
                  setBusy(null);
                }
              }}
            >
              {t('移出自选')}
            </button>
          </span>
        ),
      });
    }
    return base;
  }, [isOwner, busy, query]);

  return (
    <div className="space-y-6">
      <PageHeader
        section="05"
        eyebrow="WATCHLIST · OWNER CURATED"
        title={t('自选股')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<DataThrough date={query.data?.items.find((item) => item.quote?.trade_date)?.quote?.trade_date} />}
      />
      {state === 'loading' ? (
        <SkeletonRows rows={8} />
      ) : state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(query.error?.message ?? '')} />
      ) : state === 'empty' ? (
        <EmptyState title={t('暂无自选')} description={t('在筛选器中添加')} />
      ) : (
        <DataTable
          columns={columns}
          rows={query.data?.items ?? []}
          rowKey={(row) => row.canonical_code}
          rowHeight={44}
        />
      )}
    </div>
  );
}
