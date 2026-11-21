/**
 * 月历 — 结构与样式对齐美版 MonthCalendar（样式在 calendar.css，JST）。
 * ‹ › 上月/本月/下月 · 月标题 ·「今天」；周一→周日网格；
 * 宽容器内显示最多 3 个代码 chips（確定=实心点 / 目安=空心点 / 已公布=灰点），窄容器只显示件数。
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import PointerTooltip from '@/components/shared/PointerTooltip';
import type { EarningsUpcomingItem } from '@/api/types';
import { EarningsChipContent, earningsChipLabel } from './chipTip';
import { addDays, fmtMDCN, jstToday, statusMeta, weekStartMonday } from './types';
import { t, getLocale } from '@/i18n/core';
import './calendar.css';

interface MonthCalendarProps {
  items: EarningsUpcomingItem[];
  selectedDay: string | null;
  onSelectDay: (date: string | null) => void;
  /** 周历锚点。查看下周等动作清掉日期筛选后，月历仍跟到新的一周。 */
  anchorDate?: string;
}

const WEEKDAYS = [t('周一'), t('周二'), t('周三'), t('周四'), t('周五'), t('周六'), t('周日')] as const;
const MAX_CHIPS = 3;

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

function monthKeyOf(date: string | null | undefined, fallback: string): string {
  const key = date?.slice(0, 7);
  return key && key.length === 7 ? key : fallback;
}

function clampMonth(key: string, minMonth: string, maxMonth: string): string {
  if (key < minMonth) return minMonth;
  if (key > maxMonth) return maxMonth;
  return key;
}

export default function MonthCalendar({ items, selectedDay, onSelectDay, anchorDate }: MonthCalendarProps) {
  const navigate = useNavigate();
  const today = jstToday();
  const currentMonth = today.slice(0, 7);
  const minMonth = shiftMonth(currentMonth, -1);
  const maxMonth = shiftMonth(currentMonth, 1);

  const [cursor, setCursor] = useState(() =>
    clampMonth(monthKeyOf(selectedDay ?? anchorDate, currentMonth), minMonth, maxMonth),
  );

  useEffect(() => {
    const next = clampMonth(monthKeyOf(selectedDay ?? anchorDate, currentMonth), minMonth, maxMonth);
    setCursor((prev) => (prev === next ? prev : next));
  }, [selectedDay, anchorDate, currentMonth, minMonth, maxMonth]);

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


  const goMonth = (delta: -1 | 1) => {
    const next = shiftMonth(cursor, delta);
    if (next < minMonth || next > maxMonth) return;
    setCursor(next);
  };

  const goToday = () => {
    setCursor(currentMonth);
    onSelectDay(today);
  };

  return (
    <section className="paper-panel earnings-calendar" aria-label={t('月历')}>
      <div className="earnings-calendar-toolbar">
        <button type="button" className="earnings-calendar-nav" onClick={() => goMonth(-1)} disabled={cursor <= minMonth} aria-label={t('上个月')}>
          <Icon name="chevron-right" size={16} className="rotate-180" />
        </button>
        <div className="earnings-month-title">
          <p className="text-h3 text-ink-900" aria-live="polite">{monthTitle(cursor)}</p>
          <button type="button" onClick={goToday} className="earnings-calendar-today">{t('今天')}</button>
        </div>
        <button type="button" className="earnings-calendar-nav" onClick={() => goMonth(1)} disabled={cursor >= maxMonth} aria-label={t('下个月')}>
          <Icon name="chevron-right" size={16} />
        </button>
      </div>

      <div className="earnings-month-scroll">
        <div className="earnings-month-weekdays" aria-hidden="true">
          {WEEKDAYS.map((weekday) => <span key={weekday}>{t(weekday)}</span>)}
        </div>
        <div className="earnings-month-grid">
          {cells.map((date) => {
            const inMonth = date.slice(0, 7) === cursor;
            const isToday = date === today;
            const isSelected = selectedDay === date;
            const dow = new Date(`${date}T12:00:00Z`).getUTCDay();
            const dayItems = byDate.get(date) ?? [];
            const shown = dayItems.slice(0, MAX_CHIPS);
            const extra = dayItems.length - shown.length;
            return (
              <div key={date} className={cn(
                'earnings-month-day',
                !inMonth && 'is-outside',
                (dow === 0 || dow === 6) && 'is-weekend',
                isSelected && 'is-selected',
              )}>
                <button
                  type="button"
                  className="earnings-month-date"
                  aria-pressed={isSelected}
                  aria-current={isToday ? 'date' : undefined}
                  aria-label={t('{md}，{n} 件财报', { md: fmtMDCN(date), n: dayItems.length })}
                  onClick={() => onSelectDay(isSelected ? null : date)}
                >
                  <span className="earnings-month-number tnum">{Number(date.slice(8, 10))}</span>
                  {dayItems.length > 0 && <span className="earnings-calendar-count tnum">{dayItems.length}</span>}
                </button>
                <div className="earnings-month-tickers">
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
