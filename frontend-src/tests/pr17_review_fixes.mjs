import test from 'node:test';
import assert from 'node:assert/strict';
import { quotePair } from '../src/components/screener/quotePair.ts';

test('quotePair pairs live price with live change, not daily points', () => {
  const row = { canonical_code: '7203', close: 1000, change_pct: 5 };
  const quote = quotePair(row, { 7203: { live_price: 900, live_change_pct: -0.1 } });
  assert.equal(quote.price, 900);
  assert.equal(quote.change, -0.1);
  assert.equal(quote.live, true);
});

test('quotePair converts daily change_pct points to a ratio', () => {
  const row = { canonical_code: '7203', close: 1000, change_pct: 5 };
  const quote = quotePair(row);
  assert.equal(quote.price, 1000);
  assert.equal(quote.change, 0.05);
  assert.equal(quote.live, false);
});
