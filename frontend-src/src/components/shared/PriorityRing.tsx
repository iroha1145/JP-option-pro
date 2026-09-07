/** 告警/行为优先级环：轨道 + brand 弧 draw-line + count-up。对齐 option-pro LeadBigCard。 */

import { motion } from 'framer-motion';
import InfoHint from '@/components/shared/InfoHint';
import { useCountUp } from '@/hooks/useCountUp';
import { DUR_SECTION, EASE_PAPER } from '@/lib/motion';
import type { ScoreHint } from '@/lib/indicatorHints';

export default function PriorityRing({
  score,
  label,
  hint,
  emptyLabel,
}: {
  score: number | null;
  label: string;
  hint?: ScoreHint;
  emptyLabel: string;
}) {
  const animated = useCountUp(score ?? Number.NaN, 900);
  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const frac = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  return (
    <div
      className="flex shrink-0 flex-col items-center"
      aria-label={score === null ? emptyLabel : `${label} ${Math.round(score)}`}
    >
      <div className="relative size-[64px]">
        <svg viewBox="0 0 64 64" className="size-full -rotate-90" aria-hidden="true">
          <circle cx="32" cy="32" r={radius} fill="none" stroke="var(--line)" strokeWidth="4.5" />
          {score !== null && (
            <motion.circle
              cx="32"
              cy="32"
              r={radius}
              fill="none"
              stroke="var(--brand-600)"
              strokeWidth="4.5"
              strokeLinecap="round"
              strokeDasharray={circumference}
              initial={{ strokeDashoffset: circumference }}
              animate={{ strokeDashoffset: circumference * (1 - frac) }}
              transition={{ duration: DUR_SECTION, ease: EASE_PAPER }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-mono text-[15px] font-medium leading-[20px] text-ink-900 tnum">
            <span className="sr-only">{score === null ? '—' : Math.round(score)}</span>
            <span aria-hidden="true">{score === null ? '—' : Math.round(animated)}</span>
          </span>
        </div>
      </div>
      <span className="mt-0.5 whitespace-nowrap text-[11px] leading-[15px] text-ink-400">
        {label}
        {hint && <InfoHint hint={hint} side="top" align="end" size={11} className="ml-0.5" />}
      </span>
    </div>
  );
}
