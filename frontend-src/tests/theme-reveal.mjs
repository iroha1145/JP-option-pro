import test from 'node:test';
import { setImmediate } from 'node:timers';
import assert from 'node:assert/strict';

// Simulates the browser callback ordering where a skipped snapshot's update is
// still delivered after a second theme selection.
test('latest theme selection owns delayed callbacks, storage and reveal cleanup', async () => {
  const saved = Object.fromEntries(['window', 'document', 'innerWidth', 'innerHeight'].map(key => [key, globalThis[key]]));
  const values = new Map();
  const properties = new Map();
  const root = { dataset: {}, classList: { toggle() {} }, style: {
    setProperty(key, value) { properties.set(key, value); },
    removeProperty(key) { properties.delete(key); },
  } };
  const pending = [];
  let reduced = false;
  let systemDark = false;
  globalThis.window = {
    matchMedia(query) { return { matches: query.includes('reduced-motion') ? reduced : systemDark, addEventListener() {} }; },
    localStorage: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) },
    addEventListener() {},
  };
  globalThis.innerWidth = 390;
  globalThis.innerHeight = 844;
  globalThis.document = {
    documentElement: root,
    querySelector: () => null,
    startViewTransition(update) {
      let finish;
      const item = { update, ready: Promise.resolve(), finished: new Promise(resolve => { finish = resolve; }),
        skipTransition() { this.skipped = true; }, finish: () => finish() };
      pending.push(item);
      return item;
    },
  };
  try {
    const { revealThemePreference } = await import('../src/lib/themeReveal.ts');
    const { applyAppearance, getThemePreference, getAppearance, THEME_KEY } = await import('../src/lib/themePreference.ts');
    assert.equal(THEME_KEY, 'optixjp_theme');
    applyAppearance('light');
    const trigger = { getBoundingClientRect: () => ({ left: 300, top: 12, width: 32, height: 32 }) };
    revealThemePreference('dark', trigger);
    assert.equal(properties.get('--theme-x'), '316px');
    assert.equal(properties.get('--theme-y'), '28px');
    const radius = Number.parseFloat(properties.get('--theme-r'));
    assert.ok(radius >= Math.hypot(316, 844 - 28));
    revealThemePreference('light', trigger);
    assert.equal(pending[0].skipped, true);
    pending[0].update();
    assert.equal(getAppearance(), 'light');
    assert.equal(getThemePreference(), 'light');
    assert.equal(root.dataset.themeSwitching, undefined);
    assert.equal(properties.size, 0);

    revealThemePreference('dark', trigger);
    const second = pending.at(-1);
    second.update();
    assert.equal(getAppearance(), 'dark');
    assert.equal(values.get('optixjp_theme'), 'dark');
    second.finish();
    await second.finished;
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(root.dataset.themeSwitching, undefined);
    assert.equal(properties.size, 0);

    reduced = true;
    revealThemePreference('light', trigger);
    assert.equal(getAppearance(), 'light');
    assert.equal(pending.length, 2);
    reduced = false;
    systemDark = true;
    revealThemePreference('system', null);
    assert.equal(getAppearance(), 'dark');
    assert.equal(getThemePreference(), 'system');
    assert.equal(values.get('optixjp_theme'), 'system');
    globalThis.document.startViewTransition = undefined;
    revealThemePreference('light', trigger);
    assert.equal(getAppearance(), 'light');
  } finally {
    for (const [key, value] of Object.entries(saved)) globalThis[key] = value;
  }
});
