import { Link } from 'react-router';
import SourceNote from '@/components/shared/SourceNote';
import { t } from '@/i18n/core';

export default function Footer() {
  return (
    <footer className="mx-auto mt-16 w-full max-w-shell px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] md:px-8 xl:pb-10">
      <div className="flex flex-col items-start gap-3 min-[360px]:flex-row min-[360px]:flex-wrap min-[360px]:items-center min-[360px]:justify-between">
        <SourceNote
          className="w-full min-[360px]:w-auto min-[360px]:min-w-0 min-[360px]:flex-1"
          text={t('日线数据于收盘后更新，盘中为延迟行情')}
        />
        <nav aria-label={t('研究工具')} className="flex flex-wrap items-center gap-x-5 gap-y-2 text-caption text-ink-500">
          <Link to="/data-status" className="py-2 hover:text-brand-600">{t('数据状态')}</Link>
          <span>Optix Japan</span>
        </nav>
      </div>
    </footer>
  );
}
