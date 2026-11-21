/**
 * Layout：sticky Header + IndexTape + 内容槽 + Footer + Dock + ⌘K。
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Outlet, useLocation, useNavigate, useNavigationType } from 'react-router';
import Navbar from '@/components/Navbar';
import IndexTape from '@/components/IndexTape';
import Footer from '@/components/Footer';
import RouteErrorBoundary from '@/components/shared/RouteErrorBoundary';
import PageFallback from '@/components/shared/PageFallback';
import MobileDock from '@/components/MobileDock';
const CommandPalette = lazy(() => import('@/components/CommandPalette'));
import { pushRecent } from '@/lib/recentTickers';
import { ShellContext } from '@/hooks/useShell';
import { t } from '@/i18n/core';
import { useAccess } from '@/hooks/useAccess';

export default function Layout() {
  const location = useLocation();
  const { loading, isOwner, principalKey } = useAccess();
  const pageKey = `${location.pathname}:${principalKey}:${isOwner}`;
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const previousPathname = useRef(location.pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteMounted, setPaletteMounted] = useState(false);
  if (paletteOpen && !paletteMounted) setPaletteMounted(true);
  const [dockHeight, setDockHeight] = useState(64);

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
      // The first chunk may still be pending, so its own key handler does not exist yet.
      if (e.key === 'Escape') { setPaletteOpen(false); return; }
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
      <div className="app-shell overflow-x-clip" style={{ '--mobile-dock-height': `${dockHeight}px` } as CSSProperties}>
        <a className="skip-link" href="#main-content">{t('跳到主要内容')}</a>
        <Navbar onOpenPalette={openPalette} />
        <IndexTape />
        <main id="main-content" tabIndex={-1} className="app-main">
          <div key={pageKey}>
            <RouteErrorBoundary>
              <Suspense fallback={<PageFallback />}>
                {loading ? <PageFallback /> : <Outlet />}
              </Suspense>
            </RouteErrorBoundary>
          </div>
        </main>
        <Footer />
        <MobileDock onHeightChange={setDockHeight} />
      </div>

      {paletteMounted && <Suspense fallback={null}><CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onOpenTicker={openTicker}
        onForceRefresh={() => navigate('/watchlist?force=1')}
      /></Suspense>}
    </ShellContext.Provider>
  );
}
