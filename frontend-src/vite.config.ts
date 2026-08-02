import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

// 開発時の /api プロキシ先（既定はローカルバックエンド）。
const proxyTarget = process.env.OPTIXJP_API_PROXY || 'http://127.0.0.1:2100';

export default defineConfig({
  // ルート直下配信専用。相対 base は /stock/7203 のような深いルートで
  // ./assets が /stock/assets に解決されて白画面になるため使わない。
  base: '/',
  plugins: [react()],
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
