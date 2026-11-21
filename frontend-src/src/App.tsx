import { Suspense, lazy } from 'react';
import { MotionConfig } from 'framer-motion';
import { Navigate, Route, Routes } from 'react-router';
import { usePrefersReducedMotion } from '@/hooks/usePrefersReducedMotion';
import Layout from '@/components/Layout';
import { AccessProvider } from '@/hooks/useAccess';
import { ToastProvider } from '@/components/Toast';
import AppErrorBoundary from '@/components/shared/AppErrorBoundary';
import PageFallback from '@/components/shared/PageFallback';
import { routeLoaders } from '@/lib/routeLoaders';
import NotFound from '@/pages/NotFound';

const Home = lazy(routeLoaders.home);
const Market = lazy(routeLoaders.market);
const Radar = lazy(routeLoaders.radar);
const Screener = lazy(routeLoaders.screener);
const Watchlist = lazy(routeLoaders.watchlist);
const Earnings = lazy(routeLoaders.earnings);
const News = lazy(routeLoaders.news);
const StockDetail = lazy(routeLoaders.stockDetail);
const DataStatus = lazy(routeLoaders.dataStatus);
const ShortMonitor = lazy(routeLoaders.shortMonitor);
const Login = lazy(routeLoaders.login);

export default function App() {
  const reducedMotion = usePrefersReducedMotion();
  return (
    <AppErrorBoundary>
      <MotionConfig reducedMotion={reducedMotion ? 'always' : 'never'}>
        <AccessProvider>
          <ToastProvider>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={<Layout />}>
                  <Route index element={<Home />} />
                  <Route path="/home" element={<Navigate to="/" replace />} />
                  <Route path="/watchlist" element={<Watchlist />} />
                  <Route path="/screener" element={<Screener />} />
                  <Route path="/radar" element={<Radar />} />
                  <Route path="/market" element={<Market />} />
                  <Route path="/earnings" element={<Earnings />} />
                  <Route path="/news" element={<News />} />
                  <Route path="/short-monitor" element={<ShortMonitor />} />
                  <Route path="/data-status" element={<DataStatus />} />
                  <Route path="/stock/:code" element={<StockDetail />} />
                  <Route path="*" element={<NotFound />} />
                </Route>
              </Routes>
            </Suspense>
          </ToastProvider>
        </AccessProvider>
      </MotionConfig>
    </AppErrorBoundary>
  );
}
