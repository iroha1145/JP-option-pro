/* 机构空卖（接口契约 jp-short-monitor-v4）。
 *
 * 这一页回答一个问题：哪些股票被公开做空得最集中，最近在增加还是减少。
 * 页头 → 读法说明 → 断面概览 → 工具行 → 排行列表 + 详情卡 → 图例。
 *
 * 界面纪律：
 *   1. 只有达到 0.5% 披露门槛的机构持仓。跌破门槛的机构单独计数，不并入合计，
 *      也不画成 0。
 *   2. 有历史证据的读法只有「拥挤度」一条（机构越多、比例越高，之后越弱）。
 *      其余一律只陈述事实，不打分。
 *   3. 拥挤度与动向徽标不用涨跌色：拥挤度用警示色阶表示程度，动向用中性色。
 *      空头变化的数字按对股价的方向着色（增加用跌色、减少用涨色）。
 *   4. 标签不替数据做时间断言：窗口只写「5日」「20日」，日期由 DataThrough
 *      或显式日期给出。 */

import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { useColorMode } from '@/hooks/useColorMode';
import { Link } from 'react-router';
import PageHeader from '@/components/shared/PageHeader';
import Segmented from '@/components/shared/Segmented';
import MenuSelect from '@/components/shared/MenuSelect';
import EmptyState from '@/components/shared/EmptyState';
import EmptyRetryButton from '@/components/shared/EmptyRetryButton';
import StatCard from '@/components/shared/StatCard';
import { SkeletonBlock, SkeletonCard, SkeletonReveal, SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough } from '@/components/domain';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { shortMonitorApi, stocksApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import Icon from '@/components/icons';
import '@/components/radar.css';
import type {
  ShortCrowdingLevel,
  ShortMonitorDetail,
  ShortMonitorEvent,
  ShortMonitorHolder,
  ShortMonitorOverview,
  ShortMonitorRow,
  ShortMonitorView,
  StockBar,
} from '@/api/types';
import { fmtDate, fmtDateShort, fmtPct, fmtPctLevel, fmtTimeHHMMSS } from '@/lib/format';
import { explanationLine } from '@/lib/explainText';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import InfoHint from '@/components/shared/InfoHint';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { SHORT_HINTS, type ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';

const VIEWS: { key: ShortMonitorView; label: string; hint: string }[] = [
  { key: 'crowded', label: '拥挤度最高', hint: '有近期公开持仓的股票，按公开持仓比例从高到低' },
  { key: 'building', label: '增加最多', hint: '20日动向为增加中的股票，按20日公开持仓比例的增幅从大到小' },
  { key: 'covering', label: '减少最多', hint: '20日动向为减少中的股票，按20日公开持仓比例的降幅从大到小' },
  { key: 'entries', label: '新进入', hint: '20日内有机构新进入或重新进入公开范围的股票，按20日变化从大到小' },
  { key: 'days_to_cover', label: '回补天数最长', hint: '有近期公开持仓的股票，按回补天数从长到短' },
  { key: 'all', label: '全部', hint: '全部覆盖股票，按公开持仓比例从高到低' },
];

/** 「拥挤度下限」。1 是给概览里「低」那一格用的：点了总要有落点。 */
const CROWDING_FLOORS: { value: number; label: string }[] = [
  { value: 0, label: '不限' },
  { value: 1, label: '低及以上' },
  { value: 2, label: '中及以上' },
  { value: 3, label: '仅高' },
];

const CROWDING_LABELS: Record<ShortCrowdingLevel, string> = { 0: '无', 1: '低', 2: '中', 3: '高' };

const STATE_LABELS: Record<string, string> = {
  building: '增加中',
  covering: '减少中',
  mixed: '方向反复',
  steady: '持平',
  no_signal: '无动向',
};

const FLAG_LABELS: Record<string, string> = {
  new_entry: '新进',
  reentry: '重新进入',
  concentrated: '空头集中',
  multi_reduction: '多机构减仓',
  below_threshold: '跌破门槛',
  not_visible: '数据不可见',
  crowded_margin: '信用买入拥挤',
  regulated: '信用限制',
  earnings_near: '财报临近',
  thin_liquidity: '低流动性',
  stale_data: '数据过期',
  hedge_disclosed: '含对冲持仓',
  single_institution: '仅1家可见',
  parked_below: '停在门槛下方',
  no_informed_reporter: '仅个人名义报告',
};

/** 会降低这一行可信度的标签，与「发生了什么」的事件标签分开着色。 */
const RISK_FLAGS = new Set([
  'not_visible', 'crowded_margin', 'regulated', 'thin_liquidity',
  'stale_data', 'hedge_disclosed', 'single_institution', 'no_informed_reporter',
  'parked_below',
]);

/** 宽屏排行的列。窄屏同一组单元格折成两三行的小卡。 */
const ROW_GRID =
  'lg:grid-cols-[1.5rem_minmax(9rem,1fr)_4rem_5.5rem_2.75rem_4.25rem_4.25rem_3.5rem_4.25rem_5.5rem] lg:gap-x-1.5';

const DETAIL_HOLDER_LIMIT = 8;

export default function ShortMonitor() {
  const [view, setView] = useState<ShortMonitorView>('crowded');
  const [minCrowding, setMinCrowding] = useState(0);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const detailRef = useRef<HTMLElement>(null);

  const overviewQuery = usePolling(() => shortMonitorApi.overview(), 600_000, []);
  const rankingQuery = usePolling(
    () => shortMonitorApi.rankings({ view, limit: 60, min_crowding: minCrowding || undefined }),
    600_000,
    [view, minCrowding],
  );
  const state = remoteState(rankingQuery, (d) => d.rows.length === 0);
  const overviewState = remoteState(overviewQuery);
  const overview = overviewQuery.data;

  const rows = useMemo(() => rankingQuery.data?.rows ?? [], [rankingQuery.data]);
  const selected = useMemo(
    () => rows.find((row) => row.canonical_code === selectedCode) ?? rows[0] ?? null,
    [rows, selectedCode],
  );

  // 换视图或筛选后旧的选中项通常已不在结果里，退回首位。
  const pickView = useCallback((next: ShortMonitorView) => {
    setView(next);
    setSelectedCode(null);
  }, []);
  const pickCrowding = useCallback((next: number) => {
    setMinCrowding(next);
    setSelectedCode(null);
  }, []);

  const selectRow = useCallback((code: string) => {
    setSelectedCode(code);
    // 窄屏上详情在列表上方：不滚过去，点了就像没反应。
    if (typeof window === 'undefined' || !window.matchMedia('(max-width: 1279px)').matches) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    detailRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  }, []);

  const activeView = VIEWS.find((v) => v.key === view) ?? VIEWS[0];
  const refreshOverview = overviewQuery.refresh;
  const refreshRanking = rankingQuery.refresh;
  const refreshingMonitor = overviewQuery.refreshing || rankingQuery.refreshing;
  const onRefreshMonitor = useCallback(() => {
    refreshOverview({ force: true });
    refreshRanking({ force: true });
  }, [refreshOverview, refreshRanking]);

  return (
    <div className="page-stack">
      <PageHeader
        section="market"
        title={t('机构空卖')}
        description={t('追踪达到 0.5% 法定披露门槛的机构空头持仓与近期增减。')}
        meta={
          <>
            <DataThrough date={overview?.as_of_date ?? rankingQuery.data?.as_of_date} />
            {overviewQuery.lastUpdatedAt && (
              <span className="tnum text-caption text-ink-400">
                {t('更新')} {fmtTimeHHMMSS(overviewQuery.lastUpdatedAt)}
              </span>
            )}
            <ForceRefreshButton
              onClick={onRefreshMonitor}
              spinning={refreshingMonitor}
              label={t('刷新监控')}
              title={t('重新读取空卖监控快照')}
            />
          </>
        }
      />

      {(state === 'stale' || overviewState === 'stale') && (
        <StaleStrip onRetry={onRefreshMonitor} refreshing={refreshingMonitor} />
      )}

      {overview ? (
        <OverviewCards
          overview={overview}
          view={view}
          minCrowding={minCrowding}
          onPickView={pickView}
          onPickCrowding={pickCrowding}
        />
      ) : overviewState === 'error' ? (
        <div className="card-surface">
          <EmptyState
            size="compact"
            variant="error"
            image="/empty-chart.svg"
            title={t('概览读取失败')}
            description={String((overviewQuery.error as Error | null)?.message ?? '')}
            action={<EmptyRetryButton onClick={() => overviewQuery.refresh({ force: true })} refreshing={overviewQuery.refreshing} />}
          />
        </div>
      ) : (
        <OverviewSkeleton />
      )}

      <div className="grid grid-cols-1 gap-2">
        <div className="page-toolbar">
          <Segmented<ShortMonitorView>
            options={VIEWS.map((item) => ({ value: item.key, label: t(item.label) }))}
            value={view}
            onChange={pickView}
            ariaLabel={t('排行视图')}
            scrollable
            className="max-w-full"
          />
          <label className="flex items-center gap-1.5 text-caption text-ink-400 sm:ml-auto">
            {t('拥挤度下限')}
            <MenuSelect<number>
              value={minCrowding}
              onChange={pickCrowding}
              ariaLabel={t('拥挤度下限')}
              options={CROWDING_FLOORS.map((item) => ({ value: item.value, label: t(item.label) }))}
            />
          </label>
        </div>
        <p className="text-micro text-ink-400">{t(activeView.hint)}</p>
      </div>

      {state === 'error' ? (
        <div className="card-surface">
          <EmptyState
            variant="error"
            image="/empty-chart.svg"
            title={t('读取失败')}
            description={String((rankingQuery.error as Error | null)?.message ?? '')}
            action={<EmptyRetryButton onClick={() => rankingQuery.refresh({ force: true })} refreshing={rankingQuery.refreshing} />}
          />
        </div>
      ) : (
        <SkeletonReveal
          loading={state === 'loading'}
          skeleton={
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem] 2xl:grid-cols-[minmax(0,1fr)_26rem]">
              <SkeletonRows rows={8} />
              <SkeletonCard className="h-96" />
            </div>
          }
        >
          {state === 'empty' ? (
            <div className="card-surface">
              <EmptyState
                image="/empty-scan.svg"
                title={t('该视图当前没有符合条件的股票')}
                description={minCrowding > 0 ? t('可以把拥挤度下限放宽到「不限」再看一次') : undefined}
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem] 2xl:grid-cols-[minmax(0,1fr)_26rem] xl:items-start">
              <section aria-label={t('排行')} className="order-2 min-w-0 xl:order-1">
                <RankingList
                  rows={rows}
                  total={rankingQuery.data?.total ?? rows.length}
                  selectedCode={selected?.canonical_code ?? null}
                  onSelect={selectRow}
                />
              </section>
              <aside
                ref={detailRef}
                aria-label={t('选中股票详情')}
                className="bk-rail-scroll order-1 min-w-0 scroll-mt-20 xl:sticky xl:top-24 xl:order-2 xl:max-h-[calc(100dvh-7rem)] xl:overflow-y-auto xl:rounded-[1.5rem]"
              >
                {selected && <DetailCard key={selected.canonical_code} row={selected} />}
              </aside>
            </div>
          )}
        </SkeletonReveal>
      )}
    </div>
  );
}

