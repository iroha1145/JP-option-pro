import { test, expect } from '@playwright/test';
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
const preview = '/visual-tests/support/feel-gesture-preview.html';
async function open(page) {
  await page.addInitScript(() => localStorage.setItem('optixjp:locale', 'zh'));
  await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: { mode: 'password', is_owner: false, password_configured: true, account: { logged_in: false, username: null } } }));
  await page.goto(preview);
  const trigger = page.getByRole('navigation', { name: '移动端导航' }).getByRole('button', { name: '更多', exact: true });
  await trigger.click();
  const panel = page.getByRole('dialog', { name: '更多功能', exact: true });
  await expect(panel).toHaveAttribute('data-open', 'true');
  await expect.poll(() => panel.evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m42)).toBe(0);
  return { trigger, panel };
}
for (const action of ['Escape', 'handle', 'End', 'backdrop']) test(`real more sheet retains modal focus and scroll lock through ${action} dismissal`, async ({ page }) => {
  const { trigger, panel } = await open(page);
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  await panel.evaluate(el => {
    const capture = window.closeCapture = { unlocked: [], focusEscaped: [], closing: false, removed: false };
    const sample = () => {
      if (!el.isConnected) { capture.removed = true; observer.disconnect(); return; }
      if (el.dataset.open === 'false') capture.closing = true;
      if (document.body.style.overflow !== 'hidden') capture.unlocked.push(el.dataset.open);
    };
    const observer = new MutationObserver(sample);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'data-open'] });
    document.addEventListener('focusin', event => {
      if (el.isConnected && !el.contains(event.target)) capture.focusEscaped.push(event.target.outerHTML);
    });
  });
  if (action === 'Escape') await page.keyboard.press('Escape');
  if (action === 'handle') await panel.locator('[data-handle]').click();
  if (action === 'End') await panel.locator('[data-handle]').press('End');
  if (action === 'backdrop') await page.locator('[data-focus-backdrop]').click({ position: { x: 10, y: 20 } });
  await expect(panel).toHaveCount(0);
  const state = await page.evaluate(() => window.closeCapture);
  expect(state.removed).toBe(true);
  expect(state.closing).toBe(true);
  expect(state.unlocked).toEqual([]);
  expect(state.focusEscaped).toEqual([]);
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  await expect(trigger).toBeFocused();
});

test('real more sheet traps Tab and native touch release closes while preserving scroll cleanup', async ({ page }) => {
  const { panel } = await open(page);
  const buttons = panel.getByRole('button');
  await buttons.last().focus();
  await page.keyboard.press('Tab');
  await expect(buttons.first()).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(buttons.last()).toBeFocused();
  const box = await panel.locator('[data-handle]').boundingBox();
  const session = await page.context().newCDPSession(page);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ id: 1, x, y }] });
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ id: 1, x, y: y + 220 }] });
  await page.waitForTimeout(120);
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect(panel).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
});

test('navigation and guest sign-in retain Japan routes and release modal resources', async ({ page }) => {
  for (const name of ['新闻', '访客只读模式']) {
    const { panel } = await open(page);
    await panel.getByRole('button', { name: new RegExp(name) }).click();
    await expect(page).toHaveURL(name === '新闻' ? /\/news$/ : /\/login$/);
    await expect(panel).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  }
});
