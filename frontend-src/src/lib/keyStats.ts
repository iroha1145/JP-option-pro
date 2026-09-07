import type { StockBar, StockOverview } from '@/api/types';

const isNum = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** 约 240 个交易日才够称为 52 周；更短的窗口如实标「期间」。 */
export const YEAR_BAR_FLOOR = 240;

export function lastBar(bars: StockBar[] | null | undefined): StockBar | null {
  if (!bars || bars.length === 0) return null;
  return bars[bars.length - 1] ?? null;
}

export function previousBar(bars: StockBar[] | null | undefined): StockBar | null {
  if (!bars || bars.length < 2) return null;
  return bars[bars.length - 2] ?? null;
}

export function periodExtremes(bars: StockBar[] | null | undefined): { high: number | null; low: number | null } {
  let high: number | null = null;
  let low: number | null = null;
  for (const bar of bars ?? []) {
    const hi = bar.adj_high ?? bar.high;
    const lo = bar.adj_low ?? bar.low;
    if (isNum(hi)) high = high == null ? hi : Math.max(high, hi);
    if (isNum(lo)) low = low == null ? lo : Math.min(low, lo);
  }
  return { high, low };
}

export function isYearRange(barCount: number): boolean {
  return barCount >= YEAR_BAR_FLOOR;
}

export function rangeMarkerPct(
  price: number | null | undefined,
  high: number | null,
  low: number | null,
): number | null {
  if (!isNum(price) || !isNum(high) || !isNum(low) || high <= low) return null;
  return Math.min(100, Math.max(2, ((price - low) / (high - low)) * 100));
}

export function sessionOpen(bar: StockBar | null): number | null {
  if (!bar) return null;
  const value = bar.open ?? bar.adj_open;
  return isNum(value) ? value : null;
}

export function sessionHigh(bar: StockBar | null): number | null {
  if (!bar) return null;
  const value = bar.high ?? bar.adj_high;
  return isNum(value) ? value : null;
}

export function sessionLow(bar: StockBar | null): number | null {
  if (!bar) return null;
  const value = bar.low ?? bar.adj_low;
  return isNum(value) ? value : null;
}

export function previousClose(bar: StockBar | null): number | null {
  if (!bar) return null;
  const value = bar.close ?? bar.adj_close;
  return isNum(value) ? value : null;
}

export function markerPrice(quote: StockOverview['quote']): number | null {
  const value = quote.adj_close ?? quote.close;
  return isNum(value) ? value : null;
}
