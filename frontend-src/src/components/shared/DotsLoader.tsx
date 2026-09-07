import { cn } from '@/lib/utils';

/** Paper 三圆点加载器：路由/面板/目录检索用，不替代按钮 busy 白圈。 */
export default function DotsLoader({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      className={cn('dots-loader', className)}
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <i />
      <i />
      <i />
    </span>
  );
}
