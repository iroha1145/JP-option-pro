/** SourceNote：卡片底部的一行说明；面向普通读者，不写实现细节。 */
import { cn } from '@/lib/utils';
import { t } from '../../i18n/core.ts';

export default function SourceNote({ className, text = t('日线数据于收盘后更新') }: { className?: string; text?: string }) {
  return (
    <p className={cn('flex items-center gap-1.5 border-t border-line pt-3 text-micro text-ink-400', className)}>
      <span>{text}</span>
    </p>
  );
}
