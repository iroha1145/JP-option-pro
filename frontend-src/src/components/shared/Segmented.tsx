/** Segmented 分段切换：滑块走 beUI / transitions.dev 弹簧 */
import { useLayoutEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

interface SegmentedProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
  ariaLabel?: string;
}

export default function Segmented<T extends string>({ options, value, onChange, className, ariaLabel }: SegmentedProps<T>) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const idx = options.findIndex((o) => o.value === value);
    const btn = wrap.children[idx + 1] as HTMLElement | undefined; // +1 跳过滑块
    if (btn) setThumb({ left: btn.offsetLeft, width: btn.offsetWidth });
  }, [value, options]);

  return (
    <div
      ref={wrapRef}
      role="tablist"
      aria-label={ariaLabel}
      /* max-w-full + 横スクロール: 英語ラベルは中文の 2〜3 倍幅になり
         （"Triggered/Confirmed/Watching/Failed/All" で 385px）、375px の
         端末では素の inline-flex が文書ごと横に溢れる。滑り子は
         offsetLeft 基準なのでスクロールしても追従する。 */
      className={cn(
        'no-scrollbar relative inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-line bg-card-warm p-0.5',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="absolute top-0.5 bottom-0.5 rounded-[4px] bg-card shadow-btn transition-[left,width,opacity] duration-ui ease-spring"
        style={thumb ? { left: thumb.left, width: thumb.width } : { opacity: 0 }}
      />
      {options.map((o, index) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          /* tablist 的标准键盘行为（审计 P3-5）：roving tabindex + 左右方向键 +
             Home/End。旧实现只有 role，Tab 会逐个停在每一项，方向键完全无效。 */
          tabIndex={value === o.value ? 0 : -1}
          onClick={() => onChange(o.value)}
          onKeyDown={(event) => {
            const step =
              event.key === 'ArrowRight' || event.key === 'ArrowDown'
                ? 1
                : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
                  ? -1
                  : 0;
            let target = -1;
            if (step !== 0) {
              target = (index + step + options.length) % options.length;
            } else if (event.key === 'Home') {
              target = 0;
            } else if (event.key === 'End') {
              target = options.length - 1;
            }
            if (target < 0) return;
            event.preventDefault();
            onChange(options[target].value);
            const next = wrapRef.current?.children[target + 1];
            if (next instanceof HTMLElement) next.focus();
          }}
          className={cn(
            'relative z-10 whitespace-nowrap rounded-[4px] px-3 py-1 text-caption font-medium transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30',
            value === o.value ? 'text-ink-800' : 'text-ink-400 hover:text-ink-600',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
