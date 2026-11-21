/** Side-effect-free geometry in a generic 2-D plane; never touches the DOM or ECharts. */
import type { Point } from './types.ts';

export function normalizeRectangle(
  a: Point,
  b: Point,
): { x0: number; x1: number; y0: number; y1: number } {
  return {
    x0: Math.min(a.x, b.x),
    x1: Math.max(a.x, b.x),
    y0: Math.min(a.y, b.y),
    y1: Math.max(a.y, b.y),
  };
}
