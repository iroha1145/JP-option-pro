import { t } from '@/i18n/core';

export function PageFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-ink-500">
      <span className="eyebrow tracking-widest">{t('加载中')}…</span>
    </div>
  );
}

export function InlineFallback() {
  return (
    <div className="flex h-24 items-center justify-center text-ink-400">
      <span className="text-caption">{t('加载中')}…</span>
    </div>
  );
}
