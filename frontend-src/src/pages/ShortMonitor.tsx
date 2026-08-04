/* 机构空卖行为监控。版式对标突破雷达（§03）与选股扫描（§04）：
 * 页头带 → 断面概览 → 工具行 → Lead 大卡 → 卡片流 / 列表。
 *
 * 这一页展示的是「达到公开披露条件的机构空卖持仓」的变化，以及股价对这部分
 * 压力的反应。不是市场全部空头，也不是「空头增加就看跌」的机械指标。
 *
 * 四条不能违反的界面纪律：
 *   1. 顶部语义提示常驻，不随滚动消失；
 *   2. 跌破门槛的机构单独计数，绝不并入合计，也不画成 0；
 *   3. 门槛与权重未经历史验证时，页面自己说出来 —— 「还没验证」和「验证过
 *      但没通过」是两件事，不能用前者的说法讲后者；
 *   4. **状态徽章不用涨跌色表达「看多／看空」。** 走步验证的结论是：设计上
 *      看多的「卖压吸收」表现最差、看空的「背离失效」反而略好。用红绿给状态
 *      上色，等于把界面做成一个已经被自家数据否定的主张。 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import PageHeader from '@/components/shared/PageHeader';
import Segmented from '@/components/shared/Segmented';
import EmptyState from '@/components/shared/EmptyState';
import StatCard from '@/components/shared/StatCard';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough, ScoreBar } from '@/components/domain';
import ReactECharts from '@/components/charts/ReactECharts';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { shortMonitorApi, stocksApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import type {
  ShortMonitorDetail,
  ShortMonitorEvent,
  ShortMonitorOverview,
  ShortMonitorRow,
  StockBar,
} from '@/api/types';
import { fmtDate, fmtDateShort, fmtPct, fmtPctLevel, fmtPrice, fmtScore } from '@/lib/format';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';

type ViewMode = 'cards' | 'table';

const VIEWS: { key: string; label: string; hint: string }[] = [
  { key: 'absorption', label: '卖压吸收', hint: '空头压力较高，单位压力造成的价格损害较低' },
  { key: 'low_conflict', label: '低位增空不跌', hint: '深度低位 + 公开空头增加或重新进入' },
  { key: 'covering', label: '回补加速', hint: '多家机构减仓、公开空头快速下降' },
  { key: 'reentry', label: '机构重新进入', hint: '一度跌破门槛后再次进入公开范围' },
  { key: 'rotation', label: '机构轮换', hint: '一批退出、另一批进入。本身不是利好或利空' },
  { key: 'squeeze', label: '挤空确认', hint: '仅展示满足全部严格价格确认条件的股票' },
  { key: 'divergence_failed', label: '背离失效', hint: '空头继续增加且股价跌破长期支撑' },
  { key: 'all', label: '全部', hint: '当日全部覆盖股票' },
];

const STATE_LABELS: Record<string, string> = {
  normal_shorting: '正常做空',
  low_conflict: '低位冲突',
  absorption: '卖压吸收',
  covering_start: '回补启动',
  squeeze_confirmed: '挤空确认',
  divergence_failed: '背离失效',
  no_signal: '无动向',
};

/* 状态点的颜色是「分类色」，不是涨跌色 —— 只有 `divergence_failed` 用了下跌色，
   因为它的定义里本来就含一条价格事实（跌破长期支撑且相对继续恶化）。
   其余状态一律用中性色系：走步验证否定了它们的方向性，界面不替它下结论。 */
const STATE_DOTS: Record<string, string> = {
  squeeze_confirmed: 'bg-warn-600',
  absorption: 'bg-brand-600',
  covering_start: 'bg-ai-600',
  low_conflict: 'bg-brand-400',
  divergence_failed: 'bg-down-600',
  normal_shorting: 'bg-ink-300',
  no_signal: 'bg-line',
};

const FLAG_LABELS: Record<string, string> = {
  new_entry: '新规进入',
  reentry: '重新进入',
  rotation: '机构轮换',
  concentrated: '空头集中',
  multi_reduction: '多机构减仓',
  below_threshold: '跌破门槛',
  not_visible: '数据不可见',
  crowded_margin: '信用买入拥挤',
  regulated: '信用规制',
  earnings_near: '财报临近',
  news_catalyst: '新闻催化',
  thin_liquidity: '低流动性',
  stale_data: '数据过期',
  hedge_disclosed: '含对冲持仓',
  single_institution: '仅1家可见',
};

