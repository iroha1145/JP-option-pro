/**
 * 板块最热门个股 — 美版「板块 IV 横截面排名」的日股替代。
 * 日股无期权链，热度改用真实可得的三个口径：成交额 / 量比（20日均额倍数）/ 当日涨幅。
 * 份额条 = 该股占本业种当日成交额的比例（这一栏才是「多热」的直接答案）。
 */
import { cn } from '@/lib/utils';
import { fmtPrice, fmtYenCompact } from '@/lib/format';
import ChangeBadge from '@/components/shared/ChangeBadge';
import Segmented from '@/components/shared/Segmented';
import EmptyState from '@/components/shared/EmptyState';
import SourceNote from '@/components/shared/SourceNote';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, StateChip } from '@/components/domain';
import { t } from '@/i18n/core';
import type { IntradayQuote, SectorMembersView, SectorMemberSort } from '@/api/types';

/* 列模板は見出し行と本体行の両方に必ず渡すこと（片方だけだと行が 1 列に潰れる） */
const ROW_GRID =
  'md:grid-cols-[22px_minmax(150px,1.5fr)_minmax(120px,1.1fr)_96px_92px_76px]';

const SORT_OPTIONS: { value: SectorMemberSort; label: string }[] = [
  { value: 'turnover', label: t('成交额') },
  { value: 'heat', label: t('量比') },
  { value: 'change', label: t('涨幅') },
];

export default function SectorMembersPanel({
  data,
  loading,
  sort,
  onSortChange,
  liveQuotes,
  delayedMinutes,
}: {
  data: SectorMembersView | null;
  loading: boolean;
  sort: SectorMemberSort;
  onSortChange: (sort: SectorMemberSort) => void;
  /** 遅延気配（非公式）。無い銘柄は公式終値のまま出す —— 埋めない。 */
  liveQuotes?: Record<string, IntradayQuote>;
  delayedMinutes?: number | null;
}) {
  const hasLive = Boolean(liveQuotes && Object.keys(liveQuotes).length);
  const rows = data?.rows ?? [];
  return (
    <section className="card-surface p-4 md:p-5" aria-label={t('板块最热门个股')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="eyebrow">{t('板块最热门个股')}</p>
          <h2 className="mt-0.5 truncate text-h3 text-ink-900">
            {data?.sector33_name ?? '—'}
            {data && (
              <span className="ml-2 font-mono text-caption font-normal text-ink-400 tnum">
                {t('{n} 只', { n: data.member_count })} · {fmtYenCompact(data.sector_turnover_value)}
              </span>
            )}
          </h2>
        </div>
        <Segmented options={SORT_OPTIONS} value={sort} onChange={onSortChange} />
      </div>

      {loading && !data ? (
        <div className="mt-3">
          <SkeletonRows rows={6} />
        </div>
      ) : rows.length === 0 ? (
        <div className="mt-3">
          <EmptyState title={t('暂无数据')} description={t('该业种在当前断面没有可用个股')} />
        </div>
      ) : (
        <>
          <div className={cn('mt-3 hidden border-b border-line pb-1.5 md:grid md:gap-3', ROW_GRID)}>
            <span className="eyebrow">#</span>
            <span className="eyebrow">{t('代码')}</span>
            <span className="eyebrow">{t('成交额份额')}</span>
            <span className="eyebrow text-right">{t('收盘')}</span>
            <span className="eyebrow text-right">{t('成交额')}</span>
            <span className="eyebrow text-right">{t('近20日')}</span>
          </div>
          <ol className="md:mt-1">
            {rows.map((row, index) => (
              <li key={row.canonical_code}>
                <span
                  className={cn(
                    'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-1.5 py-2 transition-colors hover:bg-paper-2 md:grid md:gap-3',
                    ROW_GRID,
                  )}
                >
                  <span className="font-mono text-micro text-ink-300 tnum">{index + 1}</span>
                  <span className="flex min-w-0 items-center gap-1.5">
                    <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />
                    {row.radar_state && <StateChip state={row.radar_state} />}
                  </span>
                  {/* 份额条：本业种当日成交额里这只股占多少（「多热」的直接答案） */}
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="h-[4px] min-w-0 flex-1 overflow-hidden rounded-pill bg-line" aria-hidden="true">
                      <span
                        className="block h-full rounded-pill bg-brand-500"
                        style={{ width: `${Math.max(2, Math.min(100, (row.turnover_share ?? 0) * 100))}%` }}
                      />
                    </span>
                    <span className="w-10 shrink-0 text-right font-mono text-micro text-ink-500 tnum">
                      {/* 份额是占比不是涨跌 —— 不能用 fmtPct（会带 +/− 符号） */}
                      {row.turnover_share != null ? `${(row.turnover_share * 100).toFixed(1)}%` : '—'}
                    </span>
                  </span>
                  <span className="text-right">
                    {liveQuotes?.[row.canonical_code] ? (
                      <>
                        <span className="block font-mono text-body-s tnum text-ink-900">
                          {fmtPrice(liveQuotes[row.canonical_code].price)}
                          <span className="ml-1 text-micro text-warn-700" title={t('延迟盘中价')}>●</span>
                        </span>
                        <ChangeBadge value={liveQuotes[row.canonical_code].change_pct} size="sm" />
                      </>
                    ) : (
                      <>
                        <span className="block font-mono text-body-s text-ink-900 tnum">{fmtPrice(row.close)}</span>
                        <ChangeBadge value={row.return_1d} size="sm" />
                      </>
                    )}
                  </span>
                  <span className="text-right">
                    <span className="block font-mono text-caption text-ink-700 tnum">
                      {fmtYenCompact(row.turnover_value)}
                    </span>
                    <span
                      className={cn(
                        'block font-mono text-micro tnum',
                        (row.turnover_ratio ?? 0) >= 2 ? 'font-semibold text-warn-700' : 'text-ink-400',
                      )}
                      title={t('量比=当日成交额/20日均额')}
                    >
                      {row.turnover_ratio != null ? `${row.turnover_ratio.toFixed(1)}x` : '—'}
                    </span>
                  </span>
                  <span className="text-right">
                    <ChangeBadge value={row.return_20d} size="sm" />
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
      <SourceNote
        className="mt-3"
        text={
          hasLive
            ? t('● = 延迟{n}分盘中价（非官方源）· 其余为 J-Quants 官方日线 · 量比=当日成交额/20日均额', {
                n: delayedMinutes ?? 15,
              })
            : t('量比=当日成交额/20日均额 · 份额=占本业种当日成交额比重')
        }
      />
    </section>
  );
}
