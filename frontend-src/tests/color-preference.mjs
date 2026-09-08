/**
 * 涨跌色彩习惯：CSS / Tailwind / CH / 热力色阶必须共用一份状态，
 * 渲染期读全局涨跌色的组件必须订阅 useColorMode。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  PRICE_COLORS,
  applyColorMode,
  directionColors,
  getColorMode,
  setColorMode,
  subscribeColorMode,
} from '../src/lib/colorPreference.ts';
import { CH, heatColor } from '../src/lib/chart.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', 'src');

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

test.afterEach(() => {
  setColorMode('asian');
});

test('directionColors 在亚洲习惯下对调涨跌 hex', () => {
  assert.equal(directionColors('western').up600, PRICE_COLORS.western.up600);
  assert.equal(directionColors('western').down600, PRICE_COLORS.western.down600);
  assert.equal(directionColors('asian').up600, PRICE_COLORS.western.down600);
  assert.equal(directionColors('asian').down600, PRICE_COLORS.western.up600);
});

test('setColorMode 更新内存快照并通知订阅者', () => {
  const seen = [];
  const stop = subscribeColorMode(() => seen.push(getColorMode()));
  setColorMode('western');
  assert.equal(getColorMode(), 'western');
  assert.deepEqual(seen, ['western']);
  setColorMode('asian');
  assert.equal(getColorMode(), 'asian');
  assert.deepEqual(seen, ['western', 'asian']);
  stop();
});

test('CH.up600 / CH.down600 跟随当前色彩习惯', () => {
  applyColorMode('western');
  assert.equal(CH.up600, PRICE_COLORS.western.up600);
  assert.equal(CH.down600, PRICE_COLORS.western.down600);
  applyColorMode('asian');
  assert.equal(CH.up600, PRICE_COLORS.asian.up600);
  assert.equal(CH.down600, PRICE_COLORS.asian.down600);
});

test('heatColor 在亚洲习惯下翻转涨跌两端', () => {
  applyColorMode('western');
  const westUp = heatColor(3);
  const westDown = heatColor(-3);
  applyColorMode('asian');
  assert.equal(heatColor(3), westDown);
  assert.equal(heatColor(-3), westUp);
});

test('CSS 亚洲模式重映射与 PRICE_COLORS.asian 一致', async () => {
  const css = await source('index.css');
  const block = css.match(/html\[data-color-mode="asian"\]\s*\{([^}]+)\}/);
  assert.ok(block, '缺少 html[data-color-mode=asian] 规则');
  const body = block[1];
  assert.match(body, new RegExp(`--up-600:\\s*${PRICE_COLORS.asian.up600}`, 'i'));
  assert.match(body, new RegExp(`--down-600:\\s*${PRICE_COLORS.asian.down600}`, 'i'));
  assert.match(body, new RegExp(`--up-700:\\s*${PRICE_COLORS.asian.up700}`, 'i'));
  assert.match(body, new RegExp(`--down-700:\\s*${PRICE_COLORS.asian.down700}`, 'i'));
});

test('Tailwind up/down 色阶从 CSS 变量生成，而不是编译期写死 hex', async () => {
  const config = await source('../tailwind.config.js');
  assert.match(config, /up:\s*\{[^}]*var\(--up-600\)/s);
  assert.match(config, /down:\s*\{[^}]*var\(--down-600\)/s);
  assert.doesNotMatch(config, /up:\s*\{[^}]*#0E9F6E/s);
  assert.doesNotMatch(config, /down:\s*\{[^}]*#E5484D/s);
});

test('顶栏与 Dock 共用 useColorMode，不再各自 useState', async () => {
  const switcher = codeOf(await source('components/ColorModeSwitcher.tsx'));
  const dock = codeOf(await source('components/MobileDock.tsx'));
  assert.match(switcher, /useColorMode\(\)/);
  assert.match(dock, /useColorMode\(\)/);
  assert.doesNotMatch(switcher, /useState/);
  assert.doesNotMatch(dock, /setLocalColorMode|getColorMode\(\)/);
});

test('健康态 SoftBadge 不借用涨跌 up/down', async () => {
  const news = codeOf(await source('pages/News.tsx'));
  const data = codeOf(await source('pages/DataStatus.tsx'));
  const detail = codeOf(await source('pages/StockDetail.tsx'));
  const domain = codeOf(await source('components/domain.tsx'));
  const research = codeOf(await source('pages/Research.tsx'));
  assert.match(news, /tone: 'warn',\s*label: t\('异常'\)/);
  assert.match(news, /failed: \{ label: t\('分析失败'\), tone: 'warn' \}/);
  assert.match(data, /worker\.healthy \? 'brand' : 'warn'/);
  assert.match(detail, /SoftBadge tone="warn"/);
  assert.match(research, /label: '分层单调',\s*tone: 'brand'/);
  assert.match(research, /label: '不单调',\s*tone: 'warn'/);
  assert.doesNotMatch(news, /tone: 'up',\s*label: t\('正常'\)/);
  assert.doesNotMatch(data, /worker\.healthy \? 'up' : 'down'/);
  assert.doesNotMatch(domain, /confirmed:\s*'up'/);
  assert.doesNotMatch(domain, /failed:\s*'down'/);
  assert.doesNotMatch(domain, /bg-up-50|bg-down-50/);
  assert.doesNotMatch(research, /tone: 'up'/);
  assert.doesNotMatch(research, /tone: 'down'/);
});

test('渲染期读涨跌习惯的 .tsx 必须订阅 useColorMode', async () => {
  const { readdir } = await import('node:fs/promises');
  const READS_GLOBAL = /\bCH\.(up600|down600)\b|\bheat(Tone|Color)\s*\(/;
  const offenders = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.name.endsWith('.tsx')) {
        const code = codeOf(await readFile(full, 'utf8'));
        if (READS_GLOBAL.test(code) && !/useColorMode\s*\(/.test(code)) {
          offenders.push(path.relative(src, full));
        }
      }
    }
  };
  await walk(src);
  assert.deepEqual(offenders, [], `这些组件读涨跌色却没订阅换盘：${offenders.join(', ')}`);
});
