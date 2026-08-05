/**
 * 行展开明细 — 对标美版 RowExpansion，但第二列改为「结构信号」：
 * 夜间结构分析（价格行为/量价一致/技术指标）已随行返回，无需逐行再请求。
 * ① 六族分项 breakdown（与行内微条同源；权重来自 /strength/profiles）
 * ② 结构信号（结构状态/形态/量价 setup/RSI/MACD/效率比）
 * ③ 操作（打开详情 / 加入自选）+ 排名分位 + 20日均额
 */
import { useState } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { watchlistApi } from '@/api/modules';
import type { StrengthRow } from '@/api/types';
import { cn } from '@/lib/utils';
import { fmtYenCompact } from '@/lib/format';
import Icon from '@/components/icons';
import InfoHint from '@/components/shared/InfoHint';
import { STRENGTH_HINTS } from '@/lib/indicatorHints';
import { explanationLines } from '@/lib/explainText';
import { FAMILY_META } from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

function barClass(value: number): string {
  return value >= 70 ? 'bg-brand-600' : value >= 45 ? 'bg-brand-400' : 'bg-warn-600';
}

export interface RowExpansionProps {
  row: StrengthRow;
  /** 盘中叠加。無ければ何も出さない（古い値で埋めない）。 */
  live?: { live_price: number; live_change_pct?: number; live_pct_from_high_252?: number | null };
  weights: Record<string, number> | null;
  canManageWatchlist: boolean;
}

