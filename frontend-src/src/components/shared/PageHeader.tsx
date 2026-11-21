import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import type { NavSection } from '@/lib/navigation';
import SectionNav from '@/components/shared/SectionNav';

interface PageHeaderProps {
  description?: string;
  title: string;        // 我的关注
  meta?: ReactNode;     // 右侧元信息
  className?: string;
  section?: NavSection;
  /** 元信息在手机上是固定宽度的内容（例如只有一个按钮）时，仍跟标题同排。 */
  inlineMeta?: boolean;
}

export default function PageHeader({ title, description, meta, className, section, inlineMeta = false }: PageHeaderProps) {
  return (
    <div className="page-heading">
      <header
        className={cn('page-heading-row', className)}
      >
        <div className="min-w-0"><h1 className="page-title">{title}</h1>{description && <p className="mt-2 max-w-prose text-body-s text-ink-500">{description}</p>}</div>
        {meta && <div className={cn('page-heading-meta', inlineMeta && 'page-heading-meta-inline')}>{meta}</div>}
      </header>
      {section && <SectionNav section={section} />}
    </div>
  );
}
