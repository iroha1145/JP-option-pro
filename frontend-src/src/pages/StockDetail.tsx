/** 个股研究页：K线（复权/不复权）+ 财务 + 信用/空卖 + 雷达 + 决算。 */

import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { stocksApi, watchlistApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { DataThrough, SignalChip, StateChip } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import type { FinancialSummaryView, MarginInterestRow, ShortPositionRow } from '@/api/types';

type Range = '3m' | '6m' | '1y' | '3y' | '10y';
type PriceMode = 'adjusted' | 'raw';

export default function StockDetail() {
  const { code = '' } = useParams();
  const [range, setRange] = useState<Range>('1y');
  const [priceMode, setPriceMode] = useState<PriceMode>('adjusted');
  const overview = usePolling(() => stocksApi.overview(code), null, [code]);
  const chart = usePolling(() => stocksApi.chart(code, range), null, [code, range]);
  const { isOwner } = useAccess();
  const [watchNote, setWatchNote] = useState<string | null>(null);

  const state = remoteState(overview);

  const chartOption = useMemo(() => {
    const bars = chart.data?.bars ?? [];
    if (bars.length === 0) return null;
    const pick = (bar: (typeof bars)[number], adj: 'adj_open' | 'adj_high' | 'adj_low' | 'adj_close', raw: 'open' | 'high' | 'low' | 'close') =>
      priceMode === 'adjusted' ? (bar[adj] ?? bar[raw]) : bar[raw];
    const dates = bars.map((bar) => bar.trade_date.slice(2));
    const candles = bars.map((bar) => [
      pick(bar, 'adj_open', 'open'),
      pick(bar, 'adj_close', 'close'),
      pick(bar, 'adj_low', 'low'),
      pick(bar, 'adj_high', 'high'),
    ]);
    const turnover = bars.map((bar) => bar.turnover_value);
    return {
      grid: [baseGrid({ top: 12, bottom: '26%' }), baseGrid({ top: '78%', bottom: 4 })],
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: [
        { ...categoryAxis(dates), gridIndex: 0 },
        { ...categoryAxis(dates), gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { ...valueAxis({ scale: true }), gridIndex: 0 },
        { ...valueAxis(), gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      series: [
        {
          type: 'candlestick' as const,
          data: candles,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: CH.up600,
            color0: CH.down600,
            borderColor: CH.up600,
            borderColor0: CH.down600,
          },
        },
        {
          type: 'bar' as const,
          data: turnover,
          xAxisIndex: 1,
          yAxisIndex: 1,
          itemStyle: { color: CH.brand400, opacity: 0.4 },
        },
      ],
    };
  }, [chart.data, priceMode]);

  if (state === 'loading') {
    return <SkeletonCard className="mt-6 h-96" />;
  }
  if (state === 'error' || !overview.data) {
    return (
      <EmptyState
        variant="error"
        title={t('加载失败')}
        description={String(overview.error?.message ?? '')}
        className="mt-12"
      />
    );
  }

  const data = overview.data;
  const security = data.security;

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <header className="border-b border-line pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-brand-50 px-2 py-1 font-mono text-h3 font-bold text-brand-700">
            {security.display_code}
          </span>
          <h1 className="font-display text-display-m text-ink-900">{security.name_ja ?? security.name_en ?? '—'}</h1>
          {security.active === 0 && (
            <span className="rounded-sm bg-down-50 px-1.5 py-0.5 text-micro text-down-700">上場廃止 {security.delisted_date ?? ''}</span>
          )}
          {isOwner && (
            <button
              type="button"
              className="ml-auto rounded-md border border-line bg-card px-2.5 py-1 text-caption text-ink-600 hover:bg-brand-50"
              onClick={async () => {
                try {
                  const result = await watchlistApi.add(security.canonical_code);
                  setWatchNote(result.created ? '✓' : '★');
                } catch {
                  setWatchNote('—');
                }
              }}
            >
              {watchNote ?? `+ ${t('加入自选')}`}
            </button>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-ink-500">
          <span>{security.market_name ?? '—'}</span>
          <span>{security.sector33_name ?? '—'}</span>
          {security.scale_category && <span>{security.scale_category}</span>}
          {security.margin_name && <span>{security.margin_name}</span>}
          <span>{security.name_en ?? ''}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-4">
          <span className="font-mono text-display-l tnum text-ink-900">{fmtPrice(data.quote.close)}</span>
          <ChangeBadge value={data.quote.change_pct} />
          <span className="text-body-s text-ink-500">
            {t('成交额')} <span className="font-mono tnum">{fmtYenCompact(data.quote.turnover_value)}</span>
          </span>
          <DataThrough date={data.quote.trade_date} className="ml-auto" />
        </div>
      </header>

      {/* チャート */}
      <section className="card-surface rounded-lg p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <Segmented<Range>
            options={(['3m', '6m', '1y', '3y', '10y'] as Range[]).map((value) => ({ value, label: value.toUpperCase() }))}
            value={range}
            onChange={setRange}
          />
          <Segmented<PriceMode>
            options={[
              { value: 'adjusted', label: t('复权') },
              { value: 'raw', label: t('不复权') },
            ]}
            value={priceMode}
            onChange={setPriceMode}
          />
        </div>
        {chartOption ? (
          <ReactECharts className="h-80 w-full" option={chartOption} ariaLabel={`${security.display_code} chart`} />
        ) : chart.loading ? (
          <SkeletonCard className="h-80" />
        ) : (
          <EmptyState title={t('暂无数据')} />
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* 財務 */}
        <section className="card-surface rounded-lg p-4">
          <h2 className="mb-3 text-h3 text-ink-900">{t('决算时间线')}</h2>
          <FinancialTable summaries={data.financials.summaries} />
        </section>

        {/* レーダー + 信用 + 空売り */}
        <div className="space-y-6">
          <section className="card-surface rounded-lg p-4">
            <h2 className="mb-3 text-h3 text-ink-900">{t('突破雷达')}</h2>
            {data.radar_events.length === 0 ? (
              <p className="text-body-s text-ink-400">{t('暂无相关雷达事件')}</p>
            ) : (
              <ul className="divide-y divide-line">
                {data.radar_events.slice(0, 5).map((event) => (
                  <li key={event.event_id} className="flex items-center gap-2 py-2">
                    <SignalChip signal={event.signal_type} />
                    <StateChip state={event.state} />
                    <span className="ml-auto text-caption text-ink-500">
                      {fmtDate(event.discovered_date)} · {t('枢轴价')} {fmtPrice(event.pivot_price)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card-surface rounded-lg p-4">
            <h2 className="mb-3 text-h3 text-ink-900">{t('信用交易')}</h2>
            <MarginPanel rows={data.margin_interest} />
          </section>

          <section className="card-surface rounded-lg p-4">
            <h2 className="mb-3 text-h3 text-ink-900">{t('空卖残高报告')}</h2>
            <ShortPositionsPanel rows={data.short_positions} />
          </section>
        </div>
      </div>
    </div>
  );
}

function FinancialTable({ summaries }: { summaries: FinancialSummaryView[] }) {
  const columns: Column<FinancialSummaryView>[] = [
    {
      key: 'date',
      title: t('发表预定'),
      width: '104px',
      render: (row) => <span className="font-mono text-caption tnum text-ink-700">{fmtDate(row.disclosed_date)}</span>,
    },
    {
      key: 'period',
      title: t('决算种别'),
      render: (row) => (
        <span className="flex items-center gap-1">
          <span className="rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">
            {row.fiscal_year_end?.slice(0, 7) ?? '—'} {row.period_type ?? ''}
          </span>
          <span className="text-micro text-ink-400">{row.is_consolidated ? t('连结') : t('单体')}</span>
        </span>
      ),
    },
    {
      key: 'sales',
      title: t('销售额'),
      align: 'right',
      render: (row) => <span className="font-mono text-caption tnum">{fmtYenCompact(row.sales ?? row.nc_sales)}</span>,
    },
    {
      key: 'op',
      title: t('营业利益'),
      align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum">{fmtYenCompact(row.operating_profit ?? row.nc_operating_profit)}</span>
      ),
    },
    {
      key: 'np',
      title: t('纯利益'),
      align: 'right',
      render: (row) => <span className="font-mono text-caption tnum">{fmtYenCompact(row.net_profit)}</span>,
    },
    {
      key: 'eps',
      title: 'EPS',
      align: 'right',
      render: (row) => <span className="font-mono text-caption tnum">{row.eps !== null ? row.eps.toFixed(1) : '—'}</span>,
    },
    {
      key: 'forecast',
      title: `${t('会社预想')}·OP`,
      align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum text-ink-500">{fmtYenCompact(row.forecast_operating_profit)}</span>
      ),
    },
  ];
  if (summaries.length === 0) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  return (
    <DataTable columns={columns} rows={summaries} rowKey={(row) => `${row.disclosed_date}-${row.disclosure_number}`} rowHeight={44} />
  );
}

function MarginPanel({ rows }: { rows: MarginInterestRow[] }) {
  if (rows.length === 0) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  const latest = rows[rows.length - 1];
  const ratio =
    latest.long_total !== null && latest.short_total !== null && latest.short_total > 0
      ? latest.long_total / latest.short_total
      : null;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2 text-center">
        <MiniStat label={t('信用买残')} value={fmtYenCompact(latest.long_total)} />
        <MiniStat label={t('信用卖残')} value={fmtYenCompact(latest.short_total)} />
        <MiniStat label={t('信用倍率')} value={ratio !== null ? `${ratio.toFixed(2)}x` : '—'} />
      </div>
      <p className="text-right text-micro text-ink-400">
        {t('数据截至')} {fmtDate(latest.application_date)}（週次）
      </p>
    </div>
  );
}

function ShortPositionsPanel({ rows }: { rows: ShortPositionRow[] }) {
  if (rows.length === 0) return <p className="text-body-s text-ink-400">{t('暂无数据')}</p>;
  return (
    <ul className="divide-y divide-line">
      {rows.slice(0, 5).map((row, index) => (
        <li key={index} className="flex items-center justify-between gap-2 py-1.5 text-body-s">
          <span className="min-w-0 truncate text-ink-700">{row.holder_name ?? '—'}</span>
          <span className="shrink-0 font-mono tnum text-ink-900">{fmtPct(row.short_position_ratio, 2)}</span>
          <span className="shrink-0 text-micro text-ink-400">{fmtDate(row.calculated_date)}</span>
        </li>
      ))}
    </ul>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-paper-2 py-2">
      <div className="font-mono text-data-m tnum text-ink-900">{value}</div>
      <div className="text-micro text-ink-400">{label}</div>
    </div>
  );
}
