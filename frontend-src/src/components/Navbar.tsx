/**
 * Header：Logo | 编号导航（滑行下划线） | ⌘K | 时段LED+JST时钟 | 语言/涨跌色 | 登录
 */
import { useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { cn } from '@/lib/utils';
import { useNow } from '@/hooks/useNow';
import { useAccess } from '@/hooks/useAccess';
import { useToast } from '@/hooks/useToast';
import { fmtJstClock } from '@/lib/format';
import { placeGlide } from '@/lib/transitions';
import { tokyoSession, tokyoSessionLabel } from '@/lib/tokyoSession';
import Icon from '@/components/icons';
import { SessionDot } from '@/components/shared/SessionLED';
import SettingsMenu from '@/components/SettingsMenu';
import { NAV_GROUPS, isNavGroupActive, navAriaCurrent } from '@/lib/navigation';
import { t } from '@/i18n/core';

function JstClock({ className }: { className?: string }) {
  const now = useNow(1000);
  return (
    <span className={cn('text-micro text-ink-500 tnum', className)} suppressHydrationWarning>
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
  const activePath = NAV_GROUPS.find((item) => isNavGroupActive(location.pathname, item))?.path ?? '';

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
        isOwner ? t('已退出 管理员 模式') : t('已退出登录'),
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
          <img src="/logo.svg" alt="" className="size-7 dark:brightness-150 md:size-8" />
          <span className="hidden flex-col leading-none sm:flex">
            <span className="font-display text-[17px] font-medium text-ink-900">Optix Japan</span>
          </span>
        </Link>

        <nav
          ref={navRef}
          className="relative mx-auto hidden h-full items-center gap-1 xl:flex"
          aria-label={t('主导航')}
        >
          <span ref={glideRef} data-nav-glide="" aria-hidden="true" className="nav-glide" />
          {NAV_GROUPS.map((item) => {
            const active = isNavGroupActive(location.pathname, item);
            return (
              <Link
                key={item.path}
                to={item.path}
                aria-current={navAriaCurrent(location.pathname, item)}
                data-active={active}
                className={cn(
                  'flex h-full items-center gap-1.5 whitespace-nowrap px-2 text-body-s transition-colors duration-fast min-[1680px]:px-3.5',
                  active ? 'font-medium text-brand-600' : 'text-ink-500 hover:text-ink-800',
                )}
              >
                <span data-nav-label className="relative flex h-full items-center">
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 md:gap-3 xl:ml-0">
          <button
            onClick={onOpenPalette}
            className="hidden h-8 w-44 items-center gap-2 rounded-pill border border-line bg-card-warm px-3 text-caption text-ink-400 transition-[border-color,box-shadow,color] duration-fast hover:border-line-strong hover:text-ink-500 focus-visible:border-brand-500 focus-visible:shadow-focus-ring md:flex xl:hidden min-[1680px]:flex min-[1680px]:w-[220px]"
            aria-label={t('打开命令面板')}
          >
            <Icon name="search" size={14} />
            <span className="flex-1 truncate text-left">{t('搜索代码或功能…')}</span>
            <kbd className="flex items-center gap-0.5 tnum text-[10px] text-ink-400">
              <Icon name="command" size={11} />K
            </kbd>
          </button>
          <button
            onClick={onOpenPalette}
            className="flex size-11 items-center justify-center rounded-pill border border-line bg-card-warm text-ink-500 shadow-btn md:hidden xl:flex min-[1680px]:hidden"
            aria-label={t('搜索')}
          >
            <Icon name="search" size={16} />
          </button>

          <span className="hidden items-center gap-2 md:flex" aria-label={t('市场时段：{label}', { label: t(tokyoSessionLabel(session)) })}>
            <SessionDot session={session} />
            <JstClock />
          </span>

          <SettingsMenu />

          {isSignedIn ? (
            <button
              onClick={handleLogout}
              disabled={loggingOut}
              className="flex h-10 max-w-[140px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-pill border border-line bg-card px-3 text-caption text-ink-500 shadow-btn transition-colors hover:text-ink-800 disabled:cursor-wait disabled:opacity-60 md:max-w-none"
            >
              <Icon name="logout" size={14} className="shrink-0" />
              <span className="truncate">{username ? t('退出 {name}', { name: username }) : t('退出')}</span>
            </button>
          ) : (
            <Link
              to="/login"
              state={{ from: location.pathname + location.search }}
              className="flex h-10 shrink-0 items-center whitespace-nowrap rounded-pill bg-action px-3.5 text-caption font-medium text-on-action transition-[transform,background-color] duration-fast hover:bg-action-hover active:scale-[0.98]"
            >
              {t('登录')}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
