/**
 * 板块透视热力砖 — 对标美版 sectors/HeatMatrix。
 * 一块砖同时承载：当日中位涨跌 · 近20日中位涨跌 · 今日领涨（美版此处是 IV）。
 * 底色按所选口径连续映射（红涨绿跌）；缺数用虚线中性砖，绝不与「真持平」同色。
 */
import { cn } from '@/lib/utils';
import { fmtPct } from '@/lib/format';
import { heatColor } from '@/lib/chart';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import { t } from '@/i18n/core';
import type { SectorStrength } from '@/api/types';

export type HeatMetric = 'r1' | 'r20';

const GRID_CLASS = 'grid grid-cols-2 gap-2.5 md:grid-cols-4 md:gap-3 xl:grid-cols-6';

export function metricValue(sector: SectorStrength, metric: HeatMetric): number | null {
  return metric === 'r1' ? sector.median_return_1d : sector.median_return_20d;
}

/** 砖底色与文字明暗（明度阈值决定压白字还是墨字） */
function tone(value: number | null): { bg: string; dark: boolean } {
  if (value === null) return { bg: 'var(--card-warm, #FBFCFD)', dark: false };
  const bg = heatColor(value * 100);
  const match = bg.match(/rgb\((\d+),(\d+),(\d+)\)/);
  if (!match) return { bg, dark: false };
  const [r, g, b] = [Number(match[1]), Number(match[2]), Number(match[3])];
  return { bg, dark: (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.62 };
}

function HeatTile({
  sector,
  metric,
  selected,
  onSelect,
}: {
  sector: SectorStrength;
  metric: HeatMetric;
  selected: boolean;
  onSelect: () => void;
}) {
  const primary = metricValue(sector, metric);
  const secondary = metric === 'r1' ? sector.median_return_20d : sector.median_return_1d;
  const secondaryLabel = metric === 'r1' ? t('近20日') : t('当日');
  const { bg, dark } = tone(primary);
  const leader = sector.leaders[0] ?? null;
  const textMain = dark ? 'text-white' : 'text-ink-800';
  const textSub = dark ? 'text-white/75' : 'text-ink-500';
  const chipClass = dark ? 'bg-white/20 text-white' : 'bg-ink-900/[0.06] text-ink-600';

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={t('{name}，当日 {r1}，近20日 {r20}', {
        name: sector.sector33_name,
        r1: fmtPct(sector.median_return_1d),
        r20: fmtPct(sector.median_return_20d),
      })}
      className={cn(
        'group relative overflow-hidden rounded-md p-3 text-left shadow-sh-1 transition-[box-shadow,transform] duration-fast hover:-translate-y-0.5 hover:shadow-sh-2',
        primary === null && 'border border-dashed border-line-strong',
        selected && 'ring-2 ring-brand-600 ring-offset-1',
      )}
      style={{ backgroundColor: bg }}
    >
      <span className="flex items-start justify-between gap-1.5">
        <span className={cn('min-w-0 truncate text-[13px] font-semibold leading-[18px]', textMain)}>
          {sector.sector33_name}
        </span>
        <span className={cn('shrink-0 font-mono text-micro tnum', textSub)}>{sector.member_count}</span>
      </span>

      <span className={cn('mt-1.5 block font-mono text-[15px] font-semibold leading-5 tnum', textMain)}>
        {fmtPct(primary)}
      </span>
      <span className={cn('block font-mono text-micro tnum', textSub)}>
        {secondaryLabel} {fmtPct(secondary)}
      </span>

      {/* 美版此处是 IV —— 日股无期权，改为今日领涨 */}
      <span className={cn('mt-1.5 flex items-center gap-1 rounded-sm px-1 py-0.5 text-micro', chipClass)}>
        {leader ? (
          <>
            <span className="font-mono font-semibold">{leader.canonical_code.replace(/0$/, '')}</span>
            <span className="min-w-0 flex-1 truncate">{leader.name_ja ?? ''}</span>
            <span className="font-mono tnum">{fmtPct(leader.return_1d)}</span>
          </>
        ) : (
          <span className="truncate">{t('无领涨数据')}</span>
        )}
      </span>
    </button>
  );
}

export default function HeatMatrix({
  sectors,
  metric,
  selectedCode,
  onSelect,
}: {
  sectors: SectorStrength[];
  metric: HeatMetric;
  selectedCode: string | null;
  onSelect: (code: string) => void;
}) {
  return (
    <div className={GRID_CLASS} role="list" aria-label={t('板块透视')}>
      {sectors.map((sector) => (
        <span key={sector.sector33_code} role="listitem" className="contents">
          <HeatTile
            sector={sector}
            metric={metric}
            selected={selectedCode === sector.sector33_code}
            onSelect={() => onSelect(sector.sector33_code)}
          />
        </span>
      ))}
    </div>
  );
}

export function HeatMatrixSkeleton() {
  return (
    <div className={GRID_CLASS} aria-hidden="true">
      {Array.from({ length: 12 }, (_, index) => (
        <SkeletonBlock key={index} className="h-[104px] rounded-md" />
      ))}
    </div>
  );
}
