/** 日本市场页：指数走势 + 全部33业种强弱 + 广度与空卖。 */

import { useState } from 'react';
import { marketApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { CodeCell, DataThrough } from '@/components/domain';
import { t } from '@/i18n/core';
import { fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import type { SectorStrength } from '@/api/types';

export default function Market() {
  const market = usePolling(() => marketApi.overview(), 120_000);
  const [indexCode, setIndexCode] = useState('0000');
  const series = usePolling(() => marketApi.indexSeries(indexCode, 250), null, [indexCode]);
  const state = remoteState(market, (d) => d.indices.length === 0);

  const sectorColumns: Column<SectorStrength>[] = [
    {
      key: 'name',
      title: t('行业'),
      render: (row) => <span className="text-body-s text-ink-800">{row.sector33_name}</span>,
    },
    {
      key: 'members',
      title: '#',
      align: 'right',
      width: '60px',
      sortable: true,
      sortValue: (row) => row.member_count,
      render: (row) => <span className="font-mono text-body-s tnum text-ink-500">{row.member_count}</span>,
    },
    {
      key: 'r1',
      title: t('当日'),
      align: 'right',
      sortable: true,
      sortValue: (row) => row.median_return_1d ?? Number.NEGATIVE_INFINITY,
      render: (row) => <ChangeBadge value={row.median_return_1d} size="sm" />,
    },
    {
      key: 'r20',
      title: t('近20日'),
      align: 'right',
      sortable: true,
      sortValue: (row) => row.median_return_20d ?? Number.NEGATIVE_INFINITY,
      render: (row) => <ChangeBadge value={row.median_return_20d} size="sm" />,
    },
    {
      key: 'leaders',
      title: t('今日领涨'),
      render: (row) => (
        <span className="flex flex-wrap gap-2">
          {row.leaders.map((leader) => (
            <CodeCell
              key={leader.canonical_code}
              displayCode={leader.canonical_code.length === 5 && leader.canonical_code.endsWith('0') ? leader.canonical_code.slice(0, 4) : leader.canonical_code}
              nameJa={leader.name_ja}
              to={`/stock/${leader.canonical_code}`}
            />
          ))}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        section="02"
        eyebrow="JAPAN MARKET · TOPIX & SECTORS"
        title={t('日本市场')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<DataThrough date={market.data?.data_through} />}
      />

      {state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(market.error?.message ?? '')} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section className="card-surface rounded-lg p-4 lg:col-span-2">
              {/* 窄屏竖排：并排会把「指数」压成竖字、把 Segmented 压到换行 */}
              <header className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <h2 className="text-h3 text-ink-900">{t('指数')}</h2>
                <Segmented
                  className="max-w-full overflow-x-auto"
                  options={(market.data?.indices ?? []).slice(0, 4).map((index) => ({
                    value: index.index_code,
                    label: index.name.replace('東証', '').replace('市場指数', ''),
                  }))}
                  value={indexCode}
                  onChange={setIndexCode}
                />
              </header>
              {series.data && series.data.bars.length > 0 ? (
                <ReactECharts
                  className="h-64 w-full"
                  ariaLabel={series.data.name}
                  option={{
                    grid: baseGrid({ top: 16 }),
                    tooltip: glassTooltip(),
                    xAxis: categoryAxis(series.data.bars.map((bar) => bar.trade_date.slice(5))),
                    yAxis: valueAxis({ scale: true }),
                    series: [
                      {
                        type: 'line',
                        data: series.data.bars.map((bar) => bar.close),
                        showSymbol: false,
                        lineStyle: { color: CH.brand600, width: 1.6 },
                        areaStyle: { color: CH.brand400, opacity: 0.08 },
                      },
                    ],
                  }}
                />
              ) : (
                <SkeletonCard className="h-64" />
              )}
            </section>

            <section className="space-y-3">
              {(market.data?.indices ?? []).map((index) => (
                <button
                  key={index.index_code}
                  type="button"
                  onClick={() => setIndexCode(index.index_code)}
                  className={`card-surface card-hover flex w-full items-center justify-between rounded-lg px-3 py-2 text-left ${
                    index.index_code === indexCode ? 'ring-1 ring-brand-400' : ''
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-body-s text-ink-700">{index.name}</span>
                    <span className="font-mono text-data-m tnum text-ink-900">{fmtPrice(index.close)}</span>
                  </span>
                  <span className="flex flex-col items-end gap-0.5">
                    <ChangeBadge value={index.change_pct} size="sm" />
                    <span className="text-micro text-ink-400">
                      {t('近20日')} {fmtPct(index.return_20d)}
                    </span>
                  </span>
                </button>
              ))}
            </section>
          </div>

          <section className="card-surface rounded-lg p-4">
            <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-h3 text-ink-900">{t('行业强弱')}</h2>
              <span className="text-caption text-ink-400">
                {t('成交额')}: {fmtYenCompact(market.data?.breadth.total_turnover_value)} ·{' '}
                {t('上涨')} {market.data?.breadth.advancers ?? '—'} / {t('下跌')}{' '}
                {market.data?.breadth.decliners ?? '—'}
              </span>
            </header>
            <DataTable
              columns={sectorColumns}
              rows={market.data?.sectors ?? []}
              rowKey={(row) => row.sector33_code}
              rowHeight={44}
              defaultSort={{ key: 'r1', desc: true }}
            />
          </section>
        </>
      )}
    </div>
  );
}
