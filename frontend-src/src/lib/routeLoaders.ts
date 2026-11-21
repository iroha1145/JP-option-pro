export const routeLoaders = {
  home: () => import('@/pages/Home'),
  market: () => import('@/pages/Market'),
  radar: () => import('@/pages/Radar'),
  screener: () => import('@/pages/Screener'),
  watchlist: () => import('@/pages/Watchlist'),
  earnings: () => import('@/pages/Earnings'),
  news: () => import('@/pages/News'),
  stockDetail: () => import('@/pages/StockDetail'),
  dataStatus: () => import('@/pages/DataStatus'),
  shortMonitor: () => import('@/pages/ShortMonitor'),
  login: () => import('@/pages/Login'),
} as const;

const PATH_LOADERS: Record<string, () => Promise<unknown>> = {
  '/': routeLoaders.home,
  '/home': routeLoaders.home,
  '/market': routeLoaders.market,
  '/radar': routeLoaders.radar,
  '/screener': routeLoaders.screener,
  '/watchlist': routeLoaders.watchlist,
  '/earnings': routeLoaders.earnings,
  '/news': routeLoaders.news,
  '/data-status': routeLoaders.dataStatus,
  '/short-monitor': routeLoaders.shortMonitor,
  '/login': routeLoaders.login,
};

export function preloadRoute(path: string): void {
  const clean = path.split('?')[0];
  const loader = clean.startsWith('/stock/') ? routeLoaders.stockDetail : PATH_LOADERS[clean];
  if (loader) void loader().catch(() => {});
}
