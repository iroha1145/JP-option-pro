/**
 * 走步検証の結果（内部パネル）。
 *
 * 目的は検証であって見栄えではないので、意図的に素っ気なくしてある
 * （doc §十「回测展示优先服务于验证，不追求复杂动画」）。
 *
 * 表示の原則は 2 つ:
 *  - **標本不足の層を隠さない**。消すと上位だけ綺麗に見える。
 *  - 単調でないときに、その旨をはっきり書く。分数を「確率」として
 *    読ませないための一文を常に添える。
 */

import { useEffect, useState } from 'react';
import { researchApi } from '@/api/modules';
import type { ResearchReport } from '@/api/types';
import { ApiError } from '@/api/client';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import SoftBadge, { type BadgeTone } from '@/components/shared/SoftBadge';
import { SkeletonCard } from '@/components/shared/Skeleton';
import StatCard from '@/components/shared/StatCard';
import { t } from '@/i18n/core';

const VERDICT_TEXT: Record<string, { label: string; tone: BadgeTone; note: string }> = {
  monotonic: {
    label: '分层单调',
    tone: 'up',
    note: '高分层稳定优于低分层。可作为排序依据。',
  },
  weak: {
    label: '弱单调',
    tone: 'warn',
    note: '部分窗口成立、部分不成立。不足以把分数当作概率。',
  },
  not_monotonic: {
    label: '不单调',
    tone: 'down',
    note: '高分层未稳定优于低分层。当前分数不具备概率含义，只能当作粗排。',
  },
  insufficient_data: {
    label: '样本不足',
    tone: 'neutral',
    note: '可判定的分层不足，尚无法下结论。',
  },
};