export default function RowExpansion({ row, weights, canManageWatchlist, live }: RowExpansionProps) {
  const [added, setAdded] = useState(false);
  const technicals = row.structure.technicals;
  const priceAction = row.structure.price_action;
  const volPrice = row.structure.vol_price;
  // 警告と評価根拠は後端が組み立てる。数値混じりの文（「ATR约7.3%…」）は
  // 完成形だと辞書に当たらないので、テンプレート形の `*_items` を優先する。
  const warnings = explanationLines(row.warning_items, row.warnings);
  const reasons = explanationLines(row.reason_items, row.reasons);
  return (
    <div className="grid grid-cols-1 gap-x-8 gap-y-5 border-t border-line bg-card-warm/60 px-4 py-4 md:grid-cols-3">
      {/* ① 六族分项 */}
      <div>
        <p className="eyebrow">
          {t('分项强度 · BREAKDOWN')}
          <InfoHint hint={STRENGTH_HINTS.families} side="bottom" size={11} className="ml-1" />
        </p>
        <div className="mt-3 grid grid-cols-[max-content_minmax(0,1fr)_max-content] gap-y-2.5">
          {FAMILY_META.map(({ key, label }, index) => {
            const value = row.families[key] ?? null;
            const weight = weights?.[key] ?? null;
            return (
              <div key={key} className="col-span-3 grid grid-cols-subgrid items-center gap-x-2.5">
                <span className="whitespace-nowrap text-caption text-ink-500">{label}</span>
                <span className="h-1.5 overflow-hidden rounded-pill bg-line" role="presentation">
                  {value !== null && (
                    <motion.span
                      className={cn('block h-full origin-left rounded-pill', barClass(value))}
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: 0.7, ease: EASE_PAPER, delay: index * 0.05 }}
                      style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
                    />
                  )}
                </span>
                <span className="text-right font-mono text-caption text-ink-800 tnum">
                  {value !== null ? Math.round(value) : '—'}
                  {weight !== null && <span className="ml-1 text-micro text-ink-300">×{Math.round(weight * 100)}%</span>}
                </span>
              </div>
            );
          })}
        </div>
        {row.missing_families.length > 0 && (
          <p className="mt-2.5 text-micro text-ink-400">
            {t('缺失维度')}: {row.missing_families.join(' · ')} {t('（按缺失重新配权，不填中性值）')}
          </p>
        )}
        {warnings.length > 0 && (
          <ul className="mt-2.5 space-y-1">
            {warnings.map((warning, index) => (
              <li key={index} className="flex items-start gap-1.5 text-micro leading-[16px] text-warn-600">
                <span className="mt-px shrink-0" aria-hidden="true">⚠</span>
                {warning}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ② 结构信号（夜间结构分析，随行返回） */}
      <div>
        <p className="eyebrow">{t('结构信号 · STRUCTURE')}</p>
        <div className="mt-3 space-y-2 text-caption">
          <StructLine
            label={t('价格结构')}
            value={priceAction.structure_label ? t(priceAction.structure_label) : '—'}
          />
          {(priceAction.pattern_labels?.length ?? 0) > 0 && (
            <StructLine
              label={t('K线形态')}
              value={priceAction.pattern_labels!.map((label) => t(label)).join(t('、'))}
            />
          )}
          {(priceAction.spring || priceAction.upthrust) && (
            <StructLine
              label="Wyckoff"
              value={[priceAction.spring ? 'Spring' : null, priceAction.upthrust ? 'Upthrust' : null].filter(Boolean).join(' · ')}
            />
          )}
          <StructLine label={t('量价关系')} value={volPrice.setup_label ? t(volPrice.setup_label) : '—'} />
          <StructLine
            label="RSI14"
            value={technicals.rsi14 !== null && technicals.rsi14 !== undefined ? technicals.rsi14.toFixed(1) : '—'}
          />
          <StructLine
            label={t('MACD 动向')}
            value={
              technicals.macd_direction_pct !== null && technicals.macd_direction_pct !== undefined
                ? `${technicals.macd_direction_pct >= 0 ? '+' : ''}${technicals.macd_direction_pct.toFixed(2)}%`
                : '—'
            }
          />
          <StructLine
            label={t('趋势效率')}
            value={
              technicals.trend_efficiency_63d !== null && technicals.trend_efficiency_63d !== undefined
                ? technicals.trend_efficiency_63d.toFixed(2)
                : '—'
            }
          />
        </div>
        {reasons.length > 0 && (
          <div className="mt-3 border-t border-line pt-2.5">
            <p className="mb-1 text-micro text-ink-400">{t('评分依据')}</p>
            <ul className="space-y-0.5">
              {reasons.map((reason, index) => (
                <li key={index} className="text-micro leading-[16px] text-ink-600">· {reason}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* ③ 操作 + 排名 + 成交额 */}
      <div>
        <p className="eyebrow">{t('操作与排名')}</p>
        <div className="mt-3 flex flex-col items-start gap-2">
          <Link
            to={`/stock/${row.canonical_code}`}
            className="flex items-center gap-1.5 rounded-md border border-line bg-card px-3 py-1.5 text-caption text-ink-600 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600"
          >
            <Icon name="arrow-up-right" size={13} />
            {t('打开详情')}
          </Link>
          {canManageWatchlist && (
            <button
              type="button"
              disabled={added}
              onClick={async () => {
                try {
                  await watchlistApi.add(row.canonical_code);
                  setAdded(true);
                } catch {
                  /* 已在自选等情况静默 */
                }
              }}
              className="flex items-center gap-1.5 rounded-md border border-line bg-card px-3 py-1.5 text-caption text-ink-600 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600 disabled:opacity-60"
            >
              <Icon name={added ? 'check' : 'plus'} size={13} />
              {added ? t('已加入自选') : t('加入自选')}
            </button>
          )}
        </div>
        <div className="mt-3.5 space-y-1.5 border-t border-line pt-3 text-caption">
          <div className="flex items-center justify-between">
            <span className="text-ink-400">
              {t('全市场分位')}
              <InfoHint hint={STRENGTH_HINTS.percentile} size={11} className="ml-0.5" />
            </span>
            <span className="font-mono text-ink-800 tnum">
              {row.global_rank_percentile !== null ? `${row.global_rank_percentile.toFixed(1)}%` : '—'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-ink-400">{t('同业种分位')}</span>
            <span className="font-mono text-ink-800 tnum">
              {row.sector_rank_percentile !== null ? `${row.sector_rank_percentile.toFixed(1)}%` : '—'}
            </span>
          </div>
          {live && (
            <div className="flex items-center justify-between border-b border-line pb-2">
              <span className="flex items-center gap-1 text-warn-700">
                <span className="inline-block size-1.5 rounded-full bg-warn-600" aria-hidden />
                {t('盘中价')}
              </span>
              <span className="font-mono text-ink-800 tnum">
                {live.live_price.toLocaleString('ja-JP')}
                {live.live_change_pct != null && (
                  <span className={live.live_change_pct >= 0 ? 'ml-1 text-up-600' : 'ml-1 text-down-600'}>
                    {live.live_change_pct >= 0 ? '+' : ''}
                    {(live.live_change_pct * 100).toFixed(2)}%
                  </span>
                )}
              </span>
            </div>
          )}
          {/* 素点 → 減点 → 最終 を並べる。以前は減点だけ見えていて、
              それが順位に効いているのかが画面から読めなかった。 */}
          <div className="flex items-center justify-between">
            <span className="text-ink-400">{t('原始分')}</span>
            <span className="font-mono text-ink-800 tnum">
              {row.raw_ranking_score != null ? row.raw_ranking_score.toFixed(1) : '—'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-ink-400">{t('风险减分')}</span>
            <span className="font-mono text-warn-700 tnum">{row.risk_penalty !== null ? `−${row.risk_penalty}` : '—'}</span>
          </div>
          <div className="flex items-center justify-between border-t border-line pt-2">
            <span className="text-ink-500">{t('最终优先级')}</span>
            <span className="font-mono font-semibold text-ink-900 tnum">
              {(row.final_ranking_score ?? row.ranking_score) != null
                ? (row.final_ranking_score ?? row.ranking_score)!.toFixed(1)
                : '—'}
            </span>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
          <span className="text-micro text-ink-400">{t('20日均成交额')}</span>
          <span className="font-mono text-data-m text-ink-800 tnum">{fmtYenCompact(row.avg_turnover_20d)}</span>
        </div>
      </div>
    </div>
  );
}

function StructLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="shrink-0 text-ink-400">{label}</span>
      <span className="truncate text-right text-ink-700">{value}</span>
    </div>
  );
}
