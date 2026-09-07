/** HatchLegend：实心=本次命中 / 斜纹=参照母体（对标美站 §6-3）。 */
import { cn } from '@/lib/utils';
import { t } from '@/i18n/core';

export default function HatchLegend({
  className,
  actual = t('本次命中'),
  estimate = t('全市场参照'),
}: {
  className?: string;
  actual?: string;
  estimate?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-3 text-micro text-ink-400', className)}>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block size-2.5 rounded-[2px] bg-brand-600" aria-hidden="true" />
        {actual}
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block size-2.5 rounded-[2px] border border-brand-400"
          style={{ backgroundImage: 'repeating-linear-gradient(45deg, rgba(46,70,224,.55) 0 1.2px, transparent 1.2px 4px)' }}
          aria-hidden="true"
        />
        {estimate}
      </span>
    </span>
  );
}
