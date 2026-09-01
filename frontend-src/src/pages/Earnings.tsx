/**
 * §06 决算日历 — 对标美股版财报日历（earnings.md 形态，JST 口径）。
 * B0 页头带（三态计数 chips + 数据截至）
 * B1 JST 周历 scrubber ↔ 月历切换
 * B2 按日期分组列表（重点/全部 · 日过滤 · 渐进 24 · 未定折叠区）
 * B3 右栏：未来 35 天密度条 + 直近決算摘要 + 覆盖口径卡
 * 数据三态：released（实绩）/ confirmed（官方確定）/ estimated（目安，前年同期推导）。
 */
import { useCallback, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Link } from 'react-router';
import { earningsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import Segmented from '@/components/shared/Segmented';
import SourceNote from '@/components/shared/SourceNote';
import { SkeletonBlock, SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import { DataThrough } from '@/components/domain';
import Icon from '@/components/icons';
import WeekScrubber from '@/components/earnings/WeekScrubber';
import MonthCalendar from '@/components/earnings/MonthCalendar';
import EarningsList from '@/components/earnings/EarningsList';
import DensityStrip from '@/components/earnings/DensityStrip';
import {
  computeListState,
  fmtMDCN,
  jstToday,
  weekStartMonday,
  type ListMode,
} from '@/components/earnings/types';
import { cn } from '@/lib/utils';
import { fmtYenCompact } from '@/lib/format';
import { t } from '@/i18n/core';
import type { EarningsRecentItem } from '@/api/types';

const LIST_PAGE_SIZE = 24;
const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

export default function Earnings() {
  const q = usePolling(() => earningsApi.upcoming(), 1_800_000);
  const recentQ = usePolling(() => earningsApi.recent(7), 1_800_000);

  const [monday, setMonday] = useState(() => weekStartMonday(jstToday()));
  const [weekDir, setWeekDir] = useState(0);
  const [calView, setCalView] = useState<'week' | 'month'>('week');
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [listMode, setListMode] = useState<ListMode>('all');
  const [showTbd, setShowTbd] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(LIST_PAGE_SIZE);

  const items = useMemo(() => q.data?.items ?? [], [q.data]);
  const tbdItems = q.data?.tbd_items ?? [];
  const counts = q.data?.counts ?? null;

  const onWeekChange = useCallback((dir: -1 | 1) => {
    setWeekDir(dir);
    setMonday((current) => {
      const d = new Date(`${current}T12:00:00Z`);
      d.setUTCDate(d.getUTCDate() + dir * 7);
      return d.toISOString().slice(0, 10);
    });
  }, []);

  const onSelectDay = useCallback(
    (date: string | null) => {
      setSelectedDay(date);
      setVisibleLimit(LIST_PAGE_SIZE);
      if (date) {
        setWeekDir(date >= monday ? 1 : -1);
        setMonday(weekStartMonday(date));
      }
    },
    [monday],
  );

  const onJumpDay = useCallback(
    (date: string) => {
      setWeekDir(date >= monday ? 1 : -1);
      setMonday(weekStartMonday(date));
      setSelectedDay(date);
      setVisibleLimit(LIST_PAGE_SIZE);
    },
    [monday],
  );

  const onListModeChange = useCallback((mode: ListMode) => {
    setListMode(mode);
    setVisibleLimit(LIST_PAGE_SIZE);
  }, []);

  const listState = useMemo(
    () => computeListState({ items, selectedDay, mode: listMode, visibleLimit }),
    [items, selectedDay, listMode, visibleLimit],
  );

  const loading = q.loading && !q.data;
  const error503 = q.error && !q.data;

  return (
    <div>
      {/* B0 页头带 */}
      <PageHeader
        section="06"
        eyebrow="EARNINGS · DISCLOSURE CALENDAR"
        title={t('决算日历')}
        description={t('確定日来自官方发表预定，其余为前年同期推导的目安。')}
        meta={
          <>
            {counts && (
              <span className="hidden items-center gap-1.5 sm:flex">
                <CountChip label={t('已公布')} value={counts.released} className="bg-paper-2 text-ink-600" />
                <CountChip label={t('確定')} value={counts.confirmed} className="bg-brand-50 text-brand-700" />
                <CountChip label={t('目安')} value={counts.estimated} className="border border-dashed border-line-strong text-ink-500" />
              </span>
            )}
            <DataThrough date={q.data?.today} />
          </>
        }
      />

      {/* B1 周历 / 月历 */}
      <div className="mt-6">
        {loading ? (
          <div className="card-surface overflow-hidden" aria-label={t('周历加载中')}>
            <div className="flex h-11 items-center justify-center border-b border-line">
              <SkeletonBlock className="h-3 w-40" />
            </div>
            <div className="grid grid-cols-7">
              {Array.from({ length: 7 }, (_, i) => (
                <div key={i} className="min-h-[148px] space-y-2 border-r border-line p-2.5 last:border-r-0">
                  <SkeletonBlock className="h-3 w-8" />
                  <SkeletonBlock className="h-2.5 w-10" />
                  <SkeletonBlock className="h-5 w-full" />
                  <SkeletonBlock className="h-5 w-full" />
                </div>
              ))}
            </div>
          </div>
        ) : error503 ? (
          <section className="card-surface" aria-label={t('日历数据不可用')}>
            <EmptyState
              variant="error"
              title={t('日历数据不可用')}
              description={q.error?.message || t('稍后刷新再试')}
              action={
                <button
                  type="button"
                  onClick={() => q.refresh()}
                  className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white transition-[filter] hover:brightness-105"
                >
                  {t('重试')}
                </button>
              }
            />
          </section>
        ) : (
          <div>
            <div className="mb-3 flex items-center justify-between">
              <p className="eyebrow">EARNINGS CALENDAR · JST</p>
              <Segmented
                options={[
                  { value: 'week' as const, label: t('周') },
                  { value: 'month' as const, label: t('月') },
                ]}
                value={calView}
                onChange={setCalView}
              />
            </div>
            <AnimatePresence mode="wait" initial={false}>
              {calView === 'week' ? (
                <motion.div
                  key="week"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.32, ease: EASE_PAPER }}
                  className="overflow-hidden"
                >
                  <WeekScrubber
                    items={items}
                    monday={monday}
                    weekDir={weekDir}
                    onWeekChange={onWeekChange}
                    selectedDay={selectedDay}
                    onSelectDay={onSelectDay}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="month"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.32, ease: EASE_PAPER }}
                  className="overflow-hidden"
                >
                  <MonthCalendar items={items} selectedDay={selectedDay} onSelectDay={onSelectDay} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* B2 列表（8 列）· B3 右栏（4 列） */}
      <div className="mt-6 grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-12" aria-label={t('决算主体')}>
        <div className="min-w-0 space-y-4 xl:col-span-8">
          {loading ? (
            <div className="card-surface">
              <SkeletonRows rows={8} />
            </div>
          ) : error503 ? null : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Segmented
                  options={[
                    { value: 'featured' as const, label: `${t('重点公司')} ${listState.featuredCount}` },
                    { value: 'all' as const, label: `${t('全部公司')} ${listState.allCount}` },
                  ]}
                  value={listMode}
                  onChange={onListModeChange}
                />
                {selectedDay && (
                  <div className="flex items-center gap-2">
                    <p className="text-caption text-ink-500">
                      {t('已筛选')} <span className="font-mono text-brand-600">{fmtMDCN(selectedDay)}</span>
                    </p>
                    <button
                      type="button"
                      onClick={() => onSelectDay(null)}
                      className="flex items-center gap-1 rounded-sm border border-line bg-card px-2 py-1 text-caption text-ink-500 transition-colors hover:text-ink-800"
                    >
                      <Icon name="x" size={12} />
                      {t('清除筛选')}
                    </button>
                  </div>
                )}
              </div>

              <EarningsList
                items={listState.visibleItems}
                filteredByDay={selectedDay !== null}
                featuredFilteredEmpty={listMode === 'featured' && listState.allCount > 0 && listState.featuredCount === 0}
                onShowAll={() => onListModeChange('all')}
              />

              {listState.visibleItems.length < listState.listItems.length && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-card px-4 py-3">
                  <p className="text-caption text-ink-500">
                    {t('已显示')} <span className="font-mono text-ink-800 tnum">{listState.visibleItems.length}</span>
                    {' / '}
                    <span className="font-mono text-ink-800 tnum">{listState.listItems.length}</span> {t('件')}
                  </p>
                  <button
                    type="button"
                    onClick={() => setVisibleLimit((limit) => limit + LIST_PAGE_SIZE)}
                    className="h-8 rounded-md border border-line bg-card-warm px-3 text-caption text-ink-600 transition-colors hover:border-brand-400 hover:text-brand-600"
                  >
                    {t('显示更多 ·')} {Math.min(LIST_PAGE_SIZE, listState.listItems.length - listState.visibleItems.length)} {t('件')}
                  </button>
                </div>
              )}

              {/* 未定区（官方给了预定但日期未定） */}
              {tbdItems.length > 0 && (
                <div className="card-surface">
                  <button
                    type="button"
                    onClick={() => setShowTbd((v) => !v)}
                    aria-expanded={showTbd}
                    className="flex w-full items-center justify-between px-4 py-3"
                  >
                    <span className="text-body-s text-ink-700">
                      {t('日期未定')} <span className="font-mono text-caption text-ink-400 tnum">{tbdItems.length}</span>
                    </span>
                    <Icon name="chevron-down" size={14} className={cn('text-ink-400 transition-transform duration-200', showTbd && 'rotate-180')} />
                  </button>
                  {showTbd && (
                    <div className="flex flex-wrap gap-1.5 border-t border-line px-4 py-3">
                      {tbdItems.map((item) => (
                        <Link
                          key={item.canonical_code}
                          to={`/stock/${item.display_code}`}
                          className="rounded-sm bg-paper-2 px-2 py-1 font-mono text-caption text-ink-600 hover:bg-brand-50 hover:text-brand-700"
                        >
                          {item.display_code} {item.name_ja ?? ''}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* B3 右栏 */}
        <aside className="min-w-0 space-y-6 self-start xl:sticky xl:top-20 xl:col-span-4" aria-label={t('侧栏')}>
          {loading ? <SkeletonCard /> : !error503 && <DensityStrip items={items} onJumpDay={onJumpDay} />}
          <RecentPanel items={recentQ.data?.items ?? []} loading={recentQ.loading && !recentQ.data} />
          {q.data?.coverage_note && (
            <div className="card-surface p-5">
              <p className="eyebrow">{t('覆盖口径')}</p>
              <p className="mt-2.5 text-caption leading-[19px] text-ink-500">{t(q.data.coverage_note)}</p>
              <SourceNote className="mt-3" text={t('目安以公司正式公告为准，可能前后变动')} />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function CountChip({ label, value, className }: { label: string; value: number; className: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-micro', className)}>
      {label}
      <span className="font-mono tnum">{value}</span>
    </span>
  );
}

/* ---------------- 直近決算摘要（右栏） ---------------- */
function RecentPanel({ items, loading }: { items: EarningsRecentItem[]; loading: boolean }) {
  if (loading) return <SkeletonCard />;
  const shown = items.slice(0, 8);
  return (
    <section className="card-surface p-5" aria-label={t('最近决算')}>
      <p className="eyebrow">{t('最近决算 · 7 天')}</p>
      {shown.length === 0 ? (
        <p className="mt-3 text-caption text-ink-400">{t('暂无数据')}</p>
      ) : (
        <div className="mt-3 space-y-2.5">
          {shown.map((row) => (
            <Link
              key={`${row.canonical_code}-${row.disclosed_date}-${row.period_type}-${row.type_of_document}`}
              to={`/stock/${row.display_code}`}
              className="flex items-center gap-2 rounded-md px-1 py-0.5 transition-colors hover:bg-paper-2"
            >
              <span className="shrink-0 rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-caption font-semibold text-brand-700">
                {row.display_code}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-caption text-ink-700">{row.name_ja ?? '—'}</span>
                <span className="block truncate text-micro text-ink-400">
                  {row.disclosed_date?.slice(5)} · {row.period_type ?? '—'}
                  {row.is_forecast_revision ? ` · ${t('业绩预想修正')}` : ''}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block font-mono text-caption text-ink-800 tnum">{fmtYenCompact(row.operating_profit)}</span>
                {row.forecast_direction === 'upward' && (
                  <span className="inline-flex text-up-700" title={t('上方修正')} aria-label={t('上方修正')}>
                    <Icon name="arrow-up-right" size={12} />
                  </span>
                )}
                {row.forecast_direction === 'downward' && (
                  <span className="inline-flex text-down-700" title={t('下方修正')} aria-label={t('下方修正')}>
                    <Icon name="arrow-down-right" size={12} />
                  </span>
                )}
              </span>
            </Link>
          ))}
        </div>
      )}
      <SourceNote className="mt-3.5" text={t('金额为营业利益 · 修正箭头表示会社预想方向')} />
    </section>
  );
}
