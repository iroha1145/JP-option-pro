/**
 * 横向滚动条（带真实的可操作入口）。
 *
 * 这些卡片带一直是 overflow-x-auto + no-scrollbar：滚动条被藏起来了。
 * 触屏可以直接划；桌面端普通鼠标没有横向滚轮时，最右边那张卡永远是半截。
 *
 * 溢出时两侧渐隐遮罩 + 桌面端左右按钮；触屏保持原样。
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import { computeScrollEdges } from '@/lib/scrollEdges';
import { t } from '@/i18n/core';

interface Props {
  children: ReactNode;
  className?: string;
  scrollerClassName?: string;
  label?: string;
}

export default function HorizontalScroller({
  children,
  className,
  scrollerClassName,
  label,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  const measure = useCallback(() => {
    const node = ref.current;
    if (!node) return;
    const next = computeScrollEdges(node.scrollLeft, node.scrollWidth, node.clientWidth);
    setEdges((prev) => (prev.left === next.left && prev.right === next.right ? prev : next));
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    measure();
    node.addEventListener('scroll', measure, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(node);
    const track = node.firstElementChild;
    if (track) observer?.observe(track);
    return () => {
      node.removeEventListener('scroll', measure);
      observer?.disconnect();
    };
  }, [measure]);

  useEffect(() => {
    measure();
  }, [children, measure]);

  const nudge = useCallback((direction: 1 | -1) => {
    const node = ref.current;
    if (!node) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollBy({ left: direction * node.clientWidth * 0.85, behavior: reduced ? 'instant' : 'smooth' });
  }, []);

  const arrow = (side: 'left' | 'right') => {
    const active = side === 'left' ? edges.left : edges.right;
    if (!active) return null;
    return (
      <button
        type="button"
        aria-label={side === 'left' ? t('向左滚动') : t('向右滚动')}
        onClick={() => nudge(side === 'left' ? -1 : 1)}
        className={cn(
          'absolute top-1/2 z-20 hidden size-8 -translate-y-1/2 items-center justify-center',
          'rounded-md border border-line-strong bg-card text-ink-500 shadow-sh-1',
          'transition-colors duration-fast hover:text-ink-800 focus-visible:outline-none',
          'focus-visible:ring-2 focus-visible:ring-brand-500/30 md:inline-flex',
          side === 'left' ? 'left-1 md:left-2' : 'right-1 md:right-2',
        )}
      >
        <Icon name="chevron-right" size={15} className={side === 'left' ? 'rotate-180' : undefined} />
      </button>
    );
  };

  return (
    <div className={cn('relative', className)}>
      {edges.left && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 z-10 w-10 bg-gradient-to-r from-paper to-transparent"
        />
      )}
      {edges.right && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 z-10 w-10 bg-gradient-to-l from-paper to-transparent"
        />
      )}
      {arrow('left')}
      {arrow('right')}
      <motion.div
        layoutScroll
        ref={ref}
        className={cn('no-scrollbar overflow-x-auto', scrollerClassName)}
        tabIndex={edges.left || edges.right ? 0 : -1}
        role={label ? 'group' : undefined}
        aria-label={label}
      >
        {children}
      </motion.div>
    </div>
  );
}
