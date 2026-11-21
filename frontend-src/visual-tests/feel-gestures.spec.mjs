import { test, expect } from '@playwright/test';
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
const preview = '/visual-tests/support/feel-gesture-preview.html';
const yOf = page => page.locator('#sheet').evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m42);
async function touch(page) {
  const session = await page.context().newCDPSession(page);
  return async (type, points) => session.send('Input.dispatchTouchEvent', { type, touchPoints: points.map(([id,x,y]) => ({ id,x,y })) });
}
async function expectSheetOpenAfterRelease(page) {
  // A zero close count before the release finishes does not prove its landing.
  await expect.poll(() => page.locator('#sheet').evaluate(el =>
    el.getAnimations().filter(animation => !(animation instanceof CSSTransition)).length)).toBe(0);
  await expect.poll(() => yOf(page)).toBe(0);
  await expect(page.locator('#sheet')).not.toHaveAttribute('data-feel-dismissed');
  await expect(page.locator('#closes')).toHaveText('0');
}
async function releaseToPausedRebound(page) {
  await page.locator('#sheet').evaluate(panel => {
    const capture = window.feelRebound = { status: 'waiting', panel };
    window.addEventListener('pointerup', event => {
      try {
        const handle = panel.querySelector('#handle');
        if (!event.isTrusted || !event.isPrimary || event.button !== 0
          || !(event.target instanceof Node) || !handle.contains(event.target)) {
          throw new Error('Expected the native primary release on the sheet handle');
        }
        // React's release handler has created the real rebound before this
        // same event reaches window. Capture it before any driver round trip.
        const animations = panel.getAnimations().filter(animation =>
          !(animation instanceof CSSTransition) && !(animation instanceof CSSAnimation)
          && animation.effect?.target === panel);
        if (animations.length !== 1) throw new Error('Expected exactly one sheet rebound');
        const animation = capture.animation = animations[0];
        capture.duration = Number(animation.effect.getTiming().duration);
        if (!Number.isFinite(capture.duration) || capture.duration <= 0) {
          throw new Error('Expected a finite running rebound');
        }
        const backdrop = capture.backdrop = document.querySelector('#sheet-backdrop');
        const backdropAnimation = capture.backdropAnimation = backdrop.getAnimations().find(a => a.effect?.target === backdrop);
        if (!backdropAnimation) throw new Error('Expected the matching backdrop trajectory');
        animation.pause();
        backdropAnimation.pause();
        capture.status = 'pausing';
        Promise.all([animation.ready, backdropAnimation.ready]).then(() => {
          if (animation.playState !== 'paused') throw new Error('Rebound did not pause');
          capture.status = 'ready';
        }).catch(error => { capture.status = 'failed'; capture.error = String(error); });
      } catch (error) {
        capture.status = 'failed';
        capture.error = String(error);
      }
    }, { once: true });
  });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => {
    if (window.feelRebound.status === 'failed') throw new Error(window.feelRebound.error);
    return window.feelRebound.status;
  })).toBe('ready');
  return page.evaluate(() => ({ duration: window.feelRebound.duration }));
}
test.beforeEach(async ({page, contextOptions}) => {
  // reducedMotion is a BrowserContext option, not a top-level test fixture.
  // Check the real media query before mounting so mode labels cannot hide an
  // ignored configuration or a preference change arriving during a gesture.
  expect(contextOptions.reducedMotion).toMatch(/^(reduce|no-preference)$/);
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches))
    .toBe(contextOptions.reducedMotion === 'reduce');
  await page.addInitScript(() => localStorage.setItem('optixjp:locale', 'zh'));
  await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: { mode: 'password', is_owner: false, password_configured: true, account: { logged_in: false, username: null } } }));
  await page.goto(preview);
  await expect(page.locator('#handle')).toBeVisible();
});

test('resting before release removes old flick velocity for sheet and switch, including real touch', async ({page}) => {
  const send = await touch(page);
  await send('touchStart', [[1,170,170]]); await send('touchMove', [[1,170,200]]);
  await page.waitForTimeout(120); await send('touchEnd', []);
  await expectSheetOpenAfterRelease(page);
  const box = await page.getByRole('switch').boundingBox(); const x=box.x+box.width/2,y=box.y+box.height/2;
  await send('touchStart', [[1,x,y]]); await send('touchMove', [[1,x+4,y]]);
  await page.waitForTimeout(120); await send('touchEnd', []);
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');
  await page.getByRole('switch').click(); await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');
  await page.getByRole('switch').press('Space'); await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');
  await expect(page.locator('#rows')).toHaveText('0');
});

