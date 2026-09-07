/** 页头「扫描历史」popover：最近 5 次（本会话内存，不落库）。 */
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { fmtJstTime } from '@/lib/format';
import Icon from '@/components/icons';
import EmptyState from '@/components/shared/EmptyState';
import PointerTooltip from '@/components/shared/PointerTooltip';
import SoftBadge from '@/components/shared/SoftBadge';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { isTopFocusScope } from '@/lib/focusScope';
import type { ScanHistoryEntry } from './types';
import { t } from '@/i18n/core';

const SPRING_POP = { type: 'spring', stiffness: 520, damping: 32 } as const;

export default function ScanHistoryPopover({ history }: { history: ScanHistoryEntry[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  useFocusTrap(popoverRef, open);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key !== 'Escape'
        || event.defaultPrevented
        || event.isComposing
        || event.keyCode === 229
        || !isTopFocusScope(popoverRef.current)
      ) {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(
          'flex h-9 items-center gap-1.5 rounded-md border px-3 text-caption shadow-btn transition-colors duration-fast',
          open ? 'border-brand-400 text-brand-600' : 'border-line bg-card text-ink-500 hover:text-ink-800',
        )}
      >
        <Icon name="clock-ny" size={14} />
        {t('扫描历史')}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={popoverRef}
            role="dialog"
            aria-label={t('最近扫描记录')}
            initial={{ opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -4, transition: { duration: 0.16 } }}
            transition={SPRING_POP}
            className="cloud-popover absolute right-0 top-11 z-40 w-[320px] origin-top-right p-2"
          >
            <p className="px-2 pb-1.5 pt-1 eyebrow">{t('最近 5 次扫描')}</p>
            {history.length === 0 ? (
              <EmptyState size="compact" image="/empty-chart.svg" title={t('尚无扫描记录')} />
            ) : (
              <ul>
                {history.slice(0, 5).map((entry, index) => (
                  <li
                    key={index}
                    className="flex min-h-[44px] items-center gap-3 px-2 py-2.5 transition-colors duration-fast hover:bg-paper-2/70"
                  >
                    <span className="font-mono text-caption text-ink-800 tnum">
                      {fmtJstTime(new Date(entry.at).toISOString())}
                    </span>
                    <PointerTooltip
                      passthrough
                      label={entry.summary}
                      width={240}
                      contentClassName="p-2.5"
                      content={<span className="block text-micro leading-[16px] text-ink-600">{entry.summary}</span>}
                    >
                      <span className="min-w-0 flex-1 truncate text-micro text-ink-500">{entry.summary}</span>
                    </PointerTooltip>
                    <SoftBadge tone="brand" className="shrink-0 font-mono tnum">
                      {entry.count} {t('只')}
                    </SoftBadge>
                  </li>
                ))}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
