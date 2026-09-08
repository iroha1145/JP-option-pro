import test from 'node:test';
import assert from 'node:assert/strict';
import { quotePair } from '../src/components/screener/quotePair.ts';
import {
  querySucceededAsNewComputation,
  publicationMatches,
  liveQuoteDoesNotProveScoreFresh,
} from '../src/components/screener/freshness.ts';

test('G08 quotePair still pairs live price with live change', () => {
  const row = { canonical_code: '7203', close: 1000, change_pct: 5 };
  const quote = quotePair(row, { 7203: { live_price: 900, live_change_pct: -0.1 } });
  assert.equal(quote.price, 900);
  assert.equal(quote.change, -0.1);
  assert.equal(quote.live, true);
});

test('F01 HTTP 200 snapshot is never a new computation', () => {
  const response = { publication_id: 'pub_old', freshness: 'stale', rows: [{ canonical_code: '72030' }] };
  assert.equal(querySucceededAsNewComputation(response), false);
});

test('F03 read-back must match the promised publication id', () => {
  assert.equal(publicationMatches({ publication_id: 'pub_new' }, 'pub_new'), true);
  assert.equal(publicationMatches({ publication_id: 'pub_old' }, 'pub_new'), false);
});

test('G07 newer live quote does not prove the daily score is current', () => {
  assert.equal(liveQuoteDoesNotProveScoreFresh(true, 'stale'), false);
  assert.equal(liveQuoteDoesNotProveScoreFresh(true, 'current'), true);
});

test('F01 filter history kind is not a refresh computation', () => {
  const entry = { kind: 'filter', count: 12 };
  assert.equal(entry.kind === 'refresh', false);
  assert.equal(querySucceededAsNewComputation({ publication_id: 'p', rows: [] }), false);
});
