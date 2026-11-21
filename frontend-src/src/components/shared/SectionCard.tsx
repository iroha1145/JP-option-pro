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
    <section className={cn('paper-panel flex min-w-0 flex-col', className)} aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-2 pt-5 sm:px-6 sm:pt-6">
        <h2 className="section-heading">{title}</h2>
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