test.describe('initial reduced motion for final release', () => {
test.use({ contextOptions: { reducedMotion: 'reduce' } });
test('reduced motion uses final release coordinates even with no intermediate move', async ({page}) => {
  await page.locator('#handle').dispatchEvent('pointerdown',{pointerId:7,isPrimary:true,button:0,clientY:170});
  await page.waitForTimeout(120);
  // The closed magnet is at 500px; cross the midpoint instead of relying on
  // the former 110px dismissal threshold.
  await page.locator('#handle').dispatchEvent('pointerup',{pointerId:7,isPrimary:true,button:0,clientY:470});
  await expect(page.locator('#closes')).toHaveText('1');
  await page.getByRole('switch').dispatchEvent('pointerdown',{pointerId:8,isPrimary:true,button:0,clientX:50});
  await page.waitForTimeout(120);
  await page.getByRole('switch').dispatchEvent('pointerup',{pointerId:8,isPrimary:true,button:0,clientX:65});
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');
});
});

for (const reducedMotion of ['no-preference', 'reduce']) {
  test.describe(`initial ${reducedMotion} preference`,()=>{
    // Set this fixed-mode prerequisite before the preview mounts. Changing it
    // after mount can deliver a media event after pointerdown and cancel the drag.
    test.use({ contextOptions: { reducedMotion } });
    test(`switch includes final pointerup displacement with ${reducedMotion}`, async ({ page }) => {
      const toggle = page.getByRole('switch');
      await toggle.dispatchEvent('pointerdown', { pointerId: 8, isPrimary: true, button: 0, clientX: 50 });
      await page.waitForTimeout(120);
      await toggle.dispatchEvent('pointerup', { pointerId: 8, isPrimary: true, button: 0, clientX: 65 });
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      await toggle.dispatchEvent('click', { detail: 1 });
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      await expect(page.locator('#rows')).toHaveText('0');
    });
  });
}

test('changing reduced motion during switch drag cancels release and preserves the next activation',async ({page})=>{
  const toggle=page.getByRole('switch'), box=await toggle.boundingBox();
  await page.mouse.move(box.x+5,box.y+8); await page.mouse.down(); await page.mouse.move(box.x+20,box.y+8);
  await expect(toggle).toHaveAttribute('data-feel-drag','true');
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(toggle).not.toHaveAttribute('data-feel-drag');
  await page.mouse.up();
  await expect(toggle).toHaveAttribute('aria-checked','false');
  await toggle.press('Space');
  await expect(toggle).toHaveAttribute('aria-checked','true');
  await expect(page.locator('#rows')).toHaveText('0');
});

test('a new drag cancels rebound and its stale finish cannot clear current position', async ({page}) => {
  await page.mouse.move(170,170); await page.mouse.down(); await page.mouse.move(170,210); await page.waitForTimeout(120);
  const rebound = await releaseToPausedRebound(page);
  // Even a driver arriving after the original duration must retain the rebound.
  await page.waitForTimeout(rebound.duration + 100);
  expect(await page.evaluate(() => window.feelRebound.animation.playState)).toBe('paused');
  const box=await page.locator('#handle').boundingBox();
  await page.locator('#handle').evaluate(handle => {
    handle.addEventListener('pointerdown', () => {
      window.feelRebound.animation.play();
      window.feelRebound.stateAtGrab = window.feelRebound.animation.playState;
    }, { capture: true, once: true });
  });
  await page.mouse.move(170,box.y+20); await page.mouse.down();
  expect(await page.evaluate(() => ({
    before: window.feelRebound.stateAtGrab, after: window.feelRebound.animation.playState,
  }))).toEqual({ before: 'running', after: 'idle' });
  await page.mouse.move(170,box.y+50);
  // A hand spring follows the held pointer instead of teleporting to it.
  // Let it settle, then wait past the cancelled animation's original finish.
  await page.waitForTimeout(600);
  const held=await yOf(page); expect(held).toBeGreaterThan(20);
  await page.waitForTimeout(Math.max(250, rebound.duration + 100 - 600));
  expect(Math.abs(await yOf(page)-held)).toBeLessThan(1);
  await page.mouse.up(); await expectSheetOpenAfterRelease(page);
});

test('secondary touch cannot replace or end primary drag', async ({page}) => {
  const send=await touch(page);
  await send('touchStart',[[1,120,170]]); await send('touchMove',[[1,120,200]]);
  await page.waitForTimeout(600);
  const held = await yOf(page);
  expect(held).toBeGreaterThan(20);
  expect(held).toBeLessThan(35);
  await send('touchStart',[[1,120,200],[2,220,200]]);
  await send('touchMove',[[1,120,200],[2,220,350]]);
  expect(Math.abs(await yOf(page)-held)).toBeLessThan(1);
  // CDP touchEnd lists contacts to release, unlike touchMove's active contacts.
  await send('touchEnd',[[2,220,350]]);
  expect(Math.abs(await yOf(page)-held)).toBeLessThan(1);
  await page.waitForTimeout(120); await send('touchEnd',[]);
  await expectSheetOpenAfterRelease(page);
});

