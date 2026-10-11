/** 板块透视：沿用美股版发散条排名，读数仍是日本行业的中位收益。 */
import { Fragment, useMemo, type CSSProperties } from 'react';
import { cn } from '@/lib/utils';
import { fmtPct, fmtPctLevel } from '@/lib/format';
import { CH, heatColor } from '@/lib/chart';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { useColorMode } from '@/hooks/useColorMode';
import { useAppearance } from '@/hooks/useAppearance';
import { t } from '@/i18n/core';
import type { SectorStrength } from '@/api/types';
import { metricValue, rankByReturn, returnScale, type HeatMetric } from './returnRanking';

export { rankByReturn } from './returnRanking';
export type { HeatMetric } from './returnRanking';

const ROW_GRID = 'grid grid-cols-[1rem_minmax(0,5.5rem)_minmax(0,1fr)_4.25rem] items-center gap-x-2 sm:grid-cols-[1.25rem_minmax(0,6.5rem)_minmax(0,1fr)_4.25rem] sm:gap-x-2.5 md:grid-cols-[1.5rem_minmax(0,8rem)_minmax(0,1fr)_4.5rem_6.5rem] md:gap-x-3';
const LIST_GRID = 'grid grid-cols-1 gap-y-0.5 xl:grid-flow-col xl:grid-cols-2 xl:gap-x-10 xl:[grid-template-rows:repeat(var(--heat-rows),auto)]';

function ColumnHeader({ metric, className }: { metric: HeatMetric; className?: string }) {
  return (
    <div className={cn(ROW_GRID, 'border-b border-line px-2 pb-2 text-micro text-ink-500', className)} aria-hidden="true">
      <span />
      <span>{t('行业')}</span>
      <span className="col-span-2 text-right">{metric === 'r1' ? t('1日 中位') : t('20日 中位')}</span>
      <span className="hidden md:block">{t('上涨占比')}</span>
    </div>
  );
}

