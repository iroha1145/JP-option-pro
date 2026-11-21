/**
 * 手绘细线图标库（design.md §5）
 * viewBox 24 · stroke 1.6 · round 端点/接合 · currentColor
 * 允许 ≤0.3px 手绘抖动；主体落在 20×20 安全区。
 */
import { Children, Fragment, useCallback, useEffect, useRef, type ReactElement, type ReactNode, type SVGProps } from 'react';

export type IconName =
  | 'radar' | 'crosshair' | 'candle' | 'layers' | 'calendar-spark' | 'bolt' | 'star-line'
  | 'filter-funnel' | 'search' | 'command' | 'clock' | 'bell' | 'sun' | 'moon'
  | 'arrow-up-right' | 'arrow-down-right' | 'chevron-down' | 'chevron-right'
  | 'dots-grid' | 'spark-ai' | 'shield' | 'target' | 'flag' | 'x' | 'plus'
  | 'refresh' | 'wallet-gauge' | 'doc-quote' | 'logout' | 'minus'
  | 'check' | 'menu' | 'display' | 'list' | 'cards' | 'channel' | 'rect' | 'sliders';

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
  /** Opt in to a single local response from an enclosing icon-motion-trigger. */
  motion?: boolean;
  /** A brief response for selection managed outside DOM focus, such as a command list. */
  motionActive?: boolean;
}

