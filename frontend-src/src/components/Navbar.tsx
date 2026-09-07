/**
 * Header：Logo | 编号导航（滑行下划线） | ⌘K | 时段LED+JST时钟 | 语言/涨跌色 | 登录
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router';
import { cn, isNavPathActive } from '@/lib/utils';
import { useNow } from '@/hooks/useNow';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import { fmtJstClock } from '@/lib/format';
import { placeGlide } from '@/lib/transitions';
import { tokyoSession, tokyoSessionLabel } from '@/lib/tokyoSession';
import Icon from '@/components/icons';
import { SessionDot } from '@/components/shared/SessionLED';
import LanguageSwitcher from '@/components/LanguageSwitcher';
import ColorModeSwitcher from '@/components/ColorModeSwitcher';
import { t } from '@/i18n/core';

export const NAV_ITEMS = [
  { no: '01', label: t('首页'), path: '/' },
  { no: '02', label: t('自选'), path: '/watchlist' },
  { no: '03', label: t('筛选'), path: '/screener' },
  { no: '04', label: t('雷达'), path: '/radar' },
  { no: '05', label: t('市场'), path: '/market' },
  { no: '06', label: t('决算'), path: '/earnings' },
  { no: '07', label: t('新闻'), path: '/news' },
  { no: '08', label: t('空卖'), path: '/short-monitor' },
] as const;

function JstClock({ className }: { className?: string }) {
  const now = useNow(1000);
  return (
    <span className={cn('font-mono text-micro text-ink-500 tnum', className)} suppressHydrationWarning>
      {fmtJstClock(now)} JST
    </span>
  );
}

export default function Navbar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { isOwner, isSignedIn, username, logout } = useAccess();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const now = useNow(30_000);
  const session = tokyoSession(now);

  const navRef = useRef<HTMLElement>(null);
  const glideRef = useRef<HTMLSpanElement>(null);
  const glideReadyRef = useRef(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const activePath = NAV_ITEMS.find((item) => isNavPathActive(location.pathname, item.path))?.path ?? '';

  const alignRef = useRef<(animate: boolean) => void>(() => undefined);
  useLayoutEffect(() => {
    const nav = navRef.current;
    const bar = glideRef.current;
    if (!nav || !bar) return;
    alignRef.current = (animate: boolean) => {
      const label = nav.querySelector('[data-active="true"] [data-nav-label]') as HTMLElement | null;
      if (!label) {
        bar.style.width = '0px';
        return;
      }
      const navBox = nav.getBoundingClientRect();
      const box = label.getBoundingClientRect();
      placeGlide(bar, { offset: box.left - navBox.left, size: box.width }, { axis: 'x', animate });
    };
    let primed = false;
    const ro = new ResizeObserver(() => {
      if (!primed) {
        primed = true;
        return;
      }
      alignRef.current(false);
    });
    ro.observe(nav);
    return () => ro.disconnect();
  }, []);
  useLayoutEffect(() => {
    alignRef.current(glideReadyRef.current);
    glideReadyRef.current = true;
  }, [activePath]);

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
      toast.info(
        isOwner ? t('已退出 Owner 模式') : t('已退出登录'),
        t('当前为访客只读模式'),
      );
      navigate('/watchlist');
    } catch (error) {
      toast.error(t('退出失败'), error instanceof Error ? error.message : t('请稍后再试'));
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <header className="glass sticky top-0 z-50 border-b border-line">
      <div className="mx-auto flex h-12 max-w-shell items-center gap-3 px-4 md:h-16 md:gap-5 md:px-8">
        <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label={t('Optix Japan 首页')}>
          <img src="/logo.svg" alt="" className="size-7 md:size-8" />
          <span className="hidden flex-col leading-none sm:flex">
            <span className="font-display text-[17px] font-bold text-ink-900">Optix Japan</span>
            <span className="eyebrow mt-0.5 text-[9px]">JAPAN EQUITY DESK</span>
          </span>
        </Link>

        <nav
          ref={navRef}
          className="relative mx-auto hidden h-full items-center gap-1 xl:flex"
          aria-label={t('主导航')}
        >
          <span ref={glideRef} data-nav-glide="" aria-hidden="true" className="nav-glide" />
          {NAV_ITEMS.map((item) => {
            const active = isNavPathActive(location.pathname, item.path);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                data-active={active}
                className={cn(
                  'flex h-full items-center gap-1.5 whitespace-nowrap px-2 text-body-s transition-colors duration-fast 2xl:px-3.5',
                  active ? 'font-medium text-brand-600' : 'text-ink-500 hover:text-ink-800',
                )}
              >
                <span className="hidden font-mono text-[11px] text-ink-400 2xl:inline">{item.no}</span>
                <span data-nav-label className="relative flex h-full items-center">
                  {item.label}
                </span>
              </NavLink>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2.5 md:gap-3.5 xl:ml-0">
          <button
            onClick={onOpenPalette}
            className="hidden h-8 w-44 items-center gap-2 rounded-md border border-line bg-card-warm px-3 text-caption text-ink-400 transition-[border-color,box-shadow,color] duration-fast hover:border-line-strong hover:text-ink-500 focus-visible:border-brand-500 focus-visible:shadow-focus-ring md:flex xl:hidden 2xl:flex 2xl:w-[220px]"
            aria-label={t('打开命令面板')}
          >
            <Icon name="search" size={14} />
            <span className="flex-1 truncate text-left">{t('搜索代码或功能…')}</span>
            <kbd className="flex items-center gap-0.5 font-mono text-[10px] text-ink-400">
              <Icon name="command" size={11} />K
            </kbd>
          </button>
          <button
            onClick={onOpenPalette}
            className="flex size-9 items-center justify-center rounded-md border border-line bg-card-warm text-ink-500 shadow-btn md:hidden xl:flex 2xl:hidden"
            aria-label={t('搜索')}
          >
            <Icon name="search" size={16} />
          </button>

          <span className="hidden items-center gap-2 md:flex" aria-label={t('市场时段：{label}', { label: t(tokyoSessionLabel(session)) })}>
            <SessionDot session={session} />
            <JstClock />
          </span>

          <LanguageSwitcher className="hidden md:block" />
          <ColorModeSwitcher className="hidden xl:flex" />

          {isSignedIn ? (
            <button
              onClick={handleLogout}
              disabled={loggingOut}
              className="flex h-8 max-w-[140px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-card px-3 text-caption text-ink-500 shadow-btn transition-colors hover:text-ink-800 disabled:cursor-wait disabled:opacity-60 md:max-w-none"
            >
              <Icon name="logout" size={14} className="shrink-0" />
              <span className="truncate">{username ? t('退出 {name}', { name: username }) : t('退出')}</span>
            </button>
          ) : (
            <Link
              to="/login"
              className="flex h-8 shrink-0 items-center whitespace-nowrap rounded-md bg-brand-600 px-3.5 text-caption font-medium text-white shadow-btn-hi transition-[transform,background-color] duration-fast hover:bg-brand-700 active:scale-[0.98]"
            >
              {t('登录')}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
