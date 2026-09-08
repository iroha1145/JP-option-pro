/**
 * Run through Playwright CLI against an isolated fixture API and the separate
 * tests/support/synthetic_worker.py process. Before running, change one valid
 * daily input through CoreRepository without rebuilding the publication.
 * This test does not intercept any request: the browser click must enqueue a
 * real worker action and read back the exact publication that it promised.
 */
/* global location, window */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function screenerWorkerBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  await page.unrouteAll({behavior:'ignoreErrors'});
  await page.context().tracing.start({screenshots:true,snapshots:true,sources:true});
  await page.goto(`${origin}/screener`);
  await page.getByTestId('screener-owner-refresh').waitFor();
  const before = await (await page.request.get(`${origin}/api/strength/scan?top=20`)).json();
  await page.getByRole('heading', {name:`命中 ${before.matched_count} 只`,exact:true}).waitFor();
  const acceptedResponse = page.waitForResponse(response =>
    response.url().endsWith('/api/worker/actions/post_close_batch') && response.request().method() === 'POST');
  await page.getByTestId('screener-owner-refresh').click();
  const accepted = await (await acceptedResponse).json();
  if (typeof accepted.action_id !== 'number') throw new Error('No queued action id');
  await page.getByTestId('screener-refresh-status').waitFor({timeout:30_000});
  const message = await page.getByTestId('screener-refresh-status').textContent();
  const finished = await (await page.request.get(`${origin}/api/worker/actions/${accepted.action_id}`)).json();
  const after = await (await page.request.get(`${origin}/api/strength/scan?top=20`)).json();
  const promised = finished.result?.radar?.publication;
  const result = {
    actionId:accepted.action_id,actionStatus:finished.status,outcome:finished.result?.outcome,
    before:before.publication_id,promised:promised?.publication_id,after:after.publication_id,
    tradeDate:after.trade_date,freshness:after.freshness,message,
  };
  await page.evaluate(value => {window.__realWorkerResult=value;},result);
  await page.screenshot({path:'output/pr17-finalize/real-worker-published.png',fullPage:true});
  await page.context().tracing.stop({path:'output/pr17-finalize/real-worker-trace.zip'});
  if (finished.status !== 'completed' || result.outcome !== 'published') throw new Error(JSON.stringify(result));
  if (!result.after || result.after !== result.promised || result.after === result.before) throw new Error(JSON.stringify(result));
  if (!message.includes('日线与评分已更新')) throw new Error(JSON.stringify(result));
}
