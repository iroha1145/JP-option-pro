import { cn } from '@/lib/utils';

/** 日股没有美股 Logo 资产：用代码首字砖代替 TickerLogo。 */
export default function CodeMark({
  code,
  size = 24,
  className,
}: {
  code: string;
  size?: number;
  className?: string;
}) {
  const glyph = (code.replace(/\D/g, '').slice(-2) || code.slice(0, 2)).slice(0, 2);
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-md border border-line bg-card-warm font-mono font-semibold text-brand-700',
        className,
      )}
      style={{ width: size, height: size, fontSize: Math.max(9, Math.round(size * 0.38)) }}
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
}
