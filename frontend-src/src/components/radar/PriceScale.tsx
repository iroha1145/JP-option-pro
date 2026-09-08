/**
 * 雷达价格标尺：圆点、短刻线与文字价位。
 * 缺失价位不画、不补零；目标位日本站后端没有独立字段时留空。
 */
import { motion } from 'framer-motion';
import { usePrefersReducedMotion } from '@/hooks/usePrefersReducedMotion';
import { cn } from '@/lib/utils';
import { DUR_UI, EASE_PAPER } from '@/lib/motion';
import { fmtPrice } from '@/lib/format';
import NumberTicker from '@/components/shared/NumberTicker';
import { t } from '@/i18n/core';

interface PriceScaleProps {
  invalidation: number | null | undefined;
  trigger: number | null | undefined;
  target?: number | null | undefined;
  current: number | null | undefined;
  large?: boolean;
  flash?: 'up' | 'down' | null;
  className?: string;
}

interface MarkerDef {
  key: 'invalid' | 'trigger' | 'target';
  label: string;
  value: number;
}

const fin = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v);

export default function PriceScale({
  invalidation,
  trigger,
  target,
  current,
  large = false,
  flash = null,
  className,
}: PriceScaleProps) {
  const reduced = usePrefersReducedMotion();
  const known = [invalidation, trigger, target, current].filter(fin);
  if (known.length < 2 || !fin(current)) {
    return (
      <div className={cn('radar-price-scale w-full', className)} role="img" aria-label={t('价格标尺数据不足')}>
        <div className="flex h-9 items-center justify-center rounded-md bg-card-warm text-micro text-ink-400">
          {t('— 价位数据不足')}
        </div>
      </div>
    );
  }

  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const span = Math.max(0.0001, hi - lo);
  const pad = span * 0.06;
  const min = lo - pad;
  const max = hi + pad;
  const x = (v: number) => Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100));
  const currentPct = x(current);
  const markers: MarkerDef[] = [
    { key: 'invalid' as const, label: t('失效'), value: invalidation as number },
    { key: 'trigger' as const, label: t('触发'), value: trigger as number },
    { key: 'target' as const, label: t('目标'), value: target as number },
  ].filter((marker) => fin(marker.value));

  return (
    <div
      className={cn('radar-price-scale w-full', large && 'radar-price-scale-large', className)}
      role="img"
      aria-label={t('价格标尺：失效 {invalid}，触发 {trigger}，目标 {target}，现价 {current}', {
        invalid: fin(invalidation) ? fmtPrice(invalidation) : '—',
        trigger: fin(trigger) ? fmtPrice(trigger) : '—',
        target: fin(target) ? fmtPrice(target) : '—',
        current: fmtPrice(current),
      })}
    >
      <div aria-hidden="true">
        <div className="relative h-7">
          <motion.span
            initial={false}
            animate={{ left: `${currentPct}%`, x: `${-currentPct}%` }}
            transition={{ duration: reduced ? 0 : DUR_UI, ease: EASE_PAPER }}
            className="radar-current-readout absolute top-0"
          >
            <span>{t('现价')}</span>
            <strong className={cn('tick-flash rounded px-0.5 tnum', flash === 'up' && 'tick-flash-up', flash === 'down' && 'tick-flash-down')}>
              <NumberTicker text={fmtPrice(current)} />
            </strong>
          </motion.span>
        </div>

        <div className="radar-price-track relative h-[4px] rounded-full">
          {markers.map((marker) => (
            <span
              key={marker.key}
              className={cn('radar-reference-mark', `radar-reference-${marker.key}`)}
              style={{ left: `${x(marker.value)}%` }}
              data-price-marker={marker.key}
            />
          ))}
          <motion.span
            initial={false}
            animate={{ left: `${currentPct}%` }}
            transition={{ duration: reduced ? 0 : DUR_UI, ease: EASE_PAPER }}
            className="absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2"
            data-price-marker="current"
          >
            <span className="radar-price-cursor" />
          </motion.span>
        </div>

        <dl className="radar-price-key" style={{ gridTemplateColumns: `repeat(${markers.length}, minmax(0, 1fr))` }}>
          {markers.map((marker) => (
            <div key={marker.key} className="min-w-0" data-price-reference={marker.key}>
              <dt>
                <span className={cn('radar-reference-glyph', `radar-reference-${marker.key}`)} />
                {marker.label}
              </dt>
              <dd className="tnum">{fmtPrice(marker.value)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
