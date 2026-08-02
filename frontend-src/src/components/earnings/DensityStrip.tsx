/**
 * 右栏：未来 35 天决算密度条 — 对标美版 DensityStrip。
 * 每日件数迷你柱（確定+已公布=brand，含目安=淡色叠加）；hover 显当日代码；点击跳该日。
 */
import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import SourceNote from '@/components/shared/SourceNote';
import type { EarningsUpcomingItem } from '@/api/types';
import { addDays, fmtMDCN, fmtMMDD, jstToday, weekdayCN } from './types';
import { t } from '@/i18n/core';

interface DensityStripProps {
  items: EarningsUpcomingItem[];
  onJumpDay: (date: string) => void;
}

const DAYS = 35;
const MAX_TOOLTIP_CODES = 12;

export default function DensityStrip({ items, onJumpDay }: DensityStripProps) {
  const days = useMemo(() => {
    const today = jstToday();
    const byDate = new Map<string, EarningsUpcomingItem[]>();
    for (const item of items) {
      if (!item.date) continue;
      const list = byDate.get(item.date) ?? [];
      list.push(item);
      byDate.set(item.date, list);
    }
    return Array.from({ length: DAYS }, (_, i) => {
      const date = addDays(today, i);
      return { date, rows: byDate.get(date) ?? [] };
    });
  }, [items]);

  const max = Math.max(...days.map((day) => day.rows.length), 1);

  return (
    <section className="card-surface p-5" aria-label={t('决算密度')}>
      <p className="eyebrow">{t('决算密度 · 未来 35 天')}</p>
      <div className="mt-3 flex h-16 items-end gap-[2px]" role="list" aria-label={t('每日决算件数')}>
        {days.map((day, index) => {
          const n = day.rows.length;
          const solid = day.rows.filter((row) => row.status !== 'estimated').length;
          const isToday = index === 0;
          return (
            <span key={day.date} role="listitem" className="contents">
              <button
                type="button"
                onClick={() => onJumpDay(day.date)}
                aria-label={t('{date} {weekday}，{n} 件决算，跳转', { date: fmtMDCN(day.date), weekday: weekdayCN(day.date), n })}
                className="group relative flex h-full min-w-0 flex-1 items-end focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400/60"
              >
                <span
                  className={cn(
                    'glass pointer-events-none absolute -top-2 z-20 hidden w-max max-w-[190px] -translate-y-full rounded-md border border-line px-2.5 py-1.5 text-left shadow-sh-2 group-hover:block group-focus-visible:block',
                    index < days.length / 3 ? 'left-0' : index >= (days.length * 2) / 3 ? 'right-0' : 'left-1/2 -translate-x-1/2',
                  )}
                >
                  <span className="block font-mono text-[10px] text-ink-500">
                    {fmtMMDD(day.date)} {weekdayCN(day.date)}
                    {n > 0 && <span className="ml-1 text-ink-400">{t('確定')} {solid} / {t('目安')} {n - solid}</span>}
                  </span>
                  {n === 0 ? (
                    <span className="block text-[10px] text-ink-300">{t('无决算')}</span>
                  ) : (
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {day.rows.slice(0, MAX_TOOLTIP_CODES).map((row) => (
                        <span key={`${row.canonical_code}-${row.period_type}`} className="font-mono text-[10px] font-semibold text-ink-800">
                          {row.display_code}
                        </span>
                      ))}
                      {n > MAX_TOOLTIP_CODES && (
                        <span className="font-mono text-[10px] text-ink-400">+{n - MAX_TOOLTIP_CODES}</span>
                      )}
                    </span>
                  )}
                </span>
                {/* 双段柱：下段=確定/已公布（实色），上段=目安（淡色） */}
                <span className="flex w-full flex-col justify-end" style={{ height: '100%' }} aria-hidden="true">
                  {n - solid > 0 && (
                    <motion.span
                      className="w-full rounded-t-[2px] bg-brand-300/50 group-hover:bg-brand-400/60"
                      style={{ height: `${Math.max(4, ((n - solid) / max) * 100)}%` }}
                      initial={{ scaleY: 0, transformOrigin: 'bottom' }}
                      whileInView={{ scaleY: 1 }}
                      viewport={{ once: true, amount: 0.4 }}
                      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: index * 0.015 }}
                    />
                  )}
                  <motion.span
                    className={cn(
                      'w-full transition-colors duration-fast',
                      solid > 0 ? 'bg-brand-500 group-hover:bg-brand-600' : n === 0 ? 'bg-line' : 'bg-transparent',
                      n - solid <= 0 && 'rounded-t-[2px]',
                      isToday && 'ring-1 ring-brand-600 ring-offset-1',
                    )}
                    style={{ height: solid > 0 ? `${Math.max(8, (solid / max) * 100)}%` : n === 0 ? '2px' : '0px' }}
                    initial={{ scaleY: 0, transformOrigin: 'bottom' }}
                    whileInView={{ scaleY: 1 }}
                    viewport={{ once: true, amount: 0.4 }}
                    transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: index * 0.015 }}
                  />
                </span>
              </button>
            </span>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[9px] text-ink-300">
        <span>{t('今天')}</span>
        <span>+17</span>
        <span>+35</span>
      </div>
      <div className="mt-2 flex items-center gap-3 text-micro text-ink-400">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-[2px] bg-brand-500" />{t('確定/已公布')}</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-[2px] bg-brand-300/50" />{t('目安')}</span>
      </div>
      <SourceNote className="mt-3" text={t('確定=J-Quants 发表预定 · 目安=前年同期开示日推导')} />
    </section>
  );
}
