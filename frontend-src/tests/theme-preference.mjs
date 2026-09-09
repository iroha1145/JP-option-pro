/**
 * 夜间模式：跟随系统 / 手动浅色 / 手动深色。
 * CSS / Tailwind / CH / 热力中性色必须共用同一份外观快照；
 * 渲染期读主题 chrome 的组件必须订阅 useTheme。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  THEME_CHROME,
  THEME_META_COLOR,
  THEME_STORAGE_KEY,
  applyTheme,
  getResolvedTheme,
  getThemePreference,
  readSystemAppearance,
  resolveTheme,
  setThemePreference,
  subscribeTheme,
} from '../src/lib/themePreference.ts';
import { DARK_PRICE_COLORS, PRICE_COLORS, directionColors } from '../src/lib/colorPreference.ts';
import { CH, heatColor } from '../src/lib/chart.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', 'src');
const root = path.resolve(here, '..');

async function source(relativePath) {
  return readFile(path.join(src, relativePath), 'utf8');
}

function codeOf(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => {
      const trimmed = line.trimStart();
      return !trimmed.startsWith('//') && !trimmed.startsWith('*');
    })
    .join('\n');
}

function installDom({ systemDark = false } = {}) {
  const attrs = new Map();
  const classSet = new Set();
  const style = { colorScheme: '' };
  const metas = {
    'theme-color': {
      content: THEME_META_COLOR.light,
      setAttribute(name, value) {
        if (name === 'content') this.content = value;
      },
    },
    'color-scheme': {
      content: 'light dark',
      setAttribute(name, value) {
        if (name === 'content') this.content = value;
      },
    },
  };
  const store = new Map();
  const mediaListeners = new Set();
  let dark = systemDark;
  const media = {
    get matches() {
      return dark;
    },
    addEventListener(_type, fn) {
      mediaListeners.add(fn);
    },
    removeEventListener(_type, fn) {
      mediaListeners.delete(fn);
    },
  };
  globalThis.document = {
    documentElement: {
      classList: {
        toggle(name, force) {
          if (force) classSet.add(name);
          else classSet.delete(name);
        },
        contains(name) {
          return classSet.has(name);
        },
      },
      setAttribute(key, value) {
        attrs.set(key, String(value));
      },
      getAttribute(key) {
        return attrs.get(key) ?? null;
      },
      style,
    },
    querySelector(sel) {
      if (sel === 'meta[name="theme-color"]') return metas['theme-color'];
      if (sel === 'meta[name="color-scheme"]') return metas['color-scheme'];
      return null;
    },
  };
  const storage = {
    getItem(key) {
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      store.set(key, String(value));
    },
    removeItem(key) {
      store.delete(key);
    },
  };
  globalThis.window = {
    localStorage: storage,
    matchMedia(query) {
      return String(query).includes('prefers-color-scheme: dark') ? media : { matches: false, addEventListener() {}, removeEventListener() {} };
    },
    addEventListener() {},
  };
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
  return {
    attrs,
    classSet,
    style,
    metas,
    store,
    setSystemDark(next) {
      dark = next;
      mediaListeners.forEach((fn) => fn());
    },
  };
}

test.afterEach(() => {
  setThemePreference('system');
});

test('默认跟随系统；resolveTheme 把 system 映射到设备外观', () => {
  assert.equal(resolveTheme('system', 'dark'), 'dark');
  assert.equal(resolveTheme('system', 'light'), 'light');
  assert.equal(resolveTheme('dark', 'light'), 'dark');
  assert.equal(resolveTheme('light', 'dark'), 'light');
});

test('setThemePreference 更新快照、落盘并通知订阅者', () => {
  const seen = [];
  const stop = subscribeTheme(() => seen.push(`${getThemePreference()}:${getResolvedTheme()}`));
  setThemePreference('dark');
  assert.equal(getThemePreference(), 'dark');
  assert.equal(getResolvedTheme(), 'dark');
  setThemePreference('light');
  assert.equal(getThemePreference(), 'light');
  assert.equal(getResolvedTheme(), 'light');
  assert.deepEqual(seen, ['dark:dark', 'light:light']);
  stop();
});

test('applyTheme 写入 html.dark / data-theme / color-scheme / theme-color', () => {
  const dom = installDom({ systemDark: false });
  applyTheme('dark');
  assert.ok(dom.classSet.has('dark'));
  assert.equal(dom.attrs.get('data-theme'), 'dark');
  assert.equal(dom.attrs.get('data-theme-preference'), 'dark');
  assert.equal(dom.style.colorScheme, 'dark');
  assert.equal(dom.metas['theme-color'].content, THEME_CHROME.dark.paper);
  applyTheme('light');
  assert.equal(dom.classSet.has('dark'), false);
  assert.equal(dom.attrs.get('data-theme'), 'light');
  assert.equal(dom.metas['theme-color'].content, THEME_CHROME.light.paper);
});

test('preference=system 时设备切换会更新已解析外观；手动档忽略设备变化', () => {
  const dom = installDom({ systemDark: false });
  setThemePreference('system');
  applyTheme('system');
  assert.equal(getResolvedTheme(), 'light');
  assert.equal(dom.classSet.has('dark'), false);
  const seen = [];
  const stop = subscribeTheme(() => seen.push(getResolvedTheme()));
  dom.setSystemDark(true);
  assert.equal(getThemePreference(), 'system');
  assert.equal(getResolvedTheme(), 'dark');
  assert.ok(dom.classSet.has('dark'));
  setThemePreference('light');
  seen.length = 0;
  dom.setSystemDark(false);
  assert.equal(getThemePreference(), 'light');
  assert.equal(getResolvedTheme(), 'light');
  assert.deepEqual(seen, []);
  stop();
});

test('CH chrome 与涨跌色跟随当前外观', () => {
  setThemePreference('light');
  assert.equal(CH.brand600, THEME_CHROME.light.brand600);
  assert.equal(CH.ink400, THEME_CHROME.light.ink400);
  assert.equal(CH.lineChart, THEME_CHROME.light.lineChart);
  assert.equal(directionColors('western').up600, PRICE_COLORS.western.up600);
  setThemePreference('dark');
  assert.equal(CH.brand600, THEME_CHROME.dark.brand600);
  assert.equal(CH.card, THEME_CHROME.dark.card);
  assert.equal(CH.tooltipFg, THEME_CHROME.dark.tooltipFg);
  assert.equal(directionColors('western').up600, DARK_PRICE_COLORS.western.up600);
  assert.equal(directionColors('asian').up600, DARK_PRICE_COLORS.asian.up600);
});

test('heatColor 中性档在深色下不用浅纸面色', () => {
  setThemePreference('light');
  assert.equal(heatColor(0), 'rgb(241,239,232)');
  setThemePreference('dark');
  assert.equal(heatColor(0), 'rgb(44,48,57)');
});

test('深色 CSS 使用 Cloud Monitor 页底/卡片/主字/边线/主色', async () => {
  const css = await source('index.css');
  const block = css.match(/html\.dark\s*\{([\s\S]*?)\n  \}/);
  assert.ok(block, '缺少 html.dark 规则');
  const body = block[1];
  assert.match(body, /--paper:\s*#191B20/i);
  assert.match(body, /--card:\s*#24262D/i);
  assert.match(body, /--ink-900:\s*#F1F3F5/i);
  assert.match(body, /--ink-600:\s*#B0B6C0/i);
  assert.match(body, /--line:\s*#323640/i);
  assert.match(body, /--brand-600:\s*#8ABCF0/i);
  assert.match(body, /--up-600:\s*#62D0A5/i);
  assert.match(css, /html\.dark\[data-color-mode="asian"\]/);
});

test('Tailwind paper/ink/line/brand 从 CSS 变量生成，而不是编译期写死 hex', async () => {
  const config = await source('../tailwind.config.js');
  assert.match(config, /paper:\s*\{[^}]*var\(--paper\)/s);
  assert.match(config, /ink:\s*\{[^}]*var\(--ink-900\)/s);
  assert.match(config, /line:\s*\{[^}]*var\(--line\)/s);
  assert.match(config, /brand:\s*\{[^}]*var\(--brand-600\)/s);
  assert.doesNotMatch(config, /paper:\s*\{[^}]*#F6F7F9/s);
  assert.doesNotMatch(config, /ink:\s*\{[^}]*#0D1626/s);
  assert.doesNotMatch(config, /brand:\s*\{[^}]*#2E46E0/s);
});

test('顶栏始终挂 ThemeSwitcher；登录页右上角也有；不藏进 xl', async () => {
  const navbar = codeOf(await source('components/Navbar.tsx'));
  const login = codeOf(await source('pages/Login.tsx'));
  const switcher = codeOf(await source('components/ThemeSwitcher.tsx'));
  assert.match(navbar, /<ThemeSwitcher/);
  assert.doesNotMatch(navbar, /<ThemeSwitcher[^>]*className="[^"]*hidden/);
  assert.match(login, /<ThemeSwitcher corner/);
  assert.match(switcher, /corner \? 'fixed right-3 top-3/);
  assert.doesNotMatch(switcher, /corner && 'fixed/);
  assert.match(switcher, /useThemePreference\(\)/);
  assert.match(switcher, /setThemePreference/);
  assert.match(switcher, /跟随系统/);
  assert.match(switcher, /浅色/);
  assert.match(switcher, /深色/);
  assert.match(switcher, /theme-control/);
  assert.match(switcher, /data-theme-switcher/);
  assert.match(switcher, /data-theme-option/);
});

test('main 与 index.html 在首屏之前套用主题，避免白闪', async () => {
  const main = codeOf(await source('main.tsx'));
  const html = await readFile(path.join(root, 'index.html'), 'utf8');
  assert.match(main, /applyTheme\(\)/);
  assert.match(html, /optixjp_theme/);
  assert.match(html, /prefers-color-scheme: dark/);
  assert.match(html, /classList\.toggle\('dark'/);
  assert.match(html, /name="color-scheme" content="light dark"/);
  assert.match(html, /name="theme-color"/);
  assert.equal(THEME_STORAGE_KEY, 'optixjp_theme');
});

test('渲染期读主题 chrome 的 .tsx 必须订阅 useTheme', async () => {
  const { readdir } = await import('node:fs/promises');
  const READS_THEME = /\bCH\.(ink400|ink300|lineChart|brand600|brand500|brand400|ai600|warn600|card|tooltipFg)\b|\bheatColor\s*\(/;
  const offenders = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.name.endsWith('.tsx')) {
        const code = codeOf(await readFile(full, 'utf8'));
        if (READS_THEME.test(code) && !/useTheme\s*\(/.test(code)) {
          offenders.push(path.relative(src, full));
        }
      }
    }
  };
  await walk(src);
  assert.deepEqual(offenders, [], `这些组件读主题色却没订阅换肤：${offenders.join(', ')}`);
});

test('词典收录外观三态文案', async () => {
  const { DICT } = await import('../src/i18n/dict/index.ts');
  for (const key of ['外观', '切换外观', '跟随系统', '浅色', '深色', '当前：浅色模式', '当前：深色模式', '当前：跟随系统（{mode}）']) {
    assert.ok(DICT[key], `缺词典：${key}`);
    assert.equal(DICT[key].length, 2);
  }
});

test('readSystemAppearance 在没有 matchMedia 时回退浅色', () => {
  const previous = globalThis.window;
  globalThis.window = { matchMedia: undefined };
  assert.equal(readSystemAppearance(), 'light');
  globalThis.window = previous;
});
