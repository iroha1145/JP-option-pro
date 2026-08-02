/** 页头「扫描历史」popover：最近 5 次（本会话内存，不落库）。 */
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { fmtJstTime } from '@/lib/format';
import Icon from '@/components/icons';
import type { ScanHistoryEntry } from './types';
import { t } from '@/i18n/core';

const SPRING_POP = { type: 'spring', stiffness: 520, damping: 32 } as const;

export default function ScanHistoryPopover({ history }: { history: ScanHistoryEntry[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
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
          'flex h-9 items-center gap-1.5 rounded-md border px-3 text-caption transition-colors duration-fast',
          open ? 'border-brand-400 text-brand-600' : 'border-line bg-card text-ink-500 hover:text-ink-800',
        )}
      >
        <Icon name="clock-ny" size={14} />
        {t('扫描历史')}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label={t('最近扫描记录')}
            initial={{ opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -4, transition: { duration: 0.16 } }}
            transition={SPRING_POP}
            className="absolute right-0 top-11 z-40 w-[320px] origin-top-right rounded-md border border-line bg-card p-2 shadow-sh-2"
          >
            <p className="px-2 pb-1.5 pt-1 eyebrow">{t('最近 5 次扫描')}</p>
            {history.length === 0 ? (
              <p className="px-2 py-4 text-center text-caption text-ink-400">{t('尚无扫描记录')}</p>
            ) : (
              <ul className="divide-y divide-line">
                {history.slice(0, 5).map((entry, index) => (
                  <li key={index} className="flex items-center gap-3 px-2 py-2.5">
                    <span className="font-mono text-caption text-ink-800 tnum">
                      {fmtJstTime(new Date(entry.at).toISOString())}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-micro text-ink-500" title={entry.summary}>
                      {entry.summary}
                    </span>
                    <span className="shrink-0 rounded-xs bg-brand-50 px-1.5 py-px font-mono text-micro text-brand-700 tnum">
                      {entry.count} {t('只')}
                    </span>
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