const PATHS: Record<IconName, ReactElement> = {
  /* 雷达：碟形天线 —— 斜切碟面朝右上 + 馈源杆与信号球 + 左下三角支架 */
  radar: (
    <>
      <path d="M7.1 5.5 A7.2 7.2 0 0 0 17.3 15.7 Z" />
      <path d="M12.2 10.6 L16.3 6.5" />
      <circle cx="17.5" cy="5.3" r="1.7" fill="currentColor" stroke="none" />
      <path d="M6.6 17.4 L9.8 20.8 H3.4 Z" />
    </>
  ),
  crosshair: (
    <>
      <circle cx="12" cy="12" r="6.6" />
      <path d="M12 2.8v3.1M12 18.1v3.1M2.8 12h3.1M18.1 12h3.1" />
    </>
  ),
  candle: (
    <>
      <path d="M7.2 3.4v2.6M7.2 15.6v3.4" />
      <rect x="4.7" y="6" width="5" height="9.6" rx="1" />
      <path d="M16.8 5.2v2.2M16.8 16.8v2.6" />
      <rect x="14.3" y="7.4" width="5" height="9.4" rx="1" />
    </>
  ),
  layers: (
    <>
      <path d="M12 3.4 20.4 8 12 12.6 3.6 8 12 3.4Z" />
      <path d="M4.2 12.4 12 16.6l7.8-4.2" />
      <path d="M4.2 16.3 12 20.5l7.8-4.2" />
    </>
  ),
  'calendar-spark': (
    <>
      <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2" />
      <path d="M3.7 9.6h16.7M8.2 3.2v3.4M15.8 3.2v3.4" />
      <path d="M12 12.1l.9 2 2 .9-2 .9-.9 2-.9-2-2-.9 2-.9.9-2Z" />
    </>
  ),
  bolt: <path d="M13.2 2.9 5.8 13.4h4.9l-1.3 7.7 7.6-10.6h-5l1.2-7.6Z" />,
  'star-line': (
    <path d="M12 3.6l2.6 5.2 5.7.9-4.1 4 1 5.7-5.2-2.7-5.1 2.7.9-5.7-4-4 5.7-.9L12 3.6Z" />
  ),
  'filter-funnel': <path d="M3.8 5.1h16.4l-6.3 7.2v6.2l-3.8 2v-8.2L3.8 5.1Z" />,
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.4" />
      <path d="M15.6 15.6 20.4 20.4" />
    </>
  ),
  command: (
    <path d="M8.6 8.6h6.8v6.8H8.6zM8.6 8.6H6.2a2.4 2.4 0 1 1 2.4-2.4v2.4ZM15.4 8.6h2.4a2.4 2.4 0 1 0-2.4-2.4v2.4ZM8.6 15.4H6.2a2.4 2.4 0 1 0 2.4 2.4v-2.4ZM15.4 15.4h2.4a2.4 2.4 0 1 1-2.4 2.4v-2.4Z" />
  ),
  'clock': (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.2v5l3.4 2" />
      <circle cx="18.6" cy="5.4" r="1.6" />
    </>
  ),
  bell: (
    <>
      <path d="M6.1 9.4a5.9 5.9 0 0 1 11.8 0c0 4.4 1.4 5.9 1.4 5.9H4.7s1.4-1.5 1.4-5.9" />
      <path d="M10.3 19.4a1.9 1.9 0 0 0 3.4 0" />
    </>
  ),
  'sun': (
    <>
      <circle cx="12" cy="14.4" r="4.4" />
      <path d="M12 6.4V4.2M6.1 8.1 4.6 6.6M17.9 8.1l1.5-1.5M3.4 14.4H1.9M22.1 14.4h-1.5M4 20.4h16" />
    </>
  ),
  'moon': (
    <>
      <path d="M19.4 13.9A7.6 7.6 0 1 1 10.1 4.6a6.2 6.2 0 0 0 9.3 9.3Z" />
      <path d="M17.6 3.6l.5 1.3 1.3.5-1.3.5-.5 1.3-.5-1.3-1.3-.5 1.3-.5.5-1.3Z" />
    </>
  ),
  display: (
    <>
      <rect x="3.4" y="5" width="17.2" height="11.2" rx="1.8" />
      <path d="M8.2 19.4h7.6M12 16.2v3.2" />
    </>
  ),
  'arrow-up-right': <path d="M6.8 17.2 17.2 6.8M8.1 6.6h9.3v9.3" />,
  'arrow-down-right': <path d="M6.8 6.8l10.4 10.4M17.4 8.1v9.3H8.1" />,
  'chevron-down': <path d="m5.8 9.2 6.2 6.1 6.2-6.1" />,
  'chevron-right': <path d="m9.4 5.9 6.1 6.1-6.1 6.2" />,
  'dots-grid': (
    <>
      <circle cx="7.2" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="12" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="16.8" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="7.2" cy="12" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="16.8" cy="12" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="7.2" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="12" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="16.8" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
    </>
  ),
  /* v8.1：弃四角星——「sparkle+AI」是生成式设计的头号刻板组合。
     改「双弧夹核心点」：从信息流中聚焦提炼一个结论，正是本产品 AI 的职责。 */
  'spark-ai': (
    <>
      <path d="M8.2 4.9a9.7 9.7 0 0 0 0 14.2" />
      <path d="M15.8 4.9a9.7 9.7 0 0 1 0 14.2" />
      <circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.2 5 6v5.2c0 4.4 3 7.6 7 9.6 4-2 7-5.2 7-9.6V6l-7-2.8Z" />
      <path d="M8.8 12l2.2 2.2 4.2-4.4" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="4.6" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </>
  ),
  flag: (
    <>
      <path d="M5.4 21V4.2" />
      <path d="M5.4 4.6c4.6-2 7 1.8 12.4 0v8.8c-5.4 1.8-7.8-2-12.4 0" />
    </>
  ),
  x: <path d="m6.2 6.2 11.6 11.6M17.8 6.2 6.2 17.8" />,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: (
    <>
      <path d="M19.8 12a7.8 7.8 0 1 1-2.1-5.3" />
      <path d="M19.9 3.4v3.6h-3.6" />
    </>
  ),
  'wallet-gauge': (
    <>
      <path d="M4.4 15.8a8 8 0 1 1 15.2 0" />
      <path d="m12 15.6 3.4-4.6" />
      <path d="M8.2 20.4h7.6" />
    </>
  ),
  'doc-quote': (
    <>
      <path d="M7.2 4.4h9.6a1.8 1.8 0 0 1 1.8 1.8v11.6a1.8 1.8 0 0 1-1.8 1.8H7.2a1.8 1.8 0 0 1-1.8-1.8V6.2a1.8 1.8 0 0 1 1.8-1.8Z" />
      <path d="M9 9.2c-1 .5-1.6 1.3-1.6 2.5h1.9v2.6H7V11c0-1.6.8-2.7 2.3-3.3L9 9.2ZM14.4 9.2c-1 .5-1.6 1.3-1.6 2.5h1.9v2.6h-2.3V11c0-1.6.8-2.7 2.3-3.3l-.3 1.5Z" />
    </>
  ),
  logout: (
    <>
      <path d="M14.6 8.2V6.4a1.8 1.8 0 0 0-1.8-1.8H6.2a1.8 1.8 0 0 0-1.8 1.8v11.2a1.8 1.8 0 0 0 1.8 1.8h6.6a1.8 1.8 0 0 0 1.8-1.8v-1.8" />
      <path d="M9.8 12h10.4M17.2 8.6l3.4 3.4-3.4 3.4" />
    </>
  ),
  minus: <path d="M5 12h14" />,
  check: <path d="m4.8 12.8 4.6 4.6L19.2 6.6" />,
  menu: <path d="M4 7.2h16M4 12h16M4 16.8h10" />,
  list: <path d="M8.4 6.4h11.2M8.4 12h11.2M8.4 17.6h11.2M4.2 6.4h.9M4.2 12h.9M4.2 17.6h.9" />,
  cards: (
    <>
      <rect x="3.4" y="3.6" width="8.2" height="8.2" rx="1.6" />
      <rect x="12.4" y="3.6" width="8.2" height="8.2" rx="1.6" />
      <rect x="3.4" y="12.6" width="8.2" height="8.2" rx="1.6" />
      <rect x="12.4" y="12.6" width="8.2" height="8.2" rx="1.6" />
    </>
  ),
  /* 地球经纬线：外圈 + 中央经线「透镜」+ 赤道横线，语言切换用 */
  channel: (
    <>
      <path d="M4.2 16.2 19.6 8.4" />
      <path d="M4.6 19.2 20 11.4" />
    </>
  ),
  rect: <rect x="5" y="6.2" width="14" height="11.6" rx="1.4" />,
  /* 设置：三条滑轨各带一个旋钮（页头合并后的显示设置入口） */
  sliders: (
    <>
      <path d="M4.4 7h8.3M16.7 7h2.9M4.4 12h2.9M11.3 12h8.3M4.4 17h6.3M14.7 17h4.9" />
      <circle cx="14.7" cy="7" r="2" />
      <circle cx="9.3" cy="12" r="2" />
      <circle cx="12.7" cy="17" r="2" />
    </>
  ),
};

