import { t } from '@/i18n/core';

export function PageFallback() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-ink-500">
      <span className="dots-loader" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="eyebrow tracking-widest">{t('加载中')}</span>
    </div>
  );
}

export function InlineFallback() {
  return (
    <div className="flex h-24 items-center justify-center gap-2 text-ink-400">
      <span className="dots-loader" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="text-caption">{t('加载中')}</span>
    </div>
  );
}
