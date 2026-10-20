import test from 'node:test';
import assert from 'node:assert/strict';
import { dropQueryRegistry, invalidateQueryPaths, registryGet } from '../src/api/queryRegistry.ts';

const { Headers, Response } = globalThis;

const json = (value, headers = {}) => new Response(JSON.stringify(value), { headers });
test.beforeEach(() => dropQueryRegistry());
test.afterEach(() => dropQueryRegistry());

test('concurrent requests and fresh reads share the same response', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => json({ count: 7 }));
  const [first, second] = await Promise.all([registryGet('/radar/current'), registryGet('/radar/current')]);
  assert.equal(first, second);
  assert.equal(await registryGet('/radar/current'), first);
  assert.equal(fetch.mock.callCount(), 1);
});

test('refresh prevents an earlier response from replacing the new cache', async (t) => {
  let release;
  let calls = 0;
  t.mock.method(globalThis, 'fetch', () => ++calls === 1
    ? new Promise((resolve) => { release = () => resolve(json({ version: 'old' })); })
    : Promise.resolve(json({ version: 'new' })));
  const old = registryGet('/radar/current');
  invalidateQueryPaths(['/radar/current'], { reload: true });
  const current = await registryGet('/radar/current');
  release();
  await old;
  assert.equal(current.version, 'new');
  assert.equal(await registryGet('/radar/current'), current);
});

test('a late 304 resolves its original value after a forced refresh', async (t) => {
  let now = 1_000_000;
  let release;
  let calls = 0;
  t.mock.method(Date, 'now', () => now);
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    calls++;
    if (calls === 1) return json({ version: 'old' }, { ETag: '"old"' });
    if (calls === 2) {
      assert.equal(new Headers(init.headers).get('If-None-Match'), '"old"');
      return new Promise((resolve) => { release = () => resolve(new Response(null, { status: 304 })); });
    }
    assert.equal(init.cache, 'reload');
    return json({ version: 'new' }, { ETag: '"new"' });
  });
  await registryGet('/radar/current');
  now += 120_001;
  const validating = registryGet('/radar/current');
  invalidateQueryPaths(['/radar/current'], { reload: true });
  const current = await registryGet('/radar/current');
  release();
  assert.deepEqual(await validating, { version: 'old' });
  assert.equal(await registryGet('/radar/current'), current);
});

test('identity changes discard in-flight cache writes', async (t) => {
  let release;
  let calls = 0;
  t.mock.method(globalThis, 'fetch', () => ++calls === 1
    ? new Promise((resolve) => { release = () => resolve(json({ owner: 'old' })); })
    : Promise.resolve(json({ owner: 'new' })));
  const old = registryGet('/settings');
  dropQueryRegistry();
  const current = await registryGet('/settings');
  release();
  await old;
  assert.equal(await registryGet('/settings'), current);
  assert.equal(current.owner, 'new');
});
