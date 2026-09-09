/** Auto-pattern marks only. Hand-drawing projection stays in the US package. */
import { normalizeRectangle } from './geometry.ts';
import { barKeyOf, resolveAnchor } from './projection.ts';
import { renderPatternInk } from './linePresentation.ts';
import type { ChartRange, Point, Segment } from './types.ts';

export interface BarLike {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface RenderContext {
  bars: BarLike[];
  range: ChartRange;
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

export interface FillPolygon {
  vertices: Point[];
  color: string;
  opacity: number;
}

export interface DrawingMarks {
  lines: object[];
  areas: object[];
  points: object[];
  polygons: FillPolygon[];
  unresolvedIds: string[];
}

export interface AutoPatternLike {
  id: string;
  kind: string;
  subtype?: string;
  confidence: number;
  status: string;
  anchors: { time: string; barKey: string; price: number }[];
  hidden?: boolean;
  color?: string;
  label?: string;
}

export function autoPatternGeometry(
  pattern: AutoPatternLike,
  ctx: RenderContext,
): { segments: Segment[]; fill: Point[] | null } | null {
  const points: Point[] = [];
  for (const anchor of pattern.anchors) {
    const index = resolveAnchor(ctx.bars, { time: anchor.time, barKey: anchor.barKey, price: anchor.price }, ctx.range);
    if (index < 0) return null;
    points.push({ x: index, y: anchor.price });
  }
  if (points.length < 2) return null;
  if (pattern.kind === 'box') {
    const box = normalizeRectangle(
      { x: Math.min(...points.map((p) => p.x)), y: Math.min(...points.map((p) => p.y)) },
      { x: Math.max(...points.map((p) => p.x)), y: Math.max(...points.map((p) => p.y)) },
    );
    return {
      segments: [
        { a: { x: box.x0, y: box.y0 }, b: { x: box.x1, y: box.y0 } },
        { a: { x: box.x1, y: box.y0 }, b: { x: box.x1, y: box.y1 } },
        { a: { x: box.x1, y: box.y1 }, b: { x: box.x0, y: box.y1 } },
        { a: { x: box.x0, y: box.y1 }, b: { x: box.x0, y: box.y0 } },
      ],
      fill: [
        { x: box.x0, y: box.y0 },
        { x: box.x1, y: box.y0 },
        { x: box.x1, y: box.y1 },
        { x: box.x0, y: box.y1 },
      ],
    };
  }
  if (
    (pattern.kind === 'channel' || pattern.kind === 'triangle' || pattern.kind === 'wedge')
    && points.length >= 4
  ) {
    return {
      segments: [
        { a: points[0], b: points[1] },
        { a: points[2], b: points[3] },
      ],
      fill: [points[0], points[1], points[3], points[2]],
    };
  }
  return { segments: [{ a: points[0], b: points[1] }], fill: null };
}

export function autoPatternsToMarks(
  patterns: AutoPatternLike[],
  ctx: RenderContext,
  minConfidence = 70,
): DrawingMarks {
  const out: DrawingMarks = { lines: [], areas: [], points: [], polygons: [], unresolvedIds: [] };
  for (const pattern of patterns) {
    if (pattern.hidden || !Number.isFinite(pattern.confidence) || pattern.confidence < minConfidence) continue;
    const geom = autoPatternGeometry(pattern, ctx);
    if (!geom) continue;
    const ink = renderPatternInk(pattern, geom, ctx);
    out.lines.push(...ink.lines);
    out.points.push(...ink.points);
    out.areas.push(...ink.areas);
    out.polygons.push(...ink.polygons);
  }
  return out;
}

export function lastBarKey(bars: BarLike[], range: ChartRange): string | null {
  if (!bars.length) return null;
  return barKeyOf(bars[bars.length - 1], range);
}

export function deconflictEndLabels(lines: object[], _yMin: number, _yMax: number): object[] {
  return lines;
}
