/** 同路径请求共享内存值；身份切换、手动刷新使旧请求失效。 */
import { requestRaw } from './client.ts';

// 日线数据按分钟复用；刷新动作会主动失效这些窗口。
const QUERY_TTL_MS: Record<string, number> = {
  '/market/overview': 120_000,
  '/radar/current': 120_000,
  '/earnings/calendar': 300_000,
  '/earnings/recent': 300_000,
  '/data-status': 60_000,
  '/settings': 300_000,
  '/worker/status': 15_000,
};

interface Entry {
  inFlight: Promise<unknown> | null;
  value: unknown;
  etag: string | null;
  fetchedAt: number;
  generation: number;
  forceReload: boolean;
}

const entries = new Map<string, Entry>();

function entryFor(path: string): Entry {
  let entry = entries.get(path);
  if (!entry) {
    entry = { inFlight: null, value: undefined, etag: null, fetchedAt: 0, generation: 0, forceReload: false };
    entries.set(path, entry);
  }
  return entry;
}

async function fetchInto(path: string, entry: Entry): Promise<unknown> {
  const generation = entry.generation;
  const reload = entry.forceReload;
  entry.forceReload = false;
  const conditional = reload ? null : entry.etag;
  const conditionalValue = entry.value;
  const response = await requestRaw(path, {
    method: 'GET',
    ...(reload ? { cache: 'reload' as RequestCache } : {}),
    acceptNotModified: Boolean(conditional),
    headers: conditional ? { 'If-None-Match': conditional } : {},
  });
  if (response.status === 304) {
    if (entry.generation === generation) entry.fetchedAt = Date.now();
    // 刷新可能已经替换 entry.value；304 确认的是发请求时的那份值。
    return conditionalValue;
  }
  const data: unknown = response.status === 204 ? undefined : await response.json();
  if (entry.generation === generation) {
    entry.value = data;
    entry.etag = response.headers.get('ETag');
    entry.fetchedAt = Date.now();
  }
  return data;
}

export function registryGet<T>(path: string): Promise<T> {
  const ttlMs = QUERY_TTL_MS[path];
  if (ttlMs === undefined) {
    return requestRaw(path, { method: 'GET' }).then((response) => response.json() as Promise<T>);
  }
  const entry = entryFor(path);
  if (entry.value !== undefined && Date.now() - entry.fetchedAt < ttlMs) {
    return Promise.resolve(entry.value as T);
  }
  if (entry.inFlight) return entry.inFlight as Promise<T>;
  const pending = fetchInto(path, entry).finally(() => {
    if (entry.inFlight === pending) entry.inFlight = null;
  });
  entry.inFlight = pending;
  return pending as Promise<T>;
}

export function invalidateQueryPaths(prefixes: string[], options?: { reload?: boolean }): void {
  for (const [path, entry] of entries) {
    if (!prefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(`${prefix}?`))) continue;
    entry.generation += 1;
    entry.value = undefined;
    entry.etag = null;
    entry.fetchedAt = 0;
    entry.inFlight = null;
    if (options?.reload) entry.forceReload = true;
  }
}

/** 登录、登出、账号切换时调用；旧响应仍可返回，但不能再写进缓存。 */
export function dropQueryRegistry(): void {
  for (const entry of entries.values()) entry.generation += 1;
  entries.clear();
}
