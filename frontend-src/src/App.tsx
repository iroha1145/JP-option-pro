import { Suspense, lazy } from 'react';
import { MotionConfig } from 'framer-motion';
import { Navigate, Route, Routes } from 'react-router';
import { usePrefersReducedMotion } from '@/hooks/usePrefersReducedMotion';
import Layout from '@/components/Layout';
import { AccessProvider } from '@/hooks/useAccess';
import { ToastProvider } from '@/components/Toast';
import AppErrorBoundary from '@/components/shared/AppErrorBoundary';
import PageFallback from '@/components/shared/PageFallback';
import NotFound from '@/pages/NotFound';

const Home = lazy(() => import('@/pages/Home'));
const Market = lazy(() => import('@/pages/Market'));
const Radar = lazy(() => import('@/pages/Radar'));
const Screener = lazy(() => import('@/pages/Screener'));
const Watchlist = lazy(() => import('@/pages/Watchlist'));
const Earnings = lazy(() => import('@/pages/Earnings'));
const News = lazy(() => import('@/pages/News'));
const StockDetail = lazy(() => import('@/pages/StockDetail'));
const DataStatus = lazy(() => import('@/pages/DataStatus'));
const Research = lazy(() => import('@/pages/Research'));
const ShortMonitor = lazy(() => import('@/pages/ShortMonitor'));
const Login = lazy(() => import('@/pages/Login'));

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
                  <Route path="/research" element={<Research />} />
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