/* ---------------- 断面概览 ---------------- */

function OverviewSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

function OverviewCards({
  overview,
  view,
  minCrowding,
  onPickView,
  onPickCrowding,
}: {
  overview: ShortMonitorOverview;
  view: ShortMonitorView;
  minCrowding: number;
  onPickView: (view: ShortMonitorView) => void;
  onPickCrowding: (level: number) => void;
}) {
  const coverage = overview.coverage;
  const covered = coverage?.covered ?? 0;
  const visible = coverage?.with_visible_short ?? 0;
  const share = covered > 0 ? `${((visible / covered) * 100).toFixed(1)}%` : '—';
  const crowding = overview.crowding;
  const states = overview.states ?? {};
  /* 手机上数字卡两列，两张分布卡各占一行。 */
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <StatCard
        label={t('覆盖股票')}
        value={covered}
        icon="dots-grid"
        sub={`${t('数据截至')} ${fmtDate(overview.as_of_date)}`}
      />
      <StatCard
        label={t('有公开空头')}
        value={visible}
        icon="filter-funnel"
        sub={t('占覆盖 {p}', { p: share })}
      />
      <CountCard
        title={t('拥挤度分布')}
        hint={SHORT_HINTS.crowding}
        items={[
          { key: 'high', label: t('高'), count: crowding?.high ?? null, level: 3 },
          { key: 'mid', label: t('中'), count: crowding?.mid ?? null, level: 2 },
          { key: 'low', label: t('低'), count: crowding?.low ?? null, level: 1 },
        ].map((item) => ({
          key: item.key,
          label: item.label,
          count: item.count,
          meter: item.level as ShortCrowdingLevel,
          active: minCrowding === item.level,
          actionLabel: t('拥挤度下限设为「{label}」', { label: item.label }),
          onClick: () => onPickCrowding(minCrowding === item.level ? 0 : item.level),
        }))}
      />
      <CountCard
        title={t('20日动向')}
        hint={SHORT_HINTS.state}
        items={[
          {
            key: 'building',
            label: t('增加中'),
            count: states.building ?? null,
            active: view === 'building',
            actionLabel: t('切到「{label}」视图', { label: t('增加最多') }),
            onClick: () => onPickView(view === 'building' ? 'crowded' : 'building'),
          },
          {
            key: 'covering',
            label: t('减少中'),
            count: states.covering ?? null,
            active: view === 'covering',
            actionLabel: t('切到「{label}」视图', { label: t('减少最多') }),
            onClick: () => onPickView(view === 'covering' ? 'crowded' : 'covering'),
          },
          // 方向反复没有专属视图：只显示计数，不做成按钮。
          { key: 'mixed', label: t('方向反复'), count: states.mixed ?? null },
        ]}
      />
    </div>
  );
}

