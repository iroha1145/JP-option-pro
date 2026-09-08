/**
 * B3 右侧栏 — 对标美版 SideCards + MarketRegimeCard。
 * 1. MarketRegimeCard：日股市场形态 6 维（TOPIX趋势/动量/广度/量能/风险偏好/强弱价差）
 * 2. TierHistogram：本次命中（实心）vs 已评分候选池（斜纹参照），点击联动分档
 * 3. MethodCard：六族权重 + 排序合成说明（可折叠）
 */
import { useId, useState } from 'react';
import { motion } from 'framer-motion';
import type { MarketRegime, StrengthProfilesMeta, TierDistribution } from '@/api/types';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import HatchLegend from '@/components/shared/HatchLegend';
import InfoHint from '@/components/shared/InfoHint';
import PointerTooltip from '@/components/shared/PointerTooltip';
import SourceNote from '@/components/shared/SourceNote';
import SoftBadge from '@/components/shared/SoftBadge';
import EmptyState from '@/components/shared/EmptyState';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import { REGIME_DIM_HINTS, STRENGTH_HINTS } from '@/lib/indicatorHints';
import { FAMILY_META, type Tier, type TierFilter } from './types';
import { t } from '@/i18n/core';

const SPRING_POP = { type: 'spring', stiffness: 520, damping: 32 } as const;
const TIERS: Tier[] = ['S', 'A', 'B', 'C', 'D'];

/* ---------------- 市场形态 6 维 ---------------- */

const REGIME_DIMS: { key: keyof MarketRegime['dims']; label: string; en: string }[] = [
  { key: 'index_trend', label: t('指数趋势'), en: 'INDEX TREND' },
  { key: 'momentum', label: t('市场动量'), en: 'MOMENTUM' },
  { key: 'breadth', label: t('市场广度'), en: 'BREADTH' },
  { key: 'volume', label: t('量能配合'), en: 'VOLUME' },
  { key: 'risk_appetite', label: t('风险偏好'), en: 'RISK APPETITE' },
  { key: 'risk_on_spread', label: t('强弱价差'), en: 'RISK-ON SPREAD' },
];

export function MarketRegimeCard({ regime }: { regime: MarketRegime }) {
  return (
    <div className="card-surface p-5">
      <div className="flex items-baseline justify-between">
        <p className="eyebrow">
          {t('市场形态 · MARKET REGIME')}
          <InfoHint hint={STRENGTH_HINTS.marketRegime} side="bottom" size={12} className="ml-1" />
        </p>
        {regime.score !== null ? (
          <span className="metric-value text-data-m text-ink-900 tnum">{regime.score}</span>
        ) : (
          <span className="font-mono text-micro text-ink-300 tnum">{t('6 维')}</span>
        )}
      </div>
      {(regime.label || regime.spread_label) && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {regime.label && (
            <SoftBadge tone="brand">{t(regime.label)}</SoftBadge>
          )}
          {regime.spread_label && (
            <SoftBadge>{t(regime.spread_label)}</SoftBadge>
          )}
        </p>
      )}
      <div className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-3">
        {REGIME_DIMS.map((dim) => {
          const value = regime.dims[dim.key];
          const hint = REGIME_DIM_HINTS[dim.key];
          return (
            <div key={dim.key} className="col-span-3 grid grid-cols-subgrid items-center gap-x-3">
              <span className="whitespace-nowrap text-caption text-ink-500">
                {dim.label}
                {hint && <InfoHint hint={hint} side="bottom" size={11} className="ml-0.5" />}
              </span>
              <PointerTooltip
                label={dim.label}
                side="top"
                width={224}
                className="min-w-0 w-full"
                contentClassName="p-3"
                content={
                  <>
                    <span className="flex items-baseline justify-between">
                      <span className="text-caption font-semibold text-ink-800">{dim.label}</span>
                      <span className="font-mono text-micro text-ink-400">{dim.en}</span>
                    </span>
                    {hint && <span className="mt-1.5 block text-micro leading-[16px] text-ink-500">{hint.body}</span>}
                    <span className="mt-1.5 block font-mono text-caption text-brand-600 tnum">
                      {value !== null ? `${Math.round(value * 10) / 10} / 100` : t('暂无数据')}
                    </span>
                  </>
                }
              >
                <span className="strength-track relative h-1.5 w-full overflow-hidden rounded-pill bg-paper" role="presentation">
                  {value !== null && (
                    <span
                      className="block h-full origin-left rounded-pill bg-brand-500"
                      style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                    />
                  )}
                </span>
              </PointerTooltip>
              <span className="metric-value text-right text-caption text-ink-800 tnum">
                {value !== null ? Math.round(value) : '—'}
              </span>
            </div>
          );
        })}
      </div>
      {regime.warnings.length > 0 && (
        <ul className="mt-3.5 space-y-1 border-t border-line pt-3">
          {regime.warnings.map((warning, index) => (
            <li key={index}>
              <SoftBadge tone="warn" className="items-start whitespace-normal">
                <span className="mt-px shrink-0" aria-hidden="true">⚠</span>
                {t(warning)}
              </SoftBadge>
            </li>
          ))}
        </ul>
      )}
      <SourceNote className="mt-4" text={t('由 TOPIX 与全市场日线断面推导 · 收盘后更新')} />
    </div>
  );
}

