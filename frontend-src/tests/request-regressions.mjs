import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, request, requestRaw } from '../src/api/client.ts';

const { AbortController, Headers, ReadableStream, Response, TextEncoder, setTimeout, clearTimeout, queueMicrotask } = globalThis;

for (const status of [200, 503]) {
  test(`request deadline includes the ${status} response body`, async (t) => {
    let timer;
    let cancelled = false;
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{'));
        timer = setTimeout(() => {
          controller.enqueue(new TextEncoder().encode('"ok":true}'));
          controller.close();
        }, 150);
      },
      cancel() { clearTimeout(timer); cancelled = true; },
    });
    t.mock.method(globalThis, 'fetch', async () => new Response(stream, { status }));
    await assert.rejects(request('/test', { timeoutMs: 20 }), (error) =>
      error instanceof ApiError && error.code === 408 && error.bizCode === 'request_timeout');
    assert.equal(cancelled, true);
  });
}

test('Headers and tuple inputs preserve conditional headers and the write guard', async (t) => {
  const seen = [];
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    seen.push(new Headers(init.headers));
    return new Response('{}');
  });
  for (const headers of [new Headers({ 'If-None-Match': '"v1"' }), [['If-None-Match', '"v1"']]]) {
    await request('/test', { method: 'POST', headers });
  }
  for (const headers of seen) {
    assert.equal(headers.get('If-None-Match'), '"v1"');
    assert.equal(headers.get('X-Optix-Action'), '1');
  }
});

test('non-JSON failures retain an HTTP-date Retry-After header', async (t) => {
  t.mock.method(Date, 'now', () => Date.UTC(2026, 9, 20, 0, 0, 0));
  t.mock.method(globalThis, 'fetch', async () => new Response('temporarily unavailable', {
    status: 503,
    headers: { 'Retry-After': 'Tue, 20 Oct 2026 00:01:00 GMT' },
  }));
  await assert.rejects(request('/test'), (error) => error.code === 503 && error.retryAfter === 60);
});

test('caller cancellation stays active while the response body downloads', async (t) => {
  const abort = new AbortController();
  let timer;
  let cancelled = false;
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) {
      timer = setTimeout(() => { controller.enqueue(new TextEncoder().encode('{}')); controller.close(); }, 150);
      queueMicrotask(() => abort.abort());
    },
    cancel() { clearTimeout(timer); cancelled = true; },
  })));
  await assert.rejects(request('/test', { timeoutMs: 0, signal: abort.signal }), { name: 'AbortError' });
  assert.equal(cancelled, true);
});

test('conditional 304 and empty 204 responses retain their contracts', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 304 }));
  assert.equal((await requestRaw('/test', { acceptNotModified: true })).status, 304);
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }));
  assert.equal(await request('/test'), undefined);
});
