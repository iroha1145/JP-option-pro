import test from 'node:test';
import assert from 'node:assert/strict';
import { codesMatch, pickQuoteForCode } from '../src/lib/securityIdentity.ts';
import { interpretOwnerRefresh } from '../src/components/screener/freshness.ts';

for (const [a,b,expected] of [
 ['130A','130A0',true],['130A','130B',false],['130A0','130B0',false],
 ['7203','72030',true],['7203','72031',false],[' 130a.T ','130A0',true],
 ['junk7203','7203',false],['','',false],
]) test(`security identity ${a} / ${b}`,()=>assert.equal(codesMatch(a,b),expected));
test('quotes never borrowed from another letter-code',()=>assert.equal(pickQuoteForCode({'130B0': {price:200}},'130A0'),null));
const promise={publicationId:'P2',outcome:'published',tradeDate:'2026-09-08',scoreVersion:'v1',freshness:null};
const response={publication_id:'P2',trade_date:'2026-09-08',input_data_through:'2026-09-08',stored_score_version:'v1',freshness:'current'};
function verdict(promised=promise,readback=response,status='completed',previous='P0') {
 return interpretOwnerRefresh({actionStatus:status,timedOut:false,promised,readback,previousPublicationId:previous});
}
for(const freshness of ['stale','partial','unknown','degraded','incompatible']) test(`published ${freshness} is not current success`,()=>assert.notEqual(verdict(promise,{...response,freshness}).state,'done'));
test('a running action with a receipt is not terminal success',()=>assert.notEqual(verdict(promise,response,'running').state,'done'));
test('missing read-back version cannot certify a promised version',()=>assert.notEqual(verdict(promise,{...response,stored_score_version:null}).state,'done'));
test('already-current with wrong version cannot certify success',()=>assert.notEqual(verdict({...promise,outcome:'already_current'},{...response,stored_score_version:'v0'}).state,'done'));
test('matching receipt already observed by an automatic query remains valid',()=>assert.equal(verdict(promise,response,'completed','P2').state,'done'));
