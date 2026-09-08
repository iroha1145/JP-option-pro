/**
 * 雷达右栏「历史事件回溯」：JST 日分组 + 生命周期色点 + 客户端分页。
 * 行点击：事件仍在当前集则提升为 Lead，否则打开个股页。不编造 transitions。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import { radarApi } from '@/api/modules';
import { RADAR_STATE_LABELS } from '@/components/domain';
import EmptyState from '@/components/shared/EmptyState';
import DotsLoader from '@/components/shared/DotsLoader';
import { usePrefersReducedMotion } from '@/hooks/usePrefersReducedMotion';
import { getLocale, t } from '@/i18n/core';
import { fmtDateShort, fmtPrice } from '@/lib/format';
import { EASE_PAPER } from '@/lib/motion';
import { cn } from '@/lib/utils';
import type { RadarEvent } from '@/api/types';

const PAGE = 12;
const WEEKDAYS = [t('周日'), t('周一'), t('周二'), t('周三'), t('周四'), t('周五'), t('周六')];

type HistoryTone = 'brand' | 'up' | 'down' | 'ink' | 'warn';

const STATE_TONE: Record<string, HistoryTone> = {
  discovered: 'brand',
  watching: 'brand',
  triggered: 'warn',
  confirmed: 'up',
  holding: 'up',
  retesting: 'warn',
  retest_held: 'up',
  reaccelerating: 'up',
  extended: 'warn',
  failed: 'down',
  expired: 'ink',
};

const TONE_DOT: Record<HistoryTone, string> = {
  brand: 'bg-brand-600',
  up: 'bg-up-600',
  down: 'bg-down-600',
  ink: 'bg-ink-400',
  warn: 'bg-warn-600',
};

const TONE_TEXT: Record<HistoryTone, string> = {
  brand: 'text-brand-600',
  up: 'text-up-700',
  down: 'text-down-700',
  ink: 'text-ink-500',
  warn: 'text-warn-700',
};

const TONE_CHIP: Record<HistoryTone, string> = {
  brand: 'radar-chip-brand',
  up: 'radar-chip-up',
  down: 'radar-chip-down',
  ink: 'radar-chip-neutral',
  warn: 'radar-chip-volume',
};

interface HistoryRow {
  key: string;
  eventId: string;
  date: string;
  code: string;
  name: string | null | undefined;
  from: string | null;
  to: string;
  close: number | null;
}

function historyDayLabel(isoDate: string): string {
  const key = isoDate.slice(0, 10);
  const parsed = new Date(`${key}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return key;
  const week = WEEKDAYS[parsed.getUTCDay()] ?? '';
  const locale = getLocale();
  if (locale === 'en') return `${parsed.getUTCMonth() + 1}/${parsed.getUTCDate()} ${week} · JST`;
  if (locale === 'ja') return `${parsed.getUTCMonth() + 1}月${parsed.getUTCDate()}日（${week}）· JST`;
  return `${parsed.getUTCMonth() + 1} 月 ${parsed.getUTCDate()} 日 ${week}`;
}

function snapshotClose(event: RadarEvent): number | null {
  const value = event.snapshot.close;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function collectRows(events: RadarEvent[]): HistoryRow[] {
  const items: HistoryRow[] = [];
  for (const event of events) {
    for (const transition of event.transitions ?? []) {
      items.push({
        key: `${event.event_id}-${transition.date}-${transition.to}`,
        eventId: event.event_id,
        date: transition.date,
        code: event.display_code,
        name: event.name_ja,
        from: transition.from,
        to: transition.to,
        close: snapshotClose(event),
      });
    }
  }
  return items.sort((a, b) => b.date.localeCompare(a.date));
}

export default function HistoryRail({
  events,
  filterKey,
  onPromoteLead,
}: {
  events: RadarEvent[];
  filterKey: string;
  onPromoteLead?: (eventId: string) => void;
}) {
  const navigate = useNavigate();
  const reducedMotion = usePrefersReducedMotion();
  const [visible, setVisible] = useState(PAGE);
  const [loadingMore, setLoadingMore] = useState(false);
  const moreTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventIds = useMemo(() => new Set(events.map((event) => event.event_id)), [events]);
  const idKey = useMemo(() => events.map((event) => event.event_id).join(','), [events]);
  const [historyState, setHistoryState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [detailed, setDetailed] = useState<RadarEvent[]>([]);

  useEffect(
    () => () => {
      if (moreTimer.current) window.clearTimeout(moreTimer.current);
    },
    [],
  );

  const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
  if (prevFilterKey !== filterKey) {
    setPrevFilterKey(filterKey);
    setVisible(PAGE);
  }

  useEffect(() => {
    const ids = idKey ? idKey.split(',').slice(0, 30) : [];
    if (ids.length === 0) {
      setDetailed([]);
      setHistoryState('ready');
      return;
    }
    let cancelled = false;
    setHistoryState('loading');
    Promise.all(ids.map((id) => radarApi.event(id)))
      .then((rows) => {
        if (cancelled) return;
        setDetailed(rows);
        setHistoryState('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setDetailed([]);
        setHistoryState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [idKey]);

  const rows = useMemo(() => collectRows(detailed), [detailed]);
  const shown = rows.slice(0, visible);
  const groups = useMemo(() => {
    const map = new Map<string, HistoryRow[]>();
    for (const row of shown) {
      const key = row.date.slice(0, 10);
      const list = map.get(key) ?? [];
      list.push(row);
      map.set(key, list);
    }
    return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [shown]);

  const hasMore = rows.length > visible;
  const onLoadMore = () => {
    setLoadingMore(true);
    moreTimer.current = setTimeout(() => {
      setVisible((count) => count + PAGE);
      setLoadingMore(false);
    }, 320);
  };

  const openRow = (row: HistoryRow) => {
    if (onPromoteLead && eventIds.has(row.eventId)) {
      onPromoteLead(row.eventId);
      return;
    }
    navigate(`/stock/${row.code}`);
  };

  let rowIndex = 0;

  return (
    <aside aria-label={t('历史事件回溯')} className="radar-history card-surface flex max-h-[560px] flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line px-4 pb-2.5 pt-3.5">
        <p className="flex items-baseline justify-between gap-2">
          <span className="text-body-s font-semibold text-ink-900">
            {t('历史事件回溯')}
            <span className="font-mono tnum">
              {' '}
              · {t('共')} {rows.length} {t('条')}
            </span>
          </span>
        </p>
        <p className="mt-1 text-micro text-ink-400">
          {t('按时间倒序')}
          <span className="mx-1 text-ink-300" aria-hidden="true">
            ·
          </span>
          {t('状态变更会按东京日历日归组。')}
          <span className="mx-1 text-ink-300" aria-hidden="true">
            ·
          </span>
          {t('点击行打开事件或个股')}
        </p>
      </div>

      <div className="bk-rail-scroll min-h-0 flex-1 overflow-y-auto">
        {historyState === 'loading' || historyState === 'idle' ? (
          <div className="flex flex-col items-center gap-2 py-10" role="status">
            <DotsLoader />
            <p className="text-caption text-ink-400">{t('正在读取历史')}</p>
          </div>
        ) : historyState === 'error' ? (
          <EmptyState
            image="/empty-radar.svg"
            title={t('未取得历史')}
            description={t('事件详情暂时读不到状态变更，请稍后重试。')}
            action={
              <button
                type="button"
                onClick={() => {
                  const ids = events.map((event) => event.event_id).slice(0, 30);
                  setHistoryState('loading');
                  Promise.all(ids.map((id) => radarApi.event(id)))
                    .then((next) => {
                      setDetailed(next);
                      setHistoryState('ready');
                    })
                    .catch(() => setHistoryState('error'));
                }}
                className="rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white shadow-btn-hi"
              >
                {t('重试')}
              </button>
            }
            className="py-8"
          />
        ) : rows.length === 0 ? (
          <EmptyState
            image="/empty-radar.svg"
            title={t('暂无匹配的历史事件')}
            description={t('暂无状态变更')}
            className="py-8"
          />
        ) : (
          <div>
            {groups.map(([day, items]) => (
              <div key={day}>
                <div className="radar-history-date flex items-baseline justify-between px-4 py-2">
                  <p className="text-[12px] font-medium leading-[18px] text-ink-500">{historyDayLabel(day)}</p>
                  <span className="font-mono text-micro text-ink-400 tnum">
                    {items.length} {t('条')}
                  </span>
                </div>
                <ul className="radar-history-list divide-y divide-line">
                  {items.map((row) => {
                    const index = rowIndex++;
                    const tone = STATE_TONE[row.to] ?? 'ink';
                    const fromLabel = t(RADAR_STATE_LABELS[row.from ?? ''] ?? row.from ?? '—');
                    const toLabel = t(RADAR_STATE_LABELS[row.to] ?? row.to);
                    return (
                      <motion.li
                        key={row.key}
                        initial={index < PAGE && !reducedMotion ? { opacity: 0, transform: 'translateY(8px)' } : false}
                        animate={{ opacity: 1, transform: 'translateY(0px)' }}
                        transition={{
                          duration: 0.36,
                          ease: EASE_PAPER,
                          delay: index < PAGE && !reducedMotion ? Math.min(index * 0.03, 0.36) : 0,
                        }}
                      >
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={() => openRow(row)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              openRow(row);
                            }
                          }}
                          aria-label={t('{code} {from} → {to}，打开', {
                            code: row.code,
                            from: fromLabel,
                            to: toLabel,
                          })}
                          className="radar-history-row flex min-h-[60px] cursor-pointer items-center gap-2.5 px-4 py-2 transition-colors duration-fast hover:bg-paper-2"
                        >
                          <span className="w-10 shrink-0 font-mono text-caption text-ink-400 tnum">
                            {fmtDateShort(row.date)}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-baseline gap-1.5">
                              <span className="shrink-0 font-mono text-body-s font-semibold text-ink-800">{row.code}</span>
                              <span className="truncate text-micro text-ink-400">{row.name ?? '—'}</span>
                            </span>
                            <span className="mt-0.5 flex items-center gap-1.5 text-micro leading-[14px]">
                              <span className="truncate text-ink-400">
                                {fromLabel} → {toLabel}
                              </span>
                              <span className={cn('radar-chip radar-history-state shrink-0', TONE_TEXT[tone], TONE_CHIP[tone])}>
                                <span className={cn('size-1.5 rounded-full', TONE_DOT[tone])} aria-hidden="true" />
                                {toLabel}
                              </span>
                            </span>
                          </span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            <span className="font-mono text-caption text-ink-800 tnum">{fmtPrice(row.close)}</span>
                            <span className={cn('size-1.5 rounded-full', TONE_DOT[tone])} aria-hidden="true" />
                          </span>
                        </div>
                      </motion.li>
                    );
                  })}
                </ul>
              </div>
            ))}

            <div className="flex flex-col items-center gap-1.5 border-t border-line px-3 py-2.5">
              {hasMore ? (
                <button
                  type="button"
                  onClick={onLoadMore}
                  disabled={loadingMore}
                  className="flex items-center gap-2 rounded-md border border-line bg-card px-3 py-1.5 text-caption font-medium text-ink-600 shadow-btn transition-colors duration-fast hover:border-brand-400 hover:text-brand-600 disabled:opacity-60"
                >
                  {loadingMore && <DotsLoader />}
                  {t('加载更多')}
                  <span className="font-mono text-micro text-ink-400 tnum">{t('剩 {n} 条', { n: rows.length - visible })}</span>
                </button>
              ) : (
                <p className="font-mono text-micro text-ink-300 tnum">{t('已加载全部 {n} 条', { n: rows.length })}</p>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
