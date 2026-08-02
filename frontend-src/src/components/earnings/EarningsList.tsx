/**
 * B2 决算列表 — 对标美版 EarningsList（按日期分组、今天高亮、行 stagger）。
 * 列：代码/名称·业种 · 种别+三态 · 前期実績→会社予想（斜纹柱对，円）· 修正方向
 *     · 收盘/涨跌 · 20日均额 · ★/雷达。行点击进个股页。<md 转卡片。
 * 数据纪律：目安行永远带「目安」样式；缺失显「—」不编造。
 */
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import { fmtPrice, fmtYenCompact } from '@/lib/format';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import type { EarningsUpcomingItem } from '@/api/types';
import { daysUntil, fmtMDCN, relativeDayCN, statusMeta, weekdayCN } from './types';
import { t } from '@/i18n/core';

/* ---------------- 迷你斜纹柱对（前期実績=斜纹 / 会社予想=实心；负值向下淡显） ---------------- */
function ForecastPairBars({
  prior,
  forecast,
  index,
}: {
  prior: number | null;
  forecast: number | null;
  index: number;
}) {
  const max = Math.max(Math.abs(prior ?? 0), Math.abs(forecast ?? 0), 1);
  const height = (value: number | null) => (value == null ? 0 : Math.max(6, (Math.abs(value) / max) * 26));
  return (
    <span className="flex h-7 w-11 items-end justify-center gap-1" aria-hidden="true">
      {prior != null && (
        <motion.span
          className={cn('w-2.5 rounded-t-[2px] border border-ink-300/70', prior < 0 && 'opacity-50')}
          style={{
            height: height(prior),
            backgroundImage: 'repeating-linear-gradient(45deg, rgba(138,148,176,.55) 0 1.2px, transparent 1.2px 4px)',
          }}
          initial={{ scaleY: 0 }}
          whileInView={{ scaleY: 1 }}
          viewport={{ once: true, amount: 0.5 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: Math.min(index * 0.04, 0.5) }}
        />
      )}
      {forecast != null && (
        <motion.span
          className={cn('w-2.5 origin-bottom rounded-t-[2px] bg-brand-600', forecast < 0 && 'opacity-50')}
          style={{ height: height(forecast) }}
          initial={{ scaleY: 0 }}
          whileInView={{ scaleY: 1 }}
          viewport={{ once: true, amount: 0.5 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: Math.min(index * 0.04, 0.5) + 0.08 }}
        />
      )}
    </span>
  );
}

function metricLabel(metric: string | undefined): string {
  return metric === 'net_profit' ? t('纯利益') : t('营业利益');
}

/* ---------------- 状态芯片 ---------------- */
export function StatusChip({ item }: { item: EarningsUpcomingItem }) {
  const meta = statusMeta(item.status);
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span className="whitespace-nowrap rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">
        {item.quarter_label ?? '—'}
      </span>
      <span
        className={cn('whitespace-nowrap rounded-sm px-1.5 py-0.5 text-micro', meta.chipClass)}
        title={item.status === 'estimated' ? t('前年同期开示日推导的目安，以公司正式公告为准') : undefined}
      >
        {meta.label}
      </span>
      {item.actual?.is_revision && (
        <span className="whitespace-nowrap rounded-sm bg-warn-50 px-1.5 py-0.5 text-micro text-warn-700">{t('业绩预想修正')}</span>
      )}
    </span>
  );
}

/* ---------------- 主组件 ---------------- */
interface EarningsListProps {
  items: EarningsUpcomingItem[];
  filteredByDay: boolean;
  featuredFilteredEmpty?: boolean;
  onShowAll?: () => void;
}

const GRID =
  'md:grid-cols-[minmax(150px,1.35fr)_minmax(112px,0.9fr)_minmax(168px,1.25fr)_100px_88px_56px] 2xl:grid-cols-[minmax(170px,1.35fr)_minmax(120px,0.9fr)_minmax(190px,1.25fr)_110px_96px_60px]';

