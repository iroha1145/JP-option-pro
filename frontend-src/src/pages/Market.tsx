/** 日本市场页：指数走势 + 全部33业种强弱 + 广度与空卖。 */

import { useEffect, useMemo, useState } from 'react';
import { marketApi, stocksApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import DataTable, { type Column } from '@/components/shared/DataTable';
import Segmented from '@/components/shared/Segmented';
import { SkeletonCard } from '@/components/shared/Skeleton';
import InsightLineChart, { insightStroke, insightTone, type InsightScrub } from '@/components/charts/InsightLineChart';
import { CodeCell, DataThrough } from '@/components/domain';
import HeatMatrix, { HeatMatrixSkeleton, metricValue, type HeatMetric } from '@/components/sectors/HeatMatrix';
import SectorMembersPanel from '@/components/sectors/SectorMembersPanel';
import { t } from '@/i18n/core';
import { quoteSourceLabel } from '@/lib/quoteSource';
import { fmtPct, fmtPrice, fmtTimeJst, fmtYenCompact } from '@/lib/format';
import type { IntradayQuote, SectorMemberSort, SectorStrength } from '@/api/types';

export default function Market() {
  const market = usePolling(() => marketApi.overview(), 120_000);
  const [indexCode, setIndexCode] = useState('0000');
  const series = usePolling(() => marketApi.indexSeries(indexCode, 250), null, [indexCode]);
  const state = remoteState(market, (d) => d.indices.length === 0);

  const [heatMetric, setHeatMetric] = useState<HeatMetric>('r1');
  const [sectorView, setSectorView] = useState<'heat' | 'list'>('heat');
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [memberSort, setMemberSort] = useState<SectorMemberSort>('turnover');
  const [tileSource, setTileSource] = useState<'official' | 'intraday'>('intraday');

  /* 業種断面のザラ場版: 全 1,587 銘柄を 80 バッチで撫でて中央値を作る。
     遅延 15 分なので 3 分ポーリング（それ以上速くしても新しい値は出ない）。 */
  const liveSectors = usePolling(
    () => (tileSource === 'intraday' ? marketApi.intradaySectors() : Promise.resolve(null)),
    180_000,
    [tileSource],
  );

  /* 砖块按当前口径排序：热力图第一眼要看到最强/最弱聚在两端。
     ザラ場口径のときは遅延気配から作った 1 日騰落で差し替える（20 日は
     公式日足のまま —— 20 日リターンはザラ場気配からは作れない）。 */
  const liveByCode = useMemo(() => {
    const map = new Map<string, { median_return_1d: number; advancers_share: number }>();
    for (const row of liveSectors.data?.sectors ?? []) map.set(row.sector33_code, row);
    return map;
  }, [liveSectors.data]);

  const sectorsSorted = useMemo(() => {
    const base = market.data?.sectors ?? [];
    const rows = tileSource === 'intraday' && liveByCode.size
      ? base.map((row) => {
          const live = liveByCode.get(row.sector33_code);
          return live
            ? { ...row, median_return_1d: live.median_return_1d, advancers_share: live.advancers_share }
            : row;
        })
      : base;
    return [...rows].sort((a, b) => {
      const va = metricValue(a, heatMetric);
      const vb = metricValue(b, heatMetric);
      if (va === null) return 1;
      if (vb === null) return -1;
      return vb - va;
    });
  }, [market.data, heatMetric, tileSource, liveByCode]);

  /* 未选板块时默认落在当前口径最强的那个（面板永远有内容，不是空壳） */
  useEffect(() => {
    if (selectedSector === null && sectorsSorted.length > 0) {
      setSelectedSector(sectorsSorted[0].sector33_code);
    }
  }, [selectedSector, sectorsSorted]);

  const members = usePolling(
    () =>
      selectedSector
        ? marketApi.sectorMembers(selectedSector, memberSort)
        : Promise.resolve(null),
    null,
    [selectedSector, memberSort],
  );

  /* 遅延気配は 1 分ポーリング。銘柄は表示中の 12 件だけ（業種タイルの裏には
     1,587 銘柄いるので、そこはザラ場化できない —— 公式日足のまま据え置く）。 */
  const memberCodes = useMemo(
    () => (members.data?.rows ?? []).map((row) => row.display_code),
    [members.data],
  );
  const live = usePolling(
    () => stocksApi.intradayQuotes(memberCodes),
    60_000,
    [memberCodes.join(',')],
  );
  const liveQuotes: Record<string, IntradayQuote> = live.data?.enabled ? live.data.quotes : {};
  const n225 = live.data?.enabled ? (live.data.indices?.['^N225'] ?? null) : null;

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
      title: t('近1日'),
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
          {n225 && (
            <section className="card-surface flex flex-wrap items-end justify-between gap-3 rounded-lg p-4">
              <span className="flex flex-col">
                <span className="eyebrow">{t('日経225 · 盘中')}</span>
                <span className="mt-1 flex items-baseline gap-3">
                  <span className="font-mono text-display-m tnum text-ink-900">
                    {n225.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </span>
                  <ChangeBadge value={n225.change_pct} />
                </span>
              </span>
              <span className="flex items-center gap-1 text-micro text-warn-700">
                <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                {quoteSourceLabel(live.data).text}
                {n225.as_of_epoch ? ` · ${fmtTimeJst(n225.as_of_epoch)}` : ''}
              </span>
            </section>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <IndexTrendPanel
              name={series.data?.name ?? t('指数')}
              seriesCode={series.data?.index_code ?? indexCode}
              indexCode={indexCode}
              onIndexChange={setIndexCode}
              options={(market.data?.indices ?? []).slice(0, 4).map((index) => ({
                value: index.index_code,
                label: index.name.replace('東証', '').replace('市場指数', ''),
              }))}
              bars={series.data?.bars ?? []}
              loading={series.loading && !series.data}
              changePct={
                market.data?.indices.find((index) => index.index_code === indexCode)?.change_pct ?? null
              }
              compareName={
                market.data?.indices.find((index) => index.index_code === (indexCode === '0000' ? '0500' : '0000'))
                  ?.name
              }
            />

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
                  <span className="flex items-center gap-3">
                    <span className="w-[88px] shrink-0">
                      <InsightLineChart
                        data={index.sparkline}
                        height={32}
                        change={index.change_pct ?? 0}
                        interactive={false}
                        showLiveDot
                        ariaLabel={`${index.name} ${t('趋势快照')}`}
                      />
                    </span>
                    <span className="flex flex-col items-end gap-0.5">
                      <ChangeBadge value={index.change_pct} size="sm" />
                      <span className="text-micro text-ink-400">
                        {t('20日')} {fmtPct(index.return_20d)}
                      </span>
                      <span className="block text-micro text-ink-300">
                        {index.trade_date ?? '—'} {t('收盘')}
                      </span>
                    </span>
                  </span>
                </button>
              ))}
            </section>
          </div>

          {/* 板块透视：热力砖（当日/近20日/今日领涨同砖）+ 列表视图 */}
          <section className="card-surface rounded-lg p-4">
            <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="eyebrow">{t('SECTOR MATRIX · 33 業種')}</p>
                <h2 className="mt-0.5 text-h3 text-ink-900">{t('板块透视')}</h2>
                <p className="mt-0.5 text-micro text-ink-400">
                  {tileSource === 'intraday' && liveByCode.size
                    ? t('1日=盘中延迟{n}分（{q}/{u} 只覆盖）· 20日=官方日线 {date}', {
                        n: liveSectors.data?.delayed_minutes ?? 15,
                        q: liveSectors.data?.quoted ?? 0,
                        u: liveSectors.data?.universe ?? 0,
                        date: market.data?.data_through ?? '—',
                      })
                    : t('业种断面 · J-Quants 官方日线 {date} 收盘（盘中不更新）', {
                        date: market.data?.data_through ?? '—',
                      })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="hidden text-caption text-ink-400 lg:inline">
                  {t('成交额')}: {fmtYenCompact(market.data?.breadth.total_turnover_value)} ·{' '}
                  {t('上涨')} {market.data?.breadth.advancers ?? '—'} / {t('下跌')}{' '}
                  {market.data?.breadth.decliners ?? '—'}
                </span>
                <Segmented<HeatMetric>
                  options={[
                    { value: 'r1', label: t('1日') },
                    { value: 'r20', label: t('20日') },
                  ]}
                  value={heatMetric}
                  onChange={setHeatMetric}
                />
                <Segmented<'official' | 'intraday'>
                  options={[
                    { value: 'intraday', label: t('盘中') },
                    { value: 'official', label: t('官方收盘') },
                  ]}
                  value={tileSource}
                  onChange={setTileSource}
                />
                <Segmented<'heat' | 'list'>
                  options={[
                    { value: 'heat', label: t('热力') },
                    { value: 'list', label: t('列表') },
                  ]}
                  value={sectorView}
                  onChange={setSectorView}
                />
              </div>
            </header>

            {sectorsSorted.length === 0 ? (
              <HeatMatrixSkeleton />
            ) : sectorView === 'heat' ? (
              <HeatMatrix
                sectors={sectorsSorted}
                metric={heatMetric}
                selectedCode={selectedSector}
                onSelect={setSelectedSector}
              />
            ) : (
              <DataTable
                columns={sectorColumns}
                rows={sectorsSorted}
                rowKey={(row) => row.sector33_code}
                rowHeight={44}
                defaultSort={{ key: heatMetric === 'r1' ? 'r1' : 'r20', desc: true }}
                onRowClick={(row) => setSelectedSector(row.sector33_code)}
              />
            )}
          </section>

          {/* 该板块最热门个股（美版此处是板块 IV 横截面排名） */}
          <SectorMembersPanel
            data={members.data ?? null}
            loading={members.loading}
            sort={memberSort}
            onSortChange={setMemberSort}
            liveQuotes={liveQuotes}
            delayedMinutes={live.data?.delayed_minutes ?? null}
          />
        </>
      )}
    </div>
  );
}