for (const action of ['close','unmount']) test(`external ${action} cancels active rebound`,async ({page})=>{
  await page.mouse.move(170,170); await page.mouse.down(); await page.mouse.move(170,210); await page.waitForTimeout(120);
  await releaseToPausedRebound(page);
  await page.evaluate(action=>window.gestureControls[action](),action);
  // The controls request a React update; observe its commit before inspecting
  // the layout-effect cleanup rather than racing another driver round trip.
  if (action === 'unmount') await expect(page.locator('#sheet')).toHaveCount(0);
  else await expect(page.locator('#sheet')).toHaveAttribute('data-enabled','false');
  expect(await page.evaluate(()=>window.feelRebound.animation.playState)).toBe('idle');
  expect(await page.evaluate(()=>window.feelRebound.panel.getAnimations().filter(a=>!(a instanceof CSSTransition)).length)).toBe(0);
  expect(await page.evaluate(()=>window.feelRebound.panel.style.transform)).toBe('');
  expect(await page.evaluate(()=>window.feelRebound.backdropAnimation.playState)).toBe('idle');
  expect(await page.evaluate(()=>window.feelRebound.backdrop.getAnimations().length)).toBe(0);
  expect(await page.evaluate(()=>window.feelRebound.backdrop.style.opacity)).toBe('');
});

test('cancel, lost capture, blur and disabling discard a gesture',async ({page})=>{
  for(const event of ['pointercancel','lostpointercapture']) {
    await page.mouse.move(170,170); await page.mouse.down(); await page.mouse.move(170,220);
    await page.locator('#handle').dispatchEvent(event,{pointerId:1});
    await expect.poll(()=>yOf(page)).toBe(0); await page.mouse.up();
  }
  await page.mouse.move(170,170);await page.mouse.down();await page.mouse.move(170,220);
  await page.evaluate(()=>window.dispatchEvent(new Event('blur'))); await expect.poll(()=>yOf(page)).toBe(0);await page.mouse.up();
  const box=await page.getByRole('switch').boundingBox();await page.mouse.move(box.x+5,box.y+5);await page.mouse.down();await page.mouse.move(box.x+20,box.y+5);
  await page.evaluate(()=>window.gestureControls.disable());
  await expect(page.getByRole('switch')).not.toHaveAttribute('data-feel-drag'); await page.mouse.up();
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');await expect(page.locator('#closes')).toHaveText('0');
});

test.describe('initial reduced motion for touch dragging', () => {
test.use({ contextOptions: { reducedMotion: 'reduce' } });
test('reduced motion preserves functional touch dragging with instant return',async ({page})=>{
  const send=await touch(page);
  await send('touchStart',[[1,170,170]]);await send('touchMove',[[1,170,200]]);await page.waitForTimeout(120);await send('touchEnd',[]);
  expect(await yOf(page)).toBe(0);expect(await page.locator('#sheet').evaluate(el=>el.getAnimations().length)).toBe(0);
  const box=await page.getByRole('switch').boundingBox();const x=box.x+5,y=box.y+8;
  await send('touchStart',[[1,x,y]]);await send('touchMove',[[1,x+14,y]]);await page.waitForTimeout(120);await send('touchEnd',[]);
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');
  expect(await page.getByRole('switch').evaluate(el=>getComputedStyle(el).touchAction)).toBe('pan-y');
  await send('touchStart',[[1,170,170]]);await send('touchMove',[[1,170,470]]);await page.waitForTimeout(120);await send('touchEnd',[]);
  await expect(page.locator('#closes')).toHaveText('1');
});
});

