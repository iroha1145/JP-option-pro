/**
 * B2 结果表（桌面 ≥768px）— 对标美版 ResultTable。
 * 列：# / 代码 / 强度分 / 分类 / 分项 / 收盘·涨跌 / 新闻72h / 20日均额 / ▸
 * 行展开 accordion 260ms；stagger 仅第一页。
 */
import { Fragment } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { StrengthRow } from '@/api/types';
import { cn } from '@/lib/utils';
import { fmtPrice, fmtYenCompact } from '@/lib/format';
import Icon from '@/components/icons';
import ChangeBadge from '@/components/shared/ChangeBadge';
import InfoHint from '@/components/shared/InfoHint';
import { CodeCell } from '@/components/domain';
import { STRENGTH_HINTS } from '@/lib/indicatorHints';
import RowExpansion from './RowExpansion';
import { NewsBadge, ScoreCell, SubscoreTicks } from './cells';
import { tierOf, TIER_RANGE, type NewsSummaryMap } from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

export interface ResultTableProps {
  rows: StrengthRow[];
  startIndex: number;
  page: number;
  totalPages: number;
  onPageChange: (p: number) => void;
  expanded: string | null;
  onToggle: (code: string) => void;
  news: NewsSummaryMap;
  newsLoaded: boolean;
  weights: Record<string, number> | null;
  canManageWatchlist: boolean;
  animKey: string;
  /** 盘中叠加（表示専用）。夜間断面のスコアは書き換えない。 */
  overlay?: Record<string, { live_price: number; live_change_pct?: number; live_pct_from_high_252?: number | null }>;
}

export default function ResultTable({
  rows,
  startIndex,
  page,
  totalPages,
  onPageChange,
  expanded,
  onToggle,
  news,
  newsLoaded,
  weights,
  canManageWatchlist,
  animKey,
  overlay,
}: ResultTableProps) {
  return (
    <div className="card-surface overflow-x-auto overscroll-x-contain">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-card-warm">
            <Th width="36px">#</Th>
            <Th>{t('代码')}</Th>
            <Th>
              {t('强度分')}
              <InfoHint hint={STRENGTH_HINTS.composite} side="bottom" size={11} className="ml-1" />
            </Th>
            <Th>{t('分类')}</Th>
            <Th>{t('分项')}</Th>
            <Th align="right">{t('收盘 / 涨跌')}</Th>
            <Th>{t('新闻 · 72H')}</Th>
            <Th align="right">{t('20日均额')}</Th>
            <Th width="40px"> </Th>
          </tr>
        </thead>
        <tbody key={animKey}>
          {rows.map((row, index) => {
            const isOpen = expanded === row.canonical_code;
            const score = row.ranking_score;
            return (
              <Fragment key={row.canonical_code}>
                <motion.tr
                  layout="position"
                  initial={page === 1 ? { opacity: 0, y: 14 } : false}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.4,
                    ease: EASE_PAPER,
                    delay: page === 1 ? Math.min(index * 0.03, 0.3) : 0,
                    layout: { duration: 0.32, ease: EASE_PAPER },
                  }}
                  onClick={() => onToggle(row.canonical_code)}
                  tabIndex={0}
                  role="button"
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onToggle(row.canonical_code);
                    }
                  }}
                  className={cn(
                    'group h-11 cursor-pointer border-b border-line transition-colors duration-fast hover:bg-paper-2',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-500/30',
                    isOpen && 'bg-paper-2',
                  )}
                  aria-expanded={isOpen}
                >
                  <td className="px-3 py-2 font-mono text-caption text-ink-400 tnum">{startIndex + index + 1}</td>
                  <td className="px-3 py-2">
                    <CodeCell displayCode={row.display_code} nameJa={row.name_ja} />
                    <span className="block max-w-[180px] truncate pl-0.5 text-micro text-ink-400">
                      {row.sector33_name ?? '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <ScoreCell score={score} index={index} />
                  </td>
                  <td className="px-3 py-2">
                    {row.classification ? (
                      <span className="whitespace-nowrap rounded-xs bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">{t(row.classification)}</span>
                    ) : (
                      <span className="text-ink-300">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <SubscoreTicks row={row} tipSide={index < 3 ? 'bottom' : 'top'} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className="inline-block font-mono text-body-s text-ink-900 tnum">{fmtPrice(row.close)}</span>
                    <span className="ml-1.5 align-middle">
                      <ChangeBadge value={row.change_pct !== null ? row.change_pct / 100 : null} size="sm" />
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <NewsBadge summary={news[row.canonical_code]} loaded={newsLoaded} tipSide={index < 3 ? 'bottom' : 'top'} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-body-s text-ink-600 tnum">
                    {fmtYenCompact(row.avg_turnover_20d)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={cn(
                        'inline-flex size-6 items-center justify-center rounded-sm border border-line text-ink-400 transition-transform duration-200',
                        isOpen && 'rotate-180 border-brand-400 text-brand-600',
                      )}
                    >
                      <Icon name="chevron-down" size={13} />
                    </span>
                  </td>
                </motion.tr>
                <AnimatePresence>
                  {isOpen && (
                    <tr key={`${row.canonical_code}-exp`}>
                      <td colSpan={9} className="p-0">
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.26, ease: EASE_PAPER }}
                          className="overflow-hidden"
                        >
                          <RowExpansion row={row} weights={weights} canManageWatchlist={canManageWatchlist} live={overlay?.[row.canonical_code]} />
                        </motion.div>
                      </td>
                    </tr>
                  )}
                </AnimatePresence>
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-card-warm px-4 py-2.5">
        <p className="font-mono text-micro text-ink-400 tnum">
          {t('每页 20 · 分档')}{' '}
          {rows.length > 0 && rows[0].ranking_score !== null
            ? `${tierOf(rows[0].ranking_score)}–${tierOf(rows[rows.length - 1].ranking_score ?? 0)}（${TIER_RANGE[tierOf(rows[0].ranking_score)]}）`
            : '—'}
        </p>
        <nav className="flex items-center gap-1" aria-label={t('分页')}>
          <PageButton disabled={page <= 1} onClick={() => onPageChange(page - 1)} ariaLabel={t('上一页')}>
            <Icon name="chevron-right" size={13} className="rotate-180" />
          </PageButton>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPageChange(p)}
              aria-current={p === page ? 'page' : undefined}
              className={cn(
                'flex size-7 items-center justify-center rounded-sm border font-mono text-caption tnum transition-colors duration-fast',
                p === page
                  ? 'border-brand-600 bg-brand-600 text-white'
                  : 'border-line text-ink-500 hover:border-brand-400 hover:text-brand-600',
              )}
            >
              {p}
            </button>
          ))}
          <PageButton disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} ariaLabel={t('下一页')}>
            <Icon name="chevron-right" size={13} />
          </PageButton>
        </nav>
      </div>
    </div>
  );
}

function Th({
  children,
  align,
  width,
}: {
  children: React.ReactNode;
  align?: 'right' | 'center';
  width?: string;
}) {
  return (
    <th
      style={width ? { width } : undefined}
      className={cn(
        'whitespace-nowrap border-b border-line px-3 py-2.5 text-eyebrow font-sans uppercase tracking-[0.14em] text-ink-400',
        align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left',
      )}
    >
      {children}
    </th>
  );
}

function PageButton({
  children,
  disabled,
  onClick,
  ariaLabel,
}: {
  children: React.ReactNode;
  disabled: boolean;
  onClick: () => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className="flex size-7 items-center justify-center rounded-sm border border-line text-ink-500 transition-colors hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}
