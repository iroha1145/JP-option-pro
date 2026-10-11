/** Run against the locally built frontend with playwright-cli run-code --filename.
 * All API traffic is mocked; no vendor or production calls are made.
 */
/* global window, Event */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function anonymousHomeBrowser(page) {
  const origin = 'http://127.0.0.1:4317';
  const visitor = {mode:'password', is_owner:false, password_configured:true, account:{logged_in:false,username:null}};
  let identity = visitor;
  let statusCalls = 0;
  let watchCalls = 0;
  let publicCalls = 0;
  let holdStatus = null;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/access/status') {
      ++statusCalls;
      if (holdStatus) await holdStatus;
      return route.fulfill({json:identity});
    }
    if (path === '/api/watchlist') {
      ++watchCalls;
      if (!identity.account.logged_in) return route.fulfill({status:401,json:{detail:{code:'account_login_required'}}});
      return route.fulfill({json:{items:[{canonical_code:'72030',display_code:'7203',name_ja:'PRIVATE ACCOUNT A',quote:{close:1234,change_pct:1,trade_date:'2026-10-09'}}]}});
    }
    ++publicCalls;
    if (path === '/api/market/overview') return route.fulfill({json:{data_through:'2026-10-09',indices:[],sectors:[],breadth:{advancers:123,decliners:45,unchanged:6,new_highs_252:17,total_turnover_value:100000}}});
    if (path.startsWith('/api/radar/')) return route.fulfill({json:{events:[],items:[],total:0}});
    if (path.startsWith('/api/earnings/')) return route.fulfill({json:{items:[]}});
    return route.fulfill({json:{items:[],indices:[]}});
  });
  await page.goto(origin);
  await page.getByText('登录后可以把关注股票保存在账号里', {exact:true}).waitFor();
  await page.getByText('123', {exact:true}).waitFor();
  check(watchCalls === 0, 'anonymous home must not request watchlist');
  const initialStatus = statusCalls;
  const initialPublic = publicCalls;
  await page.evaluate(() => { for(let i=0;i<12;i++) window.dispatchEvent(new Event('optixjp:principal-invalid')); });
  await page.waitForTimeout(500);
  check(statusCalls === initialStatus, 'known visitor 401 events must not recheck identity');
  check(publicCalls === initialPublic, 'known visitor 401 events must not remount public cards');
  for (const path of ['/watchlist', '/radar', '/']) {
    await page.goto(origin+path);
    await page.waitForTimeout(350);
  }
  check(watchCalls === 0, 'anonymous watchlist and radar must not request protected watchlist');
  identity = {...visitor,account:{logged_in:true,username:'account-a'}};
  await page.goto(origin);
  await page.getByText('PRIVATE ACCOUNT A', {exact:true}).waitFor();
  const beforeExpiry = statusCalls;
  let release;
  holdStatus = new Promise(resolve => { release = resolve; });
  identity = visitor;
  await page.evaluate(() => { for(let i=0;i<12;i++) window.dispatchEvent(new Event('optixjp:principal-invalid')); });
  await page.getByText('PRIVATE ACCOUNT A', {exact:true}).waitFor({state:'hidden'});
  await page.waitForTimeout(200);
  check(statusCalls === beforeExpiry+1, 'concurrent expiry notifications must share one status refresh');
  release();
  holdStatus = null;
  await page.getByText('登录后可以把关注股票保存在账号里', {exact:true}).waitFor();
  await page.getByText('123', {exact:true}).waitFor();
  const settled = statusCalls;
  await page.evaluate(() => { for(let i=0;i<12;i++) window.dispatchEvent(new Event('optixjp:principal-invalid')); });
  await page.waitForTimeout(300);
  check(statusCalls === settled, 'expired session must settle as visitor without another loop');
  check(await page.getByText('PRIVATE ACCOUNT A', {exact:true}).count() === 0, 'private account data must be removed');
  await page.evaluate(result => { window.__anonymousHomeResults = result; }, {passed:true,statusCalls,watchCalls,publicCalls});
  await page.unrouteAll({behavior:'ignoreErrors'});
}
