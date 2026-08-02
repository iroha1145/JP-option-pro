/**
 * InfoHint — 指标解释图标（圈 i）+ 悬停/聚焦/点按浮层。美版组件移植。
 *
 * 设计约束（沿袭原版的教训）：
 * - 触发器是 span[role=button] 而非 <button>：说明常渲染在可点击行内部，
 *   真按钮会形成非法嵌套。
 * - 点击/键盘触发要 stopPropagation，避免误触所在行的跳转。
 * - 触屏无 hover，用受控 open 点按切换。
 * - 文案来自 lib/indicatorHints（描述后端真实算法），本组件不编内容。
 * - 浮层挂在 document.body（portal + fixed）：读数几乎都在 overflow 裁剪盒里，
 *   同层绝对定位会被祖先 overflow 切掉；挂 body 后按视口剩余空间自动翻面。
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';
import type { ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';

const TOOLTIP_MAX_WIDTH = 300;
const VIEWPORT_GUTTER = 8;
const TRIGGER_GAP = 6;
const TOOLTIP_Z_INDEX = 88;

function InfoGlyph({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="8" cy="8" r="6.6" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="5.1" r="0.9" fill="currentColor" />
      <path d="M8 7.4v3.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export default function InfoHint({
  hint,
  side = 'top',
  align = 'center',
  size = 13,
  className,
}: {
  hint: ScoreHint;
  side?: 'top' | 'bottom';
  align?: 'start' | 'center' | 'end';
  size?: number;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const tooltipId = useId();
  const exposed = open || focused || hovered;
  const [coords, setCoords] = useState<{ left: number; top: number } | null>(null);

  /* 按视口摆位：水平夹在视口内，垂直空间不够就翻面。先渲染量高度再定位。 */
  const place = useCallback(() => {
    const node = triggerRef.current;
    const tip = tooltipRef.current;
    if (!node || !tip || typeof window === 'undefined') return;
    const trigger = node.getBoundingClientRect();
    if (trigger.width === 0 && trigger.height === 0) return;

    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    const width = Math.min(TOOLTIP_MAX_WIDTH, viewportWidth - VIEWPORT_GUTTER * 2);
    const preferred =
      align === 'start'
        ? trigger.left
        : align === 'end'
          ? trigger.right - width
          : trigger.left + trigger.width / 2 - width / 2;
    const rightmost = Math.max(VIEWPORT_GUTTER, viewportWidth - width - VIEWPORT_GUTTER);
    const left = Math.min(Math.max(preferred, VIEWPORT_GUTTER), rightmost);

    const height = tip.offsetHeight;
    const aboveTop = trigger.top - TRIGGER_GAP - height;
    const belowTop = trigger.bottom + TRIGGER_GAP;
    const fitsAbove = aboveTop >= VIEWPORT_GUTTER;
    const fitsBelow = belowTop + height <= viewportHeight - VIEWPORT_GUTTER;
    const placeAbove = side === 'top' ? fitsAbove || !fitsBelow : !fitsBelow && fitsAbove;
    const lowest = Math.max(VIEWPORT_GUTTER, viewportHeight - height - VIEWPORT_GUTTER);
    const top = Math.min(Math.max(placeAbove ? aboveTop : belowTop, VIEWPORT_GUTTER), lowest);

    setCoords({ left, top });
  }, [align, side]);

  useLayoutEffect(() => {
    if (!exposed) {
      setCoords(null);
      return;
    }
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [exposed, place]);

  useEffect(() => {
    if (!open) return;
    const onDocPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onDocPointer);
    return () => document.removeEventListener('pointerdown', onDocPointer);
  }, [open]);

  return (
    <span
      ref={rootRef}
      className={cn('relative inline-flex align-middle', className)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => {
        setHovered(false);
        setOpen(false);
      }}
    >
      <span
        ref={triggerRef}
        role="button"
        tabIndex={0}
        aria-label={t('{title}：查看指标说明', { title: hint.title })}
        aria-expanded={open}
        aria-describedby={exposed ? tooltipId : undefined}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className={cn(
          'inline-flex cursor-help items-center rounded-full text-ink-300 outline-none transition-colors duration-fast',
          'hover:text-brand-600 focus-visible:text-brand-600',
          open && 'text-brand-600',
        )}
        onClick={(event) => {
          event.stopPropagation();
          event.preventDefault();
          setOpen((value) => !value);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.stopPropagation();
            event.preventDefault();
            setOpen((value) => !value);
          } else if (event.key === 'Escape') {
            setOpen(false);
          }
        }}
      >
        <InfoGlyph size={size} />
      </span>

      {/* 收起时整个移出 DOM：常驻 opacity-0 节点会被读屏当正文连读。 */}
      {exposed &&
        typeof document !== 'undefined' &&
        createPortal(
          <span
            ref={tooltipRef}
            id={tooltipId}
            role="tooltip"
            className={cn(
              'pointer-events-none fixed w-max rounded-md border border-line bg-card px-3 py-2.5 text-left shadow-sh-3',
              'transition-opacity duration-fast',
              coords ? 'opacity-100' : 'opacity-0',
            )}
            style={{
              zIndex: TOOLTIP_Z_INDEX,
              left: coords?.left ?? 0,
              top: coords?.top ?? 0,
              maxWidth: `min(${TOOLTIP_MAX_WIDTH}px, calc(100vw - ${VIEWPORT_GUTTER * 2}px))`,
            }}
          >
            {/* indicatorHints 的 title/body/note 在定义处已 t()：不再二次翻译。 */}
            <span className="block text-caption font-semibold text-ink-800">{hint.title}</span>
            <span className="mt-1 block whitespace-normal text-micro leading-relaxed text-ink-600">
              {hint.body}
            </span>
            {hint.note && (
              <span className="mt-1 block whitespace-normal text-micro leading-relaxed text-ink-400">
                {hint.note}
              </span>
            )}
          </span>,
          document.body,
        )}
    </span>
  );
}
