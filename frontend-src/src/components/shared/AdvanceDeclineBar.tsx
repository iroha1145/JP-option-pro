/** 涨跌宽度条：数字徽章 + 3px 比例条（对标美站 Watchlist AdvanceDeclineBar）。 */
import SoftBadge from '@/components/shared/SoftBadge';
import { t } from '@/i18n/core';

function countLabel(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '—';
}

function countValue(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0;
}

export default function AdvanceDeclineBar({
  advancers,
  decliners,
  unchanged = 0,
}: {
  advancers: number | null | undefined;
  decliners: number | null | undefined;
  unchanged?: number | null | undefined;
}) {
  const up = countValue(advancers);
  const down = countValue(decliners);
  const flat = countValue(unchanged);
  const total = Math.max(1, up + down + flat);
  return (
    <div className="mt-2">
      <p className="flex flex-wrap items-center gap-y-1 metric-value text-data-xl tnum">
        <SoftBadge tone="up" size="md" className="metric-value text-data-l">
          {countLabel(advancers)}
        </SoftBadge>
        <span className="mx-1.5 text-ink-300">/</span>
        <SoftBadge tone="down" size="md" className="metric-value text-data-l">
          {countLabel(decliners)}
        </SoftBadge>
        {flat > 0 && (
          <span className="ml-1.5 align-middle text-caption text-ink-400">
            · {flat} {t('平')}
          </span>
        )}
      </p>
      <div className="mt-2 flex h-[3px] w-full overflow-hidden rounded-pill bg-line" aria-hidden="true">
        <div className="h-full origin-left animate-grow-bar bg-up-600" style={{ width: `${(up / total) * 100}%` }} />
        <div className="h-full bg-ink-300" style={{ width: `${(flat / total) * 100}%` }} />
        <div className="h-full origin-right bg-down-600" style={{ width: `${(down / total) * 100}%` }} />
      </div>
    </div>
  );
}
