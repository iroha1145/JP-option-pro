import type { StrengthScanResponse } from '@/api/types';
import type { ScanFilters } from '@/components/screener/types';

/** A successful GET is a filter/query, never proof of a new nightly publication. */
export function querySucceededAsNewComputation(response: StrengthScanResponse | null): boolean {
  return false && Boolean(response);
}

export function publicationMatches(
  response: StrengthScanResponse | null,
  expectedPublicationId: string | null | undefined,
): boolean {
  if (!response || !expectedPublicationId) return false;
  return response.publication_id === expectedPublicationId;
}

export function liveQuoteDoesNotProveScoreFresh(live: boolean, scoreFreshness?: string): boolean {
  if (!live) return scoreFreshness === 'current';
  return scoreFreshness === 'current';
}

export function filtersEqual(a: ScanFilters, b: ScanFilters): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function actionStillRunning(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running';
}

export function promisedPublication(action: Record<string, unknown> | null | undefined): {
  publicationId: string | null;
  outcome: string;
  tradeDate: string | null;
  scoreVersion: string | null;
  freshness: string | null;
} {
  const result = (action?.result ?? {}) as Record<string, unknown>;
  const radar = (result.radar ?? {}) as Record<string, unknown>;
  const publication = (radar.publication ?? {}) as Record<string, unknown>;
  return {
    publicationId: typeof publication.publication_id === 'string' ? publication.publication_id : null,
    outcome: String(result.outcome ?? radar.outcome ?? ''),
    tradeDate:
      (typeof publication.trade_date === 'string' && publication.trade_date) ||
      (typeof radar.target_date === 'string' && radar.target_date) ||
      null,
    scoreVersion: typeof publication.score_version === 'string' ? publication.score_version : null,
    freshness: typeof publication.freshness === 'string' ? publication.freshness : null,
  };
}

export type RefreshVerdict = {
  state: 'running' | 'waiting' | 'done' | 'error';
  messageKey: string;
  commitResponse: boolean;
};

const QUALITY_OK = new Set(['current']);

export function interpretOwnerRefresh(input: {
  actionStatus: string | null | undefined;
  timedOut: boolean;
  promised: ReturnType<typeof promisedPublication>;
  readback: StrengthScanResponse | null;
  previousPublicationId: string | null;
}): RefreshVerdict {
  const { actionStatus, timedOut, promised, readback, previousPublicationId } = input;
  if (timedOut && actionStillRunning(actionStatus)) {
    return { state: 'running', messageKey: '后台任务仍在运行', commitResponse: false };
  }
  if (actionStatus === 'failed' || promised.outcome === 'failed') {
    return { state: 'error', messageKey: '更新失败，已保留上次结果', commitResponse: false };
  }
  if (promised.outcome === 'waiting_input') {
    return { state: 'waiting', messageKey: '仍在等待供应商发布当日日线', commitResponse: true };
  }
  if (promised.outcome === 'retained') {
    return { state: 'waiting', messageKey: '覆盖不足，已保留上次完整发布', commitResponse: true };
  }
  if (promised.outcome === 'skipped') {
    return { state: 'waiting', messageKey: '本次未发布新评分', commitResponse: true };
  }
  if (!readback?.publication_id) {
    return { state: 'error', messageKey: '未能核验承诺发布', commitResponse: false };
  }
  if (promised.outcome === 'already_current') {
    if (promised.publicationId && !publicationMatches(readback, promised.publicationId)) {
      return { state: 'error', messageKey: '读回发布与任务承诺不一致', commitResponse: false };
    }
    if (promised.tradeDate && readback.trade_date && readback.trade_date !== promised.tradeDate) {
      return { state: 'error', messageKey: '读回发布与任务承诺不一致', commitResponse: false };
    }
    if (!QUALITY_OK.has(String(readback.freshness || ''))) {
      return { state: 'waiting', messageKey: freshnessNotCurrentMessage(readback.freshness), commitResponse: true };
    }
    return { state: 'done', messageKey: '已是最新可用日线', commitResponse: true };
  }
  if (promised.outcome === 'published') {
    if (!promised.publicationId) {
      return { state: 'error', messageKey: '未能核验承诺发布', commitResponse: false };
    }
    if (!publicationMatches(readback, promised.publicationId)) {
      return { state: 'error', messageKey: '读回发布与任务承诺不一致', commitResponse: false };
    }
    if (promised.tradeDate && readback.trade_date && readback.trade_date !== promised.tradeDate) {
      return { state: 'error', messageKey: '读回发布与任务承诺不一致', commitResponse: false };
    }
    if (promised.scoreVersion && readback.stored_score_version && readback.stored_score_version !== promised.scoreVersion) {
      return { state: 'error', messageKey: '读回发布与任务承诺不一致', commitResponse: false };
    }
    if (previousPublicationId && readback.publication_id === previousPublicationId) {
      return { state: 'error', messageKey: '任务已结束但读回仍是旧发布', commitResponse: false };
    }
    return { state: 'done', messageKey: '日线与评分已更新', commitResponse: true };
  }
  return { state: 'error', messageKey: '未能核验承诺发布', commitResponse: false };
}

export function freshnessNotCurrentMessage(freshness: string | null | undefined): string {
  if (freshness === 'stale') return '快照日期早于当前目标交易日，这是筛选结果不是新的日线计算';
  if (freshness === 'partial') return '输入不完整，不能当作最新日线';
  if (freshness === 'degraded') return '指数输入偏旧，股票评分可用但不是完整新鲜';
  if (freshness === 'unknown') return '日历覆盖未知，不能当作最新日线';
  if (freshness === 'incompatible') return '已保存评分版本与当前代码不一致';
  return '读回新鲜度不是当前，不能当作最新日线';
}

export function silentScanMayCommit(input: {
  verifySeq: number;
  currentVerifySeq: number;
  requestSeqAtStart: number;
  currentRequestSeq: number;
  sessionAtStart: number;
  currentSession: number;
  filters: ScanFilters;
  applied: ScanFilters;
}): boolean {
  if (input.verifySeq !== input.currentVerifySeq) return false;
  if (input.sessionAtStart !== input.currentSession) return false;
  if (input.currentRequestSeq !== input.requestSeqAtStart) return false;
  return filtersEqual(input.filters, input.applied);
}

export function refreshMayCommitResults(input: {
  refreshSeq: number;
  currentRefreshSeq: number;
  sessionAtStart: number;
  currentSession: number;
  requestSeqAtStart: number;
  currentRequestSeq: number;
}): boolean {
  if (input.refreshSeq !== input.currentRefreshSeq) return false;
  if (input.sessionAtStart !== input.currentSession) return false;
  return input.currentRequestSeq === input.requestSeqAtStart;
}
