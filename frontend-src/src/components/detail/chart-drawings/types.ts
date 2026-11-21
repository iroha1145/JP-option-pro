/** Shared chart-overlay types. Coordinates are time + price, never screen pixels. */

/** Bar-key granularity shared with the backend analysis fingerprint. */
export type ChartRange = '5m' | '15m' | '1h' | '1d' | '1w';

export interface DrawingAnchor {
  time: string;
  barKey: string;
  price: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface Segment {
  a: Point;
  b: Point;
}