function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export default function Research() {
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [state, setState] = useState<'loading' | 'done' | 'empty' | 'running' | 'error'>('loading');

  useEffect(() => {
    let alive = true;
    researchApi
      .report()
      .then((data) => {
        if (!alive) return;
        setReport(data);
        setState('done');
      })
      .catch((error: unknown) => {
        if (!alive) return;
        const status = error instanceof ApiError ? error.code : 0;
        // 「まだ走っている」と「一度も走っていない」を区別して出す。
        setState(status === 409 ? 'running' : status === 503 || status === 404 ? 'empty' : 'error');
      });
    return () => {
      alive = false;
    };
  }, []);

  const verdict = report?.summary?.verdict ?? 'insufficient_data';
  const meta = VERDICT_TEXT[verdict] ?? VERDICT_TEXT.insufficient_data;

  return (
    <div className="space-y-6">
      <PageHeader
        section="10"
        eyebrow="WALK-FORWARD VALIDATION"
        title={t('历史验证')}
        description={t('走步验证：分数是否真的具有排序能力')}
      />

      {state === 'loading' && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <SkeletonCard key={index} />
          ))}
        </div>
      )}

      {state === 'running' && (
        <section className="card-surface p-5">
          <p className="eyebrow">WALK-FORWARD</p>
          <EmptyState
            image="/empty-chart.svg"
            title={t('验证正在运行')}
            description={t('结果尚未确定。完成后此页会显示分层收益与单调性结论。')}
          />
        </section>
      )}

      {state === 'empty' && (
        <section className="card-surface p-5">
          <p className="eyebrow">WALK-FORWARD</p>
          <EmptyState
            image="/empty-chart.svg"
            title={t('尚未运行历史验证')}
            description={t('在服务器执行 python -m app.research 后，结果会显示在这里。')}
          />
        </section>
      )}

      {state === 'error' && (
        <section className="card-surface p-5">
          <p className="eyebrow">WALK-FORWARD</p>
          <EmptyState image="/empty-chart.svg" title={t('读取失败')} description={t('请稍后重试')} />
        </section>
      )}

      {state === 'done' && report && (
        <div className="space-y-4">
          <section className="card-surface card-lift p-5">
            <p className="eyebrow">{t('验证结论')}</p>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <SoftBadge tone={meta.tone} size="md">{t(meta.label)}</SoftBadge>
              <span className="text-caption text-ink-500">
                {t('{ok}/{n} 个窗口单调', {
                  ok: report.summary?.windows_monotonic ?? 0,
                  n: report.summary?.windows_judged ?? 0,
                })}
              </span>
            </div>
            <p className="mt-2 text-caption text-ink-600">{t(meta.note)}</p>
          </section>

          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label={t('信号样本')} value={report.signals ?? 0} icon="crosshair" />
            <StatCard label={t('评估日')} value={report.evaluation_dates ?? 0} icon="calendar-spark" />
            <StatCard label={t('验证窗口')} value={report.summary?.windows ?? 0} icon="layers" />
            {report.summary?.median_top_bottom_spread != null ? (
              <StatCard
                label={t('上位10%−下位10%')}
                value={report.summary.median_top_bottom_spread * 100}
                digits={2}
                suffix="%"
                icon="wallet-gauge"
              />
            ) : (
              <div className="card-surface card-lift p-5">
                <p className="eyebrow">{t('上位10%−下位10%')}</p>
                <p className="mt-2 font-mono text-data-xl text-ink-900 tnum">—</p>
              </div>
            )}
          </section>

          {(report.windows ?? []).map((window) => (
            <section key={`${window.test[0]}-${window.test[1]}`} className="card-surface card-lift p-5">
              <p className="eyebrow">WINDOW · {window.test[0]} — {window.test[1]}</p>
              <header className="mb-2 mt-1 flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-mono text-caption text-ink-700">
                  {window.test[0]} — {window.test[1]}
                </span>
                <span className="text-micro text-ink-400">
                  n={window.samples.toLocaleString('ja-JP')} ·{' '}
                  {t('单调')}: {window.decile_monotonic === null ? '—' : window.decile_monotonic ? '✓' : '✗'}
                </span>
              </header>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-caption">
                  <thead>
                    <tr className="text-ink-400">
                      <th className="py-1 text-left font-normal">{t('分层')}</th>
                      <th className="py-1 text-right font-normal">{t('样本')}</th>
                      <th className="py-1 text-right font-normal">{t('超额中位')}</th>
                      <th className="py-1 text-right font-normal">{t('胜率')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(window.deciles ?? []).map((bucket) => (
                      <tr key={bucket.bucket} className="border-t border-line">
                        <td className="py-1 font-mono text-ink-700">
                          {bucket.bucket}
                          {/* 標本不足を隠さない。消すと上位だけ綺麗に見える。 */}
                          {!bucket.reliable && (
                            <SoftBadge tone="warn" className="ml-1">{t('样本不足')}</SoftBadge>
                          )}
                        </td>
                        <td className="py-1 text-right font-mono text-ink-600 tnum">
                          {bucket.samples.toLocaleString('ja-JP')}
                        </td>
                        <td
                          className={`py-1 text-right font-mono tnum ${
                            (bucket.median_excess_topix ?? 0) >= 0 ? 'text-up-600' : 'text-down-600'
                          }`}
                        >
                          {pct(bucket.median_excess_topix)}
                        </td>
                        <td className="py-1 text-right font-mono text-ink-600 tnum">
                          {pct(bucket.hit_rate, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}

          <section className="card-surface card-lift p-5 text-caption text-ink-600">
            <p className="eyebrow">POINT-IN-TIME LIMITS</p>
            <h3 className="mb-1 mt-1 text-h3 text-ink-900">{t('点时限制')}</h3>
            <ul className="list-disc space-y-1 pl-5">
              {(report.point_in_time_limits ?? []).map((limit) => (
                <li key={limit}>{t(limit)}</li>
              ))}
            </ul>
            <p className="mt-2 text-micro text-ink-500">
              {t('评分版本')}: {report.score_version} · {t('重放版本')}: {report.replay_version}
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
