/**
 * Feel spring and drag gestures used by the Japanese toggle and more sheet.
 *
 * Adapted from Feel (https://github.com/diip3sh/feel, https://diip3sh.github.io/feel/, MIT License).
 * Uses fixed spring parameters, RK4 trajectories, rubber-band walls and
 * momentum-projected drag release. General spring editors and demos are omitted.
 */
import { useCallback, useLayoutEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react';

// Fixed parameters used by the Japanese toggle and more-sheet gestures.
const SHEET_MASS = 1.3;
const SHEET_FREQUENCY = 3;
const SHEET_DAMPING_RATIO = 0.84;
const SHEET_STIFFNESS = SHEET_MASS * (2 * Math.PI * SHEET_FREQUENCY) ** 2;
const SHEET_DAMPING = 2 * SHEET_DAMPING_RATIO * Math.sqrt(SHEET_STIFFNESS * SHEET_MASS);

interface SpringParameters { mass: number; stiffness: number; damping: number }
const SHEET_SPRING: SpringParameters = { mass: SHEET_MASS, stiffness: SHEET_STIFFNESS, damping: SHEET_DAMPING };
const TOGGLE_MASS = 2.2;
const TOGGLE_STIFFNESS = TOGGLE_MASS * (2 * Math.PI * 3.3) ** 2;
const TOGGLE_DAMPING = 2 * 0.78 * Math.sqrt(TOGGLE_STIFFNESS * TOGGLE_MASS);
const TOGGLE_SPRING: SpringParameters = { mass: TOGGLE_MASS, stiffness: TOGGLE_STIFFNESS, damping: TOGGLE_DAMPING };
const HAND_STIFFNESS = (2 * Math.PI * 6) ** 2;
const TOGGLE_HAND: SpringParameters = {
  mass: TOGGLE_MASS,
  stiffness: HAND_STIFFNESS,
  damping: TOGGLE_DAMPING + 2 * Math.sqrt(HAND_STIFFNESS * TOGGLE_MASS),
};

const DT = 1 / 240;
const MAX_STEP = 1 / 20;
const VEL_EPS = 1e-3;
const POS_EPS = 1e-4;

function prefersReducedMotionNow(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
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
 * Internal RK4 spring body used by the fixed toggle and sheet springs.
 */
class Body {
  x: number;
  v: number;
  target: number;
  mass: number;
  stiffness: number;
  damping: number;
  asleep: boolean;

  constructor(initial: number, params: SpringParameters = SHEET_SPRING) {
    this.x = initial;
    this.v = 0;
    this.target = initial;
    this.mass = params.mass;
    this.stiffness = params.stiffness;
    this.damping = params.damping;
    this.asleep = true;
  }

  setParams(params: SpringParameters): this {
    this.mass = params.mass;
    this.stiffness = params.stiffness;
    this.damping = params.damping;
    return this;
  }

  set(x: number, v = 0): this {
    this.x = x;
    this.v = v;
    this.asleep = false;
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

  force(x: number, v: number): number {
    return -this.stiffness * (x - this.target) - this.damping * v;
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
    maxDurationMs = 520,
    onFinish,
  } = opts;

  if (!el || prefersReducedMotionNow() || typeof el.animate !== 'function') {
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

  const bx = new Body(fromX);
  const by = new Body(fromY);
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

/** The same body follows the hand and continues through release. */
export class HeavyToggleMotion {
  readonly spring = TOGGLE_SPRING;
  // The hand spring adds its damper to the thumb's own drag.
  readonly hand = TOGGLE_HAND;
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
