import { Link, useLocation } from 'react-router';
import Icon from '@/components/icons';
import { t } from '@/i18n/core';

export default function NotFound() {
  const location = useLocation();
  return (
    <section className="grid min-h-[65svh] place-items-center">
      <div className="paper-panel grid w-full max-w-xl justify-items-center gap-5 px-6 py-12 text-center sm:p-12">
        <Icon name="search" size={32} className="text-brand-600" />
        <span className="text-data-xxl text-ink-300" aria-hidden="true">404</span>
        <h1 className="page-title">{t('页面不存在')}</h1>
        <p className="max-w-prose break-words text-body-s text-ink-500 [overflow-wrap:anywhere]">
          {t('没有找到 {path} 对应的页面。链接可能已失效或地址输入有误。', { path: location.pathname })}
        </p>
        <Link to="/" className="btn-primary">{t('返回首页')}</Link>
      </div>
    </section>
  );
}
