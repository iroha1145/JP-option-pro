/**
 * Cache identity must include the algorithm and filter query, not just the path.
 * Stale in-flight responses must not overwrite a newer generation.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  normalizeQueryPath,
  persistedRecordWithinAge,
  queryConfigFor,
} from '../src/api/queryRegistry.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', 'src');

async function source(relativePath) {
  return readFile(path.join(src, relativePath), 'utf8');
}

test('normalizeQueryPath sorts keys so A0 and production are distinct identities', () => {
  const production = normalizeQueryPath('/strength/scan?top=20&ranking_algorithm=production');
  const a0 = normalizeQueryPath('/strength/scan?ranking_algorithm=a0_mid_long&top=20');
  const a0Shuffled = normalizeQueryPath('/strength/scan?top=20&ranking_algorithm=a0_mid_long');
  assert.equal(a0, a0Shuffled);
  assert.notEqual(production, a0);
  assert.match(a0, /ranking_algorithm=a0_mid_long/);
  assert.match(production, /ranking_algorithm=production/);
});

test('radar sort_algorithm and cursor are part of the identity', () => {
  const production = normalizeQueryPath('/radar/current?limit=200&sort_algorithm=production');
  const t1 = normalizeQueryPath('/radar/current?sort_algorithm=t1_daily_priority&limit=200');
  assert.notEqual(production, t1);
  const withCursor = normalizeQueryPath(
    '/radar/current?limit=200&sort_algorithm=t1_daily_priority&cursor=abc',
  );
  assert.notEqual(t1, withCursor);
});

test('strength and radar current stay on the persist whitelist', () => {
  assert.ok(queryConfigFor('/strength/scan?ranking_algorithm=a0_mid_long')?.persist);
  assert.ok(queryConfigFor('/radar/current?sort_algorithm=t1_daily_priority')?.persist);
  assert.equal(queryConfigFor('/view-preferences'), null);
});

test('restore age uses last validation, not first store', () => {
  const config = { maxRestoreAgeMs: 1000 };
  assert.equal(
    persistedRecordWithinAge(config, { storedAt: 0, validatedAt: 2000 }, 2500),
    true,
  );
  assert.equal(
    persistedRecordWithinAge(config, { storedAt: 0, validatedAt: 1000 }, 2500),
    false,
  );
});

test('modules and registry keep parameterized identity, not a bare path key', async () => {
  const registry = await source('api/queryRegistry.ts');
  const modules = await source('api/modules.ts');
  assert.match(registry, /function pathNameOf/);
  assert.match(registry, /function normalizeQueryPath/);
  assert.match(registry, /function pathMatchesPrefix/);
  assert.match(registry, /entryFor\(identity\)/);
  assert.match(registry, /deletePersisted\(identity\)/);
  assert.match(modules, /registryGet<StrengthScanResponse>\(path\)/);
  assert.match(modules, /ranking_algorithm\?:/);
  assert.match(modules, /sort_algorithm\?:/);
  assert.match(modules, /registryGet\(`\/radar\/current\?\$\{query\}`\)/);
  assert.doesNotMatch(
    modules,
    /strengthApi[\s\S]{0,400}get\(`\/strength\/scan/,
  );
});
