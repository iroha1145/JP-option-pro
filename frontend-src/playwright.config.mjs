import { defineConfig } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
export default defineConfig({
  testDir: './visual-tests',
  outputDir: join(tmpdir(), 'jp-typeui-browser-results'),
  workers: 1,
  timeout: 30_000,
  reporter: [['list']],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4318 --strictPort',
    url: 'http://127.0.0.1:4318',
    reuseExistingServer: false,
    env: { OPTIXJP_API_PROXY: 'http://127.0.0.1:9' },
  },
  use: {
    baseURL: 'http://127.0.0.1:4318',
    viewport: { width: 390, height: 844 },
    locale: 'zh-CN',
    contextOptions: { reducedMotion: 'no-preference' },
    actionTimeout: 10_000,
    launchOptions: process.env.OPTIX_PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.OPTIX_PLAYWRIGHT_EXECUTABLE_PATH } : undefined,
    trace: 'retain-on-failure',
  },
});
