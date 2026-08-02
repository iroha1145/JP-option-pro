/** 筛选器：市场区分/33业种/技术条件 → SQL 后端过滤 + 服务器分页。 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { screenerApi, watchlistApi, type ScreenerQueryBody } from '@/api/modules';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough, StateChip } from '@/components/domain';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import type { ScreenerResponse, ScreenerRow } from '@/api/types';
import { ApiError } from '@/api/client';

const PAGE_SIZE = 50;

const TURNOVER_PRESETS = [
  { label: '1億+', value: 100_000_000 },
  { label: '5億+', value: 500_000_000 },
  { label: '10億+', value: 1_000_000_000 },
  { label: '50億+', value: 5_000_000_000 },
];

export default function Screener() {
  const { isOwner } = useAccess();
  const [options, setOptions] = useState<{ markets: { code: string; name: string }[]; sectors: { code: string; name: string }[] } | null>(null);
  const [markets, setMarkets] = useState<string[]>([]);
  const [sector, setSector] = useState<string>('');
  const [minTurnover, setMinTurnover] = useState<number | undefined>(100_000_000);
  const [maAlignment, setMaAlignment] = useState(false);
  const [nearHigh, setNearHigh] = useState(false);
  const [sortBy, setSortBy] = useState('rs_topix_63d');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ScreenerResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [added, setAdded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    screenerApi.options().then(setOptions).catch(() => setOptions(null));
  }, []);

  const runQuery = useCallback(async () => {
    setLoading(true);
    setError(null);
    const body: ScreenerQueryBody = {
      markets: markets.length ? markets : undefined,
      sectors: sector ? [sector] : undefined,
      min_avg_turnover: minTurnover,
      ma_alignment: maAlignment ? true : undefined,
      // 契约: pct_from_high_252 は負値（高値からの乖離）。-5% 以内 = 高値圏。
      max_pct_from_high_252: nearHigh ? -0.05 : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
    try {
      const response = await screenerApi.query(body);
      setData(response);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setLoading(false);
    }
  }, [markets, sector, minTurnover, maAlignment, nearHigh, sortBy, sortDir, page]);

  useEffect(() => {
    void runQuery();
  }, [runQuery]);

  const columns = useMemo<Column<ScreenerRow>[]>(
    () => [
      {
        key: 'code',
        title: t('代码'),
        width: '26%',
        render: (row) => (
          <CodeCell
            displayCode={row.canonical_code.endsWith('0') && row.canonical_code.length === 5 ? row.canonical_code.slice(0, 4) : row.canonical_code}
            nameJa={row.metrics.name_ja}
            to={`/stock/${row.canonical_code}`}
          />
        ),
      },
      {
        key: 'sector',
        title: t('行业'),
        render: (row) => <span className="text-caption text-ink-500">{row.metrics.sector33_name ?? '—'}</span>,
      },
      {
        key: 'close',
        title: t('收盘'),
        align: 'right',
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.close)}</span>,
      },
      {
        key: 'r1',
        title: t('当日'),
        align: 'right',
        render: (row) => <ChangeBadge value={row.return_1d} size="sm" />,
      },
      {
        key: 'r20',
        title: t('近20日'),
        align: 'right',
        render: (row) => <ChangeBadge value={row.return_20d} size="sm" />,
      },
      {
        key: 'rs',
        title: 'RS·TOPIX',
        align: 'right',
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPct(row.rs_topix_63d)}</span>,
      },
      {
        key: 'turnover',
        title: t('成交额'),
        align: 'right',
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">{fmtYenCompact(row.avg_turnover_20d)}</span>
        ),
      },
      {
        key: 'high',
        title: t('距52周高点'),
        align: 'right',
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPct(row.pct_from_high_252)}</span>,
      },
      {
        key: 'radar',
        title: t('雷达信号'),
        render: (row) => (row.metrics.radar_state ? <StateChip state={row.metrics.radar_state} /> : <span className="text-ink-300">—</span>),
      },
      ...(isOwner
        ? [
            {
              key: 'actions',
              title: '',
              align: 'right' as const,
              render: (row: ScreenerRow) => (
                <button
                  type="button"
                  className="rounded-md border border-line px-2 py-0.5 text-micro text-ink-500 hover:bg-brand-50 hover:text-brand-700"
                  onClick={async (event) => {
                    event.stopPropagation();
                    try {
                      await watchlistApi.add(row.canonical_code);
                      setAdded((prev) => ({ ...prev, [row.canonical_code]: true }));
                    } catch {
                      /* 已在自选等情况静默 */
                    }
                  }}
                >
                  {added[row.canonical_code] ? '✓' : `+ ${t('加入自选')}`}
                </button>
              ),
            },
          ]
        : []),
    ],
    [isOwner, added],
  );

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <PageHeader
        section="04"
        eyebrow="SCREENER · CROSS-SECTION"
        title={t('筛选器')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<DataThrough date={data?.trade_date} />}
      />

      {/* フィルタ行 */}
      <div className="card-surface flex flex-wrap items-center gap-3 rounded-lg p-3">
        <FilterGroup label={t('市场区分')}>
          {(options?.markets ?? [])
            .filter((market) => ['0111', '0112', '0113'].includes(market.code))
            .map((market) => (
              <Toggle
                key={market.code}
                active={markets.includes(market.code)}
                onClick={() => {
                  setPage(0);
                  setMarkets((prev) =>
                    prev.includes(market.code) ? prev.filter((code) => code !== market.code) : [...prev, market.code],
                  );
                }}
              >
                {market.name}
              </Toggle>
            ))}
        </FilterGroup>
        <FilterGroup label={t('行业')}>
          <select
            className="rounded-md border border-line bg-card px-2 py-1 text-body-s text-ink-700"
            value={sector}
            onChange={(event) => {
              setPage(0);
              setSector(event.target.value);
            }}
          >
            <option value="">{t('全部')}</option>
            {(options?.sectors ?? []).map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </select>
        </FilterGroup>
        <FilterGroup label={t('最低日均成交额')}>
          {TURNOVER_PRESETS.map((preset) => (
            <Toggle
              key={preset.value}
              active={minTurnover === preset.value}
              onClick={() => {
                setPage(0);
                setMinTurnover(minTurnover === preset.value ? undefined : preset.value);
              }}
            >
              {preset.label}
            </Toggle>
          ))}
        </FilterGroup>
        <Toggle
          active={maAlignment}
          onClick={() => {
            setPage(0);
            setMaAlignment((v) => !v);
          }}
        >
          {t('均线多头排列')}
        </Toggle>
        <Toggle
          active={nearHigh}
          onClick={() => {
            setPage(0);
            setNearHigh((v) => !v);
          }}
        >
          {t('距52周高点')} ≤5%
        </Toggle>
        <span className="ml-auto text-caption text-ink-400">
          {t('共')} {data?.total ?? '—'} {t('条')}
        </span>
      </div>

      {loading && !data ? (
        <SkeletonRows rows={12} />
      ) : error ? (
        <EmptyState variant="error" title={t('加载失败')} description={error.message} />
      ) : data && data.rows.length === 0 ? (
        <EmptyState title={t('暂无数据')} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.rows ?? []}
            rowKey={(row) => row.canonical_code}
            rowHeight={44}
            sort={{ key: sortKeyToColumn(sortBy), desc: sortDir === 'desc' }}
            onSortChange={(next) => {
              if (!next) return;
              setPage(0);
              setSortBy(columnToSortKey(next.key));
              setSortDir(next.desc ? 'desc' : 'asc');
            }}
          />
          <div className="flex items-center justify-between text-body-s text-ink-500">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded-md border border-line px-3 py-1 disabled:opacity-40"
            >
              {t('上一页')}
            </button>
            <span className="font-mono tnum">
              {page + 1} / {totalPages}
            </span>
            <button
              type="button"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-md border border-line px-3 py-1 disabled:opacity-40"
            >
              {t('下一页')}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

const SORT_MAP: Record<string, string> = {
  rs: 'rs_topix_63d',
  r20: 'return_20d',
  r1: 'return_1d',
  turnover: 'avg_turnover_20d',
  high: 'pct_from_high_252',
  close: 'close',
};

function columnToSortKey(column: string): string {
  return SORT_MAP[column] ?? 'rs_topix_63d';
}

function sortKeyToColumn(sortKey: string): string {
  for (const [column, key] of Object.entries(SORT_MAP)) {
    if (key === sortKey) return column;
  }
  return 'rs';
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-caption text-ink-400">{label}</span>
      {children}
    </div>
  );
}

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'rounded-pill bg-brand-600 px-2.5 py-1 text-caption font-medium text-white'
          : 'rounded-pill border border-line bg-card px-2.5 py-1 text-caption text-ink-600 hover:bg-brand-50'
      }
    >
      {children}
    </button>
  );
}
