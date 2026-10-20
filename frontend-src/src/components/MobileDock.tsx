/**
 * 移动端底部 Dock：四入口 + 「更多」sheet。
 */
import { useEffect, useId, useState, useRef, type CSSProperties } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { DUR_FAST, DUR_UI, EASE_PAPER } from '@/lib/motion';
import { useFeelSheetDrag } from '@/lib/feel';
import { cn, isNavPathActive } from '@/lib/utils';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock';
import { overlayVisible, useOverlayPhase } from '@/lib/transitions';
import { isTopFocusScope } from '@/lib/focusScope';
import Icon, { type IconName } from '@/components/icons';
import GlidePill from '@/components/shared/GlidePill';
import { t } from '@/i18n/core';
import { NAV_GROUPS, isNavGroupActive, navAriaCurrent } from '@/lib/navigation';
import { useGlideLayoutId } from '@/hooks/useGlideLayoutId';

const DOCK_ITEMS: { label: string; path: string; icon: IconName }[] = [
  { label: t('首页'), path: '/', icon: 'candle' },
  { label: t('关注'), path: '/watchlist', icon: 'star-line' },
  { label: t('选股'), path: '/screener', icon: 'filter-funnel' },
  { label: t('市场'), path: '/market', icon: 'layers' },
];

const MORE_ITEMS: { label: string; path: string; icon: IconName; desc: string }[] = [
  { label: t('财报日历'), path: '/earnings', icon: 'calendar-spark', desc: t('日期 · 业绩 · 公司公告') },
  { label: t('新闻'), path: '/news', icon: 'doc-quote', desc: t('原文 · 来源') },
  { label: t('数据状态'), path: '/data-status', icon: 'wallet-gauge', desc: t('同步进度 · 数据覆盖') },
  { label: t('历史验证'), path: '/research', icon: 'crosshair', desc: t('走步验证 · 分层收益') },
];

type MobileDockProps = { onHeightChange?: (height: number) => void };

export default function MobileDock({ onHeightChange }: MobileDockProps) {
  const { pathname } = useLocation();
  return <MobileDockContent key={pathname} onHeightChange={onHeightChange} />;
}