function IndexTrendPanel({
  name,
  seriesCode,
  indexCode,
  onIndexChange,
  options,
  bars,
  loading,
  changePct,
  compareName,
}: {
  name: string;
  seriesCode: string;
  indexCode: string;
  onIndexChange: (code: string) => void;
  options: { value: string; label: string }[];
  bars: { trade_date: string; close: number | null }[];
  loading: boolean;
  changePct: number | null;
  compareName?: string;
}) {
  const compareCode = indexCode === '0000' ? '0500' : '0000';
  const compare = usePolling(() => marketApi.indexSeries(compareCode, 250), null, [compareCode]);
  const [scrub, setScrub] = useState<InsightScrub | null>(null);
  const points = useMemo(
    () =>
      bars
        .filter((bar): bar is { trade_date: string; close: number } => bar.close != null && Number.isFinite(bar.close))
        .map((bar) => ({ value: bar.close, label: bar.trade_date })),
    [bars],
  );
  const comparePoints = useMemo(
    () =>
      (compare.data?.bars ?? [])
        .filter((bar): bar is { trade_date: string; close: number } => bar.close != null && Number.isFinite(bar.close))
        .map((bar) => ({ value: bar.close, label: bar.trade_date })),
    [compare.data],
  );
  const last = points[points.length - 1];
  const shown = scrub ?? (last ? { index: points.length - 1, value: last.value, label: last.label, x: 0, y: 0 } : null);
  const badgeValue = useMemo(() => {
    if (!scrub || points.length < 2) return changePct;
    const prev = points[Math.max(0, scrub.index - 1)];
    if (!prev || prev.value === 0) return changePct;
    return (scrub.value - prev.value) / prev.value;
  }, [scrub, points, changePct]);

  return (
    <section className="card-surface flex flex-col overflow-hidden rounded-xl p-0 lg:col-span-2">
      <header className="flex items-center justify-between gap-3 px-4 pt-3">
        <h2 className="text-body text-ink-500">{t('趋势快照')}</h2>
        <span className="rounded-full bg-paper-2 px-2.5 py-0.5 text-micro text-ink-500">{t('快照')}</span>
      </header>
      <div className="mt-3 border-t border-line px-4 pt-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex size-6 items-center justify-center rounded-md bg-paper-2" title={name} aria-label={name}>
              <i className="block size-1.5 rounded-full" style={{ background: insightStroke(insightTone(changePct ?? 0)) }} />
            </span>
            <span
              className="inline-flex size-6 items-center justify-center rounded-md bg-paper-2"
              title={compareName ?? t('对照')}
              aria-label={compareName ?? t('对照')}
            >
              <i className="block size-1.5 rounded-full" style={{ background: 'var(--brand-600)' }} />
            </span>
          </div>
          <Segmented options={options} value={indexCode} onChange={onIndexChange} />
        </div>
        {loading ? (
          <SkeletonCard className="h-64" />
        ) : points.length === 0 ? (
          <EmptyState title={t('暂无数据')} />
        ) : (
          <InsightLineChart
            key={seriesCode}
            data={points}
            compare={comparePoints}
            height={228}
            change={changePct ?? 0}
            interactive
            showLiveDot
            showCursorValue
            showGrid
            showAxis
            formatValue={(value) => fmtPrice(value)}
            onScrub={setScrub}
            ariaLabel={`${name} ${t('趋势快照')}`}
          />
        )}
      </div>
      <div className="flex items-baseline justify-between gap-3 px-4 pb-4 pt-2">
        <div>
          <p className="font-mono text-data-xl tnum text-ink-900">{fmtPrice(shown?.value)}</p>
          <p className="mt-0.5 text-micro text-ink-400">
            {shown?.label ?? '—'} · {t('收盘')}
          </p>
        </div>
        <span className="flex items-center gap-1.5">
          <ChangeBadge value={badgeValue} />
          <span className="text-micro text-ink-400">{t('vs {n}日', { n: points.length || 1 })}</span>
        </span>
      </div>
    </section>
  );
}