function HeatRow({ sector, metric, rank, scale, covered, selected, onSelect }: {
  sector: SectorStrength;
  metric: HeatMetric;
  rank: number;
  scale: ReturnType<typeof returnScale>;
  covered?: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const value = metricValue(sector, metric);
  const hasReturn = value !== null;
  const length = hasReturn ? Math.abs(value) / scale.extent * 100 : 0;
  const share = sector.advancers_share;
  const validShare = share != null && Number.isFinite(share) && share >= 0 && share <= 1;
  const periodLabel = metric === 'r1' ? t('1日 中位') : t('20日 中位');
  const members = t('{n} 只', { n: sector.member_count });
  const coverage = covered === undefined ? null : t('盘中覆盖 {covered}/{total}', { covered, total: sector.member_count });
  const memberCaption = covered === undefined ? members : t('{n} 只', { n: `${covered}/${sector.member_count}` });
  const leader = sector.leaders[0];

  return (
    <PointerTooltip passthrough side="top" width={224} className="block min-w-0" contentClassName="p-2.5" content={
      <span className="block text-left">
        <span className="eyebrow block">{sector.sector33_name}</span>
        <span className="mt-1.5 block space-y-1 text-micro">
          <span className="flex items-center justify-between gap-2">
            <span className="text-ink-500">{t('1日 中位')}</span><span className="tnum text-ink-800">{fmtPct(sector.median_return_1d)}</span>
          </span>
          <span className="flex items-center justify-between gap-2">
            <span className="text-ink-500">{t('20日 中位')}</span><span className="tnum text-ink-800">{fmtPct(sector.median_return_20d)}</span>
          </span>
          <span className="flex items-center justify-between gap-2 border-t border-line pt-1">
            <span className="text-ink-500">{t('上涨占比')}</span><span className="tnum text-ink-800">{validShare ? fmtPctLevel(share, 0) : '—'}</span>
          </span>
          <span className="block text-ink-500">{members}{coverage ? ` · ${coverage}` : ''}</span>
          {leader && <span className="flex items-center justify-between gap-2">
            <span className="text-ink-500">{t('今日领涨')}</span>
            <span className="tnum text-ink-800">{leader.canonical_code.length === 5 && leader.canonical_code.endsWith('0') ? leader.canonical_code.slice(0, 4) : leader.canonical_code}</span>
          </span>}
        </span>
      </span>
    }>
      <button type="button" onClick={onSelect} aria-pressed={selected}
        aria-label={`${sector.sector33_name}，${periodLabel} ${fmtPct(value)}，${members}，${t('上涨占比')} ${validShare ? fmtPctLevel(share, 0) : '—'}${coverage ? `，${coverage}` : ''}`}
        className={cn(ROW_GRID, 'group relative w-full min-w-0 rounded-md px-2 py-1.5 text-left transition-colors duration-fast motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600', selected ? 'bg-brand-50' : 'hover:bg-paper-2')}>
        <span className="text-right text-caption text-ink-400 tnum">{hasReturn ? rank : '—'}</span>
        <span className="min-w-0">
          <span className={cn('block truncate text-body-s font-medium', hasReturn ? 'text-ink-800' : 'text-ink-500')}>{sector.sector33_name}</span>
          <span className="block truncate text-micro text-ink-400 tnum">{memberCaption}</span>
        </span>
        <span className="relative block h-3" aria-hidden="true">
          {hasReturn ? (
            <span className={cn('absolute inset-y-0', value >= 0 ? 'rounded-r-xs' : 'rounded-l-xs')} style={{
              left: `${value >= 0 ? scale.axis : scale.axis - length}%`, width: `${length}%`,
              // 二十日色阶放宽为±12%，一日沿用±3%；条长使用原始收益。
              backgroundColor: heatColor(value * 100 / (metric === 'r20' ? 4 : 1)),
            }} />
          ) : <span className="absolute inset-x-0 top-1/2 border-t border-dashed border-line-strong" />}
          <span className="absolute -inset-y-1 w-px bg-line-strong" style={{ left: `${scale.axis}%` }} />
        </span>
        <span className={cn('text-right text-body-s font-medium tnum', !hasReturn || value === 0 ? 'text-ink-500' : value > 0 ? 'text-up-700' : 'text-down-700')}>{fmtPct(value)}</span>
        <span className="hidden items-center gap-2 md:flex">
          <span className="relative h-1 w-12 overflow-hidden rounded-full bg-paper-2" aria-hidden="true">
            {validShare && <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${share * 100}%`, backgroundColor: CH.up600 }} />}
          </span>
          <span className="text-micro text-ink-500 tnum">{validShare ? fmtPctLevel(share, 0) : '—'}</span>
        </span>
      </button>
    </PointerTooltip>
  );
}

export default function HeatMatrix({ sectors, metric, selectedCode, onSelect, coverageByCode }: {
  sectors: SectorStrength[];
  metric: HeatMetric;
  selectedCode: string | null;
  onSelect: (code: string) => void;
  coverageByCode?: ReadonlyMap<string, { covered: number }>;
}) {
  useColorMode();
  useAppearance();
  const ranked = useMemo(() => rankByReturn(sectors, metric), [sectors, metric]);
  const scale = useMemo(() => returnScale(ranked, metric), [ranked, metric]);
  const perColumn = Math.ceil(ranked.length / 2);
  return (
    <div className={LIST_GRID} style={{ '--heat-rows': perColumn + 1 } as CSSProperties} role="group" aria-label={t('行业中位收益排名')}>
      <ColumnHeader metric={metric} />
      {ranked.map((sector, index) => (
        <Fragment key={sector.sector33_code}>
          {index === perColumn && <ColumnHeader metric={metric} className="hidden xl:grid" />}
          <HeatRow sector={sector} metric={metric} rank={index + 1} scale={scale} covered={coverageByCode?.get(sector.sector33_code)?.covered} selected={selectedCode === sector.sector33_code} onSelect={() => onSelect(sector.sector33_code)} />
        </Fragment>
      ))}
    </div>
  );
}

export function HeatMatrixSkeleton() {
  return (
    <div className={LIST_GRID} style={{ '--heat-rows': 18 } as CSSProperties} aria-hidden="true">
      <ColumnHeader metric="r1" />
      {Array.from({ length: 33 }, (_, index) => (
        <Fragment key={index}>
          {index === 17 && <ColumnHeader metric="r1" className="hidden xl:grid" />}
          <div className={cn(ROW_GRID, 'h-11 px-2')}>
            <SkeletonBlock className="h-3 w-3 justify-self-end" />
            <SkeletonBlock className="h-3.5 w-full" />
            <SkeletonBlock className="h-3 w-full" />
            <SkeletonBlock className="h-3.5 w-12 justify-self-end" />
            <SkeletonBlock className="hidden h-1 w-full md:block" />
          </div>
        </Fragment>
      ))}
    </div>
  );
}
