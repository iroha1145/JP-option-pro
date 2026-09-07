/**
 * Layout：sticky Header + IndexTape + 内容槽 + Footer + Dock + ⌘K。
 */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate, useNavigationType } from 'react-router';
import Navbar from '@/components/Navbar';
import IndexTape from '@/components/IndexTape';
import Footer from '@/components/Footer';
import RouteErrorBoundary from '@/components/shared/RouteErrorBoundary';
import PageFallback from '@/components/shared/PageFallback';
import MobileDock from '@/components/MobileDock';
import CommandPalette from '@/components/CommandPalette';
import { pushRecent } from '@/lib/recentTickers';
import { ShellContext } from '@/hooks/useShell';
import { t } from '@/i18n/core';

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const previousPathname = useRef(location.pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const openTicker = useCallback((code: string) => {
    pushRecent(code);
    navigate(`/stock/${encodeURIComponent(code)}`);
  }, [navigate]);

  useEffect(() => {
    const pageChanged = previousPathname.current !== location.pathname;
    previousPathname.current = location.pathname;
    if (!pageChanged || navigationType === 'POP') return;
    window.scrollTo({ top: 0, behavior: 'instant' });
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [location.pathname, navigationType]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.keyCode === 229 || e.altKey || e.shiftKey) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (!e.repeat) setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const value = useMemo(() => ({ openPalette, openTicker }), [openPalette, openTicker]);

  return (
    <ShellContext.Provider value={value}>
      {/* overflow-x-clip：绝对定位的解释浮层即使处于 opacity-0 也占布局盒，
          窄屏时会把文档撑出横向滚动条。clip 只裁剪绘制，不建立滚动容器；
          InfoHint / PointerTooltip 的可见浮层是 position:fixed，不会被这里裁到。 */}
      <div className="flex min-h-[100dvh] flex-col overflow-x-clip">
        <a className="skip-link" href="#main-content">{t('跳到主要内容')}</a>
        <Navbar onOpenPalette={openPalette} />
        <IndexTape />
        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-shell flex-1 scroll-mt-24 px-4 pt-6 md:px-8 md:pt-8">
          <div key={location.pathname} className="page-enter">
            <RouteErrorBoundary>
              <Suspense fallback={<PageFallback />}>
                <Outlet />
              </Suspense>
            </RouteErrorBoundary>
          </div>
        </main>
        <Footer />
        <MobileDock />
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onOpenTicker={openTicker}
        onForceRefresh={() => navigate('/watchlist?force=1')}
      />
    </ShellContext.Provider>
  );
}
