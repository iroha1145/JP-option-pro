/**
 * 移动端底部 Dock：四入口 + 「更多」sheet。
 */
import { useEffect, useId, useState, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { cn, isNavPathActive } from '@/lib/utils';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useBodyScrollLock } from '@/hooks/useBodyScrollLock';
import { overlayVisible, useOverlayPhase } from '@/lib/transitions';
import { isTopFocusScope } from '@/lib/focusScope';
import Icon, { type IconName } from '@/components/icons';
import Segmented from '@/components/shared/Segmented';
import GlidePill from '@/components/shared/GlidePill';
import { LOCALES, getLocale, setLocale, t } from '@/i18n/core';
import { setColorMode, type ColorMode } from '@/lib/colorPreference';
import { useColorMode } from '@/hooks/useColorMode';

const DOCK_ITEMS: { label: string; path: string; icon: IconName }[] = [
  { label: t('首页'), path: '/', icon: 'candle' },
  { label: t('自选'), path: '/watchlist', icon: 'star-line' },
  { label: t('筛选'), path: '/screener', icon: 'filter-funnel' },
  { label: t('雷达'), path: '/radar', icon: 'radar' },
];

const MORE_ITEMS: { label: string; path: string; icon: IconName; desc: string }[] = [
  { label: t('市场'), path: '/market', icon: 'layers', desc: t('指数 · 业种 · 广度') },
  { label: t('决算日历'), path: '/earnings', icon: 'calendar-spark', desc: t('確定 · 目安三态日历') },
  { label: t('新闻'), path: '/news', icon: 'doc-quote', desc: t('催化剂 · 三源新闻流') },
  { label: t('机构空卖行为监控'), path: '/short-monitor', icon: 'radar', desc: t('公开空头变化 · 价格反应') },
  { label: t('数据状态'), path: '/data-status', icon: 'wallet-gauge', desc: t('同步进度 · 数据覆盖') },
  { label: t('历史验证'), path: '/research', icon: 'crosshair', desc: t('走步验证 · 分层收益') },
];

export default function MobileDock() {
  const { pathname } = useLocation();
  return <MobileDockContent key={pathname} />;
}

