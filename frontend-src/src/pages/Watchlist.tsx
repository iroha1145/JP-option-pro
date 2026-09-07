/**
 * §05 自选股 — 直接加删版（对标美版 Watchlist 交互）。
 * 工具行：表格/卡片切换 + 搜索添加（typeahead 建议）
 * 卡片：右上角悬浮 ×（触屏常驻）；表格：行内 ★/×。
 * 主体：owner 或访客账号（账号与美股版通用）；匿名显示登录引导。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { motion } from 'framer-motion';
import { stocksApi, watchlistApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard, SkeletonReveal, SkeletonRows } from '@/components/shared/Skeleton';
import StatCard from '@/components/shared/StatCard';
import HorizontalScroller from '@/components/shared/HorizontalScroller';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import SessionLED from '@/components/shared/SessionLED';
import MenuSelect from '@/components/shared/MenuSelect';
import AdvanceDeclineBar from '@/components/shared/AdvanceDeclineBar';
import SourceNote from '@/components/shared/SourceNote';
import { CodeCell, DataThrough } from '@/components/domain';
import Icon from '@/components/icons';
import { useAccess } from '@/hooks/useAccess';
import { useNow } from '@/hooks/useNow';
import { useTickFlash } from '@/hooks/useTickFlash';
import { useToast } from '@/hooks/useToast';
import { tokyoSession } from '@/lib/tokyoSession';
import TickPrice from '@/components/shared/TickPrice';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import CodeMark from '@/components/shared/CodeMark';
import PointerTooltip from '@/components/shared/PointerTooltip';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';
import { fmtPrice, fmtTimeHHMMSS, fmtYenCompact } from '@/lib/format';
import { EASE_PAPER } from '@/lib/motion';
import { ApiError } from '@/api/client';
import type { SearchResult, WatchlistItem } from '@/api/types';

const EMPTY_WATCHLIST: WatchlistItem[] = [];

const STAT_ENTER = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE_PAPER } },
};

type WatchSortId = 'default' | 'gain' | 'loss' | 'turnover' | 'code';

const WATCH_SORTS: { id: WatchSortId; label: string }[] = [
  { id: 'default', label: t('默认排序') },
  { id: 'gain', label: t('涨幅优先') },
  { id: 'loss', label: t('跌幅优先') },
  { id: 'turnover', label: t('成交额优先') },
  { id: 'code', label: t('按代码 A–Z') },
];

function sortWatchlist(items: WatchlistItem[], sortId: WatchSortId): WatchlistItem[] {
  if (sortId === 'default') return items;
  const out = [...items];
  const pct = (item: WatchlistItem) => item.quote?.change_pct ?? Number.NEGATIVE_INFINITY;
  const turnover = (item: WatchlistItem) => item.quote?.turnover_value ?? Number.NEGATIVE_INFINITY;
  if (sortId === 'gain') out.sort((a, b) => pct(b) - pct(a) || a.canonical_code.localeCompare(b.canonical_code));
  if (sortId === 'loss') out.sort((a, b) => pct(a) - pct(b) || a.canonical_code.localeCompare(b.canonical_code));
  if (sortId === 'turnover') {
    out.sort((a, b) => turnover(b) - turnover(a) || a.canonical_code.localeCompare(b.canonical_code));
  }
  if (sortId === 'code') out.sort((a, b) => a.display_code.localeCompare(b.display_code));
  return out;
}

export default function Watchlist() {
  const navigate = useNavigate();
  const { canManageWatchlist, accountUsername, isOwner } = useAccess();
  const toast = useToast();
  const now = useNow(30_000);
  const session = tokyoSession(now);
  const [searchParams, setSearchParams] = useSearchParams();
  const query = usePolling(() => watchlistApi.list(), 120_000);
  const refreshWatchlist = query.refresh;
  const [view, setView] = useState<'cards' | 'table'>('cards');
  const [sortId, setSortId] = useState<WatchSortId>('default');
  const [busy, setBusy] = useState<string | null>(null);

  const onForceRefresh = useCallback(() => {
    refreshWatchlist({ force: true });
  }, [refreshWatchlist]);

  useEffect(() => {
    if (searchParams.get('force') !== '1') return;
    onForceRefresh();
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('force');
        return next;
      },
      { replace: true },
    );
  }, [onForceRefresh, searchParams, setSearchParams]);

  const items = useMemo(
    () => sortWatchlist(query.data?.items ?? EMPTY_WATCHLIST, sortId),
    [query.data?.items, sortId],
  );
  const breadth = useMemo(() => {
    let advancers = 0;
    let decliners = 0;
    let unchanged = 0;
    for (const item of items) {
      const pct = item.quote?.change_pct;
      if (pct == null || !Number.isFinite(pct)) continue;
      if (pct > 0) advancers += 1;
      else if (pct < 0) decliners += 1;
      else unchanged += 1;
    }
    return { advancers, decliners, unchanged };
  }, [items]);
  const flashes = useTickFlash(items, (row) => row.canonical_code, (row) => row.quote?.close ?? null);
  const maxItems = query.data?.max_items ?? null;
  const anonymous =
    query.error instanceof ApiError && query.error.bizCode === 'account_login_required';

  const doRemove = async (code: string) => {
    setBusy(code);
    try {
      await watchlistApi.remove(code);
      query.refresh({ force: true });
    } catch (error) {
      toast.error(t('移除失败'), error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const doToggleStar = async (row: WatchlistItem) => {
    setBusy(row.canonical_code);
    try {
      await watchlistApi.update(row.canonical_code, { marked_important: !row.marked_important });
      query.refresh({ force: true });
    } finally {
      setBusy(null);
    }
  };

  const columns = useMemo<Column<WatchlistItem>[]>(() => {
    const base: Column<WatchlistItem>[] = [
      {
        key: 'code',
        title: t('代码'),
        width: '30%',
        render: (row) => (
          <span className="flex items-center gap-1.5">
            {row.marked_important && <span className="text-warn-600">★</span>}
            <CodeCell displayCode={row.display_code} nameJa={row.name_ja} to={`/stock/${row.display_code}`} />
          </span>
        ),
      },
      {
        key: 'sector',
        title: t('行业'),
        render: (row) =>
          row.sector33_name ? (
            <PointerTooltip
              passthrough
              label={row.sector33_name}
              content={<span className="text-micro leading-[16px] text-ink-600">{row.sector33_name}</span>}
            >
              <SoftBadge className="max-w-[7.5rem]">
                <span className="truncate">{row.sector33_name}</span>
              </SoftBadge>
            </PointerTooltip>
          ) : (
            <span className="text-caption text-ink-400">—</span>
          ),
      },
      {
        key: 'close',
        title: t('收盘'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.close ?? Number.NEGATIVE_INFINITY,
        render: (row) => (
          <TickPrice flash={flashes[row.canonical_code]} className="font-mono text-[15px] leading-6 text-ink-900">
            {fmtPrice(row.quote?.close)}
          </TickPrice>
        ),
      },
      {
        key: 'change',
        title: t('涨跌'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.change_pct ?? Number.NEGATIVE_INFINITY,
        render: (row) => <ChangeBadge value={row.quote?.change_pct} size="sm" />,
      },
      {
        key: 'turnover',
        title: t('成交额'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.turnover_value ?? -1,
        render: (row) => (
          <span className="font-mono text-body-s tnum text-ink-600">{fmtYenCompact(row.quote?.turnover_value)}</span>
        ),
      },
      {
        key: 'note',
        title: t('备注'),
        render: (row) => <span className="truncate text-caption text-ink-500">{row.note ?? '—'}</span>,
      },
    ];
    base.push({
      key: 'actions',
      title: '',
      align: 'right',
      render: (row) => (
        <span className="flex items-center justify-end gap-1.5">
          {canManageWatchlist && (
            <>
              <PointerTooltip
                passthrough
                label={t('标记重点')}
                content={<span className="text-micro leading-[16px] text-ink-600">{t('标记重点')}</span>}
              >
                <button
                  type="button"
                  disabled={busy === row.canonical_code}
                  aria-label={t('标记重点')}
                  className={cn(
                    'rounded-md border border-line px-2 py-0.5 text-micro shadow-btn opacity-0 transition-[opacity,color] duration-fast hover:bg-brand-50 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100',
                    row.marked_important ? 'text-warn-600' : 'text-ink-400',
                  )}
                  onClick={(event) => {
                    event.stopPropagation();
                    void doToggleStar(row);
                  }}
                >
                  ★
                </button>
              </PointerTooltip>
              <PointerTooltip
                passthrough
                label={t('从自选移除 {code}', { code: row.display_code })}
                content={<span className="text-micro leading-[16px] text-ink-600">{t('移出自选')}</span>}
              >
                <button
                  type="button"
                  disabled={busy === row.canonical_code}
                  aria-label={t('从自选移除 {code}', { code: row.display_code })}
                  className="rounded-md border border-line px-2 py-0.5 text-micro text-down-700 shadow-btn opacity-0 transition-[opacity,color] duration-fast hover:bg-down-50 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                  onClick={(event) => {
                    event.stopPropagation();
                    void doRemove(row.canonical_code);
                  }}
                >
                  <Icon name="x" size={12} />
                </button>
              </PointerTooltip>
            </>
          )}
          <span className="inline-flex size-7 items-center justify-center rounded-sm border border-line bg-card text-ink-400 opacity-0 transition-opacity duration-fast group-hover:opacity-100 [@media(hover:none)]:opacity-100">
            <Icon name="arrow-up-right" size={14} />
          </span>
        </span>
      ),
    });
    return base;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManageWatchlist, busy, flashes]);

  return (
    <div className="space-y-6">
      <PageHeader
        section="02"
        eyebrow="WATCHLIST · PERSONAL"
        title={t('自选股')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <>
            {accountUsername && (
              <span className="hidden items-center gap-1.5 rounded-pill border border-line-strong bg-card px-2.5 py-1 text-caption text-ink-600 sm:inline-flex">
                <Icon name="command" size={12} className="text-brand-600" />
                {accountUsername}
              </span>
            )}
            <SessionLED session={session} />
            <DataThrough date={items.find((item) => item.quote?.trade_date)?.quote?.trade_date} />
            <ForceRefreshButton
              onClick={onForceRefresh}
              spinning={query.refreshing}
              title={t('重新获取自选行情')}
            />
          </>
        }
      />

      {/* 工具行：视图切换 + 添加表单 + 计数 */}
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-line py-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <Segmented
            options={[
              { value: 'cards' as const, label: t('卡片') },
              { value: 'table' as const, label: t('表格') },
            ]}
            value={view}
            onChange={setView}
          />
          {canManageWatchlist && (
            <AddStockForm
              onAdded={() => query.refresh({ force: true })}
              onError={(message) => toast.error(t('添加失败'), message)}
            />
          )}
          <MenuSelect<WatchSortId>
            value={sortId}
            onChange={setSortId}
            options={WATCH_SORTS.map((option) => ({ value: option.id, label: option.label }))}
            ariaLabel={t('默认排序')}
            align="right"
            leading={<Icon name="filter-funnel" size={13} />}
            triggerClassName="px-2.5 text-ink-500 hover:text-ink-800"
          />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {query.lastUpdatedAt && (
            <span className="font-mono text-caption text-ink-400 tnum">
              {t('更新')} {fmtTimeHHMMSS(query.lastUpdatedAt)}
            </span>
          )}
          <p className="text-right text-caption text-ink-400">
            <span className="font-mono tnum">{items.length}</span> {t('只标的')}
            {maxItems !== null && <span className="ml-1 text-ink-300">{t('/ 上限')} {maxItems}</span>}
            {isOwner && <span className="ml-1 text-ink-300">· {t('所有者清单')}</span>}
          </p>
        </div>
      </div>

      {query.error && query.data && (
        <StaleStrip onRetry={() => query.refresh()} refreshing={query.refreshing} />
      )}

      {query.loading && !query.data && (
        <HorizontalScroller className="-mx-1 sm:mx-0" scrollerClassName="px-1 sm:px-0" label={t('自选统计')}>
          <div className="flex gap-3 sm:grid sm:grid-cols-3">
            <SkeletonCard className="min-w-[240px] sm:min-w-0" />
            <SkeletonCard className="min-w-[240px] sm:min-w-0" />
            <SkeletonCard className="min-w-[240px] sm:min-w-0" />
          </div>
        </HorizontalScroller>
      )}

      {items.length > 0 && (
        <HorizontalScroller className="-mx-1 sm:mx-0" scrollerClassName="px-1 sm:px-0" label={t('自选统计')}>
          <motion.div
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.045 } } }}
            className="flex gap-3 sm:grid sm:grid-cols-3"
          >
            <motion.div variants={STAT_ENTER} className="min-w-[240px] snap-start sm:min-w-0">
              <StatCard label={t('只标的')} icon="list" value={items.length} />
            </motion.div>
            <motion.div variants={STAT_ENTER} className="min-w-[240px] snap-start sm:min-w-0">
              <div className="card-surface metric-card p-5">
                <div className="flex items-start justify-between">
                  <p className="eyebrow">{t('上涨 / 下跌')}</p>
                  <Icon name="candle" size={18} className="text-ink-400" />
                </div>
                <AdvanceDeclineBar
                  advancers={breadth.advancers}
                  decliners={breadth.decliners}
                  unchanged={breadth.unchanged}
                />
              </div>
            </motion.div>
            <motion.div variants={STAT_ENTER} className="min-w-[240px] snap-start sm:min-w-0">
              <StatCard
                label={t('重点标记')}
                icon="flag"
                value={items.filter((item) => item.marked_important).length}
              />
            </motion.div>
          </motion.div>
        </HorizontalScroller>
      )}

      {anonymous ? (
        <section className="card-surface">
          <EmptyState
            image="/empty-watchlist.svg"
            title={t('登录后可以把自选股保存在账号里')}
            description={t('账号与美股版通用，换设备也还在')}
            action={
              <Link
                to="/login"
                className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white shadow-btn-hi transition-[filter] hover:brightness-105"
              >
                {t('去登录 / 注册')}
              </Link>
            }
          />
        </section>
      ) : (
        <div className="min-h-[70vh]">
          <SkeletonReveal
            loading={query.loading && !query.data}
            skeleton={
              <section className="card-surface">
                <SkeletonRows rows={8} />
              </section>
            }
          >
            {query.error && !query.data ? (
              <section className="card-surface">
                <EmptyState
                  variant="error"
                  image="/empty-chart.svg"
                  title={t('加载失败')}
                  description={String(query.error?.message ?? '')}
                  action={
                    <button type="button" onClick={() => query.refresh({ force: true })} className="btn-primary">
                      {t('重试')}
                    </button>
                  }
                />
              </section>
            ) : items.length === 0 ? (
              <section className="card-surface">
                <EmptyState
                  image="/empty-watchlist.svg"
                  title={t('清单还是空的')}
                  description={canManageWatchlist ? t('在上方搜索代码或公司名，加入第一只自选') : t('在筛选器中添加')}
                />
              </section>
            ) : view === 'table' ? (
              <>
                <div className="hidden md:block">
                  <DataTable
                    columns={columns}
                    rows={items}
                    rowKey={(row) => row.canonical_code}
                    rowHeight={44}
                    onRowClick={(row) => navigate(`/stock/${row.display_code}`)}
                  />
                </div>
                <div className="grid grid-cols-1 gap-4 md:hidden">
                  {items.map((item, index) => (
                    <WatchCard
                      key={item.canonical_code}
                      item={item}
                      index={index}
                      flash={flashes[item.canonical_code]}
                      animateIn={index < 9}
                      onRemove={canManageWatchlist ? () => void doRemove(item.canonical_code) : undefined}
                      onToggleStar={canManageWatchlist ? () => void doToggleStar(item) : undefined}
                    />
                  ))}
                </div>
              </>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {items.map((item, index) => (
                  <WatchCard
                    key={item.canonical_code}
                    item={item}
                    index={index}
                    flash={flashes[item.canonical_code]}
                    animateIn={index < 9}
                    onRemove={canManageWatchlist ? () => void doRemove(item.canonical_code) : undefined}
                    onToggleStar={canManageWatchlist ? () => void doToggleStar(item) : undefined}
                  />
                ))}
              </div>
            )}
          </SkeletonReveal>
        </div>
      )}
      <SourceNote className="mt-8" text={t('本页为日线数据，收盘后更新 · 仅供研究参考，不构成投资建议')} />
    </div>
  );
}

