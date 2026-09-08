import { Link, useLocation } from 'react-router';
import { watchlistApi } from '@/api/modules';
import { ApiError } from '@/api/client';
import { useAccess } from '@/hooks/useAccess';
import { usePolling } from '@/hooks/usePolling';
import { useToast } from '@/hooks/useToast';
import Icon from '@/components/icons';
import { t } from '@/i18n/core';

export default function WatchlistToggle({
  canonicalCode,
  displayCode,
}: {
  canonicalCode: string;
  displayCode: string;
}) {
  const { canManageWatchlist } = useAccess();
  const location = useLocation();
  const toast = useToast();
  const query = usePolling(() => watchlistApi.list(), 120_000, [canonicalCode]);
  const anonymous =
    query.error instanceof ApiError && query.error.bizCode === 'account_login_required';
  const selected =
    query.data?.items.some(
      (item) => item.canonical_code === canonicalCode || item.display_code === displayCode,
    ) ?? false;
  const style =
    'inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border border-line-strong bg-card px-3 text-caption font-medium text-ink-600 shadow-btn hover:border-brand-400 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50';

  if (!canManageWatchlist || anonymous) {
    return (
      <Link className={style} to="/login" state={{ from: location.pathname }}>
        <Icon name="plus" size={15} />
        {t('登录后加入自选')}
      </Link>
    );
  }

  const toggle = async () => {
    if (query.error) {
      await query.refresh({ force: true });
      return;
    }
    try {
      if (selected) {
        await watchlistApi.remove(canonicalCode);
        toast.success(t('已移出自选'), displayCode);
      } else {
        const result = await watchlistApi.add(canonicalCode);
        toast.success(t('加入自选'), result.created ? t('已加入') : t('已在自选中'));
      }
      await query.refresh({ force: true });
    } catch (error) {
      toast.error(selected ? t('移除失败') : t('加入失败'), error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <button
      type="button"
      className={style}
      aria-pressed={selected}
      disabled={query.loading && !query.data}
      title={selected ? t('移出自选') : undefined}
      onClick={() => void toggle()}
    >
      <Icon name={selected ? 'check' : 'plus'} size={15} />
      {query.loading && !query.data
        ? t('正在读取自选…')
        : query.error
          ? t('重试读取自选')
          : selected
            ? t('已加入自选')
            : t('加入自选')}
    </button>
  );
}
