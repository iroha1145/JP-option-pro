import test from 'node:test';
import assert from 'node:assert/strict';
import { insideZoom, zoomFromOption } from '../src/components/detail/chart-drawings/zoom.ts';
import { visibleAnalysisOverlays } from '../src/components/detail/chart-drawings/analysis/visibleOverlays.ts';
import { prepareStructuralOverlays } from '../src/components/detail/chart-drawings/analysis/structuralOverlays.ts';
import { DEFAULT_LAYER_SETTINGS, settingsFromPreset } from '../src/components/detail/chart-drawings/analysis/settings.ts';

const bars=Array.from({length:40},(_,i)=>({t:new Date(Date.UTC(2026,0,i+1)).toISOString(),
  key:new Date(Date.UTC(2026,0,i+1)).toISOString().slice(0,10),o:100,h:102,l:98,c:100,closed:true}));
const overlay=(id,kind,geometry={},sourceId='auto_patterns')=>({id,kind,geometry,sourceId,
  algorithmVersion:'fixture',group:'price',status:'forming',direction:'neutral',shapeQuality:.9,
  displayPriority:5,evidence:{},formationStart:bars[0].key,formationEnd:bars[20].key,
  dataThrough:bars.at(-1).key,label:'',detail:''});
const candidates=[overlay('server','support_trend'),overlay('local','resistance_trend',{},'local-closed-bars'),
  ...['box','swing','level','gap','pivot','candle','trap','breakout'].map(kind=>overlay(kind,kind)),
  ...[20,50,200].map(window=>overlay(`ma${window}`,'ma',{window},'indicators'))];

test('drawing switch hides annotations from both sources while retaining selected moving averages',()=>{
  assert.deepEqual(visibleAnalysisOverlays(candidates,bars,DEFAULT_LAYER_SETTINGS,false).map(o=>o.id),['ma20']);
  assert.deepEqual(visibleAnalysisOverlays(candidates,bars,settingsFromPreset('all'),false).map(o=>o.id),['ma20','ma50','ma200']);
  const original=structuredClone(candidates);
  visibleAnalysisOverlays(candidates,bars,settingsFromPreset('all'),false);
  assert.deepEqual(candidates,original);
});

const rail=overlay('resistance','resistance_trend',{anchors:[
  {barKey:bars[0].key,time:bars[0].t,price:105},
  {barKey:bars[20].key,time:bars[20].t,price:105},
]});
test('a one-session excursion and wick crossing do not become a confirmed two-close breakout',()=>{
  const input=structuredClone(bars);
  input[12]={...input[12],h:111,c:110};
  input[13]={...input[13],o:110,h:111,c:100};
  const [result]=prepareStructuralOverlays([rail],input);
  assert.equal(result.status,'forming');
  assert.equal(result.evidence.visualState,'active');
  input[39]={...input[39],h:111,c:110};
  const [pending]=prepareStructuralOverlays([rail],input);
  assert.equal(pending.status,'testing');
  assert.equal(pending.evidence.visualState,'breakout_pending');
});
test('re-enabling drawings reconciles first confirmed break before current-only filtering',()=>{
  const input=structuredClone(bars);
  for(const i of [12,13])input[i]={...input[i],h:111,c:110};
  assert.deepEqual(visibleAnalysisOverlays([rail],input,DEFAULT_LAYER_SETTINGS,true),[]);
  const historical=visibleAnalysisOverlays([rail],input,{...DEFAULT_LAYER_SETTINGS,onlyActive:false},true);
  assert.equal(historical.length,1);
  assert.equal(historical[0].status,'broken_up');
  assert.equal(historical[0].geometry.breakBarKey,input[13].key);
  assert.equal(rail.status,'forming');
});

for(const count of [20,66,80,126,132,2600])test(`${count} daily bars support wheel, drag and synchronized slider`,()=>{
  const zooms=insideZoom(count,[0,1,2,3]);
  assert.equal(zooms.length,2);
  assert.equal(zooms[0].zoomOnMouseWheel,true);
  assert.equal(zooms[0].moveOnMouseMove,true);
  for(const zoom of zooms){
    assert.deepEqual(zoom.xAxisIndex,[0,1,2,3]);
    assert.equal(zoom.startValue,Math.max(0,count-126));
    assert.equal(zoom.endValue,count-1);
    assert.equal(zoom.minValueSpan,1);
  }
});
test('minute charts initially show at most 80 bars even when history is short',()=>{
  for(const count of [2,10,80,400]){
    const [zoom]=insideZoom(count,[0,1],null,80);
    assert.equal(zoom.startValue,Math.max(0,count-80));
    assert.equal(zoom.endValue,count-1);
  }
  for(const count of [0,1,NaN,-1,2.5])assert.equal(insideZoom(count,[0]),undefined);
});
test('window survives rebuilding; only the right-edge window follows appended bars',()=>{
  const pinned={start:70,end:99,pinnedEnd:true}, history={start:20,end:49,pinnedEnd:false};
  assert.deepEqual(insideZoom(101,[0],pinned).map(z=>[z.startValue,z.endValue]),[[71,100],[71,100]]);
  assert.deepEqual(insideZoom(101,[0],history).map(z=>[z.startValue,z.endValue]),[[20,49],[20,49]]);
  assert.deepEqual(insideZoom(40,[0],history).map(z=>[z.startValue,z.endValue]),[[10,39],[10,39]]);
  assert.deepEqual(insideZoom(20,[0],pinned).map(z=>[z.startValue,z.endValue]),[[0,19],[0,19]]);
});
test('percentage-only zoom events are converted to bar indices and invalid windows are rejected',()=>{
  assert.deepEqual(zoomFromOption({dataZoom:[{start:25,end:75}]},201),{start:50,end:150,pinnedEnd:false});
  assert.deepEqual(zoomFromOption({dataZoom:[{startValue:25,endValue:200,start:0,end:100}]},201),{start:25,end:200,pinnedEnd:true});
  assert.equal(zoomFromOption({dataZoom:[{startValue:5,endValue:5}]},201),null);
  assert.equal(zoomFromOption({},201),null);
});