export default function EarningsList({ items, filteredByDay, featuredFilteredEmpty = false, onShowAll }: EarningsListProps) {
  const navigate = useNavigate();

  if (items.length === 0) {
    return (
      <section className="card-surface" aria-label={t('决算列表')}>
        <EmptyState
          title={
            featuredFilteredEmpty
              ? filteredByDay ? t('当日没有重点公司决算') : t('当前范围内没有重点公司决算')
              : filteredByDay ? t('当日无决算安排') : t('窗口内暂无决算')
          }
          description={
            featuredFilteredEmpty
              ? t('切到「全部公司」查看全市场日历。')
              : t('选中的日期没有决算安排，切换日格试试。')
          }
          action={
            featuredFilteredEmpty && onShowAll ? (
              <button
                type="button"
                onClick={onShowAll}
                className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white transition-[filter] hover:brightness-105"
              >
                {t('查看全部公司')}
              </button>
            ) : undefined
          }
        />
      </section>
    );
  }

  const groups: { date: string; rows: EarningsUpcomingItem[] }[] = [];
  for (const item of items) {
    const date = item.date ?? '';
    const group = groups[groups.length - 1];
    if (group && group.date === date) group.rows.push(item);
    else groups.push({ date, rows: [item] });
  }

  let rowIndex = -1;

  return (
    <section
      className="card-surface overflow-hidden md:max-h-[min(72vh,880px)] md:overflow-y-auto md:overscroll-contain [scrollbar-gutter:stable]"
      aria-label={t('决算列表')}
    >
      {/* 桌面列头 */}
      <div className={cn('sticky top-0 z-20 hidden border-b border-line bg-card-warm px-4 py-2.5 md:grid md:gap-3', GRID)}>
        <span className="eyebrow">{t('代码')}</span>
        <span className="eyebrow">{t('种别 · 状态')}</span>
        <span className="eyebrow">{t('前期実績 vs 会社予想')}</span>
        <span className="eyebrow text-right">{t('收盘 / 涨跌')}</span>
        <span className="eyebrow text-right">{t('20日均额')}</span>
        <span className="eyebrow text-right">★</span>
      </div>

      {groups.map((group) => {
        const du = group.date ? daysUntil(group.date) : 99;
        const isToday = du === 0;
        return (
          <div key={group.date || 'tbd'}>
            <div
              className={cn(
                'flex items-baseline justify-between border-b border-line px-4 py-2.5',
                isToday ? 'bg-brand-50' : 'bg-card-warm/60',
              )}
            >
              <p className="flex items-baseline gap-2.5">
                <span className={cn('font-display text-[15px] leading-6', isToday ? 'text-brand-700' : 'text-ink-800')}>
                  {group.date ? `${fmtMDCN(group.date)} · ${weekdayCN(group.date)}` : t('日期未定')}
                </span>
                {isToday && (
                  <span className="rounded-xs bg-brand-600 px-1.5 py-px text-[10px] font-semibold leading-4 text-white">{t('今天')}</span>
                )}
              </p>
              <p className="font-mono text-micro text-ink-400 tnum">
                {group.date ? `${relativeDayCN(group.date)} · ` : ''}{group.rows.length} {t('件')}
              </p>
            </div>

            {group.rows.map((row) => {
              rowIndex += 1;
              const index = rowIndex;
              const forecast = row.forecast;
              const priorValue = forecast?.prior_fy_value ?? null;
              const forecastValue = forecast?.forecast_value ?? null;
              const released = row.actual;
              const open = () => navigate(`/stock/${row.display_code}`);
              return (
                <div key={`${row.canonical_code}-${row.period_type}-${row.date}`}>
                  {/* 桌面行 */}
                  <motion.div
                    role="button"
                    tabIndex={0}
                    onClick={open}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        open();
                      }
                    }}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay: Math.min(index * 0.035, 0.5) }}
                    className={cn(
                      'hidden cursor-pointer items-center border-b border-line px-4 py-2.5 transition-colors duration-fast last:border-b-0 md:grid md:gap-3',
                      GRID,
                      'hover:bg-paper-2',
                      row.status === 'estimated' && 'opacity-[0.92]',
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="shrink-0 rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
                        {row.display_code}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-body-s text-ink-800">{row.name_ja ?? '—'}</span>
                        <span className="block truncate text-micro text-ink-400">{row.sector33_name ?? '—'}</span>
                      </span>
                    </span>
                    <StatusChip item={row} />
                    {/* 已公布行显示实绩；否则显示 前期実績 vs 会社予想 */}
                    {released ? (
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="min-w-0 font-mono text-caption tnum">
                          <span className="block truncate">
                            <span className="text-ink-400">{t('营利')}</span>{' '}
                            <span className="font-semibold text-ink-900">{fmtYenCompact(released.operating_profit)}</span>
                          </span>
                          <span className="block truncate text-micro text-ink-500">
                            {t('销售')} {fmtYenCompact(released.sales)} · {t('纯利')} {fmtYenCompact(released.net_profit)}
                          </span>
                        </span>
                      </span>
                    ) : (
                      <span className="flex min-w-0 items-center gap-2">
                        <ForecastPairBars prior={priorValue} forecast={forecastValue} index={index} />
                        <span className="min-w-0 font-mono text-caption tnum">
                          <span className="block truncate">
                            <span className="text-ink-500">{priorValue != null ? fmtYenCompact(priorValue) : '—'}</span>
                            <span className="mx-1 text-ink-300">→</span>
                            <span className={forecastValue != null ? 'font-semibold text-ink-900' : 'text-ink-300'}>
                              {forecastValue != null ? fmtYenCompact(forecastValue) : '—'}
                            </span>
                          </span>
                          <span className="block flex items-center gap-1 truncate text-micro text-ink-400">
                            {forecast ? metricLabel(forecast.metric) : t('营业利益')}
                            {forecast?.direction === 'upward' && <span className="text-up-700">{t('上方修正')}</span>}
                            {forecast?.direction === 'downward' && <span className="text-down-700">{t('下方修正')}</span>}
                          </span>
                        </span>
                      </span>
                    )}
                    <span className="text-right">
                      <span className="block font-mono text-body-s text-ink-900 tnum">{fmtPrice(row.close)}</span>
                      <ChangeBadge value={row.change_pct !== null ? row.change_pct / 100 : null} size="sm" />
                    </span>
                    <span className="text-right font-mono text-caption text-ink-600 tnum">{fmtYenCompact(row.avg_turnover_20d)}</span>
                    <span className="text-right">
                      {row.in_watchlist && <span className="text-warn-600">★</span>}
                      {row.radar_state && <span className="ml-1 inline-block size-1.5 rounded-full bg-brand-600 align-middle" title={t('雷达信号')} />}
                    </span>
                  </motion.div>

                  {/* 移动卡片 */}
                  <motion.button
                    type="button"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay: Math.min(index * 0.035, 0.5) }}
                    onClick={open}
                    className="block w-full border-b border-line px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-paper-2 md:hidden"
                  >
                    <span className="flex items-center gap-2">
                      <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
                        {row.display_code}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body-s text-ink-800">{row.name_ja ?? '—'}</span>
                        <span className="block truncate text-micro text-ink-400">{row.sector33_name ?? '—'}</span>
                      </span>
                      <ChangeBadge value={row.change_pct !== null ? row.change_pct / 100 : null} size="sm" />
                    </span>
                    <span className="mt-2 flex items-center justify-between gap-2">
                      <StatusChip item={row} />
                      <span className="font-mono text-micro text-ink-500 tnum">
                        {released
                          ? `${t('营利')} ${fmtYenCompact(released.operating_profit)}`
                          : forecastValue != null
                            ? `${metricLabel(forecast?.metric)} ${fmtYenCompact(forecastValue)}`
                            : '—'}
                      </span>
                    </span>
                  </motion.button>
                </div>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}
