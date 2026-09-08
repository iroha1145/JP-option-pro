/** 数据状态页：数据集鲜度/能力声明/Worker任务/手动刷新入口。 */

import { useState } from 'react';
import { dataStatusApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonCard, SkeletonReveal, SkeletonRows } from '@/components/shared/Skeleton';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import StatCard from '@/components/shared/StatCard';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import Icon from '@/components/icons';
import { cn } from '@/lib/utils';
import { t } from '@/i18n/core';
import { fmtJstDateTime, fmtTimeHHMMSS } from '@/lib/format';
import ForceRefreshButton from '@/components/shared/ForceRefreshButton';
import SourceNote from '@/components/shared/SourceNote';
import type { DatasetStatus } from '@/api/types';

const MANUAL_ACTIONS: { type: string; label: string }[] = [
  { type: 'post_close_batch', label: '触发收盘批处理' },
  { type: 'master_sync', label: '触发主数据同步' },
  { type: 'fins_sync', label: '触发财务同步' },
  { type: 'backfill_step', label: '推进历史回填' },
  { type: 'radar_refresh', label: '重算雷达' },
];

export default function DataStatus() {
  const query = usePolling(() => dataStatusApi.get(), 60_000);
  const { isOwner } = useAccess();
  const toast = useToast();
  const state = remoteState(query);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const columns: Column<DatasetStatus>[] = [
    {
      key: 'name',
      title: t('数据集'),
      width: '26%',
      render: (row) => (
        <span>
          <span className="block text-body-s text-ink-800">{row.key}</span>
          <span className="block font-mono text-micro text-ink-400">{row.endpoint}</span>
        </span>
      ),
    },
    {
      key: 'status',
      title: t('状态'),
      render: (row) => <CapabilityBadge status={row.status} freshness={row.freshness} />,
    },
    {
      key: 'through',
      title: t('数据截至'),
      align: 'right',
      render: (row) => <span className="font-mono text-caption tnum text-ink-700">{row.data_through ?? '—'}</span>,
    },
    {
      key: 'success',
      title: t('最近成功'),
      align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum text-ink-500">{fmtJstDateTime(row.last_success_at)}</span>
      ),
    },
    {
      key: 'rows',
      title: t('行数'),
      align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum text-ink-500">
          {row.rows_total !== null && row.rows_total !== undefined ? row.rows_total.toLocaleString('ja-JP') : '—'}
        </span>
      ),
    },
    {
      key: 'pending',
      title: t('回填余量'),
      align: 'right',
      render: (row) => (
        <span className="font-mono text-caption tnum text-ink-500">
          {row.backfill_pending !== null && row.backfill_pending !== undefined ? row.backfill_pending : '—'}
        </span>
      ),
    },
    {
      key: 'error',
      title: t('最近错误'),
      render: (row) => (
        <span className="truncate font-mono text-micro text-down-700">{row.last_error_code ?? ''}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        section="09"
        eyebrow="DATA STATUS · J-QUANTS V2"
        title={t('数据状态')}
        description={t('本页为日线数据，收盘后更新')}
        meta={
          <>
            {query.data ? (
              <span className="text-caption text-ink-500">
                {t('数据源')}: {query.data.provider} · {t('订阅计划')}: {query.data.plan.toUpperCase()} · API key:{' '}
                {query.data.api_key_configured ? '✓' : '✗'}
              </span>
            ) : null}
            {query.lastUpdatedAt && (
              <span className="font-mono text-caption text-ink-400 tnum">
                {t('更新')} {fmtTimeHHMMSS(query.lastUpdatedAt)}
              </span>
            )}
            <ForceRefreshButton
              onClick={() => query.refresh({ force: true })}
              spinning={query.refreshing}
              label={t('刷新状态')}
              title={t('刷新状态')}
            />
          </>
        }
      />

      {state === 'error' ? (
        <section className="card-surface">
          <EmptyState
            variant="error"
            image="/empty-chart.svg"
            title={t('加载失败')}
            description={String(query.error?.message ?? '')}
            action={
              <button type="button" onClick={() => query.refresh({ force: true })} className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white shadow-btn-hi transition-[filter] hover:brightness-105">
                {t('重试')}
              </button>
            }
          />
        </section>
      ) : (
        <SkeletonReveal
          loading={state === 'loading'}
          skeleton={
            <div className="space-y-4" aria-busy="true">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {Array.from({ length: 4 }, (_, i) => (
                  <SkeletonCard key={i} className="h-24" />
                ))}
              </div>
              <section className="card-surface">
                <SkeletonRows rows={10} />
              </section>
            </div>
          }
        >
          {query.data ? (
        <>
          {state === 'stale' && (
            <StaleStrip onRetry={() => query.refresh()} refreshing={query.refreshing} />
          )}
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              label={t('数据集')}
              value={query.data.datasets.length}
              icon="layers"
            />
            <StatCard
              label={t('新鲜')}
              value={query.data.datasets.filter((row) => row.freshness === 'fresh').length}
              icon="check"
            />
            <StatCard
              label={t('过期')}
              value={query.data.datasets.filter((row) => row.freshness === 'stale' || row.freshness === 'error').length}
              icon="bell"
            />
            <StatCard
              label="Worker"
              value={Object.keys(query.data.worker?.tasks ?? {}).length}
              icon="refresh"
              sub={
                query.data.worker
                  ? query.data.worker.healthy
                    ? t('运行正常')
                    : t('已降级')
                  : t('暂无数据')
              }
            />
          </section>

          {isOwner && (
            <div className="card-surface flex flex-wrap items-center gap-2 p-5">
              <p className="eyebrow w-full">{t('手动刷新')}</p>
              {MANUAL_ACTIONS.map((action) => (
                <button
                  key={action.type}
                  type="button"
                  disabled={pendingAction !== null}
                  className="inline-flex items-center gap-1.5 rounded-md border border-line bg-card px-3 py-1.5 text-caption text-ink-600 shadow-btn transition-colors hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={async () => {
                    if (pendingAction) return;
                    setPendingAction(action.type);
                    try {
                      const result = await workerApi.trigger(action.type);
                      toast.success(t(action.label), `${t('已提交')} #${result.action_id ?? '?'}`);
                      query.refresh({ force: true });
                    } catch (error) {
                      toast.error(t(action.label), String((error as Error).message ?? error));
                    } finally {
                      setPendingAction(null);
                    }
                  }}
                >
                  <Icon
                    name="refresh"
                    size={13}
                    className={cn(pendingAction === action.type && 'animate-spin-once')}
                  />
                  {t(action.label)}
                </button>
              ))}
            </div>
          )}

          <section className="card-surface p-5">
            <p className="eyebrow">DATASETS · J-QUANTS</p>
            <h2 className="mb-3 mt-1 text-h3 text-ink-900">{t('数据集')}</h2>
            <DataTable columns={columns} rows={query.data.datasets} rowKey={(row) => row.key} rowHeight={56} />
          </section>

          <section className="card-surface p-5">
            <p className="eyebrow">INTRADAY</p>
            <h2 className="mb-2 mt-1 text-h3 text-ink-900">
              {query.data.intraday.enabled ? t('盘中数据') : t('盘中数据未接入')}
            </h2>
            <p className="text-body-s text-ink-500">{query.data.intraday.note_ja ?? ''}</p>
          </section>

          {query.data.worker && (
            <section className="card-surface p-5">
              <p className="eyebrow">WORKER</p>
              <h2 className="mb-2 mt-1 flex items-center gap-2 text-h3 text-ink-900">
                Worker
                <SoftBadge tone={query.data.worker.healthy ? 'brand' : 'warn'}>
                  {query.data.worker.healthy ? 'healthy' : 'degraded'}
                </SoftBadge>
              </h2>
              <ul className="grid grid-cols-1 gap-1.5 text-body-s md:grid-cols-2">
                {Object.entries(query.data.worker.tasks ?? {}).map(([name, task]) => (
                  <li key={name} className="flex items-center justify-between rounded-md bg-paper-2 px-2.5 py-1.5">
                    <span className="font-mono text-caption text-ink-700">{name}</span>
                    <span className="flex items-center gap-2 text-micro text-ink-500">
                      <span>{task.status}</span>
                      {task.error_code && <span className="text-down-700">{task.error_code}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
          ) : null}
        </SkeletonReveal>
      )}
      <SourceNote className="mt-8" text={t('本页展示 J-Quants 同步状态与 worker 任务')} />
    </div>
  );
}

function CapabilityBadge({ status, freshness }: { status: DatasetStatus['status']; freshness?: string | null }) {
  if (status === 'unavailable') {
    return <SoftBadge>{t('不可用')}</SoftBadge>;
  }
  if (status === 'planned') {
    return <SoftBadge tone="brand">{t('未接入')}</SoftBadge>;
  }
  const tone = freshness === 'fresh' ? 'ai' : freshness === 'stale' || freshness === 'error' ? 'warn' : 'neutral';
  const label =
    freshness === 'fresh' ? t('新鲜') : freshness === 'stale' ? t('过期') : freshness === 'never_synced' ? t('从未同步') : freshness ?? '—';
  return <SoftBadge tone={tone}>{label}</SoftBadge>;
}
