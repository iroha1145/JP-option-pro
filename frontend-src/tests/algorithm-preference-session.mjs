/**
 * Real preference write queue + revision guards used by Screener/Radar.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

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
  SCREENER_A0,
  SCREENER_PRODUCTION,
  RADAR_T1,
  RADAR_PRODUCTION,
  bumpAlgorithmPreferenceRevision,
  algorithmPreferenceRevision,
  markAlgorithmPreferencePendingSync,
  readAlgorithmPreferences,
  shouldApplyRemotePreference,
  shouldApplyFetchedPreferences,
  bumpPreferenceIdentityEpoch,
  currentPreferenceIdentityEpoch,
  resetPreferenceIdentityEpoch,
  canCommitPreferenceWriteResult,
  writeAlgorithmPreferences,
} = await import('../src/lib/algorithmPreferences.ts');
const {
  bindPreferenceWritePrincipal,
  currentPreferenceWriteGeneration,
  invalidatePreferenceWriteQueue,
  persistRemoteOrKeepLocal,
  resetPreferenceWriteQueue,
} = await import('../src/lib/viewPreferenceWrites.ts');

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('Alice queued writes abort after identity switch and never dispatch as Bob', async () => {
  resetPreferenceWriteQueue();
  bindPreferenceWritePrincipal('account:alice');
  const dispatched = [];
  const first = persistRemoteOrKeepLocal(
    { screenerRankingAlgorithm: SCREENER_A0 },
    async (signal) => {
      await delay(40);
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      dispatched.push('alice-1');
      return { screenerRankingAlgorithm: SCREENER_A0 };
    },
    { principal: 'account:alice', generation: currentPreferenceWriteGeneration() },
  );
  const second = persistRemoteOrKeepLocal(
    { screenerRankingAlgorithm: SCREENER_PRODUCTION },
    async (signal) => {
      await delay(40);
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      dispatched.push('alice-2');
      return { screenerRankingAlgorithm: SCREENER_PRODUCTION };
    },
    { principal: 'account:alice', generation: currentPreferenceWriteGeneration() },
  );
  invalidatePreferenceWriteQueue();
  bindPreferenceWritePrincipal('account:bob');
  const [one, two] = await Promise.all([first, second]);
  assert.equal(one.persisted, false);
  assert.equal(two.persisted, false);
  assert.deepEqual(dispatched, []);
});

test('late GET after local write cannot restore an older remote choice', async () => {
  writeAlgorithmPreferences({ screenerRankingAlgorithm: SCREENER_PRODUCTION }, 'account:alice');
  const started = algorithmPreferenceRevision('account:alice');
  writeAlgorithmPreferences({ screenerRankingAlgorithm: SCREENER_A0 }, 'account:alice');
  bumpAlgorithmPreferenceRevision('account:alice');
  markAlgorithmPreferencePendingSync('account:alice', true);
  const remote = { screener_ranking_algorithm: SCREENER_PRODUCTION };
  markAlgorithmPreferencePendingSync('account:alice', false);
  assert.equal(shouldApplyRemotePreference('account:alice', started), false);
  assert.equal(readAlgorithmPreferences('account:alice').screenerRankingAlgorithm, SCREENER_A0);
  assert.equal(remote.screener_ranking_algorithm, SCREENER_PRODUCTION);
});

test('late Alice GET cannot apply after Bob identity epoch advances', () => {
  resetPreferenceIdentityEpoch();
  writeAlgorithmPreferences({ radarSortAlgorithm: RADAR_T1 }, 'account:alice');
  writeAlgorithmPreferences({ radarSortAlgorithm: RADAR_PRODUCTION }, 'account:bob');
  const aliceRevision = algorithmPreferenceRevision('account:alice');
  const aliceEpoch = currentPreferenceIdentityEpoch();
  bumpPreferenceIdentityEpoch();
  assert.equal(
    shouldApplyFetchedPreferences('account:alice', aliceRevision, 'account:alice-db-id', {
      startedEpoch: aliceEpoch,
      currentEpoch: currentPreferenceIdentityEpoch(),
      currentPrincipal: 'account:bob',
    }),
    false,
  );
  assert.equal(readAlgorithmPreferences('account:bob').radarSortAlgorithm, RADAR_PRODUCTION);
});

test('logout epoch rejects a late signed-in GET', () => {
  resetPreferenceIdentityEpoch();
  const started = algorithmPreferenceRevision('account:alice');
  const startedEpoch = currentPreferenceIdentityEpoch();
  bumpPreferenceIdentityEpoch();
  assert.equal(
    shouldApplyFetchedPreferences('account:alice', started, 'account:alice-db-id', {
      startedEpoch,
      currentEpoch: currentPreferenceIdentityEpoch(),
      currentPrincipal: 'visitor',
    }),
    false,
  );
});

test('same-principal write still applies when epoch is unchanged', async () => {
  resetPreferenceWriteQueue();
  resetPreferenceIdentityEpoch();
  bindPreferenceWritePrincipal('account:bob');
  const startedEpoch = currentPreferenceIdentityEpoch();
  const result = await persistRemoteOrKeepLocal(
    { radarSortAlgorithm: RADAR_PRODUCTION },
    async () => ({ radarSortAlgorithm: RADAR_PRODUCTION }),
    { principal: 'account:bob', generation: currentPreferenceWriteGeneration() },
  );
  assert.equal(result.persisted, true);
  assert.equal(
    canCommitPreferenceWriteResult(startedEpoch, 'account:bob', 'account:bob'),
    true,
  );
});

test('503 keeps explicit local intent and reports unsynced', async () => {
  resetPreferenceWriteQueue();
  bindPreferenceWritePrincipal('owner');
  writeAlgorithmPreferences({ screenerRankingAlgorithm: SCREENER_A0 }, 'owner');
  const result = await persistRemoteOrKeepLocal(
    { screenerRankingAlgorithm: SCREENER_A0 },
    async () => {
      const error = new Error('unavailable');
      error.status = 503;
      throw error;
    },
    { principal: 'owner', generation: currentPreferenceWriteGeneration() },
  );
  assert.equal(result.persisted, false);
  assert.equal(readAlgorithmPreferences('owner').screenerRankingAlgorithm, SCREENER_A0);
});