function MobileDockContent({ onHeightChange }: MobileDockProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { isOwner, isSignedIn, username, logout } = useAccess();
  const toast = useToast();
  const [loggingOut, setLoggingOut] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const dockRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const dock = dockRef.current;
    if (!dock || !onHeightChange) return;
    const measure = () => onHeightChange(dock.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(dock);
    return () => observer.disconnect();
  }, [onHeightChange]);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const sheetDrag = useFeelSheetDrag({ enabled: moreOpen, panelRef: sheetRef, onClose: () => setMoreOpen(false) });
  useFocusTrap(sheetRef, moreOpen);
  const overlayId = useId();
  const morePhase = useOverlayPhase(moreOpen, DUR_FAST * 1000);
  useBodyScrollLock(overlayVisible(moreOpen, morePhase));

  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing || e.keyCode === 229 || !isTopFocusScope(sheetRef.current)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setMoreOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [moreOpen]);

  const moreActive = MORE_ITEMS.some((m) => isNavPathActive(location.pathname, m.path));
  const dockGlideId = useGlideLayoutId('dock');

  const renderItem = (item: (typeof DOCK_ITEMS)[number]) => {
    const group = NAV_GROUPS.find(group => group.path === item.path)!;
    const active = isNavGroupActive(location.pathname, group);
    return (
      <div key={item.path} className="relative flex min-w-0 flex-1 basis-0">
        {active && (
          <GlidePill dependency={location.pathname} layoutId={dockGlideId} className="inset-1 rounded-md bg-brand-50 shadow-none" />
        )}
        <Link
          to={item.path}
          className="icon-motion-trigger relative z-10 flex min-h-[44px] min-w-0 flex-1 flex-col items-center justify-center gap-1 py-2 transition-transform duration-fast active:scale-[0.96]"
          aria-label={item.label}
          aria-current={navAriaCurrent(location.pathname, group)}
        >
          <Icon motion name={item.icon} motionActive={active} size={19} className={active ? 'text-brand-600' : 'text-ink-400'} />
          <span className={cn('w-full text-center text-tag leading-tight [overflow-wrap:anywhere]', active ? 'font-medium text-brand-600' : 'text-ink-400')}>{item.label}</span>
        </Link>
      </div>
    );
  };

  return (
    <>
      <nav
        ref={dockRef}
        className="glass mobile-nav-glass fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+0.75rem)] z-[60] mx-auto flex min-h-16 max-w-md items-stretch rounded-lg border border-line px-1.5 shadow-dock xl:hidden"
        aria-label={t('移动端导航')}
      >
        <motion.div layoutRoot className="flex min-w-0 w-full items-stretch">
          {DOCK_ITEMS.map(renderItem)}
          <div className="relative flex min-w-0 flex-1 basis-0">
            {moreActive && (
              <GlidePill dependency={location.pathname} layoutId={dockGlideId} className="inset-1 rounded-md bg-brand-50 shadow-none" />
            )}
            <button
              onClick={() => setMoreOpen(true)}
              className="icon-motion-trigger relative z-10 flex min-h-[44px] w-full flex-col items-center justify-center gap-1 py-2 transition-transform duration-fast active:scale-[0.96]"
              aria-label={t('更多')}
              aria-current={moreActive ? 'page' : undefined}
            >
              <Icon motion name="menu" motionActive={moreOpen} size={19} className={moreActive ? 'text-brand-600' : 'text-ink-400'} />
              <span className={cn('w-full text-center text-tag leading-tight [overflow-wrap:anywhere]', moreActive ? 'font-medium text-brand-600' : 'text-ink-400')}>{t('更多')}</span>
            </button>
          </div>
        </motion.div>
      </nav>

      <AnimatePresence>
        {moreOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: DUR_FAST }}
              className="fixed inset-0 z-[64] bg-[var(--scrim)] xl:hidden"
              onClick={() => setMoreOpen(false)}
              data-focus-backdrop={overlayId}
              aria-hidden="true"
            />
          </>
        )}
      </AnimatePresence>
      {overlayVisible(moreOpen, morePhase) && (
        <div
          data-open={morePhase === 'open' ? 'true' : 'false'}
          style={{
            '--sheet-open-duration': `${DUR_UI * 1000}ms`,
            '--sheet-close-duration': `${DUR_FAST * 1000}ms`,
            '--sheet-easing': `cubic-bezier(${EASE_PAPER.join(',')})`,
          } as CSSProperties}
          data-feel-sheet
          ref={sheetRef}
          className="t-more-sheet fixed inset-x-0 bottom-0 z-[65] max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain rounded-t-xl border-t border-line bg-card pb-[calc(env(safe-area-inset-bottom)+16px)] shadow-sh-3 xl:hidden"
          role="dialog"
          aria-modal="true"
          data-focus-overlay={overlayId}
          aria-label={t('更多功能')}
        >
          <div
            data-handle
            onPointerDown={sheetDrag.onPointerDown}
            onPointerMove={sheetDrag.onPointerMove}
            onPointerUp={sheetDrag.onPointerUp}
            onPointerCancel={sheetDrag.onPointerCancel}
            onLostPointerCapture={sheetDrag.onLostPointerCapture}
            className="icon-motion-trigger flex justify-center pb-1 pt-2 text-ink-300">
            <Icon motion name="dots-grid" size={18} />
          </div>
          <p className="eyebrow px-5 pb-2 pt-1">{t('更多功能')}</p>
          <div className="px-3">
            {MORE_ITEMS.map((m) => (
              <button
                key={m.path}
                onClick={() => {
                  setMoreOpen(false);
                  navigate(m.path);
                }}
                aria-current={isNavPathActive(location.pathname, m.path) ? 'page' : undefined}
                className={cn(
                  'icon-motion-trigger flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-[transform,background-color] hover:bg-paper-2 active:bg-line/60',
                  isNavPathActive(location.pathname, m.path) && 'bg-brand-50',
                )}
              >
                <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                  <Icon motion name={m.icon} size={17} />
                </span>
                <span className="flex-1">
                  <span className="block text-body-s font-medium text-ink-800">{m.label}</span>
                  <span className="block text-micro text-ink-400">{m.desc}</span>
                </span>
                {isNavPathActive(location.pathname, m.path) ? (
                  <span className="size-1.5 shrink-0 rounded-full bg-brand-600" aria-hidden="true" />
                ) : (
                  <Icon motion name="chevron-right" size={14} className="text-ink-300" />
                )}
              </button>
            ))}
            <div className="mx-3 my-2 border-t border-line" />
            <button
              type="button"
              disabled={loggingOut}
              onClick={() => {
                if (!isSignedIn) {
                  setMoreOpen(false);
                  navigate('/login', { state: { from: location.pathname + location.search } });
                  return;
                }
                setLoggingOut(true);
                void logout()
                  .then(() => setMoreOpen(false))
                  .catch((error: unknown) => {
                    toast.error(t('退出失败'), error instanceof Error ? error.message : undefined);
                  })
                  .finally(() => setLoggingOut(false));
              }}
              className="icon-motion-trigger flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-[transform,background-color] hover:bg-paper-2 active:bg-line/60 disabled:cursor-wait disabled:opacity-60"
            >
              <span className={cn('flex size-9 items-center justify-center rounded-md border border-line', isOwner ? 'bg-up-50 text-up-700' : 'bg-card-warm text-ink-400')}>
                <Icon motion name={isSignedIn ? 'logout' : 'shield'} size={17} />
              </span>
              <span className="flex-1">
                <span className="block text-body-s font-medium text-ink-800">
                  {isOwner ? t('管理员 已登录') : isSignedIn ? t('已登录 {name}', { name: username ?? '' }) : t('访客只读模式')}
                </span>
                <span className="block text-micro text-ink-400">
                  {isOwner || isSignedIn
                    ? (loggingOut ? t('正在退出…') : t('退出登录'))
                    : t('登录后可保存关注')}
                </span>
              </span>
            </button>
            {isSignedIn && (
              <button
                type="button"
                onClick={() => {
                  setMoreOpen(false);
                  navigate('/login', { state: { from: location.pathname + location.search } });
                }}
                className="icon-motion-trigger flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-micro text-ink-500 transition-[background-color] hover:bg-paper-2 active:bg-line/60"
              >
                <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-ink-400">
                  <Icon motion name="shield" size={17} />
                </span>
                {t('退出并换账号')}
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
