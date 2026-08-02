/**
 * B1 筛选工作台 — 对标美版 FilterWorkbench。
 * 行1 分档 Segmented（数量徽标=已评分候选池）+ 预设策略 chips
 * 行2 周期 / 偏好 / Top N
 * 行3 33业种多选（折叠 +N）· 价格区间（円）· 成交额下限 · 开始扫描
 * 与美版不同：全部条件都在服务端对完整已评分池生效，无「仅前N名内筛选」问题。
 */
import { useState } from 'react';
import { motion } from 'framer-motion';
import type { StrengthProfilesMeta } from '@/api/types';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import Segmented from '@/components/shared/Segmented';
import {
  PROFILE_CN,
  TIMEFRAME_CN,
  TOPN_OPTIONS,
  TURNOVER_OPTIONS,
  type ProfilePref,
  type ScanFilters,
  type TierFilter,
  type Timeframe,
} from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];
const SPRING_POP = { type: 'spring', stiffness: 520, damping: 32 } as const;
const SECTOR_COLLAPSE_AT = 8;

const TIER_OPTIONS: { value: TierFilter; label: string }[] = [
  { value: 'all', label: t('全部') },
  { value: 'S', label: 'S' },
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'C', label: 'C' },
];

function TierSegmented({
  value,
  counts,
  onChange,
}: {
  value: TierFilter;
  counts: Record<TierFilter, number> | null;
  onChange: (v: TierFilter) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label={t('强度分档 · 计数基于已评分候选池')}
      title={t('分档计数基于已评分候选池')}
      className="no-scrollbar inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-line bg-card-warm p-0.5"
    >
      {TIER_OPTIONS.map((option) => {
        const active = value === option.value;
        return (
          <button
            key={option.value}
            role="tab"
            aria-selected={active}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              'relative shrink-0 whitespace-nowrap rounded-[6px] px-2.5 py-1 text-caption font-medium transition-colors',
              active ? 'text-ink-800' : 'text-ink-400 hover:text-ink-600',
            )}
          >
            {active && (
              <motion.span
                layoutId="jp-tier-thumb"
                className="absolute inset-0 rounded-[6px] bg-card shadow-sh-1"
                transition={{ duration: 0.26, ease: EASE_PAPER }}
                aria-hidden="true"
              />
            )}
            <span className="relative z-10 flex items-baseline gap-1">
              {option.label}
              <span className={cn('font-mono text-[11px] leading-[14px] tnum', active ? 'text-brand-600' : 'text-ink-300')}>
                {counts ? counts[option.value] : '—'}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function FieldLabel({ children }: { children: string }) {
  return <p className="mb-1.5 text-micro font-medium uppercase tracking-[0.08em] text-ink-400">{children}</p>;
}

function SelectField({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: number;
  onChange: (v: number) => void;
  options: { value: number; label: string }[];
  ariaLabel: string;
}) {
  return (
    <div className="relative">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-8 appearance-none rounded-md border border-line bg-card pl-2.5 pr-7 font-mono text-caption text-ink-600 tnum transition-colors hover:border-line-strong"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Icon name="chevron-down" size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-ink-400" />
    </div>
  );
}

function PriceInput({
  value,
  placeholder,
  ariaLabel,
  onCommit,
}: {
  value: number | null;
  placeholder: string;
  ariaLabel: string;
  onCommit: (v: number | null) => void;
}) {
  const [text, setText] = useState(value === null ? '' : String(value));
  const [prevValue, setPrevValue] = useState(value);
  if (!Object.is(prevValue, value)) {
    setPrevValue(value);
    setText(value === null ? '' : String(value));
  }
  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 font-mono text-caption text-ink-300">¥</span>
      <input
        value={text}
        inputMode="decimal"
        aria-label={ariaLabel}
        placeholder={placeholder}
        onChange={(event) => {
          const raw = event.target.value;
          if (!/^\d*\.?\d*$/.test(raw)) return;
          setText(raw);
          const number = Number(raw);
          onCommit(raw === '' || !Number.isFinite(number) ? null : number);
        }}
        className="h-8 w-[88px] rounded-md border border-line bg-card pl-6 pr-2 font-mono text-caption text-ink-800 tnum placeholder:text-ink-300 hover:border-line-strong"
      />
    </div>
  );
}

export function ScanButton({
  scanning,
  dirty,
  universeCount,
  onScan,
  className,
}: {
  scanning: boolean;
  dirty: boolean;
  universeCount: number | null;
  onScan: () => void;
  className?: string;
}) {
  const base = 'inset 0 1px 0 rgba(255,255,255,.16), 0 1px 2px rgba(16,24,40,.18), 0 4px 12px -4px rgba(16,24,40,.34)';
  return (
    <motion.button
      type="button"
      onClick={onScan}
      disabled={scanning}
      animate={
        dirty && !scanning
          ? { boxShadow: [`${base}, 0 0 0 0 rgba(46,70,224,.38)`, `${base}, 0 0 0 9px rgba(46,70,224,0)`, `${base}, 0 0 0 0 rgba(46,70,224,0)`] }
          : { boxShadow: `${base}, 0 0 0 0 rgba(46,70,224,0)` }
      }
      transition={dirty && !scanning ? { duration: 1.2, repeat: 2 } : { duration: 0.16 }}
      className={cn(
        'relative h-10 min-w-[168px] overflow-hidden rounded-md bg-brand-600 px-4 text-white transition-[filter] duration-fast',
        scanning ? 'cursor-wait' : 'hover:brightness-105',
        className,
      )}
      aria-live="polite"
      aria-busy={scanning}
    >
      {scanning && (
        <motion.span
          className="absolute inset-y-0 w-2/5 bg-gradient-to-r from-transparent via-white/18 to-transparent"
          initial={{ x: '-120%' }}
          animate={{ x: '350%' }}
          transition={{ duration: 1.25, ease: 'linear', repeat: Infinity }}
          aria-hidden="true"
        />
      )}
      <span className="relative z-10 flex items-center justify-center gap-2">
        {scanning ? (
          <>
            <span className="size-[18px] animate-spin rounded-full border-2 border-white/35 border-t-white" aria-hidden="true" />
            <span className="text-body-s font-medium">{t('扫描中…')}</span>
          </>
        ) : (
          <>
            <Icon name="crosshair" size={16} />
            <span className="text-body-s font-medium">{t('开始扫描')}</span>
            {universeCount !== null && (
              <span className="font-mono text-micro text-white/70 tnum">≈{universeCount} {t('只')}</span>
            )}
          </>
        )}
      </span>
    </motion.button>
  );
}

interface FilterWorkbenchProps {
  draft: ScanFilters;
  onChange: (f: ScanFilters) => void;
  tierCounts: Record<TierFilter, number> | null;
  universeCount: number | null;
  meta: StrengthProfilesMeta | null;
  metaFailed: boolean;
  scanning: boolean;
  dirty: boolean;
  onScan: () => void;
}

export default function FilterWorkbench({
  draft,
  onChange,
  tierCounts,
  universeCount,
  meta,
  metaFailed,
  scanning,
  dirty,
  onScan,
}: FilterWorkbenchProps) {
  const [showAllSectors, setShowAllSectors] = useState(false);
  const sectorOptions = meta?.sectors ?? [];
  const visibleSectors = showAllSectors ? sectorOptions : sectorOptions.slice(0, SECTOR_COLLAPSE_AT);
  const hiddenCount = sectorOptions.length - visibleSectors.length;

  const patch = (partial: Partial<ScanFilters>) => onChange({ ...draft, ...partial });

  const toggleSector = (id: string) => {
    const has = draft.sectors.includes(id);
    patch({ sectors: has ? draft.sectors.filter((x) => x !== id) : [...draft.sectors, id] });
  };

  const applyPreset = (id: string) => {
    if (draft.presetId === id) {
      patch({ presetId: null, minScore: null });
      return;
    }
    if (id === 'conservative' || id === 'balanced' || id === 'aggressive') {
      patch({ presetId: id, profile: id, minScore: null });
      return;
    }
    const preset = meta?.presets.find((item) => item.id === id);
    if (preset) {
      patch({
        presetId: id,
        profile: (preset.profile as ProfilePref) || 'balanced',
        minScore: preset.min_score,
      });
    }
  };

  const row = {
    hidden: { opacity: 0, y: 14 },
    show: { opacity: 1, y: 0, transition: { duration: 0.48, ease: EASE_PAPER } },
  };

  const presetChips = [
    ...(meta?.profiles ?? []).map((profile) => ({ id: profile.id, name: profile.name, description: profile.description })),
    ...(meta?.presets ?? []).map((preset) => ({ id: preset.id, name: preset.name, description: preset.description })),
  ];

  return (
    <motion.section
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.06 } } }}
      className="card-surface p-4 sm:p-5"
      aria-label={t('筛选工作台')}
    >
      {/* 行 1 · 分档与预设 */}
      <motion.div variants={row} className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-3">
        <div className="w-full min-w-0 sm:w-auto">
          <FieldLabel>{t('强度分档')}</FieldLabel>
          <TierSegmented
            value={draft.tier}
            counts={tierCounts}
            onChange={(tier) => patch({ tier, presetId: null })}
          />
        </div>
        <div className="hidden h-9 w-px bg-line sm:block" aria-hidden="true" />
        <div className="w-full min-w-0 sm:w-auto sm:flex-1">
          <FieldLabel>{t('预设策略')}</FieldLabel>
          {metaFailed ? (
            <p className="flex h-8 items-center text-caption text-ink-400">{t('预设暂不可用 · 使用默认条件')}</p>
          ) : presetChips.length === 0 ? (
            <div className="flex gap-2" aria-hidden="true">
              {Array.from({ length: 3 }, (_, i) => (
                <span key={i} className="skeleton-shimmer h-8 w-20 rounded-pill" />
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {presetChips.map((preset) => {
                const active = draft.presetId === preset.id;
                return (
                  <motion.button
                    key={preset.id}
                    type="button"
                    onClick={() => applyPreset(preset.id)}
                    animate={{ scale: active ? 1.04 : 1 }}
                    transition={SPRING_POP}
                    title={preset.description}
                    aria-pressed={active}
                    className={cn(
                      'flex h-8 items-center gap-1.5 rounded-pill border px-3 text-caption transition-colors duration-fast',
                      active
                        ? 'border-brand-400 bg-brand-100 text-brand-700'
                        : 'border-line bg-card text-ink-500 hover:border-brand-400/60 hover:text-brand-600',
                    )}
                  >
                    <Icon name="spark-ai" size={13} className={active ? 'text-brand-600' : 'text-ink-300'} />
                    {preset.name}
                  </motion.button>
                );
              })}
            </div>
          )}
        </div>
      </motion.div>

      <div className="my-4 h-px bg-line" aria-hidden="true" />

      {/* 行 2 · 周期 / 偏好 / Top N */}
      <motion.div variants={row} className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <FieldLabel>{t('周期')}</FieldLabel>
          <Segmented<Timeframe>
            options={(['short', 'mid', 'long', 'all'] as const).map((value) => ({ value, label: TIMEFRAME_CN[value] }))}
            value={draft.timeframe}
            onChange={(timeframe) => patch({ timeframe })}
          />
        </div>
        <div>
          <FieldLabel>{t('偏好')}</FieldLabel>
          <Segmented<ProfilePref>
            options={(['conservative', 'balanced', 'aggressive'] as const).map((value) => ({ value, label: PROFILE_CN[value] }))}
            value={draft.profile}
            onChange={(profile) => patch({ profile, presetId: null })}
          />
        </div>
        <div>
          <FieldLabel>{t('返回数量')}</FieldLabel>
          <SelectField
            ariaLabel={t('返回数量 Top N')}
            value={draft.topN}
            onChange={(topN) => patch({ topN })}
            options={TOPN_OPTIONS}
          />
        </div>
      </motion.div>

      <div className="my-4 h-px bg-line" aria-hidden="true" />

      {/* 行 3 · 33业种 / 价格 / 成交额 / 扫描钮 */}
      <motion.div variants={row} className="flex flex-wrap items-end gap-x-3 gap-y-3 sm:gap-x-6">
        <div className="w-full min-w-0 flex-none sm:w-auto sm:flex-1">
          <FieldLabel>{t('业种（多选）')}</FieldLabel>
          {sectorOptions.length === 0 ? (
            <div className="flex flex-wrap gap-2" aria-hidden="true">
              {Array.from({ length: 5 }, (_, i) => (
                <span key={i} className="skeleton-shimmer h-7 w-16 rounded-xs" />
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              {visibleSectors.map((sector) => {
                const active = draft.sectors.includes(sector.id);
                return (
                  <motion.button
                    key={sector.id}
                    type="button"
                    onClick={() => toggleSector(sector.id)}
                    animate={{ scale: active ? 1.04 : 1 }}
                    transition={SPRING_POP}
                    aria-pressed={active}
                    className={cn(
                      'flex h-7 shrink-0 items-center whitespace-nowrap rounded-xs border px-2 text-caption transition-colors duration-fast',
                      active
                        ? 'border-brand-400 bg-brand-100 text-brand-700'
                        : 'border-line bg-card text-ink-500 hover:border-brand-400/60 hover:text-brand-600',
                    )}
                  >
                    {sector.name}
                  </motion.button>
                );
              })}
              {hiddenCount > 0 && (
                <button
                  type="button"
                  onClick={() => setShowAllSectors(true)}
                  className="flex h-7 shrink-0 items-center whitespace-nowrap rounded-xs border border-dashed border-line-strong px-2 font-mono text-caption text-ink-400 tnum transition-colors hover:text-brand-600"
                >
                  +{hiddenCount}
                </button>
              )}
              {showAllSectors && sectorOptions.length > SECTOR_COLLAPSE_AT && (
                <button
                  type="button"
                  onClick={() => setShowAllSectors(false)}
                  className="flex h-7 shrink-0 items-center whitespace-nowrap rounded-xs px-1.5 text-caption text-ink-400 transition-colors hover:text-ink-600"
                >
                  {t('收起')}
                </button>
              )}
            </div>
          )}
        </div>
        <div>
          <FieldLabel>{t('价格区间')}</FieldLabel>
          <div className="flex items-center gap-1.5">
            <PriceInput value={draft.priceMin} placeholder={t('最低')} ariaLabel={t('最低价格')} onCommit={(priceMin) => patch({ priceMin })} />
            <span className="text-ink-300" aria-hidden="true">–</span>
            <PriceInput value={draft.priceMax} placeholder={t('最高')} ariaLabel={t('最高价格')} onCommit={(priceMax) => patch({ priceMax })} />
          </div>
        </div>
        <div>
          <FieldLabel>{t('成交额下限')}</FieldLabel>
          <SelectField
            ariaLabel={t('成交额下限')}
            value={draft.minTurnover}
            onChange={(minTurnover) => patch({ minTurnover })}
            options={TURNOVER_OPTIONS}
          />
        </div>
        <ScanButton scanning={scanning} dirty={dirty} universeCount={universeCount} onScan={onScan} className="ml-auto" />
      </motion.div>
    </motion.section>
  );
}
