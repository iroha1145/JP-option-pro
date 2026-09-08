"""Real Chromium interactions. Each case records a trace and sanitized receipts.

`test_owner_pipeline*` and failure recovery use the actual HTTP/queue/worker/
J-Quants mapping pipeline. Other cases deliberately intercept selected HTTP
responses to control UI races; they are NOT claimed as provider integrations.
"""
import asyncio
import json
from urllib.parse import urlparse

import httpx
import pytest
from playwright.async_api import async_playwright, expect


class Browser:
    def __init__(self, service, width=1440, language='zh'):
        self.service=service; self.width=width; self.language=language
        self.errors=[]; self.requests=[]; self.blocked=[]
    async def __aenter__(self):
        self.pw=await async_playwright().start()
        self.browser=await self.pw.chromium.launch()
        self.context=await self.browser.new_context(viewport={'width':self.width,'height':1000},
                                                  locale='zh-CN',reduced_motion='reduce')
        await self.context.add_init_script(f"localStorage.setItem('optixjp:locale', {json.dumps(self.language)})")
        async def isolate(route):
            host=urlparse(route.request.url).hostname
            if host not in ('127.0.0.1','localhost','::1'):
                self.blocked.append(route.request.url)
                await route.abort()
            else: await route.continue_()
        await self.context.route('**/*',isolate)
        await self.context.tracing.start(screenshots=True,snapshots=True,sources=True)
        self.page=await self.context.new_page()
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('response',lambda response:self.requests.append({'url':urlparse(response.url).path,
                                                                      'status':response.status}))
        return self
    async def __aexit__(self,typ,error,tb):
        out=self.service['evidence']
        await self.page.screenshot(path=str(out/'final.png'),full_page=True)
        await self.context.tracing.stop(path=str(out/'trace.zip'))
        (out/'requests.json').write_text(json.dumps({'responses':self.requests,'page_errors':self.errors,
                                                    'blocked_external':self.blocked},indent=2))
        await self.browser.close(); await self.pw.stop()
        if typ is None:
            assert not self.errors, self.errors
            assert not self.blocked, self.blocked
    async def go(self,path='/screener'):
        await self.page.goto(self.service['base']+path)
        if path=='/screener':
            await expect(self.page.get_by_test_id('screener-apply-filters')).to_be_enabled()
            await expect(self.page.get_by_test_id('screener-results')).to_have_attribute('data-publication-id',self.service['before']['publication']['publication_id'])
        return self.page


def readback(service):
    return httpx.get(service['base']+'/api/strength/scan?top=20',timeout=10).json()


@pytest.mark.parametrize('width',[1440,390])
def test_owner_pipeline_changes_real_publication(services,width):
    async def run():
        async with Browser(services,width) as b:
            page=await b.go(); before=readback(services)
            assert before['trade_date']=='2026-09-07'
            async with page.expect_response(lambda r:'/api/worker/actions/post_close_batch' in r.url and r.request.method=='POST') as response:
                await page.get_by_test_id('screener-owner-refresh').click()
            accepted=await (await response.value).json()
            status=page.get_by_test_id('screener-refresh-status')
            await expect(status).to_have_attribute('data-state','done',timeout=25000)
            await expect(status).to_contain_text('日线与评分已更新')
            after=readback(services)
            receipt=httpx.get(services['base']+f"/api/worker/actions/{accepted['action_id']}",timeout=5).json()
            promised=receipt['result']['radar']['publication']
            assert after['publication_id']==promised['publication_id']!=before['publication_id']
            assert after['trade_date']=='2026-09-08' and after['freshness']=='current'
            assert after['rows'] and any(row['close']!=before['rows'][0]['close'] for row in after['rows'])
            await expect(page.get_by_test_id('screener-results')).to_have_attribute('data-publication-id',after['publication_id'])
            (services['evidence']/'publication.json').write_text(json.dumps({'before':before,'after':after,'action':receipt},ensure_ascii=False,indent=2))
            # Exactly identical source input is verified, not fabricated as a new calculation.
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(status).to_contain_text('已是最新可用日线',timeout=25000)
            assert readback(services)['publication_id']==after['publication_id']
    asyncio.run(run())


@pytest.mark.parametrize('failure,state',[('fail','error'),('wait','waiting')])
def test_provider_failure_then_recovery(services,failure,state):
    services['mode'].write_text(failure)
    async def run():
        async with Browser(services) as b:
            page=await b.go(); old=readback(services)['publication_id']
            await page.get_by_test_id('screener-owner-refresh').click()
            status=page.get_by_test_id('screener-refresh-status')
            await expect(status).to_have_attribute('data-state',state,timeout=25000)
            assert readback(services)['publication_id']==old
            await expect(page.get_by_test_id('screener-results')).to_have_attribute('data-publication-id',old)
            services['mode'].write_text('ok')
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(status).to_have_attribute('data-state','done',timeout=25000)
            assert readback(services)['trade_date']=='2026-09-08'
            assert readback(services)['publication_id']!=old
    asyncio.run(run())


