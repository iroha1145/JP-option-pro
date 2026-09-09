import test from 'node:test';
import assert from 'node:assert/strict';
import { packCenteredLabels, rectanglesOverlap } from '../src/components/detail/chart-drawings/labelLayout.ts';
import { clippedLineSeries } from '../src/components/detail/chart-drawings/clippedLines.ts';
import { renderPatternInk } from '../src/components/detail/chart-drawings/linePresentation.ts';

const bounds={x:0,y:0,width:300,height:200};
const request=(id,anchorX=150,anchorY=100)=>({id,anchorX,anchorY,width:80,height:20,priority:100});
const mark=(a,b,span)=>[{coord:a,clipToPlot:true,lineStyle:{color:'#0E647F'},
  label:{show:true,formatter:'支撑',...(span?{span}:{})}}, {coord:b}];
const render=(marks,rect=bounds)=>{
  const series=clippedLineSeries(marks),context={};
  return marks.map((_,dataIndex)=>series.renderItem({dataIndex,coordSys:rect,context},{coord:p=>p}));
};
const texts=groups=>groups.flatMap(g=>g?.children.filter(c=>c.type==='text'&&!c.invisible)??[]);

test('annotation box is horizontally centered at its line anchor',()=>{
  const [p]=packCenteredLabels([request('a')],bounds);
  assert.equal(p.x+p.width/2,150);
  assert.ok(p.y+p.height<100);
});
test('collision packing keeps annotations centered and never shifts them to the price edge',()=>{
  const packed=packCenteredLabels([request('a'),request('b')],bounds);
  assert.equal(packed.length,2);
  assert.ok(packed.every(p=>p.x+p.width/2===150));
  assert.equal(rectanglesOverlap(packed[0],packed[1]),false);
  assert.deepEqual(packCenteredLabels([request('b'),request('a')],bounds),packed);
});
test('narrow views constrain labels to the plot and omit labels that cannot fit',()=>{
  const [p]=packCenteredLabels([request('a',20)],{x:4,y:4,width:92,height:160});
  assert.equal(p.x,4);
  assert.equal(packCenteredLabels([request('a')],{x:0,y:0,width:60,height:200}).length,0);
});
test('trend annotation uses the midpoint of its clipped visible segment',()=>{
  const labels=texts(render([mark([-100,160],[400,60])]));
  assert.equal(labels.length,1);
  assert.equal(labels[0].style.x,150);
});
test('panning recomputes the visible midpoint even with both original endpoints off screen',()=>{
  const line=mark([-100,160],[400,60]);
  const [label]=texts(render([line],{x:100,y:0,width:120,height:200}));
  assert.equal(label.style.x,160);
  assert.equal(label.style.text,'支撑');
});
test('solid rail and dashed continuation share one centered label and the same price text',()=>{
  const pattern={id:'line',kind:'support_trend',status:'forming',confidence:80,label:'上升支撑',observedEnds:[60]};
  const geometry={segments:[{a:{x:0,y:100},b:{x:120,y:112}}],fill:null};
  const marks=renderPatternInk(pattern,geometry,{xMin:0,xMax:180,yMin:50,yMax:200});
  assert.equal(marks.lines.length,2);
  assert.equal(marks.lines[0][0].label.show,true);
  assert.equal(marks.lines[1][0].label.show,false);
  assert.deepEqual(marks.lines[0][0].label.span,[[0,100],[168,116.8]]);
  assert.equal(marks.lines[0][0].label.formatter,'上升支撑 · 116.8');
  const before=structuredClone(marks.lines);
  const [label]=texts(render(marks.lines));
  assert.equal(label.style.x,84);
  assert.deepEqual(marks.lines,before);
});
test('label remains centered when only the dashed continuation is in view',()=>{
  const marks=[mark([0,100],[60,100],[[0,100],[180,100]]),
    [{coord:[60,100],clipToPlot:true,lineStyle:{type:'dashed'},label:{show:false}},{coord:[180,100]}]];
  const groups=render(marks,{x:100,y:0,width:100,height:200});
  assert.equal(groups[0].children[0].invisible,true);
  const labels=texts(groups);
  assert.equal(labels.length,1);
  assert.equal(labels[0].style.x,140);
});
test('fully off-screen lines produce no floating annotations',()=>{
  assert.equal(texts(render([mark([-150,100],[-50,100])])).length,0);
});
