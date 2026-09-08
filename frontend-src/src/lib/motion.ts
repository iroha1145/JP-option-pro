/**
 * framer-motion 时长/缓动档位：与 design.md §4.1 / tailwind transitionDuration 同一套。
 */
import type { Transition, Variants } from 'framer-motion';

export const EASE_PAPER = [0.16, 1, 0.3, 1] as const;
export const EASE_SNAP = [0.22, 1, 0.36, 1] as const;
export const DUR_FAST = 0.16;
export const DUR_UI = 0.24;
export const DUR_SECTION = 0.56;

export const SPRING_INDICATOR: Transition = {
  type: 'spring',
  stiffness: 170,
  damping: 24,
  mass: 1.2,
};

export const springSoft: Transition = {
  type: 'spring',
  stiffness: 440,
  damping: 34,
  mass: 0.78,
};

export const tweenPaper: Transition = { duration: 0.24, ease: EASE_PAPER };
export const tweenFast: Transition = { duration: 0.16, ease: EASE_SNAP };

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

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