test('vertical touch starting on switch still scrolls without toggling',async ({page})=>{
  await page.evaluate(async () => {
    document.body.style.minHeight = '1800px';
    document.querySelector('#sheet').style.display = 'none';
    document.querySelector('[role="switch"]').parentElement.style.marginTop = '200px';
    window.scrollTo(0, 0);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const box = await page.getByRole('switch').boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  // 逐个触点事件拖动。Input.synthesizeScrollGesture 在 CI 的 Linux 上一次都滚不动，
  // 本文件其余用触点事件的用例在同一套 CI 上是通过的。
  const send = await touch(page);
  await expect(async () => {
    await send('touchStart', [[1, x, y]]);
    for (const travel of [20, 40, 60, 80]) await send('touchMove', [[1, x, y - travel]]);
    await send('touchEnd', []);
    expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0);
  }).toPass({ timeout: 8_000 });
  await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');
  await expect(page.getByRole('switch')).not.toHaveAttribute('data-feel-drag');
});

test('cancelled switch drag discards its click but preserves next keyboard activation',async ({page})=>{
  const toggle=page.getByRole('switch');
  await toggle.dispatchEvent('pointerdown',{pointerId:9,isPrimary:true,button:0,clientX:50});
  await toggle.dispatchEvent('pointermove',{pointerId:9,isPrimary:true,button:0,clientX:64});
  await toggle.dispatchEvent('lostpointercapture',{pointerId:9,isPrimary:true,clientX:64});
  await toggle.dispatchEvent('click',{detail:1});
  await expect(toggle).toHaveAttribute('aria-checked','false');
  await toggle.press('Space');
  await expect(toggle).toHaveAttribute('aria-checked','true');
  await expect(page.locator('#rows')).toHaveText('0');
});


test('orthogonal moves cannot keep an old sheet flick alive', async ({page}) => {
  const send = await touch(page);
  await send('touchStart', [[1,120,170]]);
  await send('touchMove', [[1,120,200]]);
  for (let step=1;step<=12;step++) {
    await page.waitForTimeout(15);
    await send('touchMove', [[1,120+step*5,200]]);
  }
  await send('touchEnd', []);
  await expectSheetOpenAfterRelease(page);
});

test('holding a regrabbed sheet dissipates its old momentum before another move', async ({ page }) => {
  await page.mouse.move(170, 170);
  await page.mouse.down();
  await page.mouse.move(170, 210);
  await page.waitForTimeout(120);
  await releaseToPausedRebound(page);
  await page.evaluate(() => {
    const animation = window.feelRebound.animation;
    if (window.feelRebound.duration <= 80) throw new Error('Expected an in-flight rebound at 80ms');
    animation.currentTime = 80;
  });
  const handle = await page.locator('#handle').boundingBox();
  const x = handle.x + handle.width / 2, y = handle.y + handle.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  expect(await page.evaluate(() => window.feelRebound.animation.playState)).toBe('idle');
  await page.waitForTimeout(600);
  const held = await yOf(page);
  await page.mouse.move(x, y + 4);
  await page.waitForTimeout(50);
  expect(Math.abs(await yOf(page) - held)).toBeLessThan(10);
  await page.mouse.up();
  await expectSheetOpenAfterRelease(page);
});

test('sheet keyboard and handle activation reach the physical closed stop once', async ({ page }) => {
  const handle = page.getByRole('button', { name: '拖动', exact: true });
  await handle.press('ArrowUp');
  await expect(page.locator('#closes')).toHaveText('0');
  await handle.press('End');
  await expect(page.locator('#closes')).toHaveText('1');
  await expect(page.locator('#sheet')).toHaveAttribute('data-feel-dismissed', 'true');
  expect(await page.locator('#sheet').evaluate(element => element.getAnimations().length)).toBe(0);
});

test('changing reduced motion during release stops the compositor and keeps the open stop', async ({ page }) => {
  await page.mouse.move(170, 170);
  await page.mouse.down();
  await page.mouse.move(170, 200);
  await page.waitForTimeout(180);
  const rebound = await releaseToPausedRebound(page);
  await page.waitForTimeout(rebound.duration + 100);
  expect(await page.evaluate(() => window.feelRebound.animation.playState)).toBe('paused');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect.poll(() => page.evaluate(() => window.feelRebound.animation.playState)).toBe('idle');
  await expectSheetOpenAfterRelease(page);
});

test('switch physical dragging, arrows and repeated activation preserve one semantic change', async ({ page }) => {
  const toggle = page.getByRole('switch');
  const box = await toggle.boundingBox();
  await page.mouse.move(box.x + 5, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 19, box.y + box.height / 2, { steps: 4 });
  await page.waitForTimeout(250);
  await page.mouse.up();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('#rows')).toHaveText('0');
  await toggle.press('ArrowLeft');
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await toggle.press('ArrowRight');
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.press('Enter');
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
});

