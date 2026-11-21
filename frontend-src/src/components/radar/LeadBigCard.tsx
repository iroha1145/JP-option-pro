/**
 * 雷达首要信号大卡（结构对齐美国站 breakouts/LeadBigCard）：
 * 状态徽章行 → 大号公司名加代码 → 近 30 日 K 线（突破价与失效价两条线）
 * → 现价 / 突破枢轴 / 失效位置三格加优先级圆环 → 生命周期步进条
 * → 主要分项评分（细线条）→ 折叠：其余分项与评分贡献 → 底部按钮。
 * 数据仍是收盘后日线扫描；盘中价只来自延迟报价叠加层，缺失时显示收盘价。
 */
import { useEffect, useMemo, useRef } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { stocksApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { useColorMode } from '@/hooks/useColorMode';
import { useAppearance } from '@/hooks/useAppearance';
import TickPrice from '@/components/shared/TickPrice';
import PriorityRing from '@/components/shared/PriorityRing';
import SoftBadge from '@/components/shared/SoftBadge';
import InfoHint from '@/components/shared/InfoHint';
import { SkeletonCard } from '@/components/shared/Skeleton';
import ReactECharts from '@/components/charts/ReactECharts';
import Icon from '@/components/icons';
import { RADAR_STATE_LABELS, SIGNAL_LABELS } from '@/components/domain';
import { CH, baseGrid, categoryAxis, glassTooltip, valueAxis } from '@/lib/chart';
import { RADAR_SCORE_HINTS, radarScoreHint } from '@/lib/indicatorHints';
import { riskBarClass, strengthBarClass } from '@/lib/strengthColor';
import { DUR_SECTION, DUR_UI, EASE_PAPER } from '@/lib/motion';
import { fmtDate, fmtDateShort, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';
import { cn } from '@/lib/utils';
import { t } from '@/i18n/core';
import type { IntradayOverlayRow, RadarEvent, RadarScores, StockBar } from '@/api/types';
import { radarStateChipClass } from './stateTone';

const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/* ---------------- 生命周期步进条 ---------------- */
/* 日本站状态与美国站一一对应（小写）：discovered/watching → triggered → confirmed → holding
   → retesting 一档（retest_held / reaccelerating / extended 同档，当前节点显示真实状态名）；
   failed / expired 为终止态。列表接口不带 transitions，终止态时不假设走过哪些节点。 */
const STEPS = ['discovered', 'triggered', 'confirmed', 'holding', 'retesting'] as const;

function stepIndex(state: string): number {
  switch (state) {
    case 'discovered':
    case 'watching':
      return 0;
    case 'triggered':
      return 1;
    case 'confirmed':
      return 2;
    case 'holding':
      return 3;
    default:
      return 4;
  }
}

type StepTone = 'past' | 'current' | 'future' | 'down' | 'ink-end';

function LifecycleStepper({ state }: { state: string }) {
  const terminal = state === 'failed' || state === 'expired' ? state : null;
  const idx = terminal ? -1 : stepIndex(state);
  const label = (key: string) => t(RADAR_STATE_LABELS[key] ?? key);

  const node = (text: string, tone: StepTone, key: string, order: number) => (
    <div key={key} className="flex min-w-[44px] flex-col items-center">
      <motion.span
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: DUR_UI, ease: EASE_PAPER, delay: order * 0.06 }}
        className={cn(
          'size-2.5 rounded-full',
          tone === 'current' && 'bg-brand-600 ring-4 ring-brand-100',
          tone === 'past' && 'bg-ink-300',
          tone === 'future' && 'border border-line-strong bg-card',
          tone === 'down' && 'bg-danger-600 ring-2 ring-danger-600/25',
          tone === 'ink-end' && 'bg-ink-400 ring-2 ring-ink-400/25',
        )}
        aria-hidden="true"
      />
      <span
        className={cn(
          'mt-1.5 whitespace-nowrap text-tag',
          tone === 'current' && 'font-medium text-brand-700',
          (tone === 'past' || tone === 'future') && 'text-ink-400',
          tone === 'down' && 'font-medium text-danger-700',
          tone === 'ink-end' && 'text-ink-500',
        )}
      >
        {text}
      </span>
    </div>
  );

  const items = STEPS.map((key, i) => ({
    el: node(
      i === idx ? label(state) : label(key),
      terminal ? 'future' : i === idx ? 'current' : i < idx ? 'past' : 'future',
      key,
      i,
    ),
    passed: !terminal && i < idx,
  }));
  if (terminal) {
    items.push({
      el: node(label(terminal), terminal === 'failed' ? 'down' : 'ink-end', terminal, STEPS.length),
      passed: false,
    });
  }

  return (
    <ol
      className="no-scrollbar -mt-1.5 flex items-start overflow-x-auto pt-1.5"
      aria-label={t('状态：{state}', { state: label(state) })}
    >
      {items.map((item, i) => (
        <li key={i} className="flex flex-1 items-start last:flex-none">
          {item.el}
          {i < items.length - 1 && (
            <span className="relative mx-1 mt-[5px] h-px min-w-3 flex-1 bg-line" aria-hidden="true">
              <motion.span
                className="absolute inset-y-0 left-0 bg-brand-600"
                initial={{ width: '0%' }}
                animate={{ width: item.passed ? '100%' : '0%' }}
                transition={{ duration: DUR_SECTION, ease: EASE_PAPER, delay: 0.24 + i * 0.06 }}
              />
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

/* ---------------- 分项评分（细线条） ---------------- */
type ScoreKey =
  | 'breakout_quality' | 'trend_quality' | 'base_quality' | 'breakout_confirmation'
  | 'relative_strength' | 'participation' | 'liquidity'
  | 'market_fit' | 'sector_fit' | 'chase_risk' | 'crowding_risk';

interface ScoreDef { key: ScoreKey; label: string; risk: boolean }

/* 默认展示四项（与美国站同数）：综合、确认、相对强度与追高风险；其余七项收进折叠。 */
const MAIN_SCORES: ScoreDef[] = [
  { key: 'breakout_quality', label: '综合质量', risk: false },
  { key: 'breakout_confirmation', label: '突破确认', risk: false },
  { key: 'relative_strength', label: '相对强度', risk: false },
  { key: 'chase_risk', label: '追高风险', risk: true },
];
const MORE_SCORES: ScoreDef[] = [
  { key: 'trend_quality', label: '趋势质量', risk: false },
  { key: 'base_quality', label: '基底质量', risk: false },
  { key: 'participation', label: '量能', risk: false },
  { key: 'liquidity', label: '流动性', risk: false },
  { key: 'market_fit', label: '市场契合', risk: false },
  { key: 'sector_fit', label: '行业契合', risk: false },
  { key: 'crowding_risk', label: '拥挤度', risk: true },
];

function scoreOf(scores: RadarScores | undefined, key: ScoreKey): number | null {
  if (!scores) return null;
  const raw = scores[key];
  if (fin(raw)) return raw;
  if (raw && typeof raw === 'object' && fin(raw.score)) return raw.score;
  return null;
}

function ScoreRows({ scores, defs, label }: { scores: RadarScores | undefined; defs: ScoreDef[]; label: string }) {
  return (
    <div className="grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-2" aria-label={label}>
      {defs.map((def, i) => {
        const value = scoreOf(scores, def.key);
        const hint = radarScoreHint(def.label);
        return (
          <div key={def.key} className="col-span-3 grid grid-cols-subgrid items-center gap-x-2.5">
            <span className="whitespace-nowrap text-caption text-ink-500">
              {t(def.label)}
              {hint && <InfoHint hint={hint} size={12} className="ml-0.5" />}
            </span>
            <div className="radar-bar-track h-[5px] overflow-hidden rounded-pill bg-line">
              {value !== null && (
                <motion.div
                  className={cn('h-full origin-left rounded-pill', def.risk ? riskBarClass(value) : strengthBarClass(value))}
                  initial={{ scaleX: 0 }}
                  whileInView={{ scaleX: 1 }}
                  viewport={{ once: true, amount: 0.4 }}
                  transition={{ duration: 0.7, ease: EASE_PAPER, delay: 0.1 + i * 0.06 }}
                  style={{ width: `${Math.max(3, Math.min(100, value))}%` }}
                />
              )}
            </div>
            <span className="text-right text-caption text-ink-600 tnum">{value !== null ? value.toFixed(1) : '—'}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------- 评分贡献（只用后端 alert_priority.contributions，没有就不画） ---------------- */
const CONTRIB_DEFS = [
  { key: 'breakout_quality', label: '综合质量', cls: 'bg-brand-600' },
  { key: 'relative_strength', label: '相对强度', cls: 'bg-brand-400' },
  { key: 'participation', label: '量能', cls: 'bg-ai-600' },
  { key: 'market_fit', label: '市场契合', cls: 'bg-ink-500' },
  { key: 'sector_fit', label: '行业契合', cls: 'bg-ink-300' },
  { key: 'data_confidence', label: '数据可信度', cls: 'bg-warn-600' },
] as const;

function ContributionBar({ scores }: { scores: RadarScores | undefined }) {
  const contributions: Record<string, unknown> | undefined = scores?.alert_priority?.contributions;
  const parts = useMemo(() => {
    if (!contributions || typeof contributions !== 'object') return null;
    const raws = CONTRIB_DEFS.flatMap((def) => {
      const value = contributions[def.key];
      return fin(value) && value > 0 ? [{ def, value }] : [];
    });
    if (raws.length === 0) return null;
    const total = raws.reduce((sum, part) => sum + part.value, 0) || 1;
    return raws.map((part) => ({ ...part, pct: (part.value / total) * 100 }));
  }, [contributions]);
  const penalty = contributions?.penalty;

  if (parts === null) {
    return <p className="text-tag text-ink-400">{t('评分构成不可用（数据不足）')}</p>;
  }
  return (
    <div aria-label={t('评分构成')}>
      <div className="radar-bar-track flex h-[5px] overflow-hidden rounded-pill bg-line">
        {parts.map((part) => (
          <div key={part.def.key} className={cn('h-full', part.def.cls)} style={{ width: `${part.pct}%` }} />
        ))}
      </div>
      <ul className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {parts.map((part) => (
          <li key={part.def.key} className="inline-flex items-center gap-1.5">
            <span className={cn('inline-block size-2 rounded-[2px]', part.def.cls)} aria-hidden="true" />
            <span className="text-tag text-ink-500">{t(part.def.label)}</span>
            <span className="text-tag text-ink-600 tnum">{part.value.toFixed(1)}</span>
          </li>
        ))}
        {fin(penalty) && penalty < 0 && (
          <li className="inline-flex items-center gap-1.5">
            <span className="text-tag text-ink-500">{t('扣分')}</span>
            <span className="text-tag text-ink-600 tnum">{penalty.toFixed(1)}</span>
          </li>
        )}
      </ul>
    </div>
  );
}

/* ---------------- K 线迷你图 ---------------- */
function LeadChart({ bars, event }: { bars: StockBar[]; event: RadarEvent }) {
  const colorMode = useColorMode();
  const appearance = useAppearance();
  const invalidation = event.structure?.base?.invalidation_price ?? null;
  const option = useMemo(() => {
    void colorMode;
    void appearance;
    const dates = bars.map((bar) => bar.trade_date.slice(5));
    const candles = bars.map((bar) => [
      bar.adj_open ?? bar.open,
      bar.adj_close ?? bar.close,
      bar.adj_low ?? bar.low,
      bar.adj_high ?? bar.high,
    ]);
    const levels = [event.pivot_price, invalidation].filter(fin);
    /* 日股的枢轴与失效位常常只差几十円：两条标签分放线的两端（枢轴在线上靠右、失效在线下靠左），不叠在一起。 */
    const levelLine = (
      price: number,
      name: string,
      color: string,
      type: 'solid' | number[],
      position: 'insideEndTop' | 'insideStartBottom',
    ) => ({
      yAxis: price,
      lineStyle: { color, width: 1, type },
      label: {
        formatter: `${name} ${fmtPrice(price)}`,
        color,
        fontSize: 12,
        position,
        backgroundColor: CH.tooltipBg,
        padding: [1, 4],
        borderRadius: 3,
      },
    });
    const base = event.structure?.base;
    return {
      grid: baseGrid({ top: 10, bottom: 4, left: 6, right: 6, containLabel: true }),
      tooltip: glassTooltip({ trigger: 'axis' }),
      xAxis: categoryAxis(dates),
      yAxis: valueAxis({
        scale: true,
        position: 'right',
        /* 参考线不计入自动刻度：价位落在 30 根 K 线之外时把轴撑开，两端不标数。 */
        ...(levels.length > 0 && {
          min: (extent: { min: number }) => Math.min(extent.min, ...levels),
          max: (extent: { max: number }) => Math.max(extent.max, ...levels),
        }),
      }),
      series: [
        {
          type: 'candlestick' as const,
          data: candles,
          barMaxWidth: 10,
          itemStyle: {
            color: CH.up600, color0: CH.down600,
            borderColor: CH.up600, borderColor0: CH.down600,
          },
          markLine: {
            silent: true,
            symbol: 'none',
            animation: false,
            data: [
              ...(fin(event.pivot_price) ? [levelLine(event.pivot_price, t('枢轴价'), CH.brand600, 'solid', 'insideEndTop')] : []),
              ...(fin(invalidation) ? [levelLine(invalidation, t('失效位'), CH.ink400, [4, 3], 'insideStartBottom')] : []),
            ],
          },
          ...(base?.resistance_high != null && base?.resistance_low != null
            ? {
                markArea: {
                  silent: true,
                  itemStyle: { color: CH.brand400, opacity: 0.08 },
                  data: [
                    [{ yAxis: base.resistance_low }, { yAxis: base.resistance_high }] as [
                      { yAxis: number },
                      { yAxis: number },
                    ],
                  ],
                },
              }
            : {}),
        },
      ],
    };
  }, [appearance, bars, colorMode, event, invalidation]);
  return <ReactECharts className="h-full w-full" option={option} ariaLabel={`${event.display_code} lead chart`} />;
}

/* ================= 大卡主体 ================= */
export default function LeadBigCard({
  event,
  siblings,
  live,
  flash,
  locate = false,
  onPromote,
}: {
  event: RadarEvent;
  /** 同一只股票的其他信号（不含本条），以徽章列出，点击切换为首要信号。 */
  siblings: RadarEvent[];
  live?: IntradayOverlayRow;
  flash?: 'up' | 'down';
  locate?: boolean;
  onPromote: (eventId: string) => void;
}) {
  const chart = usePolling(
    () => stocksApi.chart(event.canonical_code, '6m'),
    null,
    [event.canonical_code],
    { identity: event.canonical_code },
  );
  const structure = event.structure ?? null;
  const invalidation = structure?.base?.invalidation_price ?? null;
  const current = live?.live_price ?? (event.snapshot.close as number | null);
  const turnover = event.snapshot.turnover_today as number | null;
  /* 首要卡上方还有状态带与筛选面板：被选为首要信号时把卡片本身滚进视口，闪烁才看得见。 */
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (locate) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [locate]);

  return (
    <motion.article
      ref={ref}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: DUR_SECTION, ease: EASE_PAPER }}
      aria-label={t('{code} 首要信号大卡', { code: event.display_code })}
      className={cn('radar-lead-card card-surface scroll-mt-24 p-5', locate && 'bk-locate')}
    >
      {/* 顶行：状态徽章 + 形态 + 行业市场 + 发现日 · 右侧首要信号 */}
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <span className={cn('radar-chip', radarStateChipClass(event.state))}>
            {t(RADAR_STATE_LABELS[event.state] ?? event.state)}
          </span>
          <span className="radar-chip radar-chip-brand">{t(SIGNAL_LABELS[event.signal_type] ?? event.signal_type)}</span>
          {live?.above_pivot && (
            <span className="radar-chip radar-chip-neutral">
              <span className="size-1.5 rounded-full bg-warn-600" aria-hidden="true" />
              {t('盘中站上枢轴')}
            </span>
          )}
          <span className="tnum text-micro text-ink-400">{t('发现日')} {fmtDate(event.discovered_date)}</span>
          <span className="hidden min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-500 lg:inline-flex">
            {event.sector33_name && <SoftBadge tone="neutral">{event.sector33_name}</SoftBadge>}
            {event.market_name && <span>{event.market_name}</span>}
            <span className="tnum">{t('成交额')} {fmtYenCompact(turnover)}</span>
          </span>
        </div>
        <span className="radar-chip radar-chip-brand shrink-0">
          <Icon name="radar" size={12} />
          {t('首要信号')}
        </span>
      </div>

      {/* 标题区 */}
      <div className="mt-2.5">
        <h3 className="font-display text-display-m text-ink-900">
          {event.name_ja ?? '—'}{' '}
          <Link
            to={`/stock/${event.display_code}`}
            className="text-brand-600 underline-offset-4 transition-colors duration-fast hover:text-brand-700 hover:underline"
          >
            {event.display_code}
          </Link>
        </h3>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-ink-500 lg:hidden">
          {event.sector33_name && <SoftBadge tone="neutral">{event.sector33_name}</SoftBadge>}
          {event.market_name && <span>{event.market_name}</span>}
          <span className="tnum">{t('成交额')} {fmtYenCompact(turnover)}</span>
        </p>
        {structure && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {structure.structure_label && <SoftBadge tone="brand">{t(structure.structure_label)}</SoftBadge>}
            {structure.setup_label && <SoftBadge tone="ai">{t(structure.setup_label)}</SoftBadge>}
            {(structure.pattern_labels ?? []).map((label) => (
              <SoftBadge key={label}>{t(label)}</SoftBadge>
            ))}
            {structure.spring && <SoftBadge tone="up">{t('Spring 假跌破回收')}</SoftBadge>}
            {structure.upthrust && <SoftBadge tone="down">{t('Upthrust 假突破')}</SoftBadge>}
          </div>
        )}
        {siblings.length > 0 && (
          <SiblingSignals siblings={siblings} onPromote={onPromote} className="mt-2" />
        )}
      </div>

      {/* K 线迷你图 */}
      <div className="mt-3">
        <p className="mb-1 text-micro text-ink-400">{t('日线 · 最多 30 个交易日')}</p>
        {chart.loading && !chart.data ? (
          <SkeletonCard className="h-[120px] sm:h-[150px]" />
        ) : chart.data && chart.data.bars.length > 1 ? (
          <div className="radar-mini-chart relative h-[120px] overflow-hidden rounded-md bg-card-warm sm:h-[150px]">
            <LeadChart bars={chart.data.bars.slice(-30)} event={event} />
          </div>
        ) : (
          <div className="radar-mini-chart relative flex h-[120px] items-center justify-center overflow-hidden rounded-md bg-card-warm sm:h-[150px]">
            <img src="/empty-chart.svg" alt="" className="h-12 w-auto opacity-90" loading="lazy" />
          </div>
        )}
      </div>

      {/* 三价位 + 优先级环 */}
      <div className="mt-3 flex flex-col gap-2.5 sm:flex-row sm:items-stretch">
        <div className="grid flex-1 grid-cols-1 gap-2.5 sm:grid-cols-3">
          <div className="radar-value-cell px-3 py-2.5">
            <p className="text-micro text-ink-400">{live ? t('盘中价') : t('当前价')}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
              <TickPrice flash={flash} className="min-w-0 text-data-l text-ink-900">
                {fmtPrice(current)}
              </TickPrice>
              {live && fin(live.pivot_distance_pct) && (
                <span className={cn('tnum text-tag', live.pivot_distance_pct >= 0 ? 'text-up-700' : 'text-down-700')}>
                  {t('距枢轴')} {fmtPct(live.pivot_distance_pct, 1)}
                </span>
              )}
            </p>
          </div>
          <div className="radar-value-cell px-3 py-2.5">
            <p className="flex items-center gap-1 text-micro text-ink-400">
              <span className="radar-reference-glyph radar-reference-trigger" aria-hidden="true" />
              {t('突破枢轴')}
            </p>
            <p className="mt-0.5 text-data-l text-ink-900 tnum">{fmtPrice(event.pivot_price)}</p>
          </div>
          <div className="radar-value-cell px-3 py-2.5">
            <p className="flex items-center gap-1 text-micro text-ink-400">
              <span className="radar-reference-glyph radar-reference-invalid" aria-hidden="true" />
              {t('失效位置')}
            </p>
            <p className="mt-0.5 text-data-l text-ink-900 tnum">{fmtPrice(invalidation)}</p>
          </div>
        </div>
        <div className="radar-value-cell radar-priority-cell flex flex-col items-center justify-center gap-1.5 px-3 py-1.5">
          <PriorityRing
            score={event.alert_priority}
            label={t('告警优先级')}
            hint={RADAR_SCORE_HINTS.优先级}
            emptyLabel={t('告警优先级数据不足')}
          />
        </div>
      </div>

      {/* 生命周期步进条 */}
      <div className="mt-4 border-t border-line pt-3">
        <LifecycleStepper state={event.state} />
      </div>

      {/* 主要分项评分 + 折叠的其余分项与评分贡献 */}
      <div className="mt-4 border-t border-line pt-3">
        <section aria-label={t('分项评分')}>
          <p className="eyebrow mb-2">{t('分项评分')}</p>
          <ScoreRows scores={event.scores} defs={MAIN_SCORES} label={t('分项评分')} />
        </section>
        <details className="radar-disclosure mt-3">
          <summary>
            <span>{t('更多分项与评分贡献')}</span>
            <Icon name="chevron-down" size={14} className="radar-disclosure-arrow" />
          </summary>
          <div className="space-y-4 pb-3 pt-1">
            <ScoreRows scores={event.scores} defs={MORE_SCORES} label={t('更多分项')} />
            <div>
              <p className="mb-1.5 text-micro text-ink-500">{t('评分贡献')}</p>
              <ContributionBar scores={event.scores} />
            </div>
          </div>
        </details>
      </div>

      {/* 操作按钮 */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t border-line pt-3">
        <span className="tnum text-micro text-ink-400">
          {t('数据截至')} {fmtDate(event.last_scanned_date)}
        </span>
        <Link to={`/stock/${event.display_code}`} className="btn-primary radar-btn-sm ml-auto">
          {t('打开研究页')}
          <Icon name="arrow-up-right" size={13} />
        </Link>
      </div>
    </motion.article>
  );
}

/* ---------------- 同股其他信号徽章（首要卡与小卡共用） ---------------- */
export function SiblingSignals({
  siblings,
  onPromote,
  limit = 3,
  className,
}: {
  siblings: RadarEvent[];
  onPromote: (eventId: string) => void;
  limit?: number;
  className?: string;
}) {
  const shown = siblings.slice(0, limit);
  const hidden = siblings.length - shown.length;
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <span className="text-micro text-ink-500">{t('另有 {n} 条信号', { n: siblings.length })}</span>
      {shown.map((sibling) => (
        <button
          key={sibling.event_id}
          type="button"
          onClick={() => onPromote(sibling.event_id)}
          aria-label={t('将 {code} 的 {signal}（{date}）设为首要信号', {
            code: sibling.display_code,
            signal: t(SIGNAL_LABELS[sibling.signal_type] ?? sibling.signal_type),
            date: fmtDate(sibling.discovered_date),
          })}
          className="radar-chip radar-chip-neutral radar-sibling-chip mobile-control-target focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
        >
          {t(SIGNAL_LABELS[sibling.signal_type] ?? sibling.signal_type)}
          <span className="tnum text-ink-400">{fmtDateShort(sibling.discovered_date)}</span>
        </button>
      ))}
      {hidden > 0 && <span className="tnum text-micro text-ink-400">+{hidden}</span>}
    </div>
  );
}
