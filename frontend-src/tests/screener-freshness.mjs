import test from 'node:test';
import assert from 'node:assert/strict';
import { quotePair } from '../src/components/screener/quotePair.ts';
import {
  querySucceededAsNewComputation,
  publicationMatches,
  liveQuoteDoesNotProveScoreFresh,
  interpretOwnerRefresh,
  promisedPublication,
  silentScanMayCommit,
  refreshMayCommitResults,
  actionStillRunning,
} from '../src/components/screener/freshness.ts';
import { codesMatch, payloadMatchesCode, pickQuoteForCode } from '../src/lib/securityIdentity.ts';

const filtersA = { tier: 'all', minScore: null, sectors: [], topN: 20 };
const filtersB = { tier: 'A', minScore: 80, sectors: [], topN: 20 };

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

test('R04 promised P2 with read-back P1 is not success', () => {
  const action = {
    status: 'completed',
    result: {
      outcome: 'published',
      radar: { publication: { publication_id: 'P2', trade_date: '2026-09-08', score_version: 'v1' } },
    },
  };
  const promised = promisedPublication(action);
  const verdict = interpretOwnerRefresh({
    actionStatus: 'completed',
    timedOut: false,
    promised,
    readback: { publication_id: 'P1', trade_date: '2026-09-08', freshness: 'current' },
    previousPublicationId: 'P0',
  });
  assert.equal(verdict.state, 'error');
  assert.equal(verdict.messageKey, '读回发布与任务承诺不一致');
  assert.equal(verdict.commitResponse, false);
});

test('R04 already_current plus stale freshness is not latest', () => {
  const verdict = interpretOwnerRefresh({
    actionStatus: 'completed',
    timedOut: false,
    promised: {
      publicationId: 'P1',
      outcome: 'already_current',
      tradeDate: '2026-09-07',
      scoreVersion: 'v1',
      freshness: null,
    },
    readback: { publication_id: 'P1', trade_date: '2026-09-07', freshness: 'stale' },
    previousPublicationId: 'P1',
  });
  assert.equal(verdict.state, 'waiting');
  assert.notEqual(verdict.messageKey, '已是最新可用日线');
});

test('R04 timeout while running stays unfinished', () => {
  assert.equal(actionStillRunning('running'), true);
  const verdict = interpretOwnerRefresh({
    actionStatus: 'running',
    timedOut: true,
    promised: { publicationId: null, outcome: '', tradeDate: null, scoreVersion: null, freshness: null },
    readback: { publication_id: 'P1', freshness: 'current' },
    previousPublicationId: 'P0',
  });
  assert.equal(verdict.state, 'running');
  assert.equal(verdict.messageKey, '后台任务仍在运行');
  assert.equal(verdict.commitResponse, false);
});

test('R04 matching published promise succeeds', () => {
  const verdict = interpretOwnerRefresh({
    actionStatus: 'completed',
    timedOut: false,
    promised: {
      publicationId: 'P2',
      outcome: 'published',
      tradeDate: '2026-09-08',
      scoreVersion: 'v1',
      freshness: null,
    },
    readback: {
      publication_id: 'P2',
      trade_date: '2026-09-08',
      stored_score_version: 'v1',
      freshness: 'current',
    },
    previousPublicationId: 'P1',
  });
  assert.equal(verdict.state, 'done');
  assert.equal(verdict.messageKey, '日线与评分已更新');
});

test('R05 silent verify cannot steal a newer request generation', () => {
  assert.equal(
    silentScanMayCommit({
      verifySeq: 1,
      currentVerifySeq: 1,
      requestSeqAtStart: 3,
      currentRequestSeq: 4,
      sessionAtStart: 1,
      currentSession: 1,
      filters: filtersA,
      applied: filtersA,
    }),
    false,
  );
  assert.equal(
    silentScanMayCommit({
      verifySeq: 2,
      currentVerifySeq: 2,
      requestSeqAtStart: 4,
      currentRequestSeq: 4,
      sessionAtStart: 1,
      currentSession: 1,
      filters: filtersB,
      applied: filtersB,
    }),
    true,
  );
});

test('R05 owner refresh cannot overwrite a newer filter request', () => {
  assert.equal(
    refreshMayCommitResults({
      refreshSeq: 1,
      currentRefreshSeq: 1,
      sessionAtStart: 1,
      currentSession: 1,
      requestSeqAtStart: 2,
      currentRequestSeq: 3,
    }),
    false,
  );
  assert.equal(
    refreshMayCommitResults({
      refreshSeq: 1,
      currentRefreshSeq: 1,
      sessionAtStart: 1,
      currentSession: 1,
      requestSeqAtStart: 3,
      currentRequestSeq: 3,
    }),
    true,
  );
});

test('R07 four-digit and five-digit codes match; quotes bind by code', () => {
  assert.equal(codesMatch('7203', '72030'), true);
  assert.equal(codesMatch('6758', '72030'), false);
  const quotes = { 72030: { price: 12 }, 67580: { price: 99 } };
  assert.equal(pickQuoteForCode(quotes, '7203').price, 12);
  assert.equal(pickQuoteForCode(quotes, '9984'), null);
});

test('R07 alphanumeric display codes bind to their complete canonical identity', () => {
  for (const [display, canonical] of [['285A', '285A0'], ['130A', '130A0'], ['7203', '72030']]) {
    assert.equal(codesMatch(display, canonical), true);
    assert.equal(codesMatch(canonical, display), true);
    assert.equal(payloadMatchesCode(canonical, display), true);
  }
  assert.equal(codesMatch(' 285a ', '285A0'), true);
  assert.equal(codesMatch('285A.T', '285A0'), true);
  assert.equal(codesMatch('7203.JP', '72030'), true);
});

test('R07 letters and meaningful fifth characters distinguish different securities', () => {
  for (const [left, right] of [
    ['285A', '285B'],
    ['285A0', '285B0'],
    ['285A0', '2850'],
    ['130A0', '1300'],
    ['7203', '72031'],
    ['285A', '285A1'],
    ['285A0', '285A1'],
  ]) {
    assert.equal(codesMatch(left, right), false, `${left} must not match ${right}`);
    assert.equal(codesMatch(right, left), false, `${right} must not match ${left}`);
    assert.equal(payloadMatchesCode(left, right), false);
  }
  assert.equal(codesMatch('285A1', '285A1'), true);
});

test('R07 malformed codes cannot acquire another security identity by losing characters', () => {
  for (const code of [null, undefined, '', '285', '285A00', 'TOYOTA', 'x72030', '72-03', '72 03']) {
    assert.equal(codesMatch(code, '72030'), false);
    assert.equal(codesMatch(code, code), false);
  }
});

test('R07 quote selection ignores digit collisions and preserves alphanumeric aliases', () => {
  const expected = { price: 1234 };
  const quotes = {
    '285B0': { price: 9876 },
    '2850': { price: 9999 },
    '285A1': { price: 8888 },
    '285A0': expected,
  };
  assert.equal(pickQuoteForCode(quotes, '285A'), expected);
  assert.equal(pickQuoteForCode(quotes, ' 285a '), expected);
  assert.equal(pickQuoteForCode({ '285B0': quotes['285B0'], '2850': quotes['2850'] }, '285A0'), null);
  assert.equal(pickQuoteForCode({ '72031': { price: 5678 } }, '7203'), null);
  assert.equal(pickQuoteForCode({ '285A': null, '285A0': expected }, '285A'), expected);
  assert.equal(pickQuoteForCode({ '72-03': expected }, '72-03'), null);
});
