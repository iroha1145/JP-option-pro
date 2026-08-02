/** 首页：市场状态 → 行业强弱 → 雷达信号 → 最近决算 → 自选异动。 */

import { Link } from 'react-router';
import { marketApi, radarApi, earningsApi, watchlistApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import ChangeBadge from '@/components/shared/ChangeBadge';
import { SkeletonCard, SkeletonRows } from '@/components/shared/Skeleton';
import Sparkline from '@/components/charts/Sparkline';
import { CodeCell, DataThrough, SignalChip, StateChip } from '@/components/domain';
import { t } from '@/i18n/core';
import { fmtDate, fmtPct, fmtPrice, fmtYenCompact } from '@/lib/format';

export default function Home() {
  const market = usePolling(() => marketApi.overview(), 120_000);
  const radar = usePolling(() => radarApi.current(), 120_000);
  const earnings = usePolling(() => earningsApi.recent(7), 300_000);
  const watchlist = usePolling(() => watchlistApi.list(), 120_000);

  const marketState = remoteState(market, (d) => d.indices.length === 0);

  return (
    <div className="space-y-8">
      <PageHeader
        section="01"
        eyebrow="OPTIX JAPAN · DAILY RESEARCH"
        title={t('首页')}
        description={t('本页为日线数据，收盘后更新')}
        meta={<DataThrough date={market.data?.data_through} />}
      />

      {/* 指数带 */}
      {marketState === 'loading' ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} className="h-24" />
          ))}
        </div>
      ) : marketState === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(market.error?.message ?? '')} />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {market.data?.indices.map((index) => (
            <Link
              key={index.index_code}
              to="/market"
              className="card-surface card-hover flex flex-col gap-1 rounded-lg p-3"
            >
              <span className="truncate text-caption text-ink-500">{index.name}</span>
              <span className="font-mono text-data-l tnum text-ink-900">{fmtPrice(index.close)}</span>
              <div className="flex items-center justify-between">
                <ChangeBadge value={index.change_pct} size="sm" />
                <Sparkline data={index.sparkline} width={64} height={20} change={index.change_pct ?? 0} />
              </div>
            </Link>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 市场广度 + 行业 */}
        <section className="card-surface rounded-lg p-4 lg:col-span-1">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-h3 text-ink-900">{t('市场广度')}</h2>
            <Link to="/market" className="text-caption text-brand-700 hover:underline">
              {t('查看全部')}
            </Link>
          </header>
          {market.data ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2 text-center">
                <BreadthCell label={t('上涨')} value={market.data.breadth.advancers} tone="up" />
                <BreadthCell label={t('下跌')} value={market.data.breadth.decliners} tone="down" />
                <BreadthCell label={t('平盘')} value={market.data.breadth.unchanged} tone="flat" />
              </div>
              <div className="flex items-center justify-between border-t border-line pt-2 text-body-s">
                <span className="text-ink-500">{t('年内新高')}</span>
                <span className="font-mono tnum text-ink-900">{market.data.breadth.new_highs_252 ?? '—'}</span>
              </div>
              <div className="flex items-center justify-between text-body-s">
                <span className="text-ink-500">{t('成交额')}</span>
                <span className="font-mono tnum text-ink-900">
                  {fmtYenCompact(market.data.breadth.total_turnover_value)}
                </span>
              </div>
              {market.data.short_selling ? (
                <div className="flex items-center justify-between text-body-s">
                  <span className="text-ink-500">{t('市场空卖占比')}</span>
                  <span className="font-mono tnum text-ink-900">
                    {fmtPct(market.data.short_selling.market_short_ratio)}
                  </span>
                </div>
              ) : null}
              <ol className="space-y-1 border-t border-line pt-2">
                {market.data.sectors.slice(0, 6).map((sector) => (
                  <li key={sector.sector33_code} className="flex items-center justify-between text-body-s">
                    <span className="truncate text-ink-700">{sector.sector33_name}</span>
                    <ChangeBadge value={sector.median_return_1d} size="sm" />
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <SkeletonRows rows={6} />
          )}
        </section>

        {/* 雷达 */}
        <section className="card-surface rounded-lg p-4 lg:col-span-2">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-h3 text-ink-900">{t('雷达信号')}</h2>
            <Link to="/radar" className="text-caption text-brand-700 hover:underline">
              {t('查看全部')}
            </Link>
          </header>
          {radar.data ? (
            radar.data.events.length === 0 ? (
              <EmptyState title={t('暂无数据')} description={radar.data.note ?? ''} />
            ) : (
              <ul className="divide-y divide-line">
                {radar.data.events.slice(0, 8).map((event) => (
                  <li key={event.event_id} className="flex items-center gap-3 py-2">
                    <CodeCell
                      displayCode={event.display_code}
                      nameJa={event.name_ja}
                      to={`/stock/${event.display_code}`}
                    />
                    <span className="ml-auto flex shrink-0 items-center gap-2">
                      <SignalChip signal={event.signal_type} />
                      <StateChip state={event.state} />
                      <span className="w-10 text-right font-mono text-body-s tnum text-ink-900">
                        {event.alert_priority !== null ? Math.round(event.alert_priority) : '—'}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <SkeletonRows rows={8} />
          )}
        </section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 最近决算 */}
        <section className="card-surface rounded-lg p-4">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-h3 text-ink-900">{t('最近决算')}</h2>
            <Link to="/earnings" className="text-caption text-brand-700 hover:underline">
              {t('查看全部')}
            </Link>
          </header>
          {earnings.data ? (
            earnings.data.items.length === 0 ? (
              <EmptyState title={t('暂无数据')} />
            ) : (
              <ul className="divide-y divide-line">
                {earnings.data.items.slice(0, 6).map((item) => (
                  <li key={`${item.canonical_code}-${item.disclosed_date}-${item.period_type}`} className="flex items-center gap-3 py-2">
                    <CodeCell displayCode={item.display_code} nameJa={item.name_ja} to={`/stock/${item.display_code}`} />
                    <span className="ml-auto flex items-center gap-2 text-caption text-ink-500">
                      <span>{fmtDate(item.disclosed_date)}</span>
                      <span className="rounded-sm bg-paper-2 px-1.5 py-0.5">{item.period_type ?? '—'}</span>
                      {item.forecast_direction === 'upward' && (
                        <span className="text-up-700">{t('上方修正')}</span>
                      )}
                      {item.forecast_direction === 'downward' && (
                        <span className="text-down-700">{t('下方修正')}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <SkeletonRows rows={6} />
          )}
        </section>

        {/* 自选异动 */}
        <section className="card-surface rounded-lg p-4">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-h3 text-ink-900">{t('自选异动')}</h2>
            <Link to="/watchlist" className="text-caption text-brand-700 hover:underline">
              {t('查看全部')}
            </Link>
          </header>
          {watchlist.data ? (
            watchlist.data.items.length === 0 ? (
              <EmptyState title={t('暂无自选')} description={t('在筛选器中添加')} />
            ) : (
              <ul className="divide-y divide-line">
                {[...watchlist.data.items]
                  .sort(
                    (a, b) =>
                      Math.abs(b.quote?.change_pct ?? 0) - Math.abs(a.quote?.change_pct ?? 0),
                  )
                  .slice(0, 6)
                  .map((item) => (
                    <li key={item.canonical_code} className="flex items-center gap-3 py-2">
                      <CodeCell displayCode={item.display_code} nameJa={item.name_ja} to={`/stock/${item.display_code}`} />
                      <span className="ml-auto flex items-center gap-3">
                        <span className="font-mono text-body-s tnum text-ink-900">
                          {fmtPrice(item.quote?.close)}
                        </span>
                        <ChangeBadge value={item.quote?.change_pct} size="sm" />
                      </span>
                    </li>
                  ))}
              </ul>
            )
          ) : (
            <SkeletonRows rows={6} />
          )}
        </section>
      </div>
    </div>
  );
}

function BreadthCell({ label, value, tone }: { label: string; value: number | null; tone: 'up' | 'down' | 'flat' }) {
  const toneClass = tone === 'up' ? 'text-up-700' : tone === 'down' ? 'text-down-700' : 'text-ink-500';
  return (
    <div className="rounded-md bg-paper-2 py-2">
      <div className={`font-mono text-data-l tnum ${toneClass}`}>{value ?? '—'}</div>
      <div className="text-micro text-ink-400">{label}</div>
    </div>
  );
}
