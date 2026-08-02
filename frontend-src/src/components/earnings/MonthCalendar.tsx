/**
 * 月历大界面 — 对标美版 MonthCalendar（JST）。
 * ‹ › 上月/本月/下月 · Serif 月标题 ·「今天」；周一→周日网格；
 * 格内 chips ≤3（確定实心点/目安空心点/已公布灰点），<sm 收缩为色点+计数。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import type { EarningsUpcomingItem } from '@/api/types';
import { addDays, fmtMDCN, jstToday, statusMeta, weekStartMonday } from './types';
import { t, getLocale } from '@/i18n/core';

interface MonthCalendarProps {
  items: EarningsUpcomingItem[];
  selectedDay: string | null;
  onSelectDay: (date: string | null) => void;
}

const WEEKDAYS = [t('周一'), t('周二'), t('周三'), t('周四'), t('周五'), t('周六'), t('周日')] as const;
const MAX_CHIPS = 3;
const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

function shiftMonth(key: string, delta: number): string {
  const year = Number(key.slice(0, 4));
  const month = Number(key.slice(5, 7)) - 1 + delta;
  return new Date(Date.UTC(year, month, 1)).toISOString().slice(0, 7);
}

function monthTitle(key: string): string {
  const year = Number(key.slice(0, 4));
  const month = Number(key.slice(5, 7));
  const locale = getLocale();
  if (locale === 'en') {
    return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-US', { year: 'numeric', month: 'short', timeZone: 'UTC' });
  }
  if (locale === 'ja') return `${year}年${month}月`;
  return `${year} 年 ${month} 月`;
}

export default function MonthCalendar({ items, selectedDay, onSelectDay }: MonthCalendarProps) {
  const navigate = useNavigate();
  const today = jstToday();
  const currentMonth = today.slice(0, 7);
  const minMonth = shiftMonth(currentMonth, -1);
  const maxMonth = shiftMonth(currentMonth, 1);

  const [cursor, setCursor] = useState(currentMonth);
  const [dir, setDir] = useState(0);

  const byDate = useMemo(() => {
    const map = new Map<string, EarningsUpcomingItem[]>();
    for (const item of items) {
      if (!item.date) continue;
      const list = map.get(item.date) ?? [];
      list.push(item);
      map.set(item.date, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => {
        const rank = (row: EarningsUpcomingItem) =>
          (row.status === 'confirmed' ? 0 : row.status === 'released' ? 1 : 2) - (row.featured ? 0.5 : 0);
        const delta = rank(a) - rank(b);
        if (delta !== 0) return delta;
        return (b.avg_turnover_20d ?? -1) - (a.avg_turnover_20d ?? -1);
      });
    }
    return map;
  }, [items]);

  const cells = useMemo(() => {
    const first = `${cursor}-01`;
    const start = weekStartMonday(first);
    const year = Number(cursor.slice(0, 4));
    const month = Number(cursor.slice(5, 7));
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const offset = Math.round((Date.parse(`${first}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000);
    const rows = Math.ceil((offset + daysInMonth) / 7);
    return Array.from({ length: rows * 7 }, (_, i) => addDays(start, i));
  }, [cursor]);

  const enteredRef = useRef(false);
  useEffect(() => {
    enteredRef.current = true;
  }, []);

  const goMonth = (delta: -1 | 1) => {
    const next = shiftMonth(cursor, delta);
    if (next < minMonth || next > maxMonth) return;
    setDir(delta);
    setCursor(next);
  };

  const goToday = () => {
    if (cursor !== currentMonth) {
      setDir(cursor < currentMonth ? 1 : -1);
      setCursor(currentMonth);
    }
    onSelectDay(today);
  };

  return (
    <section className="card-surface overflow-hidden" aria-label={t('月历')}>
      <div className="flex h-12 items-center justify-between border-b border-line px-4">
        <button
          type="button"
          onClick={() => goMonth(-1)}
          disabled={cursor <= minMonth}
          className="flex size-7 items-center justify-center rounded-sm border border-line bg-card text-ink-500 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={t('上个月')}
        >
          <Icon name="chevron-right" size={14} className="rotate-180" />
        </button>
        <div className="flex items-center gap-3">
          <p className="font-display text-h3 text-ink-900" aria-live="polite">{monthTitle(cursor)}</p>
          <button
            type="button"
            onClick={goToday}
            className="rounded-sm border border-line bg-card px-2 py-1 text-caption text-ink-500 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600"
          >
            {t('今天')}
          </button>
        </div>
        <button
          type="button"
          onClick={() => goMonth(1)}
          disabled={cursor >= maxMonth}
          className="flex size-7 items-center justify-center rounded-sm border border-line bg-card text-ink-500 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={t('下个月')}
        >
          <Icon name="chevron-right" size={14} />
        </button>
      </div>

      <div className="grid grid-cols-7 border-b border-line bg-card-warm/60">
        {WEEKDAYS.map((weekday, index) => (
          <span key={weekday} className={cn('py-1.5 text-center font-mono text-micro', index >= 5 ? 'text-ink-300' : 'text-ink-400')}>
            {weekday}
          </span>
        ))}
      </div>

      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div
          key={cursor}
          initial={{ x: dir * 36, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: dir * -36, opacity: 0 }}
          transition={{ duration: 0.26, ease: EASE_PAPER }}
          className="grid grid-cols-7"
        >
          {cells.map((date, cellIndex) => {
            const inMonth = date.slice(0, 7) === cursor;
            const isToday = date === today;
            const isSelected = selectedDay === date;
            const dow = new Date(`${date}T12:00:00Z`).getUTCDay();
            const isWeekend = dow === 0 || dow === 6;
            const isLastRow = cellIndex >= cells.length - 7;
            const dayItems = byDate.get(date) ?? [];
            const shown = dayItems.slice(0, MAX_CHIPS);
            const extra = dayItems.length - shown.length;
            const dayNumber = Number(date.slice(8, 10));
            const label = date.slice(8, 10) === '01' ? fmtMDCN(date) : String(dayNumber);
            return (
              <motion.div
                key={date}
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                aria-label={t('{md}，{n} 件决算', { md: fmtMDCN(date), n: dayItems.length })}
                onClick={() => onSelectDay(isSelected ? null : date)}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelectDay(isSelected ? null : date);
                  }
                }}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.48, ease: EASE_PAPER, delay: enteredRef.current ? 0 : cellIndex * 0.025 }}
                className={cn(
                  'flex min-h-[64px] cursor-pointer flex-col border-r border-line p-1.5 text-left transition-colors duration-fast sm:min-h-[104px] sm:p-2',
                  '[&:nth-child(7n)]:border-r-0',
                  !isLastRow && 'border-b',
                  isSelected ? 'bg-brand-50' : isWeekend ? 'bg-paper-2/70 hover:bg-paper-2' : 'hover:bg-paper-2',
                )}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={cn(
                      'font-mono text-micro tnum',
                      isToday
                        ? 'flex h-6 min-w-6 items-center justify-center rounded-full bg-brand-600 px-1 font-semibold text-white'
                        : inMonth
                          ? 'text-ink-800'
                          : 'text-ink-300',
                    )}
                  >
                    {label}
                  </span>
                  {dayItems.length > 0 && (
                    <span className="hidden rounded-pill bg-line/70 px-1 font-mono text-[10px] leading-4 text-ink-600 tnum sm:inline">
                      {dayItems.length}
                    </span>
                  )}
                </div>

                <div className="mt-1.5 hidden flex-1 flex-col gap-1 sm:flex">
                  {shown.map((item) => {
                    const meta = statusMeta(item.status);
                    return (
                      <motion.button
                        key={`${item.canonical_code}-${item.period_type}`}
                        type="button"
                        whileTap={{ scale: 0.96 }}
                        onClick={(event) => {
                          event.stopPropagation();
                          navigate(`/stock/${item.display_code}`);
                        }}
                        title={`${item.name_ja ?? item.display_code} · ${item.quarter_label ?? ''} · ${meta.label}`}
                        className="flex h-5 items-center gap-1 rounded-xs px-1 transition-colors duration-fast hover:bg-brand-50"
                      >
                        <span className={cn('size-1.5 shrink-0 rounded-full', meta.dotClass)} aria-hidden="true" />
                        <span className="truncate font-mono text-[10px] font-medium leading-4 text-ink-800">{item.display_code}</span>
                      </motion.button>
                    );
                  })}
                  {extra > 0 && <span className="px-1 font-mono text-[10px] leading-4 text-ink-400 tnum">+{extra}</span>}
                </div>

                <div className="mt-1 flex flex-1 items-end sm:hidden">
                  {dayItems.length > 0 && (
                    <span className="flex items-center gap-1" aria-hidden="true">
                      <span className="flex gap-0.5">
                        {shown.map((item, i) => (
                          <span key={i} className={cn('size-1.5 rounded-full', statusMeta(item.status).dotClass)} />
                        ))}
                      </span>
                      <span className="rounded-pill bg-line/70 px-1 font-mono text-[10px] leading-4 text-ink-600 tnum">
                        {dayItems.length}
                      </span>
                    </span>
                  )}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </AnimatePresence>
    </section>
  );
}
