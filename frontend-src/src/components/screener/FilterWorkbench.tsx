/**
 * B1 筛选工作台 — 对标美版 FilterWorkbench。
 * 常驻：分档 / 周期 / 偏好 / 返回数量 / 扫描
 * 更多筛选：预设、33 业种、价格（円）、成交额下限；折叠时仍展示当前约束
 * 手机走 pill-on-track（.mobile-selection-rail / shared Segmented）
 */
import { useState } from 'react';
import { motion } from 'framer-motion';
import type { StrengthProfilesMeta } from '@/api/types';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import Segmented from '@/components/shared/Segmented';
import FilterButton from '@/components/shared/FilterButton';
import PointerTooltip from '@/components/shared/PointerTooltip';
import SelectionViewport from '@/components/shared/SelectionViewport';
import SoftBadge from '@/components/shared/SoftBadge';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import InfoHint from '@/components/shared/InfoHint';
import { STRENGTH_HINTS, type ScoreHint } from '@/lib/indicatorHints';
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
const SECTOR_COLLAPSE_AT = 6;

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
    <Segmented<TierFilter>
      options={TIER_OPTIONS}
      value={value}
      onChange={onChange}
      scrollable
      ariaLabel={t('强度分档 · 计数基于已评分候选池')}
      renderLabel={(option, active) => (
        <span className="flex items-center gap-1.5">
          {option.label}
          <span className={cn('min-w-4 rounded-[5px] px-1 py-px font-mono text-[11px] leading-[14px] tnum', active ? 'bg-paper-2 text-ink-600' : 'text-ink-400')}>
            {counts ? counts[option.value] : '—'}
          </span>
        </span>
      )}
    />
  );
}