test('regrabbing interpolates the compositor position rather than wall clock time', async ({page}) => {
  await page.mouse.move(170,170);await page.mouse.down();await page.mouse.move(170,210);await page.waitForTimeout(120);
  await releaseToPausedRebound(page);
  const positions = await page.locator('#sheet').evaluate(el => {
    const animation=window.feelRebound.animation;
    if (animation.effect.target !== el || animation.playState !== 'paused' || window.feelRebound.duration <= 55.25) {
      throw new Error('Expected the saved rebound to provide an in-flight frame');
    }
    animation.currentTime=55.25;
    const before=new DOMMatrix(getComputedStyle(el).transform).m42;
    el.querySelector('#handle').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:9,isPrimary:true,button:0,clientY:170}));
    return {before,after:new DOMMatrix(getComputedStyle(el).transform).m42,cancelled:animation.playState};
  });
  expect(positions.cancelled).toBe('idle');
  expect(Math.abs(positions.before-positions.after)).toBeLessThan(0.05);
});


for (const component of ['MobileDock']) for (const clock of component === 'MobileDock' ? ['paused', 'live'] : ['paused']) test(`${component} ${clock} entrance transfers its painted position to a real pointer grab`, async ({page}) => {
  if (component === 'MobileDock') await page.goto(preview);
  const label = '更多功能';
  const panel=page.getByRole('dialog',{name:label,exact:true});
  // Arm observation before the native click. Waiting until the driver sees the
  // mounted panel can miss MobileDock's entire 240ms entrance on a slow runner.
  await page.evaluate(label=>{
    const capture=window.feelEntrance={status:'waiting'};
    const onRun=event=>{
      const el=event.target;
      if (!(el instanceof HTMLElement) || !el.matches('[data-feel-sheet][role="dialog"]')
        || el.getAttribute('aria-label')!==label || event.propertyName!=='transform' || event.pseudoElement) return;
      document.removeEventListener('transitionrun',onRun,true);
      const animation=el.getAnimations().find(a=>a instanceof CSSTransition
        && a.transitionProperty==='transform' && a.effect?.target===el);
      if (!animation) { capture.status='failed'; capture.error='No real entrance transition at transitionrun'; return; }
      capture.animation=animation;
      capture.trusted=event.isTrusted;
      capture.status='pausing';
      // Pause the actual transition in its start event, then wait for the
      // pending pause before selecting the in-flight frame used by the grab.
      animation.pause();
      animation.ready.then(()=>{
        if (animation.playState!=='paused' || Number(animation.effect.getTiming().duration)<=60) {
          throw new Error('Entrance transition cannot provide a paused in-flight frame');
        }
        animation.currentTime=60;
        capture.status='ready';
      }).catch(error=>{ capture.status='failed'; capture.error=String(error); });
    };
    document.addEventListener('transitionrun',onRun,true);
  },label);
  if (component === 'MobileDock') {
    await page.getByRole('navigation', {name:'移动端导航',exact:true}).getByRole('button',{name:'更多',exact:true}).click();
  }
  // Deliberately arrive after MobileDock's normal entrance would have ended.
  await page.waitForTimeout(350);
  await expect.poll(()=>page.evaluate(()=>{
    if (window.feelEntrance.status==='failed') throw new Error(window.feelEntrance.error);
    return window.feelEntrance.status;
  })).toBe('ready');
  await panel.waitFor({state:'visible'});
  await panel.evaluate((el, clock) => {
    const {animation,trusted}=window.feelEntrance;
    if (!trusted || animation.effect.target!==el || animation.playState!=='paused') {
      throw new Error('Expected the captured native entrance for this panel');
    }
    const handle=el.querySelector('[data-handle]');
    handle.addEventListener('pointerdown',event=>{
      // Capture runs before React's product handler. Resume this same entrance
      // at normal speed so that handler must take ownership of a live animation.
      if (clock === 'live') animation.play();
      el.dataset.entryGrab=JSON.stringify({
        trusted:event.isTrusted,
        hit:handle.contains(event.target),
        state:animation.playState,
        remaining:Number(animation.effect.getTiming().duration)-Number(animation.currentTime),
        playbackRate:animation.playbackRate,
      });
      el.dataset.beforeGrab=String(new DOMMatrix(getComputedStyle(el).transform).m42);
      // React handles the grab at its root before this native event reaches
      // window. Sample computed style in the same event, before the first
      // physical frame; a later driver round trip may see valid spring motion.
      window.addEventListener('pointerdown',afterEvent=>{
        el.dataset.afterGrab=JSON.stringify({
          sameEvent:afterEvent===event,
          handled:el.style.transition==='none',
          y:new DOMMatrix(getComputedStyle(el).transform).m42,
        });
      },{once:true});
    },{capture:true,once:true});
  }, clock);
  const box=await panel.locator('[data-handle]').boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  // Exercise a delayed driver without requiring it to chase a moving 30px target.
  if (clock === 'live') await page.waitForTimeout(300);
  await page.mouse.down();
  // A delayed driver must still compare the two event-time snapshots.
  await page.waitForTimeout(100);
  const grab=await panel.evaluate(el=>({
    event:JSON.parse(el.dataset.entryGrab ?? '{}'),
    before:Number(el.dataset.beforeGrab),
    after:JSON.parse(el.dataset.afterGrab ?? '{}'),
  }));
  expect(grab.event, 'the native pointer must reach the actual handle').toMatchObject({
    trusted:true,hit:true,state:clock === 'live' ? 'running' : 'paused',playbackRate:1,
  });
  expect(grab.event.remaining).toBeGreaterThan(0);
  expect(grab.before).toBeGreaterThan(0.2);
  expect(grab.after).toMatchObject({sameEvent:true,handled:true});
  expect(Math.abs(grab.before-grab.after.y)).toBeLessThan(0.05);
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2+20);
  await expect.poll(()=>panel.evaluate(el=>new DOMMatrix(getComputedStyle(el).transform).m42)).toBeGreaterThan(grab.after.y+5);
  await page.waitForTimeout(600);
  const held=await panel.evaluate(el=>new DOMMatrix(getComputedStyle(el).transform).m42);
  expect(held).toBeLessThan(grab.after.y+25);
  await page.waitForTimeout(250);
  expect(Math.abs(await panel.evaluate(el=>new DOMMatrix(getComputedStyle(el).transform).m42)-held)).toBeLessThan(1);
  await page.mouse.up();
  if (component === 'MobileDock') {
    await panel.evaluate(el => {
      if (el.dataset.open !== 'true' || document.body.style.overflow !== 'hidden') {
        throw new Error('Expected an open, scroll-locked sheet before Escape');
      }
      const capture = window.feelExit = { closing: null, removed: false, unlockedWhileMounted: [] };
      const observer = new MutationObserver(() => {
        if (!el.isConnected) {
          capture.removed = true;
          observer.disconnect();
          return;
        }
        const sample = { connected: true, open: el.dataset.open, overflow: document.body.style.overflow };
        if (sample.open === 'false' && !capture.closing) capture.closing = sample;
        if (sample.overflow !== 'hidden') capture.unlockedWhileMounted.push(sample);
      });
      observer.observe(el, { attributes: true, attributeFilter: ['data-open'] });
      observer.observe(document.body, { attributes: true, attributeFilter: ['style'] });
      observer.observe(el.parentNode, { childList: true });
    });
  }
  await page.keyboard.press('Escape');
  if (component === 'MobileDock') {
    // The driver may arrive after the 160ms exit. Keep observing in the page
    // through actual removal, including passive-effect scroll-lock cleanup.
    await page.waitForTimeout(350);
    await expect.poll(() => page.evaluate(() => window.feelExit.removed)).toBe(true);
    const exit = await page.evaluate(() => window.feelExit);
    expect(exit.closing).toEqual({ connected: true, open: 'false', overflow: 'hidden' });
    expect(exit.unlockedWhileMounted).toEqual([]);
  }
  await expect(panel).toHaveCount(0);
  await expect.poll(() => page.evaluate(()=>document.body.style.overflow)).not.toBe('hidden');
});


