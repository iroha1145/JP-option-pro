/**
 * InfoHint — 评分解释图标（圈 i）+ 悬停/聚焦/点按浮层
 *
 * 设计约束：
 * - 触发器是 span[role=button] 而非 <button>：评分常渲染在可点击行（motion.button）
 *   内部，真按钮会形成非法嵌套（TickerChip 同款教训）
 * - 点击/键盘触发要 stopPropagation，避免误触所在行的跳转
 * - 触屏无 hover，用受控 open 点按切换
 * - 文案来自 lib/indicatorHints（源自后端真实算法），本组件不编内容
 *
 * 浮层挂在 document.body（portal + position:fixed），不留在触发点旁边：
 * 读数几乎都在 `card-surface overflow-hidden` 之类的裁剪盒里，同层的绝对定位
 * 浮层会被祖先的 overflow 直接切掉——z-index 对 overflow 裁剪无效，堆叠顺序
 * 再高也救不回来。列表首行的说明因此被削去半截（新闻流实拍）。挂到 body 之后
 * 裁剪盒管不着它，方向也能按视口剩余空间自动翻面。
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import type { FocusEvent, KeyboardEvent, MouseEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';
import type { ScoreHint } from '@/lib/indicatorHints';
import { t } from '../../i18n/core.ts';

/** 浮层最大宽度（px），与下方 maxWidth 内联样式保持同一常量。 */
const TOOLTIP_MAX_WIDTH = 300;
/** 浮层与视口边缘至少保留的间距（px）。 */
const VIEWPORT_GUTTER = 8;
/** 浮层与触发点之间的间隙（px）。 */
const TRIGGER_GAP = 6;
/**
 * 抽屉 70/71、命令面板 80/81、确认对话框 85/86 之上，Toast 90 之下：
 * 说明浮层要盖住它所在的层，但不该盖住系统级提示。
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
  triggerClassName,
  children,
}: {
  hint: Omit<ScoreHint, 'body'> & { body: ReactNode };
  /** 浮层出现的方向；表格首行/页脚等边缘位置按需选 bottom */
  side?: 'top' | 'bottom';
  /** 水平对齐；靠近容器右缘时用 end，左缘时用 start */
  align?: 'start' | 'center' | 'end';
  size?: number;
  className?: string;
  /** 自定义按钮可撑满触发区域；不影响默认信息图标。 */
  triggerClassName?: string;
  /**
   * 自定义触发器。传了就用它当触发点（如绘图工具按钮本身），不再渲染那个「i」
   * 图标——工具条上再挂一排 i 是噪点，用户期待的是悬停按钮本体就出解释。
   * 此时外层不套 role="button"/tabIndex：children 往往已经是 <button>，
   * 嵌套可交互元素会让读屏念出两层控件。
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
  const hoverCloseRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const tooltipId = useId();
  /* 浮层挂在 body，CSS 的 group-hover/focus-within 够不着它，显示条件收归 state。
     aria 与真实显示一一对应：键盘用户聚焦时读屏（与 Playwright 的可访问树查询）
     都必须拿得到它。 */
  const exposed = !dismissed && (open || focused || hovered);

  const cancelHoverClose = () => {
    if (hoverCloseRef.current !== null) window.clearTimeout(hoverCloseRef.current);
    hoverCloseRef.current = null;
  };
  useEffect(() => () => {
    if (hoverCloseRef.current !== null) window.clearTimeout(hoverCloseRef.current);
  }, []);
  const enter = () => {
    cancelHoverClose();
    setDismissed(false);
    setHovered(true);
  };
  const leave = (event: MouseEvent) => {
    const next = event.relatedTarget as Node | null;
    if (next && next instanceof Node && (rootRef.current?.contains(next) || tooltipRef.current?.contains(next))) return;
    cancelHoverClose();
    // Leave enough time to cross the small gap into the body-hosted tooltip.
    hoverCloseRef.current = window.setTimeout(() => {
      hoverCloseRef.current = null;
      setHovered(false);
    }, 120);
  };
  const blur = (event: FocusEvent) => {
    const next = event.relatedTarget as Node | null;
    if (next && next instanceof Node && (rootRef.current?.contains(next) || tooltipRef.current?.contains(next))) return;
    setFocused(false);
    setOpen(false);
  };
  const dismiss = (event: KeyboardEvent) => {
    if (event.key !== 'Escape' || !exposed) return;
    event.preventDefault?.();
    event.stopPropagation();
    const trigger = triggerRef.current;
    if (document.activeElement && tooltipRef.current?.contains(document.activeElement) && trigger) {
      // Custom children usually supply their own button; its wrapper is not focusable.
      (trigger.querySelector<HTMLElement>('button,a[href],input,[tabindex]') ?? trigger).focus({ preventScroll: true });
    }
    cancelHoverClose();
    setOpen(false);
    setHovered(false);
    // Set this after restoring focus so onFocus cannot immediately reopen it.
    setDismissed(true);
  };
  const enterScrollArea = (event: KeyboardEvent) => {
    const tip = tooltipRef.current;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && tip && tip.scrollHeight > tip.clientHeight) {
      event.preventDefault();
      event.stopPropagation();
      tip.focus({ preventScroll: true });
    }
  };

  /**
   * 按视口摆位：水平夹在视口内，垂直空间不够就翻面。
   *
   * 水平只用触发点算——浮层宽度是确定的 min(300, 视口宽 − 2×gutter)。垂直必须
   * 量浮层自身高度（文案长短差很多），所以先渲染再定位，未定位时保持透明，
   * 避免先闪到错位置。
   */
  const place = useCallback(() => {
    const node = triggerRef.current;
    const tip = tooltipRef.current;
    if (!node || !tip || typeof window === 'undefined') return;
    const trigger = node.getBoundingClientRect();
    // 处于 hidden 子树（如未展开的 Accordion）时 rect 全为 0，算出来会整体错位。
    if (trigger.width === 0 && trigger.height === 0) return;

    // The soft keyboard can shrink/pan only the visual viewport, leaving the
    // layout viewport unchanged. Fixed coordinates use that layout origin.
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportWidth = viewport?.width ?? document.documentElement.clientWidth;
    const viewportHeight = viewport?.height ?? document.documentElement.clientHeight;
    tip.style.maxWidth = `${Math.max(0, Math.min(TOOLTIP_MAX_WIDTH, viewportWidth - VIEWPORT_GUTTER * 2))}px`;
    tip.style.maxHeight = `${Math.max(0, viewportHeight - VIEWPORT_GUTTER * 2)}px`;
    const width = tip.offsetWidth || Math.min(TOOLTIP_MAX_WIDTH, viewportWidth - VIEWPORT_GUTTER * 2);
    const preferred =
      align === 'start'
        ? trigger.left
        : align === 'end'
          ? trigger.right - width
          : trigger.left + trigger.width / 2 - width / 2;
    const leftmost = viewportLeft + VIEWPORT_GUTTER;
    const rightmost = Math.max(leftmost, viewportLeft + viewportWidth - width - VIEWPORT_GUTTER);
    const left = Math.min(Math.max(preferred, leftmost), rightmost);

    const height = tip.offsetHeight;
    const aboveTop = trigger.top - TRIGGER_GAP - height;
    const belowTop = trigger.bottom + TRIGGER_GAP;
    const topmost = viewportTop + VIEWPORT_GUTTER;
    const fitsAbove = aboveTop >= topmost;
    const fitsBelow = belowTop + height <= viewportTop + viewportHeight - VIEWPORT_GUTTER;
    const placeAbove = side === 'top' ? fitsAbove || !fitsBelow : !fitsBelow && fitsAbove;
    // Oversized explanations scroll inside the visible area instead of clipping.
    const lowest = Math.max(topmost, viewportTop + viewportHeight - height - VIEWPORT_GUTTER);
    const top = Math.min(Math.max(placeAbove ? aboveTop : belowTop, topmost), lowest);

    // 布局测量只更新浮层位置，不令整个触发控件在每次滚动时重渲染。
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.classList.add('is-shown');
  }, [align, side]);

  /* 显示期间跟住触发点：页面滚动、窗口缩放、上方内容变高都会让它移动。 */
  useLayoutEffect(() => {
    if (!exposed) return;
    place();
    // 财报等动态说明可能在显示期间变高，继续按新的尺寸避让视口。
    const observer = new ResizeObserver(place);
    if (tooltipRef.current) observer.observe(tooltipRef.current);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    window.visualViewport?.addEventListener('resize', place);
    window.visualViewport?.addEventListener('scroll', place);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
      window.visualViewport?.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('scroll', place);
    };
  }, [exposed, place]);

  /* 触屏点按打开后，点页面其他位置应关闭 */
  useEffect(() => {
    if (!exposed) return;
    const onDocPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node) && !tooltipRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setDismissed(true);
      }
    };
    document.addEventListener('pointerdown', onDocPointer);
    return () => document.removeEventListener('pointerdown', onDocPointer);
  }, [exposed]);

  return (
    <span
      ref={rootRef}
      className={cn('t-tt-wrap relative inline-flex align-middle', className)}
      onMouseEnter={enter}
      onMouseLeave={leave}
      onKeyDown={dismiss}
    >
      {children ? (
        <span
          ref={triggerRef}
          className={cn('inline-flex', triggerClassName)}
          aria-describedby={exposed ? tooltipId : undefined}
          onFocus={() => { setDismissed(false); setFocused(true); }}
          onBlur={blur}
          onKeyDown={enterScrollArea}
        >
          {children}
        </span>
      ) : (
        <span
          ref={triggerRef}
          role="button"
          tabIndex={0}
          aria-label={t('{title}：查看说明', { title: hint.title })}
          aria-expanded={exposed}
          aria-describedby={exposed ? tooltipId : undefined}
          onFocus={() => { setDismissed(false); setFocused(true); }}
          onBlur={blur}
          className={cn(
            't-tt-trigger inline-flex cursor-help items-center rounded-full text-ink-400 outline-none transition-colors duration-fast',
            'hover:text-brand-600 focus-visible:text-brand-600',
            open && 'text-brand-600',
          )}
          onClick={(event) => {
            event.stopPropagation();
            event.preventDefault();
            setDismissed(open);
            setOpen(!open);
          }}
          onKeyDown={(event) => {
            enterScrollArea(event);
            if (event.key === 'Enter' || event.key === ' ') {
              event.stopPropagation();
              event.preventDefault();
              setDismissed(open);
              setOpen(!open);
            }
          }}
        >
          <InfoGlyph size={size} />
        </span>
      )}

      {/* 收起时整个移出 DOM（审计 2.5.10）：常驻的 opacity-0 节点会被读屏当正文
          连读，每个 InfoHint 的几十字算法说明全部混进页面内容。 */}
      {exposed &&
        typeof document !== 'undefined' &&
        createPortal(
          <span
            ref={tooltipRef}
            id={tooltipId}
            role="tooltip"
            tabIndex={-1}
            onMouseEnter={enter}
            onMouseLeave={leave}
            onFocus={() => setFocused(true)}
            onBlur={blur}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              // Arrow/Page/End keys keep their native scroll behavior here.
              event.stopPropagation();
              dismiss(event);
            }}
            data-portal=""
            /* 内边距/圆角/底色/阴影全由 catalog .t-tt 供给（rounded-md、px-3
               这类会被后加载的 catalog 覆盖成死类，留着只会误导）；border 仍走
               设计系统的 line 色。 */
            className={cn(
              't-tt w-max border border-line text-left',
            )}
            style={{
              zIndex: TOOLTIP_Z_INDEX,
              left: 0,
              top: 0,
              pointerEvents: 'auto',
              overflowY: 'auto',
              overscrollBehavior: 'contain',
              boxSizing: 'border-box',
              maxHeight: 'calc(100dvh - 16px)',
              maxWidth: `min(${TOOLTIP_MAX_WIDTH}px, calc(100vw - ${
                VIEWPORT_GUTTER * 2
              }px))`,
            }}
          >
            {/* indicatorHints 的 title/body/note 在定义处已经 t() 过：再包一层会在
                EN/JA 下拿译文回查词典，DEV 的缺译告警被几十条假警报淹没。 */}
            <span className="block text-caption font-medium text-ink-800">{hint.title}</span>
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
