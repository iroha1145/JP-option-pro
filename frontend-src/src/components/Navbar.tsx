import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Icon } from '@/components/icons';
import { LOCALES, getLocale, setLocale, t } from '@/i18n/core';
import { stocksApi } from '@/api/modules';
import type { SearchResult } from '@/api/types';
import { useAccess } from '@/hooks/useAccess';
import { cn } from '@/lib/utils';
import { popoverReduced, popoverVariants, springSoft } from '@/lib/motion';
import Segmented from '@/components/shared/Segmented';

/* 导航用短标签，不用页面全称：全称的日文译文（ブレイクアウトレーダー 等）
   在 8 项并排时必然折行（用户实拍）。页面标题仍用全称。 */
export const NAV_ITEMS: { path: string; label: string; index: string }[] = [
  { path: '/', label: '首页', index: '01' },
  { path: '/market', label: '市场', index: '02' },
  { path: '/radar', label: '雷达', index: '03' },
  { path: '/screener', label: '筛选', index: '04' },
  { path: '/watchlist', label: '自选', index: '05' },
  { path: '/earnings', label: '决算', index: '06' },
  { path: '/news', label: '新闻', index: '07' },
  { path: '/data-status', label: '数据', index: '08' },
  { path: '/short-monitor', label: '空卖', index: '09' },
  { path: '/research', label: '验证', index: '10' },
];

export default function Navbar() {
  const { isOwner, mode, logout, accountUsername } = useAccess();
  const navigate = useNavigate();
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  const [hovered, setHovered] = useState<string | null>(null);
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-overlay backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-shell items-center gap-3 px-4 md:h-14 md:gap-4 md:px-8">
        <NavLink to="/" className="flex shrink-0 items-baseline gap-2 press-spring">
          <span className="font-display text-h3 font-semibold text-ink-900">Optix</span>
          <span className="rounded-sm bg-brand-600 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wider text-white">
            Japan
          </span>
        </NavLink>
        <nav
          aria-label={t('主导航')}
          className="hidden flex-1 items-center gap-0.5 xl:flex"
          onMouseLeave={() => setHovered(null)}
        >
          {NAV_ITEMS.map((item) => {
            const active =
              item.path === '/'
                ? location.pathname === '/'
                : location.pathname === item.path || location.pathname.startsWith(`${item.path}/`);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                onMouseEnter={() => setHovered(item.path)}
                className={cn(
                  'relative isolate whitespace-nowrap rounded-md px-2.5 py-1.5 text-body-s text-ink-600 transition-colors hover:text-ink-900',
                  active && 'font-medium text-brand-700',
                )}
              >
                {active && (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-0 -z-10 rounded-md bg-brand-50"
                    transition={reduceMotion ? { duration: 0 } : springSoft}
                  />
                )}
                {!active && hovered === item.path && (
                  <motion.span
                    layoutId="nav-hover"
                    className="absolute inset-0 -z-10 rounded-md bg-ink-900/[0.04]"
                    transition={reduceMotion ? { duration: 0 } : springSoft}
                  />
                )}
                <span className="mr-1 font-mono text-micro text-ink-300">{item.index}</span>
                {t(item.label)}
              </NavLink>
            );
          })}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-2">
          <SearchBox onPick={(code) => navigate(`/stock/${code}`)} />
          {/* 手机上语言切换收进 Dock 的「更多」sheet，顶栏只留搜索与登录 */}
          <span className="hidden sm:block">
            <LanguageSwitcher />
          </span>
          {accountUsername && (
            <span
              className="hidden items-center gap-1.5 rounded-pill border border-line bg-card px-2.5 py-1 text-caption text-ink-600 sm:inline-flex"
              title={t('账号与美股版通用 · admin 为所有者')}
            >
              <Icon name="command" size={12} className="text-brand-600" />
              {accountUsername}
            </span>
          )}
          {mode === 'password' &&
            (isOwner || accountUsername ? (
              <button
                type="button"
                onClick={() => void logout()}
                className="press-spring flex items-center gap-1 rounded-md px-2 py-1.5 text-body-s text-ink-500 hover:bg-brand-50 hover:text-ink-900"
                title={t('登出')}
              >
                <Icon name="logout" size={16} />
              </button>
            ) : (
              <NavLink to="/login" className="text-body-s text-brand-700 hover:underline">
                {t('登录')}
              </NavLink>
            ))}
        </div>
      </div>
    </header>
  );
}

function LanguageSwitcher() {
  const current = getLocale();
  return (
    <Segmented
      ariaLabel={t('切换语言')}
      options={LOCALES.map((locale) => ({ value: locale.code, label: locale.short }))}
      value={current}
      onChange={(code) => setLocale(code)}
    />
  );
}

function SearchBox({ onPick }: { onPick: (code: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const variants = reduceMotion ? popoverReduced : popoverVariants;

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    if (!query.trim()) {
      setResults([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const response = await stocksApi.search(query.trim());
        setResults(response.results.slice(0, 8));
        setOpen(true);
      } catch {
        setResults([]);
      }
    }, 220);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [query]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  return (
    <div ref={boxRef} className="relative min-w-0">
      <div className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1.5 transition-[box-shadow,border-color] duration-fast ease-paper focus-within:border-brand-300 focus-within:shadow-focus-ring">
        <Icon name="search" size={14} className="text-ink-400" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder={t('搜索代码或公司名')}
          className="w-28 bg-transparent text-body-s text-ink-900 outline-none placeholder:text-ink-300 sm:w-40"
        />
      </div>
      <AnimatePresence>
        {open && results.length > 0 && (
          <motion.ul
            variants={variants}
            initial="hidden"
            animate="show"
            exit="exit"
            className="absolute right-0 top-full z-50 mt-1 w-72 origin-top-right overflow-hidden rounded-lg border border-line bg-card shadow-sh-2"
          >
            {results.map((item) => (
              <li key={item.canonical_code}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-fast hover:bg-brand-50"
                  onClick={() => {
                    setOpen(false);
                    setQuery('');
                    onPick(item.display_code);
                  }}
                >
                  <span className="font-mono text-body-s font-medium text-ink-900">{item.display_code}</span>
                  <span className="min-w-0 flex-1 truncate text-body-s text-ink-600">{item.name_ja ?? item.name_en ?? '—'}</span>
                  <span className="text-micro text-ink-400">{item.market_name ?? ''}</span>
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
