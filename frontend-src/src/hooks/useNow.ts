import { useEffect, useState } from 'react';

/**
 * 按间隔走字的当前时间。intervalMs <= 0 时只取一次，不挂定时器。
 * ≥10s 的间隔自动对齐整周期边界（如 60_000 对齐每分钟 00 秒），页面切到后台时停表。
 */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!intervalMs || intervalMs <= 0) return undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      clearTimeout(timer);
      timer = undefined;
    };
    const schedule = () => {
      const current = Date.now();
      const delay = intervalMs >= 10_000
        ? intervalMs - (current % intervalMs) + 20
        : intervalMs;
      timer = setTimeout(() => {
        setNow(Date.now());
        schedule();
      }, delay);
    };
    const resume = () => {
      stop();
      if (document.hidden) return;
      setNow(Date.now());
      schedule();
    };
    if (!document.hidden) schedule();
    document.addEventListener('visibilitychange', resume);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', resume);
    };
  }, [intervalMs]);
  return now;
}