function FieldLabel({ children, hint }: { children: string; hint?: ScoreHint }) {
  return (
    <p className="mb-2 flex items-center gap-0.5 text-caption font-medium text-ink-500">
      {children}
      {hint && <InfoHint hint={hint} side="bottom" size={11} />}
    </p>
  );
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
        className="menu-select-trigger h-9 appearance-none rounded-md border border-line-strong bg-card pl-2.5 pr-7 font-mono text-caption text-ink-600 tnum transition-colors hover:bg-paper-2"
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
        className="screener-price-input h-8 w-[88px] rounded-[9px] border border-line/70 bg-paper-2/50 pl-6 pr-2 font-mono text-caption text-ink-800 tnum placeholder:text-ink-300 hover:border-line-strong focus-visible:border-brand-400"
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
  const base = 'inset 0 1px 0 rgba(255,255,255,.12), 0 1px 2px rgba(16,24,40,.12), 0 3px 7px -4px rgba(16,24,40,.24)';
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
        'scan-trigger relative h-9 min-w-[168px] overflow-hidden rounded-[9px] bg-brand-600 px-4 text-white shadow-btn-hi transition-[filter] duration-fast',
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

  const selectedPreset = presetChips.find((preset) => preset.id === draft.presetId);
  const selectedSectors = draft.sectors.map((id) => sectorOptions.find((sector) => sector.id === id)?.name ?? id);
  const priceSummary =
    draft.priceMin !== null && draft.priceMax !== null
      ? `${t('价格区间')} ¥${draft.priceMin} – ¥${draft.priceMax}`
      : draft.priceMin !== null
        ? `${t('价格区间')} ≥ ¥${draft.priceMin}`
        : draft.priceMax !== null
          ? `${t('价格区间')} ≤ ¥${draft.priceMax}`
          : null;
  const volumeSummary =
    draft.minTurnover > 0
      ? `${t('成交额下限')} ${TURNOVER_OPTIONS.find((option) => option.value === draft.minTurnover)?.label ?? draft.minTurnover}`
      : null;
  const advancedSummary = [
    selectedPreset?.name,
    selectedSectors.length > 0
      ? `${selectedSectors.slice(0, 2).join(' / ')}${selectedSectors.length > 2 ? ` +${selectedSectors.length - 2}` : ''}`
      : null,
    priceSummary,
    volumeSummary,
  ].filter((value): value is string => Boolean(value));

  return (
    <motion.section
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.06 } } }}
      className="card-surface p-4 sm:p-5"
      aria-label={t('筛选工作台')}
      data-testid="screener-filter-workbench"
    >
      <motion.div variants={row} className="flex min-w-0 flex-wrap items-end gap-x-5 gap-y-4">
        <div className="w-full min-w-0 sm:w-auto">
          <FieldLabel hint={STRENGTH_HINTS.tierCounts}>{t('强度分档')}</FieldLabel>
          <TierSegmented
            value={draft.tier}
            counts={tierCounts}
            onChange={(tier) => patch({ tier, presetId: null })}
          />
        </div>
        <div className="w-full min-w-0 sm:w-auto">
          <FieldLabel hint={STRENGTH_HINTS.timeframe}>{t('周期')}</FieldLabel>
          <Segmented<Timeframe>
            options={(['short', 'mid', 'long', 'all'] as const).map((value) => ({ value, label: TIMEFRAME_CN[value] }))}
            value={draft.timeframe}
            onChange={(timeframe) => patch({ timeframe })}
            ariaLabel={t('周期')}
          />
        </div>
        <div className="min-w-0">
          <FieldLabel hint={STRENGTH_HINTS.profile}>{t('偏好')}</FieldLabel>
          <Segmented<ProfilePref>
            options={(['conservative', 'balanced', 'aggressive'] as const).map((value) => ({ value, label: PROFILE_CN[value] }))}
            value={draft.profile}
            onChange={(profile) => patch({ profile, presetId: null })}
            ariaLabel={t('偏好')}
          />
        </div>
        <div>
          <FieldLabel hint={STRENGTH_HINTS.topN}>{t('返回数量')}</FieldLabel>
          <SelectField
            ariaLabel={t('返回数量 Top N')}
            value={draft.topN}
            onChange={(topN) => patch({ topN })}
            options={TOPN_OPTIONS}
          />
        </div>
        <ScanButton
          scanning={scanning}
          dirty={dirty}
          universeCount={universeCount}
          onScan={onScan}
          className="w-full sm:ml-auto sm:w-auto"
        />
      </motion.div>

      <details className="group/filters mt-5 border-t border-line/70 pt-3" data-testid="screener-advanced-filters">
        <summary className="disclosure-trigger flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-2 rounded-lg py-1 text-caption text-ink-500 outline-none transition-colors hover:text-ink-800 focus-visible:ring-2 focus-visible:ring-brand-400/40 [&::-webkit-details-marker]:hidden">
          <span className="inline-flex shrink-0 items-center gap-2 font-medium text-ink-700">
            <Icon name="filter-funnel" size={14} className="text-ink-400" />
            {t('更多筛选')}
            <Icon name="chevron-down" size={13} className="text-ink-400 transition-transform group-open/filters:rotate-180" />
          </span>
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 text-micro text-ink-500">
            {advancedSummary.length > 0 ? (
              advancedSummary.map((label, index) => <SoftBadge key={index}>{label}</SoftBadge>)
            ) : (
              <span>
                {t('预设策略')} · {t('业种（多选）')} · {t('价格区间')} · {t('成交额下限')}
              </span>
            )}
          </span>
        </summary>

        <div className="space-y-4 pt-4">
          <div className="min-w-0">
            <FieldLabel>{t('预设策略')}</FieldLabel>
            {metaFailed ? (
              <p className="flex h-8 items-center text-caption text-ink-400">{t('预设暂不可用 · 使用默认条件')}</p>
            ) : presetChips.length === 0 ? (
              <div className="t-skel flex gap-2" data-state="loading" aria-hidden="true">
                <div className="t-skel-skeleton is-pulsing flex gap-2">
                  {Array.from({ length: 3 }, (_, i) => (
                    <SkeletonBlock key={i} className="h-8 w-20 rounded-md" />
                  ))}
                </div>
                <div className="t-skel-content" />
              </div>
            ) : (
              <SelectionViewport>
                <div className="mobile-selection-rail flex flex-wrap gap-2">
                  {presetChips.map((preset) => {
                    const active = draft.presetId === preset.id;
                    const button = (
                      <FilterButton
                        key={preset.id}
                        onClick={() => applyPreset(preset.id)}
                        active={active}
                      >
                        <Icon name="spark-ai" size={13} className={active ? 'text-brand-600' : 'text-ink-400'} />
                        {preset.name}
                      </FilterButton>
                    );
                    return preset.description ? (
                      <PointerTooltip
                        key={preset.id}
                        passthrough
                        label={t(preset.description)}
                        content={<span className="text-micro leading-[16px] text-ink-600">{t(preset.description)}</span>}
                      >
                        {button}
                      </PointerTooltip>
                    ) : (
                      button
                    );
                  })}
                </div>
              </SelectionViewport>
            )}
          </div>

          <div data-screener-field="sectors" className="min-w-0">
            <FieldLabel>{t('业种（多选）')}</FieldLabel>
            {sectorOptions.length === 0 ? (
              <div className="t-skel flex flex-wrap gap-2" data-state="loading" aria-hidden="true">
                <div className="t-skel-skeleton is-pulsing flex flex-wrap gap-2">
                  {Array.from({ length: 5 }, (_, i) => (
                    <SkeletonBlock key={i} className="h-7 w-16 rounded-md" />
                  ))}
                </div>
                <div className="t-skel-content" />
              </div>
            ) : (
              <SelectionViewport>
                <div className="mobile-selection-rail flex flex-wrap items-center gap-1.5">
                  {visibleSectors.map((sector) => (
                    <FilterButton
                      key={sector.id}
                      onClick={() => toggleSector(sector.id)}
                      active={draft.sectors.includes(sector.id)}
                      className="shrink-0"
                    >
                      {sector.name}
                    </FilterButton>
                  ))}
                  {hiddenCount > 0 && (
                    <button
                      type="button"
                      onClick={() => setShowAllSectors(true)}
                      className="flex h-8 shrink-0 items-center whitespace-nowrap rounded-lg bg-paper-2 px-2.5 font-mono text-caption text-ink-500 tnum transition-colors hover:bg-paper hover:text-ink-800"
                    >
                      +{hiddenCount}
                    </button>
                  )}
                  {showAllSectors && sectorOptions.length > SECTOR_COLLAPSE_AT && (
                    <button
                      type="button"
                      onClick={() => setShowAllSectors(false)}
                      className="flex h-8 shrink-0 items-center whitespace-nowrap rounded-lg px-2 text-caption text-ink-400 transition-colors hover:text-ink-600"
                    >
                      {t('收起')}
                    </button>
                  )}
                </div>
              </SelectionViewport>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-x-6 gap-y-4 border-t border-line/60 pt-4">
            <div data-screener-field="price">
              <FieldLabel>{t('价格区间')}</FieldLabel>
              <div className="flex items-center gap-1.5">
                <PriceInput value={draft.priceMin} placeholder={t('最低')} ariaLabel={t('最低价格')} onCommit={(priceMin) => patch({ priceMin })} />
                <span className="text-ink-300" aria-hidden="true">–</span>
                <PriceInput value={draft.priceMax} placeholder={t('最高')} ariaLabel={t('最高价格')} onCommit={(priceMax) => patch({ priceMax })} />
              </div>
            </div>
            <div data-screener-field="dollar-volume">
              <FieldLabel hint={STRENGTH_HINTS.avgTurnover}>{t('成交额下限')}</FieldLabel>
              <SelectField
                ariaLabel={t('成交额下限')}
                value={draft.minTurnover}
                onChange={(minTurnover) => patch({ minTurnover })}
                options={TURNOVER_OPTIONS}
              />
            </div>
          </div>
        </div>
      </details>
    </motion.section>
  );
}
