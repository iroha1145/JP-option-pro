/**
 * B1 JST 周历 — 结构与样式对齐美版 WeekScrubber（样式在 calendar.css）。
 * 周一→周日 7 日格 · 每日件数 + 前 3 个代码 chips（確定=实心点 / 目安=空心点 / 已公布=灰点）
 * 点击日格过滤当天；点击 chip 跳个股页；‹ › 切周。
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import PointerTooltip from '@/components/shared/PointerTooltip';
import type { EarningsUpcomingItem } from '@/api/types';
import { EarningsChipContent, earningsChipLabel } from './chipTip';
import { fmtMDCN, fmtMMDD, jstToday, periodShort, statusMeta, weekDays, weekdayCN } from './types';
import { t } from '@/i18n/core';
import './calendar.css';

interface WeekScrubberProps {
  items: EarningsUpcomingItem[];
  monday: string;
  /** 保留给页面的现有接口；周历不再做滑动动画，不读取。 */
  weekDir?: number;
  onWeekChange: (dir: -1 | 1) => void;
  selectedDay: string | null;
  onSelectDay: (date: string | null) => void;
  flashSignal?: number;
}

const MAX_CHIPS = 3;
/** 三个触控尺寸的代码按钮加「+N」，让相邻周与加载骨架高度一致。 */
export const WEEK_DAY_MIN_H = 'min-h-[248px]';

export default function WeekScrubber({
  items,
  monday,
  onWeekChange,
  selectedDay,
  onSelectDay,
  flashSignal = 0,
}: WeekScrubberProps) {
  const navigate = useNavigate();
  const days = useMemo(() => weekDays(monday), [monday]);
  const today = jstToday();
  const [flashing, setFlashing] = useState(false);
  const [prevFlashSignal, setPrevFlashSignal] = useState(flashSignal);
  if (flashSignal !== prevFlashSignal) {
    setPrevFlashSignal(flashSignal);
    if (flashSignal > 0) setFlashing(true);
  }
  useEffect(() => {
    if (!flashing) return;
    const timer = window.setTimeout(() => setFlashing(false), 700);
    return () => window.clearTimeout(timer);
  }, [flashing]);

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
    <section className="paper-panel earnings-calendar" aria-label={t('周历')}>
      <div className="earnings-calendar-toolbar">
        <button type="button" className="earnings-calendar-nav" onClick={() => onWeekChange(-1)} aria-label={t('上一周')}>
          <Icon name="chevron-right" size={16} className="rotate-180" />
        </button>
        <p className="earnings-calendar-period tnum" aria-live="polite">
          <span>{fmtMDCN(days[0])} – {fmtMDCN(days[6])}</span>
          <span className="text-caption text-ink-400">JST</span>
        </p>
        <button type="button" className="earnings-calendar-nav" onClick={() => onWeekChange(1)} aria-label={t('下一周')}>
          <Icon name="chevron-right" size={16} />
        </button>
      </div>

      <div className="earnings-week-scroll">
        <div className="earnings-week-grid">
          {days.map((date) => {
            const dayItems = byDate.get(date) ?? [];
            const isToday = date === today;
            const isSelected = selectedDay === date;
            const shown = dayItems.slice(0, MAX_CHIPS);
            const extra = dayItems.length - shown.length;
            // 只有真正「確定」的日期才计入確定；已公布的不算。
            const confirmedCount = dayItems.filter((it) => it.status === 'confirmed').length;
            return (
              <div key={date} className={cn(
                'earnings-week-day tick-flash', WEEK_DAY_MIN_H,
                isSelected && 'is-selected',
                flashing && dayItems.length > 0 && 'tick-flash-up',
              )}>
                <button
                  type="button"
                  className="earnings-week-date"
                  aria-pressed={isSelected}
                  aria-current={isToday ? 'date' : undefined}
                  aria-label={t('{weekday} {md}，{n} 件财报', { weekday: weekdayCN(date), md: fmtMMDD(date), n: dayItems.length })}
                  onClick={() => onSelectDay(isSelected ? null : date)}
                >
                  <span className={cn('earnings-week-weekday', isToday && 'text-brand-600')}>
                    {weekdayCN(date)}
                    {dayItems.length > 0 && <span className="earnings-calendar-count tnum">{dayItems.length}</span>}
                  </span>
                  <span className={cn('text-caption tnum', isToday ? 'text-brand-600' : 'text-ink-500')}>{fmtMMDD(date)}</span>
                  {confirmedCount > 0 && confirmedCount < dayItems.length && (
                    <span className="earnings-week-note tnum">{t('{n} 件 · 確定{c}', { n: dayItems.length, c: confirmedCount })}</span>
                  )}
                </button>
                <div className="earnings-week-tickers">
                  {shown.map((item) => {
                    const meta = statusMeta(item.status);
                    return (
                      <PointerTooltip
                        key={`${item.canonical_code}-${item.period_type}`}
                        passthrough
                        label={earningsChipLabel(item)}
                        width={220}
                        contentClassName="p-2.5"
                        className="block w-full"
                        content={<EarningsChipContent item={item} />}
                      >
                        <button
                          type="button"
                          className={cn(
                            'earnings-calendar-ticker w-full',
                            item.status === 'confirmed' && 'is-confirmed',
                            item.status === 'estimated' && 'is-estimated',
                          )}
                          onClick={() => navigate(`/stock/${item.display_code}`)}
                        >
                          <span className={cn('size-1.5 shrink-0 rounded-full', meta.dotClass)} aria-hidden="true" />
                          <span className="min-w-0 tnum">{item.display_code}</span>
                          <span className="earnings-calendar-ticker-period tnum">{periodShort(item.period_type)}</span>
                        </button>
                      </PointerTooltip>
                    );
                  })}
                  {extra > 0 && <span className="earnings-calendar-extra tnum">+{extra}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