test('blur during switch drag suppresses the native release click', async ({page}) => {
  const toggle=page.getByRole('switch');const box=await toggle.boundingBox();
  await page.mouse.move(box.x+5,box.y+8);await page.mouse.down();await page.mouse.move(box.x+20,box.y+8);
  await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
  await page.mouse.up();
  await expect(toggle).toHaveAttribute('aria-checked','false');
  await toggle.press('Space');await expect(toggle).toHaveAttribute('aria-checked','true');
});


for (const component of ['MobileDock']) test(`${component} external close preserves the held sheet position`, async ({ page }) => {
  if (component === 'MobileDock') {
    await page.goto(preview);
    await page.getByRole('navigation', { name: '移动端导航', exact: true }).getByRole('button', { name: '更多', exact: true }).click();
  }
  const panel = page.getByRole('dialog', { name: '更多功能', exact: true });
  await expect.poll(() => panel.evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m42)).toBe(0);
  const handle = await panel.locator('[data-handle]').boundingBox();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2 + 100, { steps: 4 });
  await expect.poll(() => panel.evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m42)).toBeGreaterThan(60);
  await panel.evaluate(el => {
    const capture = window.feelExternalClose = { before: null, after: null, unlocked: [] };
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') capture.before = new DOMMatrix(getComputedStyle(el).transform).m42;
    }, { capture: true, once: true });
    const animate = el.animate;
    el.animate = function (frames, options) {
      capture.firstExitY = new DOMMatrix(frames[0].transform).m42;
      return animate.call(this, frames, options);
    };
    const observer = new MutationObserver(() => {
      if (!el.isConnected) { observer.disconnect(); return; }
      if (el.dataset.open === 'false' && capture.after === null) capture.after = new DOMMatrix(getComputedStyle(el).transform).m42;
      if (document.body.style.overflow !== 'hidden') capture.unlocked.push(el.dataset.open);
    });
    observer.observe(el, { attributes: true, attributeFilter: ['data-open', 'style'] });
    observer.observe(document.body, { attributes: true, attributeFilter: ['style'], childList: true, subtree: true });
  });
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => window.feelExternalClose.after)).not.toBeNull();
  const state = await page.evaluate(() => window.feelExternalClose);
  expect(state.before).toBeGreaterThan(60);
  expect(Math.abs(state.before - state.firstExitY)).toBeLessThan(1);
  expect(state.after).toBeGreaterThan(state.before);
  await page.mouse.up();
  await expect(panel).toHaveCount(0);
  expect(await page.evaluate(() => window.feelExternalClose.unlocked)).toEqual([]);
});

