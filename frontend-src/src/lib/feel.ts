/**
 * Feel — Perceptual Physics & Fluid Functionalism Engine for Option-Pro.
 *
 * Adapted from Feel (https://github.com/diip3sh/feel, https://diip3sh.github.io/feel/, MIT License).
 * Expresses motion in perceptual modal coordinates (mass m, natural frequency f in Hz,
 * damping ratio ζ) and compiles them to physical springs (stiffness k, damping c),
 * analytical step responses, CSS `linear()` curves, RK4 trajectories, rubber-band walls,
 * and momentum-projected drag release.
 */
import { useCallback, useLayoutEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react';

export interface ModalSpring {
  mass: number;
  freq: number;
  zeta: number;
}

export interface PhysicalSpring extends ModalSpring {
  stiffness: number;
  damping: number;
}

export type SpringInput =
  | string
  | Partial<ModalSpring & { stiffness: number; damping: number }>;

export interface MagnetWell {
  x: number;
  y?: number;
  strength?: number;
  radius?: number;
}

export interface SpringMetrics {
  overshootPct: number;
  settle: number;
  firstZero: number | null;
  oscillations: number;
  regime: 'underdamped' | 'critical' | 'overdamped';
}

const DT = 1 / 240;
const MAX_STEP = 1 / 20;
const VEL_EPS = 1e-3;
const POS_EPS = 1e-4;

export function prefersReducedMotionNow(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/**
 * Convert modal coordinates { mass, freq (Hz), zeta } to physical { mass, stiffness, damping }.
 *   ω₀ = 2πf,  k = m·ω₀²,  c = 2·ζ·√(k·m)
 */
export function fromModal({
  mass = 1,
  freq = 3.5,
  zeta = 0.72,
}: Partial<ModalSpring> = {}): PhysicalSpring {
  const m = Math.max(0.05, mass);
  const f = Math.max(0.2, freq);
  const z = Math.max(0.05, zeta);
  const w0 = 2 * Math.PI * f;
  const stiffness = m * w0 * w0;
  const damping = 2 * z * Math.sqrt(stiffness * m);
  return { mass: m, stiffness, damping, freq: f, zeta: z };
}

/**
 * Convert physical { mass, stiffness, damping } back to modal { mass, freq, zeta }.
 */
export function toModal({
  mass = 1,
  stiffness = 200,
  damping = 20,
}: {
  mass?: number;
  stiffness?: number;
  damping?: number;
} = {}): ModalSpring {
  const m = Math.max(0.05, mass);
  const k = Math.max(1, stiffness);
  const c = Math.max(0, damping);
  const w0 = Math.sqrt(k / m);
  const freq = w0 / (2 * Math.PI);
  const zeta = c / (2 * Math.sqrt(k * m));
  return { mass: m, freq, zeta };
}

type WordModifier = {
  df?: number;
  dz?: number;
  dm?: number;
  freq?: number;
  zeta?: number;
  mass?: number;
};

export const WORDS: Record<string, WordModifier> = {
  // Perceptual speed (natural frequency f)
  snappy: { df: +1.8, dz: -0.05 },
  quick: { df: +1.2 },
  crisp: { df: +1.5, dz: +0.08 },
  tight: { df: +2.0, dz: +0.12 },
  fast: { df: +1.4 },
  slow: { df: -1.4 },
  lazy: { df: -1.8, dz: +0.1 },
  gentle: { df: -1.0, dz: +0.12 },
  calm: { df: -1.2, dz: +0.18 },

  // Damping & character (zeta)
  bouncy: { dz: -0.32 },
  playful: { dz: -0.25, df: +0.4 },
  elastic: { dz: -0.38, df: +0.3 },
  springy: { dz: -0.22 },
  wobbly: { dz: -0.45 },
  settled: { dz: +0.22 },
  dead: { zeta: 1.05 },
  'critically-damped': { zeta: 1.0 },
  'no-overshoot': { zeta: 1.0 },
  smooth: { dz: +0.15, df: -0.4 },
  soft: { dz: +0.08, df: -0.8 },

  // Perceived weight (mass m)
  heavy: { dm: +1.2, df: -0.9, dz: +0.05 },
  weighted: { dm: +0.7, df: -0.5 },
  solid: { dm: +0.4, dz: +0.1 },
  light: { dm: -0.4, df: +0.6 },
  feathered: { dm: -0.55, df: +0.9, dz: +0.1 },
  airy: { dm: -0.5, df: -0.3, dz: -0.1 },

  // Ambient / spatial
  floating: { freq: 1.4, zeta: 0.55, mass: 1.3 },
  floaty: { freq: 1.6, zeta: 0.5, mass: 1.2 },
  drifting: { freq: 0.9, zeta: 0.7, mass: 1.6 },

  // Intent nouns
  dismiss: { freq: 4.6, zeta: 0.92, mass: 0.8 },
  snap: { freq: 5.2, zeta: 0.78, mass: 0.7 },
  flick: { freq: 4.8, zeta: 0.65, mass: 0.7 },
  hover: { freq: 4.2, zeta: 0.88, mass: 0.6 },
  press: { freq: 5.5, zeta: 0.85, mass: 0.6 },
  expand: { freq: 3.1, zeta: 0.76, mass: 1.1 },
  collapse: { freq: 3.8, zeta: 0.88, mass: 0.9 },
  enter: { freq: 3.2, zeta: 0.74, mass: 1.0 },
  exit: { freq: 4.4, zeta: 0.95, mass: 0.75 },
  modal: { freq: 3.3, zeta: 0.78, mass: 1.15 },
  sheet: { freq: 3.0, zeta: 0.84, mass: 1.3 },
  drawer: { freq: 3.2, zeta: 0.82, mass: 1.2 },
  tooltip: { freq: 5.0, zeta: 0.86, mass: 0.5 },
  popover: { freq: 4.4, zeta: 0.78, mass: 0.75 },
  pill: { freq: 3.4, zeta: 0.78, mass: 1.0 },
  toggle: { freq: 4.2, zeta: 0.68, mass: 0.85 },
  thumb: { freq: 4.4, zeta: 0.7, mass: 0.8 },
};

/**
 * Compile a whitespace/comma-separated perceptual phrase (e.g. "crisp toggle")
 * into physical spring parameters.
 */
export function fromWords(
  words: string,
  base: ModalSpring = { mass: 1, freq: 3.5, zeta: 0.72 },
): PhysicalSpring {
  const tokens = String(words)
    .toLowerCase()
    .trim()
    .split(/[\s,]+/)
    .filter(Boolean);
  let { mass, freq, zeta } = base;
  for (const tok of tokens) {
    const w = WORDS[tok];
    if (!w) continue;
    if (w.freq !== undefined) freq = w.freq;
    if (w.zeta !== undefined) zeta = w.zeta;
    if (w.mass !== undefined) mass = w.mass;
    if (w.df) freq += w.df;
    if (w.dz) zeta += w.dz;
    if (w.dm) mass += w.dm;
  }
  mass = Math.max(0.2, Math.min(4.0, mass));
  freq = Math.max(0.5, Math.min(9.0, freq));
  zeta = Math.max(0.18, Math.min(1.6, zeta));
  return fromModal({ mass, freq, zeta });
}

export function resolveSpring(input?: SpringInput): PhysicalSpring {
  if (!input) return fromModal();
  if (typeof input === 'string') return fromWords(input);
  if (typeof input.freq === 'number' || typeof input.zeta === 'number') {
    return fromModal({
      mass: input.mass ?? 1,
      freq: input.freq ?? 3.5,
      zeta: input.zeta ?? 0.72,
    });
  }
  const m = input.mass ?? 1;
  const k = input.stiffness ?? 200;
  const c = input.damping ?? 20;
  const modal = toModal({ mass: m, stiffness: k, damping: c });
  return { mass: m, stiffness: k, damping: c, freq: modal.freq, zeta: modal.zeta };
}

/**
 * Exact closed-form analytical solution for a 1D damped harmonic oscillator
 * with initial displacement `u0` (default -1 for unit step to 0) and velocity `v0`.
 */
export function response(input?: SpringInput, u0 = -1, v0 = 0) {
  const { mass: m, stiffness: k, damping: c } = resolveSpring(input);
  const w0 = Math.sqrt(k / m);
  const zeta = c / (2 * Math.sqrt(k * m));

  if (zeta < 1 - 1e-6) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    const A = u0;
    const B = (v0 + zeta * w0 * u0) / wd;
    return {
      zeta,
      w0,
      pos: (t: number) =>
        Math.exp(-zeta * w0 * t) * (A * Math.cos(wd * t) + B * Math.sin(wd * t)),
      vel: (t: number) => {
        const e = Math.exp(-zeta * w0 * t);
        const cos = Math.cos(wd * t);
        const sin = Math.sin(wd * t);
        return (
          e *
          ((B * wd - zeta * w0 * A) * cos - (A * wd + zeta * w0 * B) * sin)
        );
      },
    };
  }

  if (Math.abs(zeta - 1) <= 1e-6) {
    const A = u0;
    const B = v0 + w0 * u0;
    return {
      zeta: 1,
      w0,
      pos: (t: number) => Math.exp(-w0 * t) * (A + B * t),
      vel: (t: number) => Math.exp(-w0 * t) * (B - w0 * (A + B * t)),
    };
  }

  const s = Math.sqrt(zeta * zeta - 1);
  const r1 = -w0 * (zeta - s);
  const r2 = -w0 * (zeta + s);
  const A = (v0 - r2 * u0) / (r1 - r2);
  const B = u0 - A;
  return {
    zeta,
    w0,
    pos: (t: number) => A * Math.exp(r1 * t) + B * Math.exp(r2 * t),
    vel: (t: number) => A * r1 * Math.exp(r1 * t) + B * r2 * Math.exp(r2 * t),
  };
}

/**
 * Derive perceptual metrics (overshoot %, 2% envelope settle time, first zero crossing)
 * from any spring specification.
 */
export function metrics(input?: SpringInput): SpringMetrics {
  const { mass: m, stiffness: k, damping: c } = resolveSpring(input);
  const w0 = Math.sqrt(k / m);
  const zeta = c / (2 * Math.sqrt(k * m));
  const overshootPct =
    zeta < 1
      ? Math.exp((-zeta * Math.PI) / Math.sqrt(1 - zeta * zeta)) * 100
      : 0;
  const settle =
    zeta < 1 ? 4 / (zeta * w0) : (4 / w0) * (1 + 0.6 * (zeta - 1));
  const firstZero =
    zeta < 1
      ? (Math.PI - Math.acos(zeta)) / (w0 * Math.sqrt(1 - zeta * zeta))
      : null;
  const oscillations =
    zeta < 1
      ? Math.max(0, Math.floor((settle * w0 * Math.sqrt(1 - zeta * zeta)) / Math.PI))
      : 0;
  return {
    overshootPct,
    settle,
    firstZero,
    oscillations,
    regime: zeta < 0.99 ? 'underdamped' : zeta <= 1.01 ? 'critical' : 'overdamped',
  };
}

/**
 * Sample the exact analytical unit step response into a CSS `linear(...)` timing function.
 */
export function linearEasing(
  input?: SpringInput,
  samples = 36,
): {
  easing: string;
  durationMs: number;
  settleMs: number;
  overshootPct: number;
} {
  const p = resolveSpring(input);
  const m = metrics(p);
  const sol = response(p, -1, 0);
  const totalSec = Math.min(1.4, Math.max(0.16, m.settle * 1.12));
  const count = Math.max(8, samples);
  const stops: string[] = [];
  for (let i = 0; i <= count; i++) {
    const t = (i / count) * totalSec;
    const y = i === count ? 1 : 1 + sol.pos(t);
    const rounded = Number(y.toFixed(4));
    stops.push(String(rounded));
  }
  return {
    easing: `linear(${stops.join(', ')})`,
    durationMs: Math.round(totalSec * 1000),
    settleMs: Math.round(m.settle * 1000),
    overshootPct: Number(m.overshootPct.toFixed(2)),
  };
}

/**
 * Hyperbolic rubber-band constraint beyond [min, max].
 * Inside bounds, returns x untouched (1:1). Beyond bounds, asymptotes smoothly.
 */
export function wall(
  x: number,
  min = -Infinity,
  max = Infinity,
  resistance = 0.18,
): number {
  if (x < min) {
    const over = x - min;
    return min + (over * resistance) / (1 + Math.abs(over) / (120 * resistance));
  }
  if (x > max) {
    const over = x - max;
    return max + (over * resistance) / (1 + Math.abs(over) / (120 * resistance));
  }
  return x;
}

/**
 * Project a released body's coasting rest position from instantaneous velocity and mass:
 *   x_proj = x + v · (m / dragCoeff)
 */
export function projectCoast(
  pos: number,
  vel: number,
  mass = 1,
  dragCoeff = 4.5,
): number {
  return pos + (vel * Math.max(0.1, mass)) / Math.max(0.5, dragCoeff);
}

/**
 * 1D RK4 Spring-Damper-Magnet Body.
 */
export class Body {
  x: number;
  v: number;
  target: number;
  mass: number;
  stiffness: number;
  damping: number;
  magnets: MagnetWell[];
  asleep: boolean;

  constructor(
    initial = 0,
    opts?: SpringInput & { magnets?: MagnetWell[] },
  ) {
    const p = resolveSpring(opts);
    this.x = initial;
    this.v = 0;
    this.target = initial;
    this.mass = p.mass;
    this.stiffness = p.stiffness;
    this.damping = p.damping;
    this.magnets = opts && typeof opts === 'object' && 'magnets' in opts && Array.isArray(opts.magnets) ? opts.magnets : [];
    this.asleep = true;
  }

  setParams(opts: SpringInput): this {
    const p = resolveSpring(opts);
    this.mass = p.mass;
    this.stiffness = p.stiffness;
    this.damping = p.damping;
    return this;
  }

  to(target: number): this {
    if (prefersReducedMotionNow()) {
      this.x = target;
      this.target = target;
      this.v = 0;
      this.asleep = true;
      return this;
    }
    this.target = target;
    this.asleep = false;
    return this;
  }

  set(x: number, v = 0): this {
    this.x = x;
    this.v = v;
    this.asleep = false;
    return this;
  }

  impulse(dv: number): this {
    if (prefersReducedMotionNow()) return this;
    this.v += dv;
    this.asleep = false;
    return this;
  }

  force(x: number, v: number): number {
    let f = -this.stiffness * (x - this.target) - this.damping * v;
    for (let i = 0; i < this.magnets.length; i++) {
      const m = this.magnets[i];
      const d = x - m.x;
      const r = m.radius ?? 80;
      const s = m.strength ?? 400;
      const g = Math.exp(-(d * d) / (r * r));
      f += -s * d * g;
    }
    return f;
  }

  step(dt: number): number {
    if (this.asleep) return this.x;
    const clamped = Math.min(dt, MAX_STEP);
    let rem = clamped;
    const invM = 1 / this.mass;
    while (rem > 1e-6) {
      const h = rem > DT ? DT : rem;
      const x0 = this.x;
      const v0 = this.v;

      const a1 = this.force(x0, v0) * invM;
      const x2 = x0 + 0.5 * h * v0;
      const v2 = v0 + 0.5 * h * a1;
      const a2 = this.force(x2, v2) * invM;

      const x3 = x0 + 0.5 * h * v2;
      const v3 = v0 + 0.5 * h * a2;
      const a3 = this.force(x3, v3) * invM;

      const x4 = x0 + h * v3;
      const v4 = v0 + h * a3;
      const a4 = this.force(x4, v4) * invM;

      this.x = x0 + (h / 6) * (v0 + 2 * v2 + 2 * v3 + v4);
      this.v = v0 + (h / 6) * (a1 + 2 * a2 + 2 * a3 + a4);
      rem -= h;
    }

    if (
      Math.abs(this.v) < VEL_EPS &&
      Math.abs(this.x - this.target) < POS_EPS &&
      Math.abs(this.force(this.x, this.v)) < 1e-2
    ) {
      this.x = this.target;
      this.v = 0;
      this.asleep = true;
    }
    return this.x;
  }
}

/**
 * Simulate a physical spring release trajectory and hand it off to the browser's
 * compositor via Web Animations API (or snap cleanly when reduced motion is active).
 */
export function handoff(
  el: HTMLElement | null,
  opts: {
    fromX?: number;
    fromY?: number;
    toX?: number;
    toY?: number;
    vx?: number;
    vy?: number;
    spring?: SpringInput;
    maxDurationMs?: number;
    onFinish?: () => void;
  } = {},
) {
  const {
    fromX = 0,
    fromY = 0,
    toX = 0,
    toY = 0,
    vx = 0,
    vy = 0,
    spring = 'sheet',
    maxDurationMs = 520,
    onFinish,
  } = opts;

  if (!el || prefersReducedMotionNow()) {
    if (el) {
      el.style.transform =
        toX === 0 && toY === 0 ? '' : `translate3d(${toX}px, ${toY}px, 0)`;
    }
    onFinish?.();
    return {
      cancel: () => {},
      sample: () => ({ x: toX, y: toY, vx: 0, vy: 0, t: 1 }),
    };
  }

  const bx = new Body(fromX, spring);
  const by = new Body(fromY, spring);
  bx.v = vx;
  by.v = vy;
  bx.to(toX);
  by.to(toY);

  const sampleDt = 1 / 60;
  const maxFrames = Math.ceil((maxDurationMs / 1000) / sampleDt);
  const samples: { x: number; y: number; vx: number; vy: number }[] = [
    { x: fromX, y: fromY, vx, vy },
  ];

  for (let i = 0; i < maxFrames && (!bx.asleep || !by.asleep); i++) {
    bx.step(sampleDt);
    by.step(sampleDt);
    samples.push({ x: bx.x, y: by.x, vx: bx.v, vy: by.v });
  }
  samples.push({ x: toX, y: toY, vx: 0, vy: 0 });

  const duration = Math.max(80, Math.min(maxDurationMs, (samples.length - 1) * sampleDt * 1000));
  const keyframes = samples.map((s) => ({
    transform: `translate3d(${s.x.toFixed(2)}px, ${s.y.toFixed(2)}px, 0)`,
  }));

  const anim = el.animate(keyframes, {
    duration,
    easing: 'linear',
    fill: 'none',
  });

  anim.onfinish = () => {
    el.style.transform =
      toX === 0 && toY === 0 ? '' : `translate3d(${toX}px, ${toY}px, 0)`;
    onFinish?.();
  };

  return {
    cancel: () => { anim.onfinish = null; anim.cancel(); },
    sample: () => {
      // Use the compositor clock, including paused/pending animations, and the
      // same linear interpolation as the keyframes painted by the browser.
      const time = typeof anim.currentTime === 'number' ? anim.currentTime : 0;
      const u = Math.max(0, Math.min(1, time / duration));
      const frame = u * (samples.length - 1);
      const index = Math.floor(frame);
      const a = samples[index];
      const b = samples[Math.min(index + 1, samples.length - 1)];
      const mix = (start: number, end: number) => start + (end - start) * (frame - index);
      return { x: mix(a.x, b.x), y: mix(a.y, b.y), vx: mix(a.vx, b.vx), vy: mix(a.vy, b.vy), t: u };
    },
  };
}

/**
 * Pre-computed Feel spring presets for Option-Pro UI primitives.
 */
export const FEEL_PRESETS = {
  pill: fromWords('crisp pill'),
  toggle: fromWords('crisp toggle'),
  sheet: fromWords('sheet'),
  press: fromWords('press'),
  icon: fromModal({ mass: 0.75, freq: 3.8, zeta: 0.66 }),
} as const;

/**
 * Tactile thumb drag & press physics hook for `<Switch>` (Fluid Functionalism toggle).
 * Supports both normal clicks/keyboard AND pointer thumb dragging with rubber-band walls
 * and velocity-projected release (`projectCoast`).
 */
/** The same body follows the hand and continues through release. */
export class HeavyToggleMotion {
  readonly spring = fromModal({ mass: 2.2, freq: 3.3, zeta: 0.78 });
  // The hand stiffness is tuned for a unit mass, independent of the thumb's mass.
  // Add the hand damper to the body's drag, as in Feel's force model.
  readonly hand = resolveSpring({
    mass: this.spring.mass,
    stiffness: (2 * Math.PI * 6) ** 2,
    damping: this.spring.damping + 2 * Math.sqrt((2 * Math.PI * 6) ** 2 * this.spring.mass),
  });
  readonly body: Body;
  readonly travel: number;
  constructor(travel: number, checked: boolean) { this.travel = travel; this.body = new Body(checked ? travel : 0, this.spring); }
  pull(position: number) { this.body.setParams(this.hand).to(wall(position, 0, this.travel, 0.16)); }
  release() {
    const checked = projectCoast(this.body.x, this.body.v, this.spring.mass, this.spring.damping) > this.travel / 2;
    this.to(checked); return checked;
  }
  to(checked: boolean) { this.body.setParams(this.spring).to(checked ? this.travel : 0); }
  snap(checked: boolean) { this.body.set(checked ? this.travel : 0, 0); this.body.target = this.body.x; this.body.asleep = true; }
}

export function useFeelToggleDrag({ checked, disabled = false, travelPx = 14, onToggle }: {
  checked: boolean; disabled?: boolean; travelPx?: number; onToggle: () => void;
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const latest = useRef({ checked, disabled, onToggle });
  useLayoutEffect(() => { latest.current = { checked, disabled, onToggle }; }, [checked, disabled, onToggle]);
  const motionRef = useRef(new HeavyToggleMotion(travelPx, checked));
  const frameRef = useRef(0);
  const clockRef = useRef<number | null>(null);
  const dragRef = useRef<{ pointerId: number; target: HTMLButtonElement; startX: number; origin: number; lastX: number; lastAt: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const paint = useCallback(() => {
    const el = buttonRef.current, motion = motionRef.current!;
    if (!el) return;
    const x = wall(motion.body.x, 0, motion.travel, 0.16);
    const stretch = prefersReducedMotionNow() ? 1 : 1 + Math.min(0.1, Math.abs(motion.body.v) / (2600 * Math.sqrt(motion.body.mass)));
    el.style.setProperty('--thumb-physical-x', `${x}px`);
    el.style.setProperty('--thumb-scale-x', String(stretch));
    el.style.setProperty('--thumb-scale-y', String(1 / Math.sqrt(stretch)));
    el.style.setProperty('--toggle-fill', String(Math.max(0, Math.min(1, x / motion.travel))));
  }, []);
  const stop = useCallback(() => { cancelAnimationFrame(frameRef.current); frameRef.current = 0; clockRef.current = null; }, []);
  const advance = useCallback((now: number) => {
    const previous = clockRef.current; clockRef.current = now;
    if (previous !== null) motionRef.current!.body.step(Math.max(0, (now - previous) / 1000));
    paint();
  }, [paint]);
  const run = useCallback(() => {
    if (frameRef.current) return;
    clockRef.current ??= performance.now();
    const tick = (now: number) => {
      frameRef.current = 0; advance(now);
      if (!motionRef.current!.body.asleep || dragRef.current) frameRef.current = requestAnimationFrame(tick);
      else clockRef.current = null;
    };
    frameRef.current = requestAnimationFrame(tick);
  }, [advance]);
  const releaseCapture = useCallback(() => {
    const st = dragRef.current; dragRef.current = null;
    if (st) {
      if (st.moved) suppressClick.current = true;
      delete st.target.dataset.feelDrag;
      if (st.target.hasPointerCapture?.(st.pointerId)) st.target.releasePointerCapture(st.pointerId);
    }
    return st;
  }, []);
  const reset = useCallback(() => {
    if (dragRef.current) suppressClick.current = true;
    releaseCapture(); stop(); motionRef.current!.snap(latest.current.checked); paint();
  }, [releaseCapture, stop, paint]);
  const choose = (next: boolean) => {
    if (latest.current.disabled) return;
    motionRef.current!.to(next);
    if (prefersReducedMotionNow()) { motionRef.current!.snap(next); stop(); paint(); } else run();
    if (next !== latest.current.checked) latest.current.onToggle();
  };
  useLayoutEffect(() => {
    if (motionRef.current.travel !== travelPx) {
      reset();
      motionRef.current = new HeavyToggleMotion(travelPx, checked);
    }
    if (disabled || dragRef.current) reset();
    else {
      motionRef.current!.to(checked);
      if (prefersReducedMotionNow()) { motionRef.current!.snap(checked); stop(); }
      else if (!motionRef.current!.body.asleep) run();
      paint();
    }
  }, [checked, disabled, travelPx, reset, run, paint, stop]);
  useLayoutEffect(() => {
    paint();
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onPreference = () => { if (media.matches) reset(); };
    media.addEventListener('change', onPreference); window.addEventListener('blur', reset);
    return () => {
      media.removeEventListener('change', onPreference); window.removeEventListener('blur', reset);
      releaseCapture(); stop(); suppressClick.current = false;
    };
  }, [paint, reset, releaseCapture, stop]);
  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (latest.current.disabled || e.button !== 0 || e.isPrimary === false || dragRef.current) return;
    suppressClick.current = false; advance(performance.now());
    dragRef.current = { pointerId: e.pointerId, target: e.currentTarget, startX: e.clientX, origin: motionRef.current!.body.x,
      lastX: e.clientX, lastAt: performance.now(), moved: false };
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* Pointer may have ended. */ }
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const st = dragRef.current;
    if (!st || st.pointerId !== e.pointerId || latest.current.disabled) return;
    advance(performance.now());
    const dx = e.clientX - st.startX; st.moved ||= Math.abs(dx) > 3;
    if (st.moved) {
      st.target.dataset.feelDrag = 'true';
      if (prefersReducedMotionNow()) { motionRef.current!.body.set(wall(st.origin + dx, 0, travelPx, 0.16)); paint(); }
      else { motionRef.current!.pull(st.origin + dx); run(); }
    }
    st.lastX = e.clientX;
    st.lastAt = performance.now();
  };
  const finish = (e: ReactPointerEvent<HTMLButtonElement>, cancelled: boolean) => {
    const st = dragRef.current;
    if (!st || st.pointerId !== e.pointerId) return;
    if (cancelled) { reset(); return; }
    const finalDelta = e.clientX - st.lastX;
    let unsampledSeconds = Math.min(0.25, Math.max(1 / 240, (performance.now() - st.lastAt) / 1000));
    onPointerMove(e);
    // Browsers may coalesce the last move into pointerup. Integrate that final
    // hand displacement before choosing a stop instead of discarding it when
    // release() replaces the hand target. Ordinary releases keep their state.
    if (finalDelta !== 0 && st.moved && !prefersReducedMotionNow()) {
      // Body.step caps a single frame at 50ms. Subdivide a coalesced interval
      // rather than dropping the rest; cap background-tab gaps at 250ms.
      while (unsampledSeconds > 0) {
        const step = Math.min(unsampledSeconds, 0.05);
        motionRef.current!.body.step(step);
        unsampledSeconds -= step;
      }
      paint();
    }
    releaseCapture();
    if (st.moved && !latest.current.disabled) choose(motionRef.current!.release());
  };
  return { attach: (el: HTMLButtonElement | null) => { buttonRef.current = el; }, onPointerDown, onPointerMove,
    onPointerUp: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, false),
    onPointerCancel: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, true),
    onLostPointerCapture: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, true),
    onKeyDown: (e: import('react').KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); reset(); choose(e.key === 'ArrowRight'); }
    },
    activate: () => choose(!latest.current.checked),
    consumeSuppressedClick: (detail = 1) => {
      const suppressed = suppressClick.current && detail !== 0; suppressClick.current = false; return suppressed;
    },
  };
}
