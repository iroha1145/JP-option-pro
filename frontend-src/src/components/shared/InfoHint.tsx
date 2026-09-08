/**
 * InfoHint — 指标解释图标（圈 i）+ 悬停/聚焦/点按浮层。
 *
 * 设计约束（沿袭美版的教训）：
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
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';
import type { ScoreHint } from '@/lib/indicatorHints';
import { t } from '@/i18n/core';

const TOOLTIP_MAX_WIDTH = 300;
const VIEWPORT_GUTTER = 8;
const TRIGGER_GAP = 6;
/**
 * 抽屉 / 命令面板之上，Toast 之下：说明浮层要盖住它所在的层，
 * 但不该盖住系统级提示。
 */
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
  children,
}: {
  hint: ScoreHint;
  /** 浮层出现的方向；表格首行/页脚等边缘位置按需选 bottom */
  side?: 'top' | 'bottom';
  /** 水平对齐；靠近容器右缘时用 end，左缘时用 start */
  align?: 'start' | 'center' | 'end';
  size?: number;
  className?: string;
  /**
   * 自定义触发器。传了就用它当触发点（如徽章本身），不再渲染那个「i」
   * 图标。此时外层不套 role="button"/tabIndex：children 往往已经是
   * 可交互元素，嵌套会让读屏念出两层控件。
   */
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const tooltipId = useId();
  /* 浮层挂在 body，CSS 的 group-hover/focus-within 够不着它，显示条件收归 state。
     aria 与真实显示一一对应：键盘用户聚焦时读屏必须拿得到它。 */
  const exposed = !dismissed && (open || focused || hovered);

  /**
   * 按视口摆位：水平夹在视口内，垂直空间不够就翻面。
   * 水平只用触发点算；垂直必须量浮层自身高度，所以先渲染再定位。
   */
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

    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.classList.add('is-shown');
  }, [align, side]);

  useLayoutEffect(() => {
    if (!exposed) return;
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
      className={cn('t-tt-wrap relative inline-flex align-middle', className)}
      onMouseEnter={() => {
        setDismissed(false);
        setHovered(true);
      }}
      onMouseLeave={() => {
        setHovered(false);
        setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Escape' || !exposed) return;
        event.stopPropagation();
        setOpen(false);
        setDismissed(true);
      }}
    >
      {children ? (
        <span
          ref={triggerRef}
          className="inline-flex"
          aria-describedby={exposed ? tooltipId : undefined}
          onFocus={() => {
            setDismissed(false);
            setFocused(true);
          }}
          onBlur={() => setFocused(false)}
        >
          {children}
        </span>
      ) : (
        <span
          ref={triggerRef}
          role="button"
          tabIndex={0}
          aria-label={t('{title}：查看指标说明', { title: hint.title })}
          aria-expanded={exposed}
          aria-describedby={exposed ? tooltipId : undefined}
          onFocus={() => {
            setDismissed(false);
            setFocused(true);
          }}
          onBlur={() => setFocused(false)}
          className={cn(
            't-tt-trigger inline-flex cursor-help items-center rounded-full text-ink-300 outline-none transition-colors duration-fast',
            'hover:text-brand-600 focus-visible:text-brand-600',
            open && 'text-brand-600',
          )}
          onClick={(event) => {
            event.stopPropagation();
            event.preventDefault();
            setDismissed(false);
            setOpen((value) => !value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.stopPropagation();
              event.preventDefault();
              setDismissed(false);
              setOpen((value) => !value);
            }
          }}
        >
          <InfoGlyph size={size} />
        </span>
      )}

      {exposed &&
        typeof document !== 'undefined' &&
        createPortal(
          <span
            ref={tooltipRef}
            id={tooltipId}
            role="tooltip"
            data-portal=""
            className="t-tt pointer-events-none w-max border border-line text-left"
            style={{
              zIndex: TOOLTIP_Z_INDEX,
              left: 0,
              top: 0,
              maxWidth: `min(${TOOLTIP_MAX_WIDTH}px, calc(100vw - ${VIEWPORT_GUTTER * 2}px))`,
            }}
          >
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
