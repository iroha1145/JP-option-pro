/** 日股领域小组件：状态徽章、数据截至徽章、评分条、代码徽标。 */

import { Link } from 'react-router';
import InfoHint from '@/components/shared/InfoHint';
import { t } from '@/i18n/core';
import { fmtDate, fmtScore } from '@/lib/format';
import { radarScoreHint, type ScoreHint } from '@/lib/indicatorHints';
import { cn } from '@/lib/utils';

export const RADAR_STATE_LABELS: Record<string, string> = {
  discovered: '已发现',
  watching: '观察中',
  triggered: '已触发',
  confirmed: '已确认',
  holding: '保持中',
  retesting: '回踩中',
  retest_held: '回踩企稳',
  reaccelerating: '再加速',
  extended: '过热延伸',
  failed: '已失效',
  expired: '已过期',
};

export const SIGNAL_LABELS: Record<string, string> = {
  high_break_252: '52周高点突破',
  high_break_120: '120日高点突破',
  base_breakout: '基底突破',
  high_break_60: '60日高点突破',
  high_break_20: '20日高点突破',
  volume_surge_break: '放量突破',
};

const STATE_TONES: Record<string, string> = {
  discovered: 'bg-brand-50 text-brand-700',
  watching: 'bg-brand-50 text-brand-700',
  triggered: 'bg-warn-50 text-warn-700',
  confirmed: 'bg-up-50 text-up-700',
  holding: 'bg-up-50 text-up-700',
  retesting: 'bg-warn-50 text-warn-700',
  retest_held: 'bg-up-50 text-up-700',
  reaccelerating: 'bg-up-50 text-up-700',
  extended: 'bg-warn-50 text-warn-700',
  failed: 'bg-down-50 text-down-700',
  expired: 'bg-paper-2 text-ink-400',
};

export function StateChip({ state }: { state: string }) {
  const label = RADAR_STATE_LABELS[state] ?? state;
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-pill px-2 py-0.5 text-micro font-medium',
        STATE_TONES[state] ?? 'bg-paper-2 text-ink-500',
      )}
    >
      {t(label)}
    </span>
  );
}

export function SignalChip({ signal }: { signal: string }) {
  return (
    <span className="inline-flex items-center rounded-pill border border-line bg-card px-2 py-0.5 text-micro text-ink-600">
      {t(SIGNAL_LABELS[signal] ?? signal)}
    </span>
  );
}

/** 数据基准日徽章 —— 每个数据卡都必须标注截至日期，不冒充实时。 */
export function DataThrough({ date, className }: { date: string | null | undefined; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 text-caption text-ink-400', className)}>
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-ink-300" aria-hidden />
      {t('数据截至')} {fmtDate(date)} · {t('日线数据')}
    </span>
  );
}

export function ScoreBar({
  label,
  score,
  hint,
}: {
  label: string;
  score: number | null | undefined;
  /** 省略时按 label 自动查 RADAR_SCORE_HINTS；传 false 明确关闭。 */
  hint?: ScoreHint | false;
}) {
  const value = score ?? null;
  const resolvedHint = hint === false ? undefined : (hint ?? radarScoreHint(label));
  return (
    <div className="flex items-center gap-2">
      <span className="flex w-24 shrink-0 items-center gap-1 text-caption text-ink-500">
        <span className="truncate">{t(label)}</span>
        {resolvedHint && <InfoHint hint={resolvedHint} size={12} />}
      </span>
      <div className="track relative h-1.5 flex-1 overflow-hidden rounded-pill bg-line">
        {value !== null && (
          <div
            className={cn(
              'absolute inset-y-0 left-0 rounded-pill',
              value >= 70 ? 'bg-up-600' : value >= 45 ? 'bg-brand-500' : 'bg-warn-600',
            )}
            style={{ width: `${Math.max(3, Math.min(100, value))}%` }}
          />
        )}
      </div>
      <span className="w-8 text-right font-mono text-caption tnum text-ink-700">{fmtScore(value)}</span>
    </div>
  );
}

export function CodeCell({
  displayCode,
  nameJa,
  to,
}: {
  displayCode: string;
  nameJa?: string | null;
  to?: string;
}) {
  const body = (
    <span className="flex min-w-0 items-center gap-2">
      <span className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-body-s font-semibold text-brand-700">
        {displayCode}
      </span>
      <span className="min-w-0 truncate text-body-s text-ink-800">{nameJa ?? '—'}</span>
    </span>
  );
  if (!to) return body;
  return (
    <Link to={to} className="group flex min-w-0 items-center gap-2 hover:underline">
      {body}
    </Link>
  );
}
