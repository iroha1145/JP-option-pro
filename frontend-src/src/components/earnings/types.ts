/**
 * 决算日历共享类型与 JST 日期工具 — 对标美版 earnings/types.ts（ET→JST）。
 * 三态：released（已公布，实绩）/ confirmed（官方確定，仅次一交易日）/
 * estimated（目安，前年同期开示日推导）。目安必须与確定视觉区分。
 */
import type { EarningsUpcomingItem } from '@/api/types';
import { t, getLocale } from '@/i18n/core';

export type ListMode = 'featured' | 'all';

/* ---------------- JST 日期 ---------------- */
const jstFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
});

let jstTodayCache: { at: number; value: string } | null = null;
export function jstToday(): string {
  const at = Date.now();
  if (jstTodayCache && at - jstTodayCache.at < 1000) return jstTodayCache.value;
  const value = jstFmt.format(new Date(at));
  jstTodayCache = { at, value };
  return value;
}

let daysUntilCache: { today: string; byDate: Map<string, number> } | null = null;
export function daysUntil(date: string): number {
  const today = jstToday();
  if (!daysUntilCache || daysUntilCache.today !== today) {
    daysUntilCache = { today, byDate: new Map() };
  }
  const cached = daysUntilCache.byDate.get(date);
  if (cached !== undefined) return cached;
  const value = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  daysUntilCache.byDate.set(date, value);
  return value;
}

export function addDays(date: string, n: number): string {
  return new Date(Date.parse(`${date}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}

export function weekStartMonday(date: string): string {
  const dow = new Date(`${date}T12:00:00Z`).getUTCDay();
  return addDays(date, -(dow === 0 ? 6 : dow - 1));
}

export function weekDays(monday: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

export const WEEK_CN = [t('周日'), t('周一'), t('周二'), t('周三'), t('周四'), t('周五'), t('周六')] as const;

export function fmtMMDD(date: string): string {
  return `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
}

export function fmtMDCN(date: string): string {
  const mo = Number(date.slice(5, 7));
  const day = Number(date.slice(8, 10));
  const locale = getLocale();
  if (locale === 'en') return `${mo}/${day}`;
  if (locale === 'ja') return `${mo}月${day}日`;
  return `${mo} 月 ${day} 日`;
}

export function weekdayCN(date: string): string {
  return WEEK_CN[new Date(`${date}T12:00:00Z`).getUTCDay()];
}

export function relativeDayCN(date: string): string {
  const d = daysUntil(date);
  if (d === 0) return t('今天');
  if (d === 1) return t('明天');
  if (d === 2) return t('后天');
  if (d < 0) return t('{n} 天前', { n: -d });
  return weekdayCN(date);
}

/* ---------------- 三态视觉 ---------------- */

export type EarningsStatus = EarningsUpcomingItem['status'];

export function statusMeta(status: EarningsStatus): { label: string; dotClass: string; chipClass: string } {
  if (status === 'released') {
    return { label: t('已公布'), dotClass: 'bg-ink-400', chipClass: 'bg-paper-2 text-ink-600' };
  }
  if (status === 'confirmed') {
    return { label: t('確定'), dotClass: 'bg-brand-600', chipClass: 'bg-brand-50 text-brand-700' };
  }
  return { label: t('目安'), dotClass: 'border border-ink-400 bg-transparent', chipClass: 'border border-dashed border-line-strong text-ink-500' };
}

/** 决算种别短标（chips 用）：1Q/2Q/3Q/本 */
export function periodShort(periodType: string | null): string {
  if (!periodType) return '—';
  if (periodType === 'FY' || periodType === '4Q') return t('本');
  return periodType;
}

/* ---------------- 列表派生（纯函数，页面与测试共用思路同美版） ---------------- */

export function isFeaturedRow(row: EarningsUpcomingItem): boolean {
  return row.featured || row.in_watchlist || row.radar_state !== null;
}

export interface EarningsListState {
  baseItems: EarningsUpcomingItem[];
  featuredCount: number;
  allCount: number;
  listItems: EarningsUpcomingItem[];
  visibleItems: EarningsUpcomingItem[];
}

export function computeListState(input: {
  items: EarningsUpcomingItem[];
  selectedDay: string | null;
  mode: ListMode;
  visibleLimit: number;
}): EarningsListState {
  const { items, selectedDay, mode, visibleLimit } = input;
  // 默认列表从今天开始（关注即将公布）；过去几天的已公布行仍在数据里，
  // 通过周历/密度条点选具体日期进入 —— 首屏不被三天前的旧闻占满。
  const today = jstToday();
  const baseItems = selectedDay
    ? items.filter((it) => it.date === selectedDay)
    : items.filter((it) => (it.date ?? '') >= today);
  const featuredItems = baseItems.filter(isFeaturedRow);
  const listItems = mode === 'featured' ? featuredItems : baseItems;
  const visibleItems = listItems.slice(0, Math.max(0, Math.floor(visibleLimit)));
  return {
    baseItems,
    featuredCount: featuredItems.length,
    allCount: baseItems.length,
    listItems,
    visibleItems,
  };
}
