import { test, expect } from '@playwright/test';

async function open(page, locale = 'en') {
  await page.addInitScript(locale => localStorage.setItem('optixjp:locale', locale), locale);
  await page.route(url => url.pathname.startsWith('/api/'), route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/access/status') return route.fulfill({ json: { mode: 'password', is_owner: false, password_configured: true, account: { logged_in: false, username: null } } });
    return route.fulfill({ json: { results: [] } });
  });
  await page.goto('/visual-tests/support/mobile-controls.html');
}

for (const width of [320, 390]) {
  test(`phone controls have real separate 44px targets at ${width}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL, viewport: { width, height: 568 }, hasTouch: true, isMobile: true });
    const page = await context.newPage(); await open(page);
    const history = page.locator('button[aria-haspopup=dialog]');
    expect((await history.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await page.getByRole('combobox', { name: 'Regression menu' }).click();
    await page.getByRole('listbox').evaluate(async el => {
      await Promise.all(el.getAnimations().map(animation => animation.finished.catch(() => {})));
    });
    for (const item of await page.getByRole('option').all()) expect((await item.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await page.keyboard.press('Escape');
    await page.locator('#open-palette').click();
    const input = page.getByRole('combobox').last(); await input.fill('zzzz');
    const clear = page.getByRole('button', { name: /Clear search|清除搜索|検索をクリア/i });
    // The loading spinner is narrower than the clear button. Measure after
    // that real search state has finished changing the input's flex width.
    await expect(clear).toBeVisible();
    const boxes = await Promise.all([input, clear].map(el => el.boundingBox()));
    for (const box of boxes.slice(1)) { expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44); }
    expect(boxes[0].x + boxes[0].width).toBeLessThanOrEqual(boxes[1].x);
    expect(boxes[1].x + boxes[1].width).toBeLessThanOrEqual(width - 8);
    await clear.click(); await expect(input).toHaveValue(''); await expect(input).toBeFocused();
    for (const result of await page.getByRole('option').all()) expect((await result.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await context.close();
  });
}

for (const locale of ['zh', 'en', 'ja']) {
 for (const height of [160, 180]) {
  test(`existing long ${locale} ${height}px score explanation fits and scrolls in keyboard-height viewport`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height }); await open(page, locale);
    const trigger = page.locator('#hint-parent [role=button]');
    await trigger.focus();
    const tip = page.getByRole('tooltip'); await expect(tip).toBeVisible();
    await expect(tip).toContainText({ zh: '七档窗口', en: 'seven windows', ja: '7 段階のウィンドウ' }[locale]);
    await expect(tip).toContainText({ zh: '质量为七维加权', en: 'Quality is a seven-factor weighting', ja: '品質は 7 要素の加重' }[locale]);
    await expect(tip).toHaveClass(/is-shown/);
    await tip.evaluate(async el => { await Promise.all(el.getAnimations().map(a => a.finished.catch(() => {}))); });
    const metrics = await tip.evaluate(el => ({ top: el.getBoundingClientRect().top, bottom: el.getBoundingClientRect().bottom, height: el.clientHeight, content: el.scrollHeight }));
    expect(metrics.top).toBeGreaterThanOrEqual(8);
    expect(metrics.bottom).toBeLessThanOrEqual(height - 8);
    expect(metrics.content).toBeGreaterThan(metrics.height);
    await trigger.press('ArrowDown'); await expect(tip).toBeFocused();
    await page.keyboard.press('End');
    await expect.poll(() => tip.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    await tip.click({ position: { x: 15, y: 20 } });
    await expect(tip).toBeVisible(); await expect(page.locator('#parent-clicks')).toHaveText('0');
    await page.keyboard.press('Escape'); await expect(tip).toHaveCount(0); await expect(trigger).toBeFocused();
    await page.locator('#outside').click(); await expect(tip).toHaveCount(0);
  });
 }
}

test('short explanation permits pointer travel into portal and dismisses after leaving both', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 }); await open(page);
  const trigger = page.locator('#short-hint [role=button]'); await trigger.hover();
  const tip = page.getByRole('tooltip'); await expect(tip).toBeVisible();
  await tip.hover(); await expect(tip).toBeVisible();
  await page.mouse.move(500, 500); await expect(tip).toHaveCount(0);
});

test('phone long explanation scrolls with touch without closing or activating its parent', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 320, height: 180 }, hasTouch: true, isMobile: true, reducedMotion: 'reduce' });
  const page = await context.newPage(); await open(page, 'en');
  await page.locator('#hint-parent [role=button]').tap();
  const tip = page.getByRole('tooltip'); await expect(tip).toBeVisible();
  const box = await tip.boundingBox();
  const client = await context.newCDPSession(page);
  // The new fixed scroll layer must be painted before native gestures start.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  // Keep the gesture in the upper half: macOS headless Chrome's very short
  // native window clips lower compositor input even when the DOM viewport fits.
  const startY = box.y + Math.min(72, box.height / 2);
  const swipes = await tip.evaluate(el => Math.ceil((el.scrollHeight - el.clientHeight) / 50) + 1);
  for (let swipe = 0; swipe < swipes; swipe += 1) {
    await client.send('Input.synthesizeScrollGesture', {
      x: box.x + box.width / 2, y: startY,
      yDistance: -50, speed: 200, gestureSourceType: 'touch',
    });
  }
  await expect.poll(() => tip.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await expect.poll(() => tip.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThanOrEqual(1);
  await expect(tip).toBeVisible();
  await expect(page.locator('#parent-clicks')).toHaveText('0');
  await page.touchscreen.tap(316, 20);
  await expect(tip).toHaveCount(0);
  await context.close();
});

for (const theme of ['light', 'dark']) test(`settings and notification retain targets, status and keyboard semantics in ${theme}`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 });
  await open(page, 'zh');
  await page.evaluate(theme => document.documentElement.classList.toggle('dark', theme === 'dark'), theme);
  const settings = page.locator('#settings button').first();
  await settings.press('Enter');
  const menu = page.getByRole('menu');
  await expect(menu).toBeVisible();
  await menu.evaluate(async el => { await Promise.all(el.getAnimations().map(a => a.finished.catch(() => {}))); });
  for (const item of await menu.getByRole('menuitemradio').all()) {
    await expect.poll(async () => (await item.boundingBox()).height).toBeGreaterThanOrEqual(44);
  }
  await expect(menu.getByRole('menuitemradio', { name: /简体中文/ })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('End');
  await expect(menu.getByRole('menuitemradio').last()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  await expect(settings).toBeFocused();
  await page.locator('#show-toast').click();
  const notice = page.getByRole('alert');
  await expect(notice).toContainText('通知标题');
  await expect(notice).toContainText('需要保留的错误说明');
  await notice.evaluate(async el => { await Promise.all(el.getAnimations().map(a => a.finished.catch(() => {}))); });
  const close = notice.getByRole('button', { name: '关闭通知' });
  await expect.poll(async () => (await close.boundingBox()).width).toBeGreaterThanOrEqual(44);
  await expect.poll(async () => (await close.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await close.press('Enter');
  await expect(notice).toHaveCount(0);
});
