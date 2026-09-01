/** 新闻催化剂桌面 — 对齐美版信息设计：
 *  信息流（过滤+热点条+重要度+AI状态） / 个股影响 / 经济日历 / 数据源。 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { newsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import Segmented from '@/components/shared/Segmented';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { t } from '@/i18n/core';
import { explanationLines } from '@/lib/explainText';
import { fmtDate, fmtJstDateTime, fmtRelativeShort } from '@/lib/format';
import { cn } from '@/lib/utils';
import type {
  EconEvent,
  NewsHotspotGroup,
  NewsItem,
  NewsSecurityRow,
  NewsStatus,
} from '@/api/types';

type Tab = 'feed' | 'stocks' | 'econ' | 'sources';

/** 値は API に渡す絞り込みキー（後端 `classify.CATEGORY_RULES` の日本語 taxonomy）。
 *  **表示のときだけ `t()` を通す** —— ここで訳した文字列を送ると何も引っかからない。 */
const CATEGORY_FILTERS = ['決算', '業績予想修正', 'M&A・TOB', '自社株買い', '配当', '日銀・金利', '規制・政策'];

export default function News() {
  const [tab, setTab] = useState<Tab>('feed');
  const [hours, setHours] = useState<24 | 72 | 168>(72);
  const [category, setCategory] = useState<string | null>(null);
  const [onlySecurities, setOnlySecurities] = useState(false);

  const feed = usePolling(
    () => newsApi.feed({ hours, category: category ?? undefined, only_securities: onlySecurities }),
    300_000,
    [hours, category, onlySecurities],
  );
  const hotspots = usePolling(() => newsApi.hotspots(hours), 300_000, [hours]);
  const securities = usePolling(() => newsApi.securities(hours), 300_000, [hours]);
  const econ = usePolling(() => newsApi.econCalendar(), 3_600_000);
  const status = usePolling(() => newsApi.status(), 300_000);

  const feedState = remoteState(feed, (d) => d.items.length === 0);

  return (
    <div className="space-y-5">
      <PageHeader
        section="07"
        eyebrow="NEWS & CATALYSTS · JAPAN EQUITIES"
        title={t('新闻')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<StatusStrip status={status.data ?? null} />}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented<Tab>
          options={[
            { value: 'feed', label: t('信息流') },
            { value: 'stocks', label: t('个股影响') },
            { value: 'econ', label: t('经济日历') },
            { value: 'sources', label: t('数据源') },
          ]}
          value={tab}
          onChange={setTab}
        />
        {(tab === 'feed' || tab === 'stocks') && (
          <Segmented<'24' | '72' | '168'>
            options={[
              { value: '24', label: '24h' },
              { value: '72', label: '72h' },
              { value: '168', label: '7d' },
            ]}
            value={String(hours) as '24' | '72' | '168'}
            onChange={(value) => setHours(Number(value) as 24 | 72 | 168)}
          />
        )}
      </div>

      {tab === 'feed' && (
        <>
          {/* 过滤行 */}
          <div className="card-surface flex flex-wrap items-center gap-1.5 rounded-lg p-2.5">
            <FilterChip active={category === null} onClick={() => setCategory(null)}>
              {t('全部')}
            </FilterChip>
            {CATEGORY_FILTERS.map((item) => (
              <FilterChip key={item} active={category === item} onClick={() => setCategory(category === item ? null : item)}>
                {t(item)}
              </FilterChip>
            ))}
            <span className="mx-1 h-4 w-px bg-line" />
            <FilterChip active={onlySecurities} onClick={() => setOnlySecurities((v) => !v)}>
              {t('仅看关联个股')}
            </FilterChip>
            <span className="ml-auto text-caption text-ink-400">
              {t('共')} {feed.data?.items.length ?? '—'} {t('条')}
            </span>
          </div>

          {/* 热点条 */}
          {(hotspots.data?.groups.length ?? 0) > 0 && (
            <div className="no-scrollbar flex gap-2 overflow-x-auto pb-1">
              {hotspots.data!.groups.map((group) => (
                <HotspotCard key={group.canonical_code} group={group} />
              ))}
            </div>
          )}

          {feedState === 'loading' ? (
            <SkeletonRows rows={8} />
          ) : feedState === 'error' ? (
            <EmptyState variant="error" title={t('加载失败')} description={String(feed.error?.message ?? '')} />
          ) : feedState === 'empty' ? (
            <EmptyState title={t('暂无数据')} description={feed.data?.note_ja ?? ''} />
          ) : (
            <ul className="space-y-2.5">
              {feed.data!.items.map((item) => (
                <NewsCard key={item.news_id} item={item} />
              ))}
            </ul>
          )}
        </>
      )}

      {tab === 'stocks' && <StocksImpactPanel rows={securities.data?.rows ?? []} loading={securities.loading} />}

      {tab === 'econ' && (
        <EconCalendarPanel
          events={econ.data?.events ?? []}
          note={econ.data?.coverage_note_ja}
          loading={econ.loading}
        />
      )}

      {tab === 'sources' && <SourcesPanel status={status.data ?? null} loading={status.loading} />}
    </div>
  );
}