export const MOTION_NAMES = new Set<IconName>([
  'radar', 'crosshair', 'candle', 'layers', 'calendar-spark', 'bolt', 'star-line',
  'filter-funnel', 'search', 'command', 'clock', 'bell', 'sun', 'moon',
  'arrow-up-right', 'arrow-down-right', 'chevron-down', 'chevron-right',
  'dots-grid', 'spark-ai', 'shield', 'target', 'flag', 'x', 'plus',
  'refresh', 'wallet-gauge', 'doc-quote', 'logout', 'minus',
  'check', 'menu', 'display', 'channel', 'rect', 'sliders',
]);

function motionPaths(name: IconName) {
  // Keep each slider's interrupted rail and knob together: moving only the knob
  // would reveal a gap in the hand-drawn rail. All coordinates stay unchanged.
  if (name === 'sliders') {
    return <>
      <g data-icon-part="0"><path d="M4.4 7h8.3M16.7 7h2.9" /><circle cx="14.7" cy="7" r="2" /></g>
      <g data-icon-part="1"><path d="M4.4 12h2.9M11.3 12h8.3" /><circle cx="9.3" cy="12" r="2" /></g>
      <g data-icon-part="2"><path d="M4.4 17h6.3M14.7 17h4.9" /><circle cx="12.7" cy="17" r="2" /></g>
    </>;
  }
  if (name === 'menu') {
    return <>
      <g data-icon-part="0"><path d="M4 7.2h16" /></g>
      <g data-icon-part="1"><path d="M4 12h16" /></g>
      <g data-icon-part="2"><path d="M4 16.8h10" /></g>
    </>;
  }
  if (name === 'x') {
    return <>
      <g data-icon-part="0"><path d="m6.2 6.2 11.6 11.6" /></g>
      <g data-icon-part="1"><path d="M17.8 6.2 6.2 17.8" /></g>
    </>;
  }
  if (name === 'plus') {
    return <>
      <g data-icon-part="0"><path d="M12 5v14" /></g>
      <g data-icon-part="1"><path d="M5 12h14" /></g>
    </>;
  }
  if (name === 'dots-grid') {
    return <>
      <g data-icon-part="0">
        <circle cx="7.2" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="12" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="16.8" cy="7.2" r="1.05" fill="currentColor" stroke="none" />
      </g>
      <g data-icon-part="1">
        <circle cx="7.2" cy="12" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="12" cy="12" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="16.8" cy="12" r="1.05" fill="currentColor" stroke="none" />
      </g>
      <g data-icon-part="2">
        <circle cx="7.2" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="12" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
        <circle cx="16.8" cy="16.8" r="1.05" fill="currentColor" stroke="none" />
      </g>
    </>;
  }
  const drawing = PATHS[name];
  const parts = drawing.type === Fragment
    ? (drawing as ReactElement<{ children: ReactNode }>).props.children
    : drawing;
  return Children.toArray(parts).map((part, index) => (
    <g key={index} data-icon-part={index}>{part}</g>
  ));
}