async def fake_action(page,base,*,outcome='published',receipt='pub_new',state='completed'):
    calls=[]
    async def route_action(route):
        calls.append(route.request.url)
        if route.request.method=='POST':
            await route.fulfill(status=202,json={'action_id':900,'status':'queued','accepted':True})
        else:
            await route.fulfill(json={'action_id':900,'status':state,'result':{'outcome':outcome,'radar':{
                'publication':{'publication_id':receipt,'trade_date':'2026-09-08','score_version':'jp-strength-v1'}}}})
    await page.route('**/api/worker/actions/**',route_action)
    return calls


@pytest.mark.parametrize('freshness',['stale','partial','unknown','degraded','incompatible'])
def test_matching_receipt_does_not_hide_bad_quality(services,freshness):
    async def run():
        async with Browser(services) as b:
            page=await b.go(); payload=readback(services)
            payload.update(publication_id='pub_new',trade_date='2026-09-08',freshness=freshness)
            await fake_action(page,services['base'])
            await page.route('**/api/strength/scan?**',lambda route:route.fulfill(json=payload))
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(page.get_by_test_id('screener-refresh-status')).to_have_attribute('data-state','waiting')
            assert '日线与评分已更新' not in await page.get_by_test_id('screener-refresh-status').inner_text()
    asyncio.run(run())


def test_wrong_receipt_never_succeeds(services):
    async def run():
        async with Browser(services) as b:
            page=await b.go(); payload=readback(services)
            payload.update(publication_id='pub_intermediate',trade_date='2026-09-08',freshness='current')
            await fake_action(page,services['base'])
            await page.route('**/api/strength/scan?**',lambda route:route.fulfill(json=payload))
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(page.get_by_test_id('screener-refresh-status')).to_have_attribute('data-state','error',timeout=10000)
    asyncio.run(run())


def test_timeout_can_resume_without_submitting_another_action(services):
    async def run():
        async with Browser(services) as b:
            page=await b.go(); await page.clock.install()
            calls=await fake_action(page,services['base'],state='running')
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(page.get_by_test_id('screener-owner-refresh')).to_be_disabled()
            await page.clock.fast_forward(91000)
            await expect(page.get_by_test_id('screener-refresh-status')).to_have_attribute('data-state','running',timeout=8000)
            await expect(page.get_by_test_id('screener-owner-refresh')).to_be_enabled()
            before=len([c for c in calls if c.endswith('post_close_batch')])
            await page.get_by_test_id('screener-owner-refresh').click()
            await page.clock.fast_forward(91000)
            await expect(page.get_by_test_id('screener-owner-refresh')).to_be_enabled(timeout=8000)
            assert len([c for c in calls if c.endswith('post_close_batch')])==before==1
    asyncio.run(run())


def test_owner_refresh_preserves_new_filter_and_draft(services):
    async def run():
        async with Browser(services) as b:
            page=await b.go(); gate=asyncio.Event(); requested=asyncio.Event()
            payload=readback(services); payload.update(publication_id='pub_new',trade_date='2026-09-08',input_data_through='2026-09-08',freshness='current')
            async def action(route):
                if route.request.method=='POST': await route.fulfill(status=202,json={'action_id':900,'accepted':True})
                else:
                    requested.set(); await gate.wait()
                    await route.fulfill(json={'status':'completed','result':{'outcome':'published','radar':{'publication':{
                        'publication_id':'pub_new','trade_date':'2026-09-08','score_version':'jp-strength-v1'}}}})
            await page.route('**/api/worker/actions/**',action)
            await page.route('**/api/strength/scan?**',lambda route:route.fulfill(json=payload))
            await page.get_by_test_id('screener-owner-refresh').click()
            await asyncio.wait_for(requested.wait(),5)
            await page.get_by_role('tab',name='进取',exact=True).click()
            await page.get_by_test_id('screener-apply-filters').click()
            await expect(page.get_by_test_id('screener-results')).to_have_attribute('data-applied-profile','aggressive')
            # Leave a new unsubmitted draft while owner verification finishes.
            await page.get_by_role('tab',name='稳健',exact=True).click()
            gate.set()
            await expect(page.get_by_test_id('screener-refresh-status')).to_have_attribute('data-state','done')
            await expect(page.get_by_test_id('screener-results')).to_have_attribute('data-applied-profile','aggressive')
            await expect(page.get_by_role('tab',name='稳健',exact=True)).to_have_attribute('aria-selected','true')
    asyncio.run(run())


