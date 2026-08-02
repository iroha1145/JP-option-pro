import { Link } from 'react-router';
import { t } from '@/i18n/core';

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3">
      <span className="font-mono text-display-xl text-ink-300">404</span>
      <Link to="/" className="text-body text-brand-700 hover:underline">
        {t('首页')}
      </Link>
    </div>
  );
}
