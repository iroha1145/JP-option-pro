import type { StrengthRow } from '@/api/types';

export type LiveQuoteOverlay = Record<
  string,
  { live_price: number; live_change_pct?: number; live_pct_from_high_252?: number | null }
>;

/** 盘中价必须配盘中涨跌；没有叠加才用收盘价 + 日线涨跌。 */
export function quotePair(
  row: StrengthRow,
  overlay?: LiveQuoteOverlay,
): { price: number | null; change: number | null; live: boolean } {
  const live = overlay?.[row.canonical_code];
  if (live && Number.isFinite(live.live_price)) {
    return {
      price: live.live_price,
      change:
        typeof live.live_change_pct === 'number' && Number.isFinite(live.live_change_pct)
          ? live.live_change_pct
          : null,
      live: true,
    };
  }
  return {
    price: row.close,
    change: row.change_pct !== null ? row.change_pct / 100 : null,
    live: false,
  };
}
