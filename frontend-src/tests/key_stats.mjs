/**
 * KeyStats 只许用真实 K 线推导区间标签，不够一年不能冒充 52 周。
 * 执行: node --experimental-strip-types frontend-src/tests/key_stats.mjs
 */
import assert from 'node:assert/strict';
import { isYearRange, periodExtremes, rangeMarkerPct, YEAR_BAR_FLOOR } from '../src/lib/keyStats.ts';

assert.equal(isYearRange(0), false);
assert.equal(isYearRange(YEAR_BAR_FLOOR - 1), false);
assert.equal(isYearRange(YEAR_BAR_FLOOR), true);
assert.equal(isYearRange(252), true);

const extremes = periodExtremes([
  { trade_date: '2025-01-01', open: 10, high: 12, low: 9, close: 11, adj_open: 10, adj_high: 12, adj_low: 9, adj_close: 11, volume: 1, turnover_value: 1, adjustment_factor: 1 },
  { trade_date: '2025-01-02', open: 11, high: 20, low: 8, close: 15, adj_open: 11, adj_high: 18, adj_low: 7, adj_close: 15, volume: 1, turnover_value: 1, adjustment_factor: 1 },
]);
assert.equal(extremes.high, 18);
assert.equal(extremes.low, 7);

assert.equal(rangeMarkerPct(null, 18, 7), null);
assert.equal(rangeMarkerPct(7, 18, 7), 2);
assert.ok(Math.abs((rangeMarkerPct(12.5, 18, 7) ?? 0) - 50) < 0.01);

console.log('key_stats.mjs ok');
