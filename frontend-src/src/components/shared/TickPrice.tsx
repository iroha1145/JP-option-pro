import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/** 报价数字：涨跌变动时走 tick-flash（与美站 LiveQuote / ResultTable 同口径）。 */
export default function TickPrice({
  flash,
  className,
  children,
}: {
  flash?: 'up' | 'down' | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      data-tick-price={flash ?? 'none'}
      className={cn(
        'tick-flash inline-block rounded-xs px-1 font-mono tnum',
        flash === 'up' && 'tick-flash-up',
        flash === 'down' && 'tick-flash-down',
        className,
      )}
    >
      {children}
    </span>
  );
}
