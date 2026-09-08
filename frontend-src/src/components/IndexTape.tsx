/**
 * 指数跑马灯：日线收盘截面，不做实时伪装。
 */
import { memo } from 'react';
import { useNavigate } from 'react-router';
import { marketApi } from '@/api/modules';
import type { IndexSummary } from '@/api/types';
import { usePolling } from '@/hooks/usePolling';
import { useTickFlash } from '@/hooks/useTickFlash';
import { fmtPct, fmtPrice } from '@/lib/format';
import { cn } from '@/lib/utils';
import { t } from '@/i18n/core';

function TapeItem({
  q,
  flash,
  onOpen,
}: {
  q: IndexSummary;
  flash: 'up' | 'down' | null;
  onOpen: (code: string) => void;
}) {
  const change = typeof q.change_pct === 'number' && Number.isFinite(q.change_pct) ? q.change_pct : null;
  const tone = change === null ? 'missing' : change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
  return (
    <button
      type="button"
      onClick={() => onOpen(q.index_code)}
      title={t('查看大盘强弱 · {code}', { code: q.name })}
      aria-label={
        tone === 'missing'
          ? t('查看大盘强弱，{code} 最新价 {price}，{flat}', {
              code: q.name,
              price: fmtPrice(q.close),
              flat: t('涨跌数据缺失'),
            })
          : tone === 'flat'
            ? t('查看大盘强弱，{code} 最新价 {price}，{flat}', { code: q.name, price: fmtPrice(q.close), flat: t('持平') })
            : t('查看大盘强弱，{code} 最新价 {price}，涨跌 {pct}', {
                code: q.name,
                price: fmtPrice(q.close),
                pct: fmtPct(q.change_pct),
              })
      }
      className={cn(
        'tick-flash inline-flex cursor-pointer items-baseline gap-2 rounded-xs px-1 transition-colors duration-150 hover:bg-brand-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30',
        flash === 'up' && 'tick-flash-up',
        flash === 'down' && 'tick-flash-down',
      )}
    >
      <span className="font-mono text-caption font-semibold text-ink-800">{q.name}</span>
      <span className="font-mono text-caption text-ink-600 tnum">{fmtPrice(q.close)}</span>
      <span
        className={cn(
          'font-mono text-caption tnum',
          tone === 'up' ? 'text-up-700' : tone === 'down' ? 'text-down-700' : 'text-ink-500',
        )}
      >
        {tone === 'missing' ? '—' : tone === 'flat' ? '0.00%' : fmtPct(q.change_pct)}
      </span>
      <span className="ml-2 text-[8px] text-ink-300" aria-hidden="true">◆</span>
    </button>
  );
}

const TapeRow = memo(function TapeRow({
  items,
  flashes,
  onOpen,
}: {
  items: IndexSummary[];
  flashes: Record<string, 'up' | 'down'>;
  onOpen: (code: string) => void;
}) {
  return (
    <>
      {items.map((q) => (
        <TapeItem key={q.index_code} q={q} flash={flashes[q.index_code] ?? null} onOpen={onOpen} />
      ))}
    </>
  );
});

const EMPTY_INDICES: IndexSummary[] = [];

export default function IndexTape() {
  const { data } = usePolling(() => marketApi.overview(), 120_000);
  const items = data?.indices ?? EMPTY_INDICES;
  const flashes = useTickFlash(items, (q) => q.index_code, (q) => q.close ?? 0);
  const navigate = useNavigate();
  const openMarket = (code: string) => navigate(`/market?index=${encodeURIComponent(code)}`);

  return (
    <div className="marquee-track relative flex h-9 items-center overflow-hidden border-b border-line bg-paper-2/80">
      <div className="marquee-inner flex w-max animate-marquee items-center gap-8 whitespace-nowrap pl-4" aria-hidden={items.length === 0}>
        <TapeRow items={items} flashes={flashes} onOpen={openMarket} />
        <div className="contents" aria-hidden="true" inert>
          <TapeRow items={items} flashes={flashes} onOpen={openMarket} />
        </div>
      </div>
      <span className="absolute inset-y-0 right-0 z-10 flex items-stretch">
        <span className="pointer-events-none w-8 bg-gradient-to-r from-transparent to-paper-2" aria-hidden="true" />
        <span className="glass flex items-center border-l border-line bg-paper-2/95 px-3 text-micro font-medium text-ink-400">
          {t('日线行情')}
        </span>
      </span>
    </div>
  );
}
