/** 页头「扫描历史」popover：最近 5 次（本会话内存，不落库）。 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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

  useLayoutEffect(() => {
    const anchor = ref.current;
    const panel = popoverRef.current;
    if (!open || !anchor || !panel) return;
    const place = () => {
      // The meta row wraps independently of the viewport breakpoint. Retain
      // right alignment when it fits; shift only enough to keep both edges in view.
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft ?? 0) + 16;
      const rightEdge = (viewport?.offsetLeft ?? 0) + (viewport?.width ?? document.documentElement.clientWidth) - 16;
      panel.style.maxWidth = `${Math.max(0, rightEdge - leftEdge)}px`;
      const width = panel.offsetWidth;
      const anchorRight = anchor.getBoundingClientRect().right;
      const left = Math.max(leftEdge, Math.min(anchorRight - width, rightEdge - width));
      panel.style.right = `${anchorRight - left - width}px`;
      panel.style.transformOrigin = `${Math.max(0, Math.min(width, anchorRight - left))}px top`;
    };
    place();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(place);
    observer?.observe(anchor);
    observer?.observe(panel);
    if (anchor.parentElement) observer?.observe(anchor.parentElement);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    window.visualViewport?.addEventListener('resize', place);
    window.visualViewport?.addEventListener('scroll', place);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
      window.visualViewport?.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('scroll', place);
    };
  }, [open, history]);

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
          'mobile-control-target flex h-9 items-center gap-1.5 rounded-md border px-3 text-caption shadow-btn transition-colors duration-fast',
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
            className="absolute right-0 top-full mt-2 z-40 w-[320px] max-w-[calc(100vw-2rem)] origin-top-right rounded-md border border-line bg-card p-2 shadow-sh-2"
          >
            <p className="px-2 pb-1.5 pt-1 eyebrow">{t('最近 5 次扫描')}</p>
            {history.length === 0 ? (
              <EmptyState size="compact" image="/empty-chart.svg" title={t('尚无扫描记录')} />
            ) : (
              <ul className="divide-y divide-line">
                {history.slice(0, 5).map((entry, index) => (
                  <li
                    key={index}
                    className="flex min-h-[44px] items-center gap-3 px-2 py-2.5 transition-colors duration-fast hover:bg-paper-2/70"
                  >
                    <span className="tnum text-caption text-ink-800">
                      {fmtJstTime(new Date(entry.at).toISOString())}
                    </span>
                    <PointerTooltip
                      passthrough
                      label={entry.summary}
                      width={240}
                      className="min-w-0 flex-1"
                      contentClassName="p-2.5"
                      content={<span className="block text-micro leading-[16px] text-ink-600">{entry.summary}</span>}
                    >
                      <span className="block truncate text-micro text-ink-500">{entry.summary}</span>
                    </PointerTooltip>
                    <SoftBadge tone={entry.kind === 'refresh' ? 'warn' : 'brand'} className="shrink-0 tnum">
                      {entry.kind === 'refresh' ? t('更新读回') : t('条件筛选')} · {entry.count} {t('只')}
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