async function sheetAndBackdrop(page) {
  return page.locator('#sheet').evaluate(panel => ({
    y: new DOMMatrix(getComputedStyle(panel).transform).m42,
    height: panel.offsetHeight,
    opacity: Number(getComputedStyle(document.querySelector('#sheet-backdrop')).opacity),
  }));
}
function expectCoupled(state) {
  expect(Math.abs(state.opacity - (1 - Math.max(0, Math.min(1, state.y / state.height))))).toBeLessThan(0.003);
}

test('backdrop follows held displacement, the rebound trajectory and a new grab', async ({ page }) => {
  await page.mouse.move(170, 170);
  await page.mouse.down();
  await page.mouse.move(170, 340, { steps: 5 });
  await page.waitForTimeout(180);
  const held = await sheetAndBackdrop(page);
  expect(held.y).toBeGreaterThan(100);
  expect(held.opacity).toBeLessThan(0.8);
  expectCoupled(held);
  await releaseToPausedRebound(page);
  const timing = await page.evaluate(() => {
    const { animation, backdropAnimation } = window.feelRebound;
    return { panel: animation.effect.getTiming().duration, backdrop: backdropAnimation.effect.getTiming().duration };
  });
  expect(timing.panel).toBe(timing.backdrop);
  const frames = await page.evaluate(() => {
    const { animation, backdropAnimation, panel, backdrop, duration } = window.feelRebound;
    return [0.1, 0.45, 0.8].map(fraction => {
      animation.currentTime = backdropAnimation.currentTime = duration * fraction;
      return { y: new DOMMatrix(getComputedStyle(panel).transform).m42, height: panel.offsetHeight, opacity: Number(getComputedStyle(backdrop).opacity) };
    });
  });
  frames.forEach(expectCoupled);
  expect(frames.at(-1).opacity).toBeGreaterThan(frames[0].opacity);
  await page.evaluate(() => {
    const { animation, backdropAnimation, duration } = window.feelRebound;
    animation.currentTime = backdropAnimation.currentTime = duration * 0.1;
  });
  const before = await sheetAndBackdrop(page);
  const box = await page.locator('#handle').boundingBox();
  await page.locator('#handle').evaluate(handle => {
    handle.addEventListener('pointerdown', () => {
      window.addEventListener('pointerdown', () => {
        const { panel, backdrop } = window.feelRebound;
        window.feelGrabBackdrop = { y: new DOMMatrix(getComputedStyle(panel).transform).m42, height: panel.offsetHeight, opacity: Number(getComputedStyle(backdrop).opacity) };
      }, { once: true });
    }, { once: true, capture: true });
  });
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  const grabbed = await page.evaluate(() => window.feelGrabBackdrop);
  expect(Math.abs(grabbed.y - before.y)).toBeLessThan(0.05);
  expect(Math.abs(grabbed.opacity - before.opacity)).toBeLessThan(0.003);
  expectCoupled(grabbed);
  expect(await page.evaluate(() => window.feelRebound.backdropAnimation.playState)).toBe('idle');
  await page.locator('#handle').dispatchEvent('pointercancel', { pointerId: 1 });
  await page.mouse.up();
  // Observe the completed reset, including the production CSS return, rather
  // than racing it with another driver round trip. A false close fails here.
  await expectSheetOpenAfterRelease(page);
  expectCoupled(await sheetAndBackdrop(page));
  expect((await sheetAndBackdrop(page)).opacity).toBe(1);
});

