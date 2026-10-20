import { t } from '../i18n/core.ts';
import { apiHeaders, fetchBuffered, parseRetryAfter, ResponseLimitError, TransportTimeoutError } from './transport.ts';
export interface ApiErrorShape {
  code: number;
  message: string;
}

/**
 * 统一错误对象（对齐后端契约 {code, message, retryable, retry_after}）
 * - code: HTTP 状态码；bizCode: 后端业务码（如 analysis_required / version_conflict /
 *   login_cooldown / public_snapshot_unavailable / rate_limited）
 * - retryAfter: 秒（Retry-After 头或 body.retry_after_seconds）
 */
export class ApiError extends Error implements ApiErrorShape {
  code: number;
  bizCode?: string;
  retryable?: boolean;
  retryAfter?: number;
  payload?: unknown;
  constructor(code: number, message: string, extras?: { bizCode?: string; retryable?: boolean; retryAfter?: number; payload?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.bizCode = extras?.bizCode;
    this.retryable = extras?.retryable;
    this.retryAfter = extras?.retryAfter;
    this.payload = extras?.payload;
  }
}

const BASE = '/api';

/**
 * 任一主体（管理员或客户）会话失效（审计 P1-08）。
 *
 * 旧事件名只覆盖管理员，于是客户接口返回的 account_login_required 不触发任何
 * 降级：页面继续显示客户用户名和自选管理按钮，请求持续 401。两种主体现在共用
 * 同一条降级通路，由 AccessProvider 重新拉取 /access/status 得出权威结论。
 */
export const PRINCIPAL_INVALID_EVENT = 'optixjp:principal-invalid';

/**
 * 会让前端认定「当前主体已失效」的业务码。两种主体都要覆盖：owner（所有者会话）
 * 与 account（客户账号会话）。缺了 account_login_required 时，客户会话过期不会触发
 * 降级，页面继续显示已登录状态和自选管理按钮而请求持续 401。
 */
const PRINCIPAL_INVALID_CODES = new Set(['owner_login_required', 'account_login_required']);

export function notifyPrincipalInvalid(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(PRINCIPAL_INVALID_EVENT));
  }
}

/**
 * 单次请求超时（审计 P1-10）。
 *
 * fetch 没有默认超时，而 marketRead 会把同一路径的 Promise 放进 inFlight 共享；
 * 半开连接或代理不终止请求时，该路径的所有页面会永远等同一个 Promise，手动刷新
 * 也不会发起新请求，界面永久停在骨架屏且没有任何错误提示。
 */
export const REQUEST_TIMEOUT_MS = 20_000;

function pick(obj: unknown, ...keys: string[]): unknown {
  if (obj && typeof obj === 'object') {
    for (const k of keys) {
      const v = (obj as Record<string, unknown>)[k];
      if (v !== undefined && v !== null) return v;
    }
  }
  return undefined;
}

/**
 * 查询参数序列化（契约 §0：undefined/null/空串不发出；数组重复键；布尔 → true/false）
 * 返回不含前导 `?` 的串；无参数时返回空串。
 */
export function toQuery(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item === undefined || item === null || item === '') continue;
        p.append(k, String(item));
      }
      continue;
    }
    p.set(k, String(v));
  }
  return p.toString();
}

export interface RequestOptions extends RequestInit {
  /** 覆盖默认超时；长任务轮询可单独放宽。传 0 表示不超时。 */
  timeoutMs?: number;
  /** 条件请求:304 Not Modified 不作为错误抛出,原样返回 Response。 */
  acceptNotModified?: boolean;
}

/** live 模式请求（返回原始 Response 供需要读头的场景，如 202 Location） */
export async function requestRaw(path: string, init?: RequestOptions): Promise<Response> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const isWrite = method !== 'GET' && method !== 'HEAD';
  const { timeoutMs, acceptNotModified, ...rest } = init ?? {};
  const budget = timeoutMs ?? REQUEST_TIMEOUT_MS;
  let res: Response;
  try {
    res = await fetchBuffered(`${BASE}${path}`, {
      credentials: 'include',
      redirect: 'error',
      ...rest,
      headers: apiHeaders(rest.headers, isWrite),
    }, budget);
  } catch (error) {
    if (error instanceof TransportTimeoutError) {
      throw new ApiError(408, t('请求超时，请重试'), {
        bizCode: 'request_timeout',
        retryable: true,
      });
    }
    if (error instanceof ResponseLimitError) {
      throw new ApiError(502, t('响应数据过大，请缩小查询范围'), {
        bizCode: 'response_too_large',
        retryable: false,
      });
    }
    throw error;
  }
  if (res.status === 304 && acceptNotModified) {
    return res;
  }
  if (!res.ok) {
    let message = res.statusText || t('请求失败');
    let bizCode: string | undefined;
    let retryable: boolean | undefined;
    let retryAfter = parseRetryAfter(res.headers.get('Retry-After'));
    let payload: unknown;
    try {
      const body = (await res.json()) as Record<string, unknown>;
      payload = body;
      const errObj = (body?.error && typeof body.error === 'object' ? body.error : body) as Record<string, unknown>;
      const detail = body?.detail && typeof body.detail === 'object' ? (body.detail as Record<string, unknown>) : undefined;
      bizCode = String(
        pick(errObj, 'code') ?? pick(body, 'code') ?? (typeof body?.error === 'string' ? body.error : undefined) ?? (detail ? pick(detail, 'code') : undefined) ?? '',
      ) || undefined;
      const msg = pick(errObj, 'message') ?? pick(body, 'message') ?? (detail ? pick(detail, 'message') : undefined);
      if (typeof msg === 'string' && msg) message = msg;
      const r = pick(errObj, 'retryable');
      if (typeof r === 'boolean') retryable = r;
      const ra = pick(errObj, 'retry_after_seconds') ?? pick(errObj, 'retry_after');
      retryAfter = parseRetryAfter(ra) ?? retryAfter;
    } catch {
      /* ignore */
    }
    if (res.status === 401 && bizCode && PRINCIPAL_INVALID_CODES.has(bizCode)) {
      notifyPrincipalInvalid();
    }
    throw new ApiError(res.status, message, { bizCode, retryable, retryAfter, payload });
  }
  return res;
}

export async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const res = await requestRaw(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* 便捷封装一律透传 options：调用方需要能传 signal 与 timeoutMs，否则超时与
   取消只对直接使用 request() 的少数路径生效。 */
export function get<T>(path: string, options?: RequestOptions) {
  return request<T>(path, { ...options, method: 'GET' });
}
export function post<T>(path: string, body?: unknown, options?: RequestOptions) {
  return request<T>(path, {
    ...options,
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export function put<T>(path: string, body?: unknown, options?: RequestOptions) {
  return request<T>(path, {
    ...options,
    method: 'PUT',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export function patch<T>(path: string, body?: unknown, options?: RequestOptions) {
  return request<T>(path, {
    ...options,
    method: 'PATCH',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
/** 无请求体的删除；同源守卫只看 Origin 与 X-Optix-Action 头。 */
export function del<T>(path: string, options?: RequestOptions) {
  return request<T>(path, { ...options, method: 'DELETE' });
}
