import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import Layout from '@/components/Layout';
import { AccessProvider } from '@/hooks/useAccess';
import { PageFallback } from '@/components/shared/Fallbacks';

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
const Login = lazy(() => import('@/pages/Login'));
const NotFound = lazy(() => import('@/pages/NotFound'));

export default function App() {
  return (
    <BrowserRouter>
      <AccessProvider>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Layout />}>
              <Route path="/" element={<Home />} />
              <Route path="/market" element={<Market />} />
              <Route path="/radar" element={<Radar />} />
              <Route path="/screener" element={<Screener />} />
              <Route path="/watchlist" element={<Watchlist />} />
              <Route path="/earnings" element={<Earnings />} />
              <Route path="/news" element={<News />} />
              <Route path="/stock/:code" element={<StockDetail />} />
              <Route path="/data-status" element={<DataStatus />} />
              <Route path="/research" element={<Research />} />
              <Route path="/home" element={<Navigate to="/" replace />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </Suspense>
      </AccessProvider>
    </BrowserRouter>
  );
}
