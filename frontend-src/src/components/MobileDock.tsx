import { NavLink } from 'react-router';
import { Icon, type IconName } from '@/components/icons';
import { t } from '@/i18n/core';
import { cn } from '@/lib/utils';

const DOCK: { path: string; label: string; icon: IconName }[] = [
  { path: '/watchlist', label: '自选股', icon: 'star-line' },
  { path: '/radar', label: '突破雷达', icon: 'radar' },
  { path: '/market', label: '日本市场', icon: 'candle' },
  { path: '/news', label: '新闻', icon: 'doc-quote' },
  { path: '/screener', label: '筛选器', icon: 'filter-funnel' },
];

export default function MobileDock() {
  return (
    <nav
      aria-label={t('主导航')}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-overlay backdrop-blur-md lg:hidden"
    >
      <ul className="grid grid-cols-5">
        {DOCK.map((item) => (
          <li key={item.path}>
            <NavLink
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'flex flex-col items-center gap-0.5 py-2 text-micro text-ink-500',
                  isActive && 'text-brand-700',
                )
              }
            >
              <Icon name={item.icon} size={18} />
              {t(item.label)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