/* ---------------- 搜索添加（typeahead） ---------------- */

function AddStockForm({ onAdded, onError }: { onAdded: () => void; onError: (message: string) => void }) {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    const keyword = input.trim();
    if (keyword.length < 2) {
      setSuggestions([]);
      return;
    }
    const seq = ++seqRef.current;
    const timer = window.setTimeout(() => {
      stocksApi
        .search(keyword)
        .then((data) => {
          if (seqRef.current === seq) {
            setSuggestions(data.results.slice(0, 6));
            setOpen(true);
          }
        })
        .catch(() => {
          if (seqRef.current === seq) setSuggestions([]);
        });
    }, 220);
    return () => window.clearTimeout(timer);
  }, [input]);

  useEffect(() => {
    const onDoc = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  const add = async (code: string) => {
    if (!code || saving) return;
    setSaving(true);
    try {
      await watchlistApi.add(code);
      setInput('');
      setSuggestions([]);
      setOpen(false);
      onAdded();
    } catch (error) {
      onError(error instanceof ApiError ? error.message : t('加入失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div ref={boxRef} className="relative">
      <form
        className="flex items-center gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          void add(input.trim());
        }}
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          placeholder={t('代码或公司名')}
          maxLength={24}
          aria-label={t('添加自选股票')}
          className="h-8 w-[150px] rounded-sm border border-line-strong bg-card px-2 font-mono text-caption text-ink-800 outline-none transition-[border-color] duration-fast placeholder:font-sans placeholder:text-ink-300 focus:border-brand-600"
        />
        <button
          type="submit"
          disabled={saving || !input.trim()}
          className="flex h-8 items-center gap-1 rounded-sm border border-line-strong bg-card px-2.5 text-caption text-ink-600 transition-colors duration-fast hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Icon name="plus" size={13} />
          {t('添加')}
        </button>
      </form>
      {open && suggestions.length > 0 && (
        <div className="absolute left-0 top-9 z-30 w-72 overflow-hidden rounded-md border border-line bg-card shadow-sh-2">
          {suggestions.map((result) => (
            <button
              key={result.canonical_code}
              type="button"
              onClick={() => void add(result.canonical_code)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-brand-50"
            >
              <CodeMark code={result.display_code} size={22} />
              <span className="font-mono text-caption font-semibold text-brand-700">{result.display_code}</span>
              <span className="min-w-0 flex-1 truncate text-caption text-ink-700">{result.name_ja ?? result.name_en ?? '—'}</span>
              <span className="shrink-0 text-micro text-ink-400">{result.sector33_name ?? ''}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- 卡片（悬浮 × 删除；触屏常驻） ---------------- */

function WatchCard({
  item,
  index,
  flash,
  onRemove,
  onToggleStar,
  animateIn,
}: {
  item: WatchlistItem;
  index: number;
  flash?: 'up' | 'down';
  onRemove?: () => void;
  onToggleStar?: () => void;
  animateIn: boolean;
}) {
  return (
    <motion.div
      initial={animateIn ? { opacity: 0, y: 14 } : false}
      animate={animateIn ? { opacity: 1, y: 0 } : undefined}
      transition={
        animateIn
          ? { duration: 0.48, ease: EASE_PAPER, delay: Math.min(index * 0.04, 0.4) }
          : undefined
      }
      className="group/card relative"
    >
      <Link
        to={`/stock/${item.display_code}`}
        className="card-surface card-lift flex w-full flex-col p-4 pr-24 text-left"
      >
        <span className="flex items-center gap-2.5">
          {item.marked_important && <span className="shrink-0 text-warn-600">★</span>}
          <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
            {item.display_code}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-body-s text-ink-800">{item.name_ja ?? '—'}</span>
            {item.sector33_name ? (
              <PointerTooltip
                passthrough
                label={item.sector33_name}
                content={<span className="text-micro leading-[16px] text-ink-600">{item.sector33_name}</span>}
              >
                <SoftBadge className="mt-0.5 max-w-[8rem]">
                  <span className="truncate">{item.sector33_name}</span>
                </SoftBadge>
              </PointerTooltip>
            ) : (
              <span className="block truncate text-micro text-ink-400">—</span>
            )}
          </span>
          <ChangeBadge value={item.quote?.change_pct} size="sm" />
        </span>
        <span className="mt-3 flex items-end justify-between">
          <TickPrice flash={flash} className="font-mono text-data-l text-ink-900">
            {fmtPrice(item.quote?.close)}
          </TickPrice>
          <span className="font-mono text-caption text-ink-500 tnum">{fmtYenCompact(item.quote?.turnover_value)}</span>
        </span>
        {item.note && (
          <span className="mt-2 block truncate border-t border-line pt-2 text-caption text-ink-500">{item.note}</span>
        )}
      </Link>
      {/* 删除键是卡片链接的兄弟节点：读屏语义独立，误触不进详情页 */}
      {onRemove && (
        <button
          type="button"
          aria-label={t('从自选移除 {code}', { code: item.display_code })}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="pointer-events-none absolute right-1 top-1 z-10 inline-flex size-11 cursor-pointer items-center justify-center rounded-xs text-ink-300 opacity-0 outline-none transition-[opacity,color] duration-fast hover:bg-paper-2 hover:text-down-700 focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover/card:pointer-events-auto group-hover/card:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:text-ink-400"
        >
          <Icon name="x" size={13} />
        </button>
      )}
      {onToggleStar && (
        <button
          type="button"
          aria-label={t('标记重点')}
          onClick={(event) => {
            event.stopPropagation();
            onToggleStar();
          }}
          className={cn(
            'pointer-events-none absolute right-12 top-1 z-10 inline-flex size-11 cursor-pointer items-center justify-center rounded-xs opacity-0 outline-none transition-[opacity,color] duration-fast hover:bg-paper-2 focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover/card:pointer-events-auto group-hover/card:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100',
            item.marked_important ? 'text-warn-600' : 'text-ink-300 hover:text-warn-600',
          )}
        >
          ★
        </button>
      )}
    </motion.div>
  );
}