/* ---------------- 状态条 ---------------- */

function StatusStrip({ status }: { status: NewsStatus | null }) {
  if (!status) return null;
  const feedsOk = status.feeds.filter((feed) => !feed.last_error_code && feed.last_fetched_at).length;
  return (
    <span className="flex items-center gap-3 text-caption text-ink-500">
      <span>
        {t('数据源')} {feedsOk}/{status.feeds.length}
      </span>
      <span
        className={cn(
          'rounded-pill px-2 py-0.5 text-micro font-medium',
          status.ai.enabled ? 'bg-ai-50 text-ai-600' : 'bg-paper-2 text-ink-400',
        )}
      >
        AI {status.ai.enabled ? t('已启用') : t('未启用')}
      </span>
    </span>
  );
}

/* ---------------- 信息流 ---------------- */

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'rounded-pill bg-brand-600 px-2.5 py-1 text-caption font-medium text-white'
          : 'rounded-pill border border-line bg-card px-2.5 py-1 text-caption text-ink-600 hover:bg-brand-50'
      }
    >
      {children}
    </button>
  );
}

function ImportanceBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="rounded-sm bg-paper-2 px-1.5 py-0.5 font-mono text-micro text-ink-400">—</span>;
  }
  const tone = value >= 75 ? 'bg-warn-50 text-warn-700' : value >= 55 ? 'bg-brand-50 text-brand-700' : 'bg-paper-2 text-ink-500';
  return <span className={`rounded-sm px-1.5 py-0.5 font-mono text-micro font-semibold tnum ${tone}`}>{Math.round(value)}</span>;
}

function AnalysisStateChip({ state }: { state: NewsItem['analysis_state'] }) {
  if (state === 'completed' || !state) return null;
  const map: Record<string, { label: string; tone: string }> = {
    pending: { label: t('分析排队中'), tone: 'bg-brand-50 text-brand-700' },
    failed: { label: t('分析失败'), tone: 'bg-down-50 text-down-700' },
    disabled: { label: t('AI 未启用'), tone: 'bg-paper-2 text-ink-400' },
    none: { label: t('未分析'), tone: 'bg-paper-2 text-ink-400' },
  };
  const item = map[state];
  if (!item) return null;
  return <span className={`rounded-pill px-2 py-0.5 text-micro ${item.tone}`}>{item.label}</span>;
}

