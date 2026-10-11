import { isNavPathActive } from './utils.ts';
import { t } from '../i18n/core.ts';

export type NavSection = 'screener' | 'market';
export interface NavPage { label: string; path: string }
export interface NavGroup extends NavPage { pages: readonly NavPage[]; section?: NavSection }

const screener = { label: t('条件选股'), path: '/screener' };
const radar = { label: t('突破雷达'), path: '/radar' };
const market = { label: t('日本市场'), path: '/market' };
const shortMonitor = { label: t('机构空卖'), path: '/short-monitor' };
export const NAV_GROUPS: readonly NavGroup[] = [
  { label: t('首页'), path: '/', pages: [] },
  { label: t('我的关注'), path: '/watchlist', pages: [] },
  { label: t('选股'), path: screener.path, pages: [screener, radar], section: 'screener' },
  { label: t('市场'), path: market.path, pages: [market, shortMonitor], section: 'market' },
  { label: t('财报'), path: '/earnings', pages: [] },
  { label: t('新闻'), path: '/news', pages: [] },
];
export const NAV_PAGES: readonly NavPage[] = NAV_GROUPS.flatMap(group => group.pages.length ? group.pages : [group]);
export function isNavGroupActive(pathname: string, group: NavGroup): boolean {
  return (group.pages.length ? group.pages : [group]).some(page => isNavPathActive(pathname, page.path));
}
export function navAriaCurrent(pathname: string, group: NavGroup): 'page' | 'true' | undefined {
  if (isNavPathActive(pathname, group.path)) return 'page';
  return isNavGroupActive(pathname, group) ? 'true' : undefined;
}
export function navSectionPages(section: NavSection): readonly NavPage[] {
  return NAV_GROUPS.find(group => group.section === section)?.pages ?? [];
}
