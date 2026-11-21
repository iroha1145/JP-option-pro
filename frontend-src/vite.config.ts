import { defineConfig, normalizePath } from 'vite';
import type { GetManualChunk } from 'rollup';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// 開発時の /api プロキシ先（既定はローカルバックエンド）。
const proxyTarget = process.env.OPTIXJP_API_PROXY || 'http://127.0.0.1:2100';

const fromRoot = (file: string) => normalizePath(fileURLToPath(new URL(file, import.meta.url)));
const MAIN_MODULE = fromRoot('./src/main.tsx');
const APP_MODULE = fromRoot('./src/App.tsx');
const ROUTE_LOADERS_MODULE = fromRoot('./src/lib/routeLoaders.ts');
const HOME_MODULE = fromRoot('./src/pages/Home.tsx');
const STYLES = /\.(?:css|scss|sass|less|styl)(?:\?|$)/;

/** Keep stable runtime and dictionary downloads separate from application edits.
 * Share only modules used by Home and another lazy page: collecting every shared
 * page dependency would make Home download detail menus and chart engines. */
function applicationChunks(): GetManualChunk {
  let homeShared: Set<string> | undefined;
  return (id, meta) => {
    const file = normalizePath(id.split('?')[0]);
    if (file.includes('/node_modules/zrender/')) return 'chart-renderer';
    if (file.includes('/node_modules/echarts/')) return 'chart-engine';
    if (file.endsWith('commonjsHelpers.js') || /\/node_modules\/(?:react|react-dom|scheduler)\//.test(file)) return 'react-runtime';
    if (/\/node_modules\/(?:framer-motion|motion-dom|motion-utils)\//.test(file)) return 'motion-runtime';
    if (file.includes('/src/i18n/')) return 'i18n';
    if (STYLES.test(file)) return undefined;
    if (!homeShared) {
      const closure = (root: string): Set<string> => {
        const seen = new Set<string>();
        const visit = (moduleId: string) => {
          if (seen.has(moduleId)) return;
          seen.add(moduleId);
          meta.getModuleInfo(moduleId)?.importedIds.forEach(visit);
        };
        visit(root);
        return seen;
      };
      const entry = closure(MAIN_MODULE);
      // Derive Japan's lazy routes from App / routeLoaders, rather than duplicating a route list.
      const routes = [
        ...(meta.getModuleInfo(APP_MODULE)?.dynamicallyImportedIds ?? []),
        ...(meta.getModuleInfo(ROUTE_LOADERS_MODULE)?.dynamicallyImportedIds ?? []),
      ];
      const users = new Map<string, number>();
      for (const route of routes) {
        for (const moduleId of closure(route)) users.set(moduleId, (users.get(moduleId) ?? 0) + 1);
      }
      homeShared = new Set([...closure(HOME_MODULE)].filter((moduleId) =>
        !entry.has(moduleId) && !routes.includes(moduleId)
        && moduleId.includes('/src/') && !STYLES.test(moduleId)
        && (users.get(moduleId) ?? 0) > 1,
      ));
    }
    return homeShared.has(id) ? 'home-shared' : undefined;
  };
}

export default defineConfig({
  // ルート直下配信専用。相対 base は /stock/7203 のような深いルートで
  // ./assets が /stock/assets に解決されて白画面になるため使わない。
  base: '/',
  plugins: [react()],
  build: {
    // 只面向当前的现代浏览器：不降级语法，也不注入 modulepreload 的兼容脚本。
    target: 'esnext',
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: {
        // Do not pull runtime/theme dependencies into the otherwise lazy engine.
        onlyExplicitManualChunks: true,
        manualChunks: applicationChunks(),
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3100,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        // バックエンドの同源ガードを通すため Origin を書き換える
        headers: { origin: proxyTarget },
      },
    },
  },
  preview: {
    port: 4180,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        headers: { origin: proxyTarget },
      },
    },
  },
});
