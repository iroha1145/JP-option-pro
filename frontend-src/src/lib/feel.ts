/**
 * Feel spring and drag gestures used by the Japanese toggle and more sheet.
 *
 * Adapted from Feel (https://github.com/diip3sh/feel, https://diip3sh.github.io/feel/, MIT License).
 * Uses fixed spring parameters, RK4 trajectories, rubber-band walls and
 * momentum-projected drag release. General spring editors and demos are omitted.
 */
import { useLayoutEffect, useRef, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';

// Fixed parameters used by the Japanese toggle and more-sheet gestures.
const TOGGLE_MASS = 0.85;
const SHEET_MASS = 1.3;
const SHEET_FREQUENCY = 3;
const SHEET_DAMPING_RATIO = 0.84;
const SHEET_STIFFNESS = SHEET_MASS * (2 * Math.PI * SHEET_FREQUENCY) ** 2;
const SHEET_DAMPING = 2 * SHEET_DAMPING_RATIO * Math.sqrt(SHEET_STIFFNESS * SHEET_MASS);

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
 * Internal RK4 spring body used by the sheet animation handoff.
 */
class Body {
  x: number;
  v: number;
  target: number;
  mass: number;
  stiffness: number;
  damping: number;
  asleep: boolean;

  constructor(initial: number) {
    this.x = initial;
    this.v = 0;
    this.target = initial;
    this.mass = SHEET_MASS;
    this.stiffness = SHEET_STIFFNESS;
    this.damping = SHEET_DAMPING;
    this.asleep = true;
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

/**
 * Tactile thumb drag & press physics hook for `<Switch>` (Fluid Functionalism toggle).
 * Supports both normal clicks/keyboard AND pointer thumb dragging with rubber-band walls
 * and velocity-projected release (`projectCoast`).
 */
// Velocity expires when the pointer rests. Release coordinates are sampled too.
const VELOCITY_WINDOW_MS = 80;
function pointerVelocity(position: number, last: number, now: number, lastT: number, previous: number, released = false) {
  const elapsed = now - lastT;
  if (elapsed > VELOCITY_WINDOW_MS) return 0;
  if (released && position === last) return previous * Math.max(0, 1 - elapsed / VELOCITY_WINDOW_MS);
  return 0.55 * previous + 0.45 * (position - last) / Math.max(0.001, elapsed / 1000);
}

export function useFeelToggleDrag({ checked, disabled = false, travelPx = 14, onToggle }: {
  checked: boolean; disabled?: boolean; travelPx?: number; onToggle: () => void;
}) {
  const dragRef = useRef<{
    pointerId: number; target: HTMLButtonElement; startX: number; lastX: number;
    lastT: number; vx: number; moved: boolean; origin: number;
  } | null>(null);
  const suppressClick = useRef(false);
  const reset = () => {
    const st = dragRef.current;
    dragRef.current = null;
    if (!st) return;
    if (st.moved) suppressClick.current = true;
    delete st.target.dataset.feelPress;
    delete st.target.dataset.feelDrag;
    for (const name of ['--thumb-drag-x', '--thumb-scale-x', '--thumb-scale-y']) st.target.style.removeProperty(name);
    if (st.target.hasPointerCapture?.(st.pointerId)) st.target.releasePointerCapture(st.pointerId);
  };
  useLayoutEffect(() => {
    if (disabled) reset();
    window.addEventListener('blur', reset);
    return () => { window.removeEventListener('blur', reset); reset(); suppressClick.current = false; };
  }, [disabled]);
  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (disabled || e.button !== 0 || e.isPrimary === false || dragRef.current) return;
    suppressClick.current = false;
    dragRef.current = { pointerId: e.pointerId, target: e.currentTarget, startX: e.clientX,
      lastX: e.clientX, lastT: performance.now(), vx: 0, moved: false, origin: checked ? travelPx : 0 };
    if (!prefersReducedMotionNow()) {
      e.currentTarget.dataset.feelPress = 'true';
      e.currentTarget.style.setProperty('--thumb-scale-x', '1.1');
      e.currentTarget.style.setProperty('--thumb-scale-y', '0.94');
    }
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* Pointer may have already ended. */ }
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const st = dragRef.current;
    if (!st || st.pointerId !== e.pointerId || disabled) return;
    const now = performance.now();
    st.vx = pointerVelocity(e.clientX, st.lastX, now, st.lastT, st.vx);
    st.lastX = e.clientX; st.lastT = now;
    const dx = e.clientX - st.startX;
    st.moved ||= Math.abs(dx) > 3;
    if (st.moved) {
      st.target.dataset.feelDrag = 'true';
      st.target.style.setProperty('--thumb-drag-x', `${wall(st.origin + dx, 0, travelPx, 0.16)}px`);
      if (!prefersReducedMotionNow()) {
        const speed = Math.min(1, Math.abs(st.vx) / 700);
        st.target.style.setProperty('--thumb-scale-x', String(1.08 + speed * 0.1));
        st.target.style.setProperty('--thumb-scale-y', String(0.94 - speed * 0.04));
      }
    }
  };
  const finish = (e: ReactPointerEvent<HTMLButtonElement>, cancelled: boolean) => {
    const st = dragRef.current;
    if (!st || st.pointerId !== e.pointerId) return;
    const moved = st.moved || Math.abs(e.clientX - st.startX) > 3;
    const velocity = pointerVelocity(e.clientX, st.lastX, performance.now(), st.lastT, st.vx, true);
    reset();
    if (cancelled && moved) suppressClick.current = true;
    if (!cancelled && !disabled && moved) {
      suppressClick.current = true;
      const next = projectCoast(st.origin + e.clientX - st.startX, velocity, TOGGLE_MASS, 4.5) > travelPx / 2;
      if (next !== checked) onToggle();
    }
  };
  return { onPointerDown, onPointerMove,
    onPointerUp: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, false),
    onPointerCancel: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, true),
    onLostPointerCapture: (e: ReactPointerEvent<HTMLButtonElement>) => finish(e, true),
    consumeSuppressedClick: (detail = 1) => {
      const suppressed = suppressClick.current && detail !== 0;
      suppressClick.current = false;
      return suppressed;
    },
  };
}

