/**
 * ティック分析 — 分足では潰れる情報だけを出す。
 * 真の VWAP と乖離 / 大口約定 / 価格帯別出来高 / 板寄せ（寄付・引け）。
 * すべて J-Quants の確定ティック由来。遅延気配（Yahoo）は混ざらない。
 */
import { cn } from '@/lib/utils';
import { fmtPct, fmtPrice } from '@/lib/format';
import SourceNote from '@/components/shared/SourceNote';
import { t } from '@/i18n/core';
import type { AuctionPrint, TickAnalytics } from '@/api/types';

function shares(value: number | null | undefined): string {
  if (value == null) return '—';
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}億株`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万株`;
  return `${Math.round(value).toLocaleString()}株`;
}

function AuctionCard({ label, print: entry, tone }: { label: string; print: AuctionPrint | null; tone: string }) {
  return (
    <div className="rounded-md bg-paper-2 px-2.5 py-2">
      <p className="text-micro text-ink-400">{label}</p>
      {entry ? (
        <>
          <p className="font-mono text-body-s tnum text-ink-900">{fmtPrice(entry.price)}</p>
          <p className="font-mono text-micro tnum text-ink-500">
            {shares(entry.volume)}
            {entry.day_volume_share != null && (
              <span className={cn('ml-1 font-semibold', tone)}>
                {(entry.day_volume_share * 100).toFixed(1)}%
              </span>
            )}
          </p>
          <p className="font-mono text-micro text-ink-300">{entry.time}</p>
        </>
      ) : (
        <p className="font-mono text-body-s text-ink-300">—</p>
      )}
    </div>
  );
}

export default function TickAnalyticsPanel({ analytics }: { analytics: TickAnalytics | null | undefined }) {
  if (!analytics?.available) return null;
  const { vwap, large_prints: large, volume_profile: profile, auctions, sessions } = analytics;
  const maxBucket = Math.max(...(profile?.buckets ?? []).map((b) => b.volume), 1);
  /* 引けの板寄せが当日の 2 割を超える日は、終値が需給で作られている
     （指数入替・リバランス）。日足だけ見ていると絶対に見えない事実。 */
  const closingHeavy = (auctions?.closing?.day_volume_share ?? 0) >= 0.2;

  return (
    <section className="card-surface p-4" aria-label={t('逐笔分析')}>
      <p className="eyebrow">{t('逐笔分析 · 仅 Tick 数据可得')}</p>

      {/* VWAP と乖離 */}
      <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-line pb-3">
        <span>
          <span className="block text-micro text-ink-400">{t('真实 VWAP')}</span>
          <span className="font-mono text-data-l tnum text-ink-900">{fmtPrice(vwap?.vwap ?? null)}</span>
        </span>
        <span>
          <span className="block text-micro text-ink-400">{t('现价对 VWAP')}</span>
          <span
            className={cn(
              'font-mono text-data-m font-semibold tnum',
              (vwap?.deviation_pct ?? 0) >= 0 ? 'text-up-600' : 'text-down-600',
            )}
          >
            {fmtPct(vwap?.deviation_pct)}
          </span>
        </span>
        <span>
          <span className="block text-micro text-ink-400">{t('成交笔数')}</span>
          <span className="font-mono text-data-m tnum text-ink-700">
            {(analytics.tick_count ?? 0).toLocaleString()}
          </span>
        </span>
        {sessions && (
          <span>
            <span className="block text-micro text-ink-400">{t('前場 / 後場')}</span>
            <span className="font-mono text-caption tnum text-ink-600">
              {shares(sessions.morning.volume)} / {shares(sessions.afternoon.volume)}
            </span>
          </span>
        )}
      </div>

      {/* 板寄せ */}
      <div className="mt-3">
        <p className="mb-1.5 flex items-center gap-2 text-caption text-ink-500">
          {t('集合竞价（板寄せ）')}
          {closingHeavy && (
            <span className="rounded-sm bg-warn-50 px-1.5 py-0.5 text-micro text-warn-700">
              {t('引け占比偏高 · 终值由需给形成')}
            </span>
          )}
        </p>
        <div className="grid grid-cols-3 gap-2">
          <AuctionCard label={t('寄付')} print={auctions?.opening ?? null} tone="text-ink-600" />
          <AuctionCard label={t('後場寄り')} print={auctions?.afternoon_open ?? null} tone="text-ink-600" />
          <AuctionCard label={t('引け')} print={auctions?.closing ?? null} tone={closingHeavy ? 'text-warn-700' : 'text-ink-600'} />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 価格帯別出来高 */}
        <div>
          <p className="mb-1.5 text-caption text-ink-500">
            {t('价格帯别成交量')}
            {profile?.poc != null && (
              <span className="ml-2 font-mono text-micro text-brand-600">
                POC {fmtPrice(profile.poc)}
              </span>
            )}
          </p>
          <div className="space-y-px">
            {[...(profile?.buckets ?? [])].reverse().map((bucket) => {
              const isPoc = profile?.poc != null
                && profile.poc >= bucket.price_low
                && profile.poc <= bucket.price_high;
              return (
                <div key={bucket.price_low} className="flex items-center gap-1.5">
                  <span className="w-14 shrink-0 text-right font-mono text-[10px] text-ink-400 tnum">
                    {Math.round(bucket.price_low).toLocaleString()}
                  </span>
                  <span className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-[2px] bg-line/60">
                    <span
                      className={cn('block h-full rounded-[2px]', isPoc ? 'bg-brand-600' : 'bg-brand-400/70')}
                      style={{ width: `${Math.max(1, (bucket.volume / maxBucket) * 100)}%` }}
                    />
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* 大口約定 */}
        <div>
          <p className="mb-1.5 text-caption text-ink-500">
            {t('大口成交')}
            {large?.threshold != null && (
              <span className="ml-2 font-mono text-micro text-ink-400">
                ≥{shares(large.threshold)} · {large.count} {t('笔')}
                {large.volume_share != null && ` · ${(large.volume_share * 100).toFixed(1)}%`}
              </span>
            )}
          </p>
          {(large?.rows ?? []).length === 0 ? (
            <p className="text-caption text-ink-400">{t('当日无显著大口成交')}</p>
          ) : (
            <table className="w-full border-collapse font-mono text-micro tnum">
              <tbody>
                {(large?.rows ?? []).slice(0, 8).map((row) => (
                  <tr key={`${row.time}-${row.volume}`} className="border-b border-line/60 last:border-b-0">
                    <td className="py-1 text-ink-400">{row.time}</td>
                    <td className="py-1 text-right text-ink-800">{fmtPrice(row.price)}</td>
                    <td className="py-1 text-right font-semibold text-brand-700">{shares(row.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <SourceNote
        className="mt-3"
        text={t('VWAP=Σ(价格×数量)/Σ数量（分足均价不可替代）· 大口=中位笔数量 25 倍且 ≥当日成交量 0.2%，板寄せ另计')}
      />
    </section>
  );
}
