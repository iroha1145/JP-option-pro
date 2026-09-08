import { t } from '@/i18n/core';

/** 功能页错误空态重试：对标美站 Watchlist / Earnings 的 shadow-btn-hi + 忙态转圈。
 *  首页 / 404 / K 线空态仍走 btn-primary，不要用这颗。 */
export default function EmptyRetryButton({
  onClick,
  refreshing = false,
  label,
}: {
  onClick: () => void;
  refreshing?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={refreshing}
      className="flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-caption font-medium text-white shadow-btn-hi transition-[filter] hover:brightness-105 disabled:opacity-60"
    >
      {refreshing && (
        <span
          className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"
          aria-hidden="true"
        />
      )}
      {label ?? t('重试')}
    </button>
  );
}