function MobileDockContent() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isOwner, isSignedIn, username, logout } = useAccess();
  const toast = useToast();
  const [loggingOut, setLoggingOut] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  useFocusTrap(sheetRef, moreOpen);
  const overlayId = useId();
  const morePhase = useOverlayPhase(moreOpen, 150);
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

  const colorMode = useColorMode();
  const moreActive = MORE_ITEMS.some((m) => isNavPathActive(location.pathname, m.path));
  const dockGlideId = useId();

  const renderItem = (item: (typeof DOCK_ITEMS)[number]) => {
    const active = isNavPathActive(location.pathname, item.path);
    return (
      <div key={item.path} className="relative flex flex-1">
        {active && (
          <GlidePill layoutId={dockGlideId} className="inset-1 rounded-md bg-brand-50 shadow-none" />
        )}
        <Link
          to={item.path}
          className="relative z-10 flex min-h-[44px] flex-1 flex-col items-center justify-center gap-1 transition-transform duration-fast active:scale-[0.96]"
          aria-label={item.label}
          aria-current={active ? 'page' : undefined}
        >
          <Icon name={item.icon} size={19} className={active ? 'text-brand-600' : 'text-ink-400'} />
          <span className={cn('text-[10px] leading-none', active ? 'font-medium text-brand-600' : 'text-ink-400')}>{item.label}</span>
        </Link>
      </div>
    );
  };

  return (
    <>
      <nav
        className="glass fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+0.75rem)] z-[60] mx-auto flex h-16 max-w-md items-stretch rounded-lg border border-line px-1.5 shadow-dock xl:hidden"
        aria-label={t('移动端导航')}
      >
        <motion.div layoutRoot className="flex h-full w-full items-stretch">
          {DOCK_ITEMS.map(renderItem)}
          <div className="relative flex flex-1">
            {moreActive && (
              <GlidePill layoutId={dockGlideId} className="inset-1 rounded-md bg-brand-50 shadow-none" />
            )}
            <button
              onClick={() => setMoreOpen(true)}
              className="relative z-10 flex min-h-[44px] w-full flex-col items-center justify-center gap-1 transition-transform duration-fast active:scale-[0.96]"
              aria-label={t('更多')}
              aria-current={moreActive ? 'page' : undefined}
            >
              <Icon name="menu" size={19} className={moreActive ? 'text-brand-600' : 'text-ink-400'} />
              <span className={cn('text-[10px] leading-none', moreActive ? 'font-medium text-brand-600' : 'text-ink-400')}>{t('更多')}</span>
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
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-[64] bg-[rgba(13,22,38,.32)] xl:hidden"
              onClick={() => setMoreOpen(false)}
              data-focus-backdrop={overlayId}
              aria-hidden="true"
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%', transition: { duration: 0.15, ease: [0.16, 1, 0.3, 1] } }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              ref={sheetRef}
              className="fixed inset-x-0 bottom-0 z-[65] max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain rounded-t-xl border-t border-line bg-card pb-[calc(env(safe-area-inset-bottom)+16px)] shadow-sh-3 xl:hidden"
              role="dialog"
              aria-modal="true"
              data-focus-overlay={overlayId}
              aria-label={t('更多功能')}
            >
              <div className="flex justify-center pb-1 pt-2 text-ink-300">
                <Icon name="dots-grid" size={18} />
              </div>
              <p className="eyebrow px-5 pb-2 pt-1">{t('更多功能')}</p>
              <div className="px-3">
                <div className="flex items-center justify-between gap-3 rounded-md px-3 py-3">
                  <span className="flex items-center gap-3">
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                      <Icon name="languages" size={17} />
                    </span>
                    <span className="text-body-s font-medium text-ink-800">{t('界面语言')}</span>
                  </span>
                  <Segmented
                    options={LOCALES.map((l) => ({ value: l.code, label: l.short }))}
                    value={getLocale()}
                    onChange={(code) => setLocale(code)}
                  />
                </div>
                <div className="flex items-center justify-between gap-3 rounded-md px-3 py-3">
                  <span className="flex items-center gap-3">
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                      <Icon name="candle" size={17} />
                    </span>
                    <span className="text-body-s font-medium text-ink-800">{t('涨跌色彩')}</span>
                  </span>
                  <Segmented<ColorMode>
                    options={[
                      { value: 'western', label: t('绿涨红跌') },
                      { value: 'asian', label: t('红涨绿跌') },
                    ]}
                    value={colorMode}
                    onChange={setColorMode}
                  />
                </div>
                <div className="mx-3 my-2 border-t border-line" />
                {MORE_ITEMS.map((m) => (
                  <button
                    key={m.path}
                    onClick={() => {
                      setMoreOpen(false);
                      navigate(m.path);
                    }}
                    aria-current={isNavPathActive(location.pathname, m.path) ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-[transform,background-color] hover:bg-paper-2 active:bg-line/60',
                      isNavPathActive(location.pathname, m.path) && 'bg-brand-50',
                    )}
                  >
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-brand-600">
                      <Icon name={m.icon} size={17} />
                    </span>
                    <span className="flex-1">
                      <span className="block text-body-s font-medium text-ink-800">{m.label}</span>
                      <span className="block text-micro text-ink-400">{m.desc}</span>
                    </span>
                    {isNavPathActive(location.pathname, m.path) ? (
                      <span className="size-1.5 shrink-0 rounded-full bg-brand-600" aria-hidden="true" />
                    ) : (
                      <Icon name="chevron-right" size={14} className="text-ink-300" />
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
                      navigate('/login');
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
                  className="flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-[transform,background-color] hover:bg-paper-2 active:bg-line/60 disabled:cursor-wait disabled:opacity-60"
                >
                  <span className={cn('flex size-9 items-center justify-center rounded-md border border-line', isOwner ? 'bg-up-50 text-up-700' : 'bg-card-warm text-ink-400')}>
                    <Icon name={isSignedIn ? 'logout' : 'shield'} size={17} />
                  </span>
                  <span className="flex-1">
                    <span className="block text-body-s font-medium text-ink-800">
                      {isOwner ? t('Owner 已登录') : isSignedIn ? t('已登录 {name}', { name: username ?? '' }) : t('访客只读模式')}
                    </span>
                    <span className="block text-micro text-ink-400">
                      {isOwner || isSignedIn
                        ? (loggingOut ? t('正在退出…') : t('退出登录'))
                        : t('登录后可保存自选')}
                    </span>
                  </span>
                </button>
                {isSignedIn && (
                  <button
                    type="button"
                    onClick={() => {
                      setMoreOpen(false);
                      navigate('/login');
                    }}
                    className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-micro text-ink-500 transition-[background-color] hover:bg-paper-2 active:bg-line/60"
                  >
                    <span className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-ink-400">
                      <Icon name="shield" size={17} />
                    </span>
                    {t('退出并换账号')}
                  </button>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
