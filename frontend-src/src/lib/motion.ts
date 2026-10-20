/** Shared durations and the non-overshooting selection indicator spring. */
import type { Transition } from 'framer-motion';

export const EASE_PAPER = [0.16, 1, 0.3, 1] as const;
export const DUR_FAST = 0.16;
export const DUR_UI = 0.24;
export const DUR_SECTION = 0.56;

// Avoid overshoot in horizontally scrollable tabs.
export const SPRING_INDICATOR: Transition = {
  type: 'spring',
  stiffness: 245,
  damping: 36,
  mass: 1.2,
};
