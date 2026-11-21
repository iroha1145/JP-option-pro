import { useSyncExternalStore } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';
const listeners = new Set<() => void>();
let media: MediaQueryList;

function query(): MediaQueryList {
  return media ??= window.matchMedia(QUERY);
}

function notify(): void {
  listeners.forEach((listener) => listener());
}

function subscribe(onChange: () => void): () => void {
  if (listeners.size === 0) query().addEventListener('change', notify);
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
    if (listeners.size === 0) query().removeEventListener('change', notify);
  };
}

const snapshot = () => query().matches;
const serverSnapshot = () => false;

/** 实时订阅系统设置；部分动画库的同名 hook 仅保存挂载时的设置。 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}
