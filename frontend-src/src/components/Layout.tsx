import { Outlet, useLocation } from 'react-router';
import Navbar from '@/components/Navbar';
import MobileDock from '@/components/MobileDock';
import { t } from '@/i18n/core';

export default function Layout() {
  const location = useLocation();
  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <Navbar />
      {/* pb 要一直留到 xl：悬浮 Dock 在 <xl 全程可见（高 64 + 离屏 12 + 呼吸空间） */}
      <main
        key={location.pathname}
        className="page-enter mx-auto w-full max-w-shell flex-1 px-4 pb-32 pt-5 md:px-8 md:pt-6 xl:pb-12"
      >
        <Outlet />
      </main>
      <footer className="hidden border-t border-line bg-paper-2 py-4 md:block">
        <div className="mx-auto flex max-w-shell items-center justify-between px-8 text-caption text-ink-400">
          <span>Optix Japan · J-Quants API V2 (Standard)</span>
          <span>{t('本页为日线数据，收盘后更新')}</span>
        </div>
      </footer>
      <MobileDock />
    </div>
  );
}
