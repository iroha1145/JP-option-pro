/**
 * Local-first algorithm preferences and A0 view compatibility.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const memory = new Map();
globalThis.window = {
  localStorage: {
    getItem(key) {
      return memory.has(key) ? memory.get(key) : null;
    },
    setItem(key, value) {
      memory.set(key, String(value));
    },
    removeItem(key) {
      memory.delete(key);
    },
  },
};

const {
  DEFAULT_ALGORITHM_PREFERENCES,
  SCREENER_A0,
  a0ViewSupported,
  algorithmPreferencePendingSync,
  markAlgorithmPreferencePendingSync,
  preferenceStorageKey,
  readAlgorithmPreferences,
  writeAlgorithmPreferences,
} = await import('../src/lib/algorithmPreferences.ts');

const here = path.dirname(fileURLToPath(import.meta.url));

async function source(relativePath) {
  return readFile(path.resolve(here, '..', 'src', relativePath), 'utf8');
}

test('default remains follow_default, not A0 or T1', () => {
  assert.deepEqual(DEFAULT_ALGORITHM_PREFERENCES, {
    screenerRankingAlgorithm: 'follow_default',
    radarSortAlgorithm: 'follow_default',
  });
});

test('A0 is only legal on all + balanced', () => {
  assert.equal(a0ViewSupported('all', 'balanced'), true);
  assert.equal(a0ViewSupported('mid', 'balanced'), false);
  assert.equal(a0ViewSupported('all', 'aggressive'), false);
});

test('writes stay scoped to the principal and keep the other family', () => {
  writeAlgorithmPreferences({ screenerRankingAlgorithm: SCREENER_A0 }, 'owner');
  writeAlgorithmPreferences({ radarSortAlgorithm: 't1_daily_priority' }, 'account:alice');
  const owner = readAlgorithmPreferences('owner');
  const alice = readAlgorithmPreferences('account:alice');
  assert.equal(owner.screenerRankingAlgorithm, SCREENER_A0);
  assert.equal(owner.radarSortAlgorithm, 'follow_default');
  assert.equal(alice.radarSortAlgorithm, 't1_daily_priority');
  assert.equal(alice.screenerRankingAlgorithm, 'follow_default');
  assert.notEqual(preferenceStorageKey('owner'), preferenceStorageKey('account:alice'));
});

test('pending sync is local-first and does not clear the choice', () => {
  writeAlgorithmPreferences({ screenerRankingAlgorithm: SCREENER_A0 }, 'visitor');
  markAlgorithmPreferencePendingSync('visitor', true);
  assert.equal(algorithmPreferencePendingSync('visitor'), true);
  assert.equal(readAlgorithmPreferences('visitor').screenerRankingAlgorithm, SCREENER_A0);
  markAlgorithmPreferencePendingSync('visitor', false);
  assert.equal(algorithmPreferencePendingSync('visitor'), false);
});

test('screener ordinary scan does not force cache reload; owner refresh does', async () => {
  const screener = await source('pages/Screener.tsx');
  assert.match(screener, /strengthApi\.scan\(buildParams\(readFilters\), \{ cache: 'reload' \}\)/);
  assert.match(screener, /invalidateQueryPaths\(\['\/strength\/scan', '\/radar\/current'\], \{ reload: true \}\)/);
  const ordinary = screener.match(
    /const runScan = useCallback\(async[\s\S]*?strengthApi\.scan\(buildParams\(filters\), ([^)]*)\)/,
  );
  assert.ok(ordinary, 'runScan must call strengthApi.scan');
  assert.match(ordinary[1], /opts\?\.cache/);
  assert.doesNotMatch(ordinary[1], /'reload'/);
});

test('radar owner refresh binds the action then invalidates publication paths', async () => {
  const radar = await source('pages/Radar.tsx');
  assert.match(radar, /workerApi\.trigger\('radar_refresh'\)/);
  assert.match(radar, /workerApi\.action\(actionId\)/);
  assert.match(radar, /invalidateQueryPaths\(\['\/radar\/current'\], \{ reload: true \}\)/);
  assert.match(radar, /sort_algorithm: sortAlgorithm/);
});
