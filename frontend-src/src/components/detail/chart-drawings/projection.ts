/** Bar-key projection for Japan daily charts. Calendar dates stay calendar dates. */
import type { ChartRange, DrawingAnchor } from './types.ts';

export interface TimedBar {
  t: string;
}

export function barKeyOf(bar: TimedBar, range: ChartRange | string): string {
  const stamp = bar.t.trim();
  if (range === '1d' || range === '1w' || /^\d{4}-\d{2}-\d{2}/.test(stamp)) {
    return stamp.slice(0, 10);
  }
  return stamp;
}

export function resolveBarKey(
  bars: TimedBar[],
  barKey: string,
  range: ChartRange | string,
): number {
  for (let i = 0; i < bars.length; i++) {
    if (barKeyOf(bars[i], range) === barKey) return i;
  }
  return -1;
}

export function resolveAnchor(
  bars: TimedBar[],
  anchor: DrawingAnchor,
  range: ChartRange | string,
): number {
  return resolveBarKey(bars, anchor.barKey, range);
}
