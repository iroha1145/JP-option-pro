/**
 * B3 右侧栏 — 对标美版 SideCards + MarketRegimeCard。
 * 1. MarketRegimeCard：日股市场形态 6 维（TOPIX趋势/动量/广度/量能/风险偏好/强弱价差）
 * 2. TierHistogram：本次命中（实心）vs 已评分候选池（斜纹参照），点击联动分档
 * 3. MethodCard：六族权重 + 排序合成说明（可折叠）
 */
import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { MarketRegime, StrengthProfilesMeta, TierDistribution } from '@/api/types';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import InfoHint from '@/components/shared/InfoHint';
import SourceNote from '@/components/shared/SourceNote';
import { STRENGTH_HINTS } from '@/lib/indicatorHints';
import { FAMILY_META, type Tier, type TierFilter } from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];
const SPRING_POP = { type: 'spring', stiffness: 520, damping: 32 } as const;
const TIERS: Tier[] = ['S', 'A', 'B', 'C', 'D'];

/* ---------------- 市场形态 6 维 ---------------- */

const REGIME_DIMS: { key: keyof MarketRegime['dims']; label: string; en: string; hint: string }[] = [
  { key: 'index_trend', label: t('指数趋势'), en: 'INDEX TREND', hint: t('TOPIX 相对 25/75/200 日均线的位置与斜率。') },
  { key: 'momentum', label: t('市场动量'), en: 'MOMENTUM', hint: t('TOPIX 近 20 日收益的强弱。') },
  { key: 'breadth', label: t('市场广度'), en: 'BREADTH', hint: t('全市场收于 200 日线上方的个股占比。') },
  { key: 'volume', label: t('量能配合'), en: 'VOLUME', hint: t('成交额高于自身 20 日均额的个股占比。') },
  { key: 'risk_appetite', label: t('风险偏好'), en: 'RISK APPETITE', hint: t('全市场 20 日收益中位数的强弱。') },
  { key: 'risk_on_spread', label: t('强弱价差'), en: 'RISK-ON SPREAD', hint: t('グロース与プライム市场 20 日收益中位数之差。') },
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
          <span className="font-mono text-data-m text-ink-900 tnum">{regime.score}</span>
        ) : (
          <span className="font-mono text-micro text-ink-300 tnum">{t('6 维')}</span>
        )}
      </div>
      {(regime.label || regime.spread_label) && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {regime.label && (
            <span className="rounded-xs bg-brand-50 px-1.5 py-px text-micro font-medium text-brand-700">{regime.label}</span>
          )}
          {regime.spread_label && (
            <span className="rounded-xs border border-line bg-card-warm px-1.5 py-px text-micro text-ink-500">{regime.spread_label}</span>
          )}
        </p>
      )}
      <div className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-3">
        {REGIME_DIMS.map((dim, index) => {
          const value = regime.dims[dim.key];
          return (
            <div key={dim.key} className="group relative col-span-3 grid grid-cols-subgrid items-center gap-x-3">
              <span className="whitespace-nowrap text-caption text-ink-500">{dim.label}</span>
              <span className="relative h-1.5 flex-1 overflow-hidden rounded-pill bg-line" role="presentation">
                {value !== null && (
                  <motion.span
                    className="block h-full origin-left rounded-pill bg-brand-500"
                    initial={{ scaleX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    viewport={{ once: true, amount: 0.4 }}
                    transition={{ duration: 0.7, ease: EASE_PAPER, delay: index * 0.045 }}
                    style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                  />
                )}
              </span>
              <span className="text-right font-mono text-caption text-ink-800 tnum">
                {value !== null ? Math.round(value) : '—'}
              </span>
              <div className="glass pointer-events-none absolute -top-2 left-16 z-20 hidden w-56 -translate-y-full rounded-md border border-line p-3 shadow-sh-2 group-hover:block">
                <p className="flex items-baseline justify-between">
                  <span className="text-caption font-semibold text-ink-800">{dim.label}</span>
                  <span className="font-mono text-micro text-ink-400">{dim.en}</span>
                </p>
                <p className="mt-1.5 text-micro leading-[16px] text-ink-500">{dim.hint}</p>
                <p className="mt-1.5 font-mono text-caption text-brand-600 tnum">
                  {value !== null ? `${Math.round(value * 10) / 10} / 100` : t('暂无数据')}
                </p>
              </div>
            </div>
          );
        })}
      </div>
      {regime.warnings.length > 0 && (
        <ul className="mt-3.5 space-y-1 border-t border-line pt-3">
          {regime.warnings.map((warning, index) => (
            <li key={index} className="flex items-start gap-1.5 text-micro leading-[16px] text-warn-600">
              <span className="mt-px shrink-0" aria-hidden="true">⚠</span>
              {warning}
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
        {TIERS.map((tier, index) => {
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
              title={selectable ? t('只看 {tier} 档', { tier }) : t('D 档（<60）计入「全部」')}
              className={cn(
                'group relative flex h-full flex-1 flex-col items-center justify-end gap-1 rounded-t-[4px] border-b-2 pb-0.5 transition-colors duration-fast',
                active ? 'border-brand-600 bg-brand-50' : 'border-transparent hover:bg-paper-2',
                !selectable && 'cursor-default opacity-70',
              )}
            >
              <span className="font-mono text-[10px] leading-none text-ink-400 tnum">{hit}</span>
              {ref !== null && (
                <motion.span
                  className="w-full max-w-[26px] rounded-t-[3px] border border-ink-300/60"
                  initial={{ scaleY: 0 }}
                  whileInView={{ scaleY: 1 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.7, ease: EASE_PAPER, delay: index * 0.05 }}
                  style={{
                    height: `${Math.max(4, (refN / maxRef) * 72)}px`,
                    transformOrigin: 'bottom',
                    backgroundImage: 'repeating-linear-gradient(45deg, rgba(138,148,176,.45) 0 1.2px, transparent 1.2px 4px)',
                  }}
                  aria-hidden="true"
                />
              )}
              <motion.span
                className={cn('-mt-1 w-full max-w-[26px] rounded-t-[3px]', active ? 'bg-brand-600' : 'bg-brand-600/85')}
                initial={{ scaleY: 0 }}
                whileInView={{ scaleY: 1 }}
                viewport={{ once: true, amount: 0.3 }}
                transition={{ duration: 0.7, ease: EASE_PAPER, delay: 0.08 + index * 0.05 }}
                style={{ height: `${Math.max(hit > 0 ? 5 : 2, (hit / maxHit) * 56)}px`, transformOrigin: 'bottom' }}
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
      <p className="mt-3.5 text-micro text-ink-400">
        {ref !== null ? t('实心=本次命中 · 斜纹=已评分候选池') : t('仅统计本次筛选命中的标的')}
      </p>
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
  const [open, setOpen] = useState(true);
  const profile = meta?.profiles.find((item) => item.id === profileId) ?? null;
  return (
    <div className="card-surface p-5">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center justify-between">
        <span className="eyebrow">
          {t('评分方法 ·')} {profile ? profile.name : loading ? t('读取中') : error ? t('档位未知') : t('默认权重')}
        </span>
        <Icon name="chevron-down" size={14} className={cn('text-ink-400 transition-transform duration-200', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.26, ease: EASE_PAPER }}
            className="overflow-hidden"
          >
            {!meta && loading ? (
              <div className="mt-4 space-y-2.5" aria-hidden="true">
                {FAMILY_META.map(({ key }) => (
                  <span key={key} className="skeleton-shimmer block h-3 w-full rounded-xs" />
                ))}
              </div>
            ) : !meta && error ? (
              <div className="mt-4">
                <p className="text-caption leading-[18px] text-ink-500">{t('评分档位读取失败，无法显示当前权重。')}</p>
                {onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="mt-2 flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-caption text-ink-600 transition-colors hover:border-brand-400 hover:text-brand-600"
                  >
                    <Icon name="refresh" size={12} />
                    {t('重试')}
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="mt-4 grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-2.5">
                  {FAMILY_META.map(({ key, label }, index) => {
                    const weight = meta?.family_weights[key] ?? null;
                    return (
                      <div key={key} className="col-span-3 grid grid-cols-subgrid items-center gap-x-2.5">
                        <span className="text-caption text-ink-500">{label}</span>
                        <span className="h-1.5 overflow-hidden rounded-pill bg-line" role="presentation">
                          {weight !== null && (
                            <motion.span
                              className="block h-full origin-left rounded-pill bg-brand-500"
                              initial={{ scaleX: 0 }}
                              whileInView={{ scaleX: 1 }}
                              viewport={{ once: true, amount: 0.4 }}
                              transition={{ duration: 0.7, ease: EASE_PAPER, delay: index * 0.05 }}
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
                    ? profile.description
                    : t('内在强度为六族加权合成（0–100，缺失重新配权）。')}
                </p>
                <p className="mt-1.5 text-micro leading-[16px] text-ink-400">
                  {t('最终排序分 = 内在 78% + 市场形态 8% + 偏好适配 14%（置信度加权）。')}
                </p>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
