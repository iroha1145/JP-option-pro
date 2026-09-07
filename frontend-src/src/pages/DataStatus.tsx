/** 数据状态页：数据集鲜度/能力声明/Worker任务/手动刷新入口。 */

import { dataStatusApi, workerApi } from '@/api/modules';
import { usePolling } from '@/hooks/usePolling';
import { remoteState } from '@/hooks/remoteState';
import PageHeader from '@/components/shared/PageHeader';
import EmptyState from '@/components/shared/EmptyState';
import DataTable, { type Column } from '@/components/shared/DataTable';
import { SkeletonRows } from '@/components/shared/Skeleton';
import SoftBadge from '@/components/shared/SoftBadge';
import StaleStrip from '@/components/shared/StaleStrip';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import { t } from '@/i18n/core';
import { fmtJstDateTime } from '@/lib/format';
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
          query.data ? (
            <span className="text-caption text-ink-500">
              {t('数据源')}: {query.data.provider} · {t('订阅计划')}: {query.data.plan.toUpperCase()} · API key:{' '}
              {query.data.api_key_configured ? '✓' : '✗'}
            </span>
          ) : undefined
        }
      />

      {state === 'loading' ? (
        <SkeletonRows rows={10} />
      ) : state === 'error' ? (
        <EmptyState variant="error" title={t('加载失败')} description={String(query.error?.message ?? '')} />
      ) : query.data ? (
        <>
          {state === 'stale' && (
            <StaleStrip onRetry={() => query.refresh()} refreshing={query.refreshing} />
          )}
          {isOwner && (
            <div className="card-surface flex flex-wrap items-center gap-2 p-3">
              <span className="text-caption text-ink-400">{t('手动刷新')}:</span>
              {MANUAL_ACTIONS.map((action) => (
                <button
                  key={action.type}
                  type="button"
                  className="control-button"
                  onClick={async () => {
                    try {
                      const result = await workerApi.trigger(action.type);
                      toast.success(t(action.label), `${t('已提交')} #${result.action_id ?? '?'}`);
                    } catch (error) {
                      toast.error(t(action.label), String((error as Error).message ?? error));
                    }
                  }}
                >
                  {t(action.label)}
                </button>
              ))}
            </div>
          )}

          <DataTable columns={columns} rows={query.data.datasets} rowKey={(row) => row.key} rowHeight={56} />

          <section className="card-surface p-4">
            <h2 className="mb-2 text-h3 text-ink-900">
              {query.data.intraday.enabled ? t('盘中数据') : t('盘中数据未接入')}
            </h2>
            <p className="text-body-s text-ink-500">{query.data.intraday.note_ja ?? ''}</p>
          </section>

          {query.data.worker && (
            <section className="card-surface p-4">
              <h2 className="mb-2 flex items-center gap-2 text-h3 text-ink-900">
                Worker
                <SoftBadge tone={query.data.worker.healthy ? 'up' : 'down'}>
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
