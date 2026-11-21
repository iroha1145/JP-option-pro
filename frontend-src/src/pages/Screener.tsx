/**
 * §04 选股扫描（强度）— 对标美版 Screener 页。
 * B0 页头带（数据截至 / 扫描历史 popover / 轻量重扫）
 * B1 筛选工作台（分档/预设/周期/偏好/TopN/业种/价格/成交额 + 扫描钮 dirty 脉冲）
 * B2 结果区（统计行 + 参数回显 chips + 三态排序 + 结果表/卡片流 + 行展开）
 * B3 右侧栏（市场形态 6 维 / 强度剖面 / 评分方法）
 * 与美版的差异（更强的口径）：所有条件在服务端对完整已评分池生效——
 * 无「客户端条件只作用于前 N 名」问题；新闻摘要一次批量取回。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { newsApi, quotesApi, strengthApi, workerApi, type StrengthScanParams } from '@/api/modules';
import { ApiError } from '@/api/client';
import type { StrengthProfilesMeta, StrengthScanResponse, StrengthRow } from '@/api/types';
import { useAccess } from '@/hooks/useAccess';
import PageHeader from '@/components/shared/PageHeader';
import Segmented from '@/components/shared/Segmented';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import SoftBadge from '@/components/shared/SoftBadge';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import { DataThrough } from '@/components/domain';
import Icon from '@/components/icons';
import PointerTooltip from '@/components/shared/PointerTooltip';
import FilterWorkbench from '@/components/screener/FilterWorkbench';
import ResultTable from '@/components/screener/ResultTable';
import ResultCards from '@/components/screener/ResultCards';
import ScanHistoryPopover from '@/components/screener/ScanHistoryPopover';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import { MarketRegimeCard, MethodCard, TierHistogram } from '@/components/screener/SideCards';
import {
  DEFAULT_FILTERS,
  MAX_TOP_N,
  PROFILE_CN,
  SORT_CN,
  TIMEFRAME_CN,
  TURNOVER_OPTIONS,
  tierCountsFromDistribution,
  tierOf,
  type NewsSummaryMap,
  type ScanFilters,
  type ScanHistoryEntry,
  type SortMode,
  type Tier,
  type TierFilter,
} from '@/components/screener/types';
import { t } from '@/i18n/core';
import { usePolling } from '@/hooks/usePolling';
import { useTickFlash } from '@/hooks/useTickFlash';
import { quoteSourceLabel } from '@/lib/quoteSource';
import { fmtTimeHHMMSS, fmtYenCompact, fmtJstTime } from '@/lib/format';
import {
  filtersEqual,
  interpretOwnerRefresh,
  promisedPublication,
  refreshMayCommitResults,
  silentScanMayCommit,
} from '@/components/screener/freshness';

const PAGE_SIZE = 20;

type ScanState = 'idle' | 'scanning' | 'done' | 'error';

function buildParams(filters: ScanFilters): StrengthScanParams {
  return {
    timeframe: filters.timeframe,
    profile: filters.profile,
    top: filters.topN > 0 ? filters.topN : MAX_TOP_N,
    sector_id: filters.sectors.length > 0 ? filters.sectors.join(',') : undefined,
    min_price: filters.priceMin ?? undefined,
    max_price: filters.priceMax ?? undefined,
    min_avg_turnover: filters.minTurnover > 0 ? filters.minTurnover : undefined,
    tier: filters.tier !== 'all' ? filters.tier : undefined,
    min_score: filters.minScore ?? undefined,
  };
}

function summarizeFilters(filters: ScanFilters): string {
  const parts: string[] = [];
  if (filters.tier !== 'all') parts.push(`${filters.tier} ${t('档')}`);
  if (filters.timeframe !== 'all') parts.push(TIMEFRAME_CN[filters.timeframe]);
  parts.push(PROFILE_CN[filters.profile]);
  if (filters.topN > 0) parts.push(`Top ${filters.topN}`);
  if (filters.sectors.length > 0) parts.push(t('行业 {n} 项', { n: filters.sectors.length }));
  if (filters.priceMin !== null || filters.priceMax !== null) parts.push(t('价格区间'));
  if (filters.minTurnover > 0) parts.push(t('成交额≥{v}', { v: fmtYenCompact(filters.minTurnover) }));
  if (filters.minScore !== null) parts.push(t('强度≥{n}', { n: filters.minScore }));
  return parts.join(' · ') || t('默认条件');
}

export default function Screener() {
  const { canManageWatchlist, isOwner, accountUsername, loading: accessLoading } = useAccess();

  const [meta, setMeta] = useState<StrengthProfilesMeta | null>(null);
  const [metaFailed, setMetaFailed] = useState(false);
  const [draft, setDraft] = useState<ScanFilters>(DEFAULT_FILTERS);
  const [applied, setApplied] = useState<ScanFilters>(DEFAULT_FILTERS);
  const [scanState, setScanState] = useState<ScanState>('scanning');
  const [scanError, setScanError] = useState<ApiError | null>(null);
  const [response, setResponse] = useState<StrengthScanResponse | null>(null);
  const [scanDurationMs, setScanDurationMs] = useState(0);
  const [history, setHistory] = useState<ScanHistoryEntry[]>([]);
  const [sortMode, setSortMode] = useState<SortMode>('deterministic');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [news, setNews] = useState<NewsSummaryMap>({});
  const [newsLoaded, setNewsLoaded] = useState(false);
  const [refreshState, setRefreshState] = useState<'idle' | 'queued' | 'running' | 'waiting' | 'done' | 'error'>('idle');
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const requestSeq = useRef(0);
  const verifySeq = useRef(0);
  const refreshSeq = useRef(0);
  const sessionGen = useRef(0);
  const appliedRef = useRef(applied);
  appliedRef.current = applied;
  const sessionKey = `${isOwner}:${accountUsername ?? ''}`;

  const dirty = scanState === 'done' && !filtersEqual(draft, applied);

  const loadMeta = useCallback(() => {
    strengthApi
      .profiles()
      .then((data) => {
        setMeta(data);
        setMetaFailed(false);
      })
      .catch(() => setMetaFailed(true));
  }, []);
  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  /* 新闻72h摘要：一次批量取回（覆盖所有有新闻的股票）。 */
  useEffect(() => {
    let alive = true;
    newsApi
      .securities(72, { priority: 'low' })
      .then((data) => {
        if (!alive) return;
        const map: NewsSummaryMap = {};
        for (const row of data.rows) map[row.canonical_code] = row;
        setNews(map);
        setNewsLoaded(true);
      })
      .catch(() => {
        if (alive) setNewsLoaded(true); // 失败按无数据处理：徽标显 0（新闻是附注不是评分输入）
      });
    return () => {
      alive = false;
    };
  }, []);

  const sessionKeyRef = useRef(sessionKey);
  useEffect(() => {
    if (sessionKeyRef.current === sessionKey) return;
    sessionKeyRef.current = sessionKey;
    sessionGen.current += 1;
    refreshSeq.current += 1;
    requestSeq.current += 1;
    verifySeq.current += 1;
    setRefreshState('idle');
    setRefreshMessage(null);
  }, [sessionKey]);

  useEffect(
    () => () => {
      sessionGen.current += 1;
      refreshSeq.current += 1;
    },
    [],
  );

  const runScan = useCallback(async (filters: ScanFilters, opts?: { silent?: boolean; cache?: RequestCache }) => {
    const sessionAtStart = sessionGen.current;
    const requestAtStart = opts?.silent ? requestSeq.current : ++requestSeq.current;
    const verifyAtStart = opts?.silent ? ++verifySeq.current : verifySeq.current;
    if (!opts?.silent) {
      setScanState('scanning');
      setScanError(null);
    }
    const startedAt = Date.now();
    try {
      const result = await strengthApi.scan(buildParams(filters), opts?.cache ? { cache: opts.cache } : undefined);
      if (opts?.silent) {
        if (
          !silentScanMayCommit({
            verifySeq: verifyAtStart,
            currentVerifySeq: verifySeq.current,
            requestSeqAtStart: requestAtStart,
            currentRequestSeq: requestSeq.current,
            sessionAtStart,
            currentSession: sessionGen.current,
            filters,
            applied: appliedRef.current,
          })
        ) {
          return false;
        }
        setResponse(result);
        setUnverified(false);
        return true;
      }
      if (requestSeq.current !== requestAtStart) return false;
      if (sessionGen.current !== sessionAtStart) return false;
      // A silent read may have started during this query with the same filters.
      // Once the explicit result lands, that older read must not replace it.
      verifySeq.current += 1;
      setResponse(result);
      setUnverified(false);
      setApplied(filters);
      setDraft(filters);
      setScanDurationMs(Date.now() - startedAt);
      setPage(1);
      setExpanded(null);
      setScanState('done');
      setHistory((prev) =>
        [
          { at: Date.now(), count: result.rows.length, durationMs: Date.now() - startedAt, summary: summarizeFilters(filters), kind: 'filter' as const },
          ...prev,
        ].slice(0, 5),
      );
      return true;
    } catch (error) {
      if (opts?.silent) {
        if (verifySeq.current !== verifyAtStart) return false;
        if (sessionGen.current !== sessionAtStart) return false;
        if (requestSeq.current !== requestAtStart) return false;
        setUnverified(true);
        return false;
      }
      if (requestSeq.current !== requestAtStart) return false;
      if (sessionGen.current !== sessionAtStart) return false;
      setScanError(error instanceof ApiError ? error : new ApiError(500, error instanceof Error ? error.message : t('扫描失败')));
      setScanState('error');
      return false;
    }
  }, []);

  /* Wait for the first identity, then also restart reads after an account
     change. Otherwise its generation guard drops the initial pending result
     without ever settling the page's scanning state. */
  useEffect(() => {
    if (accessLoading) return;
    void runScan(appliedRef.current, { cache: 'reload' });
  }, [accessLoading, sessionKey, runScan]);

  const onScanClick = useCallback(() => void runScan(draft), [draft, runScan]);

  const pollAction = useCallback(async (actionId: number, seq: number) => {
    const deadline = Date.now() + 90_000;
    let last: Record<string, unknown> | null = null;
    while (Date.now() < deadline) {
      if (refreshSeq.current !== seq) return { item: null, timedOut: false };
      const item = await workerApi.action(actionId);
      if (refreshSeq.current !== seq) return { item: null, timedOut: false };
      last = item as Record<string, unknown>;
      const status = String(item.status);
      if (status === 'completed' || status === 'failed') return { item, timedOut: false };
      setRefreshState(status === 'running' ? 'running' : 'queued');
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    return { item: last, timedOut: true };
  }, []);

  const onOwnerRefresh = useCallback(async () => {
    const seq = ++refreshSeq.current;
    const sessionAtStart = sessionGen.current;
    const requestAtStart = requestSeq.current;
    verifySeq.current += 1;
    setRefreshState('queued');
    setRefreshMessage(null);
    try {
      const accepted = await workerApi.trigger('post_close_batch');
      if (refreshSeq.current !== seq || sessionGen.current !== sessionAtStart) return;
      const actionId = accepted.action_id;
      if (actionId == null) {
        setRefreshState('error');
        setRefreshMessage(t('无法提交日线更新'));
        return;
      }
      const polled = await pollAction(actionId, seq);
      if (refreshSeq.current !== seq || sessionGen.current !== sessionAtStart) return;
      if (!polled.item && !polled.timedOut) {
        setRefreshState('error');
        setRefreshMessage(t('更新未完成'));
        return;
      }
      const finished = (polled.item ?? {}) as { status?: string; result?: Record<string, unknown> };
      const promised = promisedPublication(finished as Record<string, unknown>);
      const previousId = response?.publication_id ?? null;
      const readFilters = appliedRef.current;
      const verified = await strengthApi.scan(buildParams(readFilters), { cache: 'reload' });
      if (refreshSeq.current !== seq || sessionGen.current !== sessionAtStart) return;
      const verdict = interpretOwnerRefresh({
        actionStatus: String(finished.status ?? ''),
        timedOut: polled.timedOut,
        promised,
        readback: verified,
        previousPublicationId: previousId,
      });
      setRefreshState(verdict.state);
      setRefreshMessage(t(verdict.messageKey));
      const mayCommit = refreshMayCommitResults({
        refreshSeq: seq,
        currentRefreshSeq: refreshSeq.current,
        sessionAtStart,
        currentSession: sessionGen.current,
        requestSeqAtStart: requestAtStart,
        currentRequestSeq: requestSeq.current,
      });
      if (verdict.commitResponse && mayCommit) {
        // Only replace an earlier query after a usable readback. Failed owner
        // updates must leave an unfinished initial query able to settle.
        requestSeq.current += 1;
        verifySeq.current += 1;
        setResponse(verified);
        setScanState('done');
        setScanError(null);
        setUnverified(false);
        if (verdict.state === 'done' && promised.outcome === 'published') {
          setHistory((prev) =>
            [
              { at: Date.now(), count: verified.rows.length, durationMs: 0, summary: t('后台更新读回'), kind: 'refresh' as const },
              ...prev,
            ].slice(0, 5),
          );
        }
      }
    } catch (error) {
      if (refreshSeq.current !== seq) return;
      if (sessionGen.current !== sessionAtStart) return;
      setRefreshState('error');
      setRefreshMessage(error instanceof ApiError ? error.message : t('更新失败，已保留上次结果'));
    }
  }, [pollAction, response]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      void runScan(applied, { silent: true, cache: 'reload' });
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      void runScan(applied, { silent: true, cache: 'reload' });
    }, 120_000);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [applied, runScan]);

  const patchAndScan = useCallback(
    (partial: Partial<ScanFilters>) => {
      const next = { ...applied, ...partial };
      setDraft(next);
      void runScan(next);
    },
    [applied, runScan],
  );

  /* ---------------- 盘中叠加（表示専用・スコアには入らない） ----------------
     再スキャンではない。夜間に確定した断面はそのままに、「今の値段が
     どこにいるか」だけを重ねる。出来高由来の指標には触れない —— 場中の
     部分出来高を 20 日平均と比べると、朝は全滅・大引け前は全通過になる。 */
  const overlay = usePolling(() => quotesApi.overlay('screener', 200), 60_000, []);
  const overlayRows = useMemo(() => overlay.data?.rows ?? {}, [overlay.data]);
  const [onlyLiveUp, setOnlyLiveUp] = useState(false);

  /* ---------------- 排序（确定性 / 最新催化 / 影响力） ---------------- */
  const allRows = useMemo(() => response?.rows ?? [], [response]);
  const liveUpCount = useMemo(
    () => allRows.filter((row) => (overlayRows[row.canonical_code]?.live_change_pct ?? 0) > 0).length,
    [allRows, overlayRows],
  );
  const rows = useMemo(
    () =>
      onlyLiveUp
        ? allRows.filter((row) => (overlayRows[row.canonical_code]?.live_change_pct ?? 0) > 0)
        : allRows,
    [allRows, onlyLiveUp, overlayRows],
  );
  const sorted = useMemo(() => {
    const out = [...rows];
    const byScore = (a: StrengthRow, b: StrengthRow) =>
      (b.ranking_score ?? -1) - (a.ranking_score ?? -1) || a.canonical_code.localeCompare(b.canonical_code);
    if (sortMode === 'latest') {
      const ts = (row: StrengthRow) => {
        const published = news[row.canonical_code]?.latest?.published_at;
        return published ? new Date(published).getTime() : -1;
      };
      out.sort((a, b) => ts(b) - ts(a) || byScore(a, b));
    } else if (sortMode === 'impact') {
      const impact = (row: StrengthRow) => news[row.canonical_code]?.max_importance ?? -1;
      const count = (row: StrengthRow) => news[row.canonical_code]?.news_count ?? 0;
      out.sort((a, b) => impact(b) - impact(a) || count(b) - count(a) || byScore(a, b));
    }
    // deterministic: 保持服务端顺序（周期加权排序）
    return out;
  }, [rows, sortMode, news]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = useMemo(() => sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE), [sorted, safePage]);
  const flashRows = useMemo(
    () =>
      pageRows.map((row) => ({
        code: row.canonical_code,
        price: overlayRows[row.canonical_code]?.live_price ?? row.close,
      })),
    [pageRows, overlayRows],
  );
  const flashes = useTickFlash(flashRows, (row) => row.code, (row) => row.price);
  const staleResults = scanState === 'error' && Boolean(response);

  const onToggle = useCallback((code: string) => {
    setExpanded((prev) => (prev === code ? null : code));
  }, []);

  const onTierFromHistogram = useCallback(
    (tier: TierFilter) => {
      patchAndScan({ tier, minScore: null });
    },
    [patchAndScan],
  );

  /* ---------------- 派生展示 ---------------- */
  const tierCounts = tierCountsFromDistribution(response?.tier_distribution ?? null);
  const hitsByTier = useMemo(() => {
    const acc: Record<Tier, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    allRows.forEach((row) => {
      if (row.ranking_score !== null) acc[tierOf(row.ranking_score)] += 1;
    });
    return acc;
  }, [allRows]);

  const chips = useMemo(() => {
    const list: { key: string; label: string; onRemove: () => void }[] = [];
    const f = applied;
    if (f.tier !== 'all') list.push({ key: 'tier', label: `${f.tier} ${t('档')}`, onRemove: () => patchAndScan({ tier: 'all' }) });
    if (f.timeframe !== 'all')
      list.push({ key: 'tf', label: t('周期 {tf}', { tf: TIMEFRAME_CN[f.timeframe] }), onRemove: () => patchAndScan({ timeframe: 'all' }) });
    if (f.profile !== 'balanced')
      list.push({ key: 'pf', label: t('偏好 {profile}', { profile: PROFILE_CN[f.profile] }), onRemove: () => patchAndScan({ profile: 'balanced' }) });
    if (f.topN > 0 && f.topN !== 20) list.push({ key: 'top', label: `Top ${f.topN}`, onRemove: () => patchAndScan({ topN: 20 }) });
    f.sectors.forEach((sectorId) => {
      const sectorName = meta?.sectors.find((s) => s.id === sectorId)?.name;
      list.push({
        key: `sec-${sectorId}`,
        label: sectorName ? t(sectorName) : sectorId,
        onRemove: () => patchAndScan({ sectors: f.sectors.filter((x) => x !== sectorId) }),
      });
    });
    if (f.priceMin !== null || f.priceMax !== null) {
      const lo = f.priceMin !== null ? `¥${f.priceMin}` : '—';
      const hi = f.priceMax !== null ? `¥${f.priceMax}` : '—';
      list.push({ key: 'price', label: t('价格 {lo}–{hi}', { lo, hi }), onRemove: () => patchAndScan({ priceMin: null, priceMax: null }) });
    }
    if (f.minTurnover > 0 && f.minTurnover !== DEFAULT_FILTERS.minTurnover) {
      const option = TURNOVER_OPTIONS.find((o) => o.value === f.minTurnover);
      list.push({ key: 'tv', label: t('成交额 {v}', { v: option?.label ?? `≥${fmtYenCompact(f.minTurnover)}` }), onRemove: () => patchAndScan({ minTurnover: DEFAULT_FILTERS.minTurnover }) });
    }
    if (f.minScore !== null) list.push({ key: 'ms', label: t('强度 ≥{n}', { n: f.minScore }), onRemove: () => patchAndScan({ minScore: null }) });
    return list;
  }, [applied, meta, patchAndScan]);

  const familyWeights = meta?.family_weights ?? null;
  const animKey = `${requestSeq.current}:${safePage}`;

  return (
    <div className="page-stack">
      {/* B0 页头带 */}
      <PageHeader
        section="screener"
        title={t('条件选股')}
        description={t('按收盘日线对全市场多维评分与筛选。')}
        meta={
          <>
            <DataThrough date={response?.input_data_through ?? response?.trade_date} />
            {response?.built_at && (
              <span className="hidden text-right sm:block">
                <span className="block text-micro text-ink-400">{t('评分时间')}</span>
                <span className="tnum text-caption text-ink-600">{fmtJstTime(response.built_at)}</span>
              </span>
            )}
            {history[0] && (
              <span className="hidden text-right sm:block">
                <span className="block text-micro text-ink-400">{t('上次筛选')}</span>
                <span className="tnum text-caption text-ink-600">
                  {fmtTimeHHMMSS(history[0].at)}
                </span>
              </span>
            )}
            <ScanHistoryPopover history={history} />
            <ForceRefreshButton
              onClick={() => void runScan(applied, { cache: 'reload' })}
              spinning={scanState === 'scanning'}
              label={t('重新读取')}
              title={t('重新读取当前筛选结果')}
              testId="screener-reread"
            />
            {isOwner && (
              <ForceRefreshButton
                onClick={() => void onOwnerRefresh()}
                spinning={refreshState === 'queued' || refreshState === 'running'}
                label={t('更新日线与评分')}
                title={t('拉取最新日线并重算评分')}
                testId="screener-owner-refresh"
              />
            )}
          </>
        }
      />

      {/* B1 筛选工作台 */}
      <div className="min-w-0">
        <FilterWorkbench
          draft={draft}
          onChange={setDraft}
          tierCounts={tierCounts}
          universeCount={response?.universe_count ?? null}
          meta={meta}
          scanning={scanState === 'scanning'}
          dirty={dirty}
          onScan={onScanClick}
        />
      </div>

      <div className="page-grid items-start">
        {/* B2 结果区 */}
        <section className="min-w-0 lg:col-span-12 2xl:col-span-9" aria-label={t('扫描结果')}>
          <div className="paper-panel flex min-w-0 flex-wrap items-center gap-x-3 gap-y-3 p-5 sm:p-6">
            {scanState === 'scanning' ? (
              <span className="flex items-center gap-2 text-body-s text-ink-500">
                <span className="size-3.5 animate-spin rounded-full border-2 border-brand-600/25 border-t-brand-600" aria-hidden="true" />
                {t('正在扫描…')}
              </span>
            ) : scanState === 'done' || (scanState === 'error' && response) ? (
              <>
                <h2 className="section-heading">
                  {t('命中')} <span className="tnum">{response?.matched_count ?? rows.length}</span> {t('只')}
                </h2>
                <span className="tnum text-caption text-ink-400">{t('耗时')} {(scanDurationMs / 1000).toFixed(1)}s</span>
                {response && (
                  <span className="tnum text-micro text-ink-400">
                    {t('股票池')} {response.universe_count} {t('/ 条件过滤后')} {response.screened_count}
                  </span>
                )}
                {response && (response.matched_count ?? 0) > rows.length && (
                  <SoftBadge tone="warn">
                    {t('显示强度前 {n} 名（条件命中共 {m} 只）', { n: rows.length, m: response.matched_count })}
                  </SoftBadge>
                )}
                {chips.map((chip) => (
                  <SoftBadge key={chip.key} className="gap-1 whitespace-normal">
                    {chip.label}
                    <button type="button" onClick={chip.onRemove} aria-label={t('移除条件 {label}', { label: chip.label })} className="inline-grid min-h-11 min-w-11 shrink-0 place-items-center rounded-[var(--r-control)] text-ink-400 transition-colors duration-fast hover:text-ink-800 sm:min-h-8 sm:min-w-8">
                      <Icon name="x" size={10} />
                    </button>
                  </SoftBadge>
                ))}
              </>
            ) : (
              <h2 className="section-heading">{t('扫描结果')}</h2>
            )}
            {response && (response.freshness === 'stale' || response.calendar_state === 'stale') && (
              <SoftBadge tone="warn" className="whitespace-normal">
                {t('快照早于最新交易日')}
              </SoftBadge>
            )}
            {response && response.freshness === 'partial' && (
              <SoftBadge tone="warn" className="whitespace-normal">
                {t('日线数据不完整')}
              </SoftBadge>
            )}
            {response && response.freshness === 'degraded' && (
              <SoftBadge tone="warn" className="whitespace-normal">
                {t('基准指数未更新')}
              </SoftBadge>
            )}
            {response && response.freshness === 'unknown' && (
              <SoftBadge tone="warn" className="whitespace-normal">
                {t('交易日历待更新')}
              </SoftBadge>
            )}
            {response && response.score_compatible === false && (
              <SoftBadge tone="warn" className="whitespace-normal">
                {t('评分版本待更新')}
              </SoftBadge>
            )}
            {unverified && (
              <SoftBadge tone="warn" data-testid="screener-unverified">
                {t('核验未完成，列表可能不是最新')}
              </SoftBadge>
            )}
            <div className="flex w-full min-w-0 flex-wrap items-center gap-3 border-t border-line pt-4">
              <Segmented<SortMode>
                className="max-w-full flex-wrap"
                options={(['deterministic', 'latest', 'impact'] as const).map((value) => ({ value, label: SORT_CN[value] }))}
                value={sortMode}
                onChange={(value) => {
                  setSortMode(value);
                  setPage(1);
                }}
              />
            </div>
          </div>
          {refreshMessage && (
            <p className="mt-2 text-micro text-ink-500" data-testid="screener-refresh-status">
              {refreshMessage}
            </p>
          )}

          <div className="mt-4 min-h-[70dvh]">
            {scanState === 'scanning' && !response ? (
              <div className="card-surface">
                <SkeletonRows rows={8} />
              </div>
            ) : scanState === 'error' && !response ? (
              <div className="card-surface">
                <EmptyState
                  variant="error"
                  image="/empty-scan.svg"
                  title={scanError?.code === 503 ? t('扫描数据不可用') : t('扫描失败')}
                  description={scanError?.code === 503 ? t('收盘后批处理完成前暂无强度快照') : scanError?.message}
                  action={
                    <EmptyRetryButton onClick={() => void runScan(applied)} />
                  }
                />
              </div>
            ) : sorted.length === 0 ? (
              <div className="card-surface">
                <EmptyState
                  image="/empty-scan.svg"
                  title={t('当前条件无命中')}
                  description={t('尝试放宽条件，或移除部分过滤器')}
                  action={
                    <div className="flex flex-wrap justify-center gap-2">
                      {(applied.tier !== 'all' || applied.minScore !== null) && (
                        <SuggestButton label={t('放宽一档')} onClick={() => patchAndScan({ tier: 'all', minScore: null })} />
                      )}
                      {applied.sectors.length > 0 && <SuggestButton label={t('清除行业')} onClick={() => patchAndScan({ sectors: [] })} />}
                      {(applied.priceMin !== null || applied.priceMax !== null) && (
                        <SuggestButton label={t('清除价格区间')} onClick={() => patchAndScan({ priceMin: null, priceMax: null })} />
                      )}
                      {applied.minTurnover > 0 && <SuggestButton label={t('清除成交额下限')} onClick={() => patchAndScan({ minTurnover: 0 })} />}
                      <SuggestButton label={t('重置全部条件')} onClick={() => patchAndScan({ ...DEFAULT_FILTERS })} />
                    </div>
                  }
                />
              </div>
            ) : (
              <>
                {scanState === 'error' && (
                  <p className="mb-2 flex items-center gap-2 text-caption text-ink-400">
                    <SoftBadge tone="warn">{t('已过期')}</SoftBadge>
                    {t('本次扫描失败，显示上次成功结果')}
                  </p>
                )}
                {/* 盘中叠加。分数と並び順は夜間の確定断面のまま —— ここで
                    絞り込むのは「今の値段の位置」だけ（doc §八）。 */}
                {overlay.data?.enabled && liveUpCount > 0 && (
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <PointerTooltip
                      passthrough
                      label={t('按 {n} 分钟延迟盘中价筛选，评分仍基于收盘日线', {
                        n: overlay.data?.delayed_minutes ?? 15,
                      })}
                      width={260}
                      contentClassName="p-2.5"
                      content={
                        <span className="text-micro text-ink-600">
                          {t('按 {n} 分钟延迟盘中价筛选，评分仍基于收盘日线', {
                            n: overlay.data?.delayed_minutes ?? 15,
                          })}
                        </span>
                      }
                    >
                    <button
                      type="button"
                      onClick={() => setOnlyLiveUp((prev) => !prev)}
                      aria-pressed={onlyLiveUp}
                      className="control-button mobile-control-target"
                    >
                      <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                      {t('盘中上涨')} {liveUpCount}
                    </button>
                    </PointerTooltip>
                    <span className="text-micro text-ink-400">{quoteSourceLabel(overlay.data).text}</span>
                    <span className="text-micro text-ink-400">{t('评分基于收盘日线')}</span>
                  </div>
                )}
                <div className={scanState === 'scanning' ? 'hidden opacity-60 xl:block' : 'hidden xl:block'}>
                  <ResultTable
                    rows={pageRows}
                    startIndex={(safePage - 1) * PAGE_SIZE}
                    page={safePage}
                    totalPages={totalPages}
                    onPageChange={setPage}
                    expanded={expanded}
                    onToggle={onToggle}
                    news={news}
                    newsLoaded={newsLoaded}
                    weights={familyWeights}
                    canManageWatchlist={canManageWatchlist}
                    animKey={animKey}
                    overlay={overlayRows}
                    flashes={flashes}
                    stale={staleResults}
                  />
                </div>
                <div className={scanState === 'scanning' ? 'opacity-60 xl:hidden' : 'xl:hidden'}>
                  <ResultCards
                    rows={pageRows}
                    expanded={expanded}
                    onToggle={onToggle}
                    news={news}
                    newsLoaded={newsLoaded}
                    weights={familyWeights}
                    canManageWatchlist={canManageWatchlist}
                    animKey={animKey}
                    page={safePage}
                    overlay={overlayRows}
                    flashes={flashes}
                    stale={staleResults}
                  />
                  {totalPages > 1 && (
                    <div className="mt-4 flex items-center justify-center gap-2">
                      <PagerButton disabled={safePage <= 1} onClick={() => setPage(safePage - 1)} label={t('上一页')} />
                      <span className="tnum text-caption text-ink-500">
                        {safePage} / {totalPages}
                      </span>
                      <PagerButton disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)} label={t('下一页')} />
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </section>

        {/* B3 右侧栏 */}
        <aside className="grid min-w-0 grid-cols-1 items-start gap-6 self-start md:grid-cols-2 lg:col-span-12 2xl:sticky 2xl:top-20 2xl:col-span-3 2xl:grid-cols-1" aria-label={t('侧栏')}>
          {response?.market_regime ? (
            <MarketRegimeCard regime={response.market_regime} />
          ) : scanState === 'scanning' || scanState === 'idle' ? (
            <SkeletonCard />
          ) : (
            <div className="card-surface p-5">
              <p className="eyebrow">{t('市场形态')}</p>
              <EmptyState
                size="compact"
                image="/empty-chart.svg"
                title={t('数据暂不可用')}
                description={t('稍后刷新再试')}
              />
            </div>
          )}
          <TierHistogram
            hits={hitsByTier}
            distribution={response?.tier_distribution ?? null}
            activeTier={applied.tier}
            onSelect={onTierFromHistogram}
          />
          <MethodCard meta={meta} profileId={applied.profile} loading={!meta && !metaFailed} error={metaFailed} onRetry={loadMeta} />
        </aside>
      </div>
    </div>
  );
}

function PagerButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="control-button mobile-control-target">
      {label}
    </button>
  );
}

function SuggestButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="control-button"
    >
      {label}
    </button>
  );
}
