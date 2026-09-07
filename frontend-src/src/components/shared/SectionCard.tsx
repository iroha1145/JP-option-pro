import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import { t } from '@/i18n/core';

export default function SectionCard({
  title,
  to,
  children,
  className,
}: {
  title: string;
  to: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('card-surface', className)} aria-label={title}>
      <div className="flex items-center justify-between gap-3 px-4 pb-1 pt-4 md:px-5 md:pt-5">
        <h3 className="text-h3 text-ink-900">{title}</h3>
        <Link
          to={to}
          className="link-learn shrink-0 text-caption font-medium text-brand-700 transition-colors duration-fast hover:text-brand-600"
        >
          {t('查看全部')}
          <span className="link-learn-chevron" aria-hidden="true">
            <Icon name="chevron-right" size={12} />
          </span>
        </Link>
      </div>
      {children}
    </section>
  );
}