export function Icon({ name, size = 18, motion = false, motionActive = false, ref, ...rest }: IconProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const playRef = useRef<(() => void) | null>(null);
  const attachRef = useCallback((node: SVGSVGElement | null) => {
    svgRef.current = node;
    const cleanup = typeof ref === 'function' ? ref(node) : undefined;
    if (ref && typeof ref !== 'function') ref.current = node;
    return () => {
      svgRef.current = null;
      if (typeof cleanup === 'function') cleanup();
      else if (typeof ref === 'function') ref(null);
      else if (ref) ref.current = null;
    };
  }, [ref]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!motion || !MOTION_NAMES.has(name) || !svg) return;
    // Retain finished CSSAnimation objects as browsers may omit them from
    // getAnimations() once their no-fill effect has ended. No timers or state.
    let previousAnimations: CSSAnimation[] = [];
    const play = () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches
        || svg.closest(':disabled, [disabled], [aria-disabled="true"]')) return;
      const current = svg.getAnimations({ subtree: true }).filter((animation): animation is CSSAnimation => (
        animation instanceof CSSAnimation
        && animation.effect instanceof KeyframeEffect
        && animation.effect.target instanceof SVGGElement
        && animation.effect.target.parentNode === svg
        && animation.effect.target.hasAttribute('data-icon-part')
      ));
      // A staggered part can finish before its neighbour. Keep its completed
      // object for the next gesture instead of replacing the cache with only
      // the still-running subset returned by getAnimations().
      previousAnimations = [...new Set([...previousAnimations, ...current])]
        .filter(animation => animation.playState !== 'idle');
      // Pointer entry, focus and press can arrive during the same gesture.
      // Let it complete instead of snapping every part back to its first frame.
      if (previousAnimations.some(animation => animation.playState === 'running')) return;
      for (const animation of previousAnimations) {
        // CSS cancels these objects when disabled or reduced motion is enabled.
        if (animation.playState === 'idle') continue;
        animation.currentTime = 0;
        animation.play();
      }
    };
    playRef.current = play;
    const trigger = svg.closest('.icon-motion-trigger');
    const pointerEnter = (event: Event) => {
      if ((event as PointerEvent).pointerType === 'mouse'
        && window.matchMedia('(hover: hover) and (pointer: fine)').matches) play();
    };
    const pointerDown = () => play();
    const focus = () => { if (trigger?.matches(':focus-visible')) play(); };
    const keyDown = (event: Event) => {
      const key = event as KeyboardEvent;
      if (!key.repeat && (key.key === 'Enter' || key.key === ' ')) play();
    };
    trigger?.addEventListener('pointerenter', pointerEnter);
    trigger?.addEventListener('pointerdown', pointerDown);
    trigger?.addEventListener('focus', focus);
    trigger?.addEventListener('keydown', keyDown);
    return () => {
      trigger?.removeEventListener('pointerenter', pointerEnter);
      trigger?.removeEventListener('pointerdown', pointerDown);
      trigger?.removeEventListener('focus', focus);
      trigger?.removeEventListener('keydown', keyDown);
      playRef.current = null;
    };
  }, [motion, name]);

  useEffect(() => {
    if (motion && motionActive) playRef.current?.();
  }, [motion, motionActive, name]);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.45}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
      ref={motion ? attachRef : ref}
      data-icon-motion={motion ? name : undefined}
      data-motion-active={motion && motionActive ? 'true' : undefined}
    >
      {motion && MOTION_NAMES.has(name) ? motionPaths(name) : PATHS[name]}
    </svg>
  );
}

export default Icon;