/** 会降低这一行可信度的标签，与「发生了什么」的事件标签分开着色。 */
const RISK_FLAGS = new Set([
  'not_visible', 'crowded_margin', 'regulated', 'thin_liquidity',
  'stale_data', 'hedge_disclosed', 'single_institution',
]);

/** 概览里点得动的四个状态。数字不只是数字，是一个入口。 */
const HEADLINE_STATES: { state: string; view: string }[] = [
  { state: 'absorption', view: 'absorption' },
  { state: 'covering_start', view: 'covering' },
  { state: 'squeeze_confirmed', view: 'squeeze' },
  { state: 'divergence_failed', view: 'divergence_failed' },
];

export default function ShortMonitor() {
  const [view, setView] = useState('absorption');
  const [mode, setMode] = useState<ViewMode>('cards');
  const [minConfidence, setMinConfidence] = useState(0);
  const [leadCode, setLeadCode] = useState<string | null>(null);

  const overviewQuery = usePolling(() => shortMonitorApi.overview(), 600_000, []);
  const rankingQuery = usePolling(
    () => shortMonitorApi.rankings({ view, limit: 60, min_confidence: minConfidence || undefined }),
    600_000,
    [view, minConfidence],
  );
  const state = remoteState(rankingQuery, (d) => d.rows.length === 0);
  const overview = overviewQuery.data;

  const rows = useMemo(() => rankingQuery.data?.rows ?? [], [rankingQuery.data]);
  const lead = useMemo(() => {
    if (leadCode) {
      const picked = rows.find((row) => row.canonical_code === leadCode);
      if (picked) return picked;
    }
    return rows[0] ?? null;
  }, [rows, leadCode]);

  // 换视图后旧的选中项通常已不在结果里，退回该视图的首位。
  useEffect(() => {
    setLeadCode(null);
  }, [view, minConfidence]);

  const activeView = useMemo(() => VIEWS.find((v) => v.key === view) ?? VIEWS[0], [view]);
  // 「还没验证」和「验证过但没通过」要分开说。
  const validation = overview?.validation;
  const unvalidated = overview?.validated && !overview.validated.score;

  return (
    <div className="space-y-6">
      <PageHeader
        section="09"
        eyebrow="SHORT MONITOR · POST-CLOSE"
        title={t('机构空卖行为监控')}
        description={t('公开披露的机构空卖持仓发生了什么变化，股价对这部分压力作出了什么反应')}
        meta={<DataThrough date={overview?.as_of_date} />}
      />

      {/* 语义提示常驻。这一句不能因为版面紧张就删掉。 */}
      <p className="flex items-start gap-2 text-caption text-ink-500">
        <span className="mt-1.5 inline-block size-1.5 shrink-0 rounded-full bg-ink-300" aria-hidden />
        {t('本页面展示达到公开披露条件的机构空卖持仓，不代表市场全部空头仓位。跌破公开门槛不代表仓位归零。')}
      </p>

      {validation?.status === 'failed' ? (
        <section className="card-surface border-warn-200 bg-warn-50/60 p-4">
          <p className="flex items-center gap-2">
            <span className="eyebrow text-warn-700">{t('历史验证结果')}</span>
            <span className="rounded-xs bg-warn-600/10 px-1.5 py-px font-mono text-micro text-warn-700">
              {t('未通过')}
            </span>
          </p>
          <p className="mt-2 text-body-s text-ink-700">{validation.summary}</p>
          {validation.run && (
            <p className="mt-1 font-mono text-micro tnum text-ink-400">
              {validation.run} · {validation.signals ?? 0} {t('个信号')} · {validation.windows ?? 0}{' '}
              {t('个走步窗口')}
            </p>
          )}
        </section>
      ) : unvalidated ? (
        <p className="rounded-md border border-warn-200 bg-warn-50 px-3 py-2 text-caption text-warn-700">
          {t('当前门槛与权重为初始参数，尚未通过历史验证，仅作研究排序使用。')}
        </p>
      ) : null}

      {overview ? <OverviewCards overview={overview} onPickView={setView} /> : <OverviewSkeleton />}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <Segmented<string>
          options={VIEWS.map((item) => ({ value: item.key, label: t(item.label) }))}
          value={view}
          onChange={setView}
        />
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-caption text-ink-400">
            {t('最低数据置信度')}
            <select
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
              className="rounded-md border border-line bg-card px-2 py-1 font-mono text-caption tnum text-ink-800"
            >
              <option value={0}>{t('不限')}</option>
              <option value={0.35}>0.35</option>
              <option value={0.6}>0.60</option>
              <option value={0.8}>0.80</option>
            </select>
          </label>
          <Segmented<ViewMode>
            options={[
              { value: 'cards', label: t('卡片') },
              { value: 'table', label: t('列表') },
            ]}
            value={mode}
            onChange={setMode}
          />
        </div>
      </div>
      <p className="-mt-3 text-micro text-ink-400">{t(activeView.hint)}</p>

      {state === 'loading' ? (
        <>
          <SkeletonCard className="h-80" />
          <SkeletonRows rows={6} />
        </>
      ) : state === 'error' ? (
        <div className="card-surface">
          <EmptyState
            variant="error"
            title={t('读取失败')}
            description={String(rankingQuery.error?.message ?? '')}
          />
        </div>
      ) : state === 'empty' ? (
        <div className="card-surface">
          <EmptyState
            title={t('该视图当前没有符合条件的股票')}
            description={minConfidence > 0 ? t('可以把最低数据置信度放宽到「不限」再看一次') : undefined}
          />
        </div>
      ) : (
        <>
          {lead && <LeadCard key={lead.canonical_code} row={lead} />}
          {mode === 'cards' ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {rows
                .filter((row) => row.canonical_code !== lead?.canonical_code)
                .map((row) => (
                  <StockCard
                    key={row.canonical_code}
                    row={row}
                    onSelect={() => {
                      setLeadCode(row.canonical_code);
                      window.scrollTo({ top: 0, behavior: 'smooth' });
                    }}
                  />
                ))}
            </div>
          ) : (
            <ShortTable
              rows={rows}
              onSelect={(row) => {
                setLeadCode(row.canonical_code);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            />
          )}
          <div className="space-y-1 text-micro text-ink-400">
            <p>
              {t('机构数后的 +N? 是实际持仓不可见的机构家数（跌破门槛，或未跌破但报告长期停止），均不计入合计')}
            </p>
            {/* 同一页上「空头变化」和「相对收益」用同一组红绿，含义却不同 ——
                不写清楚，+0.71% 是绿、+11.94% 是红这件事就只能靠猜。 */}
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex items-center gap-1 text-down-600">
                <span className="inline-block size-1.5 rounded-full bg-down-600" aria-hidden />
                {t('公开空头增加（卖压增强）')}
              </span>
              <span className="inline-flex items-center gap-1 text-up-600">
                <span className="inline-block size-1.5 rounded-full bg-up-600" aria-hidden />
                {t('公开空头减少（买方回补）')}
              </span>
              <span>{t('空头变化按对股价的方向着色；相对收益仍是红涨绿跌')}</span>
            </p>
          </div>
        </>
      )}
    </div>
  );
}

/* ---------------- 断面概览 ---------------- */

function OverviewSkeleton() {
  /* 手机上 4 张卡竖着排要滚半屏才见到列表 —— 数字卡两列，状态分布占满一行。 */
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
  onPickView,
}: {
  overview: ShortMonitorOverview;
  onPickView: (view: string) => void;
}) {
  const coverage = overview.coverage;
  const covered = coverage?.covered ?? 0;
  const share = (value: number) => (covered > 0 ? `${((value / covered) * 100).toFixed(1)}%` : '—');
  /* 手机上 4 张卡竖着排要滚半屏才见到列表 —— 数字卡两列，状态分布占满一行。 */
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <StatCard
        label={t('覆盖股票')}
        value={covered}
        icon="dots-grid"
        sub={`${t('数据截至')} ${fmtDate(overview.as_of_date)}`}
      />
      <StatCard
        label={t('有公开机构空头')}
        value={coverage?.with_visible_short ?? 0}
        icon="filter-funnel"
        sub={t('占覆盖 {p}', { p: share(coverage?.with_visible_short ?? 0) })}
      />
      <StatCard
        label={t('置信度偏低')}
        value={coverage?.low_confidence ?? 0}
        icon="clock-ny"
        sub={t('占覆盖 {p} · 报告陈旧、可见机构少或流动性薄', { p: share(coverage?.low_confidence ?? 0) })}
        // 2 列のとき 3 枚目が半端に余る。横いっぱいに伸ばして空きマスを作らない。
        className="col-span-2 xl:col-span-1"
      />
      <StateDistribution states={overview.states ?? {}} onPickView={onPickView} />
    </div>
  );
}

