/**
 * 渐进挂载长列表。
 *
 * 只限制渲染多少，不限制拿到多少：排序、统计、涨跌家数一律仍在完整
 * 数据上计算，用户滚动到底部会自动接着挂载。分页会改变「这就是全部」的语义，
 * 渐进挂载不会。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';

export interface ProgressiveList<T> {
  visible: T[];
  hasMore: boolean;
  remaining: number;
  loadMore: () => void;
  loadAll: () => void;
  prepareForPrint: () => void;
  restoreAfterPrint: () => void;
  sentinelRef: (node: HTMLElement | null) => void;
}

export function useProgressiveList<T>(
  items: T[],
  { initial = 24, step = 24 }: { initial?: number; step?: number } = {},
): ProgressiveList<T> {
  const [limit, setLimit] = useState(initial);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const total = items.length;

  const boundedLimit = total > 0 ? Math.max(initial, Math.min(limit, total)) : limit;
  if (boundedLimit !== limit) setLimit(boundedLimit);

  const loadAll = useCallback(() => setLimit(Number.MAX_SAFE_INTEGER), []);

  const limitBeforePrintRef = useRef<number | null>(null);
  const limitRef = useRef(limit);
  useEffect(() => {
    limitRef.current = limit;
  }, [limit]);

  const prepareForPrint = useCallback(() => {
    if (limitBeforePrintRef.current === null) limitBeforePrintRef.current = limitRef.current;
    flushSync(() => setLimit(Number.MAX_SAFE_INTEGER));
  }, []);

  const restoreAfterPrint = useCallback(() => {
    const previous = limitBeforePrintRef.current;
    limitBeforePrintRef.current = null;
    if (previous !== null) setLimit(previous);
  }, []);

  const loadMore = useCallback(() => {
    setLimit((current) => (current >= total ? current : current + step));
  }, [step, total]);

  const sentinelRef = useCallback(
    (node: HTMLElement | null) => {
      observerRef.current?.disconnect();
      if (!node || typeof IntersectionObserver === 'undefined') return;
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) loadMore();
        },
        { rootMargin: '600px 0px' },
      );
      observer.observe(node);
      observerRef.current = observer;
    },
    [loadMore],
  );

  useEffect(() => () => observerRef.current?.disconnect(), []);

  const visible = useMemo(
    () => (limit >= total ? items : items.slice(0, limit)),
    [items, limit, total],
  );

  return {
    visible,
    hasMore: limit < total,
    remaining: Math.max(0, total - limit),
    loadMore,
    loadAll,
    prepareForPrint,
    restoreAfterPrint,
    sentinelRef,
  };
}