export function useFeelSheetDrag({ panelRef, onClose, enabled = true }: {
  panelRef: RefObject<HTMLElement | null>; onClose: () => void; enabled?: boolean;
}) {
  const dragRef = useRef<{
    pointerId: number; handle: HTMLElement; panel: HTMLElement; startY: number;
    originY: number; lastY: number; lastT: number; vy: number; currentY: number;
  } | null>(null);
  const animationRef = useRef<ReturnType<typeof handoff> | null>(null);
  const animatedPanelRef = useRef<HTMLElement | null>(null);
  const cancelAnimation = () => {
    const sample = animationRef.current?.sample();
    animationRef.current?.cancel();
    animationRef.current = null;
    return sample;
  };
  const release = () => {
    const st = dragRef.current;
    dragRef.current = null;
    if (st) {
      st.panel.style.transition = '';
      if (st.handle.hasPointerCapture?.(st.pointerId)) st.handle.releasePointerCapture(st.pointerId);
    }
    return st;
  };
  useLayoutEffect(() => {
    const cleanup = () => {
      cancelAnimation();
      const st = release();
      const panel = st?.panel ?? animatedPanelRef.current;
      if (panel) panel.style.transform = '';
      animatedPanelRef.current = null;
    };
    window.addEventListener('blur', cleanup);
    return () => { window.removeEventListener('blur', cleanup); cleanup(); };
  }, [enabled]);
  const onPointerDown = (e: ReactPointerEvent<HTMLElement>) => {
    const panel = panelRef.current;
    if (!enabled || !panel || e.button !== 0 || e.isPrimary === false || dragRef.current) return;
    // Read before cancelling either a CSS entrance or the spring handoff.
    // A new grab starts exactly where the panel is currently painted.
    const transform = getComputedStyle(panel).transform;
    const originY = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
    cancelAnimation();
    dragRef.current = { pointerId: e.pointerId, handle: e.currentTarget, panel,
      startY: e.clientY, originY, lastY: e.clientY, lastT: performance.now(), vy: 0, currentY: originY };
    panel.style.transition = 'none';
    panel.style.transform = `translate3d(0, ${originY}px, 0)`;
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* Pointer may have already ended. */ }
  };
  const update = (e: ReactPointerEvent<HTMLElement>, released = false) => {
    const st = dragRef.current;
    if (!st || st.pointerId !== e.pointerId) return null;
    const now = performance.now();
    st.vy = pointerVelocity(e.clientY, st.lastY, now, st.lastT, st.vy, released);
    st.lastY = e.clientY; st.lastT = now;
    st.currentY = wall(st.originY + e.clientY - st.startY, 0, 800, 0.14);
    st.panel.style.transform = `translate3d(0, ${st.currentY}px, 0)`;
    return st;
  };
  const finish = (e: ReactPointerEvent<HTMLElement>, cancelled: boolean) => {
    if (dragRef.current?.pointerId !== e.pointerId) return;
    if (!cancelled) update(e, true);
    const st = release();
    if (!st) return;
    st.panel.style.transform = '';
    if (cancelled || !enabled) return;
    const threshold = Math.min(110, Math.max(56, st.panel.getBoundingClientRect().height * 0.26));
    if (projectCoast(st.currentY, st.vy, SHEET_MASS, 4.5) > threshold || (st.currentY > 24 && st.vy > 420)) {
      onClose();
    } else if (Math.abs(st.currentY) > 1) {
      animatedPanelRef.current = st.panel;
      animationRef.current = handoff(st.panel, { fromY: st.currentY, vy: st.vy });
    }
  };
  return { onPointerDown, onPointerMove: update,
    onPointerUp: (e: ReactPointerEvent<HTMLElement>) => finish(e, false),
    onPointerCancel: (e: ReactPointerEvent<HTMLElement>) => finish(e, true),
    onLostPointerCapture: (e: ReactPointerEvent<HTMLElement>) => finish(e, true),
  };
}
