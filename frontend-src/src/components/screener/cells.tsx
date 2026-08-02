/**
 * 结果行共享单元格：强度分条（grow-bar 错峰）/ 六族分项微条 / 新闻72h徽标。
 * 桌面表格与移动卡片流共用。数据缺失如实空轨道显「—」，不编造。
 */
import { motion } from 'framer-motion';
import type { NewsSecurityRow, StrengthRow } from '@/api/types';
import { cn } from '@/lib/utils';
import { fmtRelativeShort } from '@/lib/format';
import Icon from '@/components/icons';
import { FAMILY_META, strengthPresentation } from './types';
import { t } from '@/i18n/core';

const EASE_PAPER = [0.16, 1, 0.3, 1] as [number, number, number, number];

/* ---------------- 强度分：Mono 15 600 + 64px 强度条（固定分档着色） ---------------- */
export function ScoreCell({ score, index }: { score: number | null; index: number }) {
  if (score === null) {
    return <span className="font-mono text-caption text-ink-300">—</span>;
  }
  const strength = strengthPresentation(score);
  return (
    <span className="inline-flex items-center gap-2.5" title={`${strength.band} ${strength.label}`}>
      {/* 定宽 + 一位小数：84 与 84.4 字符数不同会把横条推歪整列 */}
      <span className={cn('w-[3.25rem] shrink-0 text-right font-mono text-[15px] font-semibold leading-[20px] tnum', strength.textClass)}>
        {score.toFixed(1)}
      </span>
      <span
        className="h-1 w-16 overflow-hidden rounded-pill bg-line"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
        aria-label={t('强度分 {score}', { score: score.toFixed(1) })}
        data-strength-band={strength.band}
      >
        <motion.span
          className={cn('block h-full origin-left rounded-pill', strength.barClass)}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.7, ease: EASE_PAPER, delay: 0.15 + index * 0.03 }}
          style={{ width: `${Math.max(2, Math.min(100, score))}%` }}
        />
      </span>
    </span>
  );
}

/* ---------------- 六族分项微条（14×3px 轨道 + hover 毛玻璃 tooltip） ---------------- */
export function SubscoreTicks({ row, tipSide = 'top' }: { row: StrengthRow; tipSide?: 'top' | 'bottom' }) {
  const dims = FAMILY_META.map(({ key, label }) => ({ key, label, value: row.families[key] ?? null }));
  return (
    <span className="group relative inline-flex items-center gap-1" aria-label={t('分项强度')}>
      {dims.map(({ key, value }) => (
        <span key={key} className="inline-block h-[3px] w-[11px] overflow-hidden rounded-full bg-line" aria-hidden="true">
          {value !== null && (
            <span
              className={cn('block h-full rounded-full', value >= 70 ? 'bg-brand-600' : value >= 45 ? 'bg-brand-400' : 'bg-warn-600')}
              style={{ width: `${Math.max(8, Math.min(100, value))}%` }}
            />
          )}
        </span>
      ))}
      <span
        className={cn(
          'glass pointer-events-none absolute left-1/2 z-20 hidden w-44 -translate-x-1/2 rounded-md border border-line p-2.5 shadow-sh-2 group-hover:block',
          tipSide === 'top' ? '-top-2 -translate-y-full' : '-bottom-2 translate-y-full',
        )}
      >
        {dims.map(({ key, label, value }) => (
          <span key={key} className="flex items-center justify-between py-0.5 text-micro">
            <span className="text-ink-500">{label}</span>
            <span className="font-mono text-ink-800 tnum">{value !== null ? Math.round(value) : '—'}</span>
          </span>
        ))}
      </span>
    </span>
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
    return <span className="skeleton-shimmer inline-block h-5 w-14 rounded-xs" aria-hidden="true" />;
  }
  if (!summary || summary.news_count === 0) {
    return (
      <span className="font-mono text-caption text-ink-300 tnum" aria-label={t('72 小时内无新闻')}>
        0
      </span>
    );
  }
  const importance = summary.max_importance ?? 0;
  const tone =
    importance >= 75 ? 'text-warn-600 bg-warn-50' : importance >= 55 ? 'text-brand-700 bg-brand-50' : 'text-ink-500 bg-card-warm';
  return (
    <span className="group relative inline-flex">
      <span className={cn('inline-flex items-center gap-1 rounded-xs px-1.5 py-0.5 text-micro font-medium leading-[16px]', tone)}>
        <Icon name="bolt" size={11} />
        <span className="font-mono tnum">{summary.news_count}</span>
        {summary.max_importance !== null && (
          <span className="font-mono text-[10px] tnum opacity-80">· {Math.round(importance)}</span>
        )}
      </span>
      <span
        className={cn(
          'glass pointer-events-none absolute right-0 z-20 hidden w-60 rounded-md border border-line p-3 shadow-sh-2 group-hover:block',
          tipSide === 'top' ? '-top-2 -translate-y-full' : '-bottom-2 translate-y-full',
        )}
      >
        <span className="block text-micro text-ink-500">
          {t('72h 窗口')} · {summary.news_count} {t('条')}
          {summary.max_importance !== null && <> · {t('最高重要度')} <span className="font-mono tnum">{Math.round(importance)}</span></>}
        </span>
        {summary.latest?.title && (
          <span className="mt-1.5 block truncate text-caption text-ink-800" title={summary.latest.title}>
            {summary.latest.title}
          </span>
        )}
        {summary.latest?.published_at && (
          <span className="mt-0.5 block font-mono text-micro text-ink-400 tnum">{fmtRelativeShort(summary.latest.published_at)}</span>
        )}
        <span className="mt-1 block text-[10px] text-ink-300">{t('仅覆盖已接入的 RSS 新闻源')}</span>
      </span>
    </span>
  );
}
