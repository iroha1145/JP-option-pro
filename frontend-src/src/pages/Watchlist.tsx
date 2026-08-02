/**
 * §05 自选股 — 直接加删版（对标美版 Watchlist 交互）。
 * 工具行：表格/卡片切换 + 搜索添加（typeahead 建议）
 * 卡片：右上角悬浮 ×（触屏常驻）；表格：行内 ★/×。
 * 主体：owner 或访客账号（账号与美股版通用）；匿名显示登录引导。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { motion } from 'framer-motion';
import { stocksApi, watchlistApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { CodeCell, DataThrough } from '@/components/domain';
import Icon from '@/components/icons';
import { useAccess } from '@/hooks/useAccess';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';
import { fmtPrice, fmtYenCompact } from '@/lib/format';
import { ApiError } from '@/api/client';
import type { SearchResult, WatchlistItem } from '@/api/types';

export default function Watchlist() {
  const { canManageWatchlist, accountUsername, isOwner } = useAccess();
  const query = usePolling(() => watchlistApi.list(), 120_000);
  const [view, setView] = useState<'cards' | 'table'>('cards');
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const items = query.data?.items ?? [];
  const maxItems = query.data?.max_items ?? null;
  const anonymous =
    query.error instanceof ApiError && query.error.bizCode === 'account_login_required';

  const doRemove = async (code: string) => {
    setBusy(code);
    setNotice(null);
    try {
      await watchlistApi.remove(code);
      query.refresh({ force: true });
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : t('移除失败'));
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
        render: (row) => <span className="text-caption text-ink-500">{row.sector33_name ?? '—'}</span>,
      },
      {
        key: 'close',
        title: t('收盘'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.quote?.close ?? Number.NEGATIVE_INFINITY,
        render: (row) => <span className="font-mono text-body-s tnum">{fmtPrice(row.quote?.close)}</span>,
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
    if (canManageWatchlist) {
      base.push({
        key: 'actions',
        title: '',
        align: 'right',
        render: (row) => (
          <span className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              disabled={busy === row.canonical_code}
              title={t('标记重点')}
              className={cn(
                'rounded-md border border-line px-2 py-0.5 text-micro hover:bg-brand-50',
                row.marked_important ? 'text-warn-600' : 'text-ink-400',
              )}
              onClick={(event) => {
                event.stopPropagation();
                void doToggleStar(row);
              }}
            >
              ★
            </button>
            <button
              type="button"
              disabled={busy === row.canonical_code}
              title={t('从自选移除 {code}', { code: row.display_code })}
              aria-label={t('从自选移除 {code}', { code: row.display_code })}
              className="rounded-md border border-line px-2 py-0.5 text-micro text-down-700 hover:bg-down-50"
              onClick={(event) => {
                event.stopPropagation();
                void doRemove(row.canonical_code);
              }}
            >
              <Icon name="x" size={12} />
            </button>
          </span>
        ),
      });
    }
    return base;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManageWatchlist, busy]);

  return (
    <div className="space-y-6">
      <PageHeader
        section="05"
        eyebrow="WATCHLIST · PERSONAL"
        title={t('自选股')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <>
            {accountUsername && (
              <span className="hidden items-center gap-1.5 rounded-pill border border-line bg-card px-2.5 py-1 text-caption text-ink-600 sm:inline-flex">
                <Icon name="command" size={12} className="text-brand-600" />
                {accountUsername}
              </span>
            )}
            <DataThrough date={items.find((item) => item.quote?.trade_date)?.quote?.trade_date} />
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
              onAdded={() => {
                setNotice(null);
                query.refresh({ force: true });
              }}
              onError={setNotice}
            />
          )}
        </div>
        <p className="text-right text-caption text-ink-400">
          <span className="font-mono tnum">{items.length}</span> {t('只标的')}
          {maxItems !== null && <span className="ml-1 text-ink-300">{t('/ 上限')} {maxItems}</span>}
          {isOwner && <span className="ml-1 text-ink-300">· {t('所有者清单')}</span>}
        </p>
      </div>

      {notice && (
        <p className="rounded-md border border-warn-600/25 bg-warn-50 px-3 py-2 text-caption text-warn-600" role="status">
          {notice}
        </p>
      )}

      {anonymous ? (
        <EmptyState
          title={t('登录后可以把自选股保存在账号里')}
          description={t('账号与美股版通用，换设备也还在')}
          action={
            <Link
              to="/login"
              className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white transition-[filter] hover:brightness-105"
            >
              {t('去登录 / 注册')}
            </Link>
          }
        />
      ) : query.loading && !query.data ? (
        <SkeletonRows rows={8} />
      ) : query.error && !query.data ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(query.error?.message ?? '')} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t('清单还是空的')}
          description={canManageWatchlist ? t('在上方搜索代码或公司名，加入第一只自选') : t('在筛选器中添加')}
        />
      ) : view === 'table' ? (
        <DataTable columns={columns} rows={items} rowKey={(row) => row.canonical_code} rowHeight={44} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item, index) => (
            <WatchCard
              key={item.canonical_code}
              item={item}
              index={index}
              onRemove={canManageWatchlist ? () => void doRemove(item.canonical_code) : undefined}
              onToggleStar={canManageWatchlist ? () => void doToggleStar(item) : undefined}
            />
          ))}
        </div>
      )}
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
              <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-caption font-semibold text-brand-700">
                {result.display_code}
              </span>
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
  onRemove,
  onToggleStar,
}: {
  item: WatchlistItem;
  index: number;
  onRemove?: () => void;
  onToggleStar?: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay: Math.min(index * 0.04, 0.4) }}
      whileHover={{ y: -3, transition: { duration: 0.24, ease: 'easeOut' } }}
      className="group/card relative"
    >
      <Link
        to={`/stock/${item.display_code}`}
        className="card-surface flex w-full flex-col p-4 text-left transition-shadow duration-fast hover:shadow-sh-2"
      >
        <span className="flex items-center gap-2.5">
          {item.marked_important && <span className="shrink-0 text-warn-600">★</span>}
          <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
            {item.display_code}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-body-s text-ink-800">{item.name_ja ?? '—'}</span>
            <span className="block truncate text-micro text-ink-400">{item.sector33_name ?? '—'}</span>
          </span>
          <ChangeBadge value={item.quote?.change_pct} size="sm" />
        </span>
        <span className="mt-3 flex items-end justify-between">
          <span className="font-mono text-data-l text-ink-900 tnum">{fmtPrice(item.quote?.close)}</span>
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
          title={t('移出自选')}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="pointer-events-none absolute right-2 top-2 z-10 inline-flex size-6 cursor-pointer items-center justify-center rounded-xs text-ink-300 opacity-0 outline-none transition-[opacity,color] duration-fast hover:bg-paper-2 hover:text-down-700 focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover/card:pointer-events-auto group-hover/card:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:text-ink-400"
        >
          <Icon name="x" size={13} />
        </button>
      )}
      {onToggleStar && (
        <button
          type="button"
          aria-label={t('标记重点')}
          title={t('标记重点')}
          onClick={(event) => {
            event.stopPropagation();
            onToggleStar();
          }}
          className={cn(
            'pointer-events-none absolute right-9 top-2 z-10 inline-flex size-6 cursor-pointer items-center justify-center rounded-xs opacity-0 outline-none transition-[opacity,color] duration-fast hover:bg-paper-2 focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover/card:pointer-events-auto group-hover/card:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100',
            item.marked_important ? 'text-warn-600' : 'text-ink-300 hover:text-warn-600',
          )}
        >
          ★
        </button>
      )}
    </motion.div>
  );
}
