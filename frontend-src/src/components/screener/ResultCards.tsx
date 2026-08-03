/**
 * 移动端结果卡片流（<768px 表格转卡片）— 对标美版 ResultCards。
 * 卡内：代码 + 强度大分 + 强度条 + 分项微条 + 涨跌 + 新闻徽标；点按展开明细。
 */
import { AnimatePresence, motion } from 'framer-motion';
import type { StrengthRow } from '@/api/types';
import { cn } from '@/lib/utils';
import { fmtPrice } from '@/lib/format';
import Icon from '@/components/icons';
import ChangeBadge from '@/components/shared/ChangeBadge';
import RowExpansion from './RowExpansion';
import { NewsBadge, SubscoreTicks } from './cells';
import { strengthPresentation, type NewsSummaryMap } from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

export interface ResultCardsProps {
  rows: StrengthRow[];
  expanded: string | null;
  onToggle: (code: string) => void;
  news: NewsSummaryMap;
  newsLoaded: boolean;
  weights: Record<string, number> | null;
  canManageWatchlist: boolean;
  animKey: string;
  page?: number;
  /** 盘中叠加（表示専用）。夜間断面のスコアは書き換えない。 */
  overlay?: Record<string, { live_price: number; live_change_pct?: number; live_pct_from_high_252?: number | null }>;
}

export default function ResultCards({
  rows,
  expanded,
  onToggle,
  news,
  newsLoaded,
  weights,
  canManageWatchlist,
  animKey,
  page = 1,
  overlay,
}: ResultCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-3" key={animKey}>
      {rows.map((row, index) => {
        const isOpen = expanded === row.canonical_code;
        const score = row.ranking_score;
        const strength = score !== null ? strengthPresentation(score) : null;
        const width = score !== null ? Math.max(2, Math.min(100, score)) : 0;
        return (
          <motion.div
            key={row.canonical_code}
            layout="position"
            initial={page === 1 ? { opacity: 0, y: 14 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.4,
              ease: EASE_PAPER,
              delay: page === 1 ? Math.min(index * 0.03, 0.3) : 0,
              layout: { duration: 0.32, ease: EASE_PAPER },
            }}
            whileHover={{ y: -3, transition: { duration: 0.24, ease: 'easeOut' } }}
            className="card-surface overflow-hidden transition-shadow duration-fast hover:shadow-sh-2"
          >
            <button type="button" onClick={() => onToggle(row.canonical_code)} aria-expanded={isOpen} className="flex w-full flex-col p-4 text-left">
              <span className="flex items-center gap-2.5">
                <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
                  {row.display_code}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body-s text-ink-800">{row.name_ja ?? '—'}</span>
                  <span className="block truncate text-micro text-ink-400">{row.sector33_name ?? '—'}</span>
                </span>
                <ChangeBadge value={row.change_pct !== null ? row.change_pct / 100 : null} size="sm" />
                <Icon
                  name="chevron-down"
                  size={14}
                  className={cn('text-ink-300 transition-transform duration-200', isOpen && 'rotate-180 text-brand-600')}
                />
              </span>
              <span className="mt-3 flex items-end justify-between gap-3">
                <span>
                  <span className={cn('font-mono text-data-xl tnum', strength?.textClass ?? 'text-ink-300')}>
                    {score !== null ? score.toFixed(1) : '—'}
                  </span>
                  {strength && (
                    <span className="ml-1.5 text-micro text-ink-400">
                      {t('强度分 ·')} {strength.band} {strength.label}
                    </span>
                  )}
                </span>
                <span className="pb-0.5 text-right">
                  <span className="block font-mono text-data-m text-ink-800 tnum">{fmtPrice(row.close)}</span>
                </span>
              </span>
              <span className="relative mt-2.5 h-[3px] w-full rounded-pill bg-line" role="presentation" aria-hidden="true">
                {strength && (
                  <motion.span
                    className={cn('block h-full origin-left rounded-pill', strength.barClass)}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ duration: 0.7, ease: EASE_PAPER, delay: 0.15 + index * 0.03 }}
                    style={{ width: `${width}%` }}
                  />
                )}
              </span>
              <span className="mt-3 flex items-center justify-between border-t border-line pt-3">
                <SubscoreTicks row={row} />
                <NewsBadge summary={news[row.canonical_code]} loaded={newsLoaded} />
              </span>
            </button>
            <AnimatePresence>
              {isOpen && (
                <motion.div
                  key="exp"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.26, ease: EASE_PAPER }}
                  className="overflow-hidden"
                >
                  <RowExpansion row={row} weights={weights} canManageWatchlist={canManageWatchlist} live={overlay?.[row.canonical_code]} />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </div>
  );
}
