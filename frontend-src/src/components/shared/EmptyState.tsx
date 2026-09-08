/** EmptyState：手绘插画 + H3 + 说明 + 主按钮；503 变体附一行「稍后刷新再试」 */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import Icon from '@/components/icons';
import { t } from '../../i18n/core.ts';

interface EmptyStateProps {
  image?: string;          // public/ 手绘 SVG 路径
  icon?: 'doc-quote' | 'search';
  title: string;
  description?: string;
  action?: ReactNode;      // 主按钮
  footnote?: string;       // 访客提示等 Caption
  variant?: 'empty' | 'error';
  /** 侧栏/内嵌卡用 compact，避免 220px 插画撑破纸面。 */
  size?: 'default' | 'compact';
  className?: string;
}

export default function EmptyState({
  image,
  icon,
  title,
  description,
  action,
  footnote,
  variant = 'empty',
  size = 'default',
  className,
}: EmptyStateProps) {
  const compact = size === 'compact';
  return (
    <div className={cn('flex flex-col items-center text-center', compact ? 'px-2 py-4' : 'px-6 py-12', className)}>
      {image ? (
        <img
          src={image}
          alt=""
          width={compact ? 96 : 220}
          height={compact ? 72 : 165}
          className={cn('h-auto max-w-full opacity-95', compact ? 'mb-2 w-[96px]' : 'mb-5 w-[220px]')}
          loading="lazy"
        />
      ) : (
        <span
          className={cn(
            'flex items-center justify-center rounded-lg border border-line bg-card-warm text-ink-400',
            compact ? 'mb-2 size-10' : 'mb-4 size-14',
          )}
        >
          <Icon name={icon ?? 'doc-quote'} size={compact ? 18 : 26} />
        </span>
      )}
      <h3 className={cn(compact ? 'text-caption font-medium text-ink-600' : 'text-h3 text-ink-800')}>{title}</h3>
      {description && (
        <p className={cn(compact ? 'mt-1 max-w-[240px] text-micro text-ink-400' : 'mt-1.5 max-w-[340px] text-body-s text-ink-500')}>
          {description}
        </p>
      )}
      {variant === 'error' && (
        <p className="mt-1 text-micro text-ink-400">{t('稍后刷新再试')}</p>
      )}
      {action && <div className={cn(compact ? 'mt-3' : 'mt-5')}>{action}</div>}
      {footnote && <p className="mt-3 text-caption text-ink-400">{footnote}</p>}
    </div>
  );
}
