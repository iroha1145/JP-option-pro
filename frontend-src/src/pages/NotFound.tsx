import { Link, useLocation } from 'react-router';
import EmptyState from '@/components/shared/EmptyState';
import { t } from '@/i18n/core';

export default function NotFound() {
  const location = useLocation();
  return (
    <EmptyState
      icon="search"
      title={t('页面不存在')}
      description={t('没有找到 {path} 对应的页面。链接可能已失效或地址输入有误。', { path: location.pathname })}
      action={
        <Link to="/" className="btn-primary">
          {t('返回首页')}
        </Link>
      }
      className="min-h-[70vh] justify-center py-16"
    />
  );
}
