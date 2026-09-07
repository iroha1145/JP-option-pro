/**
 * 雷达信号卡 3×3 迷你评分格。缺失显「—」+ 空轨道，不编造 0。
 * 追高风险反向着色。
 */
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { riskBarClass, strengthBarClass } from '@/lib/strengthColor';
import PointerTooltip from '@/components/shared/PointerTooltip';
import type { RadarEvent, RadarScores } from '@/api/types';
import { t } from '@/i18n/core';

const SCORE_DEFS = [
  { key: 'breakout_quality', label: '综合质量', risk: false },
  { key: 'trend_quality', label: '趋势质量', risk: false },
  { key: 'base_quality', label: '基底质量', risk: false },
  { key: 'breakout_confirmation', label: '突破确认', risk: false },
  { key: 'relative_strength', label: '相对强度', risk: false },
  { key: 'participation', label: '量能', risk: false },
  { key: 'liquidity', label: '流动性', risk: false },
  { key: 'market_fit', label: '市场契合', risk: false },
  { key: 'chase_risk', label: '追高风险', risk: true },
] as const;

const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const disp = (v: unknown): string => (fin(v) ? String(Math.round(v)) : '—');

function scoreOf(scores: RadarScores | undefined, key: (typeof SCORE_DEFS)[number]['key']): number | null {
  if (!scores) return null;
  if (key === 'market_fit' || key === 'chase_risk') {
    const value = scores[key];
    return fin(value) ? value : null;
  }
  const pack = scores[key];
  return fin(pack?.score) ? pack.score : null;
}

export default function ScoreBarsMini({ event, className }: { event: RadarEvent; className?: string }) {
  return (
    <div className={cn('radar-score-grid grid grid-cols-3 gap-x-3 gap-y-2.5', className)} aria-label={t('评分套组')}>
      {SCORE_DEFS.map((def, index) => {
        const value = scoreOf(event.scores, def.key);
        const label = t(def.label);
        return (
          <PointerTooltip
            key={def.key}
            passthrough
            className="min-w-0"
            label={`${label} ${disp(value)}`}
            width={160}
            contentClassName="p-2"
            content={
              <span className="text-micro text-ink-600">
                {label} {disp(value)}
              </span>
            }
          >
            <div>
              <p className="flex items-baseline justify-between">
                <span className="text-[11px] leading-[16px] text-ink-500">{label}</span>
                <span className="font-mono text-[11px] leading-[16px] text-ink-700 tnum">{disp(value)}</span>
              </p>
              <div className="radar-bar-track mt-0.5 h-[5px] overflow-hidden rounded-pill">
                {fin(value) && (
                  <motion.div
                    className={cn(
                      'h-full origin-left rounded-pill',
                      def.risk ? riskBarClass(value) : strengthBarClass(value),
                    )}
                    initial={{ scaleX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    viewport={{ once: true, amount: 0.4 }}
                    transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: index * 0.03 }}
                    style={{ width: `${Math.max(3, Math.min(100, value))}%` }}
                  />
                )}
              </div>
            </div>
          </PointerTooltip>
        );
      })}
    </div>
  );
}
