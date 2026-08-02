/**
 * 选股扫描（强度）· 共享类型与常量 — 对标美版 screener/types.ts。
 * 分档：S≥90 / A 80–89 / B 70–79 / C 60–69（D<60 仅计入「全部」）。
 * 强度分档着色走 brand/warn 色阶而非红绿 —— 红涨绿跌只留给涨跌幅，
 * 避免「强度高=在涨」的暗示（日中惯例红=涨，与美版相反，故不照搬美版配色）。
 */
import type { NewsSecurityRow, TierDistribution } from '@/api/types';
import { t } from '@/i18n/core';

export type Tier = 'S' | 'A' | 'B' | 'C' | 'D';
export type TierFilter = 'all' | 'S' | 'A' | 'B' | 'C';
export type Timeframe = 'short' | 'mid' | 'long' | 'all';
export type ProfilePref = 'conservative' | 'balanced' | 'aggressive';
export type SortMode = 'deterministic' | 'latest' | 'impact';

export const TIMEFRAME_CN: Record<Timeframe, string> = {
  short: t('短期'),
  mid: t('中期'),
  long: t('长期'),
  all: t('全部周期'),
};

export const PROFILE_CN: Record<ProfilePref, string> = {
  conservative: t('稳健'),
  balanced: t('均衡'),
  aggressive: t('进取'),
};

export const SORT_CN: Record<SortMode, string> = {
  deterministic: t('确定性'),
  latest: t('最新催化'),
  impact: t('影响力'),
};

export function tierOf(score: number): Tier {
  if (score >= 90) return 'S';
  if (score >= 80) return 'A';
  if (score >= 70) return 'B';
  if (score >= 60) return 'C';
  return 'D';
}

export const TIER_RANGE: Record<Tier, string> = {
  S: '≥90', A: '80–89', B: '70–79', C: '60–69', D: '<60',
};

export interface StrengthPresentation {
  band: Tier;
  label: string;
  barClass: string;
  textClass: string;
}

/** 固定分数区间着色（不随结果集漂移）；A 档在 85 细分，避免 Top20 单色。 */
export function strengthPresentation(score: number): StrengthPresentation {
  if (score >= 90) return { band: 'S', label: t('顶尖'), barClass: 'bg-brand-700', textClass: 'text-brand-700' };
  if (score >= 85) return { band: 'A', label: t('极强'), barClass: 'bg-brand-600', textClass: 'text-brand-700' };
  if (score >= 80) return { band: 'A', label: t('强势'), barClass: 'bg-brand-500', textClass: 'text-brand-600' };
  if (score >= 70) return { band: 'B', label: t('较强'), barClass: 'bg-brand-400', textClass: 'text-brand-600' };
  if (score >= 60) return { band: 'C', label: t('观察'), barClass: 'bg-warn-600', textClass: 'text-warn-600' };
  return { band: 'D', label: t('偏弱'), barClass: 'bg-ink-300', textClass: 'text-ink-500' };
}

/** 筛选条件（draft = 工作台编辑中；applied = 上次扫描快照）。全部服务端生效。 */
export interface ScanFilters {
  tier: TierFilter;
  timeframe: Timeframe;
  profile: ProfilePref;
  /** 返回条数上限；0 = 最多 200 */
  topN: number;
  sectors: string[];
  priceMin: number | null;
  priceMax: number | null;
  /** 20日均売買代金下限（円）；0 = 不限 */
  minTurnover: number;
  minScore: number | null;
  presetId: string | null;
}

export const DEFAULT_TOP_N = 20;
export const MAX_TOP_N = 200;

export const DEFAULT_FILTERS: ScanFilters = {
  tier: 'all',
  timeframe: 'all',
  profile: 'balanced',
  topN: DEFAULT_TOP_N,
  sectors: [],
  priceMin: null,
  priceMax: null,
  minTurnover: 100_000_000,
  minScore: null,
  presetId: null,
};

export const TOPN_OPTIONS: { value: number; label: string }[] = [
  { value: 10, label: 'Top 10' },
  { value: 20, label: 'Top 20' },
  { value: 40, label: 'Top 40' },
  { value: 0, label: t('最多 200') },
];

export const TURNOVER_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: t('不限成交额') },
  { value: 100_000_000, label: '≥ 1億円' },
  { value: 500_000_000, label: '≥ 5億円' },
  { value: 1_000_000_000, label: '≥ 10億円' },
  { value: 5_000_000_000, label: '≥ 50億円' },
  { value: 10_000_000_000, label: '≥ 100億円' },
];

/** 每股新闻摘要：newsApi.securities 一次批量取回（72h 窗口，仅覆盖已接入 RSS 源）。 */
export type NewsSummaryMap = Record<string, NewsSecurityRow | undefined>;

export function tierCountsFromDistribution(
  distribution: TierDistribution | null,
): Record<TierFilter, number> | null {
  if (!distribution) return null;
  return {
    all: distribution.total,
    S: distribution.S,
    A: distribution.A,
    B: distribution.B,
    C: distribution.C,
  };
}

/** 扫描历史条目（页头 popover 最近 5 次，仅本会话） */
export interface ScanHistoryEntry {
  at: number;
  count: number;
  durationMs: number;
  summary: string;
}

/** 分项微条与展开区共用的六族定义（与后端 FAMILY_WEIGHTS 同源）。 */
export const FAMILY_META: { key: string; label: string }[] = [
  { key: 'short', label: t('短期') },
  { key: 'mid', label: t('中期') },
  { key: 'long', label: t('长期') },
  { key: 'trend', label: t('趋势') },
  { key: 'breakout', label: t('突破质量') },
  { key: 'price_action', label: t('价格行为') },
];