for (const height of [240, 347, 400, 788]) test(`handle command closes a ${height}px sheet promptly with its backdrop`, async ({ page }) => {
  await page.locator('#sheet').evaluate((panel, height) => {
    panel.style.height = `${height}px`;
    window.addEventListener('click', event => {
      if (!event.isTrusted || !panel.querySelector('#handle').contains(event.target)) throw new Error('Expected trusted handle activation');
      const backdrop = document.querySelector('#sheet-backdrop');
      const animation = panel.getAnimations().find(a => !(a instanceof CSSTransition) && a.effect?.target === panel);
      const backdropAnimation = backdrop.getAnimations().find(a => a.effect?.target === backdrop);
      if (!animation || !backdropAnimation) throw new Error('Expected paired physical exit effects');
      const capture = window.feelCommand = { panel, backdrop, animation, backdropAnimation, ready: false, duration: Number(animation.effect.getTiming().duration) };
      animation.pause(); backdropAnimation.pause();
      Promise.all([animation.ready, backdropAnimation.ready]).then(() => { capture.ready = true; });
    }, { once: true });
  }, height);
  await page.locator('#handle').press('Enter');
  await expect.poll(() => page.evaluate(() => window.feelCommand?.ready)).toBe(true);
  const sample = await page.evaluate(() => {
    const { panel, backdrop, animation, backdropAnimation, duration } = window.feelCommand;
    animation.currentTime = backdropAnimation.currentTime = 200;
    return { y: new DOMMatrix(getComputedStyle(panel).transform).m42, height: panel.offsetHeight, opacity: Number(getComputedStyle(backdrop).opacity), duration };
  });
  expect(sample.y).toBeGreaterThan(height * 0.95);
  expect(sample.duration).toBeLessThan(650);
  expectCoupled(sample);
  await page.evaluate(() => {
    const { animation, backdropAnimation } = window.feelCommand;
    backdropAnimation.finish(); animation.finish();
  });
  await expect(page.locator('#closes')).toHaveText('1');
  expect((await sheetAndBackdrop(page)).opacity).toBe(0);
  expect(await page.locator('#sheet-backdrop').evaluate(el => el.getAnimations().length)).toBe(0);
});

for (const interrupt of ['pointercancel', 'resize', 'reduced']) test(`${interrupt} restores the sheet and backdrop together`, async ({ page }) => {
  await page.mouse.move(170, 170); await page.mouse.down();
  await page.mouse.move(170, 290, { steps: 4 });
  await page.waitForTimeout(180);
  expect((await sheetAndBackdrop(page)).opacity).toBeLessThan(0.9);
  if (interrupt === 'pointercancel') {
    await page.locator('#handle').dispatchEvent('pointercancel', { pointerId: 1 });
    await page.mouse.up();
  } else {
    await releaseToPausedRebound(page);
    if (interrupt === 'resize') await page.evaluate(() => window.dispatchEvent(new Event('resize')));
    else await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect.poll(() => page.evaluate(() => window.feelRebound.backdropAnimation.playState)).toBe('idle');
  }
  await expectSheetOpenAfterRelease(page);
  const state = await sheetAndBackdrop(page);
  expect(state.opacity).toBe(1);
  expectCoupled(state);
  expect(await page.locator('#sheet-backdrop').evaluate(el => ({ opacity: el.style.opacity, transition: el.style.transition, animations: el.getAnimations().length })))
    .toEqual({ opacity: '', transition: '', animations: 0 });
});


for (const activation of ['click', 'Enter']) test(`cancelled stationary regrab keeps the next ${activation} activation available`, async ({ page }) => {
  await page.mouse.move(170, 170); await page.mouse.down();
  await page.mouse.move(170, 250, { steps: 3 });
  await page.waitForTimeout(180);
  await releaseToPausedRebound(page);
  const box = await page.locator('#handle').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  // No move follows this second grab: cancellation itself must suppress the
  // release click, independently of the drag-distance threshold.
  await page.locator('#handle').dispatchEvent('pointercancel', { pointerId: 1 });
  await page.mouse.up();
  await expectSheetOpenAfterRelease(page);
  if (activation === 'click') await page.locator('#handle').click();
  else await page.locator('#handle').press('Enter');
  await expect(page.locator('#closes')).toHaveText('1');
  await expect(page.locator('#sheet')).toHaveAttribute('data-feel-dismissed', 'true');
});

test('stationary rebound regrab releases at the same coordinates without becoming a handle click', async ({ page }) => {
  await page.mouse.move(170, 170);
  await page.mouse.down();
  await page.mouse.move(170, 250, { steps: 3 });
  await page.waitForTimeout(180);
  await releaseToPausedRebound(page);
  const box = await page.locator('#handle').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(180);
  await page.mouse.up();
  await expectSheetOpenAfterRelease(page);
  await page.locator('#handle').press('Enter');
  await expect(page.locator('#closes')).toHaveText('1');
});
