/**
 * 版式与表面系统的源码约定：嵌套圆角令牌、不用侧边彩条、通知的状态图标、
 * 排版基础规则，以及各页面使用同一套页面堆叠。这些断言只证明源码遵守约定，
 * 不代替浏览器里的渲染验收。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', 'src');
const source = (p) => readFile(path.join(src, p), 'utf8');

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
const code = async (p) => codeOf(await source(p));

async function walk(dir, out = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(full, out);
    else if (/\.(tsx?|css)$/.test(entry.name)) out.push(full);
  }
  return out;
}

test('表面与控件使用同一组圆角令牌', async () => {
  const css = await code('index.css');
  assert.match(css, /--r-control:\s*12px;/);
  assert.match(css, /--r-group:\s*16px;/);
  assert.match(css, /--r-dropdown-item:\s*8px;/);
  assert.match(css, /--r-select-item:\s*10px;/);
  assert.match(css, /--r-palette-item:\s*12px;/);
  assert.match(css, /--r-dock-item:\s*14px;/);
  assert.match(css, /\.card-surface,\s*\.paper-panel,\s*\.glass-panel\s*\{[^}]*border-radius:\s*1\.5rem;[^}]*box-shadow:\s*var\(--card-shadow\)/);

  const tailwind = await readFile(path.resolve(src, '..', 'tailwind.config.js'), 'utf8');
  assert.match(tailwind, /lg:\s*'24px'/);
  assert.match(tailwind, /xl:\s*'28px'/);

  assert.match(await code('components/shared/MenuSelect.tsx'), /rounded-\[var\(--r-select-item\)\]/);
  const settings = await code('components/SettingsMenu.tsx');
  assert.match(settings, /t-dropdown[^\n]*rounded-\[var\(--r-group\)\][^\n]*p-1\.5/);
  assert.match(settings, /rounded-\[var\(--r-dropdown-item\)\]/);
  assert.match(await code('components/MobileDock.tsx'), /inset-1 rounded-\[var\(--r-dock-item\)\]/);
  const palette = await code('components/CommandPalette.tsx');
  assert.match(palette, /inset-x-1\.5[^\n]*rounded-\[var\(--r-palette-item\)\]/);
  assert.match(palette, /rounded-\[var\(--r-palette-item\)\]\s+px-4\s+py-2/);
});

test('不使用侧边彩条：通知、命令面板、雷达定位与各页面', async () => {
  assert.doesNotMatch(await code('components/Toast.tsx'), /inset-y-0\s+left-0\s+w-\[3px\]/);
  assert.doesNotMatch(await code('components/CommandPalette.tsx'), /inset-y-1\s+left-0\s+w-0\.5/);
  const css = await code('index.css');
  assert.doesNotMatch(css, /inset\s+3px\s+0\s+0\s+var\(--brand-600\)/);
  assert.match(css, /inset\s+0\s+0\s+0\s+1\.5px\s+var\(--brand-600\)/);
  for (const file of await walk(src)) {
    const text = codeOf(await readFile(file, 'utf8'));
    const rel = path.relative(src, file);
    // 带颜色的粗左边框，或只画在一侧的内嵌色条。
    assert.doesNotMatch(text, /border-l-(?:2|4|8|\[[^\]]+\])\s+border-(?:brand|up|down|ok|warn|danger|ai|cat)-/, rel);
    assert.doesNotMatch(text, /inset\s+[1-9]\d*px\s+0\s+0\s+var\(--(?:brand|up|down|ok|warn|danger|ai)/, rel);
  }
});

test('通知保留状态图标、最高浮层阴影与够大的关闭按钮', async () => {
  const toast = await code('components/Toast.tsx');
  assert.match(toast, /STATUS_BADGE/);
  assert.match(toast, /icon:\s*'check'[\s\S]*bg-ok-50\s+text-ok-700/);
  assert.match(toast, /icon:\s*'bell'[\s\S]*bg-brand-50\s+text-brand-700/);
  assert.match(toast, /rounded-\[var\(--r-group\)\]\s+border\s+border-line\s+bg-card\s+shadow-sh-3/);
  assert.match(toast, /touch-target[^\n]*rounded-\[var\(--r-dropdown-item\)\]/);
});

test('排版基础：标题均匀断行、标签不被误选中、字重只用常规与中等', async () => {
  const css = await code('index.css');
  assert.match(css, /font-variant-ligatures:\s*common-ligatures\s+contextual;/);
  assert.match(css, /h1,\s*h2,\s*h3\s*\{\s*text-wrap:\s*balance;\s*\}/);
  assert.match(css, /label:has\(input\[type="checkbox"\],\s*input\[type="radio"\],\s*\[role="switch"\]\)\s*\{\s*user-select:\s*none;\s*\}/);
  for (const file of await walk(src)) {
    if (!/\.tsx?$/.test(file)) continue;
    const text = codeOf(await readFile(file, 'utf8'));
    assert.doesNotMatch(text, /\bfont-(?:semibold|bold|extrabold|black)\b/, path.relative(src, file));
  }
});

test('字阶：最小字号 12 像素，说明文字用字阶自带行高，表头不做全大写加字距', async () => {
  for (const file of await walk(src)) {
    if (!/\.tsx?$/.test(file)) continue;
    const text = codeOf(await readFile(file, 'utf8'));
    const rel = path.relative(src, file);
    // 任意值字号里不得出现小于 12px 的档位。
    for (const match of text.matchAll(/\btext-\[(\d+(?:\.\d+)?)px\]/g)) {
      assert.ok(Number(match[1]) >= 12, `${rel}: ${match[0]}`);
    }
    // 13px 的多行说明不压成 16px 行高（约 1.23 倍，低于 1.4 到 1.6 的可读范围）。
    assert.doesNotMatch(text, /text-micro\s+leading-\[16px\]/, rel);
    assert.doesNotMatch(text, /\buppercase\b[^'"`]*tracking-\[/, rel);
  }
  const tailwind = await readFile(path.resolve(src, '..', 'tailwind.config.js'), 'utf8');
  assert.match(tailwind, /body:\s*\['1rem',\s*\{\s*lineHeight:\s*'1\.625'/);
  assert.match(tailwind, /micro:\s*\['\.8125rem',\s*\{\s*lineHeight:\s*'1\.4'/);
  assert.match(tailwind, /tag:\s*\['\.75rem'/);
  assert.match(await code('pages/News.tsx'), /<h3 className="mt-2 max-w-prose /);
});

test('每个页面都放在同一套页面堆叠里，整页不会被内容撑宽', async () => {
  const css = await code('index.css');
  assert.match(css, /\.page-stack\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /\.app-main\s*\{[^}]*max-inline-size:\s*90rem/);
  assert.match(await code('components/Layout.tsx'), /className="app-main"/);
  assert.match(await code('components/shared/PageHeader.tsx'), /className="page-title"/);
  const pages = (await readdir(path.join(src, 'pages'))).filter((name) => name.endsWith('.tsx'));
  for (const name of pages) {
    const text = await code(`pages/${name}`);
    if (name === 'Login.tsx') { assert.match(text, /login-page/); assert.match(text, /login-layout/); continue; }
    if (name === 'NotFound.tsx') { assert.match(text, /paper-panel/); continue; }
    assert.match(text, /className="page-stack"/, name);
  }
});

test('聚焦环用实色品牌蓝，不用半透明色', async () => {
  for (const file of await walk(src)) {
    if (!/\.tsx?$/.test(file)) continue;
    const text = codeOf(await readFile(file, 'utf8'));
    assert.doesNotMatch(text, /focus-visible:ring-brand-\d+\/\d+/, path.relative(src, file));
  }
});

test('更多筛选保留原生展开语义与键盘焦点', async () => {
  const workbench = await code('components/screener/FilterWorkbench.tsx');
  const summary = workbench.match(/<summary\b[^>]*>/)?.[0];
  assert.ok(summary, '保留原生 details/summary 的键盘展开语义');
  assert.doesNotMatch(summary, /outline-none/);
  const css = await code('index.css');
  assert.match(css, /:focus-visible\s*\{\s*outline:\s*2px solid var\(--brand-600\)/);
});
