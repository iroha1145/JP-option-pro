/**
 * 动效契约（beUI Motion Guide + transitions.dev + 本站纸面终端）
 *
 * - 页级进场只动 transform，不动 opacity（冻结时内容仍可读）
 * - 弹出层可以淡入：短、可卸载
 * - 共享 layoutId 滑块：导航 / Dock / 分段
 * - 一律尊重 prefers-reduced-motion
 */
import type { Transition, Variants } from 'framer-motion';

export const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];
export const EASE_SNAP = [0.22, 1, 0.36, 1] as [number, number, number, number];

/** beUI / transitions.dev 共用的软弹簧：滑块、指示条 */
export const springSoft: Transition = {
  type: 'spring',
  stiffness: 440,
  damping: 34,
  mass: 0.78,
};

export const springSnappy: Transition = {
  type: 'spring',
  stiffness: 560,
  damping: 38,
  mass: 0.65,
};

export const tweenPaper: Transition = { duration: 0.24, ease: EASE_PAPER };
export const tweenFast: Transition = { duration: 0.16, ease: EASE_SNAP };

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** 列表子项上浮（无 opacity，避免白页） */
export const riseItem: Variants = {
  hidden: { y: 8 },
  show: { y: 0, transition: tweenPaper },
};

export const staggerFast: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04, delayChildren: 0.03 } },
};

export const popoverVariants: Variants = {
  hidden: { opacity: 0, y: -6, filter: 'blur(4px)' },
  show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: tweenFast },
  exit: { opacity: 0, y: -4, filter: 'blur(4px)', transition: { duration: 0.12, ease: EASE_SNAP } },
};

export const popoverReduced: Variants = {
  hidden: { y: -4 },
  show: { y: 0, transition: { duration: 0.12 } },
  exit: { y: -2, transition: { duration: 0.08 } },
};
