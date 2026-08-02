/** 新闻页：news_mode=off 时如实显示未启用；启用后由阶段5填充列表。 */

import { newsApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import { SkeletonRows } from '@/components/shared/Skeleton';
import { t } from '@/i18n/core';

export default function News() {
  const query = usePolling(() => newsApi.feed(72), 300_000);
  return (
    <div className="space-y-6">
      <PageHeader
        section="07"
        eyebrow="NEWS · JAPAN EQUITIES"
        title={t('新闻')}
        description={t('本页为日线数据，收盘后更新')}
      />
      {query.loading && !query.data ? (
        <SkeletonRows rows={8} />
      ) : query.error ? (
        <EmptyState variant="error" title={t('加载失败')} description={query.error.message} />
      ) : query.data?.mode === 'off' ? (
        <EmptyState title={t('新闻功能未启用')} description={query.data.note_ja ?? ''} />
      ) : (query.data?.items?.length ?? 0) === 0 ? (
        <EmptyState title={t('暂无数据')} />
      ) : (
        <NewsList items={query.data!.items as NewsItem[]} />
      )}
    </div>
  );
}

interface NewsItem {
  news_id: string;
  source: string | null;
  published_at: string | null;
  original_title: string | null;
  translated_title_ja: string | null;
  summary_ja: string | null;
  analysis_zh: { headline: string | null; impact: string | null } | null;
  categories: string[];
  securities: { canonical_code: string; display_code: string; name_ja: string | null }[];
  importance: number | null;
}

function NewsList({ items }: { items: NewsItem[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.news_id} className="card-surface rounded-lg p-4">
          {/* 主要文本 = 日本語訳; 原文はサブ表示 */}
          <h3 className="text-body font-medium text-ink-900">
            {item.translated_title_ja ?? item.original_title ?? '—'}
          </h3>
          {item.translated_title_ja && item.original_title && item.translated_title_ja !== item.original_title && (
            <p className="mt-0.5 truncate text-caption text-ink-400">{item.original_title}</p>
          )}
          {item.summary_ja && <p className="mt-2 text-body-s text-ink-700">{item.summary_ja}</p>}
          {item.analysis_zh?.impact && (
            <div className="mt-2 rounded-md bg-ai-50 p-2.5 text-body-s text-ink-800">
              <span className="mr-1.5 rounded-sm bg-ai-600 px-1 py-0.5 text-micro font-bold text-white">中文分析</span>
              {item.analysis_zh.impact}
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-micro text-ink-400">
            {item.source && <span>{item.source}</span>}
            {item.published_at && <span>{item.published_at.slice(0, 16).replace('T', ' ')}</span>}
            {item.securities.map((security) => (
              <span key={security.canonical_code} className="rounded-sm bg-brand-50 px-1.5 py-0.5 font-mono text-brand-700">
                {security.display_code}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}
