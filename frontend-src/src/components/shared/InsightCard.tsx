/**
 * Insight Cards 卡片语言落到 Paper Terminal：
 * 大数值 + 涨跌徽标 + 绝对变动 + 比较基准。
 */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { fmtPrice } from '@/lib/format';
import ChangeBadge from '@/components/shared/ChangeBadge';
import SoftBadge from '@/components/shared/SoftBadge';
import Icon from '@/components/icons';
import { toneOf, type Tone } from '@/lib/insightTone';

const TONE_TEXT: Record<Tone, string> = {
  up: 'text-up-600',
  down: 'text-down-600',
  flat: 'text-ink-400',
};

export function InsightCard({
  title,
  tone = 'flat',
  badge,
  className,
  children,
}: {
  title: string;
  tone?: Tone;
  badge?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn('card-surface p-4', className)}>
      <header className="flex items-center gap-2">
        {tone !== 'flat' && (
          <Icon
            name={tone === 'up' ? 'arrow-up-right' : 'arrow-down-right'}
            size={15}
            className={cn('shrink-0', TONE_TEXT[tone])}
          />
        )}
        <h3 className="min-w-0 truncate text-body-s font-semibold text-ink-900">{title}</h3>
        {badge && <SoftBadge className="ml-auto shrink-0">{badge}</SoftBadge>}
      </header>
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

export function InsightFrame({
  label,
  action,
  className,
  children,
}: {
  label?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn('insight-frame rounded-lg border border-line bg-card-warm p-2', className)}>
      {(label || action) && (
        <div className="mb-1 flex min-h-6 items-center gap-2 px-1">
          {label && <span className="min-w-0 truncate text-micro text-ink-400">{label}</span>}
          {action && <div className="ml-auto shrink-0">{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

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
