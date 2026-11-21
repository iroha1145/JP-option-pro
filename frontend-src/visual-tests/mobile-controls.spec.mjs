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
  // 逐个触点事件拖动。Input.synthesizeScrollGesture 在 CI 的 Linux 上一次都滚不动；
  // feel-gestures 里用触点事件的滚动用例在同一套 CI 上是通过的，这里用同一写法。
  const x = box.x + box.width / 2;
  const send = (type, ys) => client.send('Input.dispatchTouchEvent', { type, touchPoints: ys.map(y => ({ id: 1, x, y })) });
  const swipeUp = async () => {
    await send('touchStart', [startY]);
    for (const travel of [20, 40, 60]) await send('touchMove', [startY - travel]);
    await send('touchEnd', []);
  };
  const remaining = () => tip.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop);
  // 滚动由合成器线程命中测试，慢机器上浮层的滚动层可能晚一拍才生效，所以滑到真的动了为止。
  await expect(async () => {
    await swipeUp();
    expect(await tip.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  }).toPass({ timeout: 8_000 });
  await expect(async () => {
    if (await remaining() > 1) await swipeUp();
    expect(await remaining()).toBeLessThanOrEqual(1);
  }).toPass({ timeout: 8_000 });
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


for (const locale of ['zh', 'en', 'ja']) {
  const widths = locale === 'en' ? [320, 390, 639, 640, 767, 768, 1440] : [320, 390];
  for (const width of widths) for (const populated of [false, true]) {
    test(`scan history stays in viewport: ${locale} ${width}px ${populated ? 'records' : 'empty'}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.addInitScript(locale => localStorage.setItem('optixjp:locale', locale), locale);
      await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: { mode: 'password', is_owner: false, password_configured: true, account: { logged_in: false, username: null } } }));
      await page.goto('/visual-tests/support/mobile-controls.html?scan-history' + (populated ? '&populated' : ''));
      const trigger = page.locator('button[aria-haspopup=dialog]');
      if (width < 768) expect((await trigger.boundingBox()).height).toBeGreaterThanOrEqual(44);
      await trigger.press('Enter');
      const panel = page.getByRole('dialog');
      await expect.poll(() => panel.evaluate(el => Number(getComputedStyle(el).opacity))).toBe(1);
      await expect.poll(() => panel.evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m11)).toBe(1);
      const box = await panel.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(16);
      expect(box.x + box.width).toBeLessThanOrEqual(width - 16);
      const parent = await trigger.boundingBox();
      if (parent.x + parent.width - box.width >= 16) expect(Math.abs(box.x + box.width - parent.x - parent.width)).toBeLessThan(1);
      expect(Math.abs(box.y - parent.y - parent.height - 8)).toBeLessThan(1);
      if (populated) {
        await expect(panel.locator('li')).toHaveCount(5);
        for (const row of await panel.locator('li').all()) {
          expect((await row.boundingBox()).height).toBeGreaterThanOrEqual(44);
          const layout = await row.evaluate(el => {
            const rect = el.getBoundingClientRect();
            return {
              client: el.clientWidth, scroll: el.scrollWidth,
              blocks: Array.from(el.children, child => {
                const box = child.getBoundingClientRect();
                return { left: box.left - rect.left, right: box.right - rect.left, width: box.width,
                  client: child.clientWidth, scroll: child.scrollWidth };
              }),
            };
          });
          expect(layout.scroll).toBeLessThanOrEqual(layout.client);
          for (const block of layout.blocks) {
            expect(block.width).toBeGreaterThan(0);
            expect(block.left).toBeGreaterThanOrEqual(0);
            expect(block.right).toBeLessThanOrEqual(layout.client);
            expect(block.scroll).toBeLessThanOrEqual(block.client);
          }
        }
        const summary = panel.locator('[data-pointer-tooltip-trigger]').first();
        const completeText = await summary.textContent();
        expect(await summary.locator('span').evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
        await summary.hover();
        const tooltip = page.getByRole('tooltip');
        await expect(tooltip).toHaveText(completeText);
        await expect(tooltip).toBeVisible();
        await expect.poll(() => tooltip.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
        await page.mouse.move(width - 1, 20);
        await expect(tooltip).toHaveCount(0);
      } else {
        await expect(panel.locator('li')).toHaveCount(0);
        await expect(panel).toContainText({zh:'尚无扫描记录',en:'No scans yet',ja:'まだスキャンはありません'}[locale]);
      }
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect(await panel.evaluate(el => el.contains(document.activeElement))).toBe(true);
      await page.keyboard.press('Escape');
      await expect(panel).toHaveCount(0);
      await expect(trigger).toBeFocused();
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      console.log('scan-history geometry', JSON.stringify({locale,width,populated,left:box.x,right:box.x+box.width,triggerHeight:parent.height}));
    });
  }
}

test('open scan history reclamps when the meta row changes across phone and desktop widths', async ({ page }) => {
  await open(page, 'en');
  await page.goto('/visual-tests/support/mobile-controls.html?scan-history&populated');
  await page.locator('button[aria-haspopup=dialog]').click();
  const panel = page.getByRole('dialog');
  for (const width of [320, 390, 640, 768, 1440, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect.poll(async () => { const box = await panel.boundingBox(); return box.x >= 16 && box.x + box.width <= width - 16; }).toBe(true);
    await expect.poll(() => panel.evaluate(el => el.scrollWidth <= el.clientWidth && Array.from(el.querySelectorAll('li')).every(row => row.scrollWidth <= row.clientWidth))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(page.locator('button[aria-haspopup=dialog]')).toBeFocused();
});
