import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router';
import { Icon } from '@/components/icons';
import { LOCALES, getLocale, setLocale, t } from '@/i18n/core';
import { stocksApi } from '@/api/modules';
import type { SearchResult } from '@/api/types';
import { useAccess } from '@/hooks/useAccess';
import { cn } from '@/lib/utils';

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
];

export default function Navbar() {
  const { isOwner, mode, logout, accountUsername } = useAccess();
  const navigate = useNavigate();
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-overlay backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-shell items-center gap-3 px-4 md:h-14 md:gap-4 md:px-8">
        <NavLink to="/" className="flex shrink-0 items-baseline gap-2">
          <span className="font-display text-h3 font-semibold text-ink-900">Optix</span>
          <span className="rounded-sm bg-brand-600 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wider text-white">
            Japan
          </span>
        </NavLink>
        <nav aria-label={t('主导航')} className="hidden flex-1 items-center gap-1 xl:flex">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                cn(
                  'whitespace-nowrap rounded-md px-2.5 py-1.5 text-body-s text-ink-600 transition-colors hover:bg-brand-50 hover:text-ink-900',
                  isActive && 'bg-brand-50 font-medium text-brand-700',
                )
              }
            >
              <span className="mr-1 font-mono text-micro text-ink-300">{item.index}</span>
              {t(item.label)}
            </NavLink>
          ))}
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
                className="flex items-center gap-1 rounded-md px-2 py-1.5 text-body-s text-ink-500 hover:bg-brand-50 hover:text-ink-900"
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
    <select
      aria-label={t('切换语言')}
      className="rounded-md border border-line bg-card px-1.5 py-1 text-caption text-ink-600"
      value={current}
      onChange={(event) => setLocale(event.target.value as typeof current)}
    >
      {LOCALES.map((locale) => (
        <option key={locale.code} value={locale.code}>
          {locale.short}
        </option>
      ))}
    </select>
  );
}

function SearchBox({ onPick }: { onPick: (code: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

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
      <div className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1.5">
        <Icon name="search" size={14} className="text-ink-400" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder={t('搜索代码或公司名')}
          className="w-28 bg-transparent text-body-s text-ink-900 outline-none placeholder:text-ink-300 sm:w-40"
        />
      </div>
      {open && results.length > 0 && (
        <ul className="absolute right-0 top-full z-50 mt-1 w-72 overflow-hidden rounded-lg border border-line bg-card shadow-sh-2">
          {results.map((item) => (
            <li key={item.canonical_code}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-brand-50"
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
        </ul>
      )}
    </div>
  );
}
