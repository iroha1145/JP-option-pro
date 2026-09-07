/**
 * Insight Cards 卡片语言落到 Paper Terminal：
 * 大数值 + 涨跌徽标 + 绝对变动 + 比较基准。
 */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { fmtPrice } from '@/lib/format';
import ChangeBadge from '@/components/shared/ChangeBadge';
import SoftBadge from '@/components/shared/SoftBadge';
import { toneOf } from '@/lib/insightTone';

export function InsightValue({
  value,
  suffix,
  changePct,
  change,
  basis,
  size = 'md',
  className,
}: {
  value: ReactNode;
  suffix?: string;
  changePct?: number | null;
  change?: number | null;
  basis?: string;
  size?: 'md' | 'xl';
  className?: string;
}) {
  const hasChange = typeof change === 'number' && Number.isFinite(change);
  const tone = toneOf(change ?? changePct);
  return (
    <div className={cn('flex flex-wrap items-baseline gap-x-2.5 gap-y-1', className)}>
      <span
        className={cn(
          'metric-value text-ink-900',
          size === 'xl' ? 'text-[clamp(30px,10vw,44px)] leading-none' : 'text-data-l leading-tight',
        )}
      >
        {value}
      </span>
      {suffix && <span className="text-body-s text-ink-500">{suffix}</span>}
      {changePct !== undefined && <ChangeBadge value={changePct} size={size === 'xl' ? 'md' : 'sm'} />}
      {hasChange && (
        <SoftBadge tone={tone === 'flat' ? 'neutral' : tone} size={size === 'xl' ? 'md' : 'sm'}>
          {change > 0 ? '+' : change < 0 ? '−' : ''}
          {fmtPrice(Math.abs(change))}
        </SoftBadge>
      )}
      {basis && <span className="text-micro text-ink-400">{basis}</span>}
    </div>
  );
}
