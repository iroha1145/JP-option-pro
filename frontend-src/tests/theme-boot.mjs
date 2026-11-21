/** 启动脚本与应用内的外观、语言规则必须一致：键名、深色判定、语言回退顺序。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { detectLocale, LOCALES } from '../src/i18n/core.ts';
import { THEME_KEY } from '../src/lib/themePreference.ts';

const boot = fs.readFileSync(new URL('../public/theme-boot.js', import.meta.url), 'utf8');
const core = fs.readFileSync(new URL('../src/i18n/core.ts', import.meta.url), 'utf8');
const LOCALE_KEY = core.match(/const STORAGE_KEY = '([^']+)'/)[1];

function run({ stored = {}, systemDark = false, languages = ['en-US'], storageThrows = false } = {}) {
  const classes = new Set();
  const meta = { content: '#FAFAFA', setAttribute(name, value) { this[name] = value; } };
  const root = {
    lang: 'zh-CN', dataset: {}, style: {},
    classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) },
  };
  vm.runInNewContext(boot, {
    localStorage: { getItem: (key) => { if (storageThrows) throw new Error('denied'); return stored[key] ?? null; } },
    matchMedia: () => ({ matches: systemDark }),
    navigator: { language: languages[0], languages },
    document: { documentElement: root, querySelector: () => meta },
  });
  return { root, dark: classes.has('dark'), themeColor: meta.content };
}

test('启动脚本读取的键名与应用一致', () => {
  assert.ok(boot.includes(`'${THEME_KEY}'`));
  assert.ok(boot.includes(`'${LOCALE_KEY}'`));
});

test('外观：已保存的选择优先，其次跟随系统', () => {
  assert.equal(run({ stored: { [THEME_KEY]: 'dark' } }).dark, true);
  assert.equal(run({ stored: { [THEME_KEY]: 'light' }, systemDark: true }).dark, false);
  assert.equal(run({ stored: { [THEME_KEY]: 'system' }, systemDark: true }).dark, true);
  const dark = run({ systemDark: true });
  assert.deepEqual([dark.dark, dark.root.dataset.theme, dark.root.style.colorScheme, dark.themeColor], [true, 'dark', 'dark', '#0F0F10']);
  const light = run();
  assert.deepEqual([light.dark, light.root.dataset.theme, light.root.style.colorScheme, light.themeColor], [false, 'light', 'light', '#FAFAFA']);
});

test('语言：已保存的选择优先，否则与 detectLocale 同一回退顺序', () => {
  const tagOf = (code) => LOCALES.find((item) => item.code === code).tag;
  for (const code of ['zh', 'ja', 'en']) {
    assert.equal(run({ stored: { [LOCALE_KEY]: code }, languages: ['fr-FR'] }).root.lang, tagOf(code));
  }
  for (const languages of [['ja-JP', 'en-US'], ['zh-TW'], ['fr-FR', 'zh-CN'], ['de-DE'], ['en-GB', 'ja'], ['ko-KR', 'ja-JP', 'zh-CN']]) {
    assert.equal(run({ languages }).root.lang, tagOf(detectLocale(languages)), languages.join(','));
  }
  assert.equal(run({ stored: { [LOCALE_KEY]: 'toString' }, languages: ['ja'] }).root.lang, 'ja-JP');
});

test('读不到本机存储时仍按系统外观与浏览器语言完成设置', () => {
  const result = run({ storageThrows: true, systemDark: true, languages: ['ja-JP'] });
  assert.equal(result.dark, true);
  assert.equal(result.root.lang, 'ja-JP');
});
