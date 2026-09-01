/**
 * B1 JST 周历 scrubber — 对标美版 WeekScrubber（ET→JST，盘前/盘后→三态标记）。
 * 周一→周日 7 日格 · 每日件数 + 前 3 个代码 chips（確定=实心点 / 目安=空心点 / 已公布=灰点）
 * 点击日格过滤当天；点击 chip 跳个股页；‹ › 周切换整带 slide。
 */
import { useMemo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import type { EarningsUpcomingItem } from '@/api/types';
import { fmtMDCN, fmtMMDD, jstToday, periodShort, statusMeta, weekDays, weekdayCN } from './types';
import { t } from '@/i18n/core';

interface WeekScrubberProps {
  items: EarningsUpcomingItem[];
  monday: string;
  weekDir: number;
  onWeekChange: (dir: -1 | 1) => void;
  selectedDay: string | null;
  onSelectDay: (date: string | null) => void;
}

const MAX_CHIPS = 3;

export default function WeekScrubber({
  items,
  monday,
  weekDir,
  onWeekChange,
  selectedDay,
  onSelectDay,
}: WeekScrubberProps) {
  const navigate = useNavigate();
  const days = useMemo(() => weekDays(monday), [monday]);
  const today = jstToday();

  const byDate = useMemo(() => {
    const map = new Map<string, EarningsUpcomingItem[]>();
    for (const item of items) {
      if (!item.date) continue;
      const list = map.get(item.date) ?? [];
      list.push(item);
      map.set(item.date, list);
    }
    // 確定 → 重点 → 成交额降序（chips 是每天的“门面”，别被小盘目安占满）
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

  return (
    <section className="card-surface overflow-hidden" aria-label={t('周历')}>
      <div className="flex h-11 items-center justify-between border-b border-line px-4">
        <button
          type="button"
          onClick={() => onWeekChange(-1)}
          className="flex size-7 items-center justify-center rounded-sm border border-line bg-card text-ink-500 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600"
          aria-label={t('上一周')}
        >
          <Icon name="chevron-right" size={14} className="rotate-180" />
        </button>
        <p className="font-mono text-caption text-ink-600 tnum" aria-live="polite">
          {fmtMDCN(days[0])} – {fmtMDCN(days[6])}
          <span className="ml-2 font-sans text-micro text-ink-400">JST</span>
        </p>
        <button
          type="button"
          onClick={() => onWeekChange(1)}
          className="flex size-7 items-center justify-center rounded-sm border border-line bg-card text-ink-500 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600"
          aria-label={t('下一周')}
        >
          <Icon name="chevron-right" size={14} />
        </button>
      </div>

      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-6 bg-gradient-to-r from-card to-transparent sm:hidden" aria-hidden="true" />
        <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-6 bg-gradient-to-l from-card to-transparent sm:hidden" aria-hidden="true" />
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.div
            key={monday}
            initial={{ x: weekDir * 44, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: weekDir * -44, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="flex snap-x snap-mandatory overflow-x-auto no-scrollbar sm:grid sm:grid-cols-7 sm:overflow-visible"
          >
            {days.map((date, dayIndex) => {
              const dayItems = byDate.get(date) ?? [];
              const isToday = date === today;
              const isSelected = selectedDay === date;
              const shown = dayItems.slice(0, MAX_CHIPS);
              const extra = dayItems.length - shown.length;
              // Only truly-confirmed dates count toward the 確定 badge; released
              // (already-disclosed) items are not 確定 and were being mislabeled.
              const confirmedCount = dayItems.filter((it) => it.status === 'confirmed').length;
              return (
                <motion.div
                  key={date}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSelected}
                  aria-label={t('{weekday} {md}，{n} 件决算', { weekday: weekdayCN(date), md: fmtMMDD(date), n: dayItems.length })}
                  onClick={() => onSelectDay(isSelected ? null : date)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectDay(isSelected ? null : date);
                    }
                  }}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.48, ease: [0.16, 1, 0.3, 1], delay: dayIndex * 0.035 }}
                  className={cn(
                    'flex min-h-[148px] w-[86px] shrink-0 cursor-pointer snap-start flex-col border-r border-line px-2 py-2.5 text-left transition-colors duration-fast last:border-r-0 sm:w-auto sm:min-w-0',
                    isSelected ? 'bg-brand-50' : 'hover:bg-paper-2',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className={cn('text-caption', isToday ? 'font-semibold text-brand-600' : 'text-ink-500')}>
                      {weekdayCN(date)}
                    </span>
                    {isToday && <span className="size-1.5 rounded-full bg-brand-600" aria-label={t('今天')} />}
                  </div>
                  <span className={cn('font-mono text-micro tnum', isToday ? 'text-brand-600' : 'text-ink-400')}>
                    {fmtMMDD(date)}
                  </span>

                  <div className="mt-2 flex flex-1 flex-col gap-1">
                    {dayItems.length === 0 ? (
                      <span className="pt-1 font-mono text-micro text-ink-300" aria-hidden="true">—</span>
                    ) : (
                      <>
                        {shown.map((item, chipIndex) => {
                          const meta = statusMeta(item.status);
                          return (
                            <motion.button
                              key={`${item.canonical_code}-${item.period_type}`}
                              type="button"
                              initial={{ opacity: 0, scale: 0.9 }}
                              animate={{ opacity: 1, scale: 1 }}
                              transition={{ type: 'spring', stiffness: 520, damping: 32, delay: dayIndex * 0.035 + chipIndex * 0.02 }}
                              onClick={(event) => {
                                event.stopPropagation();
                                navigate(`/stock/${item.display_code}`);
                              }}
                              title={`${item.name_ja ?? item.display_code} · ${item.quarter_label ?? ''} · ${meta.label}`}
                              className={cn(
                                'flex h-6 items-center gap-1 rounded-xs border-l-2 px-1 transition-[transform,background-color] duration-fast hover:-translate-y-px',
                                item.status === 'confirmed'
                                  ? 'border-brand-600 bg-brand-50'
                                  : item.status === 'released'
                                    ? 'border-ink-300 bg-paper-2'
                                    : 'border-transparent bg-paper-2/70 hover:bg-brand-50',
                              )}
                            >
                              <span className={cn('size-1.5 shrink-0 rounded-full', meta.dotClass)} aria-hidden="true" />
                              <span className="min-w-0 truncate font-mono text-micro font-medium text-ink-800">{item.display_code}</span>
                              <span className="ml-auto shrink-0 font-mono text-[9px] text-ink-400">{periodShort(item.period_type)}</span>
                            </motion.button>
                          );
                        })}
                        {extra > 0 && <span className="px-1 font-mono text-[10px] leading-4 text-ink-400">+{extra}</span>}
                      </>
                    )}
                  </div>

                  <span className="mt-1 truncate whitespace-nowrap font-mono text-[10px] leading-4 text-ink-300 tnum">
                    {/* 7 日グリッドの 1 セルは端末幅で ~48px。確定内訳は sm 以上でのみ出す
                        （英語 "101 · 76 confirmed" は必ず切れる。状態は上のチップが示す） */}
                    {dayItems.length > 0 ? (
                      <>
                        <span className="sm:hidden">{t('{n} 件', { n: dayItems.length })}</span>
                        <span className="hidden sm:inline">
                          {confirmedCount > 0 && confirmedCount < dayItems.length
                            ? t('{n} 件 · 確定{c}', { n: dayItems.length, c: confirmedCount })
                            : t('{n} 件', { n: dayItems.length })}
                        </span>
                      </>
                    ) : ''}
                  </span>
                </motion.div>
              );
            })}
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
}
