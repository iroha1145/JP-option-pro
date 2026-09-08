/**
 * 个股侧栏关键数据（对标美站 KeyStats 纸面）。
 * 只展示日本站真实字段：今开/昨收/高低/收盘/成交量/成交额 + 区间标尺。
 * 不编造市值、PE、IV、均量。K 线不够约 240 根时标「期间区间」，不假装 52 周。
 */
import { stocksApi } from '@/api/modules';
import type { StockOverview } from '@/api/types';
import { usePolling } from '@/hooks/usePolling';
import { t } from '@/i18n/core';
import { fmtPrice, fmtShares, fmtYenCompact } from '@/lib/format';
import {
  isYearRange,
  lastBar,
  markerPrice,
  periodExtremes,
  previousBar,
  previousClose,
  rangeMarkerPct,
  sessionHigh,
  sessionLow,
  sessionOpen,
} from '@/lib/keyStats';
import { codesMatch } from '@/lib/securityIdentity';

export default function KeyStats({
  code,
  quote,
}: {
  code: string;
  quote: StockOverview['quote'];
}) {
  const year = usePolling(
    () => stocksApi.chart(code, '1y'),
    null,
    [code],
    { identity: code, belongsTo: (data) => codesMatch(data.canonical_code, code) },
  );
  const bars = year.data && codesMatch(year.data.canonical_code, code) ? year.data.bars : [];
  const latest = lastBar(bars);
  const prior = previousBar(bars);
  const extremes = periodExtremes(bars);
  const yearLike = isYearRange(bars.length);
  const pos = rangeMarkerPct(markerPrice(quote), extremes.high, extremes.low);
  const hasRange = extremes.high != null && extremes.low != null;

  const rows: [string, string][] = [
    [t('今开'), fmtPrice(sessionOpen(latest))],
    [t('昨收'), fmtPrice(previousClose(prior))],
    [t('最高价'), fmtPrice(sessionHigh(latest))],
    [t('最低价'), fmtPrice(sessionLow(latest))],
    [t('收盘'), fmtPrice(quote.close)],
    [t('成交量'), quote.volume == null ? '—' : fmtShares(quote.volume)],
    [t('成交额'), fmtYenCompact(quote.turnover_value)],
  ];

  return (
    <section className="card-surface p-5">
      <p className="eyebrow">KEY STATS</p>
      <h3 className="mt-1.5 text-h3 text-ink-900">{t('关键数据')}</h3>
      <dl className="mt-3 divide-y divide-line">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between py-2">
            <dt className="text-body-s text-ink-400">{label}</dt>
            <dd className="font-mono text-body-s text-ink-800 tnum">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 border-t border-line pt-3">
        <div className="flex items-center justify-between text-micro text-ink-400">
          <span>{yearLike ? t('52 周区间') : t('期间区间')}</span>
          <span className="font-mono tnum">
            {hasRange ? `${fmtPrice(extremes.low)} — ${fmtPrice(extremes.high)}` : '—'}
          </span>
        </div>
        {hasRange && pos != null && (
          <div className="relative mt-2 h-1 rounded-pill bg-line" role="presentation">
            <div className="h-full rounded-pill bg-brand-100" />
            <span
              className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-brand-600 shadow-sh-1"
              style={{ left: `${pos}%` }}
            />
          </div>
        )}
      </div>
    </section>
  );
}
