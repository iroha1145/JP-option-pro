/**
 * 结果行共享单元格：强度分条 / 六族分项微条 / 新闻72h徽标。
 * 桌面表格与移动卡片流共用。hover 小窗走 PointerTooltip（portal），
 * 避免被表格 overflow 或 Layout overflow-x-clip 裁掉。
 * 强度条首帧即完整比例（对标美站 ScoreCell），不再 scaleX 入场。
 */
import type { NewsSecurityRow, StrengthRow } from '@/api/types';
import { cn } from '@/lib/utils';
import { fmtRelativeShort } from '@/lib/format';
import Icon from '@/components/icons';
import PointerTooltip from '@/components/shared/PointerTooltip';
import SoftBadge from '@/components/shared/SoftBadge';
import { SkeletonBlock } from '@/components/shared/Skeleton';
import { FAMILY_META, strengthPresentation } from './types';
import { t } from '@/i18n/core';

/* ---------------- 强度分：Mono 15 600 + 64px 强度条（固定分档着色） ---------------- */
export function ScoreCell({ score }: { score: number | null; index?: number }) {
  if (score === null) {
    return <span className="font-mono text-caption text-ink-300">—</span>;
  }
  const strength = strengthPresentation(score);
  return (
    <PointerTooltip
      label={`${strength.band} ${strength.label}`}
      width={168}
      contentClassName="p-2.5"
      content={
        <>
          <span className="block text-caption font-semibold text-ink-800">
            {strength.band} · {strength.label}
          </span>
          <span className="mt-1 block font-mono text-micro text-ink-500 tnum">{score.toFixed(1)}</span>
        </>
      }
    >
      <span className="inline-flex items-center gap-2.5">
      <SoftBadge tone={strength.badgeTone} className="metric-value w-[3.25rem] shrink-0 justify-end text-[15px] leading-[20px] font-semibold tnum">
        {score.toFixed(1)}
      </SoftBadge>
      <span
        className="strength-track h-1 w-16 overflow-hidden rounded-pill bg-paper"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
        aria-label={t('强度分 {score}', { score: score.toFixed(1) })}
        data-strength-band={strength.band}
      >
        <span
          className={cn('block h-full origin-left rounded-pill', strength.barClass)}
          style={{ width: `${Math.max(2, Math.min(100, score))}%` }}
        />
      </span>
      </span>
    </PointerTooltip>
  );
}

/* ---------------- 六族分项微条（14×3px 轨道 + 跟随指针的 cloud-popover） ---------------- */
export function SubscoreTicks({ row, tipSide = 'top' }: { row: StrengthRow; tipSide?: 'top' | 'bottom' }) {
  const dims = FAMILY_META.map(({ key, label }) => ({ key, label, value: row.families[key] ?? null }));
  return (
    <PointerTooltip
      label={t('分项强度')}
      side={tipSide}
      width={176}
      className="gap-1"
      contentClassName="p-2.5"
      content={dims.map(({ key, label, value }) => (
        <span key={key} className="flex items-center justify-between gap-3 py-0.5 text-micro">
          <span className="text-ink-500">{label}</span>
          <span className="font-mono text-ink-800 tnum">{value !== null ? Math.round(value) : '—'}</span>
        </span>
      ))}
    >
      {dims.map(({ key, value }) => (
        <span key={key} className="inline-block h-1 w-[15px] overflow-hidden rounded-full bg-paper" aria-hidden="true">
          {value !== null && (
            <span
              className={cn('block h-full rounded-full', value >= 70 ? 'bg-brand-600' : value >= 45 ? 'bg-brand-400' : 'bg-warn-600')}
              style={{ width: `${Math.max(8, Math.min(100, value))}%` }}
            />
          )}
        </span>
      ))}
    </PointerTooltip>
  );
}

/* ---------------- 新闻72h徽标：一次批量取回；无新闻显 0，未取到显骨架 ---------------- */
export function NewsBadge({
  summary,
  loaded,
  tipSide = 'top',
}: {
  summary: NewsSecurityRow | undefined;
  loaded: boolean;
  tipSide?: 'top' | 'bottom';
}) {
  if (!loaded) {
    return <SkeletonBlock className="inline-block h-5 w-14 rounded-xs" />;
  }
  if (!summary || summary.news_count === 0) {
    return (
      <SoftBadge aria-label={t('72 小时内无新闻')}>0</SoftBadge>
    );
  }
  const importance = summary.max_importance ?? 0;
  const tone = importance >= 75 ? 'warn' : importance >= 55 ? 'brand' : 'neutral';
  return (
    <PointerTooltip
      label={`${t('新闻 · 72H')} · ${summary.news_count}`}
      side={tipSide}
      width={240}
      contentClassName="p-3"
      content={
        <>
          <span className="block text-micro text-ink-500">
            {t('72h 窗口')} · {summary.news_count} {t('条')}
            {summary.max_importance !== null && (
              <>
                {' · '}
                {t('最高重要度')} <span className="font-mono tnum">{Math.round(importance)}</span>
              </>
            )}
          </span>
          {summary.latest?.title && (
            <span className="mt-1.5 line-clamp-3 break-words text-caption text-ink-800">{summary.latest.title}</span>
          )}
          {summary.latest?.published_at && (
            <span className="mt-0.5 block font-mono text-micro text-ink-400 tnum">{fmtRelativeShort(summary.latest.published_at)}</span>
          )}
          <span className="mt-1 block text-[10px] text-ink-300">{t('仅覆盖已接入的 RSS 新闻源')}</span>
        </>
      }
    >
      <SoftBadge tone={tone}>
        <Icon name="bolt" size={11} />
        <span className="font-mono tnum">{summary.news_count}</span>
        {summary.max_importance !== null && (
          <span className="font-mono text-[10px] tnum opacity-80">· {Math.round(importance)}</span>
        )}
      </SoftBadge>
    </PointerTooltip>
  );
}
