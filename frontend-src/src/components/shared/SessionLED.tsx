import { cn } from '@/lib/utils';
import { tokyoSessionLabel, type TokyoSession } from '@/lib/tokyoSession';
import { t } from '@/i18n/core';

const SESSION_STYLE: Record<TokyoSession, { dot: string }> = {
  pre: { dot: 'bg-warn-600' },
  morning: { dot: 'bg-up-600' },
  lunch: { dot: 'bg-ai-600' },
  afternoon: { dot: 'bg-up-600' },
  closed: { dot: 'bg-ink-400' },
};

export function SessionDot({ session, className }: { session: TokyoSession | null; className?: string }) {
  return (
    <span
      className={cn(
        'inline-block size-2 rounded-full',
        session === null ? 'bg-ink-300' : SESSION_STYLE[session].dot,
        session !== null && session !== 'closed' && 'animate-led-pulse',
        className,
      )}
      aria-hidden="true"
    />
  );
}

export default function SessionLED({
  session,
  label,
  className,
  showLabel = true,
}: {
  session: TokyoSession | null;
  label?: string;
  className?: string;
  showLabel?: boolean;
}) {
  if (session === null) {
    return (
      <span className={cn('inline-flex items-center gap-1.5', className)}>
        <SessionDot session={null} />
        {showLabel && <span className="text-caption text-ink-400">{t('时段未知')}</span>}
      </span>
    );
  }
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <SessionDot session={session} />
      {showLabel && (
        <span className="text-caption text-ink-500">{label ?? t(tokyoSessionLabel(session))}</span>
      )}
    </span>
  );
}
