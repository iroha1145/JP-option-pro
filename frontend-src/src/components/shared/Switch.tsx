/**
 * Switch —— 全站唯一的拨杆开关（transitions.dev 27-toggle：拇指双段回弹）。
 * 尺寸走 size 三档；is-init 只在首次交互后加，避免挂载时空放回弹。
 */
import { useState, type CSSProperties } from 'react';
import { cn } from '@/lib/utils';

export type SwitchSize = 'sm' | 'md' | 'lg';

const GEOMETRY: Record<SwitchSize, { track: string; thumb: string; travel: number }> = {
  sm: { track: 'h-4 w-7', thumb: 'size-3', travel: 12 },
  md: { track: 'h-[18px] w-8', thumb: 'size-[14px]', travel: 14 },
  lg: { track: 'h-5 w-9', thumb: 'size-4', travel: 16 },
};

export default function Switch({
  checked,
  onToggle,
  label,
  disabled,
  size = 'md',
  className,
  id,
}: {
  checked: boolean;
  onToggle: () => void;
  label?: string;
  disabled?: boolean;
  size?: SwitchSize;
  className?: string;
  id?: string;
}) {
  const [init, setInit] = useState(false);
  const geo = GEOMETRY[size];
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        if (disabled) return;
        setInit(true);
        onToggle();
      }}
      data-on={checked ? 'true' : 'false'}
      style={{ '--toggle-travel': `${geo.travel}px` } as CSSProperties}
      className={cn(
        't-toggle relative shrink-0 rounded-pill shadow-track transition-transform duration-fast active:scale-95',
        'before:absolute before:-inset-2 before:content-[""] sm:before:hidden',
        init && 'is-init',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30',
        geo.track,
        checked ? 'bg-brand-600' : 'bg-ink-300',
        disabled && 'cursor-not-allowed opacity-40',
        className,
      )}
    >
      <span className={cn('t-toggle-thumb absolute left-[2px] top-[2px] rounded-full bg-card shadow-knob', geo.thumb)} />
    </button>
  );
}
