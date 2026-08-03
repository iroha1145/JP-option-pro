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
import { SkeletonCard } from '@/components/shared/Skeleton';
import { t } from '@/i18n/core';

const VERDICT_TEXT: Record<string, { label: string; tone: string; note: string }> = {
  monotonic: {
    label: '分层单调',
    tone: 'text-up-700 bg-up-50 border-up-200',
    note: '高分层稳定优于低分层。可作为排序依据。',
  },
  weak: {
    label: '弱单调',
    tone: 'text-warn-700 bg-warn-50 border-warn-200',
    note: '部分窗口成立、部分不成立。不足以把分数当作概率。',
  },
  not_monotonic: {
    label: '不单调',
    tone: 'text-down-700 bg-down-50 border-down-200',
    note: '高分层未稳定优于低分层。当前分数不具备概率含义，只能当作粗排。',
  },
  insufficient_data: {
    label: '样本不足',
    tone: 'text-ink-600 bg-ink-50 border-line',
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
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-4 md:px-6">
      <PageHeader
        section="09"
        eyebrow="WALK-FORWARD VALIDATION"
        title={t('历史验证')}
        description={t('走步验证：分数是否真的具有排序能力')}
      />

      {state === 'loading' && <SkeletonCard />}

      {state === 'running' && (
        <EmptyState
          title={t('验证正在运行')}
          description={t('结果尚未确定。完成后此页会显示分层收益与单调性结论。')}
        />
      )}

      {state === 'empty' && (
        <EmptyState
          title={t('尚未运行历史验证')}
          description={t('在服务器执行 python -m app.research 后，结果会显示在这里。')}
        />
      )}

      {state === 'error' && <EmptyState title={t('读取失败')} description={t('请稍后重试')} />}

      {state === 'done' && report && (
        <div className="space-y-4">
          <section className={`rounded-lg border px-4 py-3 ${meta.tone}`}>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-data-l font-semibold">{t(meta.label)}</span>
              <span className="text-caption">
                {t('{ok}/{n} 个窗口单调', {
                  ok: report.summary?.windows_monotonic ?? 0,
                  n: report.summary?.windows_judged ?? 0,
                })}
              </span>
            </div>
            <p className="mt-1 text-caption">{t(meta.note)}</p>
          </section>

          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: t('信号样本'), value: (report.signals ?? 0).toLocaleString('ja-JP') },
              { label: t('评估日'), value: String(report.evaluation_dates ?? 0) },
              { label: t('验证窗口'), value: String(report.summary?.windows ?? 0) },
              {
                label: t('上位10%−下位10%'),
                value:
                  report.summary?.median_top_bottom_spread != null
                    ? pct(report.summary.median_top_bottom_spread)
                    : '—',
              },
            ].map((item) => (
              <div key={item.label} className="rounded-md border border-line bg-card px-3 py-2">
                <div className="text-micro text-ink-400">{item.label}</div>
                <div className="font-mono text-data-m text-ink-900 tnum">{item.value}</div>
              </div>
            ))}
          </section>

          {(report.windows ?? []).map((window) => (
            <section key={`${window.test[0]}-${window.test[1]}`} className="rounded-lg border border-line bg-card p-4">
              <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
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
                            <span className="ml-1 text-micro text-warn-600">{t('样本不足')}</span>
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

          <section className="rounded-lg border border-line bg-ink-50 p-4 text-caption text-ink-600">
            <h3 className="mb-1 font-semibold text-ink-800">{t('点时限制')}</h3>
            <ul className="list-disc space-y-1 pl-5">
              {(report.point_in_time_limits ?? []).map((limit) => (
                <li key={limit}>{limit}</li>
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