function HotspotCard({ group }: { group: NewsHotspotGroup }) {
  return (
    <Link
      to={`/stock/${group.display_code}`}
      className="card-surface card-hover flex min-w-[220px] max-w-[260px] shrink-0 flex-col gap-1 rounded-lg p-2.5"
    >
      <span className="flex items-center gap-1.5">
        <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-caption font-semibold text-brand-700">
          {group.display_code}
        </span>
        <span className="min-w-0 truncate text-caption text-ink-700">{group.name_ja ?? '—'}</span>
        <span className="ml-auto">
          <ImportanceBadge value={group.max_importance} />
        </span>
      </span>
      <span className="line-clamp-2 text-caption text-ink-600">{group.latest?.title ?? '—'}</span>
      <span className="flex items-center gap-1.5 text-micro text-ink-400">
        <span>{group.item_count} {t('条')}</span>
        {group.categories.slice(0, 2).map((cat) => (
          <span key={cat} className="rounded-sm bg-paper-2 px-1 py-0.5">{t(cat)}</span>
        ))}
      </span>
    </Link>
  );
}

function NewsCard({ item }: { item: NewsItem }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="card-surface rounded-lg p-3.5">
      <div className="flex items-start gap-2.5">
        <ImportanceBadge value={item.importance} />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="block w-full text-left"
          >
            <h3 className="text-body font-medium leading-snug text-ink-900">
              {item.translated_title_ja ?? item.original_title ?? '—'}
            </h3>
          </button>
          {item.translated_title_ja && item.original_title && item.translated_title_ja !== item.original_title && (
            <p className="mt-0.5 truncate text-caption text-ink-400">{item.original_title}</p>
          )}
          {item.summary_ja && <p className="mt-1.5 text-body-s text-ink-700">{item.summary_ja}</p>}

          {/* 中文影响分析（独立区域，不混入日语正文） */}
          {item.analysis_zh && (
            <div className="mt-2 rounded-md bg-ai-50 p-2.5 text-body-s text-ink-800">
              <span className="mr-1.5 rounded-sm bg-ai-600 px-1 py-0.5 text-micro font-bold text-white">{t('中文分析')}</span>
              {item.analysis_zh.headline && <strong className="mr-1">{item.analysis_zh.headline}</strong>}
              {item.analysis_zh.impact}
              {/* 受影响股票只列代码与理由，不显示涨跌方向（产品决定移除方向预测） */}
              {(item.analysis_zh.affected?.length ?? 0) > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {item.analysis_zh.affected!.map((affected) => (
                    <Link
                      key={affected.code}
                      to={`/stock/${affected.code.endsWith('0') && affected.code.length === 5 ? affected.code.slice(0, 4) : affected.code}`}
                      title={affected.reason_zh ?? undefined}
                      className="rounded-pill bg-paper-2 px-2 py-0.5 font-mono text-micro text-ink-600 hover:bg-brand-50 hover:text-brand-700"
                    >
                      {affected.code.endsWith('0') && affected.code.length === 5 ? affected.code.slice(0, 4) : affected.code}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-micro text-ink-400">
            {(item.categories ?? []).slice(0, 3).map((cat) => (
              <span key={cat} className="rounded-sm border border-line bg-card px-1.5 py-0.5 text-ink-600">{t(cat)}</span>
            ))}
            {item.securities.map((security) => (
              <Link
                key={security.canonical_code}
                to={`/stock/${security.display_code}`}
                className="rounded-sm bg-brand-50 px-1.5 py-0.5 font-mono text-brand-700 hover:underline"
              >
                {security.display_code}
                {security.name_ja ? ` ${security.name_ja}` : ''}
              </Link>
            ))}
            <AnalysisStateChip state={item.analysis_state} />
            <span className="ml-auto flex items-center gap-2">
              <span>{item.source}</span>
              <span title={item.published_at ?? ''}>{fmtRelativeShort(item.published_at)}</span>
              {item.source_url && (
                <a href={item.source_url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">
                  {t('原文')}
                </a>
              )}
            </span>
          </div>

          {expanded && (
            <div className="mt-2 space-y-1.5 border-t border-line pt-2 text-caption text-ink-500">
              {item.original_summary && <p className="text-ink-600">{item.original_summary}</p>}
              {(item.importance_reason_items?.length ?? item.importance_reasons?.length ?? 0) > 0 && (
                <p>
                  {t('重要度依据')}:{' '}
                  {explanationLines(item.importance_reason_items, item.importance_reasons).join(' · ')}
                </p>
              )}
              <p>
                {t('发布')}: {fmtJstDateTime(item.published_at)} · {t('语言')}: {item.source_language}
                {item.market_relevance === 'market' && <span> · {t('市场级新闻')}</span>}
              </p>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

/* ---------------- 个股影响 ---------------- */

function StocksImpactPanel({ rows, loading }: { rows: NewsSecurityRow[]; loading: boolean }) {
  const columns = useMemo<Column<NewsSecurityRow>[]>(
    () => [
      {
        key: 'code',
        title: t('代码'),
        width: '30%',
        render: (row) => (
          <Link to={`/stock/${row.display_code}`} className="flex min-w-0 items-center gap-2 hover:underline">
            <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
              {row.display_code}
            </span>
            <span className="min-w-0 truncate text-body-s text-ink-800">{row.name_ja ?? '—'}</span>
          </Link>
        ),
      },
      {
        key: 'count',
        title: t('新闻数'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.news_count,
        render: (row) => <span className="font-mono text-body-s tnum">{row.news_count}</span>,
      },
      {
        key: 'importance',
        title: t('最高重要度'),
        align: 'right',
        sortable: true,
        sortValue: (row) => row.max_importance ?? -1,
        render: (row) => <ImportanceBadge value={row.max_importance} />,
      },
      {
        key: 'categories',
        title: t('主要类别'),
        render: (row) => (
          <span className="flex flex-wrap gap-1">
            {row.categories.map((cat) => (
              <span key={cat} className="rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-600">{t(cat)}</span>
            ))}
          </span>
        ),
      },
      {
        key: 'ai',
        title: t('AI 分析'),
        align: 'right',
        render: (row) =>
          row.ai ? (
            <span className="font-mono text-caption text-ink-600 tnum">
              {t('已分析')} {row.ai.analyzed}
            </span>
          ) : (
            <span className="text-micro text-ink-300">{t('未分析')}</span>
          ),
      },
      {
        key: 'latest',
        title: t('最新标题'),
        width: '30%',
        render: (row) => <span className="line-clamp-1 text-caption text-ink-600">{row.latest?.title ?? '—'}</span>,
      },
    ],
    [],
  );
  if (loading && rows.length === 0) return <SkeletonRows rows={8} />;
  if (rows.length === 0) return <EmptyState title={t('暂无数据')} />;
  return <DataTable columns={columns} rows={rows} rowKey={(row) => row.canonical_code} rowHeight={44} />;
}

/* ---------------- 经济日历 ---------------- */

function EconCalendarPanel({ events, note, loading }: { events: EconEvent[]; note?: string; loading: boolean }) {
  if (loading && events.length === 0) return <SkeletonRows rows={8} />;
  if (events.length === 0) return <EmptyState title={t('暂无数据')} />;
  const grouped = new Map<string, EconEvent[]>();
  for (const event of events) {
    const list = grouped.get(event.date) ?? [];
    list.push(event);
    grouped.set(event.date, list);
  }
  return (
    <div className="space-y-3">
      {note && <p className="text-caption text-ink-400">{note}</p>}
      {Array.from(grouped.entries()).map(([date, dayEvents]) => (
        <section key={date} className="card-surface rounded-lg p-3">
          <h3 className="mb-2 flex items-baseline gap-2">
            <span className="font-mono text-body font-semibold tnum text-ink-900">{fmtDate(date)}</span>
            <span className="text-micro text-ink-400">{weekdayJa(date)}</span>
          </h3>
          <ul className="divide-y divide-line">
            {dayEvents.map((event, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2 py-1.5">
                <span className="w-12 shrink-0 font-mono text-caption tnum text-ink-500">
                  {event.time_jst || '—'}
                </span>
                <EconImportanceDot importance={event.importance} />
                <span className="min-w-0 flex-1 text-body-s text-ink-800">{event.name_ja}</span>
                <span className="rounded-sm bg-paper-2 px-1.5 py-0.5 text-micro text-ink-500">{t(event.category)}</span>
                <span className="text-micro text-ink-400">{event.organizer}</span>
                {!event.confirmed && (
                  <span className="rounded-sm bg-warn-50 px-1.5 py-0.5 text-micro text-warn-700" title={event.note ?? ''}>
                    {t('目安')}
                  </span>
                )}
                {event.source_url && (
                  <a href={event.source_url} target="_blank" rel="noreferrer" className="text-micro text-brand-700 hover:underline">
                    {t('出处')}
                  </a>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function EconImportanceDot({ importance }: { importance: string }) {
  const tone = importance === 'high' ? 'bg-warn-600' : importance === 'medium' ? 'bg-brand-500' : 'bg-ink-300';
  const label = importance === 'high' ? t('高') : importance === 'medium' ? t('中') : t('低');
  return (
    <span className="flex w-8 shrink-0 items-center gap-1">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden />
      <span className="text-micro text-ink-400">{label}</span>
    </span>
  );
}

function weekdayJa(isoDate: string): string {
  // 正午 JST = 03:00 UTC 同日 → getUTCDay がそのまま JST の曜日。閲覧者 TZ 非依存。
  const parsed = new Date(`${isoDate}T12:00:00+09:00`);
  if (Number.isNaN(parsed.getTime())) return '';
  const days = ['日', '月', '火', '水', '木', '金', '土'];
  return `(${days[parsed.getUTCDay()]})`;
}

/* ---------------- 数据源 ---------------- */

function SourcesPanel({ status, loading }: { status: NewsStatus | null; loading: boolean }) {
  if (loading && !status) return <SkeletonRows rows={5} />;
  if (!status) return <EmptyState title={t('暂无数据')} />;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section className="card-surface rounded-lg p-4">
        <h3 className="mb-2 text-h3 text-ink-900">RSS {t('数据源')}</h3>
        <ul className="divide-y divide-line">
          {status.feeds.map((feed) => (
            <li key={feed.feed_url} className="py-2">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    'inline-block h-2 w-2 rounded-full',
                    feed.last_error_code ? 'bg-down-600' : feed.last_fetched_at ? 'bg-ai-600' : 'bg-ink-300',
                  )}
                />
                <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink-700">{feed.feed_url}</span>
              </div>
              <div className="mt-1 flex items-center gap-3 pl-4 text-micro text-ink-400">
                <span>{t('最近取得')}: {fmtJstDateTime(feed.last_fetched_at)}</span>
                <span>{t('累计')}: {feed.items_seen}</span>
                {feed.last_error_code && <span className="text-down-700">{feed.last_error_code}</span>}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-micro text-ink-400">
          {t('实体目录')}: {status.entity_aliases.toLocaleString('ja-JP')} · {t('同步间隔')}: {status.sync_seconds}s
        </p>
      </section>

      <section className="card-surface rounded-lg p-4">
        <h3 className="mb-2 text-h3 text-ink-900">AI {t('管道')}</h3>
        <dl className="space-y-1.5 text-body-s">
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('状态')}</dt>
            <dd className={status.ai.enabled ? 'text-ai-600' : 'text-ink-400'}>
              {status.ai.enabled ? t('已启用') : t('未启用')}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('翻译目标语言')}</dt>
            <dd className="font-mono text-ink-800">{status.ai.translation_target}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('分析语言')}</dt>
            <dd className="font-mono text-ink-800">{status.ai.analysis_language}</dd>
          </div>
          {Object.keys(status.ai.queue).length > 0 && (
            <div className="flex justify-between">
              <dt className="text-ink-500">{t('任务队列')}</dt>
              <dd className="font-mono text-caption tnum text-ink-700">
                {Object.entries(status.ai.queue).map(([key, count]) => `${key}:${count}`).join(' ')}
              </dd>
            </div>
          )}
        </dl>
        {status.ai.note_ja && <p className="mt-2 rounded-md bg-paper-2 p-2 text-caption text-ink-500">{status.ai.note_ja}</p>}
      </section>
    </div>
  );
}
