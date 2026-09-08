import Icon from '@/components/icons';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';

/** 页头强制刷新：shadow-btn + animate-spin-once（一次旋转，不是无限转圈）。 */
export default function ForceRefreshButton({
  onClick,
  spinning,
  label,
  busyLabel,
  title,
  disabled,
  testId,
}: {
  onClick: () => void;
  spinning?: boolean;
  label?: string;
  busyLabel?: string;
  title?: string;
  disabled?: boolean;
  testId?: string;
}) {
  const blocked = Boolean(disabled || spinning);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={blocked}
      title={title}
      data-testid={testId}
      className={cn(
        'flex h-9 items-center gap-2 rounded-md border px-3 text-caption shadow-btn transition-colors duration-fast',
        blocked
          ? 'cursor-not-allowed border-line bg-card-warm text-ink-300'
          : 'border-line bg-card text-ink-600 hover:border-brand-400 hover:text-brand-600',
      )}
    >
      <Icon name="refresh" size={15} className={spinning ? 'animate-spin-once' : ''} />
      {spinning ? (busyLabel ?? t('刷新中')) : (label ?? t('强制刷新'))}
    </button>
  );
}