function StateDistribution({
  states,
  onPickView,
}: {
  states: Record<string, number>;
  onPickView: (view: string) => void;
}) {
  const max = Math.max(1, ...HEADLINE_STATES.map((item) => states[item.state] ?? 0));
  return (
    <div className="card-surface col-span-2 p-5 xl:col-span-1">
      <p className="eyebrow">{t('状态分布')}</p>
      <ul className="mt-3 space-y-1.5">
        {HEADLINE_STATES.map((item) => {
          const count = states[item.state] ?? 0;
          return (
            <li key={item.state}>
              <button
                type="button"
                onClick={() => onPickView(item.view)}
                className="group flex w-full items-center gap-2 rounded-xs text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30"
              >
                <span
                  className={cn('size-1.5 shrink-0 rounded-full', STATE_DOTS[item.state] ?? 'bg-ink-300')}
                  aria-hidden
                />
                <span className="w-16 shrink-0 truncate text-caption text-ink-500 group-hover:text-ink-800">
                  {t(STATE_LABELS[item.state] ?? item.state)}
                </span>
                <span className="relative h-1 flex-1 overflow-hidden rounded-pill bg-line">
                  <span
                    className={cn('absolute inset-y-0 left-0 rounded-pill', STATE_DOTS[item.state] ?? 'bg-ink-300')}
                    style={{ width: `${Math.max(2, (count / max) * 100)}%` }}
                  />
                </span>
                <span className="w-8 shrink-0 text-right font-mono text-caption tnum text-ink-800">{count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ---------------- Lead 大卡 ---------------- */

function LeadCard({ row }: { row: ShortMonitorRow }) {
  const detailQuery = usePolling(
    () => shortMonitorApi.stock(row.canonical_code),
    null,
    [row.canonical_code],
  );
  const chartQuery = usePolling(() => stocksApi.chart(row.canonical_code, '6m'), null, [row.canonical_code]);
  const eventQuery = usePolling(
    () => shortMonitorApi.events(row.canonical_code, { limit: 60 }),
    null,
    [row.canonical_code],
  );
  const detail = detailQuery.data;
  const events = eventQuery.data?.events ?? [];
  const invisible = row.below_threshold_count + (row.stale_reporting_count ?? 0);

  return (
    <section className="card-surface overflow-hidden rounded-xl">
      <div className="grid grid-cols-1 lg:grid-cols-3">
        {/* 左 2/3：标题 + 事实 + K 线（机构事件标在图上） */}
        <div className="border-line p-4 lg:col-span-2 lg:border-r">
          <header className="mb-2 flex flex-wrap items-center gap-2">
            <CodeCell displayCode={row.display_code} nameJa={row.name} to={`/stock/${row.display_code}`} />
            <ShortStateChip state={row.primary_state} />
            <span className="ml-auto flex items-baseline gap-1.5">
              <span className="text-micro text-ink-400">{t('行为分')}</span>
              <span className="font-mono text-display-m tnum text-ink-900">{fmtScore(row.behavior_score)}</span>
            </span>
          </header>
          <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-500">
            <span>
              {row.sector33_name ?? '—'} · {row.market_name ?? '—'}
            </span>
            <span>
              {t('收盘')} <span className="font-mono tnum text-ink-800">{fmtPrice(row.close)}</span>
            </span>
            <span>
              {t('公开可见空头')}{' '}
              <span className="font-mono tnum text-ink-800">{fmtPctLevel(row.visible_short_ratio)}</span>
            </span>
            <span>
              {t('机构数')}{' '}
              <span className="font-mono tnum text-ink-800">
                {row.visible_institution_count}
                {invisible > 0 && <span className="text-ink-400"> +{invisible}?</span>}
              </span>
            </span>
            <span>
              {t('公开可见回补天数')}{' '}
              <span className="font-mono tnum text-ink-800">
                {row.visible_days_to_cover != null ? row.visible_days_to_cover.toFixed(2) : '—'}
              </span>
            </span>
          </div>

          {chartQuery.data && chartQuery.data.bars.length > 0 ? (
            <LeadChart bars={chartQuery.data.bars} events={events} code={row.display_code} />
          ) : (
            <SkeletonCard className="h-64" />
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
            <span>{t('标在公开日之后的首个交易日 —— 市场最早能知道的那天')}</span>
          </p>

          {events.length > 0 && (
            <ul className="mt-3 divide-y divide-line border-t border-line">
              {events.slice(0, 4).map((event) => (
                <EventLine key={event.event_id} event={event} />
              ))}
            </ul>
          )}

          <FlagList flags={row.flags} className="mt-3" max={8} />
        </div>

        {/* 右 1/3：分项 → 风险与置信度 → 判定说明 */}
        <div className="flex flex-col gap-3 p-4">
          <div className="space-y-1.5">
            <ScoreBar label="低位" score={row.scores.low_position} hint={false} />
            <ScoreBar label="空头压力" score={row.scores.short_pressure} hint={false} />
            <ScoreBar label="卖压吸收" score={row.scores.absorption} hint={false} />
            <ScoreBar label="回补强度" score={row.scores.covering} hint={false} />
            <ScoreBar label="机构轮换" score={row.scores.rotation} hint={false} />
            <ScoreBar label="催化" score={row.scores.catalyst} hint={false} />
          </div>
          <dl className="flex items-center gap-4 border-t border-line pt-2.5 text-caption">
            <div className="flex items-baseline gap-1.5">
              <dt className="text-ink-400">{t('风险减分')}</dt>
              <dd className="font-mono tnum text-warn-700">{fmtScore(row.scores.risk)}</dd>
            </div>
            <div className="flex items-baseline gap-1.5">
              <dt className="text-ink-400">{t('数据置信度')}</dt>
              <dd className="font-mono tnum text-ink-800">{row.data_confidence?.toFixed(2) ?? '—'}</dd>
            </div>
          </dl>

          {detail ? (
            <Explanation detail={detail} />
          ) : (
            <div className="space-y-1.5 border-t border-line pt-2.5">
              <span className="skeleton-shimmer block h-3 w-full rounded-sm" aria-hidden />
              <span className="skeleton-shimmer block h-3 w-4/5 rounded-sm" aria-hidden />
            </div>
          )}

          <Link
            to={`/stock/${row.display_code}`}
            className="mt-auto rounded-md border border-line py-1.5 text-center text-body-s text-brand-700 hover:bg-brand-50"
          >
            {t('个股研究')} →
          </Link>
        </div>
      </div>
    </section>
  );
}

function Explanation({ detail }: { detail: ShortMonitorDetail }) {
  return (
    <div className="border-t border-line pt-2.5">
      <p className="mb-1.5 flex items-center gap-1.5 text-micro text-ink-400">
        {t('当前判定')}
        <ShortStateChip state={detail.explanation.state} label={detail.explanation.state_label} />
      </p>
      <ul className="space-y-1 text-caption leading-relaxed text-ink-600">
        {detail.explanation.lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
      {detail.explanation.caveat && (
        <p className="mt-1.5 border-l-2 border-warn-200 pl-2 text-micro text-ink-500">
          {detail.explanation.caveat}
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
  const option = useMemo(() => {
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
        // 空头增加 = 卖方进场 = 对股价不利 = 绿；减少 = 红。与个股页的事件配色一致。
        coord: [index, (bars[index].adj_high ?? bars[index].high) as number],
        symbol: 'circle',
        symbolSize: 7,
        symbolOffset: [0, -10],
        itemStyle: { color: delta > 0 ? CH.down600 : CH.up600 },
        name: `${bars[index].trade_date} ${delta > 0 ? '+' : '−'}${Math.abs(delta * 100).toFixed(2)}%`,
        value: '',
      }));

    return {
      // containLabel は最初のカテゴリラベルのはみ出しを見てくれない ——
      // left を詰めると "01-20" が "1-20" に欠ける（実測）。
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
  }, [bars, events]);
  return <ReactECharts className="h-64 w-full" option={option} ariaLabel={`${code} short monitor chart`} />;
}

function EventLine({ event }: { event: ShortMonitorEvent }) {
  const delta = event.ratio_delta;
  return (
    <li className="flex items-baseline gap-2 py-1 text-caption">
      <span className="font-mono text-micro tnum text-ink-400">{fmtDateShort(event.effective_trade_date)}</span>
      <span className="min-w-0 flex-1 truncate text-ink-600">{event.institution}</span>
      <span className="shrink-0 font-mono tnum text-ink-500">{fmtPctLevel(event.short_ratio)}</span>
      <ShortDelta value={delta} className="w-16 shrink-0 text-right" />
    </li>
  );
}

/* ---------------- 卡片流 ---------------- */

function StockCard({ row, onSelect }: { row: ShortMonitorRow; onSelect: () => void }) {
  const invisible = row.below_threshold_count + (row.stale_reporting_count ?? 0);
  return (
    <button
      type="button"
      onClick={onSelect}
      className="card-surface card-hover flex flex-col gap-2 rounded-lg p-3 text-left"
    >
      <div className="flex items-center gap-2">
        <CodeCell displayCode={row.display_code} nameJa={row.name} />
        <span className="ml-auto font-mono text-data-l tnum text-ink-900">{fmtScore(row.behavior_score)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <ShortStateChip state={row.primary_state} />
        <FlagList flags={row.flags} max={2} />
      </div>
      <div className="grid grid-cols-3 gap-1 text-caption">
        <CardFact label={t('公开可见空头')} value={fmtPctLevel(row.visible_short_ratio)} />
        <CardFact label={t('5日变化')} value={<ShortDelta value={row.ratio_change_5d} />} />
        <CardFact
          label={t('机构数')}
          value={
            <>
              {row.visible_institution_count}
              {invisible > 0 && <span className="text-ink-400"> +{invisible}?</span>}
            </>
          }
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-micro text-ink-400">
        <span>
          {t('相对TOPIX')} <RelSigned value={row.rel_topix_20d} />
        </span>
        <span>·</span>
        <span>
          {t('52周回撤')} <span className="font-mono tnum">{fmtPct(row.drawdown_52w)}</span>
        </span>
        <span className="ml-auto font-mono tnum">
          {t('置信度')} {row.data_confidence?.toFixed(2) ?? '—'}
        </span>
      </div>
    </button>
  );
}

function CardFact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="rounded-md bg-paper-2 px-1.5 py-1">
      <span className="block truncate text-micro text-ink-400">{label}</span>
      <span className="font-mono text-body-s tnum text-ink-800">{value}</span>
    </span>
  );
}

/* ---------------- 列表 ---------------- */

function ShortTable({ rows, onSelect }: { rows: ShortMonitorRow[]; onSelect: (row: ShortMonitorRow) => void }) {
  const columns = useMemo<Column<ShortMonitorRow>[]>(
    () => [
      {
        key: 'code', title: <Th>{t('代码')}</Th>, width: '220px',
        /* table-layout は auto なので th の width はただの希望。長い社名が
           入ると列が勝手に伸びて、最後の「标签」列が画面外に押し出される
           —— 中身側を実寸で止める。 */
        render: (row) => (
          <div className="flex w-[188px]">
            <CodeCell displayCode={row.display_code} nameJa={row.name} to={`/stock/${row.display_code}`} />
          </div>
        ),
      },
      { key: 'state', title: <Th>{t('状态')}</Th>, render: (row) => <ShortStateChip state={row.primary_state} /> },
      {
        key: 'score', title: <Th>{t('行为分')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.behavior_score ?? -1,
        render: (row) => (
          <span className="font-mono text-data-m tnum text-ink-900">{fmtScore(row.behavior_score)}</span>
        ),
      },
      {
        key: 'confidence', title: <Th>{t('置信度')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.data_confidence ?? -1,
        render: (row) => (
          <span className="font-mono text-caption tnum text-ink-500">
            {row.data_confidence?.toFixed(2) ?? '—'}
          </span>
        ),
      },
      {
        key: 'visible', title: <Th>{t('公开可见空头')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.visible_short_ratio ?? -1,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-800">{fmtPctLevel(row.visible_short_ratio)}</span>
        ),
      },
      {
        key: 'change5', title: <Th>{t('5日变化')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.ratio_change_5d ?? 0,
        render: (row) => <ShortDelta value={row.ratio_change_5d} />,
      },
      {
        key: 'pressure', title: <Th>{t('变化/ADV20')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.pressure_adv20_20d ?? 0,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">
            {row.pressure_adv20_20d != null ? row.pressure_adv20_20d.toFixed(2) : '—'}
          </span>
        ),
      },
      {
        key: 'institutions', title: <Th>{t('机构数')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.visible_institution_count,
        render: (row) => {
          const invisible = row.below_threshold_count + (row.stale_reporting_count ?? 0);
          return (
            <span className="font-mono text-body-s tnum text-ink-800">
              {row.visible_institution_count}
              {invisible > 0 && <span className="text-micro text-ink-400"> +{invisible}?</span>}
            </span>
          );
        },
      },
      {
        key: 'topix', title: <Th>{t('相对TOPIX')}</Th>, align: 'right', sortable: true,
        sortValue: (row) => row.rel_topix_20d ?? 0,
        render: (row) => <RelSigned value={row.rel_topix_20d} />,
      },
      {
        key: 'flags', title: <Th>{t('标签')}</Th>, width: '160px',
        render: (row) => (
          <div className="w-[128px]">
            {/* 2 枚だと 128px に収まらず 2 枚目が途中で切れる。列は 1 枚 + 「+N」。 */}
            <FlagList flags={row.flags} max={1} wrap={false} />
          </div>
        ),
      },
    ],
    [],
  );
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.canonical_code}
      rowHeight={44}
      onRowClick={onSelect}
    />
  );
}

/* ---------------- 小件 ---------------- */

/** 表头。**绝不换行** —— 表头的 eyebrow 字距把中文撑得很宽，一挤就会把
 *  「行为分」劈成「行为 / 分」。表格本身横向可滚，宁可滚也不要劈字。 */
function Th({ children }: { children: React.ReactNode }) {
  return <span className="whitespace-nowrap">{children}</span>;
}

/** 状态徽章。点是分类色，**不是涨跌色** —— 详见文件头第 4 条。 */
function ShortStateChip({ state, label }: { state: string; label?: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-pill border border-line bg-card px-2 py-0.5 text-micro text-ink-700">
      <span className={cn('size-1.5 rounded-full', STATE_DOTS[state] ?? 'bg-ink-300')} aria-hidden />
      {t(label ?? STATE_LABELS[state] ?? state)}
    </span>
  );
}

function FlagList({
  flags,
  max = 2,
  wrap = true,
  className,
}: {
  flags: string[];
  max?: number;
  /** 表格里关掉：换行会把固定 44px 的行撑高，一屏里行高就参差不齐。 */
  wrap?: boolean;
  className?: string;
}) {
  if (!flags?.length) return <span className="text-micro text-ink-300">—</span>;
  const shown = flags.slice(0, max);
  const rest = flags.slice(max);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1',
        wrap ? 'flex-wrap' : 'max-w-full flex-nowrap overflow-hidden',
        className,
      )}
    >
      {shown.map((flag) => (
        <span
          key={flag}
          className={cn(
            'whitespace-nowrap rounded-xs px-1.5 py-0.5 text-micro',
            RISK_FLAGS.has(flag) ? 'bg-warn-50 text-warn-700' : 'bg-paper-2 text-ink-500',
          )}
        >
          {t(FLAG_LABELS[flag] ?? flag)}
        </span>
      ))}
      {rest.length > 0 && (
        <span
          className="whitespace-nowrap rounded-xs bg-paper-2 px-1 py-0.5 text-micro text-ink-400"
          title={rest.map((flag) => t(FLAG_LABELS[flag] ?? flag)).join(' · ')}
        >
          +{rest.length}
        </span>
      )}
    </span>
  );
}

/** 相对收益。红涨绿跌 —— 这里的正负就是股价相对强弱本身。 */
function RelSigned({ value }: { value: number | null }) {
  if (value == null) return <span className="font-mono tnum text-ink-400">—</span>;
  return (
    <span className={cn('font-mono tnum', value > 0 ? 'text-up-600' : value < 0 ? 'text-down-600' : 'text-ink-400')}>
      {fmtPct(value)}
    </span>
  );
}

/** 公开空头的变化。
 *
 *  **按对股价的方向着色，不按数字符号。** 空头增加是卖方进场（绿），空头减少
 *  是买方回补（红）—— 与个股页「机构空卖行为」区块的事件配色一致。同一件事
 *  在两个页面上是相反的颜色，比任何一种约定都糟。 */
function ShortDelta({ value, className }: { value: number | null; className?: string }) {
  if (value == null) return <span className={cn('font-mono tnum text-ink-400', className)}>—</span>;
  return (
    <span
      className={cn(
        'font-mono tnum',
        value > 0 ? 'text-down-600' : value < 0 ? 'text-up-600' : 'text-ink-400',
        className,
      )}
      title={value > 0 ? t('公开空头增加（卖压增强）') : value < 0 ? t('公开空头减少（买方回补）') : undefined}
    >
      {fmtPct(value)}
    </span>
  );
}