/* ---------------- 强度剖面（分档命中直方图） ---------------- */

export function TierHistogram({
  hits,
  distribution,
  activeTier,
  onSelect,
}: {
  /** 当前结果各档命中数（客户端统计） */
  hits: Record<Tier, number> | null;
  /** 已评分候选池分布（服务端 tier_distribution） */
  distribution: TierDistribution | null;
  activeTier: TierFilter;
  onSelect: (tier: TierFilter) => void;
}) {
  const ref: Record<Tier, number> | null = distribution
    ? { S: distribution.S, A: distribution.A, B: distribution.B, C: distribution.C, D: distribution.D }
    : null;
  const maxHit = Math.max(1, ...TIERS.map((tier) => hits?.[tier] ?? 0));
  const maxRef = Math.max(1, ...TIERS.map((tier) => ref?.[tier] ?? 0));
  return (
    <div className="card-surface p-5">
      <p className="eyebrow">{t('强度剖面 · 分档命中')}</p>
      <div className="mt-4 flex h-28 items-end gap-2.5">
        {TIERS.map((tier) => {
          const hit = hits?.[tier] ?? 0;
          const refN = ref?.[tier] ?? 0;
          const selectable = tier !== 'D';
          const active = activeTier === tier;
          return (
            <motion.button
              key={tier}
              type="button"
              onClick={selectable ? () => onSelect(active ? 'all' : tier) : undefined}
              disabled={!selectable}
              animate={{ scale: active ? 1.04 : 1 }}
              transition={SPRING_POP}
              aria-pressed={active}
              aria-label={selectable ? t('只看 {tier} 档', { tier }) : t('D 档（<60）计入「全部」')}
              className={cn(
                'group relative flex h-full flex-1 flex-col items-center justify-end gap-1 rounded-t-[4px] border-b-2 pb-0.5 transition-colors duration-fast',
                active ? 'border-brand-400 bg-paper-2' : 'border-transparent hover:bg-paper-2',
                !selectable && 'cursor-default opacity-70',
              )}
            >
              <span className="metric-value text-[11px] leading-none text-ink-500 tnum">{hit}</span>
              {ref !== null && (
                <span
                  className="w-full max-w-[26px] rounded-t-[3px] border border-ink-300/30"
                  style={{
                    height: `${Math.max(4, (refN / maxRef) * 72)}px`,
                    backgroundImage: 'repeating-linear-gradient(45deg, rgba(138,148,176,.45) 0 1.2px, transparent 1.2px 4px)',
                  }}
                  aria-hidden="true"
                />
              )}
              <span
                className={cn('-mt-1 w-full max-w-[26px] rounded-t-[3px]', active ? 'bg-brand-600' : 'bg-brand-600/85')}
                style={{ height: `${Math.max(hit > 0 ? 5 : 2, (hit / maxHit) * 56)}px` }}
                aria-hidden="true"
              />
            </motion.button>
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-2.5">
        {TIERS.map((tier) => (
          <span key={tier} className={cn('flex-1 text-center font-mono text-[10px] tnum', activeTier === tier ? 'text-brand-600' : 'text-ink-400')}>
            {tier}
          </span>
        ))}
      </div>
      {ref !== null ? (
        <HatchLegend className="mt-3.5" actual={t('本次命中')} estimate={t('全市场参照')} />
      ) : (
        <p className="mt-3.5 text-micro text-ink-400">{t('仅统计本次筛选命中的标的')}</p>
      )}
    </div>
  );
}

/* ---------------- 评分方法卡（可折叠） ---------------- */

export function MethodCard({
  meta,
  profileId,
  loading,
  error,
  onRetry,
}: {
  meta: StrengthProfilesMeta | null;
  profileId: string;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const profile = meta?.profiles.find((item) => item.id === profileId) ?? null;
  return (
    <div className="card-surface t-acc p-5" data-open={open ? 'true' : 'false'}>
      <button
        type="button"
        className="t-acc-head flex w-full items-center justify-between gap-3 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
      >
        <span className="eyebrow">
          {t('评分方法 ·')} {profile ? profile.name : loading ? t('读取中') : error ? t('档位未知') : t('默认权重')}
        </span>
        <span className="t-acc-chevron text-ink-400">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d="M4 6.5L8 10.5L12 6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </span>
      </button>
      <div id={panelId} className="t-acc-panel" aria-hidden={!open} inert={!open}>
        <div className="t-acc-panel-inner">
          {!meta && loading ? (
            <div className="t-skel mt-4 space-y-2.5" data-state="loading" aria-hidden="true">
              <div className="t-skel-skeleton is-pulsing space-y-2.5">
                {FAMILY_META.map(({ key }) => (
                  <SkeletonBlock key={key} className="h-3 w-full rounded-xs" />
                ))}
              </div>
              <div className="t-skel-content" />
            </div>
          ) : !meta && error ? (
            <EmptyState
              size="compact"
              image="/empty-chart.svg"
              title={t('评分档位读取失败，无法显示当前权重。')}
              action={
                onRetry ? (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="mt-2 flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-caption text-ink-600 shadow-btn transition-colors hover:border-brand-400 hover:text-brand-600"
                  >
                    <Icon name="refresh" size={12} />
                    {t('重试')}
                  </button>
                ) : undefined
              }
            />
          ) : (
            <>
              <div className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-2.5">
                {FAMILY_META.map(({ key, label }) => {
                  const weight = meta?.family_weights[key] ?? null;
                  return (
                    <div key={key} className="col-span-3 grid grid-cols-subgrid items-center gap-x-2.5">
                      <span className="text-caption text-ink-500">{label}</span>
                      <span className="strength-track h-1.5 overflow-hidden rounded-pill bg-paper" role="presentation">
                        {weight !== null && (
                          <span
                            className="block h-full origin-left rounded-pill bg-brand-500"
                            style={{ width: `${weight * 100 * 4}%` }}
                          />
                        )}
                      </span>
                      <span className="text-right font-mono text-caption text-ink-800 tnum">
                        {weight !== null ? `${Math.round(weight * 100)}%` : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
              <p className="mt-3 text-caption leading-[18px] text-ink-500">
                {profile?.description
                  ? t(profile.description)
                  : t('内在强度为六族加权合成（0–100，缺失重新配权）。')}
              </p>
              <p className="mt-1.5 text-micro leading-[16px] text-ink-400">
                {t('最终排序分 = 内在 78% + 市场形态 8% + 偏好适配 14%（置信度加权）。')}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