def test_late_automatic_read_cannot_roll_back_owner_publication(services):
    async def run():
        async with Browser(services) as b:
            page=await b.go(); old=readback(services); gate=asyncio.Event(); requested=asyncio.Event(); n=0
            new={**old,'publication_id':'pub_new','trade_date':'2026-09-08','input_data_through':'2026-09-08','freshness':'current'}
            async def scans(route):
                nonlocal n
                n+=1
                if n==1:
                    requested.set(); await gate.wait(); await route.fulfill(json=old)
                else: await route.fulfill(json=new)
            await page.route('**/api/strength/scan?**',scans)
            await fake_action(page,services['base'])
            await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            await asyncio.wait_for(requested.wait(),5)
            await page.get_by_test_id('screener-owner-refresh').click()
            await expect(page.get_by_test_id('screener-refresh-status')).to_have_attribute('data-state','done')
            gate.set(); await page.wait_for_timeout(150)
            await expect(page.get_by_test_id('screener-results')).to_have_attribute('data-publication-id','pub_new')
    asyncio.run(run())


@pytest.mark.parametrize('language',['zh','ja','en'])
@pytest.mark.parametrize('width',[1440,390])
def test_all_routes_and_home_alias(services,language,width):
    async def run():
        async with Browser(services,width,language) as b:
            page=b.page
            paths=['/home','/market','/radar','/screener','/watchlist','/earnings','/news','/short-monitor','/data-status','/research','/stock/285A']
            results=[]
            for index,path in enumerate(paths):
                await page.goto(services['base']+path)
                await expect(page.locator('main')).to_be_visible()
                # Wait for lazy route content, not an arbitrary network-idle interval.
                await expect(page.locator('main h1').first).to_be_visible(timeout=10000) if path!='/stock/285A' else await expect(page.locator('h1').first).to_be_visible()
                if path=='/home': assert urlparse(page.url).path=='/'
                overflow=await page.evaluate('document.documentElement.scrollWidth>window.innerWidth+2')
                results.append({'path':path,'horizontal_overflow':overflow})
                assert not overflow, path
                await page.screenshot(path=str(services['evidence']/f'route-{index:02d}.png'),full_page=True)
            (services['evidence']/'routes.json').write_text(json.dumps(results,indent=2))
    asyncio.run(run())


@pytest.mark.parametrize('failed_chart',[False,True])
def test_spa_stock_transition_never_reuses_other_letter_code(services,failed_chart):
    """Actual React route transition; selected quote/chart responses are controlled."""
    template=httpx.get(services['base']+'/api/stocks/285A',timeout=10).json()
    chart_template=httpx.get(services['base']+'/api/stocks/285A/chart?range=1y',timeout=10).json()
    async def run():
        async with Browser(services) as b:
            page=b.page; gate=asyncio.Event()
            async def stocks(route):
                path=urlparse(route.request.url).path
                code='130B' if '/130B' in path else '130A'
                if '/chart' in path:
                    if code=='130B':
                        await gate.wait()
                        if failed_chart:
                            await route.fulfill(status=503,json={'detail':{'code':'fixture_chart_failed'}})
                            return
                    price=1111 if code=='130A' else 8001
                    bars=[{**bar,'open':price,'high':price+10,'low':price-10,'close':price,
                           'adj_open':price,'adj_high':price+10,'adj_low':price-10,'adj_close':price}
                          for bar in chart_template['bars']]
                    await route.fulfill(json={**chart_template,'canonical_code':code+'0','bars':bars})
                else:
                    await route.fulfill(json={**template,
                        'security':{**template['security'],'canonical_code':code+'0','display_code':code},
                        'quote':{**template['quote'],'close':1111 if code=='130A' else 8001}})
            async def quotes(route):
                # A deliberately returned for a B request must not be borrowed by B.
                await route.fulfill(json={'enabled':True,'quotes':{'130A0':{
                    'canonical_code':'130A0','price':9998,'change_pct':.01}},'source':'fixture'})
            await page.route('**/api/stocks/130*',stocks)
            await page.route('**/api/stocks/130*/**',stocks)
            await page.route('**/api/quotes/intraday?**',quotes)
            await page.goto(services['base']+'/stock/130A')
            await expect(page.locator('h1').first).to_contain_text('130A')
            key=page.locator('section').filter(has=page.get_by_text('KEY STATS',exact=True))
            await expect(key).to_contain_text('1,111')
            await page.evaluate("history.pushState({},'', '/stock/130B'); dispatchEvent(new PopStateEvent('popstate'))")
            await expect(page.locator('h1').first).to_contain_text('130B')
            await expect(key).to_contain_text('8,001')
            assert '1,111' not in await key.inner_text()
            assert '9,998' not in await page.locator('main').inner_text()
            gate.set()
            if not failed_chart:
                await expect(key).to_contain_text('8,011')
            else:
                await page.wait_for_timeout(150)
            assert '1,111' not in await key.inner_text()
            assert '9,998' not in await page.locator('main').inner_text()
    asyncio.run(run())
