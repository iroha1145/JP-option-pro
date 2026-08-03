/**
 * §04 选股扫描（强度）— 对标美版 Screener 页。
 * B0 页头带（数据截至 / 扫描历史 popover）
 * B1 筛选工作台（分档/预设/周期/偏好/TopN/业种/价格/成交额 + 扫描钮 dirty 脉冲）
 * B2 结果区（统计行 + 参数回显 chips + 三态排序 + 结果表/卡片流 + 行展开）
 * B3 右侧栏（市场形态 6 维 / 强度剖面 / 评分方法）
 * 与美版的差异（更强的口径）：所有条件在服务端对完整已评分池生效——
 * 无「客户端条件只作用于前 N 名」问题；新闻摘要一次批量取回。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { newsApi, quotesApi, strengthApi, type StrengthScanParams } from '@/api/modules';
import { ApiError } from '@/api/client';
import type { StrengthProfilesMeta, StrengthScanResponse, StrengthRow } from '@/api/types';
import { useAccess } from '@/hooks/useAccess';
import PageHeader from '@/components/shared/PageHeader';
import Segmented from '@/components/shared/Segmented';
import EmptyState from '@/components/shared/EmptyState';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import { DataThrough } from '@/components/domain';
import Icon from '@/components/icons';
import FilterWorkbench from '@/components/screener/FilterWorkbench';
import ResultTable from '@/components/screener/ResultTable';
import ResultCards from '@/components/screener/ResultCards';
import ScanHistoryPopover from '@/components/screener/ScanHistoryPopover';
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
import { quoteSourceLabel } from '@/lib/quoteSource';
import { fmtYenCompact } from '@/lib/format';

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

function filtersEqual(a: ScanFilters, b: ScanFilters): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function summarizeFilters(filters: ScanFilters): string {
  const parts: string[] = [];
  if (filters.tier !== 'all') parts.push(`${filters.tier} ${t('档')}`);
  if (filters.timeframe !== 'all') parts.push(TIMEFRAME_CN[filters.timeframe]);
  parts.push(PROFILE_CN[filters.profile]);
  if (filters.topN > 0) parts.push(`Top ${filters.topN}`);
  if (filters.sectors.length > 0) parts.push(t('业种 {n} 项', { n: filters.sectors.length }));
  if (filters.priceMin !== null || filters.priceMax !== null) parts.push(t('价格区间'));
  if (filters.minTurnover > 0) parts.push(t('成交额≥{v}', { v: fmtYenCompact(filters.minTurnover) }));
  if (filters.minScore !== null) parts.push(t('强度≥{n}', { n: filters.minScore }));
  return parts.join(' · ') || t('默认条件');
}

export default function Screener() {
  const { canManageWatchlist } = useAccess();

  const [meta, setMeta] = useState<StrengthProfilesMeta | null>(null);
  const [metaFailed, setMetaFailed] = useState(false);
  const [draft, setDraft] = useState<ScanFilters>(DEFAULT_FILTERS);
  const [applied, setApplied] = useState<ScanFilters>(DEFAULT_FILTERS);
  const [scanState, setScanState] = useState<ScanState>('idle');
  const [scanError, setScanError] = useState<ApiError | null>(null);
  const [response, setResponse] = useState<StrengthScanResponse | null>(null);
  const [scanDurationMs, setScanDurationMs] = useState(0);
  const [history, setHistory] = useState<ScanHistoryEntry[]>([]);
  const [sortMode, setSortMode] = useState<SortMode>('deterministic');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [news, setNews] = useState<NewsSummaryMap>({});
  const [newsLoaded, setNewsLoaded] = useState(false);
  const scanSeq = useRef(0);

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
      .securities(72)
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

  const runScan = useCallback(async (filters: ScanFilters) => {
    const seq = ++scanSeq.current;
    setScanState('scanning');
    setScanError(null);
    const startedAt = Date.now();
    try {
      const result = await strengthApi.scan(buildParams(filters));
      if (scanSeq.current !== seq) return false;
      setResponse(result);
      setApplied(filters);
      setDraft(filters);
      setScanDurationMs(Date.now() - startedAt);
      setPage(1);
      setExpanded(null);
      setScanState('done');
      setHistory((prev) =>
        [
          { at: Date.now(), count: result.rows.length, durationMs: Date.now() - startedAt, summary: summarizeFilters(filters) },
          ...prev,
        ].slice(0, 5),
      );
      return true;
    } catch (error) {
      if (scanSeq.current !== seq) return false;
      setScanError(error instanceof ApiError ? error : new ApiError(500, error instanceof Error ? error.message : t('扫描失败')));
      setScanState('error');
      return false;
    }
  }, []);

  /* 首次进入自动跑一次默认扫描（读取夜间快照，成本低）。 */
  useEffect(() => {
    void runScan(DEFAULT_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onScanClick = useCallback(() => void runScan(draft), [draft, runScan]);

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
  const overlayRows = overlay.data?.rows ?? {};
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

  const onToggle = useCallback((code: string) => {
    setExpanded((prev) => (prev === code ? null : code));
  }, []);

  const onTierFromHistogram = useCallback(
    (tier: TierFilter) => {
      patchAndScan({ tier, presetId: null, minScore: null });
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
      list.push({ key: 'pf', label: t('偏好 {profile}', { profile: PROFILE_CN[f.profile] }), onRemove: () => patchAndScan({ profile: 'balanced', presetId: null }) });
    if (f.topN > 0 && f.topN !== 20) list.push({ key: 'top', label: `Top ${f.topN}`, onRemove: () => patchAndScan({ topN: 20 }) });
    f.sectors.forEach((sectorId) =>
      list.push({
        key: `sec-${sectorId}`,
        label: meta?.sectors.find((s) => s.id === sectorId)?.name ?? sectorId,
        onRemove: () => patchAndScan({ sectors: f.sectors.filter((x) => x !== sectorId) }),
      }),
    );
    if (f.priceMin !== null || f.priceMax !== null) {
      const lo = f.priceMin !== null ? `¥${f.priceMin}` : '—';
      const hi = f.priceMax !== null ? `¥${f.priceMax}` : '—';
      list.push({ key: 'price', label: t('价格 {lo}–{hi}', { lo, hi }), onRemove: () => patchAndScan({ priceMin: null, priceMax: null }) });
    }
    if (f.minTurnover > 0 && f.minTurnover !== DEFAULT_FILTERS.minTurnover) {
      const option = TURNOVER_OPTIONS.find((o) => o.value === f.minTurnover);
      list.push({ key: 'tv', label: t('成交额 {v}', { v: option?.label ?? `≥${fmtYenCompact(f.minTurnover)}` }), onRemove: () => patchAndScan({ minTurnover: DEFAULT_FILTERS.minTurnover }) });
    }
    if (f.minScore !== null) list.push({ key: 'ms', label: t('强度 ≥{n}', { n: f.minScore }), onRemove: () => patchAndScan({ minScore: null, presetId: null }) });
    return list;
  }, [applied, meta, patchAndScan]);

  const familyWeights = meta?.family_weights ?? null;
  const animKey = `${scanSeq.current}:${safePage}`;

  return (
    <div className="space-y-0">
      {/* B0 页头带 */}
      <PageHeader
        section="04"
        eyebrow="SCREENER · STRENGTH SCAN"
        title={t('选股扫描')}
        description={t('收盘后按日线全市场计算强度分，扫描读取当日快照。')}
        meta={
          <>
            <DataThrough date={response?.trade_date} />
            <ScanHistoryPopover history={history} />
          </>
        }
      />

      {/* B1 筛选工作台 */}
      <div className="mt-6">
        <FilterWorkbench
          draft={draft}
          onChange={setDraft}
          tierCounts={tierCounts}
          universeCount={response?.universe_count ?? null}
          meta={meta}
          metaFailed={metaFailed}
          scanning={scanState === 'scanning'}
          dirty={dirty}
          onScan={onScanClick}
        />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* B2 结果区 */}
        <section className="lg:col-span-8" aria-label={t('扫描结果')}>
          <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-2">
            {scanState === 'scanning' ? (
              <span className="flex items-center gap-2 text-body-s text-ink-500">
                <span className="size-3.5 animate-spin rounded-full border-2 border-brand-600/25 border-t-brand-600" aria-hidden="true" />
                {t('正在扫描…')}
              </span>
            ) : scanState === 'done' || (scanState === 'error' && response) ? (
              <>
                <h2 className="font-display text-[18px] leading-[24px] text-ink-900">
                  {t('命中')} <span className="font-mono tnum">{response?.matched_count ?? rows.length}</span> {t('只')}
                </h2>
                <span className="font-mono text-caption text-ink-400 tnum">{t('耗时')} {(scanDurationMs / 1000).toFixed(1)}s</span>
                {response && (
                  <span className="font-mono text-micro text-ink-400 tnum">
                    {t('股票池')} {response.universe_count} {t('/ 条件过滤后')} {response.screened_count}
                  </span>
                )}
                {response && (response.matched_count ?? 0) > rows.length && (
                  <span className="rounded-xs bg-paper-2 px-1.5 py-px text-micro text-ink-500">
                    {t('显示强度前 {n} 名（条件命中共 {m} 只）', { n: rows.length, m: response.matched_count })}
                  </span>
                )}
                {chips.map((chip) => (
                  <span key={chip.key} className="inline-flex items-center gap-1 rounded-xs border border-line bg-card-warm px-1.5 py-0.5 text-micro text-ink-500">
                    {chip.label}
                    <button type="button" onClick={chip.onRemove} aria-label={t('移除条件 {label}', { label: chip.label })} className="text-ink-300 transition-colors hover:text-down-600">
                      <Icon name="x" size={10} />
                    </button>
                  </span>
                ))}
              </>
            ) : (
              <h2 className="font-display text-[18px] leading-[24px] text-ink-900">{t('扫描结果')}</h2>
            )}
            <div className="ml-auto flex items-center gap-2">
              <Segmented<SortMode>
                options={(['deterministic', 'latest', 'impact'] as const).map((value) => ({ value, label: SORT_CN[value] }))}
                value={sortMode}
                onChange={(value) => {
                  setSortMode(value);
                  setPage(1);
                }}
              />
            </div>
          </div>
          {sortMode !== 'deterministic' && (
            <p className="mt-2 text-micro text-ink-400">{t('催化排序基于 72h 新闻摘要（仅覆盖已接入 RSS 源）；无新闻的股票排在其后。')}</p>
          )}

          <div className="mt-4">
            {scanState === 'scanning' && !response ? (
              <div className="card-surface">
                <SkeletonRows rows={8} />
              </div>
            ) : scanState === 'error' && !response ? (
              <div className="card-surface">
                <EmptyState
                  variant="error"
                  title={scanError?.code === 503 ? t('扫描数据不可用') : t('扫描失败')}
                  description={scanError?.code === 503 ? t('收盘后批处理完成前暂无强度快照') : scanError?.message}
                  action={
                    <button
                      type="button"
                      onClick={() => void runScan(applied)}
                      className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white transition-[filter] hover:brightness-105"
                    >
                      {t('重试')}
                    </button>
                  }
                />
              </div>
            ) : sorted.length === 0 ? (
              <div className="card-surface">
                <EmptyState
                  title={t('当前条件无命中')}
                  description={t('尝试放宽条件，或移除部分过滤器')}
                  action={
                    <div className="flex flex-wrap justify-center gap-2">
                      {(applied.tier !== 'all' || applied.minScore !== null) && (
                        <SuggestButton label={t('放宽一档')} onClick={() => patchAndScan({ tier: 'all', minScore: null, presetId: null })} />
                      )}
                      {applied.sectors.length > 0 && <SuggestButton label={t('清除业种')} onClick={() => patchAndScan({ sectors: [] })} />}
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
                    <span className="rounded-xs bg-warn-50 px-1.5 py-px font-mono text-micro text-warn-600">{t('已过期')}</span>
                    {t('本次扫描失败，显示上次成功结果')}
                  </p>
                )}
                {/* 盘中叠加。分数と並び順は夜間の確定断面のまま —— ここで
                    絞り込むのは「今の値段の位置」だけ（doc §八）。 */}
                {overlay.data?.enabled && liveUpCount > 0 && (
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setOnlyLiveUp((prev) => !prev)}
                      title={t('用{n}分延迟的盘中价筛选，分数与排序仍来自夜间官方数据', {
                        n: overlay.data?.delayed_minutes ?? 15,
                      })}
                      className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-caption transition-colors duration-fast ${
                        onlyLiveUp
                          ? 'border-brand-400 bg-brand-50 text-brand-700'
                          : 'border-line bg-card text-ink-600 hover:border-brand-400 hover:text-brand-600'
                      }`}
                    >
                      <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                      {t('盘中上涨')} {liveUpCount}
                    </button>
                    <span className="text-micro text-ink-400">{quoteSourceLabel(overlay.data).text}</span>
                  </div>
                )}
                <div className={scanState === 'scanning' ? 'hidden opacity-60 md:block' : 'hidden md:block'}>
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
                  />
                </div>
                <div className={scanState === 'scanning' ? 'opacity-60 md:hidden' : 'md:hidden'}>
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
                  />
                  {totalPages > 1 && (
                    <div className="mt-4 flex items-center justify-center gap-2">
                      <SuggestButton label={t('上一页')} onClick={() => setPage(Math.max(1, safePage - 1))} />
                      <span className="font-mono text-caption text-ink-500 tnum">
                        {safePage} / {totalPages}
                      </span>
                      <SuggestButton label={t('下一页')} onClick={() => setPage(Math.min(totalPages, safePage + 1))} />
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </section>

        {/* B3 右侧栏 */}
        <aside className="grid grid-cols-1 gap-4 self-start md:grid-cols-2 lg:sticky lg:top-20 lg:col-span-4 lg:grid-cols-1" aria-label={t('侧栏')}>
          {response?.market_regime ? (
            <MarketRegimeCard regime={response.market_regime} />
          ) : scanState === 'scanning' || scanState === 'idle' ? (
            <SkeletonCard />
          ) : (
            <div className="card-surface p-5">
              <p className="eyebrow">{t('市场形态 · MARKET REGIME')}</p>
              <p className="mt-3 text-body-s text-ink-500">{t('数据暂不可用 · 稍后刷新再试')}</p>
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

function SuggestButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-8 items-center rounded-pill border border-line bg-card px-3 text-caption text-ink-500 transition-colors duration-fast hover:border-brand-400/60 hover:text-brand-600"
    >
      {label}
    </button>
  );
}
