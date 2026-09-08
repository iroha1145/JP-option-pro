/**
 * Real React interaction regressions. Run with Playwright CLI, against a local
 * fixture API that already serves the production frontend, using:
 *   playwright-cli run-code --filename frontend-src/tests/screener-browser.mjs
 * The current page must belong to the fixture origin. Responses are derived
 * from that API; only scheduling/identity/publication scenarios are replaced.
 * Read window.__screenerBrowserResults afterward. No vendor calls are needed.
 */
/* global document, location, window, Event */
// Invoked by Playwright CLI's run-code loader, not by the JavaScript module loader.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function screenerBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  const source = await (await page.request.get(`${origin}/api/strength/scan?top=20`)).json();
  if (!source.publication_id || !source.rows.length) throw new Error('A populated fixture publication is required');
  const results = [];
  const pause = (ms = 80) => page.waitForTimeout(ms);
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const waitUntil = async (predicate, message) => {
    for (let i = 0; i < 100; i += 1) {
      if (await predicate()) return;
      await pause(40);
    }
    throw new Error(message);
  };
  const publication = (id, count) => ({
    ...source, publication_id: id, matched_count: count,
    rows: source.rows.slice(0, 1).map(row => ({...row, name_ja: `验证发布 ${id}`})),
  });
  const countText = () => page.getByRole('heading', {level:2}).allTextContents();
  const hasCount = async count => (await countText()).some(text => text.includes(`命中 ${count} 只`));
  const enterAfterIdentity = async () => {
    await page.goto(`${origin}/`);
    await page.getByRole('button', {name:'退出 admin', exact:true}).waitFor();
    await page.getByRole('navigation', {name:'主导航'}).getByRole('link', {name:'筛选', exact:true}).click();
  };
  const action = (outcome, id = 'P2', status = 'completed') => ({
    status, result:{outcome,radar:{publication:{publication_id:id,trade_date:source.trade_date,score_version:source.stored_score_version}}},
  });
  const routeAction = async (value, held = null) => {
    await page.route('**/api/worker/actions/post_close_batch', route => route.fulfill({status:202,json:{action_id:9001,status:'queued'}}));
    await page.route('**/api/worker/actions/9001', async route => {
      if (held) await held;
      await route.fulfill({json:value});
    });
  };
  const statusHas = async text => (await page.getByTestId('screener-refresh-status').textContent())?.includes(text);
  const test = async (name, run) => {
    try {
      await page.unrouteAll({behavior:'ignoreErrors'});
      await run();
      await page.screenshot({path:`output/pr17-finalize/browser-${results.length + 1}.png`});
      results.push({name,passed:true});
    } catch (error) {
      results.push({name,passed:false,error:String(error)});
    }
  };
  await page.setViewportSize({width:1440,height:1000});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.context().tracing.start({screenshots:true,snapshots:true,sources:true});

  await test('identity resolution cannot strand the initial scan', async () => {
    let release;
    let releaseIdentity;
    let requests = 0;
    const held = new Promise(resolve => { release = resolve; });
    const identityHeld = new Promise(resolve => { releaseIdentity = resolve; });
    await page.route('**/api/access/status', async route => {
      await identityHeld;
      await route.fulfill({json:{mode:'private_network',is_owner:true,password_configured:false,account:{logged_in:false,username:null}}});
    });
    await page.route('**/api/strength/scan?*', async route => {
      requests += 1;
      if (requests === 1) await held;
      await route.fulfill({json:publication('P1',11)});
    });
    await page.goto(`${origin}/screener`);
    await page.getByRole('heading', {name:'选股扫描',exact:true}).waitFor();
    await pause(120);
    releaseIdentity();
    await page.getByTestId('screener-owner-refresh').waitFor();
    await waitUntil(() => requests > 0, 'initial scan was not requested');
    await pause(100);
    release();
    await waitUntil(() => hasCount(11), 'identity changed while initial scan was pending; result never rendered');
    check(!(await page.getByTestId('screener-reread').isDisabled()), 'reread remains disabled');
  });

  await test('a silent old response cannot overwrite an owner publication', async () => {
    let requests = 0;
    let release;
    const held = new Promise(resolve => { release = resolve; });
    await page.route('**/api/strength/scan?*', async route => {
      const request = ++requests;
      if (request === 2) await held;
      await route.fulfill({json:publication(request === 3 ? 'P2' : 'P1', request === 3 ? 22 : 11)});
    });
    await page.route('**/api/worker/actions/post_close_batch', route => route.fulfill({status:202,json:{action_id:9001,status:'queued'}}));
    await page.route('**/api/worker/actions/9001', route => route.fulfill({json:{status:'completed',result:{outcome:'published',radar:{publication:{publication_id:'P2',trade_date:source.trade_date,score_version:source.stored_score_version}}}}}));
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await waitUntil(() => requests === 2, 'silent request did not start');
    await page.getByTestId('screener-owner-refresh').click();
    await waitUntil(() => hasCount(22), 'owner readback did not render P2');
    release();
    await pause(300);
    check(await hasCount(22), 'late silent P1 replaced verified owner P2');
  });

  await test('a silent read started during the worker cannot overwrite its readback', async () => {
    let requests = 0;
    let releaseAction;
    let releaseSilent;
    const actionHeld = new Promise(resolve => { releaseAction = resolve; });
    const silentHeld = new Promise(resolve => { releaseSilent = resolve; });
    await page.route('**/api/strength/scan?*', async route => {
      const request = ++requests;
      if (request === 2) await silentHeld;
      await route.fulfill({json:publication(request === 3 ? 'P2' : 'P1',request === 3 ? 22 : 11)});
    });
    await routeAction(action('published'), actionHeld);
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await waitUntil(() => requests === 2, 'silent request did not start during worker');
    releaseAction();
    await waitUntil(() => hasCount(22), 'owner publication P2 is missing');
    releaseSilent();
    await pause(250);
    check(await hasCount(22), 'silent read begun during worker replaced its verified result');
  });

  await test('a silent read cannot overwrite a newer explicit reread', async () => {
    let requests = 0;
    let releaseQuery;
    let releaseSilent;
    const queryHeld = new Promise(resolve => { releaseQuery = resolve; });
    const silentHeld = new Promise(resolve => { releaseSilent = resolve; });
    await page.route('**/api/strength/scan?*', async route => {
      const request = ++requests;
      if (request === 2) await queryHeld;
      if (request === 3) await silentHeld;
      await route.fulfill({json:publication(request === 2 ? 'P2' : 'P1',request === 2 ? 22 : 11)});
    });
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-reread').click();
    await waitUntil(() => requests === 2, 'explicit request did not start');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await waitUntil(() => requests === 3, 'silent request did not start');
    releaseQuery();
    await waitUntil(() => hasCount(22), 'explicit P2 is missing');
    releaseSilent();
    await pause(250);
    check(await hasCount(22), 'silent P1 replaced explicit P2');
  });

  await test('a mismatched publication is not reported as updated', async () => {
    await page.route('**/api/strength/scan?*', route => route.fulfill({json:publication('P1',11)}));
    await routeAction(action('published'));
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await page.getByTestId('screener-refresh-status').waitFor();
    await waitUntil(() => statusHas('读回发布与任务承诺不一致'), 'mismatch was not reported');
    check(await hasCount(11), 'mismatch discarded the previous result');
  });

  await test('already_current with stale data is not reported as latest', async () => {
    await page.route('**/api/strength/scan?*', route => route.fulfill({json:{...publication('P1',11),freshness:'stale'}}));
    await routeAction(action('already_current','P1'));
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await page.getByTestId('screener-refresh-status').waitFor();
    await waitUntil(() => statusHas('快照日期早于'), 'stale already_current was not distinguished');
    check(!(await statusHas('已是最新可用日线')), 'stale data was labelled latest');
  });

  for (const [outcome,status,message] of [
    ['waiting_input','completed','仍在等待供应商发布当日日线'],
    ['failed','failed','更新失败，已保留上次结果'],
  ]) {
    await test(`${outcome} retains results without claiming success`, async () => {
      await page.route('**/api/strength/scan?*', route => route.fulfill({json:publication('P1',11)}));
      await routeAction(action(outcome,'P1',status));
      await enterAfterIdentity();
      await waitUntil(() => hasCount(11), 'initial publication is missing');
      await page.getByTestId('screener-owner-refresh').click();
      await page.getByTestId('screener-refresh-status').waitFor();
      await waitUntil(() => statusHas(message), 'worker outcome message is incorrect');
      check(await hasCount(11), 'worker outcome discarded the previous result');
    });
  }

  await test('an owner readback cannot overwrite a newer filter request', async () => {
    let requests = 0;
    let releaseAction;
    const actionHeld = new Promise(resolve => { releaseAction = resolve; });
    await page.route('**/api/strength/scan?*', route => {
      const request = ++requests;
      return route.fulfill({json:publication(request === 1 ? 'P1' : request === 2 ? 'P3' : 'P2',request === 1 ? 11 : request === 2 ? 33 : 22)});
    });
    await routeAction(action('published'), actionHeld);
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await page.getByRole('tab', {name:'短期',exact:true}).click();
    await page.getByTestId('screener-apply-filters').click();
    await waitUntil(() => hasCount(33), 'new filter P3 is missing');
    releaseAction();
    await page.getByTestId('screener-refresh-status').waitFor();
    await pause(200);
    check(await hasCount(33), 'owner readback stole the later explicit filter');
  });

  await test('logout invalidates the pending owner operation', async () => {
    let signedIn = true;
    let releaseAction;
    const actionHeld = new Promise(resolve => { releaseAction = resolve; });
    await page.route('**/api/access/status', route => route.fulfill({json:{mode:'password',is_owner:signedIn,password_configured:true,account:{logged_in:false,username:null}}}));
    await page.route('**/api/access/logout', route => { signedIn = false; return route.fulfill({json:{ok:true}}); });
    await page.route('**/api/strength/scan?*', route => route.fulfill({json:publication(signedIn ? 'P1' : 'P3',signedIn ? 11 : 33)}));
    await routeAction(action('published'), actionHeld);
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await page.getByRole('button', {name:'退出 admin',exact:true}).click();
    await page.getByRole('heading', {name:'自选股',exact:true}).waitFor();
    await page.getByRole('navigation', {name:'主导航'}).getByRole('link', {name:'筛选',exact:true}).click();
    await waitUntil(() => hasCount(33), 'the new identity did not finish loading');
    releaseAction();
    await pause(250);
    check(await hasCount(33), 'old owner task affected the new identity');
    check(await page.getByTestId('screener-owner-refresh').count() === 0, 'owner control remained after logout');
    check(await page.getByTestId('screener-refresh-status').count() === 0, 'old owner status survived logout');
  });

  await test('a rejected owner update does not discard the unfinished initial query', async () => {
    let release;
    let requests = 0;
    const held = new Promise(resolve => { release = resolve; });
    await page.route('**/api/strength/scan?*', async route => {
      requests += 1;
      await held;
      await route.fulfill({json:publication('P1',11)});
    });
    await page.route('**/api/worker/actions/post_close_batch', route => route.fulfill({status:503,json:{detail:{code:'review_fixture_rejection',message:'后台任务暂时不可用'}}}));
    await enterAfterIdentity();
    await waitUntil(() => requests > 0, 'initial request did not start');
    await page.getByTestId('screener-owner-refresh').click();
    await page.getByTestId('screener-refresh-status').waitFor();
    check(!(await page.getByRole('heading', {name:'当前条件无命中',exact:true}).count()), 'an unfinished query was shown as empty');
    release();
    await waitUntil(() => hasCount(11), 'failed owner update stranded the initial result');
    check(!(await page.getByTestId('screener-reread').isDisabled()), 'reread remains disabled after initial result');
  });

  await test('rereading filters never submits a background update', async () => {
    let reads = 0;
    let writes = 0;
    await page.route('**/api/strength/scan?*', route => { reads += 1; return route.fulfill({json:publication('P1',11)}); });
    await page.route('**/api/worker/actions/post_close_batch', route => { writes += 1; return route.fulfill({status:503,json:{detail:{code:'unexpected_update'}}}); });
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-reread').click();
    await waitUntil(async () => reads >= 2 && !(await page.getByTestId('screener-reread').isDisabled()), 'reread did not finish');
    check(writes === 0, 'filter reread submitted a worker job');
    check(await page.getByTestId('screener-refresh-status').count() === 0, 'filter reread claimed an update');
  });

  await test('a failed silent verification marks old results unverified', async () => {
    let reads = 0;
    await page.route('**/api/strength/scan?*', route => {
      reads += 1;
      return reads === 1
        ? route.fulfill({json:publication('P1',11)})
        : route.fulfill({status:503,json:{detail:{code:'review_fixture_read_failure'}}});
    });
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.getByTestId('screener-unverified').waitFor();
    check(await hasCount(11), 'silent verification failure discarded old rows');
  });

  await test('a polling timeout remains running rather than reporting success', async () => {
    await page.clock.install();
    let polls = 0;
    await page.route('**/api/strength/scan?*', route => route.fulfill({json:publication('P1',11)}));
    await page.route('**/api/worker/actions/post_close_batch', route => route.fulfill({status:202,json:{action_id:9001,status:'queued'}}));
    await page.route('**/api/worker/actions/9001', route => { polls += 1; return route.fulfill({json:{status:'running'}}); });
    await enterAfterIdentity();
    await waitUntil(() => hasCount(11), 'initial publication is missing');
    await page.getByTestId('screener-owner-refresh').click();
    await waitUntil(() => polls > 0, 'worker status was not polled');
    await pause(100);
    await page.clock.fastForward(91_000);
    await page.getByTestId('screener-refresh-status').waitFor();
    await waitUntil(() => statusHas('后台任务仍在运行'), 'timeout was incorrectly treated as completion');
    check(await hasCount(11), 'timeout discarded the existing publication');
    await page.clock.setSystemTime(Date.now());
  });

  await page.unrouteAll({behavior:'ignoreErrors'});
  await page.context().tracing.stop({path:'output/pr17-finalize/screener-browser-trace.zip'});
  await page.evaluate(value => { window.__screenerBrowserResults = value; }, results);
  if (results.some(result => !result.passed)) throw new Error(JSON.stringify(results.filter(result => !result.passed)));
}