interface CountItem {
  key: string;
  label: string;
  count: number | null;
  meter?: ShortCrowdingLevel;
  active?: boolean;
  actionLabel?: string;
  onClick?: () => void;
}

function CountCard({ title, hint, items }: { title: string; hint: ScoreHint; items: CountItem[] }) {
  const max = Math.max(1, ...items.map((item) => item.count ?? 0));
  return (
    <div className="card-surface col-span-2 p-5 sm:col-span-1">
      <p className="flex items-center gap-1 text-caption font-medium text-ink-500">
        {title}
        <InfoHint hint={hint} size={12} />
      </p>
      <ul className="mt-3 space-y-1">
        {items.map((item) => {
          const body = (
            <>
              <span className="flex min-w-0 items-center gap-1.5 text-caption text-ink-600">
                {item.meter !== undefined && <CrowdingMeter level={item.meter} />}
                <span className="min-w-0 whitespace-normal break-words">{item.label}</span>
              </span>
              <span className="strength-track relative h-1 min-w-8 overflow-hidden rounded-pill" aria-hidden>
                <span
                  className="absolute inset-y-0 left-0 rounded-pill bg-ink-400"
                  style={{ width: `${Math.max(2, ((item.count ?? 0) / max) * 100)}%` }}
                />
              </span>
              <span className="text-right tnum text-caption text-ink-800">{item.count ?? '—'}</span>
            </>
          );
          const grid = 'grid w-full grid-cols-[minmax(0,7rem)_minmax(2rem,1fr)_3rem] items-center gap-2 rounded-sm px-1.5 py-1';
          return (
            <li key={item.key}>
              {item.onClick ? (
                <button
                  type="button"
                  onClick={item.onClick}
                  aria-pressed={item.active}
                  aria-label={`${item.label} ${item.count ?? '—'} · ${item.actionLabel ?? ''}`}
                  className={cn(
                    grid,
                    'mobile-control-target text-left transition-colors duration-fast hover:bg-paper-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600',
                    item.active && 'bg-brand-50 hover:bg-brand-50',
                  )}
                >
                  {body}
                </button>
              ) : (
                <div className={grid}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ---------------- 排行列表 ---------------- */

function RankingList({
  rows,
  total,
  selectedCode,
  onSelect,
}: {
  rows: ShortMonitorRow[];
  total: number;
  selectedCode: string | null;
  onSelect: (code: string) => void;
}) {
  // 细条按当前页最大值归一：比的是这一页里谁更集中。
  const maxRatio = Math.max(0, ...rows.map((row) => row.visible_short_ratio ?? 0));
  return (
    <div className="card-surface overflow-hidden">
      <div className="section-heading border-b border-line px-4 py-3">
        <h2 className="text-body-s font-medium text-ink-900">{t('排行')}</h2>
        <span className="tnum text-micro text-ink-400">
          {total > rows.length
            ? t('显示前 {n} 只 · 共 {total} 只', { n: rows.length, total })
            : t('共 {total} 只', { total })}
        </span>
      </div>
      <div
        className={cn(
          'hidden border-b border-line bg-paper-2/60 px-3 py-2 text-micro text-ink-400 lg:grid lg:items-center',
          ROW_GRID,
        )}
      >
        <span className="text-right">#</span>
        <span>{t('股票')}</span>
        <span className="flex items-center gap-0.5">
          {t('拥挤度')}
          <InfoHint hint={SHORT_HINTS.crowding} size={11} side="bottom" align="start" />
        </span>
        <span className="flex items-center gap-0.5">
          {t('公开持仓比例')}
          <InfoHint hint={SHORT_HINTS.visibleShort} size={11} side="bottom" />
        </span>
        <span className="flex items-center justify-end gap-0.5">
          {t('机构')}
          <InfoHint hint={SHORT_HINTS.institutions} size={11} side="bottom" />
        </span>
        <span className="text-right">{t('20日变化')}</span>
        <span className="text-right">{t('5日变化')}</span>
        <span className="flex items-center justify-end gap-0.5">
          {t('回补')}
          <InfoHint hint={SHORT_HINTS.daysToCover} size={11} side="bottom" />
        </span>
        <span className="text-right">{t('相对TOPIX 20日')}</span>
        <span className="flex items-center gap-0.5">
          {t('动向')}
          <InfoHint hint={SHORT_HINTS.state} size={11} side="bottom" align="end" />
        </span>
      </div>
      <ol>
        {rows.map((row, index) => (
          <li key={row.canonical_code} className="border-b border-line last:border-b-0">
            <RankingRow
              row={row}
              rank={index + 1}
              maxRatio={maxRatio}
              selected={row.canonical_code === selectedCode}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}

/** 一行。整行是一个按钮，里面不能再有可交互的子元素（提示放在表头里）。
 *  窄屏用 grid-template-areas 把同一组单元格折成三行；宽屏 `lg:contents`
 *  让事实单元格直接参与表格网格。 */
function RankingRow({
  row,
  rank,
  maxRatio,
  selected,
  onSelect,
}: {
  row: ShortMonitorRow;
  rank: number;
  maxRatio: number;
  selected: boolean;
  onSelect: (code: string) => void;
}) {
  const ratio = row.visible_short_ratio;
  const width = ratio != null && maxRatio > 0 ? Math.max(2, (ratio / maxRatio) * 100) : 0;
  return (
    <button
      type="button"
      onClick={() => onSelect(row.canonical_code)}
      aria-current={selected ? 'true' : undefined}
      className={cn(
        'grid w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1.5 px-3 py-2.5 text-left transition-colors duration-fast',
        '[grid-template-areas:"rank_name_crowd"_"._ratio_state"_"._facts_facts"] lg:[grid-template-areas:"rank_name_crowd_ratio_inst_d20_d5_dtc_rel_state"]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-600',
        ROW_GRID,
        selected ? 'bg-brand-50' : 'hover:bg-paper-2/70',
      )}
    >
      <span className="text-right tnum text-micro text-ink-400 [grid-area:rank]">{rank}</span>
      <span className="flex min-w-0 items-center gap-1.5 [grid-area:name]">
        <CodeCell displayCode={row.display_code} nameJa={row.name} />
        {row.security_kind === 'reit' && <SoftBadge className="shrink-0">REIT</SoftBadge>}
      </span>
      <span className="justify-self-end [grid-area:crowd] lg:justify-self-start">
        <CrowdingBadge level={row.crowding_level} />
      </span>
      <span className="flex min-w-0 items-center gap-2 [grid-area:ratio]">
        <span className="sr-only">{t('公开持仓比例')}</span>
        <span className="w-14 shrink-0 text-right tnum text-body-s text-ink-900">{fmtPctLevel(ratio)}</span>
        <span className="strength-track relative h-1 min-w-6 flex-1 overflow-hidden rounded-pill" aria-hidden>
          {width > 0 && (
            <span className="absolute inset-y-0 left-0 rounded-pill bg-ink-400" style={{ width: `${width}%` }} />
          )}
        </span>
      </span>
      <span className="justify-self-end [grid-area:state] lg:justify-self-start">
        <StateBadge state={row.primary_state} />
      </span>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 text-micro text-ink-500 [grid-area:facts] lg:contents">
        <Fact area="inst" label={t('机构')}>
          <span className="text-ink-800">{row.visible_institution_count}</span>
        </Fact>
        <Fact area="d20" label={t('20日')}>
          <ShortDelta value={row.ratio_change_20d} />
        </Fact>
        <Fact area="d5" label={t('5日')}>
          <ShortDelta value={row.ratio_change_5d} />
        </Fact>
        <Fact area="dtc" label={t('回补')}>
          <span className="text-ink-800">{fmtDays(row.visible_days_to_cover)}</span>
        </Fact>
        <Fact area="rel" label={t('相对TOPIX')}>
          <RelSigned value={row.rel_topix_20d} />
        </Fact>
      </span>
    </button>
  );
}

const FACT_AREAS = {
  inst: 'lg:[grid-area:inst]',
  d20: 'lg:[grid-area:d20]',
  d5: 'lg:[grid-area:d5]',
  dtc: 'lg:[grid-area:dtc]',
  rel: 'lg:[grid-area:rel]',
} as const;

/** 窄屏带标签；宽屏标签交给表头，但读屏仍念出来。 */
function Fact({ area, label, children }: { area: keyof typeof FACT_AREAS; label: string; children: ReactNode }) {
  return (
    <span className={cn('inline-flex items-baseline gap-1 tnum lg:justify-end lg:text-body-s', FACT_AREAS[area])}>
      <span className="lg:sr-only">{label}</span>
      {children}
    </span>
  );
}

function fmtDays(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value >= 100 ? value.toFixed(0) : value.toFixed(1);
}

/* ---------------- 详情卡 ---------------- */

function DetailCard({ row }: { row: ShortMonitorRow }) {
  const detailQuery = usePolling(() => shortMonitorApi.stock(row.canonical_code), null, [row.canonical_code]);
  const chartQuery = usePolling(() => stocksApi.chart(row.canonical_code, '6m'), null, [row.canonical_code]);
  const eventQuery = usePolling(
    () => shortMonitorApi.events(row.canonical_code, { limit: 60 }),
    null,
    [row.canonical_code],
  );
  const detail = detailQuery.data;
  const detailState = remoteState(detailQuery);
  const events = eventQuery.data?.events ?? [];
  const inScope = row.reported_in_scope_ratio;
  const showInScope = inScope != null && inScope - (row.visible_short_ratio ?? 0) > 0.0005;

  return (
    <article className="card-surface overflow-hidden p-5">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <CrowdingBadge level={row.crowding_level} withLabel />
        <StateBadge state={row.primary_state} />
        {row.security_kind === 'reit' && <SoftBadge>REIT</SoftBadge>}
      </div>
      <h3 className="font-display text-display-m text-ink-900">
        {row.name ?? '—'}{' '}
        <Link
          to={`/stock/${row.display_code}`}
          className="text-brand-600 underline-offset-4 transition-colors hover:text-brand-700 hover:underline"
        >
          {row.display_code}
        </Link>
      </h3>
      <p className="mt-1 text-caption text-ink-500">
        {row.sector33_name ? t(row.sector33_name) : '—'} · {row.market_name ? t(row.market_name) : '—'}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-2">
        <ValueCell label={t('公开持仓比例')} hint={SHORT_HINTS.visibleShort}>
          {fmtPctLevel(row.visible_short_ratio)}
        </ValueCell>
        <ValueCell label={t('近期机构数')} hint={SHORT_HINTS.institutions}>
          {row.visible_institution_count}
        </ValueCell>
        <ValueCell label={t('20日变化')}>
          <ShortDelta value={row.ratio_change_20d} />
        </ValueCell>
        <ValueCell label={t('回补天数')} hint={SHORT_HINTS.daysToCover}>
          {fmtDays(row.visible_days_to_cover)}
        </ValueCell>
      </dl>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-500">
        {showInScope && (
          <span className="inline-flex items-center gap-0.5">
            {t('在册合计')}
            <InfoHint hint={SHORT_HINTS.inScope} size={11} />{' '}
            <span className="tnum text-ink-800">{fmtPctLevel(inScope)}</span>
          </span>
        )}
        <InstitutionStatusNotes row={row} />
      </div>

      <div className="mt-4">
        {chartQuery.data && chartQuery.data.bars.length > 0 ? (
          <LeadChart bars={chartQuery.data.bars} events={events} code={row.display_code} />
        ) : chartQuery.error && !chartQuery.data ? (
          <p className="rounded-[var(--r-control)] bg-paper-2 px-3 py-6 text-center text-micro text-ink-400">
            {t('K 线暂不可用')}
          </p>
        ) : (
          <SkeletonCard className="h-56" />
        )}
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-400">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block size-1.5 rounded-full bg-down-600" aria-hidden />
            {t('公开空头增加')}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block size-1.5 rounded-full bg-up-600" aria-hidden />
            {t('公开空头减少或跌破门槛')}
          </span>
          <span>{t('按披露次一交易日标记')}</span>
        </p>
      </div>

      <DetailSection title={t('机构明细')}>
        {detail ? (
          <HolderTable holders={detail.holders} />
        ) : detailState === 'error' ? (
          <p className="text-micro text-ink-400">{t('机构明细读取失败')}</p>
        ) : (
          <DetailSkeleton />
        )}
      </DetailSection>

      {events.length > 0 && (
        <DetailSection title={t('最近事件')}>
          <ul>
            {events.slice(0, 4).map((event) => (
              <EventLine key={event.event_id} event={event} />
            ))}
          </ul>
        </DetailSection>
      )}

      <DetailSection title={t('当前判定')}>
        {detail ? (
          <Explanation detail={detail} />
        ) : detailState === 'error' ? (
          <p className="text-micro text-ink-400">{t('判定说明读取失败')}</p>
        ) : (
          <DetailSkeleton />
        )}
      </DetailSection>

      {row.flags.length > 0 && (
        <DetailSection title={t('标签')}>
          <FlagList flags={row.flags} />
        </DetailSection>
      )}

      <Link
        to={`/stock/${row.display_code}`}
        className="mobile-control-target mt-4 flex items-center justify-center gap-1.5 rounded-pill bg-brand-600 px-3.5 py-2 text-caption font-medium text-white shadow-btn-hi transition-[transform,background-color] duration-fast hover:bg-brand-700 active:scale-[0.98]"
      >
        {t('打开研究页')}
        <Icon name="arrow-up-right" size={13} />
      </Link>
    </article>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-4 border-t border-line pt-3">
      <h4 className="mb-1.5 text-micro text-ink-400">{title}</h4>
      {children}
    </section>
  );
}

function DetailSkeleton() {
  return (
    <div className="t-skel space-y-1.5" data-state="loading" aria-hidden="true">
      <div className="t-skel-skeleton is-pulsing space-y-1.5">
        <SkeletonBlock className="h-3 w-full" />
        <SkeletonBlock className="h-3 w-4/5" />
      </div>
      <div className="t-skel-content" />
    </div>
  );
}

function ValueCell({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ScoreHint;
  children: ReactNode;
}) {
  return (
    <div className="radar-value-cell min-w-0 px-3 py-2.5">
      <dt className="flex items-center gap-0.5 text-micro text-ink-400">
        <span className="min-w-0 break-words">{label}</span>
        {hint && <InfoHint hint={hint} size={11} className="shrink-0" />}
      </dt>
      <dd className="mt-0.5 tnum text-data-l text-ink-900">{children}</dd>
    </div>
  );
}

/** 状态明细放在指标格外，给三种语言留出完整行宽。 */
function InstitutionStatusNotes({ row }: { row: ShortMonitorRow }) {
  const statuses = [
    {
      count: row.below_threshold_count,
      label: t('低于披露门槛'),
      detail: t('最后报告低于 0.5%，未计入公开持仓与在册合计。'),
    },
    {
      count: row.stale_reporting_count ?? 0,
      label: t('久未更新'),
      detail: t('最后报告达 0.5% 但逾 125 个交易日未更新，仅计入在册合计。'),
    },
    {
      count: row.unknown_institution_count ?? 0,
      label: t('比例缺失'),
      detail: t('最新报告缺少持仓比例，未计入合计。'),
    },
  ].filter((status) => status.count > 0);
  if (!statuses.length) return null;
  return (
    <>
      {statuses.map((status) => (
        <PointerTooltip
          key={status.label}
          label={`${status.label} ${status.count}`}
          className="max-w-full rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
          content={<span className="text-micro leading-relaxed text-ink-600">{status.detail}</span>}
        >
          <span className="min-w-0 whitespace-normal break-words">
            {status.label} <span className="tnum">{status.count}</span>
          </span>
        </PointerTooltip>
      ))}
    </>
  );
}

const HOLDER_STATUS: Record<string, { label: string; order: number }> = {
  reporting: { label: '报告中', order: 0 },
  stale: { label: '久未更新', order: 1 },
  below_public_threshold: { label: '低于披露门槛', order: 2 },
  unknown: { label: '比例缺失', order: 3 },
  closed: { label: '已清零', order: 4 },
};

/** stale_reporting 挂在 visibility_status = reporting 的机构上，先判它。 */
function holderStatusKey(holder: ShortMonitorHolder): string {
  if (holder.visibility_status === 'reporting') return holder.stale_reporting ? 'stale' : 'reporting';
  return HOLDER_STATUS[holder.visibility_status] ? holder.visibility_status : 'unknown';
}

function HolderTable({ holders }: { holders: ShortMonitorHolder[] }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = useMemo(
    () =>
      holders
        .map((holder) => ({ holder, status: holderStatusKey(holder) }))
        .sort(
          (a, b) =>
            HOLDER_STATUS[a.status].order - HOLDER_STATUS[b.status].order ||
            (b.holder.last_reported_ratio ?? -1) - (a.holder.last_reported_ratio ?? -1),
        ),
    [holders],
  );
  if (sorted.length === 0) {
    return <p className="text-micro text-ink-400">{t('当前没有公开披露的机构空头')}</p>;
  }
  const shown = expanded ? sorted : sorted.slice(0, DETAIL_HOLDER_LIMIT);
  const rest = sorted.length - shown.length;
  return (
    <>
      <table className="w-full table-fixed text-micro">
        <colgroup>
          <col />
          <col className="w-[4.75rem]" />
          <col className="w-[3.25rem]" />
          <col className="w-[5.5rem]" />
        </colgroup>
        <thead>
          <tr className="text-ink-400">
            <th scope="col" className="pb-1 text-left font-normal">{t('机构')}</th>
            <th scope="col" className="pb-1 text-right font-normal">{t('最后报告比例')}</th>
            <th scope="col" className="pb-1 text-right font-normal">{t('仓位日')}</th>
            <th scope="col" className="pb-1 pl-2 text-left font-normal">{t('状态')}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ holder, status }) => {
            const live = status === 'reporting';
            return (
              <tr key={holder.legal_id} className="border-t border-line">
                <td className="truncate py-1.5 pr-2 text-ink-700" title={holder.name}>{holder.name}</td>
                <td className={cn('py-1.5 text-right tnum', live ? 'text-ink-900' : 'text-ink-500')}>
                  {fmtPctLevel(holder.last_reported_ratio)}
                </td>
                <td className="py-1.5 text-right tnum text-ink-500">{fmtDateShort(holder.last_position_date)}</td>
                <td className={cn('py-1.5 pl-2', live ? 'text-ink-700' : 'text-ink-500')}>
                  {t(HOLDER_STATUS[status].label)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(rest > 0 || expanded) && sorted.length > DETAIL_HOLDER_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mobile-control-target mt-1.5 rounded-pill bg-paper-2 px-2.5 py-1 text-micro text-ink-600 transition-colors hover:bg-brand-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
        >
          {expanded ? t('收起') : t('另有 {n} 家', { n: rest })}
        </button>
      )}
    </>
  );
}

function Explanation({ detail }: { detail: ShortMonitorDetail }) {
  return (
    <div>
      <p className="mb-1.5 flex items-center gap-1.5 text-micro text-ink-400">
        <SoftBadge>{t(detail.explanation.state_label)}</SoftBadge>
      </p>
      <ul className="space-y-1 text-caption leading-relaxed text-ink-600">
        {/* 后端返回模板 + 参数（它不知道对方的语言）。替换在这里经 t()：
            词典以中文原文作 msgid，模板本身就是 msgid。没有 line_items 的
            旧响应退回到已替换好的中文。 */}
        {(detail.explanation.line_items ?? []).length > 0
          ? detail.explanation.line_items!.map((item, index) => <li key={index}>{explanationLine(item)}</li>)
          : detail.explanation.lines.map((line, index) => <li key={index}>{line}</li>)}
      </ul>
      {detail.explanation.caveat && (
        <p className="mt-1.5 rounded-[var(--r-control)] border border-line bg-paper-2/60 px-2.5 py-2 text-micro text-ink-500">
          {t(detail.explanation.caveat)}
        </p>
      )}
    </div>
  );
}

/** 6 个月日线 + 机构空卖事件标记。
 *
 *  标记打在 `effective_trade_date`（公开日之后的首个交易日）而不是仓位日：
 *  市场在公开之前不可能知道这件事，标在仓位日等于把未来信息画进过去。 */
function LeadChart({ bars, events, code }: { bars: StockBar[]; events: ShortMonitorEvent[]; code: string }) {
  const colorMode = useColorMode();
  const option = useMemo(() => {
    void colorMode;
    const dates = bars.map((bar) => bar.trade_date.slice(5));
    const candles = bars.map((bar) => [
      bar.adj_open ?? bar.open,
      bar.adj_close ?? bar.close,
      bar.adj_low ?? bar.low,
      bar.adj_high ?? bar.high,
    ]);
    const indexByDate = new Map(bars.map((bar, index) => [bar.trade_date, index]));

    /* 同一天可能有多家机构同时公开，合成一个标记（否则密集处会叠成一坨）。 */
    const byDate = new Map<number, number>();
    for (const event of events) {
      const index = indexByDate.get(event.effective_trade_date);
      if (index === undefined) continue; // 窗口之外
      const delta = Number.isFinite(event.ratio_delta ?? NaN) ? (event.ratio_delta as number) : 0;
      byDate.set(index, (byDate.get(index) ?? 0) + delta);
    }
    const marks = [...byDate.entries()]
      .filter(([index, delta]) => delta !== 0 && (bars[index].adj_high ?? bars[index].high) !== null)
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .slice(0, 14)
      .map(([index, delta]) => ({
        // 空头增加 = 卖方进场 = 对股价不利 = 跌色；减少 = 涨色。与个股页的事件配色一致。
        coord: [index, (bars[index].adj_high ?? bars[index].high) as number],
        symbol: 'circle',
        symbolSize: 7,
        symbolOffset: [0, -10],
        itemStyle: { color: delta > 0 ? CH.down600 : CH.up600 },
        name: `${bars[index].trade_date} ${delta > 0 ? '+' : '−'}${Math.abs(delta * 100).toFixed(2)}%`,
        value: '',
      }));

    return {
      // containLabel 不看首个类目标签的溢出 —— left 收得太紧会把 "01-20" 截成 "1-20"（实测）。
      grid: baseGrid({ top: 10, bottom: 4, left: 16, right: 44 }),
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: categoryAxis(dates),
      yAxis: valueAxis({ scale: true, position: 'right' }),
      series: [
        {
          type: 'candlestick' as const,
          data: candles,
          itemStyle: {
            color: CH.up600, color0: CH.down600,
            borderColor: CH.up600, borderColor0: CH.down600,
          },
          markPoint: { silent: true, animation: false, data: marks },
        },
      ],
    };
  }, [bars, colorMode, events]);
  return <ReactECharts className="h-56 w-full" option={option} ariaLabel={`${code} short monitor chart`} />;
}

function EventLine({ event }: { event: ShortMonitorEvent }) {
  return (
    <li className="flex min-h-11 items-center gap-3 border-b border-line px-1 py-2 last:border-b-0">
      <span className="w-11 shrink-0 tnum text-tag text-ink-400">{fmtDateShort(event.effective_trade_date)}</span>
      <span className="min-w-0 flex-1 truncate text-caption text-ink-700">{event.institution}</span>
      <span className="shrink-0 tnum text-micro text-ink-500">{fmtPctLevel(event.short_ratio)}</span>
      <ShortDelta value={event.ratio_delta} className="w-16 shrink-0 text-right text-micro" />
    </li>
  );
}

/* ---------------- 小件 ---------------- */

/** 拥挤度：三格刻度用警示色阶表示程度，不用涨跌色。 */
function CrowdingMeter({ level }: { level: ShortCrowdingLevel }) {
  return (
    <span className="inline-flex shrink-0 items-end gap-px" aria-hidden>
      {[1, 2, 3].map((step) => (
        <span
          key={step}
          className={cn('w-[3px] rounded-pill', step <= level ? 'bg-warn-600' : 'bg-line')}
          style={{ height: `${4 + step * 2}px` }}
        />
      ))}
    </span>
  );
}

function CrowdingBadge({ level, withLabel = false }: { level: ShortCrowdingLevel; withLabel?: boolean }) {
  const label = t(CROWDING_LABELS[level] ?? '无');
  return (
    <SoftBadge tone={level >= 3 ? 'warn' : 'neutral'}>
      <CrowdingMeter level={level} />
      {withLabel ? `${t('拥挤度')} ${label}` : (
        <>
          <span className="sr-only">{t('拥挤度')} </span>
          {label}
        </>
      )}
    </SoftBadge>
  );
}

/** 动向徽标：中性色。 */
function StateBadge({ state }: { state: string }) {
  return <SoftBadge>{t(STATE_LABELS[state] ?? state)}</SoftBadge>;
}

function FlagList({ flags }: { flags: string[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {flags.map((flag) => (
        <SoftBadge key={flag} tone={RISK_FLAGS.has(flag) ? 'warn' : 'neutral'}>
          {t(FLAG_LABELS[flag] ?? flag)}
        </SoftBadge>
      ))}
    </span>
  );
}

/** 相对收益。红涨绿跌 —— 这里的正负就是股价相对强弱本身。 */
function RelSigned({ value }: { value: number | null }) {
  if (value == null) return <span className="tnum text-ink-400">—</span>;
  return (
    <span className={cn('tnum', value > 0 ? 'text-up-600' : value < 0 ? 'text-down-600' : 'text-ink-400')}>
      {fmtPct(value)}
    </span>
  );
}

/** 公开空头的变化。
 *
 *  **按对股价的方向着色，不按数字符号。** 空头增加是卖方进场（跌色），空头减少
 *  是买方回补（涨色）—— 与个股页「机构空卖」区块的事件配色一致。
 *  排行行是整行按钮，这里只用 title 补充说明，不再套一层可交互的提示。 */
function ShortDelta({ value, className }: { value: number | null; className?: string }) {
  if (value == null) return <span className={cn('tnum text-ink-400', className)}>—</span>;
  const tip = value > 0 ? t('公开空头增加（卖压增强）') : value < 0 ? t('公开空头减少（买方回补）') : undefined;
  return (
    <span
      title={tip}
      className={cn('tnum', value > 0 ? 'text-down-600' : value < 0 ? 'text-up-600' : 'text-ink-400', className)}
    >
      {fmtPct(value)}
    </span>
  );
}
