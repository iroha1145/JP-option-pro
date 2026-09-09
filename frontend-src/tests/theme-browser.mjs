/**
 * 夜间模式浏览器覆盖：各路由 + 桌面/手机 + 系统/浅色/深色。
 * 需要本机 Chrome 与已启动的预览服务。
 *
 *   THEME_BASE_URL=http://127.0.0.1:4180 node frontend-src/tests/theme-browser.mjs
 */
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';

const BASE = process.env.THEME_BASE_URL || 'http://127.0.0.1:4180';
const CHROME = process.env.CHROME_PATH || '/usr/bin/google-chrome-stable';

const ROUTES = [
  '/',
  '/watchlist',
  '/screener',
  '/radar',
  '/market',
  '/earnings',
  '/news',
  '/short-monitor',
  '/data-status',
  '/research',
  '/login',
  '/stock/7203',
];

const TOKENS = {
  light: { paper: 'rgb(246, 247, 249)', card: 'rgb(255, 255, 255)', ink: 'rgb(13, 22, 38)' },
  dark: { paper: 'rgb(25, 27, 32)', card: 'rgb(36, 38, 45)', ink: 'rgb(241, 243, 245)' },
};

async function readTheme(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const css = getComputedStyle(root);
    return {
      darkClass: root.classList.contains('dark'),
      theme: root.getAttribute('data-theme'),
      preference: root.getAttribute('data-theme-preference'),
      colorScheme: root.style.colorScheme || getComputedStyle(root).colorScheme,
      paper: css.getPropertyValue('--paper').trim(),
      card: css.getPropertyValue('--card').trim(),
      ink: css.getPropertyValue('--ink-900').trim(),
      brand: css.getPropertyValue('--brand-600').trim(),
      switchers: document.querySelectorAll('[data-theme-switcher]').length,
    };
  });
}

function hexToRgb(hex) {
  const raw = hex.replace('#', '');
  const n = Number.parseInt(raw, 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

async function chooseAppearance(page, preference) {
  const trigger = await page.waitForSelector('[data-theme-switcher]', { timeout: 5000 });
  assert.ok(trigger, `页面没有外观按钮`);
  await trigger.click();
  const option = await page.waitForSelector(`[data-theme-option="${preference}"]`, { timeout: 3000 });
  assert.ok(option, `菜单里没有 ${preference}`);
  await option.click();
  await page.waitForFunction(
    (wanted) => document.documentElement.getAttribute('data-theme-preference') === wanted,
    { timeout: 3000 },
    preference,
  );
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  const failures = [];
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);

    await page.goto(`${BASE}/`, { waitUntil: 'networkidle0', timeout: 30000 });
    await chooseAppearance(page, 'light');
    let theme = await readTheme(page);
    assert.equal(theme.preference, 'light');
    assert.equal(theme.darkClass, false);
    assert.equal(hexToRgb(theme.paper), TOKENS.light.paper);

    await chooseAppearance(page, 'dark');
    theme = await readTheme(page);
    assert.equal(theme.preference, 'dark');
    assert.equal(theme.darkClass, true);
    assert.equal(hexToRgb(theme.paper), TOKENS.dark.paper);
    assert.equal(hexToRgb(theme.card), TOKENS.dark.card);
    assert.equal(hexToRgb(theme.ink), TOKENS.dark.ink);
    assert.equal(theme.brand.toUpperCase(), '#8ABCF0');

    for (const route of ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForSelector('[data-theme-switcher]', { timeout: 8000 });
      const snapshot = await readTheme(page);
      if (!snapshot.darkClass || snapshot.theme !== 'dark' || snapshot.switchers < 1) {
        failures.push(`${route} desktop dark: ${JSON.stringify(snapshot)}`);
      }
    }

    await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    for (const route of ['/', '/watchlist', '/screener', '/login']) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForSelector('[data-theme-switcher]', { timeout: 8000 });
      const snapshot = await readTheme(page);
      const box = await page.evaluate(() => {
        const trigger = document.querySelector('[data-theme-switcher]');
        if (!trigger) return null;
        const rect = trigger.getBoundingClientRect();
        return {
          top: rect.top,
          right: window.innerWidth - rect.right,
          centerX: rect.left + rect.width / 2,
          width: rect.width,
          height: rect.height,
          vw: window.innerWidth,
        };
      });
      const inTopRight = box && box.top <= 72 && box.centerX > box.vw * 0.55 && box.height >= 32;
      if (!snapshot.darkClass || !inTopRight) {
        failures.push(`${route} mobile: ${JSON.stringify({ snapshot, box })}`);
      }
    }

    await chooseAppearance(page, 'system');
    theme = await readTheme(page);
    assert.equal(theme.preference, 'system');
    assert.equal(theme.darkClass, false);

    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
    await page.reload({ waitUntil: 'domcontentloaded' });
    theme = await readTheme(page);
    if (theme.preference !== 'system' || !theme.darkClass) {
      failures.push(`system+device dark: ${JSON.stringify(theme)}`);
    }
  } finally {
    await browser.close();
  }

  assert.deepEqual(failures, [], failures.join('\n'));
  console.log(`theme-browser ok: ${ROUTES.length} routes, desktop+mobile, system/light/dark`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
