import { useLayoutEffect, useRef, type KeyboardEvent, type MouseEvent, type PointerEvent, type RefObject } from 'react';
import { MagneticSheetBody, type SheetSample } from '@/lib/magneticSheet';

interface Drag {
  pointerId: number;
  handle: HTMLElement;
  panel: HTMLElement;
  body: MagneticSheetBody;
  startY: number;
  originY: number;
  lastY: number;
  lastAt: number;
  moved: boolean;
}

/** Open/closed magnetic stops preserve the existing full-height reading area. */
export function useFeelSheetDrag({ panelRef, backdropRef, onClose, enabled = true }: {
  panelRef: RefObject<HTMLElement | null>;
  backdropRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
  enabled?: boolean;
}) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const dragRef = useRef<Drag | null>(null);
  const frameRef = useRef(0);
  const clockRef = useRef(0);
  const suppressClick = useRef(false);
  const motionRef = useRef<{ panel: HTMLElement; animation: Animation; backdropAnimation?: Animation; sample: () => SheetSample } | null>(null);
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const opacityAt = (panel: HTMLElement, y: number) => 1 - Math.max(0, Math.min(1, y / Math.max(1, panel.offsetHeight)));
  const paintBackdrop = (panel: HTMLElement, y: number) => {
    const backdrop = backdropRef?.current;
    if (!backdrop) return;
    backdrop.style.transition = 'none';
    backdrop.style.opacity = String(opacityAt(panel, y));
  };
  const restoreBackdrop = () => {
    const backdrop = backdropRef?.current;
    if (!backdrop) return;
    backdrop.style.opacity = '';
    backdrop.style.transition = '';
  };
  const paint = (panel: HTMLElement, y: number) => {
    panel.style.transform = `translate3d(0, ${y}px, 0)`;
    paintBackdrop(panel, y);
  };
  const cancelMotion = () => {
    const motion = motionRef.current;
    if (!motion) return null;
    const sample = motion.sample();
    motion.animation.onfinish = null;
    motion.animation.cancel();
    motion.backdropAnimation?.cancel();
    motionRef.current = null;
    return sample;
  };
  const releaseCapture = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    if (drag?.handle.hasPointerCapture?.(drag.pointerId)) drag.handle.releasePointerCapture(drag.pointerId);
    return drag;
  };
  const settle = (panel: HTMLElement, rest: number) => {
    if (rest === 0) {
      restoreBackdrop();
      panel.style.transform = '';
      panel.style.transition = '';
    } else {
      // The physical exit has already completed. Keep it offscreen through the
      // parent's existing overlay cleanup instead of playing a second exit.
      panel.dataset.feelDismissed = 'true';
      paint(panel, rest);
      closeRef.current();
    }
  };
  const animate = (panel: HTMLElement, body: MagneticSheetBody) => {
    cancelMotion();
    panel.style.transition = 'none';
    if (reduced() || typeof panel.animate !== 'function') {
      settle(panel, body.rest(body.projected()));
      return;
    }
    const path = body.path();
    if (Math.abs(body.x - path.rest) < 0.25 && Math.abs(body.v) < 4) {
      settle(panel, path.rest);
      return;
    }
    const animation = panel.animate(
      path.samples.map(({ x }) => ({ transform: `translate3d(0, ${x}px, 0)` })),
      { duration: path.duration, easing: 'linear', fill: 'both' },
    );
    const backdrop = backdropRef?.current;
    if (backdrop) backdrop.style.transition = 'none';
    const backdropAnimation = backdrop?.animate(
      path.samples.map(({ x }) => ({ opacity: opacityAt(panel, x) })),
      { duration: path.duration, easing: 'linear', fill: 'both' },
    );
    // Both compositor effects share the exact timeline origin and sample times.
    const startTime = document.timeline.currentTime;
    if (startTime !== null) {
      animation.startTime = startTime;
      if (backdropAnimation) backdropAnimation.startTime = startTime;
    }
    const sample = () => {
      const time = typeof animation.currentTime === 'number' ? animation.currentTime : 0;
      const frame = Math.max(0, Math.min(path.samples.length - 1, time / path.duration * (path.samples.length - 1)));
      const index = Math.floor(frame);
      const a = path.samples[index], b = path.samples[Math.min(index + 1, path.samples.length - 1)];
      return { x: a.x + (b.x - a.x) * (frame - index), v: a.v + (b.v - a.v) * (frame - index) };
    };
    motionRef.current = { panel, animation, backdropAnimation, sample };
    animation.onfinish = () => {
      if (motionRef.current?.animation !== animation) return;
      motionRef.current = null;
      animation.onfinish = null;
      animation.cancel();
      backdropAnimation?.cancel();
      settle(panel, path.rest);
    };
  };
  const reset = () => {
    const animatedPanel = motionRef.current?.panel;
    cancelMotion();
    const drag = releaseCapture();
    if (drag) suppressClick.current = true;
    const panel = drag?.panel ?? animatedPanel ?? panelRef.current;
    if (panel && panel.dataset.feelDismissed !== 'true') {
      restoreBackdrop();
      panel.style.transform = '';
      panel.style.transition = '';
    }
  };
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (enabled && panel) {
      delete panel.dataset.feelDismissed;
      restoreBackdrop();
      panel.style.transform = '';
      panel.style.transition = '';
    }
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onReducedChange = () => {
      if (!media.matches) return;
      const motion = motionRef.current;
      if (motion) {
        const state = cancelMotion()!;
        const body = new MagneticSheetBody(motion.panel.offsetHeight, state.x, state.v);
        settle(motion.panel, body.rest(body.projected()));
      }
      const drag = dragRef.current;
      if (drag?.body.hand) {
        drag.body.x = Math.max(0, Math.min(drag.body.height, drag.body.hand.x));
        drag.body.v = 0;
        paint(drag.panel, drag.body.x);
      }
    };
    window.addEventListener('blur', reset);
    window.addEventListener('resize', reset);
    window.visualViewport?.addEventListener('resize', reset);
    media.addEventListener('change', onReducedChange);
    return () => {
      window.removeEventListener('blur', reset);
      window.removeEventListener('resize', reset);
      window.visualViewport?.removeEventListener('resize', reset);
      media.removeEventListener('change', onReducedChange);
      reset();
    };
    // DOM listeners own a single enabled lifetime; current callback is in a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  const tick = (now: number) => {
    const drag = dragRef.current;
    if (!drag) { frameRef.current = 0; return; }
    if (drag.body.hand && now - drag.lastAt > 60) drag.body.hand.v = 0;
    if (reduced()) {
      drag.body.x = Math.max(0, Math.min(drag.body.height, drag.body.hand?.x ?? drag.body.x));
      drag.body.v = 0;
    } else {
      drag.body.step((now - clockRef.current) / 1000);
    }
    clockRef.current = now;
    paint(drag.panel, drag.body.x);
    frameRef.current = requestAnimationFrame(tick);
  };
  const update = (event: PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const now = performance.now(), elapsed = now - drag.lastAt;
    const delta = event.clientY - drag.lastY;
    const velocity = elapsed > 80 ? 0 : delta / Math.max(0.001, elapsed / 1000);
    drag.body.hand = {
      x: drag.originY + event.clientY - drag.startY,
      v: delta === 0 ? (elapsed > 60 ? 0 : drag.body.hand?.v ?? 0) : Math.max(-4000, Math.min(4000, velocity)),
    };
    drag.moved ||= Math.abs(event.clientY - drag.startY) > 3;
    drag.lastY = event.clientY;
    if (delta !== 0) drag.lastAt = now;
    if (drag.moved && !frameRef.current) {
      clockRef.current = now;
      frameRef.current = requestAnimationFrame(tick);
    }
  };
  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    const panel = panelRef.current;
    if (!enabled || !panel || event.button !== 0 || event.isPrimary === false || dragRef.current) return;
    const transform = getComputedStyle(panel).transform;
    const originY = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
    const state = cancelMotion();
    suppressClick.current = false;
    delete panel.dataset.feelDismissed;
    panel.style.transition = 'none';
    paint(panel, originY);
    dragRef.current = {
      pointerId: event.pointerId, handle: event.currentTarget, panel,
      body: new MagneticSheetBody(panel.offsetHeight, originY, state?.v ?? 0),
      startY: event.clientY, originY, lastY: event.clientY, lastAt: performance.now(), moved: false,
    };
    dragRef.current.body.hand = { x: originY, v: 0 };
    clockRef.current = performance.now();
    frameRef.current = requestAnimationFrame(tick);
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* Pointer has already ended. */ }
  };
  const finish = (event: PointerEvent<HTMLElement>, cancelled: boolean) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const finalDelta = event.clientY - drag.lastY;
    if (!cancelled) update(event);
    releaseCapture();
    if (drag.moved) suppressClick.current = true;
    if (cancelled || !enabled) {
      // A regrab can be cancelled before any new movement. Its subsequent
      // native click must not turn that cancellation into a close command.
      suppressClick.current = true;
      restoreBackdrop();
      drag.panel.style.transform = '';
      drag.panel.style.transition = '';
      return;
    }
    if (!drag.moved) return;
    // A final pointerup position is not guaranteed to have a pointermove. Give
    // that last displacement a physical step before dropping the hand spring.
    if (finalDelta !== 0 && drag.body.hand) drag.body.step(1 / 60);
    if (reduced()) {
      drag.body.x = Math.max(0, Math.min(drag.body.height, drag.body.hand?.x ?? drag.body.x));
      drag.body.v = 0;
    }
    drag.body.hand = null;
    animate(drag.panel, drag.body);
  };
  const go = (closed: boolean) => {
    const panel = panelRef.current;
    if (!enabled || !panel) return;
    const transform = getComputedStyle(panel).transform;
    const x = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
    const sample = cancelMotion();
    releaseCapture();
    const body = new MagneticSheetBody(panel.offsetHeight, x, sample?.v ?? 0);
    if (reduced()) {
      settle(panel, closed ? body.height : 0);
      return;
    }
    body.kickTo(closed ? body.height : 0);
    animate(panel, body);
  };
  return {
    onPointerDown,
    onPointerMove: update,
    onPointerUp: (event: PointerEvent<HTMLElement>) => finish(event, false),
    onPointerCancel: (event: PointerEvent<HTMLElement>) => finish(event, true),
    onLostPointerCapture: (event: PointerEvent<HTMLElement>) => finish(event, true),
    onClick: (event: MouseEvent<HTMLElement>) => {
      if (event.detail !== 0 && suppressClick.current) { suppressClick.current = false; return; }
      suppressClick.current = false;
      go(true);
    },
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      if (['ArrowUp', 'Home', 'ArrowDown', 'End'].includes(event.key)) {
        event.preventDefault();
        go(event.key === 'ArrowDown' || event.key === 'End');
      }
    },
  };
}
